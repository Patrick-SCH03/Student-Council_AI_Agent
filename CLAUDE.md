# 학생회 규정 AI 어시스턴트 (v2)

인하대학교 학생회 규정·감사 질의응답 서비스. **실서비스 운영 중** — 변경은 곧 사용자에게 나간다.

- 프론트: https://ai-agent-patrick-16be.vercel.app (Vercel) · 백엔드: https://aiagent-production-d71a.up.railway.app (Railway)
- `main` push → CI 통과 후 양쪽 자동 배포
- 구조: FastAPI + LangGraph (`router → retrieve → reviewer‖auditor → coordinator`) + ChromaDB / Next.js 16
- LLM `gemini-3.7-flash` · 임베딩 `gemini-embedding-2` · `GEMINI_API_KEY` 없으면 목업 모드

## 비용 규칙 (최우선)

유료 API를 부르는 작업은 **실행 전에 예상 금액을 알리고 승인받는다.** 기본은 무료 경로.

| 작업 | 비용 | 비고 |
|---|---|---|
| `smoke_test.py`(목업) · lint · build · `evaluate.py --retrieval` | 무료 | 기본 검증 수단 |
| `evaluate.py --case <id>` | 건당 ~35원 | 프롬프트 일부 변경 시 1~3건만 |
| `evaluate.py` 전체 50건 | ~1,750원 | 배포 직전 1회만, 로컬·원격 중 **한쪽만** |
| 문서 재색인 (OCR 포함) | ~750원 | OCR 캐시 덕에 프롬프트를 안 바꾸면 재호출 없음 |

실제 사고(2026-08-16): 검증 반복이 누적 비용의 85%를 차지했고 크레딧 소진으로 서비스 장애 발생.

## 명령

```bash
cd api
.venv/Scripts/python.exe smoke_test.py              # 목업 스모크 (CI와 동일)
.venv/Scripts/python.exe evaluate.py --retrieval    # 검색 지표(MRR·순위), LLM 미호출
.venv/Scripts/python.exe ingest_folder.py           # documents/ ↔ 로컬 색인 동기화
.venv/Scripts/python.exe upload_to_remote.py <배포URL>  # 배포 서버로 업로드 (기존 파일 건너뜀)
cd web && npm run lint && npm run build
```

Windows 주의: 인터프리터는 `api/.venv/Scripts/python.exe`, 한글 출력에는 `PYTHONIOENCODING=utf-8`.

## 함정 (실제로 겪은 것)

- **검색 관련 회귀는 배포본에서 확인한다.** OCR이 비결정적이라 로컬/원격 청크 경계가 달라 로컬만 통과한 적이 있다. 지금은 `data/ocr_cache`로 고정 — 캐시 키가 파일해시+프롬프트라 `_OCR_PROMPT`를 바꾸면 전체 재추출 비용이 발생한다.
- **원격 평가 전 답변 캐시를 비운다** (`POST /api/cache/clear`). 안 비우면 캐시가 0.3초에 응답해 새 코드가 검증되지 않는다. 문서 추가·삭제 시엔 자동으로 비워진다.
- 관리자 API 인증: `Authorization: Bearer <ADMIN_TOKEN>` (`api/.env`). settings 변경은 **PUT** (POST는 405).
- 관리자 토큰이 실린 `/api/chat`은 일일 한도에서 제외된다 (지표엔 기록됨). `evaluate.py --url`이 토큰을 자동으로 싣는다.
- 문서 분류는 파일명 기준(`classify_doc`): `보고서`/`감사결과` 포함 → audit (Gemini 표 구조 추출), 그 외 → regulation (pypdf + 조항 청킹).
- `documents/`는 git 제외(내부 문서). 로컬 색인과 배포 색인은 **별개** — 배포 반영은 `upload_to_remote.py`.
- Railway 프록시 뒤에서 클라이언트 IP는 X-Forwarded-For의 **오른쪽 끝** 항목이다 (앞쪽은 클라이언트가 위조 가능).
- 응답이 갑자기 30초 이상으로 느려지면 코드보다 **Gemini 크레딧·쿼터**부터 의심한다. 대시보드 오류 배지에 마우스를 올리면 실패 사유가 보인다.

## 품질 기준선 (2026-08-16)

평가셋 50/50 통과 · 검색 MRR 0.861(평균 순위 1.9위) · 질의당 입력 ~15.7k 토큰 · 응답 9~12초 · 질의당 ~35원

평가 실패 시 **시스템 문제인지 평가셋 기대치 문제인지 먼저 가른다** — 커밋 규칙·CI 구성은 [CONTRIBUTING.md](CONTRIBUTING.md).
