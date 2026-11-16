@echo off
rem Starts oar on Windows with the settings from .env. Used by oar-windows.ps1.
cd /d "%~dp0.."
for /f "usebackq eol=# tokens=1,* delims==" %%a in (".env") do if not "%%b"=="" set "%%a=%%b"
if not exist data mkdir data
.venv\Scripts\oar.exe run >> data\oar.log 2>&1
