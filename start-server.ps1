# 내 PC를 서버로 실행: API + 웹(프로덕션) + Cloudflare 터널
# 사용법: PowerShell에서  .\start-server.ps1
# 종료:   .\start-server.ps1 -Stop

param([switch]$Stop)

$root = $PSScriptRoot
$api = Join-Path $root "v2\api"
$web = Join-Path $root "v2\web"
$cloudflared = "C:\Program Files (x86)\cloudflared\cloudflared.exe"
$tunnelLog = Join-Path $env:TEMP "regulation-ai-tunnel.log"

function Stop-ByPort($port) {
    $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($conn) { Stop-Process -Id $conn.OwningProcess -Force -Confirm:$false }
}

if ($Stop) {
    Stop-ByPort 8000
    Stop-ByPort 3000
    Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -Confirm:$false
    Write-Host "서버를 모두 종료했습니다." -ForegroundColor Yellow
    exit 0
}

Write-Host "== 학생회 규정 AI 서버 시작 ==" -ForegroundColor Cyan

# 1) API (uvicorn)
if (-not (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue)) {
    Start-Process -WindowStyle Hidden -WorkingDirectory $api `
        -FilePath "$api\.venv\Scripts\python.exe" `
        -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"
    Write-Host "[1/3] API 서버 시작 (port 8000)"
} else {
    Write-Host "[1/3] API 서버 이미 실행 중"
}

# 2) 웹 (Next.js 프로덕션) — 빌드가 없으면 same-origin 모드로 빌드
if (-not (Test-Path "$web\.next\BUILD_ID")) {
    Write-Host "      웹 프로덕션 빌드 중... (최초 1회)"
    Push-Location $web
    $env:NEXT_PUBLIC_API_URL = "/"
    npm run build | Out-Null
    Pop-Location
}
if (-not (Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue)) {
    Start-Process -WindowStyle Hidden -WorkingDirectory $web `
        -FilePath "cmd.exe" -ArgumentList "/c", "npx next start -p 3000"
    Write-Host "[2/3] 웹 서버 시작 (port 3000)"
} else {
    Write-Host "[2/3] 웹 서버 이미 실행 중"
}

# 3) Cloudflare 터널
Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -Confirm:$false
Remove-Item $tunnelLog -ErrorAction SilentlyContinue
Start-Process -WindowStyle Hidden -FilePath $cloudflared `
    -ArgumentList "tunnel", "--url", "http://localhost:3000" `
    -RedirectStandardError $tunnelLog
Write-Host "[3/3] Cloudflare 터널 연결 중..."

# 공개 URL 출력
$url = $null
foreach ($i in 1..20) {
    Start-Sleep -Seconds 2
    if (Test-Path $tunnelLog) {
        $match = Select-String -Path $tunnelLog -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" | Select-Object -First 1
        if ($match) { $url = $match.Matches[0].Value; break }
    }
}

if ($url) {
    Write-Host ""
    Write-Host "  공개 주소:  $url" -ForegroundColor Green
    Write-Host ""
    Write-Host "  * 이 주소는 터널을 재시작할 때마다 바뀝니다 (임시 터널)."
    Write-Host "  * PC가 켜져 있고 절전 모드가 아니어야 접속됩니다."
} else {
    Write-Host "터널 URL을 가져오지 못했습니다. 로그 확인: $tunnelLog" -ForegroundColor Red
}
