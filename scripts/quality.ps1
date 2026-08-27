Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-QualityStep {
    param(
        [Parameter(Mandatory)]
        [string]$Name,

        [Parameter(Mandatory)]
        [scriptblock]$Action
    )

    Write-Host ""
    Write-Host "==> $Name" -ForegroundColor Cyan

    & $Action

    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE"
    }
}

$projectRoot = Split-Path -Parent $PSScriptRoot

Push-Location $projectRoot

try {
    $pythonVersion = (
        python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    ).Trim()

    if ($LASTEXITCODE -ne 0) {
        throw "Python could not be executed. Activate the lifepilot environment first."
    }

    if ($pythonVersion -ne "3.11") {
        throw "Python $pythonVersion detected. This project requires Python 3.11."
    }

    Write-Host "Python environment passed: $pythonVersion" -ForegroundColor Green

    Invoke-QualityStep "Ruff lint" {
        python -m ruff check .
    }

    Invoke-QualityStep "Ruff format check" {
        python -m ruff format --check .
    }

    Invoke-QualityStep "Mypy type check" {
        python -m mypy app
    }

    Invoke-QualityStep "Pytest with branch coverage" {
        python -m pytest --cov=app --cov-report=term-missing --cov-report=html
    }

    Write-Host ""
    Write-Host "All quality checks passed." -ForegroundColor Green
}
finally {
    Pop-Location
}
