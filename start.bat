@echo off
cd /d "%~dp0"

where pyw >nul 2>nul
if %errorlevel%==0 (
    set "PY=py -3"
    set "PYW=pyw -3"
) else (
    where pythonw >nul 2>nul
    if %errorlevel%==0 (
        set "PY=python"
        set "PYW=pythonw"
    ) else (
        echo [错误] 未找到 Python，请先安装 Python 3.10+ 并勾选"添加到 PATH"。
        pause
        exit /b 1
    )
)

%PY% -c "import customtkinter, uiautomation, pyperclip, loguru" >nul 2>nul
if not %errorlevel%==0 (
    echo [提示] 首次运行需要安装依赖，正在安装...
    %PY% -m pip install -r requirements.txt
    if not %errorlevel%==0 (
        echo [错误] 依赖安装失败，请检查网络后重试。
        pause
        exit /b 1
    )
)

echo 正在启动 DiffGuard ...
start "" /b %PYW% main.py