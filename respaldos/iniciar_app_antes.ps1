$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location $PSScriptRoot
Write-Host "🚀 Abriendo RenderCV Studio Pro en tu navegador..." -ForegroundColor Cyan
python -m streamlit run app.py

