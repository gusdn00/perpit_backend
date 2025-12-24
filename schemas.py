from pydantic import BaseModel, EmailStr, Field

# 회원가입 요청 (POST /signup)
class UserCreate(BaseModel):
    user_id: str = Field(..., min_length=8, max_length=16, pattern="^[a-zA-Z0-9]+$")
    name: str = Field(..., min_length=3, max_length=30)
    password: str = Field(..., min_length=8, max_length=16)
    email: EmailStr

# 로그인 요청 (POST /login)
class UserLogin(BaseModel):
    id: str = Field(..., min_length=8, max_length=16)
    password: str = Field(..., min_length=8, max_length=16)

# 공통 응답 형식
class MessageResponse(BaseModel):
    message: str