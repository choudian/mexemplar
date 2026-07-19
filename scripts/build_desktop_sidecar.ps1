param(
    [string]$OutputDirectory = "src-tauri/binaries",
    [string]$BuildSpec = "",
    [string]$TargetTriple = "x86_64-pc-windows-msvc",
    [string]$SidecarName = "mexamplar-sidecar"
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$rootPath = $root.Path
Set-Location $root

$extension = if ($IsWindows -or $env:OS -eq "Windows_NT") { ".exe" } else { "" }
$candidate = Join-Path "dist" "$SidecarName$extension"

# 先移除精确的预期产物；构建失败后绝不能把旧 dist 文件误当成本次成功产物复制。
if (Test-Path -LiteralPath $candidate) {
    Remove-Item -LiteralPath $candidate -Force
}

if ($BuildSpec) {
    if (-not (Test-Path -LiteralPath $BuildSpec)) {
        throw "PyInstaller spec not found: $BuildSpec"
    }
    & uv run pyinstaller --clean --noconfirm $BuildSpec
} else {
    $dataSeparator = [IO.Path]::PathSeparator
    $browserExtensionSource = Join-Path $rootPath "src/recording/browser_extension"
    $browserExtensionData = "${browserExtensionSource}${dataSeparator}src/recording/browser_extension"
    $entryPoint = Join-Path $rootPath "src/desktop_api/__main__.py"
    & uv run pyinstaller `
        --clean `
        --noconfirm `
        --onefile `
        --name $SidecarName `
        --specpath "build" `
        --paths $rootPath `
        --add-data $browserExtensionData `
        $entryPoint
}

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller sidecar build failed with exit code $LASTEXITCODE."
}

if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
    throw "Expected PyInstaller sidecar was not created: $candidate"
}

New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$target = Join-Path $OutputDirectory "$SidecarName-$TargetTriple$extension"
Copy-Item -LiteralPath $candidate -Destination $target -Force
Write-Host "Copied sidecar binary to $target"
