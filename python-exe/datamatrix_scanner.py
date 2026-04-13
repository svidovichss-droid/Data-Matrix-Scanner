"""
DataMatrix Quality Scanner
ГОСТ Р 57302-2016 / ISO/IEC 15415
Авторы: Александр Свидович, Алексей Петляков
"""

import tkinter as tk
from tkinter import ttk, font as tkfont
import cv2
import numpy as np
from PIL import Image, ImageTk
import threading
import queue
import time
import winsound
from datetime import datetime
import sys
import os

try:
    from pylibdmtx.pylibdmtx import decode as dmtx_decode
    DMTX_AVAILABLE = True
except Exception:
    DMTX_AVAILABLE = False

# ─── Цвета темы ────────────────────────────────────────────────────────────────
BG        = "#0f1117"
BG2       = "#161b22"
BG3       = "#1c2333"
BORDER    = "#30363d"
FG        = "#e6edf3"
FG2       = "#8b949e"
PRIMARY   = "#00b4d8"
GRADE_A   = "#22c55e"
GRADE_B   = "#14b8a6"
GRADE_C   = "#eab308"
GRADE_D   = "#f97316"
GRADE_F   = "#ef4444"

GRADE_COLORS = {"A": GRADE_A, "B": GRADE_B, "C": GRADE_C, "D": GRADE_D, "F": GRADE_F}
GRADE_LABELS = {
    "A": "Отлично",
    "B": "Хорошо",
    "C": "Удовлетворительно",
    "D": "Плохо",
    "F": "Неудовлетворительно",
}

# ─── Звуковое сопровождение ────────────────────────────────────────────────────
def play_sound(grade: str):
    def _play():
        try:
            if grade == "A":
                winsound.Beep(880, 100)
                time.sleep(0.05)
                winsound.Beep(1100, 140)
            elif grade == "B":
                winsound.Beep(780, 100)
                time.sleep(0.05)
                winsound.Beep(980, 140)
            elif grade == "C":
                winsound.Beep(660, 90)
                time.sleep(0.08)
                winsound.Beep(660, 90)
            elif grade == "D":
                for i in range(4):
                    winsound.Beep(440 if i % 2 == 0 else 330, 160)
                    time.sleep(0.04)
            elif grade == "F":
                for i in range(8):
                    winsound.Beep(380 if i % 2 == 0 else 220, 110)
                    time.sleep(0.03)
        except Exception:
            pass
    threading.Thread(target=_play, daemon=True).start()


# ─── Анализ качества ГОСТ Р 57302-2016 ────────────────────────────────────────
PARAMS_META = [
    ("SC",  "Контраст символа",                   "п. 5.4"),
    ("MOD", "Модуляция",                           "п. 5.5"),
    ("RM",  "Запас отражательной способности",     "п. 5.6"),
    ("FPD", "Повреждение фиксированного рисунка",  "п. 5.7"),
    ("ANU", "Осевая неравномерность",              "п. 5.8"),
    ("GNU", "Неравномерность сетки",               "п. 5.9"),
    ("UEC", "Неиспользованная коррекция ошибок",   "п. 5.10"),
    ("PG",  "Прирост печати",                      "п. 5.11"),
]

GRADE_THRESH = {
    "SC":  [0.70, 0.55, 0.40, 0.20],
    "MOD": [0.75, 0.60, 0.40, 0.20],
    "RM":  [0.65, 0.45, 0.30, 0.15],
    "FPD": [0.85, 0.65, 0.45, 0.25],
    "ANU": [0.80, 0.60, 0.40, 0.20],
    "GNU": [0.82, 0.62, 0.42, 0.22],
    "UEC": [0.62, 0.50, 0.37, 0.25],
    "PG":  [0.80, 0.60, 0.40, 0.20],
}

def value_to_grade(value: float, key: str) -> str:
    t = GRADE_THRESH[key]
    if value >= t[0]: return "A"
    if value >= t[1]: return "B"
    if value >= t[2]: return "C"
    if value >= t[3]: return "D"
    return "F"

def grade_to_score(g: str) -> float:
    return {"A": 4, "B": 3, "C": 2, "D": 1, "F": 0}[g]

def worst_grade(grades):
    s = min(grade_to_score(g) for g in grades)
    thresholds = [(3.5, "A"), (2.5, "B"), (1.5, "C"), (0.5, "D")]
    for t, g in thresholds:
        if s >= t: return g
    return "F"

def analyze_frame(frame: np.ndarray) -> dict:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
    h, w = gray.shape
    total = h * w

    Rmax = float(gray.max())
    Rmin = float(gray.min())
    rng  = Rmax - Rmin if Rmax != Rmin else 1.0

    sc = (Rmax - Rmin) / Rmax if Rmax > 0 else 0.0

    threshold = (Rmax + Rmin) / 2
    dark   = gray[gray <  threshold]
    light  = gray[gray >= threshold]
    dark_mean  = float(dark.mean())  if len(dark)  > 0 else 0.0
    light_mean = float(light.mean()) if len(light) > 0 else 255.0
    dark_std   = float(dark.std())   if len(dark)  > 1 else 0.0
    light_std  = float(light.std())  if len(light) > 1 else 0.0
    mod = 1.0 - (dark_std + light_std) / rng

    rm = min(
        (light_mean - threshold) / max(light_mean - Rmin, 1),
        (threshold - dark_mean)  / max(Rmax - dark_mean,  1),
    )

    # FPD — оцениваем по горизонтальным переходам в верхних строках
    edges = 0
    for row in range(min(4, h)):
        line = (gray[row] < threshold).astype(np.uint8)
        edges += int(np.sum(np.abs(np.diff(line))))
    expected = (w + h) * 2
    fpd = min(1.0, edges / max(expected * 0.5, 1))

    # ANU — вариация плотности по строкам и столбцам
    row_dark = np.array([(gray[y] < threshold).mean() for y in range(h)])
    col_dark = np.array([(gray[:, x] < threshold).mean() for x in range(w)])
    anu = 1.0 - float(np.sqrt((row_dark.var() + col_dark.var()) / 2))

    # GNU — вариация яркости блоков
    bs = max(4, min(h, w) // 8)
    block_means = []
    for by in range(0, h - bs + 1, bs):
        for bx in range(0, w - bs + 1, bs):
            block_means.append(float(gray[by:by+bs, bx:bx+bs].mean()))
    gnu = 1.0 - (float(np.std(block_means)) / 255) if len(block_means) > 1 else 1.0

    # UEC
    uec = min(1.0, sc * mod)

    # PG — отклонение доли тёмных пикселей от 0.5
    dark_ratio = len(dark) / total
    pg = 1.0 - min(1.0, abs(dark_ratio - 0.5) * 4)

    raw = {"SC": sc, "MOD": mod, "RM": rm, "FPD": fpd,
           "ANU": anu, "GNU": gnu, "UEC": uec, "PG": pg}

    params = {}
    for key, val in raw.items():
        v = max(0.0, min(1.0, val))
        params[key] = {"value": v, "grade": value_to_grade(v, key)}

    grades = [p["grade"] for p in params.values()]
    avg    = sum(grade_to_score(g) for g in grades) / len(grades)
    overall = worst_grade(grades)
    return {"params": params, "overall": overall, "score": avg}


# ─── Главное приложение ────────────────────────────────────────────────────────
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("DataMatrix Quality Scanner  —  ГОСТ Р 57302-2016")
        self.configure(bg=BG)
        self.state("zoomed")
        self.minsize(1100, 650)

        self._setup_fonts()
        self._setup_styles()
        self._build_ui()

        self.cap = None
        self.camera_id = 0
        self.running = False
        self.sound_on = True
        self.history = []

        self._last_decoded = ""
        self._last_decoded_time = 0.0

        self.frame_queue = queue.Queue(maxsize=2)
        self._update_camera_list()
        self.after(100, self._poll_frame)

    # ── шрифты и стили ──────────────────────────────────────────────────────
    def _setup_fonts(self):
        try:
            self.fn_body  = tkfont.Font(family="Segoe UI",    size=9)
            self.fn_small = tkfont.Font(family="Segoe UI",    size=8)
            self.fn_mono  = tkfont.Font(family="Consolas",    size=9)
            self.fn_grade = tkfont.Font(family="Segoe UI",    size=60, weight="bold")
            self.fn_head  = tkfont.Font(family="Segoe UI",    size=10, weight="bold")
            self.fn_title = tkfont.Font(family="Segoe UI",    size=11, weight="bold")
        except Exception:
            self.fn_body = self.fn_small = self.fn_mono = \
                self.fn_grade = self.fn_head = self.fn_title = None

    def _setup_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame",       background=BG)
        style.configure("Card.TFrame",  background=BG2)
        style.configure("TLabel",       background=BG,  foreground=FG,  font=self.fn_body)
        style.configure("Card.TLabel",  background=BG2, foreground=FG,  font=self.fn_body)
        style.configure("Muted.TLabel", background=BG2, foreground=FG2, font=self.fn_small)
        style.configure("TCombobox",    fieldbackground=BG3, background=BG3,
                        foreground=FG, selectbackground=BG3, selectforeground=FG)
        style.map("TCombobox",
                  fieldbackground=[("readonly", BG3)],
                  selectbackground=[("readonly", BG3)],
                  foreground=[("readonly", FG)])
        style.configure("TScrollbar", background=BG3, troughcolor=BG2,
                        arrowcolor=FG2, bordercolor=BG2)

    # ── интерфейс ────────────────────────────────────────────────────────────
    def _build_ui(self):
        # заголовок
        hdr = tk.Frame(self, bg=BG2, height=46)
        hdr.pack(fill="x", side="top")
        hdr.pack_propagate(False)

        tk.Label(hdr, text="◼ DataMatrix Quality Scanner",
                 bg=BG2, fg=PRIMARY, font=self.fn_title).pack(side="left", padx=16, pady=10)
        tk.Label(hdr, text="ГОСТ Р 57302-2016 / ISO/IEC 15415",
                 bg=BG2, fg=FG2, font=self.fn_small).pack(side="left", padx=0, pady=10)

        self.fps_lbl = tk.Label(hdr, text="", bg=BG2, fg=PRIMARY, font=self.fn_mono)
        self.fps_lbl.pack(side="right", padx=12)

        self.snd_btn = tk.Button(hdr, text="🔊", bg=BG2, fg=PRIMARY,
                                 relief="flat", cursor="hand2",
                                 command=self._toggle_sound, font=self.fn_head)
        self.snd_btn.pack(side="right", padx=4)

        tk.Label(hdr, text="Авторы: А. Свидович · А. Петляков",
                 bg=BG2, fg=FG2, font=self.fn_small).pack(side="right", padx=16)

        # основное тело
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True)

        # левая колонка: камера
        left = tk.Frame(body, bg="black", width=680)
        left.pack(side="left", fill="both", expand=True)
        left.pack_propagate(False)

        self.video_lbl = tk.Label(left, bg="black")
        self.video_lbl.pack(fill="both", expand=True)

        ctrl = tk.Frame(left, bg=BG2, height=52)
        ctrl.pack(fill="x", side="bottom")
        ctrl.pack_propagate(False)

        self.cam_var = tk.StringVar()
        self.cam_combo = ttk.Combobox(ctrl, textvariable=self.cam_var,
                                      state="readonly", width=34, font=self.fn_body)
        self.cam_combo.pack(side="left", padx=10, pady=12)
        self.cam_combo.bind("<<ComboboxSelected>>", lambda e: self._on_camera_changed())

        self.start_btn = tk.Button(ctrl, text="  ▶  Старт  ",
                                   bg=PRIMARY, fg=BG, relief="flat",
                                   font=self.fn_head, cursor="hand2",
                                   command=self._toggle_scan, padx=8, pady=4)
        self.start_btn.pack(side="left", padx=6)

        self.status_lbl = tk.Label(ctrl, text="Нажмите «Старт»", bg=BG2, fg=FG2,
                                   font=self.fn_small)
        self.status_lbl.pack(side="left", padx=8)

        # правая колонка: результаты
        right = tk.Frame(body, bg=BG, width=420)
        right.pack(side="right", fill="both")
        right.pack_propagate(False)

        # вкладки
        tab_bar = tk.Frame(right, bg=BG2)
        tab_bar.pack(fill="x")
        self._tabs = {}
        self._active_tab = tk.StringVar(value="result")
        for key, label in [("result", "Результат анализа"), ("history", "История")]:
            btn = tk.Button(tab_bar, text=label, relief="flat", cursor="hand2",
                            bg=BG2, fg=FG2, font=self.fn_body, padx=12, pady=8,
                            command=lambda k=key: self._switch_tab(k))
            btn.pack(side="left", fill="x", expand=True)
            self._tabs[key] = btn

        self.tab_frame = tk.Frame(right, bg=BG)
        self.tab_frame.pack(fill="both", expand=True)

        self._build_result_tab()
        self._build_history_tab()
        self._switch_tab("result")

        # статус-бар
        bar = tk.Frame(self, bg=BG2, height=24)
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)
        tk.Label(bar, text="ГОСТ Р 57302-2016 · ISO/IEC 15415:2011",
                 bg=BG2, fg=FG2, font=self.fn_small).pack(side="left", padx=12, pady=4)
        tk.Label(bar, text="Авторы: Александр Свидович, Алексей Петляков",
                 bg=BG2, fg=FG2, font=self.fn_small).pack(side="right", padx=12, pady=4)

    def _build_result_tab(self):
        self.result_frame = tk.Frame(self.tab_frame, bg=BG)

        # оценка
        grade_card = tk.Frame(self.result_frame, bg=BG2, padx=16, pady=12)
        grade_card.pack(fill="x", padx=10, pady=(10, 4))

        self.grade_lbl = tk.Label(grade_card, text="—", bg=BG2, fg=FG2,
                                  font=self.fn_grade)
        self.grade_lbl.pack(side="left")

        ginfo = tk.Frame(grade_card, bg=BG2)
        ginfo.pack(side="left", padx=14)
        self.grade_name_lbl = tk.Label(ginfo, text="Ожидание сканирования",
                                       bg=BG2, fg=FG2, font=self.fn_head)
        self.grade_name_lbl.pack(anchor="w")
        self.score_lbl = tk.Label(ginfo, text="Поднесите DataMatrix к камере",
                                  bg=BG2, fg=FG2, font=self.fn_small)
        self.score_lbl.pack(anchor="w")

        # шкала
        bar_f = tk.Frame(grade_card, bg=BG2)
        bar_f.pack(side="right", fill="x", expand=True)
        self.grade_bar_bg = tk.Frame(bar_f, bg=BG3, height=8)
        self.grade_bar_bg.pack(fill="x", pady=4)
        self.grade_bar_fg = tk.Frame(self.grade_bar_bg, bg=FG2, height=8)
        self.grade_bar_fg.place(relwidth=0.0, relheight=1.0)

        # параметры
        tk.Label(self.result_frame, text="  ПАРАМЕТРЫ КАЧЕСТВА (ГОСТ Р 57302-2016)",
                 bg=BG, fg=FG2, font=self.fn_small, anchor="w").pack(fill="x", padx=10, pady=(6, 2))

        params_card = tk.Frame(self.result_frame, bg=BG2)
        params_card.pack(fill="x", padx=10, pady=(0, 6))

        self.param_rows = {}
        for i, (key, name, ref) in enumerate(PARAMS_META):
            row = tk.Frame(params_card, bg=BG2 if i % 2 == 0 else BG3)
            row.pack(fill="x")

            grade_box = tk.Label(row, text="—", bg="#333", fg=FG2,
                                 font=self.fn_mono, width=3, padx=4, pady=2)
            grade_box.pack(side="left", padx=(8, 6), pady=2)

            info = tk.Frame(row, bg=row["bg"])
            info.pack(side="left", fill="x", expand=True)
            tk.Label(info, text=f"{key}  {name}", bg=row["bg"], fg=FG,
                     font=self.fn_body, anchor="w").pack(fill="x")

            bar_bg = tk.Frame(info, bg=BG3, height=4)
            bar_bg.pack(fill="x", pady=(0, 3))
            bar_fill = tk.Frame(bar_bg, bg=FG2, height=4)
            bar_fill.place(relwidth=0.0, relheight=1.0)

            pct_lbl = tk.Label(row, text="—%", bg=row["bg"], fg=FG2,
                               font=self.fn_mono, width=7, anchor="e")
            pct_lbl.pack(side="right", padx=6)

            ref_lbl = tk.Label(row, text=ref, bg=row["bg"], fg=FG2,
                               font=self.fn_small, width=7, anchor="e")
            ref_lbl.pack(side="right")

            self.param_rows[key] = {"grade_box": grade_box, "bar": bar_fill, "pct": pct_lbl}

        # декодированные данные
        tk.Label(self.result_frame, text="  ДЕКОДИРОВАННЫЕ ДАННЫЕ",
                 bg=BG, fg=FG2, font=self.fn_small, anchor="w").pack(fill="x", padx=10, pady=(4, 2))
        data_f = tk.Frame(self.result_frame, bg=BG2, padx=10, pady=8)
        data_f.pack(fill="x", padx=10)
        self.data_lbl = tk.Label(data_f, text="—", bg=BG2, fg=FG,
                                 font=self.fn_mono, wraplength=360, justify="left", anchor="w")
        self.data_lbl.pack(fill="x")

        self.time_lbl = tk.Label(self.result_frame, text="", bg=BG, fg=FG2, font=self.fn_small)
        self.time_lbl.pack(pady=4)

    def _build_history_tab(self):
        self.history_frame = tk.Frame(self.tab_frame, bg=BG)

        scroll_frame = tk.Frame(self.history_frame, bg=BG)
        scroll_frame.pack(fill="both", expand=True)

        scrollbar = ttk.Scrollbar(scroll_frame)
        scrollbar.pack(side="right", fill="y")

        self.history_canvas = tk.Canvas(scroll_frame, bg=BG, yscrollcommand=scrollbar.set,
                                        highlightthickness=0)
        self.history_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.history_canvas.yview)

        self.history_inner = tk.Frame(self.history_canvas, bg=BG)
        self.history_canvas.create_window((0, 0), window=self.history_inner, anchor="nw")
        self.history_inner.bind("<Configure>",
            lambda e: self.history_canvas.configure(
                scrollregion=self.history_canvas.bbox("all")))

        self.history_empty_lbl = tk.Label(self.history_inner, text="История пуста",
                                          bg=BG, fg=FG2, font=self.fn_body)
        self.history_empty_lbl.pack(pady=40)

    # ── вкладки ──────────────────────────────────────────────────────────────
    def _switch_tab(self, key):
        self._active_tab.set(key)
        for k, btn in self._tabs.items():
            if k == key:
                btn.config(bg=BG3, fg=PRIMARY, relief="flat")
            else:
                btn.config(bg=BG2, fg=FG2, relief="flat")
        self._show_tab(key)

    def _show_tab(self, key):
        for f in (self.result_frame, self.history_frame):
            f.pack_forget()
        if key == "result":
            self.result_frame.pack(fill="both", expand=True)
        else:
            self.history_frame.pack(fill="both", expand=True)

    # ── камера ───────────────────────────────────────────────────────────────
    def _update_camera_list(self):
        available = []
        for i in range(8):
            cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
            if cap.isOpened():
                ret, _ = cap.read()
                if ret:
                    available.append(i)
                cap.release()
        if available:
            labels = [f"Камера {i}" for i in available]
            self.cam_combo["values"] = labels
            self.cam_combo.current(len(available) - 1)
            self.camera_id = available[-1]
        else:
            self.cam_combo["values"] = ["Нет камер"]
            self.cam_combo.current(0)

    def _on_camera_changed(self):
        idx = self.cam_combo.current()
        vals = self.cam_combo["values"]
        if vals and vals[0] != "Нет камер":
            try:
                self.camera_id = int(vals[idx].split()[-1])
            except Exception:
                pass
        if self.running:
            self._stop_camera()
            self._start_camera()

    def _toggle_scan(self):
        if self.running:
            self._stop_camera()
            self.start_btn.config(text="  ▶  Старт  ", bg=PRIMARY, fg=BG)
            self.status_lbl.config(text="Остановлено")
        else:
            self._start_camera()
            if self.running:
                self.start_btn.config(text="  ⏹  Стоп  ", bg=GRADE_F, fg="white")
                self.status_lbl.config(text="Сканирование...")

    def _start_camera(self):
        try:
            cap = cv2.VideoCapture(self.camera_id, cv2.CAP_DSHOW)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH,  1920)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
            cap.set(cv2.CAP_PROP_FPS,          60)
            cap.set(cv2.CAP_PROP_AUTOFOCUS,    1)
            cap.set(cv2.CAP_PROP_BUFFERSIZE,   1)
            if not cap.isOpened():
                self.status_lbl.config(text="Ошибка открытия камеры")
                return
            self.cap = cap
            self.running = True
            t = threading.Thread(target=self._capture_loop, daemon=True)
            t.start()
        except Exception as e:
            self.status_lbl.config(text=f"Ошибка: {e}")

    def _stop_camera(self):
        self.running = False
        time.sleep(0.15)
        if self.cap:
            self.cap.release()
            self.cap = None

    def _capture_loop(self):
        fps_counter = 0
        fps_time = time.time()
        while self.running and self.cap:
            ret, frame = self.cap.read()
            if not ret:
                time.sleep(0.01)
                continue
            fps_counter += 1
            now = time.time()
            if now - fps_time >= 1.0:
                self.fps_lbl.config(text=f"{fps_counter} fps")
                fps_counter = 0
                fps_time = now

            try:
                self.frame_queue.put_nowait(frame.copy())
            except queue.Full:
                try:
                    self.frame_queue.get_nowait()
                    self.frame_queue.put_nowait(frame.copy())
                except Exception:
                    pass

    # ── обработка кадров ─────────────────────────────────────────────────────
    def _poll_frame(self):
        try:
            frame = self.frame_queue.get_nowait()
            self._process_frame(frame)
        except queue.Empty:
            pass
        self.after(16, self._poll_frame)

    def _process_frame(self, frame: np.ndarray):
        h, w = frame.shape[:2]

        # Отрисовка прицела
        display = frame.copy()
        m = 0.15
        x1, y1 = int(w * m), int(h * m)
        x2, y2 = int(w * (1 - m)), int(h * (1 - m))
        clr = (0, 180, 216)
        corner = 28
        thick = 2
        for (sx, sy, dx, dy) in [(x1, y1, 1, 1), (x2, y1, -1, 1),
                                  (x1, y2, 1, -1), (x2, y2, -1, -1)]:
            cv2.line(display, (sx, sy), (sx + dx * corner, sy), clr, thick)
            cv2.line(display, (sx, sy), (sx, sy + dy * corner), clr, thick)
        cv2.line(display, (0, h // 2), (w, h // 2), (0, 180, 216, 30), 1)

        # Показ в GUI
        rgb    = cv2.cvtColor(display, cv2.COLOR_BGR2RGB)
        canvas_w = max(1, self.video_lbl.winfo_width())
        canvas_h = max(1, self.video_lbl.winfo_height())
        scale  = min(canvas_w / w, canvas_h / h)
        nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
        rgb    = cv2.resize(rgb, (nw, nh), interpolation=cv2.INTER_LINEAR)
        img    = Image.fromarray(rgb)
        imgtk  = ImageTk.PhotoImage(image=img)
        self.video_lbl.imgtk = imgtk
        self.video_lbl.config(image=imgtk)

        if not DMTX_AVAILABLE:
            return

        # Попытка декодировать DataMatrix из центральной зоны
        roi = frame[y1:y2, x1:x2]
        try:
            decoded_list = dmtx_decode(Image.fromarray(
                cv2.cvtColor(roi, cv2.COLOR_BGR2RGB)))
        except Exception:
            return

        if not decoded_list:
            return

        text = decoded_list[0].data.decode("utf-8", errors="replace")
        now  = time.time()
        if text == self._last_decoded and now - self._last_decoded_time < 2.0:
            return
        self._last_decoded      = text
        self._last_decoded_time = now

        t0  = time.perf_counter()
        res = analyze_frame(roi)
        ms  = (time.perf_counter() - t0) * 1000

        if self.sound_on:
            play_sound(res["overall"])

        self._update_result(text, res, ms)
        self._add_history(text, res)

    # ── обновление интерфейса ────────────────────────────────────────────────
    def _update_result(self, text: str, res: dict, ms: float):
        grade  = res["overall"]
        score  = res["score"]
        color  = GRADE_COLORS[grade]
        pct    = score / 4.0

        self.grade_lbl.config(text=grade, fg=color)
        self.grade_name_lbl.config(text=GRADE_LABELS[grade], fg=color)
        self.score_lbl.config(
            text=f"Итоговый балл: {score:.2f} / 4.0   (анализ: {ms:.0f} мс)")
        self.grade_bar_fg.place(relwidth=pct, relheight=1.0)
        self.grade_bar_fg.config(bg=color)

        for key, meta in res["params"].items():
            row = self.param_rows[key]
            g   = meta["grade"]
            v   = meta["value"]
            c   = GRADE_COLORS[g]
            row["grade_box"].config(text=g, bg=c + "33", fg=c)
            row["bar"].config(bg=c)
            row["bar"].place(relwidth=v, relheight=1.0)
            row["pct"].config(text=f"{v*100:.1f}%")

        self.data_lbl.config(text=text)
        self.time_lbl.config(text=datetime.now().strftime("%H:%M:%S"))

    def _add_history(self, text: str, res: dict):
        self.history.insert(0, {"text": text, "res": res, "ts": datetime.now()})
        self.history = self.history[:50]
        self.history_empty_lbl.pack_forget()

        for w in self.history_inner.winfo_children():
            w.destroy()

        for rec in self.history:
            grade = rec["res"]["overall"]
            color = GRADE_COLORS[grade]
            row   = tk.Frame(self.history_inner, bg=BG2)
            row.pack(fill="x", padx=4, pady=1)

            tk.Label(row, text=grade, bg=color + "22", fg=color,
                     font=self.fn_head, width=4, pady=6).pack(side="left")
            info = tk.Frame(row, bg=BG2)
            info.pack(side="left", fill="x", expand=True, padx=8)
            tk.Label(info, text=rec["text"][:48], bg=BG2, fg=FG,
                     font=self.fn_mono, anchor="w").pack(fill="x")
            tk.Label(info, text=rec["ts"].strftime("%H:%M:%S") +
                     f"  ·  балл {rec['res']['score']:.2f}",
                     bg=BG2, fg=FG2, font=self.fn_small, anchor="w").pack(fill="x")

        # Обновить счётчик вкладки
        self._tabs["history"].config(text=f"История ({len(self.history)})")

    def _toggle_sound(self):
        self.sound_on = not self.sound_on
        self.snd_btn.config(fg=PRIMARY if self.sound_on else FG2,
                            text="🔊" if self.sound_on else "🔇")

    def on_close(self):
        self._stop_camera()
        self.destroy()


# ─── Запуск ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = App()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()
