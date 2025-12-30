import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# .env 파일 읽기
load_dotenv()

SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL")

# DB 연결 엔진 생성
engine = create_engine(SQLALCHEMY_DATABASE_URL, pool_recycle=3600) # 연결 유지 시간 설정

# DB와 대화하는 세션 생성기
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 모든 테이블의 부모 클래스
Base = declarative_base()

# API에서 DB 세션이 필요할 때 호출할 함수
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()