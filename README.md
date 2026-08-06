# 🎓 학생회 규정 AI 어시스턴트 (v2)

학생회 규정·재정·감사 질문을 **AI 멀티에이전트**가 문서 기반(RAG)으로 분석해
위반 여부·감사 처분 가능성·최종 권고안을 제시하는 웹 서비스입니다.

> v1(Gradio + Gemini 단일 앱)은 `legacy/`에 보관되어 있으며, v2는 전면 재구축 버전입니다.

## 아키텍처

```
Next.js 16 (web/)  ──SSE──▶  FastAPI (api/)
  채팅 UI · 문서 관리          │
                              ▼
                    LangGraph 1.0 파이프라인
                    router ─┬▶ reviewer(규정 검토) ─┐
                            │▶ auditor(감사 분석)  ─┴▶ coordinator(종합 권고)
                            └▶ general(일반 답변)      * reviewer/auditor 병렬 실행
                              │
              ┌───────────────┼────────────────┐
              ▼               ▼                ▼
        Gemini API      ChromaDB(RAG)      SQLite(이력)
```

### v1 대비 핵심 개선

| 항목 | v1 | v2 |
|---|---|---|
| 에이전트 실행 | 이름만 병렬(순차) | LangGraph fan-out 실제 병렬 |
| 위험도 판정 | 키워드 카운팅(중복 매칭 버그) | 구조화 출력 enum → 코드에서 결정론적 계산 |
| 출처 인용 | 메타데이터 키 불일치로 항상 실패 | 청크 메타데이터 일원화, UI 인용 칩 |
| 문서 색인 | 첫 질문 시점(느림) | 업로드 시점 백그라운드 색인 |
| 결과 기록 | Notion(필수 의존) | 자체 SQLite + 이력 API |
| UI | Gradio | Next.js 16 + Tailwind v4 (Figma AI Chatbot UI Kit 기반) |
| 응답 | 완료 후 일괄 | SSE 스트리밍(진행 단계 + 토큰) |

## 기술 스택

- **LLM**: Google Gemini (`gemini-2.5-flash`, 환경변수로 교체 가능)
- **임베딩**: `gemini-embedding-001`
- **오케스트레이션**: LangGraph 1.0
- **백엔드**: FastAPI + ChromaDB + SQLite
- **프론트**: Next.js 16 (App Router) + Tailwind CSS v4 + Plus Jakarta Sans

## 실행 방법

### 1. 백엔드 (api/)

```bash
cd v2/api
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
copy .env.example .env         # GEMINI_API_KEY 입력
uvicorn app.main:app --port 8000
```

> `GEMINI_API_KEY`가 없으면 **목업 모드**로 동작합니다(LLM 호출 없이 전체 플로우 검증 가능).
> 키 발급: https://aistudio.google.com/apikey

### 2. 프론트엔드 (web/)

```bash
cd v2/web
npm install
npm run dev                    # http://localhost:3000
```

### 3. 규정 문서 색인

`documents/` 폴더에 규정·세칙·감사보고서 PDF를 넣고:

```bash
cd v2/api
.venv\Scripts\python.exe ingest_folder.py
```

이미 색인된 파일명은 자동으로 건너뛰므로 문서 추가 시 다시 실행하면 됩니다.

### 4. 사용

채팅 화면에서 질문 → 규정 검토·감사 분석 병렬 진행 → 위험도 배지 + 종합 권고 + 출처 인용 확인

## API 요약

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/chat` | SSE 스트리밍 분석 (stage/token/agent_done/result 이벤트) |
| POST | `/api/documents` | PDF 업로드 및 색인 (운영용, UI 없음) |
| GET | `/api/documents` | 색인 문서 목록 |
| DELETE | `/api/documents/{doc_id}` | 문서 및 색인 삭제 |
| GET | `/api/history` | 분석 이력 |
| GET | `/api/health` | 상태(목업 여부, 모델, 청크 수) |

## 테스트

```bash
cd v2/api
python smoke_test.py           # 벡터 스토어 + 그래프 병렬 실행 + 라우팅 검증 (목업 모드)
```

## 배포 로드맵 (다음 단계)

- [ ] Supabase Auth (학교 이메일 도메인 제한) + 사용자별 일일 질의 제한
- [ ] 배포: 프론트 Vercel, 백엔드 Google Cloud Run(scale-to-zero) — 목표 운영비 월 1~3만원
- [x] 스캔본 PDF 대응 — Gemini 멀티모달 폴백으로 자동 텍스트 추출
- [ ] 실제 규정 문서 기반 평가셋(20~30문항) 구축 및 프롬프트 튜닝
- [ ] 감사 기록 문서를 별도 컬렉션으로 분리

## 주의

본 서비스의 AI 분석은 참고용입니다. 최종 판단은 감사위원회 및 관련 규정을 따릅니다.
