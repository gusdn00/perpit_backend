import os
import uuid
import boto3
import datetime
import httpx
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, Response
from sqlalchemy.orm import Session
from database import get_db
from core.security import get_current_user  # 이전에 만든 토큰 검증 함수
from dotenv import load_dotenv
from models import MusicJob, Sheet, User, MySheet

load_dotenv()

router = APIRouter(prefix="/create_sheets", tags=["She  ets"])
AI_SERVER_URL = "http://127.0.0.1:5001/create_sheets/ai"

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
    title: str = Form(..., min_length=1, max_length=50), # 제목 길이 제한
    purpose: int = Form(..., ge=1, le=2),   # 1 이상(ge), 2 이하(le)
    style: int = Form(..., ge=1, le=3),     # 1 이상, 3 이하
    difficulty: int = Form(..., ge=1, le=2), # 1 이상, 2 이하
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    # 1. 파일 확장자 검사
    allowed_extensions = [".mp3", ".wav"]
    file_ext = os.path.splitext(file.filename)[1].lower()
    if file_ext not in allowed_extensions:
        raise HTTPException(status_code=400, detail="지원하지 않는 파일 형식입니다. (.mp3, .wav만 가능)")

    # 2. 고유한 작업 ID(jobID) 생성
    job_id = str(uuid.uuid4())
    user_record = db.query(User).filter(User.user_id == current_user["user_id"]).first()
   
    # [중요] 파일 내용을 메모리에 먼저 읽기 (AI 전송 및 S3 업로드 양쪽에서 사용)
    file_content = await file.read()
   
    # 3. AI 서버로 우선 전송 (S3 업로드보다 먼저 실행)
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
            # AI 서버에 요청을 던짐 (비동기)
            response = await client.post(AI_SERVER_URL, data=ai_data, files=ai_files, timeout=60.0)
        # [수정 3] AI 서버의 응답 상태를 체크합니다.
            response.raise_for_status() 
            print(f"AI 서버 전송 성공: {response.status_code}")

        except httpx.HTTPStatusError as e:
            print(f"AI 서버가 에러를 반환함: {e.response.status_code} - {e.response.text}")
        except Exception as e:
            print(f"AI 서버 통신 중 알 수 없는 에러 발생: {e}")
            # AI 서버 전송에 실패해도 S3 업로드와 DB 저장은 계속 진행합니다.
   
    # S3에 저장될 경로 설정 (예: uploads/uuid_파일명.mp3)
    s3_file_path = f"uploads/{job_id}_{file.filename}"

    try:
        # 3. S3에 파일 업로드
        # file.file은 실제 파일 객체입니다.
        s3_client.put_object(
            Bucket=BUCKET_NAME,
            Key=s3_file_path,
            Body=file_content,  # await file.read()로 읽어둔 데이터를 직접 넣습니다.
            ContentType=file.content_type
        )
    except Exception as e:
        print(f"S3 업로드 에러: {e}")
        raise HTTPException(status_code=500, detail="파일 업로드 중 서버 오류가 발생했습니다.")

    # 4. DB에 작업 기록 남기기
    try:
        new_job = MusicJob(
            user_id=current_user["user_id"],      # security.py에서 반환한 dict의 키값
            job_id=job_id,                       # 위에서 생성한 고유 ID
            title=title,                         # 사용자가 입력한 제목
            original_s3_path=f"s3://{BUCKET_NAME}/{s3_file_path}", # 원본 파일 주소
            status="pending"                     # 초기 상태값 설정
        )
        db.add(new_job)
        
        new_sheet = Sheet(
            job_id=job_id,
            title=title,
            file_path=None,  # 아직 결과가 없으므로 NULL
            purpose=purpose,
            style=style,
            difficulty=difficulty,
            creator_id=user_record.id, # 조회한 유저의 Integer PK값
            created_at=datetime.datetime.utcnow()
        )
        db.add(new_sheet)

        db.commit()   # DB 저장 확정
        db.refresh(new_job)
    except Exception as e:
        print(f"DB 기록 에러: {e}")
        # S3 업로드는 성공했으나 DB 기록에 실패한 경우
        raise HTTPException(status_code=500, detail="데이터베이스 기록 중 오류가 발생했습니다.")

    return {
        "jobId": job_id,
        "message": "악보 생성 작업이 시작되었습 니다."
    }

@router.get("/mysheets", status_code=200)
async def get_my_sheets(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    명세서 규격 + 1분 유효 보안 링크 적용
    """
    try:
        # 1. 유저의 정수 PK(id) 조회
        user_record = db.query(User).filter(User.user_id == current_user["user_id"]).first()
        if not user_record:
            raise HTTPException(status_code=404, detail="유저 정보를 찾을 수 없습니다.")
        
        # 2. MySheet와 Sheet 조인 조회
        results = db.query(Sheet).join(MySheet).filter(MySheet.user_id == user_record.id).all()

        # 3. 데이터 가공 및 Presigned URL 생성
        data = []
        for s in results:
            # S3에서 1분짜리 임시 링크 생성
            try:
                # s.file_path가 null일 경우를 대비
                if s.file_path:
                    object_key = s.file_path.split(f"{BUCKET_NAME}.s3.amazonaws.com/")[1]
                    link = s3_client.generate_presigned_url(
                        'get_object',
                        Params={
                            'Bucket': BUCKET_NAME,
                            'Key': object_key,
                            'ResponseContentDisposition': f'attachment; filename="{s.title}.musicxml"'
                        },
                        ExpiresIn=300
                    )
                else:
                    link = None
            except Exception:
                link = s.file_path # 에러 시 기본 DB 경로 사용

            data.append({
                "sid": s.sid,
                "name": s.title,
                "link": link # 보안 링크 전달
            })

        return {
            "data": data,
            "meta": {
                "count": len(data)
            }
        }
    except Exception as e:
        # 에러 발생 시 로그 출력
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

    # 데이터가 없거나 결과 경로가 없는 경우 예외 처리
    if not job or not job.result_s3_path:
        raise HTTPException(status_code=404, detail="악보 데이터를 찾을 수 없습니다.")

    try:
        # 2. S3 Object Key 추출 (URL 형태에 맞춰 분리)
        # job.result_s3_path가 https://... 형식이어야 정상 작동합니다.
        object_key = job.result_s3_path.split(f"{BUCKET_NAME}.s3.amazonaws.com/")[1]
        
        # 3. S3에서 파일 내용 직접 읽기
        s3_obj = s3_client.get_object(Bucket=BUCKET_NAME, Key=object_key)
        xml_content = s3_obj['Body'].read().decode('utf-8') # 바이너리를 UTF-8 문자열로 변환

        # 4. XML 데이터 원문 반환
        # Response를 사용하면 JSON이 아닌 순수 텍스트 데이터를 보낼 수 있습니다.
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
    """
    보관함의 특정 악보(sid) XML 데이터를 서버가 S3에서 직접 읽어 반환합니다.
    CORS 문제를 해결하며 프론트엔드 OSMD 렌더링에 최적화된 방식입니다.
    """
    try:
        # 1. 현재 로그인한 유저 정보 확인
        user_record = db.query(User).filter(User.user_id == current_user["user_id"]).first()
        if not user_record:
            raise HTTPException(status_code=404, detail="유저 정보를 찾을 수 없습니다.")

        # 2. 보관함(MySheet) 권한 확인 (본인 악보인지 검증)
        my_sheet_exists = db.query(MySheet).filter(
            MySheet.user_id == user_record.id,
            MySheet.sheet_sid == sid
        ).first()

        if not my_sheet_exists:
            raise HTTPException(status_code=403, detail="해당 악보에 대한 접근 권한이 없거나 보관함에 없습니다.")

        # 3. 실제 악보(Sheet) 경로 정보 조회
        sheet = db.query(Sheet).filter(Sheet.sid == sid).first()
        if not sheet or not sheet.file_path:
            raise HTTPException(status_code=404, detail="악보 파일 정보를 찾을 수 없습니다.")

        # 4. S3에서 XML 내용 직접 읽기
        # URL에서 object_key 추출 (https://... 형태 기준)
        object_key = sheet.file_path.split(f"{BUCKET_NAME}.s3.amazonaws.com/")[1]
        
        s3_obj = s3_client.get_object(Bucket=BUCKET_NAME, Key=object_key)
        xml_content = s3_obj['Body'].read().decode('utf-8')

        # 5. XML 데이터 원문 반환
        # 프론트엔드는 이 응답을 받아 osmd.load(response.data)로 즉시 사용 가능합니다.
        return Response(content=xml_content, media_type="application/xml")

    except Exception as e:
        print(f"보관함 XML 데이터 읽기 에러 (sid: {sid}): {e}")
        raise HTTPException(status_code=500, detail="XML 데이터를 읽어오는 중 오류가 발생했습니다.")

@router.delete("/mysheets/{sid}", status_code=204)
async def delete_from_my_sheets(
    sid: int, # 삭제할 악보의 sid (Sheet 테이블의 PK)
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    내 보관함에서 특정 악보를 삭제합니다.
    """
    try:
        # 1. 현재 로그인한 유저의 숫자 ID(PK) 조회
        user_record = db.query(User).filter(User.user_id == current_user["user_id"]).first()
        if not user_record:
            raise HTTPException(status_code=404, detail="유저 정보를 찾을 수 없습니다.")

        # 2. 보관함(MySheet)에서 해당 유저의 해당 악보 기록 찾기
        my_sheet_entry = db.query(MySheet).filter(
            MySheet.user_id == user_record.id,
            MySheet.sheet_sid == sid
        ).first()

        if not my_sheet_entry:
            raise HTTPException(status_code=404, detail="보관함에 해당 악보가 존재하지 않습니다.")

        # 3. 데이터 삭제
        db.delete(my_sheet_entry)
        db.commit()

        # 204 No Content는 본문 없이 성공을 응답함
        return None

    except Exception as e:
        db.rollback()
        print(f"보관함 삭제 에러: {e}")
        raise HTTPException(status_code=500, detail="삭제 처리 중 오류가 발생했습니다.")

@router.get("/{job_id}")
async def get_sheet_detail(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    특정 작업 ID(job_id)의 상세 정보를 조회합니다.
    """
    # 1. DB에서 해당 job_id를 가진 데이터를 찾습니다.
    # 보안을 위해 현재 로그인한 유저(user_id)의 작업인지도 함께 확인합니다.
    job = db.query(MusicJob).filter(
        MusicJob.job_id == job_id,
        MusicJob.user_id == current_user["user_id"]
    ).first()

    # 2. 데이터가 없는 경우 404 에러를 반환합니다.
    if not job:
        raise HTTPException(status_code=404, detail="해당 악보 정보를 찾을 수 없습니다.")
    
    if job.status == "failed":
        raise HTTPException(status_code=404, detail="악보 생성에 실패했습니다.")

    if job.status != "completed":
        return {"status": job.status, "message": "아직 작업 중입니다."}

    try:
        # DB에 저장된 전체 URL에서 Key(파일명)만 추출합니다.
        object_key = job.result_s3_path.split(f"{BUCKET_NAME}.s3.amazonaws.com/")[1]

        presigned_url = s3_client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': BUCKET_NAME,
                'Key': object_key,
                # 다운로드 시 파일명을 예쁘게 지정하고 싶을 때 추가
                'ResponseContentDisposition': f'attachment; filename="{job.title}.musicxml"'
            },
            ExpiresIn=300
        )
    except Exception as e:
        print(f"Presigned URL 생성 에러: {e}")
        # 에러 발생 시 원래 저장된 주소라도 보냅니다.
        presigned_url = job.result_s3_path

    # 3. 요청하신 최소 응답 구조에 맞춰 데이터를 반환합니다.
    return {
        "job_id": job.job_id,
        "status": job.status,
        "title": job.title,
        "result_url": presigned_url,
        "created_at": job.created_at
    }

@router.post("/callback/ai-result")
async def receive_ai_result(
    job_id: str = Form(...),
    status: str = Form(...),           # "completed" 또는 "failed"
    xml_file: UploadFile = File(None),  # 실패 시 파일이 없을 수 있으므로 None 허용
    db: Session = Depends(get_db)
):
    """
    AI 서버로부터 악보 생성 결과(성공/실패)를 받는 엔드포인트입니다.
    """
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
            print(f"Job {job_id} 생성 실패 상태 반영 완료")
            return {"status": "success", "message": "실패 상태가 기록되었습니다."}

        # 3. 상태가 'completed'로 온 경우 처리
        if status == "completed":
            if not xml_file:
                return {"status": "error", "message": "성공 상태이지만 XML 파일이 누락되었습니다."}

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
    
@router.post("/{job_id}/add", status_code=201)
async def add_to_my_sheets(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    # 1. 문자열 ID를 가진 유저 객체를 찾습니다. (이 과정이 있어야 '숫자 ID'를 얻을 수 있습니다)
    user_record = db.query(User).filter(User.user_id == current_user["user_id"]).first()
    if not user_record:
        raise HTTPException(status_code=404, detail="유저 정보를 찾을 수 없습니다.")
    
    # 2. 해당 악보가 존재하는지 확인
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

    # 4. 보관함(MySheet)에 저장
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