@echo off
chcp 65001 >nul
title East Money Tunnel (SSH → ECS)

echo ============================================
echo   East Money Proxy Tunnel
echo   ECS :9999 → 本机 :1080 → 东方财富 API
echo ============================================
echo.
echo 保持此窗口打开，最小化即可。
echo 关机会自动重连。
echo.

:loop
echo [%date% %time%] 正在连接 SSH 隧道...
ssh -o ServerAliveInterval=30 ^
    -o ServerAliveCountMax=3 ^
    -o ExitOnForwardFailure=yes ^
    -o TCPKeepAlive=yes ^
    -R 9999:localhost:1080 ^
    -N ^
    root@47.76.50.77

echo [%date% %time%] SSH 断开，5 秒后重连...
timeout /t 5 >nul
goto loop
