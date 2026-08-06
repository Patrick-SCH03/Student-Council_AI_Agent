# 학생회 규정 AI 어시스턴트

인하대학교 학생회 규정·재정·감사 질문에 대해 **AI 멀티에이전트**가 실제 회칙·세칙·감사보고서를 근거로
위반 여부, 감사 처분 가능성, 최종 권고안을 분석해주는 챗봇 서비스입니다.

> "학생회비로 회식비 사용이 가능한가요?" → 규정 검토 + 감사 분석 + 종합 권고를 출처와 함께 제공

## 주요 기능

- **멀티에이전트 분석** — 규정 검토 에이전트와 감사 에이전트가 병렬로 분석하고, 조정 에이전트가 종합 권고안을 도출
- **문서 기반 답변 (RAG)** — 실제 학생회칙·세칙·감사보고서를 검색해 조항 단위로 인용, 근거 문단 확인 가능
- **위험도 판정** — 에이전트의 구조화 출력(enum)을 기반으로 높음/보통/낮음을 결정론적으로 계산
- **실시간 스트리밍** — 분석 단계 표시, 에이전트별 완료 즉시 부분 결과 렌더링, 답변 토큰 스트리밍
- **대화 맥락 유지** — 후속 질문("그럼 처분은 얼마나 돼?")을 이전 대화 기준으로 이해
- **후속 질문 제안 · 답변 복사 · 대화 이력 유지(localStorage)**
- **스캔본 PDF 자동 파싱** — 텍스트 레이어가 없는 문서는 Gemini 멀티모달로 원문 추출
- **도메인 가드** — 학생회 업무와 무관한 질문은 LLM 호출 없이 안내 메시지로 응답

## 아키텍처

```
Next.js 16 (web/)  ──SSE──▶  FastAPI (api/)
  채팅 UI                      │
                               ▼
                     LangGraph 파이프라인
                     router ─┬▶ reviewer(규정 검토) ─┐
                             │▶ auditor(감사 분석)  ─┴▶ coordinator(종합 권고)
                             └▶ out-of-scope 안내      * reviewer/auditor 병렬
                               │
               ┌───────────────┼────────────────┐
               ▼               ▼                ▼
         Gemini API      ChromaDB(RAG)      SQLite(이력)
```

## 기술 스택

| 영역 | 기술 |
|---|---|
| LLM | Google Gemini (`gemini-3.6-flash`) |
| 임베딩 | `gemini-embedding-2` |
| 오케스트레이션 | LangGraph 1.0 |
| 백엔드 | FastAPI · ChromaDB · SQLite |
| 프론트엔드 | Next.js 16 (App Router) · Tailwind CSS v4 |
| 배포 | Docker Compose + Caddy (단일 서버) |

## 시작하기

### 1. 백엔드

```bash
cd v2/api
python -m venv .venv
.venv\Scripts\activate          # Windows (Linux/Mac: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env           # GEMINI_API_KEY 입력
uvicorn app.main:app --port 8000
```

> `GEMINI_API_KEY`가 없으면 목업 모드로 동작합니다 (LLM 호출 없이 플로우 확인용).
> 키 발급: https://aistudio.google.com/apikey

### 2. 프론트엔드

```bash
cd v2/web
npm install
npm run dev                      # http://localhost:3000
```

### 3. 규정 문서 색인

`documents/` 폴더에 규정·세칙·감사보고서 PDF를 넣고:

```bash
cd v2/api
.venv\Scripts\python.exe ingest_folder.py
```

- 이미 색인된 파일명은 자동으로 건너뜁니다 (문서 추가 시 재실행)
- 스캔본 PDF는 Gemini 멀티모달로 자동 추출됩니다
- 무료 티어 쿼터(429) 초과 시 자동 백오프 재시도

## API

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/chat` | SSE 스트리밍 분석 (`stage` / `agent_done` / `token` / `result` 이벤트) |
| GET | `/api/health` | 상태 확인 (모드, 모델, 색인 청크 수) |
| GET | `/api/history` | 분석 이력 |
| POST | `/api/documents` | PDF 업로드·색인 (운영용) |
| DELETE | `/api/documents/{doc_id}` | 문서 색인 삭제 |

## 배포

단일 서버(VPS)에 Docker Compose로 배포합니다. 자세한 절차는 [DEPLOYMENT.md](DEPLOYMENT.md) 참고.

```bash
cp deploy/.env.example deploy/.env   # 키·도메인 입력
cd deploy
docker compose up -d --build
```

## 테스트

```bash
cd v2/api
python smoke_test.py    # 벡터 스토어 + 파이프라인 + 라우팅 검증 (목업 모드)
```

## 주의

본 서비스의 AI 분석은 참고용입니다. 최종 판단은 감사위원회 및 관련 규정을 따릅니다.
