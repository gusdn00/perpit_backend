from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, PrimaryKeyConstraint
from sqlalchemy.orm import relationship
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