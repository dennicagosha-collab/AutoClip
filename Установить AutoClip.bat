@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Установка в один клик (P4): Python 3.13 и ffmpeg через winget, потом библиотеки (install.bat),
rem ярлык на рабочем столе. С ключом --check только показывает, чего не хватает, и ничего не ставит.
set "CHECK="
if /i "%~1"=="--check" set "CHECK=1"
echo === Установка AutoClip ===
echo.

rem то, что winget поставит сейчас, станет видно в PATH только в новом окне — добавим сами
set "PATH=%LOCALAPPDATA%\Programs\Python\Launcher;%LOCALAPPDATA%\Microsoft\WinGet\Links;%LOCALAPPDATA%\Microsoft\WindowsApps;%PATH%"

call :findpy
call :findffmpeg
if defined PY (echo [ок] Python: %PY%) else (echo [ ] Python 3.13 — поставлю)
if defined FF (echo [ок] ffmpeg) else (echo [ ] ffmpeg — поставлю)
if defined CHECK exit /b 0
if defined PY if defined FF goto libs

where winget >nul 2>nul || goto nowinget

if defined PY goto ffmpeg
echo.
echo [1/4] Ставлю Python 3.13, это пара минут...
winget install -e --id Python.Python.3.13 --scope user --silent --accept-package-agreements --accept-source-agreements
call :findpy
if not defined PY goto nopython

:ffmpeg
if defined FF goto libs
echo.
echo [2/4] Ставлю ffmpeg (сборка gyan.dev)...
winget install -e --id Gyan.FFmpeg --silent --accept-package-agreements --accept-source-agreements
call :findffmpeg
if not defined FF goto noffmpeg

:libs
echo.
echo [3/4] Ставлю библиотеки...
call "%~dp0install.bat" --no-pause
if errorlevel 1 goto failed

echo.
echo [4/4] Ярлык на рабочем столе...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$d=[Environment]::GetFolderPath('Desktop'); $s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'AutoClip.lnk')); $s.TargetPath='%~dp0AutoClip.bat'; $s.WorkingDirectory='%~dp0'; $s.IconLocation='%~dp0icon\autoclip.ico'; $s.WindowStyle=7; $s.Save()" >nul 2>nul
echo.
echo === Готово. Запускай AutoClip с ярлыка на рабочем столе ===
echo При первом запуске программа спросит ник, папки и видеокарту.
pause
exit /b 0

:nowinget
echo.
echo [!] Нет winget — установщика программ Windows.
echo     Открой Microsoft Store, найди "Установщик приложений" (App Installer), обнови его
echo     и запусти этот файл ещё раз. Или поставь Python и ffmpeg вручную — см. КАК УСТАНОВИТЬ.txt
pause
exit /b 1

:nopython
echo.
echo [!] Python не встал. Закрой это окно и запусти файл ещё раз — иногда Windows видит
echo     новую программу только в новом окне. Не помогло — см. КАК УСТАНОВИТЬ.txt
pause
exit /b 1

:noffmpeg
echo.
echo [!] ffmpeg не встал. Закрой это окно и запусти файл ещё раз.
echo     Не помогло — см. КАК УСТАНОВИТЬ.txt, раздел "Вручную".
pause
exit /b 1

:failed
echo.
echo [!] Библиотеки не установились. Сделай скрин этого окна целиком и отправь в чат.
pause
exit /b 1

:findpy
set "PY="
for %%V in (3.13 3.12 3.14 3.11) do (
  if not defined PY (
    py -%%V -c "import sys" >nul 2>nul
    if not errorlevel 1 set "PY=py -%%V"
  )
)
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PY="%LOCALAPPDATA%\Programs\Python\Python313\python.exe""
exit /b

:findffmpeg
set "FF="
if exist "%~dp0ffmpeg.exe" if exist "%~dp0ffprobe.exe" set "FF=1"
if not defined FF (
  where ffmpeg >nul 2>nul && where ffprobe >nul 2>nul && set "FF=1"
)
exit /b
