# 배포 가이드

프론트엔드는 **Vercel**, 백엔드는 **Railway**에 배포합니다.

```
[브라우저] ──정적 페이지──▶ Vercel (web)
     └────SSE 스트리밍─────▶ Railway (api) ──▶ Gemini API
                                  └──▶ Volume (/data: ChromaDB + SQLite)
```

API는 브라우저가 Railway로 **직접** 호출합니다. Vercel 프록시를 거치면
20~30초 걸리는 스트리밍 응답이 서버리스 함수 타임아웃·비용에 걸립니다.

**예상 비용**: Vercel 무료 + Railway Hobby $5/월 + Gemini API 사용량

---

## 0. 관리자 토큰 준비

문서 관리(`/api/documents`)와 운영 지표(`/api/stats`, `/api/history`, `/api/analyses`)는
**관리자 전용**입니다. `ADMIN_TOKEN`을 반드시 설정하세요.

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

- 미설정 시 해당 API는 `503`으로 차단됩니다 (공개 배포 사고 방지)
- 설정 여부는 `/api/health`의 `admin_protected` 필드로 확인
- 웹의 `/stats` 최초 접속 시 이 토큰을 입력하면 브라우저에 저장됩니다

---

## 1. Railway — 백엔드

1. [railway.com](https://railway.com) → **New Project** → **Deploy from GitHub repo** → 이 저장소 선택
2. **Settings → Root Directory**를 `api`로 지정 (Dockerfile 자동 감지)
3. **Variables** 탭에 환경변수 추가

   | 키 | 값 |
   |---|---|
   | `GEMINI_API_KEY` | Gemini API 키 |
   | `GEMINI_MODEL` | `gemini-3.6-flash` |
   | `ADMIN_TOKEN` | 0단계에서 생성한 토큰 |
   | `DATA_DIR` | `/data` |

4. **볼륨 연결** — 캔버스에서 우클릭(또는 `Ctrl+K`) → **Volume** → 서비스 선택 →
   **Mount path에 `/data`** 입력

   > 빠뜨리면 재배포할 때마다 색인이 사라집니다. Railway는 Docker의 `VOLUME`
   > 지시어를 지원하지 않으므로 이 설정으로만 영속화됩니다.

5. **Settings → Networking → Generate Domain** → `xxx.up.railway.app` 발급
6. `https://xxx.up.railway.app/api/health` 확인

   ```json
   {"status":"ok","mock_mode":false,"admin_protected":true,...}
   ```

   | 값 | 의미 |
   |---|---|
   | `mock_mode: false` | Gemini 키 정상 인식 |
   | `admin_protected: true` | 관리자 토큰 설정됨 |

## 2. 규정 문서 업로드

`documents/`는 git에 포함되지 않으므로 로컬에서 업로드합니다.

```bash
cd api
.venv\Scripts\python upload_to_remote.py https://xxx.up.railway.app --token <ADMIN_TOKEN>
```

- 서버가 추출·청킹·임베딩을 수행하므로 문서 수에 따라 수 분 소요
- 이미 업로드된 파일명은 건너뜁니다 (재실행 안전)
- 완료 후 `/api/health`의 `indexed_chunks`로 확인

## 3. Vercel — 프론트엔드

1. [vercel.com](https://vercel.com) → **Add New → Project** → 같은 저장소 Import
2. **Root Directory**를 `web`으로 지정 (Framework는 Next.js 자동 인식)
3. **Environment Variables**에 `NEXT_PUBLIC_API_URL` = `https://xxx.up.railway.app` 추가
4. **Deploy** → 프로덕션 주소 발급
5. **Settings → Deployment Protection** → Vercel Authentication을 `Disabled`로 변경

   > 기본값이 켜져 있으면 방문자가 Vercel 로그인 화면으로 리다이렉트됩니다.

## 4. 연결 마무리

1. Railway Variables에 `CORS_ORIGINS` = `https://<프로덕션 주소>` 추가 → 자동 재배포

   > 배포마다 바뀌는 해시 주소(`xxx-abc123-team.vercel.app`)가 아니라
   > **고정 프로덕션 주소**를 넣어야 합니다. 여러 개는 쉼표로 구분합니다.

2. 사이트 접속 → 질문 테스트 (스트리밍·인용 확인)
3. `/stats` → 관리자 토큰 입력 → 대시보드 확인

---

## 운영

| 작업 | 방법 |
|---|---|
| 코드 배포 | `main`에 push → Vercel·Railway 자동 재배포 |
| 문서 추가 | `documents/`에 PDF 추가 → `upload_to_remote.py` 실행 |
| 로그 확인 | Railway → Deployments → Deploy Logs |
| 비용 확인 | `/stats`의 "예상 API 비용" 타일 |

## 보안 체크리스트

- [ ] `ADMIN_TOKEN` 설정 (`/api/health`의 `admin_protected: true` 확인)
- [ ] `CORS_ORIGINS`를 실제 프론트엔드 도메인으로 제한
- [ ] Vercel Deployment Protection 상태 확인 (공개 여부 의도대로인지)
- [ ] Gemini API 키에 [사용량 한도](https://aistudio.google.com/) 설정
- [ ] 규정 PDF가 저장소에 포함되지 않았는지 확인 (`documents/*.pdf` gitignore)

## 다음 단계 (선택)

- **사용자 접근 제한**: 학교 이메일 인증으로 채팅 자체를 구성원 전용화
- **사용량 제한**: 사용자/IP별 일일 질의 제한으로 API 비용 방어
- **관측**: Langfuse 연동으로 에이전트별 비용·품질 추적
