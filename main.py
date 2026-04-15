import cv2
import time
from collections import deque
from pyzbar import pyzbar
import numpy as np

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

    print(f"Нажмите 'q' для выхода, 's' для сохранения кадра, 'h' для вывода истории.")
    print(f"История обработки: до {MAX_HISTORY} позиций")

    while True:
        start_time = time.time()
        frame_counter += 1

        # Мгновенный захват кадра
        ret, frame = cap.read()
        if not ret:
            print("Ошибка: Не удалось захватить кадр.")
            break

        # --- БЛОК ОБРАБОТКИ: Сканер DataMatrix/QR ---
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # Улучшение контраста для лучшего распознавания
        gray = cv2.equalizeHist(gray)
        
        # Декодирование штрих-кодов и DataMatrix
        decoded_objects = pyzbar.decode(gray)
        
        processed_frame = frame.copy()
        
        for obj in decoded_objects:
            # Получаем тип и данные
            obj_type = obj.type
            obj_data = obj.data.decode('utf-8') if obj.data else "N/A"
            
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
