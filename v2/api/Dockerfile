FROM python:3.12-slim

WORKDIR /app

# 의존성 먼저 설치 (레이어 캐시 활용)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY ingest_folder.py .

# 런타임 데이터(벡터DB/SQLite)는 볼륨 마운트 지점
ENV DATA_DIR=/data
VOLUME /data

EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
