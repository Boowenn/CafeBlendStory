@echo off
chcp 65001 >nul
title 创意咖啡物语 修改器
echo 正在启动修改器...
echo 请确保游戏已经运行！
echo.
python "%~dp0trainer_gui.py"
if errorlevel 1 (
    echo.
    echo GUI版本启动失败，切换到控制台版本...
    python "%~dp0trainer.py"
)
pause
