@echo off
cd /d "%~dp0"
set "PYW="
for %%V in (3.13 3.12 3.14 3.11) do (
  if not defined PYW (
    py -%%V -c "import sys" >nul 2>nul
    if not errorlevel 1 set "PYW=pyw -%%V"
  )
)
if not defined PYW set "PYW=pythonw"
start "" %PYW% "%~dp0gui.py"
