@echo off
echo Building Cayde 420 executable...
echo.

REM Install dependencies if needed
python -m pip install -r requirements.txt --quiet

REM Build from the spec — single source of truth for the flags.
REM The spec used to carry --icon=build\QwythosAI.ico, which pointed into a
REM gitignored build/ dir that does not exist on a fresh clone. PyInstaller
REM fails on a missing icon path, so the icon entry was dropped.
pyinstaller --noconfirm Cayde420.spec

echo.
echo Build complete!
echo Output: dist\Cayde420.exe
echo.
pause