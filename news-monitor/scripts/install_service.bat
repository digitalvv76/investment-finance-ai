@echo off
REM 金融新闻监控 — Windows 服务安装脚本
REM 右键此文件 → 以管理员身份运行

set TELEGRAM_BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN
set DEEPSEEK_API_KEY=YOUR_DEEPSEEK_KEY

cd /d D:\class1\news-monitor
python scripts/install_service.py install

echo.
echo 安装完成！按任意键启动服务...
pause >nul
nssm start NewsMonitor
nssm status NewsMonitor
echo.
echo 服务已启动，开机自启已生效。
pause
