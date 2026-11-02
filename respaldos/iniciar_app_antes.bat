@echo off
chcp 65001 >nul
set PYTHONUTF8=1
echo ========================================================
echo   Iniciando RenderCV Studio Pro (Aplicacion Web Local)
echo ========================================================
cd /d "%~dp0"
python -m streamlit run app.py
pause

