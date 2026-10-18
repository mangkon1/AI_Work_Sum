@echo off
REM ===========================================================================
REM  AI Agent Router - Windows one-file build  ->  dist\AI-Agent-Router.exe
REM  Usage:  build.bat            (run from the project folder, double-click OK)
REM  Needs:  Python 3.11 - 3.13 (64-bit) on PATH  (py launcher or python.exe)
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

echo [3/4] Building with PyInstaller ...
if exist build rmdir /s /q build
if exist dist\AI-Agent-Router.exe del /q dist\AI-Agent-Router.exe
REM  NOTE: do NOT use "--collect-all mcp": it imports mcp.cli which needs the optional
REM        'typer' package and aborts the build. Collect the needed sub-packages instead.
"%VPY%" -m PyInstaller --noconfirm --clean --onefile --console --name AI-Agent-Router --paths . ^
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
  --hidden-import agents.grok --hidden-import agents.cursor --hidden-import agents.opencode --hidden-import agents.http_agent ^
  --hidden-import config --hidden-import router_core --hidden-import mcp_server ^
  main.py
if errorlevel 1 ( echo [ERROR] PyInstaller build failed & exit /b 1 )

echo [4/4] Copying example config files next to the EXE ...
copy /y config.yaml.example dist\config.yaml.example >nul
copy /y .env.example dist\.env.example >nul
if not exist dist\.env copy /y .env.example dist\.env >nul
if exist config.yaml copy /y config.yaml dist\config.yaml >nul

echo.
echo  Done:  dist\AI-Agent-Router.exe
echo  1) edit dist\.env  (ROUTER_API_KEYS, XAI_API_KEY)
echo  2) run  dist\AI-Agent-Router.exe          -^> http://127.0.0.1:8080/health
echo     or   dist\AI-Agent-Router.exe --mcp-stdio
endlocal
