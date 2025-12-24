# core/security.py
from passlib.context import CryptContext
from datetime import datetime, timedelta
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader

# 1. 보안 설정
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SECRET_KEY = "PERPIT_SECRET_KEY" 
ALGORITHM = "HS256"

# 2. 헤더 설정 (Authorization 헤더를 읽음)
api_key_header = APIKeyHeader(name="Authorization", auto_error=False)

def get_password_hash(password):
    return pwd_context.hash(password)

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(hours=24)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

# 3. 인증 함수 (프론트엔드 Bearer 대응 로직 추가)
async def get_current_user(token: str = Depends(api_key_header)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="자격 증명을 확인할 수 없습니다.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    if not token:
        raise credentials_exception

    try:
        # 핵심: 프론트엔드에서 보낸 'Bearer ' 문자열을 확실하게 제거
        if token.startswith("Bearer "):
            token = token.split(" ")[1]
        elif token.startswith("bearer "): # 소문자 대응
            token = token.split(" ")[1]

        # 토큰 해독
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        
        if user_id is None:
            raise credentials_exception
            
        return {"user_id": user_id}
        
    except (JWTError, IndexError):
        # 토큰 변조, 만료 또는 형식 오류(IndexError) 발생 시
        raise credentials_exception