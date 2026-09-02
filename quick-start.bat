@echo off
setlocal enabledelayedexpansion
title DeepSeek Harness - Quick Start

set "PORT=3080"

REM --- Check we are in the project root ---
if not exist "package.json" (
    echo.
    echo  [ERROR] package.json not found.
    echo  Run this script from the project root.
    pause
    exit /b 1
)

:MENU
cls
echo.
echo  ============================================
echo    DeepSeek Harness - Quick Start
echo    Web GUI:  http://localhost:%PORT%
echo  ============================================
echo.
echo    [1] Install    pnpm install
echo    [2] Build      pnpm run clean + pnpm run build
echo    [3] Run        pnpm dsh web --port %PORT%
echo    [0] Exit
echo.
set "CHOICE="
set /p "CHOICE=  Select an option (press Enter to Run): "

REM --- Strip surrounding spaces so " 2" still works ---
for /f "tokens=* delims= " %%a in ("!CHOICE!") do set "CHOICE=%%a"

if not defined CHOICE goto RUN
if "!CHOICE!"=="1" goto INSTALL
if "!CHOICE!"=="2" goto BUILD
if "!CHOICE!"=="3" goto RUN
if "!CHOICE!"=="0" goto END

echo.
echo  [WARN] Invalid option: !CHOICE!
timeout /t 2 >nul
goto MENU

REM ============================================================
:INSTALL
echo.
echo  [Install] Installing dependencies ...
echo.
call pnpm install
if errorlevel 1 (
    echo.
    echo  [ERROR] Failed to install dependencies.
    pause
    goto MENU
)
echo.
echo  [Install] Done.
pause
goto MENU

REM ============================================================
:BUILD
if not exist "node_modules" (
    echo.
    echo  [ERROR] node_modules not found. Run option [1] Install first.
    pause
    goto MENU
)

echo.
echo  [Build 1/2] Cleaning build outputs ...
echo.
call pnpm run clean
if errorlevel 1 (
    echo.
    echo  [ERROR] Clean failed.
    pause
    goto MENU
)

echo.
echo  [Build 2/2] Building the project ...
echo.
call pnpm run build
if errorlevel 1 (
    echo.
    echo  [ERROR] Build failed.
    pause
    goto MENU
)
echo.
echo  [Build] Done.
pause
goto MENU

REM ============================================================
:RUN
if not exist "node_modules" (
    echo.
    echo  [ERROR] node_modules not found. Run option [1] Install first.
    pause
    goto MENU
)
if not exist "apps\web\dist\index.html" (
    echo.
    echo  [ERROR] Web frontend not built. Run option [2] Build first.
    pause
    goto MENU
)

echo.
echo  [Run] Starting Web GUI ...
echo.
echo  The browser will open automatically at  http://localhost:%PORT%
echo  Press Ctrl+C to stop the server.
echo.
call pnpm dsh web --port %PORT%
echo.
echo  [Run] Server stopped.
pause
goto MENU

REM ============================================================
:END
endlocal
exit /b 0
