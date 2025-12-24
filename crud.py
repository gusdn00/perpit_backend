# crud.py
from sqlalchemy.orm import Session
import models, schemas
from core import security

def get_user_by_user_id(db: Session, user_id: str):
    return db.query(models.User).filter(models.User.user_id == user_id).first()

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