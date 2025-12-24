import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# .env 파일을 읽어옵니다.
load_dotenv()

SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL")

# DB 연결 엔진 생성
# pool_recycle은 연결 유지 시간을 설정합니다 (MySQL 기본 연결 끊김 방지)
engine = create_engine(SQLALCHEMY_DATABASE_URL, pool_recycle=3600)

# DB와 대화하는 세션 생성기
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 모든 모델(테이블)의 부모 클래스
Base = declarative_base()

# API에서 DB 세션이 필요할 때 호출할 함수
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()