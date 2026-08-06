# 배포 가이드

두 가지 배포 경로가 있습니다.

- **A. 내 PC + Cloudflare Tunnel** — 비용 0원, 시험 운영·베타용. PC가 켜져 있을 때만 서비스됨
- **B. VPS + Docker Compose** — 24시간 정식 운영용 (아래 상세)

## A. 내 PC를 서버로 (Cloudflare Tunnel)

요구사항: cloudflared 설치 (`winget install Cloudflare.cloudflared`)

```powershell
.\start-server.ps1        # API + 웹(프로덕션) + 터널 실행, 공개 URL 출력
.\start-server.ps1 -Stop  # 전체 종료
```

- 발급되는 `https://xxx.trycloudflare.com` 주소를 공유하면 외부에서 바로 접속 가능
- 임시 터널이라 재시작 시 주소가 바뀜 — 고정 주소가 필요하면 Cloudflare 계정에 도메인을 연결해
  [Named Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/)로 전환
- Windows 전원 설정에서 절전 모드를 꺼두어야 함 (설정 → 시스템 → 전원 → 절전 안 함)

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

## 다음 단계 (선택)

- **접근 제한**: 학교 구성원만 사용하도록 Caddy `basic_auth` 또는 학교 이메일 인증(Supabase Auth) 추가
- **사용량 제한**: 사용자/IP별 일일 질의 제한으로 API 비용 방어
- **관측**: Langfuse 연동으로 에이전트별 비용·품질 추적
