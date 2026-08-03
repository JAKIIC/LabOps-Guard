@echo off
setlocal
cd /d "%~dp0"
"D:\APP\Anaconda\envs\d2l\python.exe" demos\checkpoint-regression\run_demo.py --output artifacts\DEMO-RCA-001\baseline --repeats 3
if errorlevel 1 exit /b %errorlevel%
"D:\APP\Anaconda\envs\d2l\python.exe" -m labops run-incident --incident demos\checkpoint-regression\incident.json
if errorlevel 1 exit /b %errorlevel%
"D:\APP\Anaconda\envs\d2l\python.exe" -m labops run-incident --incident demos\checkpoint-regression\incident-policy-violation.json
exit /b %errorlevel%
