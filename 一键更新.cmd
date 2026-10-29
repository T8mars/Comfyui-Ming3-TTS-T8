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
  pause
  exit /b 1
)
echo 请先关闭本程序的工作台窗口，再执行更新。
echo 更新只替换程序文件，保留您的 Python 环境、模型、设置和作品。
"%MING_T8_PYTHON%" -X utf8 "%~dp0scripts\update_program.py" --update
set "MING_T8_EXIT=%ERRORLEVEL%"
if "%MING_T8_EXIT%"=="0" (
  echo 更新检查已完成。请双击“启动工作台.cmd”继续使用。
) else (
  echo 更新未完成，请查看上方提示后重试。
)
pause
exit /b %MING_T8_EXIT%
