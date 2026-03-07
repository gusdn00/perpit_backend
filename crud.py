import uuid
from sqlalchemy.orm import Session
import models, schemas
from core import security

def get_user_by_user_id(db: Session, user_id: str):
    return db.query(models.User).filter(models.User.user_id == user_id).first()

def get_user_by_social_id(db: Session, social_id: str):
    return db.query(models.User).filter(models.User.social_id == social_id).first()

def create_user(db: Session, user: schemas.UserCreate):
    hashed_pw = security.get_password_hash(user.password)
    db_user = models.User(
        user_id=user.user_id,
        name=user.name,
        password=hashed_pw,
        email=user.email
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

def create_social_user(db: Session, social_id: str, name: str, email: str, social_provider: str):
    # user_id: 소셜 ID 뒤 10자리로 구성 (최대 16자 제한)
    user_id = f"k{social_id[-15:]}"
    # 소셜 로그인 유저는 비밀번호 불필요 → 랜덤 해시 저장
    random_pw = security.get_password_hash(str(uuid.uuid4()))
    db_user = models.User(
        user_id=user_id,
        name=name,
        email=email,
        password=random_pw,
        social_provider=social_provider,
        social_id=social_id,
        token_balance=0
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user