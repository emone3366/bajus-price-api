@echo off
echo ========================================================
echo   BAJUS Price API - Local Development Server
echo ========================================================
echo.

:: Set environment variables to force local zero-dependency mode
set POSTGRES_HOST=sqlite
set REDIS_HOST=memory

echo [INFO] Running in ZERO-DEPENDENCY mode.
echo [INFO] Database: SQLite (local file)
echo [INFO] Cache: In-Memory (Redis disabled)
echo.

:: Check if virtual environment exists
if not exist .venv\Scripts\activate.bat (
    echo [ERROR] Virtual environment not found. 
    echo Please run 'python -m venv .venv' and install requirements first.
    pause
    exit /b 1
)

:: Activate venv and run
call .venv\Scripts\activate.bat
echo [INFO] Starting FastAPI server...
uvicorn src.main:app --reload
