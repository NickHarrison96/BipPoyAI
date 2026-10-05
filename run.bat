@echo off
REM BipPoyAI CLI Test Runner - Verbose startup for testing tool capabilities

echo [INFO] Starting BipPoyAI test environment...
where python >nul 2>nul || echo [WARN] Python not in PATH; using default interpreter.

if exist main.py (
    echo [OK] Found main.py in current directory (/c/Users/nick/Documents/GitHub/BipPoyAI)
    echo [RUN] Launching main.py...
    python main.py %*
) else if exist .\main.py (
    echo [OK] Found main.py using relative path.
    echo [RUN] Launching main.py...
    python .\main.py %*
) else (
    echo [WARN] main.py not found in /c/Users/nick/Documents/GitHub/BipPoyAI or current dir.
    echo       Creating a stub for testing purposes:

    type nul > main.py
    echo "print('Hello from test runner!')" > main.py
)
