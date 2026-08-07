# 내 PC를 서버로 실행: API + 웹(프로덕션) + Tailscale Funnel(고정 주소)
# 사용법: PowerShell에서  .\start-server.ps1
# 종료:   .\start-server.ps1 -Stop

param([switch]$Stop)

$root = $PSScriptRoot
$api = Join-Path $root "v2\api"
$web = Join-Path $root "v2\web"
$tailscale = "C:\Program Files\Tailscale\tailscale.exe"

function Stop-ByPort($port) {
    $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($conn) { Stop-Process -Id $conn.OwningProcess -Force -Confirm:$false }
}

if ($Stop) {
    Stop-ByPort 8000
    Stop-ByPort 3000
    # Funnel 설정은 유지 (서버만 내려감). 완전히 끄려면: tailscale funnel reset
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

# 3) Tailscale Funnel (고정 주소 — 설정은 재부팅 후에도 유지됨)
$status = & $tailscale funnel status 2>&1 | Out-String
if ($status -match "No serve config") {
    & $tailscale funnel --bg 3000 | Out-Null
    $status = & $tailscale funnel status 2>&1 | Out-String
}
Write-Host "[3/3] Tailscale Funnel 확인"

$match = [regex]::Match($status, "https://[a-z0-9.-]+\.ts\.net")
if ($match.Success) {
    Write-Host ""
    Write-Host "  공개 주소:  $($match.Value)" -ForegroundColor Green
    Write-Host ""
    Write-Host "  * 이 주소는 고정입니다 (재시작해도 동일)."
    Write-Host "  * PC가 켜져 있고 절전 모드가 아니어야 접속됩니다."
} else {
    Write-Host "Funnel이 아직 설정되지 않았습니다. 'tailscale funnel --bg 3000' 실행 후 안내 링크에서 활성화하세요." -ForegroundColor Red
}
