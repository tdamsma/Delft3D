@echo off

call "C:\Program Files (x86)\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" || exit /b %errorlevel%
call "C:\Program Files (x86)\Intel\oneAPI\setvars.bat" intel64 || exit /b %errorlevel%

where cl >nul || exit /b 1