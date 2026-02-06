from pydantic import BaseModel, EmailStr, Field
from typing import List, Optional
from datetime import datetime

# =========================================
# 1. 공통 응답 (Common)
# =========================================
class MessageResponse(BaseModel):
    message: str

# =========================================
# 2. 회원 인증 (Authentication)
# =========================================

# [회원가입 요청]
class UserCreate(BaseModel):
    user_id: str = Field(..., min_length=8, max_length=20, pattern="^[a-zA-Z0-9]+$")
    name: str = Field(..., min_length=2, max_length=10) # 3->2로 완화 (한국 이름 고려)
    password: str = Field(..., min_length=8, max_length=20)
    email: EmailStr

# [로컬 로그인 요청]
class UserLogin(BaseModel):
    user_id: str = Field(..., description="로그인용 아이디") # id -> user_id로 명칭 통일
    password: str

# [소셜 로그인 요청] (구글/카카오)
class SocialLoginRequest(BaseModel):
    access_token: str = Field(..., description="소셜 제공자(Google/Kakao)에게 받은 액세스 토큰")

# [로그인/회원정보 응답] (토큰 잔액 포함)
class UserResponse(BaseModel):
    id: int
    user_id: str
    name: str
    email: str
    token_balance: int # 중요: 현재 잔액 정보를 같이 줌
    social_provider: str
    
    class Config:
        from_attributes = True # ORM 객체를 Pydantic 모델로 변환 허용

# [JWT 토큰 응답]
class TokenResponse(BaseModel):
    token: str
    message: str

# =========================================
# 3. 카카오페이 결제 (Payment)
# =========================================

# [결제 준비 요청] 프론트 -> 백엔드
class PaymentReadyRequest(BaseModel):
    # item_name은 선택 사항 (안 보내면 백엔드가 '토큰 충전'으로 설정)
    item_name: Optional[str] = "토큰 충전" 
    quantity: int = Field(..., gt=0, description="충전할 토큰 수량")
    # total_amount 제거됨 (백엔드에서 계산)

# [결제 준비 응답] 백엔드 -> 프론트
class PaymentReadyResponse(BaseModel):
    tid: str
    next_redirect_pc_url: str # PC 결제창 URL
    partner_order_id: str

# [결제 승인 완료 응답]
class PaymentApproveResponse(BaseModel):
    message: str
    current_balance: int # 갱신된 잔액
    payment_date: datetime

# =========================================
# 4. 토큰 관리 (Token)
# =========================================

# [단일 트랜잭션 내역]
class TokenTransactionSchema(BaseModel):
    id: int
    amount: int
    transaction_type: str # CHARGE, GENERATION, PURCHASE
    description: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True

# [토큰 내역 목록 응답]
class TokenHistoryResponse(BaseModel):
    total_count: int
    data: List[TokenTransactionSchema]

# =========================================
# 5. 악보 생성 (Sheet Generation)
# =========================================
# 기존에 있던 기능이지만 토큰 로직에 맞춰 리팩토링 필요 시 참고

class SheetCreateResponse(BaseModel):
    job_id: str
    message: str