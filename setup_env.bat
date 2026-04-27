@echo off
setlocal

echo ========================================
echo  AI JobSearch - Conda Environment Setup
echo ========================================
echo.

REM Check if conda is available
conda --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Conda not found. Please install Anaconda or Miniconda first.
    pause
    exit /b 1
)

echo [1/4] Creating conda environment "jobsearch" (Python 3.11)...
conda create -n jobsearch python=3.11 -y
if %errorlevel% neq 0 (
    echo [ERROR] Failed to create conda environment.
    pause
    exit /b 1
)

echo.
echo [2/4] Activating environment...
call conda activate jobsearch
if %errorlevel% neq 0 (
    echo [ERROR] Failed to activate conda environment.
    pause
    exit /b 1
)

echo.
echo [3/4] Installing dependencies...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)

echo.
echo [4/4] Verifying installation...
python -c "import streamlit; import openai; import agentscope; print('[OK] Core packages verified.')"

echo.
echo ========================================
echo  Setup complete!
echo ========================================
echo.
echo To start the app:
echo   conda activate jobsearch
echo   streamlit run app.py
echo.
pause
