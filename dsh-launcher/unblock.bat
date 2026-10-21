@echo off
rem Double-click to clear the "downloaded from the internet" marker (Mark of the Web)
rem from every file in this folder, so SmartScreen stops blocking dsh-launcher.exe.
rem SmartScreen only checks files carrying this marker, which is added when the folder
rem arrives via chat apps, email, cloud drives or browser downloads.
rem Only run this on a folder you trust: it skips the system check, not the risk.
rem Keep this file ASCII-only: cmd misparses multi-byte text in LF-terminated batch files.
cd /d "%~dp0"

echo === Clearing Mark of the Web from files in this folder ===
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -LiteralPath '%~dp0.' -Recurse -File | Unblock-File"
if errorlevel 1 (
    echo [ERROR] Failed. Make sure no file in this folder is in use, then retry.
) else (
    echo Done. Double-click dsh-launcher.exe; SmartScreen should no longer block it.
)

echo.
pause
