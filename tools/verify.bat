@echo off
cd /d "%~dp0\.."
python -m py_compile app.py tools\check.py
if errorlevel 1 exit /b 1
echo COMPILE_OK
node tools\check_js.js
