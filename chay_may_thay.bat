@echo off
chcp 65001 >nul
cd /d "%~dp0"
title CodeGuard - May thay (KHONG dong cua so nay trong gio thi)
where py >/dev/null 2>nul
if %errorlevel%==0 (
  py maythay.py
) else (
  python maythay.py
)
pause
