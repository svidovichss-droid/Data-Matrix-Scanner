@echo off
chcp 65001 >nul
echo ============================================================
echo   DataMatrix Quality Scanner — Сборка EXE
echo   ГОСТ Р 57302-2016 / ISO/IEC 15415
echo   Авторы: А. Свидович, А. Петляков
echo ============================================================
echo.

:: Проверка Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ОШИБКА] Python не найден. Установите Python 3.10+ с python.org
    pause & exit /b 1
)
python --version
echo [OK] Python найден
echo.

:: Установка зависимостей
echo [1/3] Установка зависимостей...
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [ОШИБКА] Не удалось установить зависимости
    pause & exit /b 1
)
pip install pyinstaller --quiet
if errorlevel 1 (
    echo [ОШИБКА] Не удалось установить PyInstaller
    pause & exit /b 1
)
echo [OK] Зависимости установлены
echo.

:: Поиск папки pylibdmtx
echo [2/3] Поиск ресурсов pylibdmtx...
for /f "delims=" %%i in ('python -c "import pylibdmtx, os; print(os.path.dirname(pylibdmtx.__file__))"') do set DMTX_DIR=%%i
echo     Путь: %DMTX_DIR%
echo.

:: Проверка наличия DLL
set DLL_ARGS=
if exist "%DMTX_DIR%\libdmtx-64.dll" (
    set DLL_ARGS=--add-binary "%DMTX_DIR%\libdmtx-64.dll;pylibdmtx"
    echo [OK] libdmtx-64.dll найдена
) else if exist "%DMTX_DIR%\libdmtx.dll" (
    set DLL_ARGS=--add-binary "%DMTX_DIR%\libdmtx.dll;pylibdmtx"
    echo [OK] libdmtx.dll найдена
) else (
    echo [ПРЕДУПРЕЖДЕНИЕ] DLL не найдена, сборка продолжается без явного include
)
echo.

:: Сборка EXE
echo [3/3] Сборка EXE (1-3 минуты)...
pyinstaller ^
    --onefile ^
    --windowed ^
    --name "DataMatrixScanner" ^
    %DLL_ARGS% ^
    --hidden-import pylibdmtx ^
    --hidden-import pylibdmtx.pylibdmtx ^
    --hidden-import cv2 ^
    --hidden-import PIL ^
    --hidden-import PIL._tkinter_finder ^
    --collect-all pylibdmtx ^
    --collect-all cv2 ^
    datamatrix_scanner.py

if errorlevel 1 (
    echo.
    echo [ОШИБКА] Сборка не удалась. Смотрите сообщения выше.
    pause & exit /b 1
)

echo.
echo ============================================================
echo   Готово! Файл: dist\DataMatrixScanner.exe
echo ============================================================
echo.
pause
