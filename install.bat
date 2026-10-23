@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === Установка AutoClip ===
echo.

call :findpy
if not defined PY goto nopython

%PY% -c "import sys,platform;print('Найден Python', sys.version.split()[0], platform.architecture()[0])"
%PY% -c "import sys,struct;sys.exit(0 if (3,11)<=sys.version_info[:2]<=(3,14) and struct.calcsize('P')==8 else 1)"
if errorlevel 1 goto badpython

echo.
echo [1/3] Ставлю библиотеки, это несколько минут...
%PY% -m pip install --upgrade pip
%PY% -m pip install --only-binary=:all: faster-whisper numpy PySide6 send2trash pytest "opencv-python-headless<5" scikit-learn nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*"
if errorlevel 1 goto pipfail

echo.
echo [2/3] Проверяю, что всё встало...
%PY% -c "import faster_whisper, av, ctranslate2, numpy, PySide6.QtMultimedia, send2trash; print('Библиотеки на месте')"
if errorlevel 1 goto pipfail

echo.
echo [3/3] Проверяю ffmpeg...
if exist "%~dp0ffmpeg.exe" if exist "%~dp0ffprobe.exe" goto ok
where ffmpeg >nul 2>nul || goto noffmpeg
where ffprobe >nul 2>nul || goto noffmpeg
goto ok

:nopython
echo [!] Python не найден.
echo     Скачай Python 3.13 с python.org, при установке поставь галочку "Add python.exe to PATH",
echo     потом запусти этот файл ещё раз.
start https://www.python.org/downloads/windows/
pause
exit /b

:badpython
echo.
echo [!] Эта версия Python не подходит. Нужен 64-битный Python от 3.11 до 3.14, лучше 3.13.
echo     Для нужных библиотек под другие версии ещё нет готовых сборок.
echo     1. Открой "Установка и удаление программ" и удали текущий Python.
echo     2. Скачай Python 3.13 "Windows installer 64-bit" со страницы, которая сейчас откроется.
echo     3. При установке поставь галочку "Add python.exe to PATH".
echo     4. Запусти этот файл ещё раз.
start https://www.python.org/downloads/windows/
pause
exit /b

:pipfail
echo.
echo [!] Библиотеки не установились. Сделай скрин этого окна целиком и отправь в чат.
pause
exit /b

:noffmpeg
echo [!] Не найден ffmpeg.
echo     Скачай ffmpeg-release-essentials.zip, открой архив, папку bin,
echo     и скопируй ffmpeg.exe и ffprobe.exe в эту папку:  %~dp0
start https://www.gyan.dev/ffmpeg/builds/
pause
exit /b

:ok
echo.
echo === Всё готово! Запускай AutoClip.bat ===
pause
exit /b

:findpy
set "PY="
for %%V in (3.13 3.12 3.14 3.11) do (
  if not defined PY (
    py -%%V -c "import sys" >nul 2>nul
    if not errorlevel 1 set "PY=py -%%V"
  )
)
if not defined PY (
  python -c "import sys" >nul 2>nul
  if not errorlevel 1 set "PY=python"
)
exit /b
