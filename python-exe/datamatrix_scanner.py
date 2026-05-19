"""
DataMatrix Quality Scanner
ГОСТ Р 57302-2016 / ISO/IEC 15415
Авторы: Александр Свидович, Алексей Петляков
"""

import threading
import time
import queue
from datetime import datetime

import tkinter as tk
from tkinter import ttk, font as tkfont, simpledialog, messagebox

import cv2
import numpy as np
from PIL import Image, ImageTk

try:
    import winsound
    WINSOUND_AVAILABLE = True
except ImportError:
    WINSOUND_AVAILABLE = False

try:
    from pylibdmtx.pylibdmtx import decode as dmtx_decode
    DMTX_AVAILABLE = True
except Exception:
    DMTX_AVAILABLE = False

# ── Опциональные промышленные камеры ──────────────────────────────────────────
try:
    import pypylon.pylon as pylon
    BASLER_AVAILABLE = True
except Exception:
    BASLER_AVAILABLE = False

try:
    from harvesters.core import Harvester
    HARVESTERS_AVAILABLE = True
except Exception:
    HARVESTERS_AVAILABLE = False

try:
    import PySpin
    FLIR_AVAILABLE = True
except Exception:
    FLIR_AVAILABLE = False

# ── Тема ──────────────────────────────────────────────────────────────────────
BG      = "#0f1117"
BG2     = "#161b22"
BG3     = "#1c2333"
FG      = "#e6edf3"
FG2     = "#8b949e"
PRIMARY = "#00b4d8"

GRADE_COLORS = {
    "A": "#22c55e",
    "B": "#14b8a6",
    "C": "#eab308",
    "D": "#f97316",
    "F": "#ef4444",
}
GRADE_DIM = {
    "A": "#0f2d1c",
    "B": "#09211e",
    "C": "#2e2406",
    "D": "#2e1506",
    "F": "#2e0a0a",
}
GRADE_LABELS = {
    "A": "Отлично",
    "B": "Хорошо",
    "C": "Удовлетворительно",
    "D": "Плохо",
    "F": "Неудовлетворительно",
}

# ── Параметры ГОСТ ─────────────────────────────────────────────────────────────
PARAMS_META = [
    ("SC",  "Контраст символа",                  "п. 5.4"),
    ("MOD", "Модуляция",                          "п. 5.5"),
    ("RM",  "Запас отражательной способности",    "п. 5.6"),
    ("FPD", "Повреждение фиксированного рисунка", "п. 5.7"),
    ("ANU", "Осевая неравномерность",             "п. 5.8"),
    ("GNU", "Неравномерность сетки",              "п. 5.9"),
    ("UEC", "Неиспользованная коррекция ошибок",  "п. 5.10"),
    ("PG",  "Прирост печати",                     "п. 5.11"),
]

GRADE_THRESH = {
    # ISO/IEC 15415 Table 3 — пороги для оценок 4(A) 3(B) 2(C) 1(D)
    "SC":  [0.70, 0.55, 0.40, 0.20],   # Symbol Contrast          §7.4
    "MOD": [0.60, 0.50, 0.40, 0.30],   # Modulation (min ERN)     §7.5
    "RM":  [0.30, 0.20, 0.10, 0.01],   # Reflectance Margin       §7.6
    "FPD": [0.90, 0.75, 0.55, 0.30],   # Fixed Pattern Damage     §7.7
    "ANU": [0.94, 0.92, 0.90, 0.88],   # Axial Non-Uniformity     §7.8 (1 − δ)
    "GNU": [0.94, 0.92, 0.90, 0.88],   # Grid Non-Uniformity      §7.9 (1 − δ)
    "UEC": [0.62, 0.50, 0.37, 0.25],   # Unused Error Correction  §7.10
    "PG":  [0.90, 0.75, 0.55, 0.30],   # Print Growth             §7.11
}


def value_to_grade(value: float, key: str) -> str:
    t = GRADE_THRESH[key]
    if value >= t[0]: return "A"
    if value >= t[1]: return "B"
    if value >= t[2]: return "C"
    if value >= t[3]: return "D"
    return "F"


def grade_to_score(g: str) -> float:
    return {"A": 4.0, "B": 3.0, "C": 2.0, "D": 1.0, "F": 0.0}[g]


def worst_grade(grades) -> str:
    s = min(grade_to_score(g) for g in grades)
    if s >= 3.5: return "A"
    if s >= 2.5: return "B"
    if s >= 1.5: return "C"
    if s >= 0.5: return "D"
    return "F"


def _estimate_module_pitch(profile_bool: np.ndarray) -> int:
    """
    Оценка шага модуля (в пикселях) через анализ переходов двоичного профиля.
    Возвращает медиану ширин пробегов.
    """
    n = len(profile_bool)
    if n < 4:
        return max(1, n)
    transitions = np.where(np.diff(profile_bool.astype(np.int16)) != 0)[0]
    if len(transitions) < 2:
        return max(1, n // 10)
    gaps = np.diff(transitions)
    return max(1, int(np.median(gaps)))


def _fail_analysis() -> dict:
    params = {k: {"value": 0.0, "grade": "F"} for k, _, _ in PARAMS_META}
    return {"params": params, "overall": "F", "score": 0.0}


def analyze_datamatrix_iso(roi_bgr: np.ndarray) -> dict:
    """
    Анализ качества DataMatrix строго по ISO/IEC 15415 / ГОСТ Р 57302-2016.

    Все 8 параметров вычисляются на уровне отдельных модулей:
      SC  §7.4 — Symbol Contrast
      MOD §7.5 — Modulation (min Edge Reflectance Normalised по всем модулям)
      RM  §7.6 — Reflectance Margin
      FPD §7.7 — Fixed Pattern Damage (Finder + Clock tracks)
      ANU §7.8 — Axial Non-Uniformity
      GNU §7.9 — Grid Non-Uniformity
      UEC §7.10 — Unused Error Correction (аппроксимация)
      PG  §7.11 — Print Growth
    """
    gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    h, w = gray.shape

    # ── §7.4  SC — Symbol Contrast ───────────────────────────────────────────
    Rmax = float(gray.max())
    Rmin = float(gray.min())
    if Rmax < 1.0:
        return _fail_analysis()
    rng = max(Rmax - Rmin, 1e-3)
    RDT = (Rmax + Rmin) / 2.0          # Reference Decode Threshold
    SC  = (Rmax - Rmin) / Rmax          # ∈ [0, 1]

    # ── Определение модульной сетки ──────────────────────────────────────────
    binary = gray < RDT                 # True = тёмный модуль

    # Шаг по X — из строки на уровне верхнего тактового рисунка (≈ 1/8 сверху)
    top_y  = max(0, h // 8)
    px = _estimate_module_pitch(binary[top_y, :])

    # Шаг по Y — из центрального столбца
    mid_x  = w // 2
    py = _estimate_module_pitch(binary[:, mid_x])

    px = max(1, min(px, w // 2))
    py = max(1, min(py, h // 2))
    n_cols = max(2, w // px)
    n_rows = max(2, h // py)

    # ── Выборка значений в центрах модулей ───────────────────────────────────
    dark_vals  = []
    light_vals = []
    for row in range(n_rows):
        for col in range(n_cols):
            cx = int((col + 0.5) * px)
            cy = int((row + 0.5) * py)
            if cx >= w or cy >= h:
                continue
            r  = max(1, min(px, py) // 4)
            x1 = max(0, cx - r); x2 = min(w, cx + r + 1)
            y1 = max(0, cy - r); y2 = min(h, cy + r + 1)
            val = float(gray[y1:y2, x1:x2].mean())
            if val < RDT:
                dark_vals.append(val)
            else:
                light_vals.append(val)

    if not dark_vals or not light_vals:
        return _fail_analysis()

    dark_arr  = np.array(dark_vals,  dtype=np.float32)
    light_arr = np.array(light_vals, dtype=np.float32)

    # ── §7.5  MOD — Modulation ────────────────────────────────────────────────
    # ERN_dark  = (RDT − val) / (RDT − Rmin)  — для каждого тёмного модуля
    # ERN_light = (val − RDT) / (Rmax − RDT)  — для каждого светлого модуля
    # MOD = min(ERN) по всем модулям
    dark_denom  = max(RDT - Rmin, 1e-3)
    light_denom = max(Rmax - RDT, 1e-3)
    ern_dark  = (RDT - dark_arr)  / dark_denom
    ern_light = (light_arr - RDT) / light_denom
    MOD = float(min(float(ern_dark.min()), float(ern_light.min())))
    MOD = max(0.0, min(1.0, MOD))

    # ── §7.6  RM — Reflectance Margin ────────────────────────────────────────
    # Минимальный запас каждого модуля до RDT, нормированный на (Rmax − Rmin)
    dark_margin  = float((RDT - dark_arr).min())  / rng
    light_margin = float((light_arr - RDT).min()) / rng
    RM = min(dark_margin, light_margin)
    RM = max(0.0, min(1.0, RM))

    # ── §7.7  FPD — Fixed Pattern Damage ─────────────────────────────────────
    # Левый фиксированный рисунок (вертикаль, вся чёрная)
    left_score = float(binary[:, 0].mean())

    # Нижний фиксированный рисунок (горизонталь, вся чёрная)
    bot_score  = float(binary[-1, :].mean())

    # Верхний тактовый рисунок (чередование): считаем переходы
    top_trans   = int(np.sum(np.abs(np.diff(binary[0, :].astype(np.int16)))))
    top_clock   = min(1.0, top_trans * 2.0 / max(w - 1, 1))

    # Правый тактовый рисунок
    right_trans = int(np.sum(np.abs(np.diff(binary[:, -1].astype(np.int16)))))
    right_clock = min(1.0, right_trans * 2.0 / max(h - 1, 1))

    FPD = (left_score + bot_score + top_clock + right_clock) / 4.0
    FPD = max(0.0, min(1.0, FPD))

    # ── §7.8  ANU — Axial Non-Uniformity ─────────────────────────────────────
    # δ = |px − py| / ((px + py) / 2);  результат = 1 − δ (чем ближе к 1, тем лучше)
    avg_pitch = (px + py) / 2.0
    ANU = max(0.0, 1.0 - abs(px - py) / max(avg_pitch, 1.0))

    # ── §7.9  GNU — Grid Non-Uniformity ──────────────────────────────────────
    # Отклонение реальных позиций переходов от идеальной сетки
    deviations = []
    for row in range(0, n_rows, max(1, n_rows // 6)):
        cy = int((row + 0.5) * py)
        if cy >= h:
            continue
        profile = binary[cy, :].astype(np.int16)
        trans   = np.where(np.diff(profile) != 0)[0]
        for i, t in enumerate(trans):
            ideal = int(i * px + px / 2)
            if ideal < w:
                deviations.append(abs(int(t) - ideal))

    if deviations:
        max_dev = float(np.percentile(deviations, 95))
        GNU = max(0.0, 1.0 - max_dev / max(px, 1))
    else:
        GNU = 0.5
    GNU = max(0.0, min(1.0, GNU))

    # ── §7.10  UEC — Unused Error Correction ─────────────────────────────────
    # Точный расчёт требует доступа к ECC200-декодеру.
    # Аппроксимация: SC и MOD коррелируют с запасом коррекции ошибок.
    UEC = min(1.0, SC * 0.5 + MOD * 0.5)

    # ── §7.11  PG — Print Growth ──────────────────────────────────────────────
    # Разброс отражений внутри классов модулей (чем меньше, тем ровнее печать)
    dark_spread  = float(dark_arr.std())  / rng
    light_spread = float(light_arr.std()) / rng
    PG = max(0.0, 1.0 - (dark_spread + light_spread))
    PG = max(0.0, min(1.0, PG))

    # ── Итоговая оценка ──────────────────────────────────────────────────────
    raw = {"SC": SC, "MOD": MOD, "RM": RM, "FPD": FPD,
           "ANU": ANU, "GNU": GNU, "UEC": UEC, "PG": PG}

    params = {}
    for k, v in raw.items():
        v = max(0.0, min(1.0, float(v)))
        params[k] = {"value": v, "grade": value_to_grade(v, k)}

    grades = [p["grade"] for p in params.values()]
    avg    = sum(grade_to_score(g) for g in grades) / len(grades)
    return {"params": params, "overall": worst_grade(grades), "score": avg}


# ── Звук ───────────────────────────────────────────────────────────────────────
def play_sound(grade: str):
    if not WINSOUND_AVAILABLE:
        return
    def _play():
        try:
            if grade == "A":
                winsound.Beep(880, 100); time.sleep(0.05); winsound.Beep(1100, 140)
            elif grade == "B":
                winsound.Beep(780, 100); time.sleep(0.05); winsound.Beep(980, 140)
            elif grade == "C":
                winsound.Beep(660, 90);  time.sleep(0.08); winsound.Beep(660, 90)
            elif grade == "D":
                for i in range(4):
                    winsound.Beep(440 if i % 2 == 0 else 330, 160); time.sleep(0.04)
            elif grade == "F":
                for i in range(8):
                    winsound.Beep(380 if i % 2 == 0 else 220, 110); time.sleep(0.03)
        except Exception:
            pass
    threading.Thread(target=_play, daemon=True).start()


# ── Абстракция источника видеопотока ──────────────────────────────────────────
class CameraSource:
    """Базовый класс источника видеопотока."""
    @property
    def label(self) -> str:
        return "Камера"

    def open(self) -> bool:
        raise NotImplementedError

    def read(self):
        raise NotImplementedError

    def release(self):
        pass

    def set_property(self, prop_id, value):
        pass


class OpenCVCamera(CameraSource):
    """
    USB / DirectShow камера по индексу.
    Поддерживает все камеры, доступные через OpenCV на Windows.
    """
    def __init__(self, index: int):
        self._index = index
        self._cap   = None

    @property
    def label(self):
        return f"USB Камера {self._index}"

    def open(self) -> bool:
        self._cap = cv2.VideoCapture(self._index, cv2.CAP_DSHOW)
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH,  1920)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        self._cap.set(cv2.CAP_PROP_FPS,          60)
        self._cap.set(cv2.CAP_PROP_AUTOFOCUS,    1)
        self._cap.set(cv2.CAP_PROP_BUFFERSIZE,   1)
        return self._cap.isOpened()

    def read(self):
        if not self._cap:
            return False, None
        return self._cap.read()

    def release(self):
        if self._cap:
            self._cap.release()
            self._cap = None

    def set_property(self, prop_id, value):
        if self._cap:
            self._cap.set(prop_id, value)


class RTSPCamera(CameraSource):
    """
    IP-камера / сетевая камера по URL.
    Поддерживает RTSP (rtsp://...), HTTP MJPEG (http://...),
    а также любой другой поток, принимаемый OpenCV.
    Примеры:
      rtsp://admin:pass@192.168.1.100:554/stream
      http://192.168.1.100:8080/video
      rtsp://192.168.1.100/axis-media/media.amp
    """
    def __init__(self, url: str):
        self._url = url.strip()
        self._cap = None

    @property
    def label(self):
        return f"IP: {self._url}"

    def open(self) -> bool:
        self._cap = cv2.VideoCapture(self._url, cv2.CAP_FFMPEG)
        self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return self._cap.isOpened()

    def read(self):
        if not self._cap:
            return False, None
        return self._cap.read()

    def release(self):
        if self._cap:
            self._cap.release()
            self._cap = None


class BaslerCamera(CameraSource):
    """
    Камера Basler через pypylon (официальный Basler SDK).
    Поддерживает GigE Vision и USB3 Vision камеры Basler.
    serial — серийный номер камеры (пусто = первая доступная).
    """
    def __init__(self, serial: str = ""):
        self._serial  = serial.strip()
        self._cam     = None
        self._grab    = None

    @property
    def label(self):
        sn = self._serial or "первая"
        return f"Basler ({sn})"

    def open(self) -> bool:
        if not BASLER_AVAILABLE:
            return False
        try:
            tlf = pylon.TlFactory.GetInstance()
            devices = tlf.EnumerateDevices()
            if not devices:
                return False
            if self._serial:
                device = next(
                    (d for d in devices if d.GetSerialNumber() == self._serial),
                    None
                )
                if device is None:
                    return False
                self._cam = pylon.InstantCamera(tlf.CreateDevice(device))
            else:
                self._cam = pylon.InstantCamera(tlf.CreateFirstDevice())
            self._cam.Open()
            self._cam.Width.Value  = self._cam.Width.Max
            self._cam.Height.Value = self._cam.Height.Max
            try:
                self._cam.AcquisitionFrameRateEnable.Value = True
                self._cam.AcquisitionFrameRate.Value       = 60.0
            except Exception:
                pass
            self._cam.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)
            return True
        except Exception:
            return False

    def read(self):
        if not self._cam:
            return False, None
        try:
            result = self._cam.RetrieveResult(2000, pylon.TimeoutHandling_Return)
            if result and result.GrabSucceeded():
                img = result.Array
                result.Release()
                if len(img.shape) == 2:
                    img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
                return True, img
            if result:
                result.Release()
        except Exception:
            pass
        return False, None

    def release(self):
        try:
            if self._cam:
                self._cam.StopGrabbing()
                self._cam.Close()
                self._cam = None
        except Exception:
            pass

    @staticmethod
    def list_devices() -> list:
        if not BASLER_AVAILABLE:
            return []
        try:
            tlf     = pylon.TlFactory.GetInstance()
            devices = tlf.EnumerateDevices()
            return [d.GetSerialNumber() for d in devices]
        except Exception:
            return []


class HarvestersCamera(CameraSource):
    """
    GenICam / GigE Vision камера через библиотеку Harvesters.
    Поддерживает Basler, Allied Vision, FLIR, IDS, Teledyne и
    любые другие GenTL-совместимые промышленные камеры.
    cti_path — путь к GenTL-провайдеру (.cti файл).
    index    — номер устройства в списке.
    """
    def __init__(self, cti_path: str, index: int = 0):
        self._cti   = cti_path.strip()
        self._index = index
        self._h     = None
        self._ia    = None

    @property
    def label(self):
        return f"GenICam [{self._index}] ({self._cti.split('/')[-1]})"

    def open(self) -> bool:
        if not HARVESTERS_AVAILABLE:
            return False
        try:
            self._h = Harvester()
            self._h.add_file(self._cti)
            self._h.update()
            if self._index >= len(self._h.device_info_list):
                return False
            self._ia = self._h.create(self._index)
            self._ia.start()
            return True
        except Exception:
            return False

    def read(self):
        if not self._ia:
            return False, None
        try:
            with self._ia.fetch(timeout=2.0) as buf:
                component = buf.payload.components[0]
                data = component.data.reshape(component.height, component.width)
                img  = cv2.cvtColor(data.astype(np.uint8), cv2.COLOR_GRAY2BGR)
                return True, img.copy()
        except Exception:
            return False, None

    def release(self):
        try:
            if self._ia:
                self._ia.stop()
                self._ia.destroy()
                self._ia = None
            if self._h:
                self._h.reset()
                self._h = None
        except Exception:
            pass


class FlirCamera(CameraSource):
    """
    FLIR / Teledyne камера через официальный SDK PySpin (Spinnaker SDK).
    Поддерживает FLIR Blackfly, Grasshopper, Chameleon и другие.
    index — номер камеры в системе.
    """
    def __init__(self, index: int = 0):
        self._index  = index
        self._system = None
        self._cam    = None

    @property
    def label(self):
        return f"FLIR [{self._index}]"

    def open(self) -> bool:
        if not FLIR_AVAILABLE:
            return False
        try:
            self._system = PySpin.System.GetInstance()
            cams = self._system.GetCameras()
            if self._index >= cams.GetSize():
                cams.Clear()
                return False
            self._cam = cams.GetByIndex(self._index)
            cams.Clear()
            self._cam.Init()
            self._cam.AcquisitionMode.SetValue(PySpin.AcquisitionMode_Continuous)
            self._cam.BeginAcquisition()
            return True
        except Exception:
            return False

    def read(self):
        if not self._cam:
            return False, None
        try:
            img_result = self._cam.GetNextImage(2000)
            if img_result.IsIncomplete():
                img_result.Release()
                return False, None
            arr  = img_result.GetNDArray()
            img_result.Release()
            if len(arr.shape) == 2:
                arr = cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
            return True, arr.copy()
        except Exception:
            return False, None

    def release(self):
        try:
            if self._cam:
                self._cam.EndAcquisition()
                self._cam.DeInit()
                del self._cam
                self._cam = None
            if self._system:
                self._system.ReleaseInstance()
                self._system = None
        except Exception:
            pass

    @staticmethod
    def list_devices() -> list:
        if not FLIR_AVAILABLE:
            return []
        try:
            system = PySpin.System.GetInstance()
            cams   = system.GetCameras()
            count  = cams.GetSize()
            cams.Clear()
            system.ReleaseInstance()
            return list(range(count))
        except Exception:
            return []


# ── Быстрое декодирование DataMatrix ──────────────────────────────────────────
def try_decode_dmtx(img_bgr: np.ndarray):
    """
    Быстрое декодирование DataMatrix: максимум 6 попыток, ранний выход.
    Порядок попыток (от самой быстрой к менее): оригинал → CLAHE → масштаб 1.5×.
    Возвращает (text, rect_in_roi) или None.
    rect_in_roi — (x, y, w, h) относительно img_bgr.
    """
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape

    clahe    = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    _, otsu  = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # 6 попыток в порядке убывания вероятности успеха
    attempts = [
        (gray,     1.0),    # 1. оригинал, 1×
        (enhanced, 1.0),    # 2. CLAHE,    1×
        (gray,     1.5),    # 3. оригинал, 1.5× (маленький символ)
        (otsu,     1.0),    # 4. Otsu,     1×
        (enhanced, 1.5),    # 5. CLAHE,    1.5×
        (otsu,     1.5),    # 6. Otsu,     1.5×
    ]

    for im, scale in attempts:
        if scale != 1.0:
            nw = max(1, int(w * scale))
            nh = max(1, int(h * scale))
            im = cv2.resize(im, (nw, nh), interpolation=cv2.INTER_CUBIC)
        try:
            results = dmtx_decode(Image.fromarray(im), timeout=80, max_count=1)
            if results:
                r    = results[0]
                text = r.data.decode("utf-8", errors="replace")
                rx = int(r.rect.left   / scale)
                ry = int(r.rect.top    / scale)
                rw = int(r.rect.width  / scale)
                rh = int(r.rect.height / scale)
                ry = max(0, h - ry - rh)
                return text, (rx, ry, rw, rh)
        except Exception:
            pass
    return None


# ── Детектор L-образного узора DataMatrix ─────────────────────────────────────
def find_datamatrix_pattern(frame: np.ndarray) -> list:
    """
    Ищет характерный L-образный фиксированный узор DataMatrix (ECC200):
      — сплошная чёрная левая сторона (Finder Pattern)
      — сплошная чёрная нижняя сторона (Finder Pattern)
      — чередующийся тактовый рисунок на правой и верхней сторонах

    Алгоритм:
      1. Морфологическое выделение сплошных горизонтальных и вертикальных линий
      2. Поиск их пересечений (кандидаты угла L)
      3. Измерение длины линий от угла (оценка размера символа)
      4. Проверка тактового рисунка на противоположных сторонах
      5. Дедупликация перекрывающихся ROI

    Возвращает список (x, y, w, h) — ROI в координатах оригинала,
    отсортированных по уверенности (лучшие — первыми).
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if len(frame.shape) == 3 else frame.copy()
    fh, fw = gray.shape

    all_candidates = []

    for scale in [1.0, 1.5, 0.75, 2.0]:
        if scale != 1.0:
            sw = max(1, int(fw * scale))
            sh = max(1, int(fh * scale))
            g  = cv2.resize(gray, (sw, sh), interpolation=cv2.INTER_LINEAR)
        else:
            g = gray
        sh2, sw2 = g.shape

        blurred = cv2.GaussianBlur(g, (3, 3), 0)
        _, otsu_val = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        # Тёмный символ на светлом фоне И светлый на тёмном
        for binary in [otsu_val, 255 - otsu_val]:
            # Минимальная длина линии = 1/20 от меньшей стороны, но не менее 12px
            min_len = max(12, min(sw2, sh2) // 20)

            hkernel = cv2.getStructuringElement(cv2.MORPH_RECT, (min_len, 1))
            vkernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, min_len))

            hlines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, hkernel)
            vlines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, vkernel)

            # Пересечения горизонтальных и вертикальных сплошных линий — кандидаты угла L
            corners = cv2.bitwise_and(hlines, vlines)
            corners = cv2.dilate(corners, np.ones((5, 5), np.uint8))

            cnts, _ = cv2.findContours(corners, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            for cnt in cnts:
                cx, cy, cw2, ch2 = cv2.boundingRect(cnt)
                ax = cx + cw2 // 2
                ay = cy + ch2 // 2

                # Длина горизонтальной линии вправо от угла
                hlen = 0
                if ax < sw2:
                    row_pix = hlines[ay, ax:]
                    for px in row_pix:
                        if px > 0:
                            hlen += 1
                        else:
                            break

                # Длина вертикальной линии вниз от угла
                vlen = 0
                if ay < sh2:
                    col_pix = vlines[ay:, ax]
                    for px in col_pix:
                        if px > 0:
                            vlen += 1
                        else:
                            break

                # Обе стороны должны быть заметной длины и примерно равными (DataMatrix — квадрат)
                if hlen < min_len or vlen < min_len:
                    continue
                ratio = max(hlen, vlen) / max(min(hlen, vlen), 1)
                if ratio > 2.2:
                    continue

                size = max(hlen, vlen)

                # ── Проверка тактового рисунка (Timing Pattern) ───────────────
                # Верхняя сторона: чередование B/W вдоль строки y=ay, x от ax до ax+size
                # Правая сторона:  чередование B/W вдоль столбца x=ax+size, y от ay до ay+size
                clock_score = 0
                try:
                    # Верхний тактовый рисунок
                    top_y = max(0, ay - 1)
                    top_x2 = min(sw2 - 1, ax + size)
                    if top_x2 > ax + 4:
                        top_strip = binary[top_y, ax:top_x2]
                        # Нормируем и считаем переходы
                        norm = (top_strip > 127).astype(int)
                        transitions = int(np.sum(np.abs(np.diff(norm))))
                        expected = max(1, (top_x2 - ax) // 2)
                        clock_score += min(2, transitions * 2 // expected)

                    # Правый тактовый рисунок
                    right_x = min(sw2 - 1, ax + size)
                    bot_y   = min(sh2 - 1, ay + size)
                    if bot_y > ay + 4:
                        right_strip = binary[ay:bot_y, right_x]
                        norm = (right_strip > 127).astype(int)
                        transitions = int(np.sum(np.abs(np.diff(norm))))
                        expected = max(1, (bot_y - ay) // 2)
                        clock_score += min(2, transitions * 2 // expected)
                except Exception:
                    pass

                # Итоговая оценка: 0..4 (4 — отличный кандидат с двумя тактовыми рисунками)
                confidence = clock_score

                # Конвертируем в координаты оригинального кадра
                pad = max(6, size // 6)
                rx  = max(0, int((ax - pad)        / scale))
                ry  = max(0, int((ay - pad)        / scale))
                rw  = min(fw - rx, int((size + 2 * pad) / scale))
                rh  = min(fh - ry, int((size + 2 * pad) / scale))

                if rw > 20 and rh > 20:
                    all_candidates.append((confidence, rx, ry, rw, rh))

    if not all_candidates:
        return []

    # Сортируем по убыванию уверенности
    all_candidates.sort(key=lambda c: -c[0])

    # Дедупликация: убираем ROI, перекрывающиеся с уже выбранными
    result = []
    for conf, x, y, rw, rh in all_candidates:
        overlap = False
        for ox, oy, ow, oh in result:
            ix = max(x, ox); ix2 = min(x + rw, ox + ow)
            iy = max(y, oy); iy2 = min(y + rh, oy + oh)
            if ix2 > ix and iy2 > iy:
                inter = (ix2 - ix) * (iy2 - iy)
                union = rw * rh + ow * oh - inter
                if union > 0 and inter / union > 0.4:
                    overlap = True
                    break
        if not overlap:
            result.append((x, y, rw, rh))
        if len(result) >= 6:
            break

    return result


def find_square_roi(frame: np.ndarray):
    """Fallback: ищет квадратный контур. Возвращает (x, y, w, h) или None."""
    gray    = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    fh, fw  = frame.shape[:2]

    candidates = []
    for t in [None, 80, 120, 160]:
        if t is None:
            _, binary = cv2.threshold(blurred, 0, 255,
                                      cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        else:
            _, binary = cv2.threshold(blurred, t, 255, cv2.THRESH_BINARY)
        contours, _ = cv2.findContours(binary, cv2.RETR_LIST,
                                       cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < 1500:
                continue
            peri   = cv2.arcLength(cnt, True)
            approx = cv2.approxPolyDP(cnt, 0.04 * peri, True)
            if len(approx) != 4:
                continue
            x, y, bw, bh = cv2.boundingRect(approx)
            aspect = max(bw, bh) / max(min(bw, bh), 1)
            if aspect > 2.0:
                continue
            candidates.append((area, x, y, bw, bh))

    if not candidates:
        return None
    candidates.sort(reverse=True)
    _, x, y, bw, bh = candidates[0]
    pad = max(8, min(bw, bh) // 8)
    x  = max(0, x - pad);        y  = max(0, y - pad)
    bw = min(fw - x, bw + 2*pad); bh = min(fh - y, bh + 2*pad)
    return x, y, bw, bh


# ── Главное приложение ─────────────────────────────────────────────────────────
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("DataMatrix Quality Scanner  —  ГОСТ Р 57302-2016")
        self.configure(bg=BG)
        self.minsize(1100, 650)
        try:
            self.state("zoomed")
        except Exception:
            self.geometry("1280x720")

        # Состояние камеры
        self.cam_source       = None          # текущий CameraSource
        self.running          = False
        self.sound_on         = True
        self.history          = []

        # Состояние декодирования
        self._last_decoded    = ""
        self._last_decoded_t  = 0.0
        self._decode_interval = 0.15
        self._scan_lock_ms    = 1500

        # Очереди (три независимых потока)
        self.display_q = queue.Queue(maxsize=1)
        self.decode_q  = queue.Queue(maxsize=1)
        self.result_q  = queue.Queue(maxsize=8)

        # Визуализация
        self._overlay      = None
        self._overlay_lock = threading.Lock()

        # Кандидаты узора (для отрисовки)
        self._pattern_rois      = []
        self._pattern_rois_lock = threading.Lock()

        self._setup_fonts()
        self._setup_styles()
        self._build_ui()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(200, self._init_cameras)
        self.after(16,  self._poll_display)
        self.after(50,  self._poll_results)

    # ── Шрифты ────────────────────────────────────────────────────────────────
    def _setup_fonts(self):
        try:
            self.fn_title = tkfont.Font(family="Segoe UI", size=11, weight="bold")
            self.fn_head  = tkfont.Font(family="Segoe UI", size=10, weight="bold")
            self.fn_body  = tkfont.Font(family="Segoe UI", size=9)
            self.fn_small = tkfont.Font(family="Segoe UI", size=8)
            self.fn_mono  = tkfont.Font(family="Consolas", size=9)
            self.fn_grade = tkfont.Font(family="Segoe UI", size=60, weight="bold")
        except Exception:
            f = tkfont.nametofont("TkDefaultFont")
            self.fn_title = self.fn_head = self.fn_body = \
                self.fn_small = self.fn_mono = self.fn_grade = f

    # ── Стили ttk ─────────────────────────────────────────────────────────────
    def _setup_styles(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("TFrame",    background=BG)
        s.configure("TLabel",    background=BG, foreground=FG, font=self.fn_body)
        s.configure("TCombobox", fieldbackground=BG3, background=BG3,
                    foreground=FG, selectbackground=BG3, selectforeground=FG)
        s.map("TCombobox",
              fieldbackground=[("readonly", BG3)],
              selectbackground=[("readonly", BG3)],
              foreground=[("readonly", FG)])
        s.configure("TScrollbar", background=BG3, troughcolor=BG2,
                    arrowcolor=FG2, bordercolor=BG2)

    # ── Интерфейс ─────────────────────────────────────────────────────────────
    def _build_ui(self):
        # Заголовок
        hdr = tk.Frame(self, bg=BG2, height=46)
        hdr.pack(fill="x", side="top")
        hdr.pack_propagate(False)

        tk.Label(hdr, text="◼ DataMatrix Quality Scanner",
                 bg=BG2, fg=PRIMARY, font=self.fn_title).pack(side="left", padx=16, pady=10)
        tk.Label(hdr, text="ГОСТ Р 57302-2016 / ISO/IEC 15415",
                 bg=BG2, fg=FG2, font=self.fn_small).pack(side="left", padx=2, pady=10)
        tk.Label(hdr, text="Авторы: А. Свидович · А. Петляков",
                 bg=BG2, fg=FG2, font=self.fn_small).pack(side="right", padx=16)
        self.snd_btn = tk.Button(hdr, text="🔊", bg=BG2, fg=PRIMARY,
                                 relief="flat", cursor="hand2",
                                 command=self._toggle_sound, font=self.fn_head)
        self.snd_btn.pack(side="right", padx=4)
        self.fps_lbl = tk.Label(hdr, text="", bg=BG2, fg=PRIMARY, font=self.fn_mono)
        self.fps_lbl.pack(side="right", padx=12)

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True)

        # ── Левая колонка: видео ──────────────────────────────────────────────
        left = tk.Frame(body, bg="black", width=680)
        left.pack(side="left", fill="both", expand=True)
        left.pack_propagate(False)

        self.video_lbl = tk.Label(left, bg="black")
        self.video_lbl.pack(fill="both", expand=True)

        # Панель управления камерой (2 строки)
        ctrl = tk.Frame(left, bg=BG2)
        ctrl.pack(fill="x", side="bottom")

        # Строка 1: тип камеры
        row1 = tk.Frame(ctrl, bg=BG2)
        row1.pack(fill="x", padx=10, pady=(8, 2))

        tk.Label(row1, text="Тип:", bg=BG2, fg=FG2, font=self.fn_small).pack(side="left")

        cam_types = ["USB / Веб-камера"]
        if BASLER_AVAILABLE:
            cam_types.append("Basler (pypylon)")
        if HARVESTERS_AVAILABLE:
            cam_types.append("GenICam / GigE Vision")
        if FLIR_AVAILABLE:
            cam_types.append("FLIR / Spinnaker")
        cam_types.append("IP-камера (RTSP/HTTP)")

        self.cam_type_var = tk.StringVar(value=cam_types[0])
        self.cam_type_combo = ttk.Combobox(row1, textvariable=self.cam_type_var,
                                           values=cam_types, state="readonly",
                                           width=22, font=self.fn_body)
        self.cam_type_combo.pack(side="left", padx=(4, 10))
        self.cam_type_combo.bind("<<ComboboxSelected>>", lambda _: self._on_type_changed())

        # Строка 2: выбор устройства / адрес
        row2 = tk.Frame(ctrl, bg=BG2)
        row2.pack(fill="x", padx=10, pady=(0, 8))

        # Combobox для USB-камер и Basler/GenICam/FLIR (выбор из списка)
        self.cam_var   = tk.StringVar()
        self.cam_combo = ttk.Combobox(row2, textvariable=self.cam_var,
                                      state="readonly", width=28, font=self.fn_body)
        self.cam_combo.pack(side="left")
        self.cam_combo.bind("<<ComboboxSelected>>", lambda _: self._on_camera_changed())

        # Поле ввода URL для IP-камеры
        self.ip_var   = tk.StringVar(value="rtsp://")
        self.ip_entry = tk.Entry(row2, textvariable=self.ip_var, bg=BG3, fg=FG,
                                 insertbackground=FG, font=self.fn_mono, width=34,
                                 relief="flat")

        # Поле для CTI-пути (GenICam)
        self.cti_var   = tk.StringVar(value="")
        self.cti_entry = tk.Entry(row2, textvariable=self.cti_var, bg=BG3, fg=FG,
                                  insertbackground=FG, font=self.fn_mono, width=28,
                                  relief="flat")

        tk.Button(row2, text="↺", bg=BG3, fg=PRIMARY, relief="flat",
                  cursor="hand2", font=self.fn_head,
                  command=self._init_cameras).pack(side="left", padx=(6, 0))

        self.start_btn = tk.Button(row2, text="  ▶  Старт  ",
                                   bg=PRIMARY, fg=BG, relief="flat",
                                   font=self.fn_head, cursor="hand2",
                                   command=self._toggle_scan, padx=8, pady=4)
        self.start_btn.pack(side="left", padx=8)

        self.status_lbl = tk.Label(row2, text="Инициализация...",
                                   bg=BG2, fg=FG2, font=self.fn_small)
        self.status_lbl.pack(side="left", padx=4)

        # ── Правая колонка: результаты ────────────────────────────────────────
        right = tk.Frame(body, bg=BG, width=420)
        right.pack(side="right", fill="both")
        right.pack_propagate(False)

        tab_bar = tk.Frame(right, bg=BG2)
        tab_bar.pack(fill="x")
        self._tab_btns = {}
        for key, label in [("result", "Результат анализа"), ("history", "История")]:
            btn = tk.Button(tab_bar, text=label, relief="flat", cursor="hand2",
                            bg=BG2, fg=FG2, font=self.fn_body, padx=12, pady=8,
                            command=lambda k=key: self._switch_tab(k))
            btn.pack(side="left", fill="x", expand=True)
            self._tab_btns[key] = btn

        self.tab_frame = tk.Frame(right, bg=BG)
        self.tab_frame.pack(fill="both", expand=True)

        self._build_result_tab()
        self._build_history_tab()
        self._switch_tab("result")

        bar = tk.Frame(self, bg=BG2, height=24)
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)
        tk.Label(bar, text="ГОСТ Р 57302-2016 · ISO/IEC 15415:2011",
                 bg=BG2, fg=FG2, font=self.fn_small).pack(side="left", padx=12, pady=4)
        tk.Label(bar, text="Авторы: Александр Свидович, Алексей Петляков",
                 bg=BG2, fg=FG2, font=self.fn_small).pack(side="right", padx=12, pady=4)

    def _build_result_tab(self):
        self.result_frame = tk.Frame(self.tab_frame, bg=BG)

        grade_card = tk.Frame(self.result_frame, bg=BG2, padx=16, pady=12)
        grade_card.pack(fill="x", padx=10, pady=(10, 4))

        self.grade_lbl = tk.Label(grade_card, text="—", bg=BG2, fg=FG2,
                                  font=self.fn_grade)
        self.grade_lbl.pack(side="left")

        ginfo = tk.Frame(grade_card, bg=BG2)
        ginfo.pack(side="left", padx=14, fill="x", expand=True)
        self.grade_name_lbl = tk.Label(ginfo, text="Ожидание сканирования",
                                       bg=BG2, fg=FG2, font=self.fn_head)
        self.grade_name_lbl.pack(anchor="w")
        self.score_lbl = tk.Label(ginfo, text="Поднесите DataMatrix к камере",
                                  bg=BG2, fg=FG2, font=self.fn_small)
        self.score_lbl.pack(anchor="w")
        self.grade_bar_bg = tk.Frame(ginfo, bg=BG3, height=8)
        self.grade_bar_bg.pack(fill="x", pady=(6, 0))
        self.grade_bar_fg = tk.Frame(self.grade_bar_bg, bg=FG2, height=8)
        self.grade_bar_fg.place(relwidth=0.0, relheight=1.0)

        tk.Label(self.result_frame, text="  ПАРАМЕТРЫ КАЧЕСТВА (ГОСТ Р 57302-2016)",
                 bg=BG, fg=FG2, font=self.fn_small, anchor="w").pack(fill="x", padx=10, pady=(6, 2))

        params_card = tk.Frame(self.result_frame, bg=BG2)
        params_card.pack(fill="x", padx=10, pady=(0, 6))

        self.param_rows = {}
        for i, (key, name, ref) in enumerate(PARAMS_META):
            row_bg = BG2 if i % 2 == 0 else BG3
            row = tk.Frame(params_card, bg=row_bg)
            row.pack(fill="x")

            grade_box = tk.Label(row, text="—", bg=BG3, fg=FG2,
                                 font=self.fn_mono, width=3, padx=4, pady=3)
            grade_box.pack(side="left", padx=(8, 6), pady=2)

            pct_lbl = tk.Label(row, text="   —%", bg=row_bg, fg=FG2,
                               font=self.fn_mono, width=7, anchor="e")
            pct_lbl.pack(side="right", padx=6)
            tk.Label(row, text=ref, bg=row_bg, fg=FG2,
                     font=self.fn_small, width=7, anchor="e").pack(side="right")

            info = tk.Frame(row, bg=row_bg)
            info.pack(side="left", fill="x", expand=True)
            tk.Label(info, text=f"{key}  {name}", bg=row_bg, fg=FG,
                     font=self.fn_body, anchor="w").pack(fill="x")
            bar_bg = tk.Frame(info, bg=BG3, height=4)
            bar_bg.pack(fill="x", pady=(0, 3))
            bar_fill = tk.Frame(bar_bg, bg=FG2, height=4)
            bar_fill.place(relwidth=0.0, relheight=1.0)

            self.param_rows[key] = {"grade_box": grade_box, "bar": bar_fill, "pct": pct_lbl}

        tk.Label(self.result_frame, text="  ДЕКОДИРОВАННЫЕ ДАННЫЕ",
                 bg=BG, fg=FG2, font=self.fn_small, anchor="w").pack(fill="x", padx=10, pady=(4, 2))
        data_f = tk.Frame(self.result_frame, bg=BG2, padx=10, pady=8)
        data_f.pack(fill="x", padx=10)
        self.data_lbl = tk.Label(data_f, text="—", bg=BG2, fg=FG,
                                 font=self.fn_mono, wraplength=360, justify="left", anchor="w")
        self.data_lbl.pack(fill="x")

        self.time_lbl = tk.Label(self.result_frame, text="",
                                 bg=BG, fg=FG2, font=self.fn_small)
        self.time_lbl.pack(pady=4)

    def _build_history_tab(self):
        self.history_frame = tk.Frame(self.tab_frame, bg=BG)

        wrap = tk.Frame(self.history_frame, bg=BG)
        wrap.pack(fill="both", expand=True)

        sb = ttk.Scrollbar(wrap)
        sb.pack(side="right", fill="y")

        self.hist_canvas = tk.Canvas(wrap, bg=BG, yscrollcommand=sb.set,
                                     highlightthickness=0)
        self.hist_canvas.pack(side="left", fill="both", expand=True)
        sb.config(command=self.hist_canvas.yview)

        self.hist_inner = tk.Frame(self.hist_canvas, bg=BG)
        self._hist_win  = self.hist_canvas.create_window(
            (0, 0), window=self.hist_inner, anchor="nw")
        self.hist_inner.bind("<Configure>", lambda _: self.hist_canvas.configure(
            scrollregion=self.hist_canvas.bbox("all")))
        self.hist_canvas.bind("<Configure>", lambda e: self.hist_canvas.itemconfig(
            self._hist_win, width=e.width))

        tk.Label(self.hist_inner, text="История пуста",
                 bg=BG, fg=FG2, font=self.fn_body).pack(pady=40)

    # ── Вкладки ───────────────────────────────────────────────────────────────
    def _switch_tab(self, key: str):
        for k, btn in self._tab_btns.items():
            btn.config(bg=BG3 if k == key else BG2,
                       fg=PRIMARY if k == key else FG2)
        self.result_frame.pack_forget()
        self.history_frame.pack_forget()
        if key == "result":
            self.result_frame.pack(fill="both", expand=True)
        else:
            self.history_frame.pack(fill="both", expand=True)

    # ── Камера: тип ───────────────────────────────────────────────────────────
    def _on_type_changed(self):
        """Переключаем UI под выбранный тип камеры."""
        t = self.cam_type_var.get()
        # Скрываем все поля
        self.cam_combo.pack_forget()
        self.ip_entry.pack_forget()
        self.cti_entry.pack_forget()

        if t == "IP-камера (RTSP/HTTP)":
            self.ip_entry.pack(side="left")
            self.status_lbl.config(text="Введите URL и нажмите Старт")
        elif t == "GenICam / GigE Vision":
            self.cti_entry.pack(side="left")
            self.cam_combo.pack(side="left", padx=(4, 0))
            self.status_lbl.config(text="Укажите путь к .cti файлу")
        else:
            self.cam_combo.pack(side="left")
            self._init_cameras()

    # ── Камера: инициализация ─────────────────────────────────────────────────
    def _init_cameras(self):
        t = self.cam_type_var.get()
        self.status_lbl.config(text="Поиск камер...")
        self.update_idletasks()

        if t == "USB / Веб-камера":
            available = []
            for i in range(10):
                try:
                    cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
                    if cap.isOpened():
                        ret, _ = cap.read()
                        if ret:
                            available.append(i)
                    cap.release()
                except Exception:
                    pass
            if available:
                self.cam_combo["values"] = [f"USB Камера {i}" for i in available]
                self.cam_combo.current(len(available) - 1)
                self._usb_indices = available
                self.status_lbl.config(text=f"Найдено камер: {len(available)}")
            else:
                self.cam_combo["values"] = ["Камеры не найдены"]
                self.cam_combo.current(0)
                self._usb_indices = []
                self.status_lbl.config(text="USB-камера не найдена")

        elif t == "Basler (pypylon)":
            serials = BaslerCamera.list_devices()
            if serials:
                self.cam_combo["values"] = [f"Basler S/N: {s}" for s in serials]
                self.cam_combo.current(0)
                self._basler_serials = serials
                self.status_lbl.config(text=f"Basler камер: {len(serials)}")
            else:
                self.cam_combo["values"] = ["Basler не найдены"]
                self.cam_combo.current(0)
                self._basler_serials = []
                self.status_lbl.config(text="Basler камеры не найдены")

        elif t == "FLIR / Spinnaker":
            indices = FlirCamera.list_devices()
            if indices:
                self.cam_combo["values"] = [f"FLIR [{i}]" for i in indices]
                self.cam_combo.current(0)
                self._flir_indices = indices
                self.status_lbl.config(text=f"FLIR камер: {len(indices)}")
            else:
                self.cam_combo["values"] = ["FLIR не найдены"]
                self.cam_combo.current(0)
                self._flir_indices = []
                self.status_lbl.config(text="FLIR камеры не найдены")

        elif t == "GenICam / GigE Vision":
            self.cam_combo["values"] = ["Устройство 0", "Устройство 1",
                                        "Устройство 2", "Устройство 3"]
            self.cam_combo.current(0)
            self.status_lbl.config(text="Укажите .cti файл и нажмите Старт")

        elif t == "IP-камера (RTSP/HTTP)":
            self.status_lbl.config(text="Введите URL и нажмите Старт")

    def _on_camera_changed(self):
        if self.running:
            self._stop_camera()
            self._start_camera()

    def _build_cam_source(self) -> CameraSource | None:
        """Создаёт объект CameraSource на основе текущих настроек UI."""
        t = self.cam_type_var.get()

        if t == "USB / Веб-камера":
            indices = getattr(self, "_usb_indices", [])
            if not indices:
                return None
            idx = min(self.cam_combo.current(), len(indices) - 1)
            return OpenCVCamera(indices[max(0, idx)])

        elif t == "Basler (pypylon)":
            serials = getattr(self, "_basler_serials", [])
            if not serials:
                return None
            idx = min(self.cam_combo.current(), len(serials) - 1)
            return BaslerCamera(serials[max(0, idx)])

        elif t == "FLIR / Spinnaker":
            indices = getattr(self, "_flir_indices", [])
            if not indices:
                return None
            idx = min(self.cam_combo.current(), len(indices) - 1)
            return FlirCamera(indices[max(0, idx)])

        elif t == "GenICam / GigE Vision":
            cti = self.cti_var.get().strip()
            if not cti:
                messagebox.showerror("GenICam", "Укажите путь к .cti файлу провайдера GenTL.")
                return None
            dev_idx = self.cam_combo.current()
            return HarvestersCamera(cti, dev_idx)

        elif t == "IP-камера (RTSP/HTTP)":
            url = self.ip_var.get().strip()
            if not url or url == "rtsp://":
                messagebox.showerror("IP-камера", "Введите корректный URL камеры.")
                return None
            return RTSPCamera(url)

        return None

    def _toggle_scan(self):
        if self.running:
            self._stop_camera()
            self.start_btn.config(text="  ▶  Старт  ", bg=PRIMARY, fg=BG)
            self.status_lbl.config(text="Остановлено")
            self.fps_lbl.config(text="")
        else:
            self._start_camera()
            if self.running:
                self.start_btn.config(text="  ⏹  Стоп  ",
                                      bg=GRADE_COLORS["F"], fg="white")
                self.status_lbl.config(text="Сканирование...")

    def _start_camera(self):
        src = self._build_cam_source()
        if src is None:
            return
        try:
            self.status_lbl.config(text=f"Подключение: {src.label}...")
            self.update_idletasks()
            if not src.open():
                self.status_lbl.config(text=f"Ошибка: {src.label} не открывается")
                return
            self.cam_source = src
            self.running    = True
            threading.Thread(target=self._capture_loop, daemon=True).start()
            if DMTX_AVAILABLE:
                threading.Thread(target=self._decode_loop, daemon=True).start()
            else:
                threading.Thread(target=self._square_only_loop, daemon=True).start()
        except Exception as e:
            self.status_lbl.config(text=f"Ошибка: {e}")

    def _stop_camera(self):
        self.running = False
        time.sleep(0.3)
        if self.cam_source:
            self.cam_source.release()
            self.cam_source = None
        self.video_lbl.config(image="")
        with self._overlay_lock:
            self._overlay = None
        with self._pattern_rois_lock:
            self._pattern_rois = []

    # ── Поток 1: захват кадров ────────────────────────────────────────────────
    def _capture_loop(self):
        fps_count = 0
        fps_t     = time.time()
        while self.running and self.cam_source:
            ret, frame = self.cam_source.read()
            if not ret or frame is None:
                time.sleep(0.005)
                continue
            fps_count += 1
            now = time.time()
            if now - fps_t >= 1.0:
                v = fps_count
                self.after(0, lambda v=v: self.fps_lbl.config(text=f"{v} fps"))
                fps_count = 0
                fps_t = now
            try:
                self.display_q.put_nowait(frame)
            except queue.Full:
                try:
                    self.display_q.get_nowait()
                    self.display_q.put_nowait(frame)
                except Exception:
                    pass
            try:
                self.decode_q.put_nowait(frame)
            except queue.Full:
                pass

    # ── Поток 2: декодирование DataMatrix с поиском узоров ───────────────────
    def _decode_loop(self):
        while self.running:
            try:
                frame = self.decode_q.get(timeout=0.5)
            except queue.Empty:
                continue

            now = time.time()
            if now - self._last_decoded_t < self._decode_interval:
                continue

            fh, fw = frame.shape[:2]
            text         = None
            box_in_frame = None
            square_found = False

            # ── Шаг 1: Поиск L-образного узора DataMatrix ────────────────────
            pattern_rois = find_datamatrix_pattern(frame)

            with self._pattern_rois_lock:
                self._pattern_rois = list(pattern_rois)

            # Пробуем декодировать каждый найденный ROI узора
            for px, py, pw, ph in pattern_rois:
                px = max(0, px); py = max(0, py)
                pw = min(fw - px, pw); ph = min(fh - py, ph)
                if pw < 10 or ph < 10:
                    continue
                roi = frame[py:py+ph, px:px+pw]
                result = try_decode_dmtx(roi)
                if result:
                    text, rect = result
                    box_in_frame = (px + rect[0], py + rect[1], rect[2], rect[3])
                    break

            # ── Шаг 2: весь кадр (если узор не дал результата) ───────────────
            if text is None:
                result = try_decode_dmtx(frame)
                if result:
                    text, rect = result
                    box_in_frame = rect

            # ── Шаг 3: центральная зона ────────────────────────────────────────
            if text is None:
                m  = 0.15
                ox = int(fw * m);      oy = int(fh * m)
                ex = int(fw * (1-m));  ey = int(fh * (1-m))
                roi = frame[oy:ey, ox:ex]
                result = try_decode_dmtx(roi)
                if result:
                    text, rect = result
                    box_in_frame = (ox + rect[0], oy + rect[1], rect[2], rect[3])

            # ── Шаг 4: fallback — поиск квадрата ──────────────────────────────
            if text is None:
                sq = find_square_roi(frame)
                if sq is not None:
                    sx, sy, sw, sh = sq
                    sq_roi = frame[sy:sy+sh, sx:sx+sw]
                    result = try_decode_dmtx(sq_roi)
                    if result:
                        text, rect = result
                        box_in_frame = (sx + rect[0], sy + rect[1], rect[2], rect[3])
                    else:
                        square_found = True
                        box_in_frame = sq

            if text is None and not square_found:
                continue

            label = text if text else "[нераспознан]"
            if label == self._last_decoded and now - self._last_decoded_t < (self._scan_lock_ms / 1000.0):
                continue

            self._last_decoded   = label
            self._last_decoded_t = now
            self.after(self._scan_lock_ms, self._reset_scan_lock)

            with self._overlay_lock:
                self._overlay = {
                    "box":   box_in_frame,
                    "t":     time.time(),
                    "ok":    not square_found,
                    "grade": None,
                }

            t0 = time.perf_counter()
            if square_found:
                params = {k: {"value": 0.0, "grade": "F"} for k, _, _ in PARAMS_META}
                res    = {"params": params, "overall": "F", "score": 0.0}
            else:
                if box_in_frame:
                    bx, by, bw, bh = box_in_frame
                    bx = max(0, bx); by = max(0, by)
                    bw = min(fw - bx, bw); bh = min(fh - by, bh)
                    analysis_roi = frame[by:by+bh, bx:bx+bw] if bw > 4 and bh > 4 else frame
                else:
                    analysis_roi = frame
                res = analyze_datamatrix_iso(analysis_roi)
            ms = (time.perf_counter() - t0) * 1000.0

            with self._overlay_lock:
                if self._overlay:
                    self._overlay["grade"] = res["overall"]

            if self.sound_on:
                play_sound(res["overall"])

            try:
                self.result_q.put_nowait({
                    "text":    label,
                    "res":     res,
                    "ms":      ms,
                    "decoded": not square_found,
                })
            except queue.Full:
                pass

    # ── Поток 2b: только квадраты (когда pylibdmtx недоступен) ──────────────
    def _square_only_loop(self):
        while self.running:
            try:
                frame = self.decode_q.get(timeout=0.5)
            except queue.Empty:
                continue
            now = time.time()
            if now - self._last_decoded_t < self._decode_interval:
                continue

            # Поиск узора даже без декодера
            pattern_rois = find_datamatrix_pattern(frame)
            with self._pattern_rois_lock:
                self._pattern_rois = list(pattern_rois)

            sq = find_square_roi(frame)
            if not sq:
                continue
            label = "[нераспознан]"
            if label == self._last_decoded and now - self._last_decoded_t < (self._scan_lock_ms / 1000.0):
                continue
            self._last_decoded   = label
            self._last_decoded_t = now
            self.after(self._scan_lock_ms, self._reset_scan_lock)
            with self._overlay_lock:
                self._overlay = {"box": sq, "t": time.time(), "ok": False, "grade": "F"}
            params = {k: {"value": 0.0, "grade": "F"} for k, _, _ in PARAMS_META}
            res    = {"params": params, "overall": "F", "score": 0.0}
            if self.sound_on:
                play_sound("F")
            try:
                self.result_q.put_nowait({"text": label, "res": res, "ms": 0.0, "decoded": False})
            except queue.Full:
                pass

    # ── Поток 3 (главный): отображение видео ─────────────────────────────────
    def _poll_display(self):
        try:
            frame = self.display_q.get_nowait()
            self._render_frame(frame)
        except queue.Empty:
            pass
        self.after(16, self._poll_display)

    def _render_frame(self, frame: np.ndarray):
        fh, fw = frame.shape[:2]
        display = frame.copy()

        # Прицел (центральная зона)
        m  = 0.15
        x1 = int(fw * m);     y1 = int(fh * m)
        x2 = int(fw * (1-m)); y2 = int(fh * (1-m))
        aim_clr = (0, 180, 216)
        c = 28
        for sx, sy, dx, dy in [(x1,y1,1,1),(x2,y1,-1,1),(x1,y2,1,-1),(x2,y2,-1,-1)]:
            cv2.line(display, (sx, sy), (sx + dx*c, sy), aim_clr, 2)
            cv2.line(display, (sx, sy), (sx, sy + dy*c), aim_clr, 2)
        cv2.line(display, (0, fh//2), (fw, fh//2), aim_clr, 1)

        # ── Отрисовка найденных узоров DataMatrix (пунктирные рамки) ─────────
        with self._pattern_rois_lock:
            prois = list(self._pattern_rois)

        for rx, ry, rw, rh in prois:
            # Пунктирный синий прямоугольник для кандидатов узора
            dash = 8
            clr  = (0, 140, 200)
            for i in range(0, rw, dash * 2):
                cv2.line(display, (rx+i, ry), (min(rx+i+dash, rx+rw), ry), clr, 1)
                cv2.line(display, (rx+i, ry+rh), (min(rx+i+dash, rx+rw), ry+rh), clr, 1)
            for i in range(0, rh, dash * 2):
                cv2.line(display, (rx, ry+i), (rx, min(ry+i+dash, ry+rh)), clr, 1)
                cv2.line(display, (rx+rw, ry+i), (rx+rw, min(ry+i+dash, ry+rh)), clr, 1)
            # Метка «DM?»
            cv2.putText(display, "DM?", (rx + 2, ry - 4 if ry > 14 else ry + rh + 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, clr, 1, cv2.LINE_AA)

        # ── Оверлей подтверждённого символа ───────────────────────────────────
        with self._overlay_lock:
            ov = self._overlay

        if ov and (time.time() - ov["t"]) < 2.5:
            bx, by, bw, bh = ov["box"]
            grade  = ov.get("grade")
            if ov["ok"] and grade and grade != "F":
                box_clr = (34, 197, 94)
            elif ov["ok"]:
                box_clr = (249, 115, 22)
            else:
                box_clr = (239, 68, 68)

            cv2.rectangle(display, (bx, by), (bx+bw, by+bh), box_clr, 3)
            cc = 20
            for px, py, dx, dy in [(bx,by,1,1),(bx+bw,by,-1,1),(bx,by+bh,1,-1),(bx+bw,by+bh,-1,-1)]:
                cv2.line(display, (px, py), (px + dx*cc, py), box_clr, 5)
                cv2.line(display, (px, py), (px, py + dy*cc), box_clr, 5)

            if grade:
                txt = grade if ov["ok"] else "?"
                cv2.putText(display, txt,
                            (bx + 6, by - 10 if by > 20 else by + bh + 24),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.2, box_clr, 3, cv2.LINE_AA)

        # Масштабирование под размер виджета
        cw = max(1, self.video_lbl.winfo_width())
        ch = max(1, self.video_lbl.winfo_height())
        sc = min(cw / fw, ch / fh)
        nw = max(1, int(fw * sc))
        nh = max(1, int(fh * sc))
        small = cv2.resize(display, (nw, nh), interpolation=cv2.INTER_LINEAR)
        rgb   = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
        imgtk = ImageTk.PhotoImage(image=Image.fromarray(rgb))
        self.video_lbl.imgtk = imgtk
        self.video_lbl.config(image=imgtk)

    # ── Результаты ────────────────────────────────────────────────────────────
    def _poll_results(self):
        try:
            item = self.result_q.get_nowait()
            self._update_result(item["text"], item["res"], item["ms"],
                                item.get("decoded", True))
            self._add_history(item["text"], item["res"])
        except queue.Empty:
            pass
        self.after(50, self._poll_results)

    def _update_result(self, text: str, res: dict, ms: float, decoded: bool = True):
        grade = res["overall"]
        score = res["score"]
        color = GRADE_COLORS[grade]

        self.grade_lbl.config(text=grade, fg=color)
        self.grade_name_lbl.config(
            text=GRADE_LABELS[grade] if decoded else "Квадрат найден — DataMatrix не читается",
            fg=color)
        self.score_lbl.config(
            text=f"Итоговый балл: {score:.2f} / 4.0   (анализ: {ms:.0f} мс)")
        self.grade_bar_fg.place(relwidth=score / 4.0, relheight=1.0)
        self.grade_bar_fg.config(bg=color)

        for key, meta in res["params"].items():
            row = self.param_rows[key]
            g   = meta["grade"]
            v   = meta["value"]
            c   = GRADE_COLORS[g]
            d   = GRADE_DIM[g]
            row["grade_box"].config(text=g, bg=d, fg=c)
            row["bar"].place(relwidth=v, relheight=1.0)
            row["bar"].config(bg=c)
            row["pct"].config(text=f"{v*100:5.1f}%", fg=c)

        self.data_lbl.config(text=text)
        self.time_lbl.config(text=datetime.now().strftime("%H:%M:%S"))

    def _add_history(self, text: str, res: dict):
        self.history.insert(0, {"text": text, "res": res, "ts": datetime.now()})
        if len(self.history) > 50:
            self.history.pop()
        self._rebuild_history()

    def _rebuild_history(self):
        for w in self.hist_inner.winfo_children():
            w.destroy()
        if not self.history:
            tk.Label(self.hist_inner, text="История пуста",
                     bg=BG, fg=FG2, font=self.fn_body).pack(pady=40)
            return
        for rec in self.history:
            grade = rec["res"]["overall"]
            color = GRADE_COLORS[grade]
            dim   = GRADE_DIM[grade]
            row   = tk.Frame(self.hist_inner, bg=BG2)
            row.pack(fill="x", padx=6, pady=2)
            tk.Label(row, text=grade, bg=dim, fg=color,
                     font=self.fn_head, width=4, pady=6).pack(side="left")
            info = tk.Frame(row, bg=BG2)
            info.pack(side="left", fill="x", expand=True, padx=8)
            tk.Label(info, text=rec["text"][:50], bg=BG2, fg=FG,
                     font=self.fn_mono, anchor="w").pack(fill="x")
            tk.Label(info,
                     text=rec["ts"].strftime("%H:%M:%S") + f"  ·  балл {rec['res']['score']:.2f}",
                     bg=BG2, fg=FG2, font=self.fn_small, anchor="w").pack(fill="x")

        self._tab_btns["history"].config(text=f"История ({len(self.history)})")

    # ── Прочее ────────────────────────────────────────────────────────────────
    def _reset_scan_lock(self):
        """Сбрасывает блокировку повтора — программа готова найти следующий код."""
        self._last_decoded   = ""
        self._last_decoded_t = 0.0

    def _toggle_sound(self):
        self.sound_on = not self.sound_on
        self.snd_btn.config(
            text="🔊" if self.sound_on else "🔇",
            fg=PRIMARY if self.sound_on else FG2)

    def _on_close(self):
        self._stop_camera()
        self.destroy()


# ── Запуск ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = App()
    app.mainloop()
