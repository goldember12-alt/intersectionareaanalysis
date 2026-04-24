param(
    [string]$Destination = "$env:USERPROFILE\source\IntersectionCrashAnalysis",
    [string]$RemoteUrl = "",
    [string]$Branch = "",
    [switch]$SkipClone,
    [switch]$SkipOverlay
)

$ErrorActionPreference = "Stop"

function Write-Section($Text) {
    Write-Host ""
    Write-Host "=== $Text ===" -ForegroundColor Cyan
}

function Resolve-RepoRoot {
    if ($PSScriptRoot) {
        return (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
    }
    return (Get-Location).Path
}

function Assert-Git {
    $git = Get-Command git -ErrorAction SilentlyContinue
    if (-not $git) {
        throw "Git is not available on PATH."
    }
}

function Get-GitValue($Args) {
    $value = (& git @Args 2>$null)
    if ($LASTEXITCODE -ne 0) {
        return ""
    }
    return ($value | Select-Object -First 1)
}

$SourceRoot = Resolve-RepoRoot
$Destination = [System.IO.Path]::GetFullPath($Destination)
$DestinationParent = Split-Path -Parent $Destination

Assert-Git

if (-not $RemoteUrl) {
    Push-Location $SourceRoot
    try {
        $RemoteUrl = Get-GitValue @("remote", "get-url", "origin")
    } finally {
        Pop-Location
    }
}

if (-not $RemoteUrl) {
    throw "Could not determine remote URL. Pass -RemoteUrl explicitly."
}

if (-not $Branch) {
    Push-Location $SourceRoot
    try {
        $Branch = Get-GitValue @("branch", "--show-current")
    } finally {
        Pop-Location
    }
}

if (-not $Branch) {
    $Branch = "main"
}

Write-Section "Copy Plan"
Write-Host "Source:      $SourceRoot"
Write-Host "Destination: $Destination"
Write-Host "Remote:      $RemoteUrl"
Write-Host "Branch:      $Branch"

if (-not (Test-Path -LiteralPath $DestinationParent)) {
    New-Item -ItemType Directory -Force -Path $DestinationParent | Out-Null
}

if ((Test-Path -LiteralPath $Destination) -and -not $SkipClone) {
    $existingItems = Get-ChildItem -LiteralPath $Destination -Force -ErrorAction SilentlyContinue
    if ($existingItems) {
        throw "Destination already exists and is not empty: $Destination. Choose a new destination or pass -SkipClone to use the existing clone."
    }
}

if (-not $SkipClone) {
    Write-Section "Sparse Partial Clone"
    & git clone --filter=blob:none --sparse --branch $Branch $RemoteUrl $Destination
    if ($LASTEXITCODE -ne 0) {
        throw "git clone failed."
    }
}

Push-Location $Destination
try {
    Write-Section "Sparse Checkout Rules"
    & git sparse-checkout init --no-cone
    if ($LASTEXITCODE -ne 0) {
        throw "git sparse-checkout init failed."
    }

    $SparseFile = Join-Path $Destination ".git\info\sparse-checkout"
    @(
        "/*",
        "!/.venv/",
        "!/artifacts/",
        "!/legacy/",
        "!/work/",
        "!/Intersection Crash Analysis Layers/"
    ) | Set-Content -LiteralPath $SparseFile -Encoding ascii

    & git read-tree -mu HEAD
    if ($LASTEXITCODE -ne 0) {
        throw "git sparse checkout update failed."
    }
} finally {
    Pop-Location
}

if (-not $SkipOverlay) {
    Write-Section "Overlay Current Working Files"
    $excludeDirs = @(
        ".git",
        ".venv",
        "artifacts",
        "legacy",
        "work",
        "Intersection Crash Analysis Layers",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache"
    )
    $excludeFiles = @("*.pyc", "*.pyo", "*.log")

    & robocopy $SourceRoot $Destination /E /XD $excludeDirs /XF $excludeFiles /R:2 /W:1 /NFL /NDL /NP
    $robocopyCode = $LASTEXITCODE
    if ($robocopyCode -gt 7) {
        throw "robocopy failed with exit code $robocopyCode."
    }
}

Push-Location $Destination
try {
    Write-Section "Stage Removal of Ignored Large Directories"
    & git rm -r --cached --sparse --ignore-unmatch -- "Intersection Crash Analysis Layers" artifacts legacy
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "git rm with --sparse failed; retrying without --sparse."
        & git rm -r --cached --ignore-unmatch -- "Intersection Crash Analysis Layers" artifacts legacy
        if ($LASTEXITCODE -ne 0) {
            throw "git rm --cached failed."
        }
    }

    Write-Section "Resulting Status"
    & git status --short

    Write-Section "Next Steps"
    Write-Host "Review the new copy:"
    Write-Host "  cd `"$Destination`""
    Write-Host "  git status"
    Write-Host ""
    Write-Host "Ignored local working-state directories are intentionally excluded from this copy:"
    Write-Host "  artifacts"
    Write-Host "  work"
    Write-Host "  legacy"
    Write-Host "  Intersection Crash Analysis Layers"
    Write-Host ""
    Write-Host "If you need the new copy to replace an existing OneDrive working tree immediately, hydrate those directories separately."
    Write-Host "Do not copy a repo-local .venv by default; use bootstrap to discover or recreate the active interpreter."
    Write-Host ""
    Write-Host "If it looks right, commit from the new local copy."
} finally {
    Pop-Location
}


