@echo off
REM Launch Claude Code with a clean environment to avoid tool-resolution issues

set "PATH=C:\Windows\System32;C:\Program Files\Python313;%PATH%"
set "JAVA_AWT_CANARY="
cd /d "%~dp0"
start "" "claude"
exit /b 0
