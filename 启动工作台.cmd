@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "MING_PYTHON=%~dp0runtime\python.exe"
if exist "%MING_PYTHON%" set "MING_T8_DATA=%~dp0data"
if not exist "%MING_PYTHON%" set "MING_PYTHON=D:\Ming3-TTS-data\runtime\Scripts\python.exe"
if not exist "%MING_PYTHON%" (
  echo 未找到整合包运行时。请使用完整整合包，或先完成开发环境安装。
  pause
  exit /b 1
)
"%MING_PYTHON%" -X utf8 studio.py %*
if errorlevel 1 pause
