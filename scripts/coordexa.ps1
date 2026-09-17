param(
    [ValidateSet('start', 'stop', 'restart', 'status', 'logs', 'verify', 'test', 'benchmark')]
    [string]$Command = 'status',
    [string]$Service = ''
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot

function Wait-CoordexaStack {
    param([int]$TimeoutSeconds = 120)

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $required = @('backend', 'chromadb', 'frontend', 'prometheus', 'redis')
    do {
        $items = @()
        $lines = docker compose ps --format json 2>$null
        if ($LASTEXITCODE -eq 0) {
            $items = @($lines | Where-Object { $_ } | ForEach-Object { $_ | ConvertFrom-Json })
        }
        $byService = @{}
        foreach ($item in $items) { $byService[$item.Service] = $item }

        $ready = $true
        foreach ($name in $required) {
            if (-not $byService.ContainsKey($name) -or $byService[$name].State -ne 'running') {
                $ready = $false
                break
            }
        }
        foreach ($name in @('backend', 'chromadb', 'redis')) {
            if ($ready -and $byService[$name].Health -ne 'healthy') {
                $ready = $false
                break
            }
        }
        if ($ready) {
            try {
                $targetPayload = Invoke-RestMethod `
                    -Uri 'http://localhost:9190/api/v1/targets' `
                    -TimeoutSec 3
                $targets = @($targetPayload.data.activeTargets)
                $unhealthyTargets = @($targets | Where-Object { $_.health -ne 'up' })
                if ($targets.Count -lt 2 -or $unhealthyTargets.Count -gt 0) {
                    $ready = $false
                }
            }
            catch {
                $ready = $false
            }
        }
        if ($ready) { return }
        Start-Sleep -Seconds 3
    } while ((Get-Date) -lt $deadline)

    throw "等待 Coordexa 服务健康超时（${TimeoutSeconds}秒）。请运行 scripts/coordexa.ps1 logs 查看日志。"
}

Push-Location $ProjectRoot
try {
    switch ($Command) {
        'start' {
            if (-not (Test-Path -LiteralPath '.env')) {
                throw '缺少 .env。请先复制 .env.example，并填写自己的模型服务配置。'
            }
            if ((Get-Content -LiteralPath '.env' -Raw) -match 'replace_with_your_key') {
                throw '.env 仍包含示例密钥，请先替换后再启动。'
            }
            docker compose up -d --build
            if ($LASTEXITCODE -ne 0) { throw 'Docker Compose 启动失败。' }
            Wait-CoordexaStack
            python scripts/verify_stack.py
            if ($LASTEXITCODE -ne 0) { throw '服务已启动，但验收检查未全部通过。' }
        }
        'stop' {
            docker compose stop
        }
        'restart' {
            docker compose restart
            if ($LASTEXITCODE -ne 0) { throw 'Docker Compose 重启失败。' }
            Wait-CoordexaStack
            python scripts/verify_stack.py
        }
        'status' {
            docker compose ps
        }
        'logs' {
            if ($Service) { docker compose logs --tail 200 $Service }
            else { docker compose logs --tail 200 }
        }
        'verify' {
            python scripts/verify_stack.py
        }
        'test' {
            docker compose --profile test run --rm --build tests
        }
        'benchmark' {
            python scripts/run_benchmark.py --base-url http://localhost:8200 --output evaluation/results/coordexa_latest_benchmark.json
        }
    }
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
finally {
    Pop-Location
}
