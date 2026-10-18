@echo off
REM ===========================================================================
REM  AI Agent Router - Windows one-file build  ->  dist\AI-Agent-Router.exe
REM  Usage:  build.bat            (run from the project folder, double-click OK)
REM  Needs:  Python 3.11 - 3.13 (64-bit, from python.org: includes tkinter) on PATH
REM ===========================================================================
setlocal EnableExtensions
cd /d "%~dp0"

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY (
  echo [ERROR] Python not found. Install Python 3.11+ from https://www.python.org/ and tick "Add to PATH".
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/4] Creating virtual environment .venv ...
  %PY% -m venv .venv || ( echo [ERROR] venv creation failed & exit /b 1 )
)
set "VPY=.venv\Scripts\python.exe"

echo [2/4] Installing requirements ...
"%VPY%" -m pip install --upgrade pip >nul
"%VPY%" -m pip install -r requirements.txt || ( echo [ERROR] pip install failed & exit /b 1 )
"%VPY%" -c "import tkinter" 2>nul || ( echo [ERROR] this Python has no tkinter - reinstall Python from python.org with "tcl/tk and IDLE" ticked & exit /b 1 )

echo [3/4] Building with PyInstaller ...
if exist build rmdir /s /q build
if exist dist\AI-Agent-Router.exe del /q dist\AI-Agent-Router.exe
REM  NOTES
REM  * do NOT use "--collect-all mcp": it imports mcp.cli which needs the optional 'typer'
REM    package and aborts the build. The needed mcp sub-packages are collected instead.
REM  * CONSOLE exe + "--hide-console hide-early" (not --windowed):
REM      - a console exe always has a real stdin/stdout, so "--mcp-stdio" works for OpenCode/Cursor
REM      - when the EXE is double-clicked it owns its console, and the bootloader hides that
REM        console right away -> the user only sees the GUI
REM      - when started from cmd/PowerShell the console is NOT hidden (it is not ours)
"%VPY%" -m PyInstaller --noconfirm --clean --onefile --console --hide-console hide-early ^
  --name AI-Agent-Router --paths . ^
  --hidden-import mcp ^
  --collect-submodules mcp.server --collect-submodules mcp.shared --collect-submodules mcp.client ^
  --collect-submodules mcp.types --collect-submodules mcp.os --collect-data mcp --copy-metadata mcp ^
  --collect-all mcp_types ^
  --collect-all fastapi --collect-all starlette --collect-all uvicorn --collect-all sse_starlette ^
  --collect-all pydantic --collect-all pydantic_core ^
  --collect-all httpx --collect-all httpx2 --collect-all anyio ^
  --collect-all jsonschema --collect-all jsonschema_specifications --collect-all opentelemetry ^
  --hidden-import yaml --hidden-import dotenv --hidden-import python_multipart ^
  --collect-submodules agents ^
  --hidden-import agents.grok --hidden-import agents.cursor --hidden-import agents.opencode --hidden-import agents.http_agent --hidden-import agents.openai_compat ^
  --hidden-import config --hidden-import router_core --hidden-import mcp_server ^
  --hidden-import gui --hidden-import gui_agents --hidden-import agent_store --hidden-import presets --hidden-import tkinter --hidden-import tkinter.ttk --hidden-import tkinter.scrolledtext ^
  --hidden-import tkinter.messagebox --hidden-import tkinter.font ^
  main.py
if errorlevel 1 ( echo [ERROR] PyInstaller build failed & exit /b 1 )

echo [4/4] Copying example config files next to the EXE ...
copy /y config.yaml.example dist\config.yaml.example >nul
copy /y .env.example dist\.env.example >nul
if exist config.yaml copy /y config.yaml dist\config.yaml >nul
REM  no .env is copied on purpose: on first launch the GUI creates dist\.env with a fresh random key

echo.
echo  Done:  dist\AI-Agent-Router.exe
echo  - double-click it: the GUI opens, creates the Router Key and starts the server
echo  - headless server:  dist\AI-Agent-Router.exe --no-gui
echo  - MCP over stdio:   dist\AI-Agent-Router.exe --mcp-stdio
endlocal
