@echo OFF

reg Query "HKLM\Hardware\Description\System\CentralProcessor\0" | find /i "x86" > NUL && set OS=32BIT || set OS=64BIT

cd %~dp0

if %OS%==32BIT start java8_32\bin\javaw.exe -jar "Hitachi Net Configurator.jar"
if %OS%==64BIT start java8_64\bin\javaw.exe -jar "Hitachi Net Configurator.jar"

