# 배포 가이드

세 가지 배포 경로가 있습니다.

- **A. 내 PC + Tailscale Funnel** — 비용 0원, 시험 운영·베타용. PC가 켜져 있을 때만 서비스됨
- **B. VPS + Docker Compose** — 24시간 정식 운영용
- **C. Vercel(프론트) + Railway(백엔드)** — 관리형 PaaS, 서버 관리 불필요 (약 $5/월)

## 공통: 관리자 토큰

문서 관리(`/api/documents`)와 운영 지표(`/api/stats`, `/api/history`, `/api/analyses`)는
**관리자 전용**입니다. `ADMIN_TOKEN` 환경변수를 반드시 설정하세요.

- 미설정 시 해당 API는 `503`으로 차단됩니다 (공개 배포 사고 방지)
- 설정 여부는 `/api/health`의 `admin_protected` 필드로 확인
- 웹의 `/stats` 페이지 최초 접속 시 토큰을 입력하면 브라우저에 저장됩니다

```bash
# 토큰 생성 예시
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

## A. 내 PC를 서버로 (Tailscale Funnel — 무료 고정 주소)

최초 1회 설정:

1. `winget install Tailscale.Tailscale` 설치 후 로그인 (`tailscale login`)
2. `tailscale funnel --bg 3000` 실행 → 안내 링크에서 Funnel 활성화 승인

이후 운영:

```powershell
.\start-server.ps1        # API + 웹(프로덕션) 실행, 고정 공개 URL 출력
.\start-server.ps1 -Stop  # 서버 종료 (Funnel 설정은 유지)
```

- 공개 주소는 `https://<PC이름>.<테일넷>.ts.net` 형태의 **고정 주소** (재시작해도 동일)
- Funnel 설정은 Tailscale 서비스에 저장되어 재부팅 후에도 유지됨
- Windows 전원 설정에서 절전 모드를 꺼두어야 함 (설정 → 시스템 → 전원 → 절전 안 함)
- 운영 현황은 `/stats` 페이지에서 확인 (질의 수·응답 시간·토큰 사용량·위험도 분포)

## B. VPS + Docker Compose (정식 운영)

단일 서버(VPS) 하나에 Docker Compose로 전체 스택(API + 웹 + HTTPS 프록시)을 올리는 구성입니다.
예상 비용: 서버 월 6,000~10,000원 + Gemini API 사용량(일 수십 건 기준 월 1~2만원 이내).

```
[브라우저] ── HTTPS ──▶ Caddy ──┬── /api/* ──▶ FastAPI (api)
                                └── 그 외  ──▶ Next.js (web)
```

## 1. 서버 준비 (직접 해야 하는 것)

1. VPS 1대 생성 — 서울 리전, 1GB RAM 이상이면 충분
   - 예: Vultr, DigitalOcean, AWS Lightsail, Oracle Cloud 무료 티어 등
   - OS: Ubuntu 22.04+
2. 방화벽에서 80, 443 포트 오픈
3. (권장) 도메인 준비 후 A 레코드를 서버 IP로 연결 — 도메인이 있으면 Caddy가 HTTPS 인증서를 자동 발급
4. 서버에 Docker 설치:
   ```bash
   curl -fsSL https://get.docker.com | sh
   ```

## 2. 프로젝트 배포

```bash
# 서버에서
git clone https://github.com/Patrick-SCH03/AI-agent.git
cd AI-agent

# 환경 변수 설정
cp deploy/.env.example deploy/.env
nano deploy/.env
#  - GEMINI_API_KEY: 실제 키 입력
#  - SITE_ADDRESS: 도메인 (예: rules.example.kr) / 도메인 없으면 :80 유지
#  - SITE_ORIGIN: https://도메인 (도메인 없으면 http://서버IP)

# 빌드 및 기동
cd deploy
docker compose up -d --build
```

접속: `https://도메인` (또는 `http://서버IP`)

## 3. 규정 문서 색인

로컬 `documents/` 폴더는 git에 올라가지 않으므로, PDF를 서버로 복사한 뒤 색인합니다.

```bash
# 로컬에서 서버로 문서 업로드
scp documents/*.pdf user@서버IP:~/AI-agent/documents/

# 서버에서 색인 실행 (api 컨테이너 내부의 /documents 는 읽기전용 마운트)
cd ~/AI-agent/deploy
docker compose exec api python ingest_folder.py /documents
```

문서를 추가·교체할 때마다 같은 명령을 다시 실행하면 됩니다 (기존 파일명은 자동 건너뜀).

## 4. 운영 명령 모음

```bash
docker compose logs -f api        # API 로그
docker compose restart api        # API 재시작
docker compose up -d --build      # 코드 업데이트 반영 (git pull 후)
docker compose down               # 전체 중지 (데이터 볼륨은 유지됨)
```

색인·이력 데이터는 `api-data` 도커 볼륨에 저장되어 컨테이너를 재빌드해도 유지됩니다.

## 5. 보안 체크리스트

- [ ] `deploy/.env`는 서버에만 존재 (git에 커밋 금지 — .gitignore로 차단됨)
- [ ] Gemini API 키에 [사용량 한도](https://aistudio.google.com/) 설정
- [ ] 서버 SSH는 키 인증만 허용 권장
- [ ] 규정 PDF는 저장소에 포함되지 않음 (`documents/*.pdf` gitignore)

---

# C. Vercel(프론트) + Railway(백엔드)

서버 관리 없이 배포하는 경로입니다. Vercel은 무료, Railway는 Hobby $5/월(사용량 크레딧 포함).

```
[브라우저] ──정적 페이지──▶ Vercel (web)
     └────SSE 스트리밍─────▶ Railway (api) ──▶ Gemini API
                                  └──▶ Volume (/data: ChromaDB + SQLite)
```

API는 브라우저가 Railway로 **직접** 호출합니다. Vercel 프록시를 거치면 30초 걸리는
스트리밍 응답이 서버리스 함수 타임아웃·비용에 걸립니다.

## C-1. Railway에 백엔드 배포

1. [railway.com](https://railway.com) → **New Project** → **Deploy from GitHub repo** → 이 저장소 선택
2. **Settings → Root Directory**를 `api`로 지정 (Dockerfile 자동 감지)
3. **Variables** 탭에 환경변수 추가

   | 키 | 값 |
   |---|---|
   | `GEMINI_API_KEY` | Gemini API 키 |
   | `GEMINI_MODEL` | `gemini-3.6-flash` |
   | `ADMIN_TOKEN` | 랜덤 문자열 (위 "공통" 섹션 참고) |
   | `DATA_DIR` | `/data` |

4. **Volumes** → 볼륨 생성 후 마운트 경로를 **`/data`**로 지정
   > 빠뜨리면 재배포할 때마다 색인이 사라집니다.
5. **Settings → Networking → Generate Domain** → `xxx.up.railway.app` 발급
6. `https://xxx.up.railway.app/api/health` 접속 → `admin_protected: true` 확인

## C-2. 규정 문서 업로드·색인

`documents/`는 git에 포함되지 않으므로 로컬에서 업로드합니다.

```bash
cd api
.venv\Scripts\python upload_to_remote.py https://xxx.up.railway.app --token <ADMIN_TOKEN>
```

- 서버가 추출·청킹·임베딩을 수행하므로 문서 수에 따라 수 분 소요
- 이미 업로드된 파일명은 건너뜁니다 (재실행 안전)
- 완료 후 `/api/health`의 `indexed_chunks`로 확인

## C-3. Vercel에 프론트엔드 배포

1. [vercel.com](https://vercel.com) → **Add New → Project** → 같은 저장소 Import
2. **Root Directory**를 `web`으로 지정 (Framework는 Next.js 자동 인식)
3. **Environment Variables**에 `NEXT_PUBLIC_API_URL` = `https://xxx.up.railway.app` 추가
4. **Deploy** → `yyy.vercel.app` 발급

## C-4. 연결 마무리

1. Railway Variables에 `CORS_ORIGINS` = `https://yyy.vercel.app` 추가 → 자동 재배포
2. `yyy.vercel.app` 접속 → 질문 테스트 (스트리밍·인용 확인)
3. `yyy.vercel.app/stats` → 관리자 토큰 입력 → 대시보드 확인

> 커스텀 도메인을 붙이면 `CORS_ORIGINS`에 해당 도메인도 추가해야 합니다 (쉼표 구분).

---

## 다음 단계 (선택)

- **사용자 접근 제한**: 학교 이메일 인증(Supabase Auth 등)으로 채팅 자체를 구성원 전용화
- **사용량 제한**: 사용자/IP별 일일 질의 제한으로 API 비용 방어
- **관측**: Langfuse 연동으로 에이전트별 비용·품질 추적
