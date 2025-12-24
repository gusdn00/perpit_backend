# main.py
from fastapi import FastAPI
import models
from database import engine
from api import auth, sheets # 방금 만든 auth 라우터

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Perpit API")

# Express의 app.use('/auth', authRouter)와 동일
app.include_router(auth.router)
app.include_router(sheets.router)

@app.get("/")
def root():
    return {"message": "Perpit API Server is Running"}