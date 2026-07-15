@echo off
chcp 65001 >nul
title East Money Proxy + Tunnel

echo.
echo ============================================
echo   东方财富数据通道
echo   代理 :1080 + 隧道 → ECS :9999
echo ============================================
echo.

:: Use full path to Python (Explorer PATH doesn't include it)
set PYTHON=C:\Users\nycr\AppData\Local\Programs\Python\Python312\python.exe
if not exist "%PYTHON%" set PYTHON=python

:: Check if proxy is already running
netstat -ano 2>nul | findstr ":1080.*LISTENING" >nul
if errorlevel 1 (
    echo [启动] 代理服务器 :1080 ...
    start "EastMoney-Proxy" /min "%PYTHON%" -u "%~dp0eastmoney_proxy.py" --port 1080
    timeout /t 2 >nul
) else (
    echo [OK] 代理已在 :1080 运行
)

:: Start SSH tunnel (in this window — keeps reconnect visible)
echo [启动] SSH 隧道 → ECS :9999 ...
echo.
call "%~dp0eastmoney_tunnel.bat"
