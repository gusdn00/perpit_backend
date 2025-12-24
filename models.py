from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, PrimaryKeyConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base
import datetime

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(16), unique=True, index=True, nullable=False)
    password = Column(String(255), nullable=False) # 해싱된 비번 저장용
    name = Column(String(30))
    email = Column(String(100), unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class Sheet(Base):
    __tablename__ = "sheets"
    sid = Column(Integer, primary_key=True, index=True)
    title = Column(String(50), nullable=False)
    file_path = Column(String(255))
    purpose = Column(Integer)  # 1: 반주용, 2: 연주용
    style = Column(Integer)    # 1: 락, 2: 발라드, 3: 오리지널
    difficulty = Column(Integer) # 1: Easy, 2: Normal
    creator_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class MySheet(Base):
    __tablename__ = "my_sheets"
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    sheet_sid = Column(Integer, ForeignKey("sheets.sid"), nullable=False)
    saved_at = Column(DateTime, default=datetime.datetime.utcnow)

    # (user_id, sheet_sid)를 복합키로 설정하여 중복 방지
    __table_args__ = (
        PrimaryKeyConstraint('user_id', 'sheet_sid'),
    )

class MusicJob(Base):
    __tablename__ = "music_jobs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(50), index=True)  # 요청한 사용자 ID
    job_id = Column(String(100), unique=True, index=True) # 고유 작업 ID
    title = Column(String(50)) # 곡 제목
    
    # AI 작업 관련 정보
    original_s3_path = Column(String(500)) # 우리가 방금 올린 .wav S3 주소
    result_s3_path = Column(String(500), nullable=True) # AI가 만든 악보 S3 주소 (처음엔 비어있음)
    
    status = Column(String(20), default="pending") # 상태 (pending/completed 등)
    # 상태 관리: 'pending' (대기), 'processing' (진행중), 'completed' (완료), 'failed' (실패)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())