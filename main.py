import cv2
import time
from collections import deque
from pyzbar import pyzbar
import numpy as np

def enhance_image_for_decoding(image):
    """
    Улучшенное предображение изображения для лучшего декодирования
    """
    # Конвертация в grayscale
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image.copy()
    
    # Применяем фильтр Гаусса для уменьшения шума
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    
    # Адаптивная бинаризация (лучше для неравномерного освещения)
    binary_adaptive = cv2.adaptiveThreshold(
        blurred, 
        255, 
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
        cv2.THRESH_BINARY, 
        11, 
        2
    )
    
    # Морфологические операции для улучшения качества
    kernel = np.ones((2, 2), np.uint8)
    denoised = cv2.morphologyOps(binary_adaptive, cv2.MORPH_CLOSE, kernel)
    denoised = cv2.morphologyOps(denoised, cv2.MORPH_OPEN, kernel)
    
    return [gray, blurred, binary_adaptive, denoised]


def decode_with_multiple_methods(images):
    """
    Попытка декодирования несколькими методами для максимального качества
    """
    all_results = []
    
    for img in images:
        # Основное декодирование
        decoded = pyzbar.decode(img)
        all_results.extend(decoded)
        
        # Декодирование с увеличенной резкостью
        if len(img.shape) == 2:
            # Применяем unsharp mask для повышения резкости
            gaussian = cv2.GaussianBlur(img, (0, 0), 3.0)
            sharpened = cv2.addWeighted(img, 1.5, gaussian, -0.5, 0, img)
            decoded_sharp = pyzbar.decode(sharpened)
            all_results.extend(decoded_sharp)
    
    # Удаляем дубликаты по данным
    unique_results = []
    seen_data = set()
    
    for obj in all_results:
        data = obj.data.decode('utf-8', errors='ignore') if obj.data else ""
        if data and data not in seen_data:
            seen_data.add(data)
            unique_results.append(obj)
    
    return unique_results


def trekvision_1_decode(image):
    """
    Метод TREKVISION-1: Продвинутое декодирование с использованием
    множественных масштабов и ориентаций для максимального качества
    """
    all_results = []
    
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image.copy()
    
    # Масштабирование для разных размеров кодов
    scales = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]
    
    for scale in scales:
        resized = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        
        # Базовое декодирование
        decoded = pyzbar.decode(resized)
        all_results.extend(decoded)
        
        # Бинаризация Оцу
        _, binary_otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        decoded_otsu = pyzbar.decode(binary_otsu)
        all_results.extend(decoded_otsu)
        
        # Инвертированная бинаризация
        _, binary_inv = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        decoded_inv = pyzbar.decode(binary_inv)
        all_results.extend(decoded_inv)
    
    # Поворот изображения для поиска под разными углами
    angles = [90, 180, 270, 45, 135, 225, 315]
    for angle in angles:
        (h, w) = gray.shape[:2]
        center = (w // 2, h // 2)
        rotated = cv2.getRotationMatrix2D(center, angle, 1.0)
        rotated_img = cv2.warpAffine(gray, rotated, (w, h), flags=cv2.INTER_CUBIC)
        
        decoded_rotated = pyzbar.decode(rotated_img)
        all_results.extend(decoded_rotated)
    
    # CLAHE (Contrast Limited Adaptive Histogram Equalization)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    enhanced_clahe = clahe.apply(gray)
    decoded_clahe = pyzbar.decode(enhanced_clahe)
    all_results.extend(decoded_clahe)
    
    # Комбинация CLAHE + бинаризация
    _, binary_clahe = cv2.threshold(enhanced_clahe, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    decoded_clahe_bin = pyzbar.decode(binary_clahe)
    all_results.extend(decoded_clahe_bin)
    
    # Удаляем дубликаты по данным
    unique_results = []
    seen_data = set()
    
    for obj in all_results:
        data = obj.data.decode('utf-8', errors='ignore') if obj.data else ""
        if data and data not in seen_data:
            seen_data.add(data)
            unique_results.append(obj)
    
    return unique_results


def main():
    # Инициализация захвата с камеры (0 - основная камера)
    # Для уменьшения задержки можно попробовать бэкенды: cv2.CAP_DSHOW (Windows) или cv2.CAP_V4L2 (Linux)
    cap = cv2.VideoCapture(0, cv2.CAP_ANY)

    if not cap.isOpened():
        print("Ошибка: Не удалось открыть камеру.")
        return

    # Оптимизация настроек камеры для минимальной задержки
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Уменьшаем буфер до 1 кадра
    cap.set(cv2.CAP_PROP_FPS, 60)        # Пытаемся установить высокий FPS
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    # История обработки до 100 000 позиций (кольцевой буфер)
    # Хранит: (номер_кадра, время_захвата, результат_обработки, fps)
    MAX_HISTORY = 100000
    processing_history = deque(maxlen=MAX_HISTORY)
    frame_counter = 0
    
    # Статистика по сканированию
    total_scanned = 0
    last_scan_result = "Нет данных"
    last_scan_time = 0

    print(f"Нажмите 'q' для выхода, 's' для сохранения кадра, 'h' для вывода истории, 't' для переключения режима.")
    print(f"История обработки: до {MAX_HISTORY} позиций")
    print(f"Режим: TREKVISION-1 (продвинутое декодирование)")
    print(f"Нажмите 't' для переключения между TREKVISION-1 и стандартным режимом")
    
    # Флаг для выбора режима декодирования
    use_trekvision = True  # True = использовать TREKVISION-1, False = стандартный режим

    while True:
        start_time = time.time()
        frame_counter += 1

        # Мгновенный захват кадра
        ret, frame = cap.read()
        if not ret:
            print("Ошибка: Не удалось захватить кадр.")
            break

        # --- БЛОК ОБРАБОТКИ: Сканер DataMatrix/QR с улучшенным декодированием ---
        
        # Декодирование с использованием TREKVISION-1 или стандартного метода
        if use_trekvision:
            decoded_objects = trekvision_1_decode(frame)
        else:
            # Создаем несколько версий изображения для лучшего распознавания
            enhanced_images = enhance_image_for_decoding(frame)
            # Декодирование с использованием всех методов
            decoded_objects = decode_with_multiple_methods(enhanced_images)
        
        processed_frame = frame.copy()
        
        for obj in decoded_objects:
            # Получаем тип и данные
            obj_type = obj.type
            obj_data = obj.data.decode('utf-8', errors='ignore') if obj.data else "N/A"
            
            # Получаем координаты ограничивающей рамки
            points = obj.polygon
            if len(points) >= 4:
                # Рисуем рамку вокруг кода
                pts = np.array([(p.x, p.y) for p in points], dtype=np.int32)
                pts = pts.reshape((-1, 1, 2))
                cv2.polylines(processed_frame, [pts], True, (0, 255, 0), 3)
                
                # Рисуем текст с данными
                rect = obj.rect
                cv2.putText(processed_frame, f"{obj_type}: {obj_data[:20]}", 
                           (rect.left, rect.top - 10), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                
                # Обновляем статистику
                total_scanned += 1
                last_scan_result = f"{obj_type}: {obj_data}"
                last_scan_time = time.time()
        
        # Отображение результата (сплит экран: слева оригинал, справа обработка)
        result = cv2.hconcat([frame, processed_frame])
        # -----------------------

        # Расчет и отображение FPS (для проверки производительности)
        end_time = time.time()
        fps = 1 / (end_time - start_time) if (end_time - start_time) > 0 else 0
        
        # Добавляем запись в историю
        history_entry = {
            'frame_number': frame_counter,
            'timestamp': time.time(),
            'processing_time_ms': (end_time - start_time) * 1000,
            'fps': fps,
            'result_summary': f"Scanned: {total_scanned} codes",
            'last_scan': last_scan_result
        }
        processing_history.append(history_entry)
        
        # Отображение информации на экране
        cv2.putText(result, f"FPS: {fps:.2f}", (10, 30), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.putText(result, f"History: {len(processing_history)}/{MAX_HISTORY}", 
                    (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
        cv2.putText(result, f"Total Scanned: {total_scanned}", 
                    (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        
        # Индикатор текущего режима декодирования
        mode_display = "TREKVISION-1" if use_trekvision else "STANDARD"
        mode_color = (0, 255, 255) if use_trekvision else (255, 255, 255)
        cv2.putText(result, f"Mode: {mode_display}", (10, 120), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, mode_color, 2)
        
        # Показываем последние 5 записей истории прямо на экране
        y_offset = 130
        cv2.putText(result, "Last 5 scans:", (10, y_offset), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        y_offset += 25
        
        recent_history = list(processing_history)[-5:]
        for i, entry in enumerate(recent_history):
            scan_text = entry.get('last_scan', 'No scan')[:35]
            color = (0, 255, 0) if scan_text != 'No scan' else (100, 100, 100)
            cv2.putText(result, f"{i+1}. {scan_text}", (10, y_offset + i*22), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)
        
        # Индикатор последнего сканирования (мигает если недавно было сканирование)
        if time.time() - last_scan_time < 2.0:
            alpha = 0.5
            overlay = result.copy()
            cv2.rectangle(overlay, (10, 240), (300, 280), (0, 255, 0), -1)
            cv2.addWeighted(overlay, alpha, result, 1-alpha, 0, result)
            cv2.putText(result, f"LATEST: {last_scan_result[:30]}", (15, 265), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)

        cv2.imshow('DataMatrix Scanner - History Live', result)

        # Обработка нажатий клавиш (увеличенная задержка для надежной работы)
        key = cv2.waitKey(10) & 0xFF
        if key == ord('q'):
            break
        elif key == ord('s'):
            filename = f'scan_{frame_counter}.jpg'
            cv2.imwrite(filename, processed_frame)
            print(f"Кадр сохранен как {filename}")
        elif key == ord('h'):
            # Вывод последних 10 записей истории в консоль
            print("\n=== ПОСЛЕДНИЕ 10 ЗАПИСЕЙ ИСТОРИИ ===")
            for entry in list(processing_history)[-10:]:
                print(f"Кадр #{entry['frame_number']} | "
                      f"Время: {entry['timestamp']:.3f} | "
                      f"Обработка: {entry['processing_time_ms']:.2f}мс | "
                      f"FPS: {entry['fps']:.2f} | "
                      f"Scan: {entry.get('last_scan', 'No data')}")
            print(f"Всего записей в истории: {len(processing_history)}")
            print(f"Всего отсканировано: {total_scanned}\n")
        elif key == ord('t'):
            # Переключение режима TREKVISION-1
            use_trekvision = not use_trekvision
            mode_text = "TREKVISION-1" if use_trekvision else "Стандартный"
            print(f"\n>>> Режим декодирования переключен на: {mode_text} <<<\n")

    # Освобождение ресурсов
    cap.release()
    cv2.destroyAllWindows()
    
    # Сохранение полной истории в файл при выходе
    if processing_history:
        with open('processing_history.txt', 'w', encoding='utf-8') as f:
            f.write(f"Всего записей: {len(processing_history)}\n")
            f.write(f"Всего отсканировано: {total_scanned}\n")
            f.write("="*80 + "\n")
            for entry in processing_history:
                f.write(f"Кадр #{entry['frame_number']} | "
                       f"Время: {entry['timestamp']:.6f} | "
                       f"Обработка: {entry['processing_time_ms']:.4f}мс | "
                       f"FPS: {entry['fps']:.4f} | "
                       f"{entry.get('last_scan', 'No scan')}\n")
        print(f"История обработки ({len(processing_history)} записей) сохранена в processing_history.txt")

if __name__ == "__main__":
    main()
