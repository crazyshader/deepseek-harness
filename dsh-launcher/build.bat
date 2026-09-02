@echo off
rem 双击打包 dsh-launcher.exe：自动找 Python、缺 PyInstaller 自动安装、
rem 跑 build.py，成功后打开 dist 输出目录。窗口最后停住，便于看结果。
chcp 65001 >nul
cd /d "%~dp0"

echo === dsh-launcher 打包 ===
echo.

rem --- 找 Python：优先 PATH 里的 python，回退到 py 启动器 ---
set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY (
    where py >nul 2>nul && set "PY=py -3"
)
if not defined PY (
    echo [错误] 未找到 Python。请先安装 Python 3.9+，安装时勾选 "Add Python to PATH"。
    goto :fail
)
echo 使用 Python: %PY%
%PY% --version
echo.

rem --- PyInstaller 缺失时自动安装 ---
%PY% -c "import PyInstaller" >nul 2>nul
if errorlevel 1 (
    echo 未检测到 PyInstaller，正在安装...
    %PY% -m pip install pyinstaller
    if errorlevel 1 (
        echo [错误] PyInstaller 安装失败。请检查网络后手动执行: %PY% -m pip install pyinstaller
        goto :fail
    )
)

rem --- 运行 build.py（它自带成功/失败判定，含产物被占用的检测）---
%PY% build.py
if errorlevel 1 goto :fail

echo.
echo 打包成功，打开输出目录...
explorer "dist"
goto :done

:fail
echo.
echo 打包失败，请查看上方错误信息。
goto :done

:done
echo.
pause
