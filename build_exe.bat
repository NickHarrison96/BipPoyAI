@echo off
echo Building Cayde 420 executable...
echo.

REM Install dependencies if needed
python -m pip install -r requirements.txt --quiet

REM Build from the spec — single source of truth for the flags.
REM The spec used to carry an icon reference that pointed into a gitignored
REM build/ directory (no longer present). PyInstaller would have failed on
REM a missing icon path, so the icon was dropped from the spec.
pyinstaller --noconfirm --clean Cayde420.spec

echo.
echo Build complete!
echo Output: dist\Cayde420.exe
echo.
pause