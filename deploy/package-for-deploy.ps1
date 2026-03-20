# 在项目根目录执行：构建前端并打 zip 包（排除 node_modules、.venv、密钥等），便于上传到 AWS Linux
# 用法:  .\deploy\package-for-deploy.ps1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if (-not (Test-Path (Join-Path $Root "frontend\package.json"))) {
  Write-Error "请在 promanager 仓库根目录通过 deploy\package-for-deploy.ps1 调用"
}

Set-Location (Join-Path $Root "frontend")
if (-not (Test-Path "node_modules")) {
  npm ci
}
npm run build

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$outDir = Join-Path $Root "deploy\out"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$zipName = "promanager-deploy-$stamp.zip"
$zipPath = Join-Path $outDir $zipName

# 使用 tar（Windows 10+）生成 zip：先打 tar.gz 更简单，但用户要 zip —— 用 Compress-Archive 需逐个文件易超路径长度，改用 tar.gz
$tarName = "promanager-deploy-$stamp.tar.gz"
$tarPath = Join-Path $outDir $tarName

Push-Location $Root
try {
  # --exclude 语法为 GNU tar（Windows 自带 bsdtar 也支持部分）
  # Windows 自带 tar 一般为 bsdtar：逐条 exclude 路径
  tar -czvf $tarPath `
    --exclude=".git" `
    --exclude="frontend/node_modules" `
    --exclude="backend/.venv" `
    --exclude="backend/__pycache__" `
    --exclude="backend/.env" `
    --exclude="backend/data" `
    --exclude="deploy/out" `
    .
}
finally {
  Pop-Location
}

Write-Host "已生成: $tarPath"
Write-Host "上传到服务器后解压到目标目录，执行: chmod +x deploy/*.sh && ./deploy/build-on-server.sh"
Write-Host "再配置 backend/.env 并用 deploy/promanager.service 注册 systemd（见 deploy/README.md）"
