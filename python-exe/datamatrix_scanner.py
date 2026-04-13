"""
DataMatrix Quality Scanner
ГОСТ Р 57302-2016 / ISO/IEC 15415
Авторы: Александр Свидович, Алексей Петляков
"""

import sys
import os
import threading
import time
import queue
from datetime import datetime

import tkinter as tk
from tkinter import ttk, font as tkfont

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
    return {"A": 4.0, "B": 3.0, "C": 2.0, "D": 1.0, "F": 0.0}[g]


def worst_grade(grades) -> str:
    s = min(grade_to_score(g) for g in grades)
    if s >= 3.5: return "A"
    if s >= 2.5: return "B"
    if s >= 1.5: return "C"
    if s >= 0.5: return "D"
    return "F"


def analyze_frame(frame: np.ndarray) -> dict:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
    h, w = gray.shape
    total = h * w

    Rmax = float(gray.max())
    Rmin = float(gray.min())
    rng  = Rmax - Rmin if Rmax != Rmin else 1.0
    thr  = (Rmax + Rmin) / 2.0

    sc = (Rmax - Rmin) / Rmax if Rmax > 0 else 0.0

    dark  = gray[gray <  thr]
    light = gray[gray >= thr]
    dm    = float(dark.mean())   if len(dark)  > 0 else 0.0
    lm    = float(light.mean())  if len(light) > 0 else 255.0
    ds    = float(dark.std())    if len(dark)  > 1 else 0.0
    ls    = float(light.std())   if len(light) > 1 else 0.0
    mod   = max(0.0, 1.0 - (ds + ls) / rng)

    rm = min(
        (lm - thr) / max(lm - Rmin, 1),
        (thr - dm) / max(Rmax - dm,  1),
    )

    edges = 0
    for row in range(min(4, h)):
        line = (gray[row] < thr).astype(np.uint8)
        edges += int(np.sum(np.abs(np.diff(line))))
    fpd = min(1.0, edges / max((w + h), 1))

    row_d = np.array([(gray[y] < thr).mean() for y in range(h)])
    col_d = np.array([(gray[:, x] < thr).mean() for x in range(w)])
    anu   = max(0.0, 1.0 - float(np.sqrt((row_d.var() + col_d.var()) / 2.0)))

    bs = max(4, min(h, w) // 8)
    bm = [float(gray[by:by+bs, bx:bx+bs].mean())
          for by in range(0, h - bs + 1, bs)
          for bx in range(0, w - bs + 1, bs)]
    gnu = max(0.0, 1.0 - float(np.std(bm)) / 255.0) if len(bm) > 1 else 1.0

    uec = min(1.0, sc * mod)
    pg  = max(0.0, 1.0 - min(1.0, abs(len(dark) / total - 0.5) * 4.0))

    raw = {"SC": sc, "MOD": mod, "RM": rm, "FPD": fpd,
           "ANU": anu, "GNU": gnu, "UEC": uec, "PG": pg}

    params = {k: {"value": max(0.0, min(1.0, float(v))),
                  "grade": value_to_grade(max(0.0, min(1.0, float(v))), k)}
              for k, v in raw.items()}

    grades  = [p["grade"] for p in params.values()]
    avg     = sum(grade_to_score(g) for g in grades) / len(grades)
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

        # ── Состояние ────────────────────────────────────────────────────────
        self.cap               = None
        self.camera_id         = 0
        self.running           = False
        self.sound_on          = True
        self.history           = []
        self._last_decoded     = ""
        self._last_decoded_t   = 0.0
        self._decode_interval  = 0.25     # минимальный интервал между попытками декодирования

        # Три независимые очереди:
        #   display_q  — кадры для отображения (главный поток)
        #   decode_q   — кадры для декодирования (фоновый поток)
        #   result_q   — результаты декодирования (главный поток)
        self.display_q = queue.Queue(maxsize=1)
        self.decode_q  = queue.Queue(maxsize=1)
        self.result_q  = queue.Queue(maxsize=4)

        self._fps_count = 0
        self._fps_t     = time.time()

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

        # Левая: видео
        left = tk.Frame(body, bg="black", width=680)
        left.pack(side="left", fill="both", expand=True)
        left.pack_propagate(False)

        self.video_lbl = tk.Label(left, bg="black")
        self.video_lbl.pack(fill="both", expand=True)

        ctrl = tk.Frame(left, bg=BG2, height=52)
        ctrl.pack(fill="x", side="bottom")
        ctrl.pack_propagate(False)

        self.cam_var   = tk.StringVar()
        self.cam_combo = ttk.Combobox(ctrl, textvariable=self.cam_var,
                                      state="readonly", width=34, font=self.fn_body)
        self.cam_combo.pack(side="left", padx=10, pady=12)
        self.cam_combo.bind("<<ComboboxSelected>>", lambda _: self._on_camera_changed())

        self.start_btn = tk.Button(ctrl, text="  ▶  Старт  ",
                                   bg=PRIMARY, fg=BG, relief="flat",
                                   font=self.fn_head, cursor="hand2",
                                   command=self._toggle_scan, padx=8, pady=4)
        self.start_btn.pack(side="left", padx=6)

        self.status_lbl = tk.Label(ctrl, text="Инициализация...",
                                   bg=BG2, fg=FG2, font=self.fn_small)
        self.status_lbl.pack(side="left", padx=8)

        # Правая: результаты
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

            grade_box = tk.Label(row, text="—", bg="#2a2a2a", fg=FG2,
                                 font=self.fn_mono, width=3, padx=4, pady=3)
            grade_box.pack(side="left", padx=(8, 6), pady=2)

            pct_lbl = tk.Label(row, text="  —%  ", bg=row_bg, fg=FG2,
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

    # ── Вкладки ────────────────────────────────────────────────────────────────
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

    # ── Камера ─────────────────────────────────────────────────────────────────
    def _init_cameras(self):
        available = []
        for i in range(8):
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
            self.cam_combo["values"] = [f"Камера {i}" for i in available]
            self.cam_combo.current(len(available) - 1)
            self.camera_id = available[-1]
            self.status_lbl.config(text="Нажмите «Старт»")
        else:
            self.cam_combo["values"] = ["Камеры не найдены"]
            self.cam_combo.current(0)
            self.status_lbl.config(text="Камера не найдена")

    def _on_camera_changed(self):
        vals = list(self.cam_combo["values"])
        if not vals or vals[0] == "Камеры не найдены":
            return
        try:
            self.camera_id = int(vals[self.cam_combo.current()].split()[-1])
        except Exception:
            return
        if self.running:
            self._stop_camera()
            self._start_camera()

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
        try:
            cap = cv2.VideoCapture(self.camera_id, cv2.CAP_DSHOW)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH,  1920)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
            cap.set(cv2.CAP_PROP_FPS,          60)
            cap.set(cv2.CAP_PROP_AUTOFOCUS,    1)
            cap.set(cv2.CAP_PROP_BUFFERSIZE,   1)
            if not cap.isOpened():
                self.status_lbl.config(text="Ошибка: камера не открывается")
                return
            self.cap     = cap
            self.running = True
            threading.Thread(target=self._capture_loop, daemon=True).start()
            if DMTX_AVAILABLE:
                threading.Thread(target=self._decode_loop, daemon=True).start()
        except Exception as e:
            self.status_lbl.config(text=f"Ошибка: {e}")

    def _stop_camera(self):
        self.running = False
        time.sleep(0.25)
        if self.cap:
            self.cap.release()
            self.cap = None
        self.video_lbl.config(image="")

    # ── Поток захвата ──────────────────────────────────────────────────────────
    # Только читает кадры и раскладывает по очередям — никакой обработки
    def _capture_loop(self):
        fps_count = 0
        fps_t     = time.time()

        while self.running and self.cap:
            ret, frame = self.cap.read()
            if not ret:
                time.sleep(0.005)
                continue

            fps_count += 1
            now = time.time()
            if now - fps_t >= 1.0:
                v = fps_count
                self.after(0, lambda v=v: self.fps_lbl.config(text=f"{v} fps"))
                fps_count = 0
                fps_t     = now

            # Очередь отображения: только самый свежий кадр
            try:
                self.display_q.put_nowait(frame)
            except queue.Full:
                try:
                    self.display_q.get_nowait()
                    self.display_q.put_nowait(frame)
                except Exception:
                    pass

            # Очередь декодирования: кладём только если декодер не занят
            try:
                self.decode_q.put_nowait(frame)
            except queue.Full:
                pass   # декодер занят — пропускаем кадр, не ждём

    # ── Поток декодирования ────────────────────────────────────────────────────
    # Полностью изолирован от UI; результат кладёт в result_q
    def _decode_loop(self):
        while self.running:
            try:
                frame = self.decode_q.get(timeout=0.5)
            except queue.Empty:
                continue

            # Минимальный интервал между попытками
            now = time.time()
            if now - self._last_decoded_t < self._decode_interval:
                continue

            h, w = frame.shape[:2]
            m  = 0.15
            x1 = int(w * m);      y1 = int(h * m)
            x2 = int(w * (1-m));  y2 = int(h * (1-m))
            roi = frame[y1:y2, x1:x2]

            try:
                decoded_list = dmtx_decode(
                    Image.fromarray(cv2.cvtColor(roi, cv2.COLOR_BGR2RGB)))
            except Exception:
                continue

            if not decoded_list:
                continue

            text = decoded_list[0].data.decode("utf-8", errors="replace")
            if text == self._last_decoded and now - self._last_decoded_t < 2.0:
                continue

            self._last_decoded   = text
            self._last_decoded_t = now

            t0  = time.perf_counter()
            res = analyze_frame(roi)
            ms  = (time.perf_counter() - t0) * 1000.0

            if self.sound_on:
                play_sound(res["overall"])

            # Передаём результат в главный поток
            try:
                self.result_q.put_nowait({"text": text, "res": res, "ms": ms})
            except queue.Full:
                pass

    # ── Главный поток: отображение видео ──────────────────────────────────────
    def _poll_display(self):
        try:
            frame = self.display_q.get_nowait()
            self._render_frame(frame)
        except queue.Empty:
            pass
        self.after(16, self._poll_display)   # ~60 fps

    def _render_frame(self, frame: np.ndarray):
        h, w = frame.shape[:2]
        m  = 0.15
        x1 = int(w * m);      y1 = int(h * m)
        x2 = int(w * (1-m));  y2 = int(h * (1-m))
        clr = (0, 180, 216)
        c   = 28

        display = frame.copy()
        for sx, sy, dx, dy in [(x1,y1,1,1),(x2,y1,-1,1),(x1,y2,1,-1),(x2,y2,-1,-1)]:
            cv2.line(display, (sx, sy), (sx + dx*c, sy), clr, 2)
            cv2.line(display, (sx, sy), (sx, sy + dy*c), clr, 2)
        cv2.line(display, (0, h//2), (w, h//2), clr, 1)

        cw = max(1, self.video_lbl.winfo_width())
        ch = max(1, self.video_lbl.winfo_height())
        sc = min(cw / w, ch / h)
        nw = max(1, int(w * sc))
        nh = max(1, int(h * sc))

        # Быстрое масштабирование для отображения
        small = cv2.resize(display, (nw, nh), interpolation=cv2.INTER_LINEAR)
        rgb   = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
        img   = Image.fromarray(rgb)
        imgtk = ImageTk.PhotoImage(image=img)
        self.video_lbl.imgtk = imgtk
        self.video_lbl.config(image=imgtk)

    # ── Главный поток: обновление результатов ─────────────────────────────────
    def _poll_results(self):
        try:
            item = self.result_q.get_nowait()
            self._update_result(item["text"], item["res"], item["ms"])
            self._add_history(item["text"], item["res"])
        except queue.Empty:
            pass
        self.after(50, self._poll_results)

    # ── Обновление UI результатов ──────────────────────────────────────────────
    def _update_result(self, text: str, res: dict, ms: float):
        grade = res["overall"]
        score = res["score"]
        color = GRADE_COLORS[grade]

        self.grade_lbl.config(text=grade, fg=color)
        self.grade_name_lbl.config(text=GRADE_LABELS[grade], fg=color)
        self.score_lbl.config(
            text=f"Итоговый балл: {score:.2f} / 4.0   (анализ: {ms:.0f} мс)")
        self.grade_bar_fg.place(relwidth=score / 4.0, relheight=1.0)
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
        if len(self.history) > 50:
            self.history = self.history[:50]

        for w in self.hist_inner.winfo_children():
            w.destroy()

        for rec in self.history:
            grade = rec["res"]["overall"]
            color = GRADE_COLORS[grade]
            row   = tk.Frame(self.hist_inner, bg=BG2)
            row.pack(fill="x", padx=4, pady=1)

            tk.Label(row, text=grade, bg=color + "22", fg=color,
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
