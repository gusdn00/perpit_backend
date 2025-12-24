# core/security.py
from passlib.context import CryptContext
from datetime import datetime, timedelta
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader # 변경됨

# 1. 기존 보안 설정 유지
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SECRET_KEY = "PERPIT_SECRET_KEY" 
ALGORITHM = "HS256"

# 2. 토큰 추출을 위한 설정 변경 (Swagger UI에서 토큰만 넣기 위해)
# Authorization 헤더에서 값을 가져오도록 설정합니다.
api_key_header = APIKeyHeader(name="Authorization") # 변경됨

# --- 기존 함수 유지 ---

def get_password_hash(password):
    return pwd_context.hash(password)

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(hours=24)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

# --- 새로 추가된 인증 함수 ---

async def get_current_user(token: str = Depends(api_key_header)): # 의존성 변경
    """
    사용자가 보낸 JWT 토큰을 해독하여 유효성을 검사하고 유저 정보를 반환합니다.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="자격 증명을 확인할 수 없습니다.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        # Swagger UI에서 'Bearer ' 문구를 포함해 넣을 수 있으므로 처리
        if token.startswith("Bearer "):
            token = token.replace("Bearer ", "")

        # 토큰 해독
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub") 
        
        if user_id is None:
            raise credentials_exception
            
        return {"user_id": user_id}
        
    except JWTError:
        raise credentials_exception