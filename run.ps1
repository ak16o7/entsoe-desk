Set-Location $PSScriptRoot
if (!(Test-Path .env)) { Copy-Item .env.example .env; Write-Host "Created .env - add your ENTSOE_API_KEY, then run again."; exit 1 }
if (!(Test-Path .venv)) { python -m venv .venv }
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
