# 带染色的日志 tail：ERROR 行整行红、WARNING 行整行黄，其余原样。
# 行格式: yyyyMMdd HH:mm:ss,SSS | LEVEL | ... （级别在第 2 个 | 分隔字段）
param(
    [Parameter(Mandatory=$true)][string]$File,
    [int]$Tail = 30
)
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$red = "$([char]27)[91m"; $yellow = "$([char]27)[33m"; $reset = "$([char]27)[0m"

Get-Content $File -Tail $Tail -Wait -Encoding UTF8 | ForEach-Object {
    if ($_ -match '^\S+ \S+ \| ERROR\s+\|') {
        Write-Host ($red + $_ + $reset)
    } elseif ($_ -match '^\S+ \S+ \| (WARNING|WARN)\s+\|') {
        Write-Host ($yellow + $_ + $reset)
    } else {
        Write-Host $_
    }
}
