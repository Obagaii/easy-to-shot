$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
$FrontendDirectory = Join-Path $RepoRoot 'frontend'
$OutputDirectory = Join-Path $FrontendDirectory 'dist'

function Invoke-FrontendBuild {
    param([string] $WorkingDirectory)

    Push-Location $WorkingDirectory
    try {
        & npm ci
        if ($LASTEXITCODE -ne 0) { throw 'npm ci 失败' }
        & npm run typecheck
        if ($LASTEXITCODE -ne 0) { throw 'TypeScript 检查失败' }
        & npm run build
        if ($LASTEXITCODE -ne 0) { throw 'Vite 构建失败' }
    }
    finally {
        Pop-Location
    }
}

Invoke-FrontendBuild -WorkingDirectory $FrontendDirectory

$IndexPath = Join-Path $OutputDirectory 'index.html'
if (-not (Test-Path $IndexPath)) {
    throw "静态产物缺少 index.html：$IndexPath"
}

Write-Output "静态产物位置：$OutputDirectory"
