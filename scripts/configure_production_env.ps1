param(
    [string]$EnvPath = ".env"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function New-UrlSafeSecret {
    $bytes = New-Object byte[] 32
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($bytes)
    }
    finally {
        $generator.Dispose()
    }
    return [Convert]::ToBase64String($bytes).TrimEnd("=").Replace("+", "-").Replace("/", "_")
}

$resolvedPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($EnvPath)
if (-not (Test-Path -LiteralPath $resolvedPath)) {
    throw "找不到 $resolvedPath；请先将 .env.example 复制为 .env。"
}

$lines = [System.Collections.Generic.List[string]]::new()
$lines.AddRange([string[]](Get-Content -LiteralPath $resolvedPath))
$requiredValues = [ordered]@{
    POSTGRES_PASSWORD = New-UrlSafeSecret
    REDIS_PASSWORD = New-UrlSafeSecret
    MINIO_ROOT_USER = "lifepilot-admin"
    MINIO_ROOT_PASSWORD = New-UrlSafeSecret
}
$configured = [System.Collections.Generic.List[string]]::new()

foreach ($entry in $requiredValues.GetEnumerator()) {
    $prefix = "$($entry.Key)="
    $index = -1
    for ($position = 0; $position -lt $lines.Count; $position++) {
        if ($lines[$position].StartsWith($prefix, [StringComparison]::Ordinal)) {
            $index = $position
        }
    }

    if ($index -lt 0) {
        $lines.Add("$prefix$($entry.Value)")
        $configured.Add($entry.Key)
        continue
    }

    if ([string]::IsNullOrWhiteSpace($lines[$index].Substring($prefix.Length))) {
        $lines[$index] = "$prefix$($entry.Value)"
        $configured.Add($entry.Key)
    }
}

$encoding = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllLines($resolvedPath, $lines, $encoding)

if ($configured.Count -eq 0) {
    Write-Host "生产基础设施密钥已经配置；未覆盖任何现有值。" -ForegroundColor Green
}
else {
    Write-Host "已生成缺失配置（值未显示）：$($configured -join ', ')" -ForegroundColor Green
}
