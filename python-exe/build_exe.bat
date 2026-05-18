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

:: Установка базовых зависимостей
echo [1/4] Установка базовых зависимостей...
pip install opencv-python pylibdmtx Pillow numpy pyinstaller --quiet
if errorlevel 1 (
    echo [ОШИБКА] Не удалось установить зависимости
    pause & exit /b 1
)
echo [OK] Базовые зависимости установлены
echo.

:: Опциональные промышленные камеры (устанавливаются если доступны)
echo [2/4] Проверка опциональных модулей промышленных камер...

set HIDDEN_IMPORTS=
set COLLECT_ALL=

:: Basler pypylon
pip show pypylon >nul 2>&1
if not errorlevel 1 (
    echo     [OK] pypylon (Basler) найден
    set HIDDEN_IMPORTS=%HIDDEN_IMPORTS% --hidden-import pypylon --hidden-import pypylon.pylon
    set COLLECT_ALL=%COLLECT_ALL% --collect-all pypylon
) else (
    echo     [--] pypylon (Basler) не установлен
)

:: Harvesters (GenICam)
pip show harvesters >nul 2>&1
if not errorlevel 1 (
    echo     [OK] harvesters (GenICam) найден
    set HIDDEN_IMPORTS=%HIDDEN_IMPORTS% --hidden-import harvesters --hidden-import harvesters.core
    set COLLECT_ALL=%COLLECT_ALL% --collect-all harvesters
) else (
    echo     [--] harvesters (GenICam) не установлен
)

:: PySpin (FLIR)
pip show spinnaker-python >nul 2>&1
if not errorlevel 1 (
    echo     [OK] PySpin (FLIR) найден
    set HIDDEN_IMPORTS=%HIDDEN_IMPORTS% --hidden-import PySpin
    set COLLECT_ALL=%COLLECT_ALL% --collect-all PySpin
) else (
    echo     [--] PySpin (FLIR) не установлен
)
echo.

:: Поиск DLL pylibdmtx
echo [3/4] Поиск ресурсов pylibdmtx...
for /f "delims=" %%i in ('python -c "import pylibdmtx, os; print(os.path.dirname(pylibdmtx.__file__))"') do set DMTX_DIR=%%i
echo     Путь: %DMTX_DIR%

set DLL_ARGS=
if exist "%DMTX_DIR%\libdmtx-64.dll" (
    set DLL_ARGS=--add-binary "%DMTX_DIR%\libdmtx-64.dll;pylibdmtx"
    echo     [OK] libdmtx-64.dll найдена
) else if exist "%DMTX_DIR%\libdmtx.dll" (
    set DLL_ARGS=--add-binary "%DMTX_DIR%\libdmtx.dll;pylibdmtx"
    echo     [OK] libdmtx.dll найдена
) else (
    echo     [ПРЕДУПРЕЖДЕНИЕ] DLL не найдена, сборка продолжается без явного include
)
echo.

:: Сборка EXE
echo [4/4] Сборка EXE (1-3 минуты)...
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
    %HIDDEN_IMPORTS% ^
    --collect-all pylibdmtx ^
    --collect-all cv2 ^
    %COLLECT_ALL% ^
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
