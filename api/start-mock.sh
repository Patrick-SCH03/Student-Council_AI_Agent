#!/usr/bin/env bash
# 로컬 UI 테스트용 목업 백엔드 (비용 0원). 빈 GEMINI_API_KEY는 load_dotenv가 덮지 않아 목업이 강제된다.
cd "$(dirname "$0")"
exec env GEMINI_API_KEY= GOOGLE_API_KEY= DATA_DIR="$PWD/data-mock" CORS_ORIGINS=http://localhost:3000 .venv/Scripts/python.exe -m uvicorn app.main:app --port 8001
