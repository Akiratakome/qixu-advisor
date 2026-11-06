$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$env:UV_CACHE_DIR = Join-Path $projectRoot '.cache/uv'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $projectRoot '.cache/python'
uv sync --locked
if ($LASTEXITCODE -ne 0) { throw '依赖安装失败，请检查上方错误。' }
# 某些 Windows 应用控制策略不接受 uv 的启动器；改用 Python 标准 venv 启动器。
$pythonPath = uv python find 3.12
if ($LASTEXITCODE -eq 0) { & $pythonPath -m venv .venv --without-pip }
