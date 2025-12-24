# main.py
from fastapi import FastAPI
import models
from database import engine
from api import auth, sheets # 방금 만든 auth 라우터
from fastapi.middleware.cors import CORSMiddleware

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Perpit API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 테스트 단계에서는 전체 허용, 나중에 프론트 주소만 넣기
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Express의 app.use('/auth', authRouter)와 동일
app.include_router(auth.router)
app.include_router(sheets.router)

@app.get("/")
def root():
    return {"message": "Perpit API Server is Running"}