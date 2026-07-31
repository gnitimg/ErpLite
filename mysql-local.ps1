param(
  [ValidateSet("start", "stop", "status")]
  [string]$Action = "start"
)

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$DataDir = Join-Path $ProjectDir ".mysql-data"
$UndoDir = Join-Path $ProjectDir ".mysql-undo"
$InitializedFile = Join-Path $ProjectDir ".mysql-initialized"
$LogDir = Join-Path $ProjectDir "logs"
$ErrorLog = Join-Path $LogDir "mysql.err.log"
$PidFile = Join-Path $DataDir "mysql-local.pid"
$ConfigFile = Join-Path $ProjectDir ".mysql-local.ini"
$InitConfigFile = Join-Path $ProjectDir ".mysql-init.ini"
$Port = 3307
$MysqldExe = (Get-Command mysqld -ErrorAction Stop).Source
$MysqlExe = (Get-Command mysql -ErrorAction Stop).Source
$BaseDir = Split-Path -Parent (Split-Path -Parent $MysqldExe)

function Get-LocalMySqlProcess {
  if (-not (Test-Path -LiteralPath $PidFile)) { return $null }
  $savedPid = [int](Get-Content -LiteralPath $PidFile -Raw)
  return Get-Process -Id $savedPid -ErrorAction SilentlyContinue
}

function Wait-ForMySql {
  for ($attempt = 0; $attempt -lt 40; $attempt++) {
    $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($connection) { return }
    Start-Sleep -Milliseconds 500
  }
  throw "Local MySQL did not start. Check $ErrorLog"
}

switch ($Action) {
  "start" {
    $running = Get-LocalMySqlProcess
    if ($running) { Write-Host "Local MySQL is already running (PID $($running.Id), port $Port)."; break }

    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
    @(
      "[mysqld]",
      "basedir=$($BaseDir.Replace('\', '/'))",
      "datadir=$($DataDir.Replace('\', '/'))",
      "innodb-undo-directory=$($UndoDir.Replace('\', '/'))",
      "port=$Port",
      "bind-address=127.0.0.1",
      "mysqlx=0",
      "character-set-server=utf8mb4",
      "collation-server=utf8mb4_0900_ai_ci",
      "pid-file=$($PidFile.Replace('\', '/'))",
      "log-error=$($ErrorLog.Replace('\', '/'))"
    ) | Set-Content -LiteralPath $ConfigFile -Encoding Ascii
    @(
      "[mysqld]",
      "basedir=$($BaseDir.Replace('\', '/'))",
      "datadir=$($DataDir.Replace('\', '/'))",
      "innodb-undo-directory=$($UndoDir.Replace('\', '/'))"
    ) | Set-Content -LiteralPath $InitConfigFile -Encoding Ascii
    if (-not (Test-Path -LiteralPath (Join-Path $DataDir "mysql"))) {
      New-Item -ItemType Directory -Path $DataDir -Force | Out-Null
      New-Item -ItemType Directory -Path $UndoDir -Force | Out-Null
      & $MysqldExe "--defaults-file=$InitConfigFile" --initialize-insecure
      if ($LASTEXITCODE -ne 0) { throw "MySQL data directory initialization failed." }
    }

    $arguments = @("--defaults-file=$ConfigFile")
    Start-Process -FilePath $MysqldExe -ArgumentList $arguments -WorkingDirectory $ProjectDir -WindowStyle Hidden | Out-Null
    Wait-ForMySql

    if (-not (Test-Path -LiteralPath $InitializedFile)) {
      Get-Content -LiteralPath (Join-Path $ProjectDir "database\init_mysql.sql") -Raw |
        & $MysqlExe --protocol=TCP --host=127.0.0.1 --port=$Port --user=root
      if ($LASTEXITCODE -ne 0) { throw "ERP database initialization failed." }
      Set-Content -LiteralPath $InitializedFile -Value (Get-Date -Format o)
    }
    $running = Get-LocalMySqlProcess
    Write-Host "Local MySQL is ready (PID $($running.Id), 127.0.0.1:$Port)." -ForegroundColor Green
  }
  "stop" {
    $running = Get-LocalMySqlProcess
    if ($running) {
      $oldPassword = $env:MYSQL_PWD
      $env:MYSQL_PWD = "LocalRoot@2026!"
      try { & (Join-Path (Split-Path -Parent $MysqlExe) "mysqladmin.exe") --protocol=TCP --host=127.0.0.1 --port=$Port --user=root shutdown }
      finally { $env:MYSQL_PWD = $oldPassword }
      Write-Host "Local MySQL stopped." -ForegroundColor Yellow
    }
    else { Write-Host "Local MySQL is not running." }
  }
  "status" {
    $running = Get-LocalMySqlProcess
    if ($running) { Write-Host "Local MySQL is running (PID $($running.Id), port $Port)." -ForegroundColor Green }
    else { Write-Host "Local MySQL is not running." -ForegroundColor Yellow }
  }
}
