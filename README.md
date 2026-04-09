# В папке python-exe созданы 4 файла:

Файл	Назначение
datamatrix_scanner.py	Главная программа
requirements.txt	Список библиотек
build_exe.bat	Автоматическая сборка EXE
ИНСТРУКЦИЯ_СБОРКИ.txt	Подробная инструкция
Как собрать EXE на Windows
Шаг 1. Скачайте папку python-exe на свой Windows-компьютер

Шаг 2. Убедитесь, что установлен Python 3.10+ с python.org — при установке обязательно отметьте "Add Python to PATH"

Шаг 3. Дважды щёлкните build_exe.bat — он сам:

установит все библиотеки (OpenCV, pylibdmtx, Pillow)
установит PyInstaller
соберёт DataMatrixScanner.exe
Шаг 4. Готовый файл появится в dist\DataMatrixScanner.exe — это самодостаточный EXE, который можно перенести на любой Windows-компьютер без установки Python.
