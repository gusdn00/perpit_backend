# api/auth.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db
import models, schemas, crud
from core import security
from core.security import get_current_user

router = APIRouter(prefix="/auth", tags=["Auth"])

# 회원가입
@router.post("/signup", status_code=201)
def signup(user: schemas.UserCreate, db: Session = Depends(get_db)):
    if crud.get_user_by_user_id(db, user.user_id):
        raise HTTPException(status_code=409, detail="이미 사용 중인 아이디입니다.")
    return crud.create_user(db, user)

# 로그인
@router.post("/login")
def login(user: schemas.UserLogin, db: Session = Depends(get_db)):
    db_user = crud.get_user_by_user_id(db, user.id)
    if not db_user or not security.verify_password(user.password, db_user.password):
        raise HTTPException(status_code=401, detail="아이디 또는 비밀번호 불일치")
    
    token = security.create_access_token(data={"sub": db_user.user_id})
    return {"token": token, "message": "로그인 성공"}

# ID 중복체크
@router.get("/check-id")
def check_id(id: str, db: Session = Depends(get_db)):
    exists = crud.get_user_by_user_id(db, id) is not None
    return {"isRedundancy": exists, "message": "이미 사용 중" if exists else "사용 가능"}


# 프로필 정보 확인
@router.get("/profile", status_code=200)
def get_profile(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    # 1. DB에 user id 확인
    db_user = crud.get_user_by_user_id(db, current_user["user_id"])
    
    if not db_user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

    # 2. 데이터 반환
    return {
        "message": "프로필 조회 성공",
        "data": {
            "name": db_user.name,
            "user_id": db_user.user_id,
            "email": db_user.email
        }
    }