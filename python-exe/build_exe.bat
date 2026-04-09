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
echo [OK] Python найден

:: Установка зависимостей
echo.
echo [1/3] Установка зависимостей...
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [ОШИБКА] Не удалось установить зависимости
    pause & exit /b 1
)
pip install pyinstaller --quiet
echo [OK] Зависимости установлены

:: Поиск DLL от pylibdmtx
echo.
echo [2/3] Подготовка ресурсов...
for /f "delims=" %%i in ('python -c "import pylibdmtx; import os; print(os.path.dirname(pylibdmtx.__file__))"') do set DMTX_DIR=%%i
echo     pylibdmtx: %DMTX_DIR%

:: Сборка EXE
echo.
echo [3/3] Сборка EXE (это займёт 1-3 минуты)...
pyinstaller ^
    --onefile ^
    --windowed ^
    --name "DataMatrixScanner" ^
    --add-binary "%DMTX_DIR%\libdmtx-64.dll;pylibdmtx" ^
    --add-binary "%DMTX_DIR%\libdmtx-32.dll;pylibdmtx" ^
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
    echo [ОШИБКА] Сборка не удалась. Проверьте сообщения выше.
    pause & exit /b 1
)

echo.
echo ============================================================
echo   Готово! EXE находится в папке: dist\DataMatrixScanner.exe
echo ============================================================
echo.
pause
