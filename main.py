import cv2
import time
from collections import deque

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

        # --- БЛОК ОБРАБОТКИ ---
        # Пример обработки: Детекция границ (Canny Edge Detection)
        # Вы можете заменить эту строку на любую другую логику обработки
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 100, 200)
        
        # Преобразуем обратно в BGR для отображения поверх оригинала (опционально)
        processed_frame = cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)
        
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
            'result_summary': f"Canny edges detected"
        }
        processing_history.append(history_entry)
        
        cv2.putText(result, f"FPS: {fps:.2f}", (10, 30), 
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        cv2.putText(result, f"History: {len(processing_history)}/{MAX_HISTORY}", 
                    (10, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)

        cv2.imshow('Instant Capture & Processing', result)

        # Обработка нажатий клавиш
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord('s'):
            cv2.imwrite('captured_frame.jpg', frame)
            print("Кадр сохранен как captured_frame.jpg")
        elif key == ord('h'):
            # Вывод последних 10 записей истории в консоль
            print("\n=== ПОСЛЕДНИЕ 10 ЗАПИСЕЙ ИСТОРИИ ===")
            for entry in list(processing_history)[-10:]:
                print(f"Кадр #{entry['frame_number']} | "
                      f"Время: {entry['timestamp']:.3f} | "
                      f"Обработка: {entry['processing_time_ms']:.2f}мс | "
                      f"FPS: {entry['fps']:.2f}")
            print(f"Всего записей в истории: {len(processing_history)}\n")

    # Освобождение ресурсов
    cap.release()
    cv2.destroyAllWindows()
    
    # Сохранение полной истории в файл при выходе
    if processing_history:
        with open('processing_history.txt', 'w') as f:
            f.write(f"Всего записей: {len(processing_history)}\n")
            f.write("="*80 + "\n")
            for entry in processing_history:
                f.write(f"Кадр #{entry['frame_number']} | "
                       f"Время: {entry['timestamp']:.6f} | "
                       f"Обработка: {entry['processing_time_ms']:.4f}мс | "
                       f"FPS: {entry['fps']:.4f} | "
                       f"{entry['result_summary']}\n")
        print(f"История обработки ({len(processing_history)} записей) сохранена в processing_history.txt")

if __name__ == "__main__":
    main()
