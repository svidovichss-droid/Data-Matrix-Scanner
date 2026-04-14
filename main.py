import cv2
import time

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

    print("Нажмите 'q' для выхода, 's' для сохранения кадра.")

    while True:
        start_time = time.time()

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
        cv2.putText(result, f"FPS: {fps:.2f}", (10, 30), 
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

        cv2.imshow('Instant Capture & Processing', result)

        # Обработка нажатий клавиш
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord('s'):
            cv2.imwrite('captured_frame.jpg', frame)
            print("Кадр сохранен как captured_frame.jpg")

    # Освобождение ресурсов
    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
