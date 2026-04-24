param(
    [switch]$CreateVenv,
    [switch]$InstallDeps,
    [switch]$UseExternalVenv,
    [string]$PythonExe = "",
    [string]$ExternalVenvRoot = "$HOME\.venvs",
    [string]$TempRoot = "$HOME\.tmp",
    [string]$PipCacheRoot = "$HOME\.pip-cache"
)

$ErrorActionPreference = "Stop"

function Write-Section($text) {
    Write-Host ""
    Write-Host "=== $text ===" -ForegroundColor Cyan
}

function Resolve-RepoRoot {
    if ($PSScriptRoot) {
        return (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
    }
    return (Get-Location).Path
}

$RepoRoot = Resolve-RepoRoot
Set-Location $RepoRoot

$RepoName = Split-Path $RepoRoot -Leaf
$ScriptsDir = Join-Path $RepoRoot "scripts"
$RepoLocalVenv = Join-Path $RepoRoot ".venv"
$ExternalVenvPath = Join-Path $ExternalVenvRoot $RepoName

if ($UseExternalVenv) {
    $SelectedVenv = $ExternalVenvPath
} else {
    $SelectedVenv = $RepoLocalVenv
}

$SelectedPython = ""
if ($PythonExe -and (Test-Path $PythonExe)) {
    $SelectedPython = (Resolve-Path $PythonExe).Path
} else {
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        $SelectedPython = "py -3.11"
    } else {
        $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
        if ($pythonCmd) {
            $SelectedPython = $pythonCmd.Source
        }
    }
}

if (-not $SelectedPython) {
    throw "Could not find a usable base Python. Install Python 3.11 or pass -PythonExe explicitly."
}

New-Item -ItemType Directory -Force -Path $TempRoot | Out-Null
New-Item -ItemType Directory -Force -Path $PipCacheRoot | Out-Null
if ($UseExternalVenv) {
    New-Item -ItemType Directory -Force -Path $ExternalVenvRoot | Out-Null
}

$env:TMP = $TempRoot
$env:TEMP = $TempRoot
$env:PIP_CACHE_DIR = $PipCacheRoot
$env:PYTHONDONTWRITEBYTECODE = "1"

$VenvPython = Join-Path $SelectedVenv "Scripts\python.exe"
$VenvPip = Join-Path $SelectedVenv "Scripts\pip.exe"

Write-Section "Bootstrap Context"
Write-Host "Repo root:        $RepoRoot"
Write-Host "Repo name:        $RepoName"
Write-Host "TMP/TEMP:         $($env:TMP)"
Write-Host "PIP_CACHE_DIR:    $($env:PIP_CACHE_DIR)"
Write-Host "Venv mode:        $(if ($UseExternalVenv) { 'external' } else { 'repo-local' })"
Write-Host "Selected venv:    $SelectedVenv"
Write-Host "Base Python:      $SelectedPython"

if ($CreateVenv -and -not (Test-Path $VenvPython)) {
    Write-Section "Creating virtual environment"
    if ($SelectedPython -eq "py -3.11") {
        & py -3.11 -m venv $SelectedVenv
    } else {
        & $SelectedPython -m venv $SelectedVenv
    }
}

if (-not (Test-Path $VenvPython)) {
    Write-Warning "Virtual environment does not exist yet."
    Write-Host "Create it with:" -ForegroundColor Yellow
    Write-Host "  .\scripts\bootstrap.cmd -CreateVenv $(if ($UseExternalVenv) { '-UseExternalVenv' } else { '' })" -ForegroundColor Yellow
} else {
    Write-Section "Virtual environment detected"
    Write-Host "Venv Python:      $VenvPython"
    Write-Host "Venv Pip:         $VenvPip"

    if ($InstallDeps) {
        Write-Section "Installing dependencies"
        & $VenvPython -m pip install --upgrade pip setuptools wheel
        if (Test-Path (Join-Path $RepoRoot "requirements.txt")) {
            & $VenvPython -m pip install --only-binary=:all: -r (Join-Path $RepoRoot "requirements.txt")
        } elseif (Test-Path (Join-Path $RepoRoot "pyproject.toml")) {
            & $VenvPython -m pip install --only-binary=:all: -e $RepoRoot
        } else {
            Write-Warning "No requirements.txt or pyproject.toml install target found."
        }
    }

    Write-Section "Recommended session setup"
    Write-Host "For this PowerShell session, use:"
    Write-Host "  `$env:TMP='$TempRoot'"
    Write-Host "  `$env:TEMP='$TempRoot'"
    Write-Host "  `$env:PIP_CACHE_DIR='$PipCacheRoot'"
    Write-Host "  & '$VenvPython' --version"

    Write-Section "Codex-facing interpreter path"
    Write-Host $VenvPython -ForegroundColor Green
}

Write-Section "Done"
