# 학생회 규정 AI 어시스턴트 (v2)

인하대학교 학생회 규정·감사 질의응답 서비스. **실서비스 운영 중** — 변경은 곧 사용자에게 나간다.

- 프론트: https://ai-agent-patrick-16be.vercel.app (Vercel) · 백엔드: https://aiagent-production-d71a.up.railway.app (Railway)
- `main` push → CI 통과 후 양쪽 자동 배포 · 배포 버전은 `/api/health`의 `version` (릴리스 태그·`config.APP_VERSION`과 함께 올린다, [CONTRIBUTING.md](CONTRIBUTING.md#릴리스))
- 구조: FastAPI + LangGraph (`router → retrieve → reviewer‖auditor → coordinator`) + ChromaDB / Next.js 16
- LLM `gemini-3.7-flash` · 임베딩 `gemini-embedding-2` · `GEMINI_API_KEY` 없으면 목업 모드

## 비용 규칙 (최우선)

유료 API를 부르는 작업은 **실행 전에 예상 금액을 알리고 승인받는다.** 기본은 무료 경로.

| 작업 | 비용 | 비고 |
|---|---|---|
| `smoke_test.py` · `tests/check_all.py` · lint · build | 무료 | 기본 검증 수단. 두 파이썬 스크립트는 키를 비우고 임시 `DATA_DIR`로 강제 목업 (`api/.env`에 키가 있어도) |
| `evaluate.py --retrieval` / `--multihop` | 거의 무료 | **실제 로컬 색인** + Gemini 질의 임베딩 호출 (LLM 미호출). `api/data/`가 없으면 만들고 인용 그래프도 생성할 수 있다 |
| `evaluate.py --case <id>` | 건당 ~35원 | 프롬프트 일부 변경 시 1~3건만 |
| `evaluate.py` 전체 50건 | ~1,750원 | 배포 직전 1회만, 로컬·원격 중 **한쪽만** |
| 문서 재색인 (OCR 포함) | ~750원 | OCR 캐시 덕에 프롬프트를 안 바꾸면 재호출 없음 |

실제 사고(2026-08-16): 검증 반복이 누적 비용의 85%를 차지했고 크레딧 소진으로 서비스 장애 발생.

## 명령

```bash
cd api
.venv/Scripts/python.exe smoke_test.py              # 강제 목업 스모크 (임시 DATA_DIR, CI와 동일)
.venv/Scripts/python.exe tests/check_all.py         # 회귀 테스트 26건 (키·서버 없이, CI와 동일)
.venv/Scripts/python.exe evaluate.py --retrieval    # 검색 지표(MRR·순위), 실제 색인·임베딩, LLM 미호출
.venv/Scripts/python.exe evaluate.py --multihop     # 인용 그래프 A/B(판례 커버리지), 실제 색인·임베딩, LLM 미호출
.venv/Scripts/python.exe ingest_folder.py           # documents/ ↔ 로컬 색인 동기화
.venv/Scripts/python.exe upload_to_remote.py <배포URL>  # 배포 서버로 업로드 (기존 파일 건너뜀)
cd web && npm run lint && npm run build
```

Windows 주의: 인터프리터는 `api/.venv/Scripts/python.exe`, 한글 출력에는 `PYTHONIOENCODING=utf-8`.

## 함정 (실제로 겪은 것)

- **"목업" 스크립트는 키를 직접 비워야 목업이다.** `config.py`가 import 시 `api/.env`를 읽으므로, 환경변수만 없는 상태로는 로컬 실키가 잡혀 실제 과금·실제 색인 변경이 일어난다. 2026-09-26까지 `smoke_test.py`가 이 상태였다(CI는 키가 없어 몰랐음). 새 검증 스크립트는 `GEMINI_API_KEY`·`GOOGLE_API_KEY`를 `""`로, `DATA_DIR`을 임시 폴더로 **app import 전에** 강제하고, `MOCK_MODE`가 아니면 즉시 종료한다.
- **검색 관련 회귀는 배포본에서 확인한다.** OCR이 비결정적이라 로컬/원격 청크 경계가 달라 로컬만 통과한 적이 있다. 지금은 `data/ocr_cache`로 고정 — 캐시 키가 파일해시+프롬프트라 `_OCR_PROMPT`를 바꾸면 전체 재추출 비용이 발생한다.
- **원격 평가 전 답변 캐시를 비운다** (`POST /api/cache/clear`). 안 비우면 캐시가 0.3초에 응답해 새 코드가 검증되지 않는다. 문서 추가·삭제 시엔 자동으로 비워진다.
- 관리자 API 인증: `Authorization: Bearer <ADMIN_TOKEN>` (`api/.env`). settings 변경은 **PUT** (POST는 405). `/docs`·`/openapi.json`은 운영에서 꺼져 있다 (목업 모드에서만 열림).
- 개인정보는 프롬프트 규칙 + **코드 마스킹**(`app/privacy.py`) 이중 방어. 실명 목록은 저장소에 없다 — 로컬은 `api/private_names.txt`(gitignore), 배포는 Railway 환경변수 `PRIVATE_NAMES`(쉼표 구분). 목록이 비면 `evaluate.py`의 실명 검사가 실패로 표시된다. 전화·계좌·이메일은 목록 없이도 정규식으로 지운다. 등록된 실명이 **질문에** 있으면 라우터 전에 `general`(고정 거절문)로 보낸다 — LLM 미호출. 질의 원문도 DB 계층(`add_analysis`·`record_metric`)에서 마스킹해 저장하고, 기존 행은 기동 시 소급 정리한다. 브라우저에는 규정 질의 턴만 7일간 저장한다.
- 비용 폭주 방어: 일일 한도에 진행 중 요청을 더해 검사하고, 동시 LLM 파이프라인은 `MAX_INFLIGHT_TOTAL`(기본 5)로 제한한다. 지표·분석 기록은 `RETENTION_DAYS`(기본 365) 지나면 기동 시 삭제.
- 관리자 토큰이 실린 `/api/chat`은 일일 한도에서 제외된다 (지표엔 기록됨). `evaluate.py --url`이 토큰을 자동으로 싣는다. 일일 한도·일별 집계의 '오늘'은 **한국 자정** 기준이다 (`db._TODAY`).
- 클라이언트가 응답 중 끊어도 `status=cancelled`로 지표에 남는다 — 끊기로 한도를 우회할 수 없다. 캐시는 세대(`cache_generation`)로 보호되어, 비운 뒤 완료된 옛 요청이 낡은 답을 다시 저장하지 않는다.
- 피드백은 결과 이벤트의 `feedback_token`(HMAC 서명)이 있어야 받는다 — 순번 `analysis_id`만으로는 남의 답변을 평가할 수 없다.
- 프론트 CSP는 `next.config.ts`에서 백엔드 주소로만 통신을 허용한다(`connect-src`). 새 외부 서비스를 부르면 여기에 추가해야 한다.
- 인용 그래프(`citation_graph.py`)는 색인의 파생물 — 문서 추가·삭제 시 자동 재생성된다. 확장은 라우터의 `needs_precedents` 판별로만 켜지고, `GRAPH_EXPANSION=0`이 킬 스위치다.
- 문서 분류는 파일명 기준(`classify_doc`): `보고서`/`감사결과` 포함 → audit (Gemini 표 구조 추출), 그 외 → regulation (pypdf + 조항 청킹).
- `documents/`는 git 제외(내부 문서). 로컬 색인과 배포 색인은 **별개** — 배포 반영은 `upload_to_remote.py`.
- Railway 프록시 뒤에서 클라이언트 IP는 X-Forwarded-For의 **오른쪽 끝** 항목이다 (앞쪽은 클라이언트가 위조 가능).
- 응답이 갑자기 30초 이상으로 느려지면 코드보다 **Gemini 크레딧·쿼터**부터 의심한다. 대시보드 오류 배지에 마우스를 올리면 실패 사유가 보인다.

## 품질 기준선 (2026-08-16)

평가셋 50/50 통과 · 검색 MRR 0.861(평균 순위 1.9위) · 질의당 입력 ~15.7k 토큰 · 응답 9~12초 · 질의당 ~35원

평가 실패 시 **시스템 문제인지 평가셋 기대치 문제인지 먼저 가른다** — 커밋 규칙·CI 구성은 [CONTRIBUTING.md](CONTRIBUTING.md).
