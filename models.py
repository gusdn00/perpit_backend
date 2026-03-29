from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, PrimaryKeyConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base
import datetime

# 1. User 테이블: 토큰 잔액 및 소셜 로그인 필드 추가
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(16), unique=True, index=True, nullable=False)
    password = Column(String(255), nullable=False)
    name = Column(String(30))
    email = Column(String(100), unique=True, nullable=False)
    
    # [추가] 토큰 및 소셜 로그인 관련
    token_balance = Column(Integer, default=0, nullable=False) # 현재 보유 토큰
    social_provider = Column(String(20), default="local") # local, google, kakao
    social_id = Column(String(255), unique=True, nullable=True) # 소셜 고유 ID
    
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # 관계 설정 (선택 사항: 유저 객체에서 결제/토큰 내역 바로 접근 가능)
    payments = relationship("KakaoPayPayment", back_populates="user")
    token_transactions = relationship("TokenTransaction", back_populates="user")

# 2. [신규] 카카오페이 결제 테이블 (API 파라미터 1:1 매칭)
class KakaoPayPayment(Base):
    __tablename__ = "kakao_pay_payments"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # 결제 준비(Ready) 데이터
    cid = Column(String(20), default="TC0ONETIME") # 가맹점 코드
    partner_order_id = Column(String(100), unique=True, index=True, nullable=False) # 서버 주문번호
    partner_user_id = Column(String(100), nullable=False) # 서버 유저ID
    item_name = Column(String(100)) # 상품명
    quantity = Column(Integer, default=1)
    total_amount = Column(Integer, nullable=False) # 결제 금액
    tax_free_amount = Column(Integer, default=0) # 비과세
    
    # 카카오 응답 데이터 (중요)
    tid = Column(String(50), unique=True, index=True, nullable=True) # 결제 고유 번호 (Ready 응답 시 저장)
    next_redirect_pc_url = Column(String(500), nullable=True)
    next_redirect_mobile_url = Column(String(500), nullable=True)
    
    # 결제 승인(Approve) 데이터
    pg_token = Column(String(255), nullable=True) # 리다이렉트 시 받음
    approved_at = Column(DateTime, nullable=True) # 최종 승인 시각
    
    status = Column(String(20), default="READY") # READY, APPROVED, CANCELED, FAILED
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # 관계 설정
    user = relationship("User", back_populates="payments")
    token_transaction = relationship("TokenTransaction", back_populates="payment", uselist=False)

# 3. [신규] 토큰 변동 내역 테이블
class TokenTransaction(Base):
    __tablename__ = "token_transactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    amount = Column(Integer, nullable=False) # 변동량 (+충전, -사용)
    transaction_type = Column(String(20), nullable=False) # CHARGE, GENERATION, PURCHASE
    
    # 충전일 경우 결제 내역과 연결 (nullable=True: 악보 생성 소모 시엔 결제ID 없음)
    payment_id = Column(Integer, ForeignKey("kakao_pay_payments.id"), nullable=True)
    
    description = Column(String(255)) # 상세 내용
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # 관계 설정
    user = relationship("User", back_populates="token_transactions")
    payment = relationship("KakaoPayPayment", back_populates="token_transaction")

# 4. 기존 테이블 (유지)
class Sheet(Base):
    __tablename__ = "sheets"
    sid = Column(Integer, primary_key=True, index=True)
    job_id = Column(String(100), unique=True, index=True)
    title = Column(String(50), nullable=False)
    file_path = Column(String(255))
    purpose = Column(Integer)     # 1: 반주용, 2: 연주용
    style = Column(Integer)       # 1: 락, 2: 발라드, 3: 오리지널
    difficulty = Column(Integer)  # 1: Easy, 2: Normal
    instrument = Column(Integer, nullable=True)  # 1: 피아노, 2: 기타
    creator_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class MySheet(Base):
    __tablename__ = "my_sheets"
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    sheet_sid = Column(Integer, ForeignKey("sheets.sid"), nullable=False)
    saved_at = Column(DateTime, default=datetime.datetime.utcnow)

    __table_args__ = (
        PrimaryKeyConstraint('user_id', 'sheet_sid'),
    )

class MusicJob(Base):
    __tablename__ = "music_jobs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(50), index=True) # 주의: 여기는 users.id(Integer)가 아니라 user_id(String)을 쓰시는군요 (유지)
    job_id = Column(String(100), unique=True, index=True)
    title = Column(String(50))
    
    original_s3_path = Column(String(500)) 
    result_s3_path = Column(String(500), nullable=True) 
    
    status = Column(String(20), default="pending") 
    created_at = Column(DateTime(timezone=True), server_default=func.now())