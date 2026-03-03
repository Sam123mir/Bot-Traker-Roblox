@echo off
:loop
python roblox_version_monitor.py
echo El script se cerro o crasheo. Reiniciando en 10 segundos...
timeout /t 10
goto loop
