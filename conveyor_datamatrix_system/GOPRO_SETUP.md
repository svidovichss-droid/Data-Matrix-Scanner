# Подключение и настройка GoPro камеры

## Обзор

Система поддерживает подключение камер GoPro Hero 8 и новее через USB в режиме веб-камеры для распознавания DataMatrix кодов.

## Требования

- GoPro Hero 8 или более новая модель
- USB-C кабель (желательно оригинальный)
- OpenCV: `pip install opencv-python`
- NumPy: `pip install numpy`

## Настройка GoPro

1. **Включите GoPro** и убедитесь, что батарея заряжена
2. **Переключите в режим веб-камеры**:
   - Проведите вниз от верхнего края экрана
   - Выберите "Connect" → "Webcam"
   - Или используйте режим "Live Burst"
3. **Подключите через USB-C** к компьютеру
4. **Проверьте подключение**: камера должна определиться как устройство `/dev/video0` (Linux) или webcam index 0 (Windows)

## Быстрый старт

### Вариант 1: Использование конфигурационного файла

```bash
cd /workspace/conveyor_datamatrix_system

# Запуск с конфигурацией для GoPro
PYTHONPATH=/workspace/conveyor_datamatrix_system:$PYTHONPATH \
python src/main.py --config config/camera_config_gopro.yaml
```

### Вариант 2: Через аргумент командной строки

```bash
# Запуск существующей системы с переключением на GoPro
PYTHONPATH=/workspace/conveyor_datamatrix_system:$PYTHONPATH \
python src/main.py --config config/camera_config.yaml --camera-id 0

# Затем вручную измените type на 'gopro' в camera_config.yaml
```

### Вариант 3: Программно

```python
from camera_interface import CameraConfig, create_camera

# Создайте конфигурацию для GoPro
config = CameraConfig(
    camera_type='gopro',
    camera_id=0,      # USB device index
    width=1920,
    height=1080,
    fps=30
)

# Создайте и откройте камеру
camera = create_camera(config)
camera.open()

# Захват кадра
frame = camera.capture()
if frame.success:
    print(f"Frame captured: {frame.image.shape}")

# Закройте камеру
camera.close()
```

## Переключение между камерами

### Из test на GoPro

В файле `config/camera_config.yaml`:

```yaml
camera:
  type: gopro  # было: test
  id: 0
  settings:
    width: 1920   # изменили с 2448
    height: 1080  # изменили с 2048
```

### Из промышленной камеры на GoPro

```yaml
camera:
  type: gopro  # было: basler/flir/gige
  id: 0      # IP адрес больше не нужен
  trigger:
    enabled: false  # GoPro работает в непрерывном режиме
```

## Проверка подключения

Запустите тестовый скрипт:

```bash
PYTHONPATH=/workspace/conveyor_datamatrix_system:$PYTHONPATH \
python examples/gopro_example.py
```

Ожидаемый вывод:
```
✅ GoPro connected successfully!
Camera status: connected=True
Frame 1: size=(1080, 1920), timestamp=...
```

## Доступные разрешения

GoPro поддерживает следующие разрешения (настраиваются в коде):

- `1080p`: 1920x1080 @ 30fps (рекомендуется)
- `720p`: 1280x720 @ 60fps
- `4k`: 3840x2160 @ 30fps (требует мощный CPU)

Пример изменения разрешения:

```python
camera.set_resolution('720p')
```

## Ограничения режима USB веб-камеры

- ❌ Нет контроля экспозиции через USB
- ❌ Нет контроля增益 (gain) через USB
- ❌ Нет аппаратного триггера
- ✅ Автоматическая фокусировка
- ✅ Непрерывный поток кадров
- ✅ Преобразование в оттенки серого для DataMatrix

Для полного контроля используйте Wi-Fi API GoPro (требуется дополнительная реализация).

## Диагностика проблем

### Камера не определяется

```bash
# Linux: проверьте устройства video
ls -la /dev/video*

# Проверьте права доступа
sudo usermod -a -G video $USER
```

### Черный экран

- Убедитесь, что GoPro включена
- Проверьте, что выбран режим "Webcam", а не "Media Transfer"
- Попробуйте другой USB порт (желательно USB 3.0)
- Используйте качественный кабель

### Низкая частота кадров

- Уменьшите разрешение до 720p
- Закройте другие приложения, использующие камеру
- Используйте USB 3.0 порт

## Интеграция с конвейерной системой

Для работы с конвейером без триггера:

```yaml
camera:
  type: gopro
  trigger:
    enabled: false
    mode: continuous
    
processing:
  buffer_size: 10  # увеличьте буфер для непрерывного потока
```

Система будет обрабатывать кадры в реальном времени по мере их поступления.
