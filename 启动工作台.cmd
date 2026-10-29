@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "MING_T8_PYTHON="
if defined MING_PYTHON if exist "%MING_PYTHON%" set "MING_T8_PYTHON=%MING_PYTHON%"
if not defined MING_T8_PYTHON if exist "%~dp0runtime\python.exe" set "MING_T8_PYTHON=%~dp0runtime\python.exe"
if not defined MING_T8_PYTHON if exist "%~dp0runtime\Scripts\python.exe" set "MING_T8_PYTHON=%~dp0runtime\Scripts\python.exe"
if not defined MING_T8_PYTHON if exist "%~dp0python_embeded\python.exe" set "MING_T8_PYTHON=%~dp0python_embeded\python.exe"
if not defined MING_T8_PYTHON (
  echo 本程序包不包含 Python 环境和模型。
  echo 请先准备好环境，将其放在 runtime 或 python_embeded 目录，
  echo 或将 MING_PYTHON 环境变量设置为已有 python.exe 的完整路径。
  echo 启动后可在设置中选择本机模型路径。
  pause
  exit /b 1
)
"%MING_T8_PYTHON%" -X utf8 "%~dp0scripts\update_program.py" --apply-pending
if errorlevel 1 (
  echo 程序更新尚未完成，请关闭其它工作台窗口后重试。
  pause
  exit /b 1
)
"%MING_T8_PYTHON%" -X utf8 "%~dp0studio.py" %*
set "MING_T8_EXIT=%ERRORLEVEL%"
if not "%MING_T8_EXIT%"=="0" pause
exit /b %MING_T8_EXIT%
