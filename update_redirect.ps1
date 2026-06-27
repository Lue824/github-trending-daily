# PowerShell 脚本：更新 GitHub Pages 跳转地址
# 用法：当 Cloudflare Tunnel URL 变化时，运行此脚本更新跳转页面
# .\update_redirect.ps1

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

Write-Host "=== 更新 GitHub Pages 跳转地址 ===" -ForegroundColor Cyan

# 1. 读取 current_url.txt 获取最新 tunnel URL
$urlFile = Join-Path $projectRoot "current_url.txt"
$urlFileAlt = Join-Path $projectRoot "data\current_url.txt"

$newUrl = ""
if (Test-Path $urlFile) {
    $newUrl = (Get-Content $urlFile -Raw).Trim()
} elseif (Test-Path $urlFileAlt) {
    $newUrl = (Get-Content $urlFileAlt -Raw).Trim()
}

if (-not $newUrl -or -not $newUrl.StartsWith("https://")) {
    Write-Host "[错误] current_url.txt 中没有有效的 tunnel URL" -ForegroundColor Red
    Write-Host "请先运行 .\start_tunnel.ps1 启动隧道，再运行此脚本" -ForegroundColor Yellow
    exit 1
}

Write-Host "[1/4] 读取到最新 tunnel URL: $newUrl" -ForegroundColor Green

# 2. 读取当前 redirect.json
$redirectFile = Join-Path $projectRoot "redirect.json"
$currentUrl = ""
if (Test-Path $redirectFile) {
    $current = Get-Content $redirectFile -Raw | ConvertFrom-Json
    $currentUrl = $current.url
}

if ($newUrl -eq $currentUrl) {
    Write-Host "[跳过] URL 未变化（$newUrl），无需更新" -ForegroundColor Yellow
    exit 0
}

Write-Host "[2/4] URL 已变化：" -ForegroundColor Cyan
Write-Host "  旧: $currentUrl" -ForegroundColor DarkGray
Write-Host "  新: $newUrl" -ForegroundColor Green

# 3. 更新 redirect.json
$timestamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd HH:mm:ss") + " UTC"
$redirect = @{
    url = $newUrl
    updated_at = $timestamp
    status = "online"
} | ConvertTo-Json -Depth 3

$redirect | Out-File -FilePath $redirectFile -Encoding utf8 -NoNewline
Write-Host "[3/4] 已更新 redirect.json" -ForegroundColor Green

# 4. commit 并 push 到 GitHub
Write-Host "[4/4] 推送到 GitHub..." -ForegroundColor Cyan
git add redirect.json
git commit -m "Update redirect URL: $newUrl"
git push origin main

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "=== 完成 ===" -ForegroundColor Green
    Write-Host "GitHub Pages 跳转地址已更新" -ForegroundColor Green
    Write-Host "固定跳转页: https://lue824.github.io/github-trending-daily/" -ForegroundColor Cyan
    Write-Host "用户访问固定页面会自动跳转到: $newUrl" -ForegroundColor Green
    Write-Host ""
    Write-Host "注意：GitHub Pages 缓存约 1-2 分钟生效" -ForegroundColor Yellow
} else {
    Write-Host "[错误] git push 失败，请检查网络或权限" -ForegroundColor Red
    exit 1
}
