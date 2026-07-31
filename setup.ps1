param([switch]$SkipFrontendBuild)

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$FrontendDir = Join-Path $ProjectDir "frontend"

if (-not (Test-Path -LiteralPath $PythonExe)) {
  python -m venv (Join-Path $ProjectDir ".venv")
}

& $PythonExe -m pip install -r (Join-Path $ProjectDir "backend\requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Python dependency installation failed." }

if (-not $SkipFrontendBuild) {
  $oldHusky = $env:HUSKY
  $env:HUSKY = "0"
  try {
    Push-Location $FrontendDir
    corepack pnpm install --frozen-lockfile
    if ($LASTEXITCODE -ne 0) { throw "Frontend dependency installation failed." }
    corepack pnpm build
    if ($LASTEXITCODE -ne 0) { throw "Frontend production build failed." }
  }
  finally {
    Pop-Location
    $env:HUSKY = $oldHusky
  }
}

Write-Host "Dependencies and frontend build are ready." -ForegroundColor Green
