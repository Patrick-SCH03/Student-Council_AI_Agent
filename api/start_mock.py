"""로컬 UI 테스트용 목업 백엔드 실행기 (비용 0원).

셸 스크립트 대신 파이썬으로 환경을 고정한다 — 런처가 어떤 셸(bash/WSL/cmd)로
실행하든 프로세스 안에서 직접 설정한 환경변수는 항상 적용된다.
빈 GEMINI_API_KEY는 load_dotenv(기본 override=False)가 덮지 않아 목업이 강제된다.
"""

import os
from pathlib import Path

API_DIR = Path(__file__).resolve().parent
os.chdir(API_DIR)
os.environ["GEMINI_API_KEY"] = ""
os.environ["GOOGLE_API_KEY"] = ""
os.environ["DATA_DIR"] = str(API_DIR / "data-mock")
os.environ["CORS_ORIGINS"] = "http://localhost:3000"

import uvicorn  # noqa: E402  (환경 설정 후에 임포트)

if __name__ == "__main__":
    uvicorn.run("app.main:app", port=8001)
