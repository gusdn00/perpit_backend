import os
import uuid
import boto3
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from core.security import get_current_user  # 이전에 만든 토큰 검증 함수
from dotenv import load_dotenv
from models import MusicJob

load_dotenv()

router = APIRouter(prefix="/create_sheets", tags=["Sheets"])

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
    # S3에 저장될 경로 설정 (예: uploads/uuid_파일명.mp3)
    s3_file_path = f"uploads/{job_id}_{file.filename}"

    try:
        # 3. S3에 파일 업로드
        # file.file은 실제 파일 객체입니다.
        s3_client.upload_fileobj(
            file.file,
            BUCKET_NAME,
            s3_file_path,
            ExtraArgs={'ContentType': file.content_type}
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
        db.commit()   # DB 저장 확정
        db.refresh(new_job)
    except Exception as e:
        print(f"DB 기록 에러: {e}")
        # S3 업로드는 성공했으나 DB 기록에 실패한 경우
        raise HTTPException(status_code=500, detail="데이터베이스 기록 중 오류가 발생했습니다.")

    return {
        "jobId": job_id,
        "message": "악보 생성 작업이 시작되었습니다."
    }

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

    # 3. 요청하신 최소 응답 구조에 맞춰 데이터를 반환합니다.
    return {
        "job_id": job.job_id,
        "status": job.status,
        "title": job.title,
        "result_url": job.result_s3_path, # AI가 생성해 넣은 S3 주소
        "created_at": job.created_at
    }