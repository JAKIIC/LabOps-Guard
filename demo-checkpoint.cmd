@echo off
setlocal
cd /d "%~dp0"
if defined LABOPS_PYTHON (
  set "PYTHON=%LABOPS_PYTHON%"
) else (
  set "PYTHON=python"
)
"%PYTHON%" demos\checkpoint-regression\run_demo.py --output artifacts\DEMO-RCA-001\baseline --repeats 3
if errorlevel 1 exit /b %errorlevel%
"%PYTHON%" -m labops run-incident --incident demos\checkpoint-regression\incident.json
if errorlevel 1 exit /b %errorlevel%
"%PYTHON%" -m labops run-incident --incident demos\checkpoint-regression\incident-policy-violation.json
exit /b %errorlevel%
