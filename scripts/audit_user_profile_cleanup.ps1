param(
    [string]$ProfileRoot = $env:USERPROFILE,
    [int]$Top = 40
)

$ErrorActionPreference = "Stop"

function Get-DirectorySize {
    param([string]$Path)
    try {
        $sum = Get-ChildItem -LiteralPath $Path -Recurse -File -Force -ErrorAction SilentlyContinue |
            Measure-Object -Property Length -Sum
        return [int64]($sum.Sum)
    } catch {
        return $null
    }
}

Write-Host "Profile cleanup audit only. No files will be changed." -ForegroundColor Cyan
Write-Host "Profile root: $ProfileRoot"
Write-Host ""

Write-Host "Top-level directory sizes:" -ForegroundColor Cyan
Get-ChildItem -LiteralPath $ProfileRoot -Directory -Force |
    Where-Object {
        $_.Name -notin @(
            "AppData",
            "Application Data",
            "Cookies",
            "Local Settings",
            "My Documents",
            "NetHood",
            "PrintHood",
            "Recent",
            "SendTo",
            "Start Menu",
            "Templates"
        )
    } |
    ForEach-Object {
        [PSCustomObject]@{
            SizeGB = [math]::Round((Get-DirectorySize $_.FullName) / 1GB, 2)
            LastWriteTime = $_.LastWriteTime
            Path = $_.FullName
        }
    } |
    Sort-Object SizeGB -Descending |
    Select-Object -First $Top |
    Format-Table -AutoSize

Write-Host ""
Write-Host "Large top-level files:" -ForegroundColor Cyan
Get-ChildItem -LiteralPath $ProfileRoot -File -Force |
    Where-Object { $_.Length -ge 10MB } |
    Sort-Object Length -Descending |
    Select-Object @{Name="SizeMB";Expression={[math]::Round($_.Length / 1MB, 2)}}, LastWriteTime, FullName |
    Format-Table -AutoSize

Write-Host ""
Write-Host "Likely cleanup candidates to review manually:" -ForegroundColor Cyan
Get-ChildItem -LiteralPath $ProfileRoot -Force |
    Where-Object {
        $_.Name -in @(
            ".pip-cache",
            ".tmp",
            ".venvs",
            "IntersectionCrashAnalysis_publish",
            "IntersectionCrashAnalysis.zip",
            "node-v24.14.1-win-x64",
            "Graphviz-14.1.5-win64"
        )
    } |
    Select-Object Mode, LastWriteTime, FullName |
    Format-Table -AutoSize

