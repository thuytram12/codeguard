@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Cham Tu Luan (KHONG dong cua so nay khi dang cham bai)
set PY=python
where py >nul 2>nul && set PY=py
%PY% -c "import anthropic" 2>nul || (
  echo Dang cai thu vien anthropic lan dau, vui long cho...
  %PY% -m pip install --upgrade anthropic
)
%PY% chambai.py
pause
