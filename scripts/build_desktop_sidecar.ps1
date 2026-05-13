param(
    [string]$OutputDirectory = "src-tauri/binaries",
    [string]$BuildSpec = "build_exe.spec",
    [string]$TargetTriple = "x86_64-pc-windows-msvc",
    [string]$SidecarName = "mexamplar-sidecar"
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $root

uv run pyinstaller --clean $BuildSpec
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null

$candidate = Get-ChildItem -Path "dist" -Recurse -File |
    Where-Object { $_.Extension -in @(".exe", "") -and $_.Name -match "Mexemplar|mexamplar|sidecar" } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

if (-not $candidate) {
    throw "No PyInstaller executable was found under dist/."
}

$extension = if ($IsWindows -or $env:OS -eq "Windows_NT") { ".exe" } else { "" }
$target = Join-Path $OutputDirectory "$SidecarName-$TargetTriple$extension"
Copy-Item -LiteralPath $candidate.FullName -Destination $target -Force
Write-Host "Copied sidecar binary to $target"
