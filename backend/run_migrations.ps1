# MoonTest 迁移一键执行（PowerShell，在 backend 目录运行）
# 11 个迁移全部幂等，重复执行安全
# 注意：迁移跑在 .env DATABASE_URL 指向的库（当前 = localhost:5433 pgvector 容器）

$ErrorActionPreference = "Continue"
$envFile = Join-Path $PSScriptRoot ".env"
$dbUser = "moontest"; $dbPass = "moontest123"; $dbName = "moontest"; $dbHost = "localhost"; $dbPort = "5433"
Get-Content $envFile | ForEach-Object {
    if ($_ -match "^DATABASE_URL=postgresql://([^:]+):([^@]+)@([^:]+):(\d+)/(\w+)") {
        $dbUser = $Matches[1]; $dbPass = $Matches[2]; $dbHost = $Matches[3]; $dbPort = $Matches[4]; $dbName = $Matches[5]
    }
}
Write-Host "目标: ${dbHost}:${dbPort}/${dbName} (user=$dbUser)" -ForegroundColor Cyan

$env:PGPASSWORD = $dbPass
$migrationDir = Join-Path $PSScriptRoot "migrations"
$scripts = Get-ChildItem "$migrationDir\*.sql" | Sort-Object Name
$fail = 0
foreach ($s in $scripts) {
    Write-Host "==> $($s.Name)" -ForegroundColor White
    $pgpsql = "D:\Program Files\PostgreSQL\16\bin\psql.exe"
    if (Test-Path $pgpsql) {
        & $pgpsql -h $dbHost -p $dbPort -U $dbUser -d $dbName -v ON_ERROR_STOP=1 -f $s.FullName 2>&1 | Out-Null
        $code = $LASTEXITCODE
    } else {
        Get-Content $s.FullName -Raw -Encoding UTF8 | docker exec -i moontest-pgvector psql -U $dbUser -d $dbName -v ON_ERROR_STOP=1 2>&1 | Out-Null
        $code = $LASTEXITCODE
    }
    if ($code -ne 0) { Write-Host "    FAILED" -ForegroundColor Red; $fail++ }
    else { Write-Host "    OK" -ForegroundColor Green }
}
Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue
Write-Host ""
if ($fail -eq 0) { Write-Host "全部 $($scripts.Count) 个迁移执行成功" -ForegroundColor Green }
else { Write-Host "$fail 个迁移失败，检查输出" -ForegroundColor Red }
