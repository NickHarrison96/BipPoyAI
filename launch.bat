@echo off
title Qwythos AI
cd /d "%~dp0"
python main.py
if errorlevel 1 (
    echo.
    echo Something went wrong. Make sure Python is installed and in your PATH.
    echo Also run: pip install -r requirements.txt
    pause
)
