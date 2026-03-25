import os
import uuid
import boto3
import datetime
import httpx
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, Response, Body
from sqlalchemy.orm import Session
from database import get_db
from core.security import get_current_user
from dotenv import load_dotenv
from models import MusicJob, Sheet, User, MySheet, TokenTransaction
from schemas import RemixRequest

load_dotenv()

router = APIRouter(prefix="/create_sheets", tags=["Sheets"])
AI_SERVER_URL = os.getenv("AI_SERVER_URL", "http://www.perpit.kr:5001/create_sheets/ai")

# S3 클라이언트 설정
s3_client = boto3.client(
    's3',
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    region_name=os.getenv("AWS_REGION")
)

BUCKET_NAME = os.getenv("AWS_S3_BUCKET_NAME")

@router.post("", status_code=202)
async def create_sheets(
    file: UploadFile = File(...),
    title: str = Form(..., min_length=1, max_length=50), 
    purpose: int = Form(..., ge=1, le=2),  
    style: int = Form(..., ge=1, le=3),    
    difficulty: int = Form(..., ge=1, le=2), 
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    # 1. 토큰 잔액 확인 (악보 생성 1회당 3토큰 필요)
    TOKEN_COST = 3
    user_record = db.query(User).filter(User.user_id == current_user["user_id"]).first()
    if not user_record:
        raise HTTPException(status_code=404, detail="유저 정보를 찾을 수 없습니다.")
    if user_record.token_balance < TOKEN_COST:
        raise HTTPException(status_code=402, detail=f"토큰이 부족합니다. (필요: {TOKEN_COST}, 보유: {user_record.token_balance})")

    # 2. 파일 확장자 검사
    allowed_extensions = [".mp3", ".wav"]
    file_ext = os.path.splitext(file.filename)[1].lower()
    if file_ext not in allowed_extensions:
        raise HTTPException(status_code=400, detail="지원하지 않는 파일 형식입니다. (.mp3, .wav만 가능)")

    # 3. 고유한 작업 ID(jobID) 생성
    job_id = str(uuid.uuid4())

    # 파일 내용을 메모리에 먼저 읽기 (AI 전송 및 S3 업로드 양쪽에서 사용)
    file_content = await file.read()

    # 4. AI 서버로 우선 전송
    async with httpx.AsyncClient() as client:
        try:
            ai_data = {
                "job_id": job_id,
                "title": title,
                "purpose": purpose,
                "style": style,
                "difficulty": difficulty
            }
            ai_files = {
                "file": (file.filename, file_content, file.content_type)
            }
            # AI 서버에 요청 (비동기)
            response = await client.post(AI_SERVER_URL, data=ai_data, files=ai_files, timeout=60.0)
        #AI 서버의 응답 상태를 체크
            response.raise_for_status() 
            print(f"AI 서버 전송 성공: {response.status_code}")

        except httpx.HTTPStatusError as e:
            print(f"AI 서버가 에러를 반환함: {e.response.status_code} - {e.response.text}")
        except Exception as e:
            print(f"AI 서버 통신 에러 발생: {e}")
            # AI 서버 전송에 실패해도 S3 업로드와 DB 저장은 계속 진행해야함
   
    # S3에 저장될 경로 설정 (uploads/uuid_파일명.mp3 형식)
    s3_file_path = f"uploads/{job_id}_{file.filename}"

    try:
        # 5. S3에 파일 업로드
        s3_client.put_object(
            Bucket=BUCKET_NAME,
            Key=s3_file_path,
            Body=file_content,
            ContentType=file.content_type
        )
    except Exception as e:
        print(f"S3 업로드 에러: {e}")
        raise HTTPException(status_code=500, detail="파일 업로드 중 서버 오류가 발생했습니다.")

    # 6. DB에 작업 기록 남기기
    try:
        new_job = MusicJob(
            user_id=current_user["user_id"],    
            job_id=job_id,                      
            title=title,                        
            original_s3_path=f"s3://{BUCKET_NAME}/{s3_file_path}", # 원본 파일 주소
            status="pending"                  
        )
        db.add(new_job)
        
        new_sheet = Sheet(
            job_id=job_id,
            title=title,
            file_path=None,  
            purpose=purpose,
            style=style,
            difficulty=difficulty,
            creator_id=user_record.id, 
            created_at=datetime.datetime.utcnow()
        )
        db.add(new_sheet)

        # 7. 토큰 차감 및 내역 기록
        user_record.token_balance -= TOKEN_COST
        token_tx = TokenTransaction(
            user_id=user_record.id,
            amount=-TOKEN_COST,
            transaction_type="GENERATION",
            description=f"악보 생성 사용 ({title})"
        )
        db.add(token_tx)

        db.commit()
        db.refresh(new_job)
    except Exception as e:
        print(f"DB 기록 에러: {e}")
        raise HTTPException(status_code=500, detail="데이터베이스 기록 중 오류가 발생했습니다.")

    return {
        "jobId": job_id,
        "message": "악보 생성 작업이 시작되었습니다."
    }

@router.get("/mysheets", status_code=200)
async def get_my_sheets(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        # 1. 유저 id 조회
        user_record = db.query(User).filter(User.user_id == current_user["user_id"]).first()
        if not user_record:
            raise HTTPException(status_code=404, detail="유저 정보를 찾을 수 없습니다.")
        
        # 2. MySheet와 Sheet 조인 조회
        results = db.query(Sheet).join(MySheet).filter(MySheet.user_id == user_record.id).all()

        # 3. 데이터 가공 및 Presigned URL 생성
        data = []
        for s in results:
            try:
                if s.file_path:
                    object_key = s.file_path.split(f"{BUCKET_NAME}.s3.amazonaws.com/")[1]
                    link = s3_client.generate_presigned_url(
                        'get_object',
                        Params={
                            'Bucket': BUCKET_NAME,
                            'Key': object_key,
                            'ResponseContentDisposition': f'attachment; filename="{s.title}.musicxml"'
                        },
                        ExpiresIn=300 # S3 링크 유효 시간
                    )
                else:
                    link = None
            except Exception:
                link = s.file_path

            data.append({
                "sid": s.sid,
                "name": s.title,
                "link": link
            })

        return {
            "data": data,
            "meta": {
                "count": len(data)
            }
        }
    except Exception as e:
        print(f"Error in get_my_sheets: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{job_id}/view")
async def view_sheet_content(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    S3의 XML 데이터를 직접 읽어와서 반환합니다. (CORS 문제 해결)
    프론트엔드의 OSMD는 이 응답(XML 문자열)을 받아 바로 렌더링합니다.
    """
    # 1. DB에서 악보 작업 정보 조회
    job = db.query(MusicJob).filter(
        MusicJob.job_id == job_id,
        MusicJob.user_id == current_user["user_id"]
    ).first()

    # 데이터 없는 경우
    if not job or not job.result_s3_path:
        raise HTTPException(status_code=404, detail="악보 데이터를 찾을 수 없습니다.")

    try:
        # 2. S3 Object Key 추출
        object_key = job.result_s3_path.split(f"{BUCKET_NAME}.s3.amazonaws.com/")[1]
        
        # 3. S3에서 파일 내용 직접 읽기
        s3_obj = s3_client.get_object(Bucket=BUCKET_NAME, Key=object_key)
        xml_content = s3_obj['Body'].read().decode('utf-8') # UTF-8 문자열로 변환

        # 4. XML 데이터 원문 반환
        # Response로 JSON이 아닌 순수 텍스트 데이터 전달
        return Response(content=xml_content, media_type="application/xml")
        
    except Exception as e:
        print(f"View error (job_id: {job_id}): {e}")
        raise HTTPException(status_code=500, detail="XML 데이터를 읽는 중 오류가 발생했습니다.")

@router.get("/mysheets/{sid}/view")
async def view_my_sheet_individual(
    sid: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    
    try:
        # 1. 현재 로그인한 유저 정보 확인
        user_record = db.query(User).filter(User.user_id == current_user["user_id"]).first()
        if not user_record:
            raise HTTPException(status_code=404, detail="유저 정보를 찾을 수 없습니다.")

        # 2. 보관함 권한 확인 (본인 악보인지 검증)
        my_sheet_exists = db.query(MySheet).filter(
            MySheet.user_id == user_record.id,
            MySheet.sheet_sid == sid
        ).first()

        if not my_sheet_exists:
            raise HTTPException(status_code=403, detail="보관함에 없습니다.")

        # 3. 실제 악보 경로 정보 조회
        sheet = db.query(Sheet).filter(Sheet.sid == sid).first()
        if not sheet or not sheet.file_path:
            raise HTTPException(status_code=404, detail="악보 파일 정보를 찾을 수 없습니다.")

        # 4. S3에서 XML 내용 직접 읽기
        # URL에서 object_key 추출
        object_key = sheet.file_path.split(f"{BUCKET_NAME}.s3.amazonaws.com/")[1]
        
        s3_obj = s3_client.get_object(Bucket=BUCKET_NAME, Key=object_key)
        xml_content = s3_obj['Body'].read().decode('utf-8')

        # 5. XML 데이터 원문 반환
        return Response(content=xml_content, media_type="application/xml")

    except Exception as e:
        print(f"보관함 XML 데이터 읽기 에러 (sid: {sid}): {e}")
        raise HTTPException(status_code=500, detail="XML 데이터를 읽어오는 중 오류가 발생했습니다.")

@router.delete("/mysheets/{sid}", status_code=204)
async def delete_from_my_sheets(
    sid: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        # 1. 현재 로그인한 유저 id 조회
        user_record = db.query(User).filter(User.user_id == current_user["user_id"]).first()
        if not user_record:
            raise HTTPException(status_code=404, detail="유저 정보를 찾을 수 없습니다.")

        # 2. 보관함에서 해당 유저의 해당 악보 목록 찾기
        my_sheet_entry = db.query(MySheet).filter(
            MySheet.user_id == user_record.id,
            MySheet.sheet_sid == sid
        ).first()

        if not my_sheet_entry:
            raise HTTPException(status_code=404, detail="보관함에 해당 악보가 없습니다.")

        # 3. 데이터 삭제
        db.delete(my_sheet_entry)
        db.commit()

        # 204 No Content는 본문 없이 성공을 응답함
        return None

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print(f"보관함 삭제 에러: {e}")
        raise HTTPException(status_code=500, detail="삭제 처리 중 오류가 발생했습니다.")

@router.post("/callback/ai-result")
async def receive_ai_result(
    job_id: str = Form(...),
    status: str = Form(...),           # "completed" 또는 "failed"
    xml_file: UploadFile = File(None),  # 실패 시 파일이 없을 수 있으므로 None 허용
    db: Session = Depends(get_db)
):
    try:
        # 1. DB에서 해당 작업 찾기
        job = db.query(MusicJob).filter(MusicJob.job_id == job_id).first()
        sheet = db.query(Sheet).filter(Sheet.job_id == job_id).first()

        if not job:
            print(f"오류: 존재하지 않는 job_id {job_id}")
            return {"status": "error", "message": "해당 job_id를 찾을 수 없습니다."}

        # 2. 상태가 'failed'로 온 경우 처리
        if status == "failed":
            job.status = "failed"
            db.commit()
            print(f"Job {job_id} 생성 실패")
            return {"status": "success", "message": "실패 상태가 기록되었습니다."}

        # 3. 상태가 'completed'로 온 경우 처리
        if status == "completed":
            if not xml_file:
                return {"status": "error", "message": "XML 파일이 누락되었습니다."}

            # XML 파일 읽기 및 S3 저장
            xml_content = await xml_file.read()
            xml_s3_key = f"results/{job_id}_result.xml"
            
            s3_client.put_object(
                Bucket=BUCKET_NAME,
                Key=xml_s3_key,
                Body=xml_content,
                ContentType="application/xml"
            )
            
            xml_url = f"https://{BUCKET_NAME}.s3.amazonaws.com/{xml_s3_key}"

            # DB 정보 업데이트
            job.result_s3_path = xml_url
            job.status = "completed"
            
            if sheet:
                sheet.file_path = xml_url
                
            db.commit()
            print(f"Job {job_id} 완료 및 S3 업로드 성공")
            return {"status": "success", "message": "결과가 성공적으로 저장되었습니다."}

        return {"status": "error", "message": "잘못된 status 값입니다."}

    except Exception as e:
        db.rollback()
        print(f"AI 결과 수신 중 에러 발생: {e}")
        return {"status": "error", "message": str(e)}

"""
프론트에서 완성된 악보 정보 가져가는 API
프론트가 5초마다 get 요청 보냄
"""

@router.get("/{job_id}")
async def get_sheet_detail(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    # 1. DB에서 해당 job_id 작업 탐색
    job = db.query(MusicJob).filter(
        MusicJob.job_id == job_id,
        MusicJob.user_id == current_user["user_id"]
    ).first()

    # 2. 데이터가 없는 경우 에러
    if not job:
        raise HTTPException(status_code=404, detail="해당 악보 정보를 찾을 수 없습니다.")
    
    if job.status == "failed":
        raise HTTPException(status_code=404, detail="악보 생성에 실패했습니다.")

    if job.status != "completed":
        return {"status": job.status, "message": "아직 작업 중입니다."}

    try:
        # DB에 저장된 전체 URL에서 파일명만 추출
        object_key = job.result_s3_path.split(f"{BUCKET_NAME}.s3.amazonaws.com/")[1]

        presigned_url = s3_client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': BUCKET_NAME,
                'Key': object_key,
                # 파일명 정돈
                'ResponseContentDisposition': f'attachment; filename="{job.title}.musicxml"'
            },
            ExpiresIn=300 # 유효 시간
        )
    except Exception as e:
        print(f"Presigned URL 생성 에러: {e}")
        # 에러 발생 시 원래 저장된 주소 반환
        presigned_url = job.result_s3_path

    # 3. 데이터 반환
    return {
        "job_id": job.job_id,
        "status": job.status,
        "title": job.title,
        "result_url": presigned_url,
        "created_at": job.created_at
    }

@router.post("/mysheets/{sid}/remix", status_code=202)
async def remix_sheet(
    sid: int,
    request: RemixRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    REMIX_COST = 1

    # 1. 유저 확인
    user_record = db.query(User).filter(User.user_id == current_user["user_id"]).first()
    if not user_record:
        raise HTTPException(status_code=404, detail="유저 정보를 찾을 수 없습니다.")

    # 2. 보관함에 있는 악보인지 확인
    my_sheet = db.query(MySheet).filter(
        MySheet.user_id == user_record.id,
        MySheet.sheet_sid == sid
    ).first()
    if not my_sheet:
        raise HTTPException(status_code=403, detail="보관함에 없는 악보입니다.")

    # 3. 원본 악보 및 작업 정보 조회
    sheet = db.query(Sheet).filter(Sheet.sid == sid).first()
    if not sheet:
        raise HTTPException(status_code=404, detail="악보 정보를 찾을 수 없습니다.")

    original_job = db.query(MusicJob).filter(MusicJob.job_id == sheet.job_id).first()
    if not original_job or not original_job.original_s3_path:
        raise HTTPException(status_code=400, detail="원본 음원 정보를 찾을 수 없습니다.")

    # 4. 토큰 잔액 확인
    if user_record.token_balance < REMIX_COST:
        raise HTTPException(
            status_code=402,
            detail=f"토큰이 부족합니다. (필요: {REMIX_COST}, 보유: {user_record.token_balance})"
        )

    # 5. S3에서 원본 음원 다운로드
    try:
        s3_key = original_job.original_s3_path.split(f"s3://{BUCKET_NAME}/")[1]
        s3_obj = s3_client.get_object(Bucket=BUCKET_NAME, Key=s3_key)
        file_content = s3_obj['Body'].read()
        original_filename = s3_key.split("/")[-1]  # uuid_파일명.mp3 형태
    except Exception as e:
        print(f"S3 원본 음원 다운로드 에러: {e}")
        raise HTTPException(status_code=500, detail="원본 음원을 불러오는 중 오류가 발생했습니다.")

    # 6. 새 작업 ID 생성 및 제목 넘버링
    new_job_id = str(uuid.uuid4())

    # 같은 제목(원본 포함)의 악보 수를 세서 다음 번호 결정
    same_title_count = db.query(Sheet).filter(
        Sheet.creator_id == user_record.id,
        Sheet.title.like(f"{sheet.title}%")
    ).count()
    new_title = f"{sheet.title} ({same_title_count + 1})"

    # 7. AI 서버로 전송
    async with httpx.AsyncClient() as client:
        try:
            ai_data = {
                "job_id": new_job_id,
                "title": new_title,
                "purpose": request.purpose,
                "style": request.style,
                "difficulty": request.difficulty
            }
            ai_files = {
                "file": (original_filename, file_content, "audio/mpeg")
            }
            response = await client.post(AI_SERVER_URL, data=ai_data, files=ai_files, timeout=60.0)
            response.raise_for_status()
            print(f"AI 서버 리믹스 전송 성공: {response.status_code}")
        except httpx.HTTPStatusError as e:
            print(f"AI 서버가 에러를 반환함: {e.response.status_code} - {e.response.text}")
        except Exception as e:
            print(f"AI 서버 통신 에러 발생: {e}")

    # 8. DB에 새 작업 및 악보 기록, 토큰 차감
    try:
        new_job = MusicJob(
            user_id=current_user["user_id"],
            job_id=new_job_id,
            title=new_title,
            original_s3_path=original_job.original_s3_path,  # 원본 음원 재사용
            status="pending"
        )
        db.add(new_job)

        new_sheet = Sheet(
            job_id=new_job_id,
            title=new_title,
            file_path=None,
            purpose=request.purpose,
            style=request.style,
            difficulty=request.difficulty,
            creator_id=user_record.id,
            created_at=datetime.datetime.utcnow()
        )
        db.add(new_sheet)
        db.flush()  # new_sheet.sid 확보

        # 보관함에 자동 추가
        new_my_sheet = MySheet(
            user_id=user_record.id,
            sheet_sid=new_sheet.sid
        )
        db.add(new_my_sheet)

        # 토큰 차감 및 내역 기록
        user_record.token_balance -= REMIX_COST
        token_tx = TokenTransaction(
            user_id=user_record.id,
            amount=-REMIX_COST,
            transaction_type="GENERATION",
            description=f"악보 리믹스 사용 ({new_title})"
        )
        db.add(token_tx)

        db.commit()
        db.refresh(new_job)
    except Exception as e:
        db.rollback()
        print(f"DB 기록 에러: {e}")
        raise HTTPException(status_code=500, detail="데이터베이스 기록 중 오류가 발생했습니다.")

    return {
        "jobId": new_job_id,
        "message": "새로운 버전의 악보 생성이 시작되었습니다."
    }


"""
Add my sheets 기능 API
"""

@router.post("/{job_id}/add", status_code=201)
async def add_to_my_sheets(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    # 1. DB에서 user id 탐색
    user_record = db.query(User).filter(User.user_id == current_user["user_id"]).first()
    if not user_record:
        raise HTTPException(status_code=404, detail="유저 정보를 찾을 수 없습니다.")
    
    # 2. job_id에서 해당 악보 정보 확인
    sheet = db.query(Sheet).filter(Sheet.job_id == job_id).first()
    if not sheet:
        raise HTTPException(status_code=404, detail="악보를 찾을 수 없습니다.")

    # 3. 이미 보관함에 있는지 중복 확인
    existing_entry = db.query(MySheet).filter(
        MySheet.user_id == user_record.id,
        MySheet.sheet_sid == sheet.sid
    ).first()

    if existing_entry:
        return {"message": "이미 보관함에 추가된 악보입니다."}

    # 4. 보관함에 저장
    try:
        new_my_sheet = MySheet(
            user_id=user_record.id,
            sheet_sid=sheet.sid
        )
        db.add(new_my_sheet)
        db.commit()
        return {"message": "내 보관함에 성공적으로 추가되었습니다."}
    except Exception as e:
        db.rollback()
        print(f"보관함 저장 에러: {e}")
        raise HTTPException(status_code=500, detail="보관함 저장 중 오류가 발생했습니다.")