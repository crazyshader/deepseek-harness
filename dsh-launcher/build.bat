@echo off
rem Double-click to build dsh-launcher.exe: finds Python, installs PyInstaller if missing,
rem runs build.py, then opens the dist folder. Window stays open for reading results.
chcp 65001 >nul
cd /d "%~dp0"

echo === dsh-launcher build ===
echo.

rem --- Find Python: prefer PATH python, fall back to py launcher ---
set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY (
    where py >nul 2>nul && set "PY=py -3"
)
if not defined PY (
    echo [ERROR] Python not found. Install Python 3.9+ and check "Add Python to PATH".
    goto :fail
)
echo Using Python: %PY%
%PY% --version
echo.

rem --- Install PyInstaller if missing ---
%PY% -c "import PyInstaller" >nul 2>nul
if errorlevel 1 (
    echo PyInstaller not detected, installing...
    %PY% -m pip install pyinstaller
    if errorlevel 1 (
        echo [ERROR] PyInstaller install failed. Check network and run manually: %PY% -m pip install pyinstaller
        goto :fail
    )
)

rem --- Run build.py (it has its own success/failure detection, including file-lock check) ---
%PY% build.py
if errorlevel 1 goto :fail

echo.
echo Build succeeded, opening output directory...
explorer "dist"
goto :done

:fail
echo.
echo Build failed, see errors above.
goto :done

:done
echo.
pause
