@echo off
rem Mo cong 8765 (TCP) va 8766 (UDP) tren tuong lua Windows cho CodeGuard.
rem Bam chuot phai vao file nay, chon "Run as administrator".
net session >/dev/null 2>&1
if %errorlevel% neq 0 (
  echo.
  echo  Can quyen quan tri. Hay bam chuot phai vao file nay va chon "Run as administrator".
  echo.
  pause
  exit /b
)
netsh advfirewall firewall delete rule name="CodeGuard TCP 8765" >/dev/null 2>&1
netsh advfirewall firewall add rule name="CodeGuard TCP 8765" dir=in action=allow protocol=TCP localport=8765 profile=any
netsh advfirewall firewall delete rule name="CodeGuard UDP 8766" >/dev/null 2>&1
netsh advfirewall firewall add rule name="CodeGuard UDP 8766" dir=in action=allow protocol=UDP localport=8766 profile=any
echo.
echo  Da mo tuong lua cho CodeGuard xong.
pause
