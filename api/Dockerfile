FROM python:3.12-slim

WORKDIR /app

# 의존성 먼저 설치 (레이어 캐시 활용). 잠금 파일로 버전을 고정해, 같은 커밋을 다시
# 빌드해도 검증한 그 버전이 깔린다 (하한만 두면 빌드 시점의 최신이 몰래 들어온다).
COPY requirements.txt requirements-lock.txt ./
RUN pip install --no-cache-dir -r requirements.txt -c requirements-lock.txt

COPY app ./app
COPY ingest_folder.py .

# 런타임 데이터(벡터DB/SQLite) 저장 위치.
# 이 경로에 볼륨을 마운트해야 재배포 후에도 색인이 유지된다.
#   - Railway: Volume의 Mount path를 /data 로 지정 (Docker VOLUME 지시어는 미지원)
#   - Docker Compose: deploy/docker-compose.yml 에서 api-data:/data 로 마운트
ENV DATA_DIR=/data

EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
