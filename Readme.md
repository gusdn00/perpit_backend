#### venv 활성화
.\venv\Scripts\activate                   

#### 서버 실행
uvicorn main:app --reload

#### pm2 서버 실행
pm2 start "venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000" --name perpit-backend-server

#### pm2 로그 확인
pm2 logs perpit-backend-server --lines 30
