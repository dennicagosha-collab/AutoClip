# -*- coding: utf-8 -*-
"""AutoClip — окно: перетащи запись стрима, нажми «Нарезать»."""

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ["PATH"] = HERE + os.pathsep + os.environ.get("PATH", "")

import autoclip  # noqa: E402

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except Exception:
    HAS_DND = False

SETTINGS = os.path.join(HERE, "настройки.json")
QUALITY = {"Максимальное": 14, "Высокое": 16, "Файлы полегче": 19}
WEBCAM = {"Вебка сверху": 0.30, "Вебка снизу": 0.70, "По центру": 0.50}
VIDEO_TYPES = [("Видео", "*.mp4 *.mkv *.mov *.flv *.ts *.webm"), ("Все файлы", "*.*")]

BG, PANEL, FG, MUTED, ACCENT = "#15161a", "#202229", "#eceef2", "#8b8f9a", "#ff4f6d"


class Stream:
    """Перехват print/ошибок библиотек в окно (у pythonw нет консоли)."""
    def __init__(self, q):
        self.q = q

    def write(self, s):
        if s.strip():
            self.q.put(s.rstrip())

    def flush(self):
        pass


class App:
    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        self.files = []
        self.last_out = None
        self.busy = False

        root.title("AutoClip — нарезка стримов")
        root.configure(bg=BG)
        root.geometry("640x760")
        root.minsize(560, 640)

        st = ttk.Style()
        st.theme_use("clam")
        st.configure(".", background=BG, foreground=FG, fieldbackground=PANEL,
                     font=("Segoe UI", 10))
        st.configure("TCheckbutton", background=PANEL, foreground=FG)
        st.map("TCheckbutton", background=[("active", PANEL)])
        st.configure("TLabel", background=PANEL, foreground=FG)
        st.configure("TCombobox", fieldbackground=PANEL, background=PANEL, foreground=FG,
                     arrowcolor=FG)
        st.map("TCombobox",
               fieldbackground=[("readonly", "#2c2f38")],
               foreground=[("readonly", FG)],
               selectbackground=[("readonly", "#2c2f38")],
               selectforeground=[("readonly", FG)])
        root.option_add("*TCombobox*Listbox.background", PANEL)
        root.option_add("*TCombobox*Listbox.foreground", FG)
        root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        root.option_add("*TCombobox*Listbox.font", ("Segoe UI", 10))
        st.configure("TSpinbox", fieldbackground=PANEL, foreground=FG, arrowcolor=FG)
        st.configure("Horizontal.TProgressbar", troughcolor=PANEL, background=ACCENT,
                     bordercolor=PANEL, lightcolor=ACCENT, darkcolor=ACCENT)

        left = root

        # --- зона для видео ---
        self.drop = tk.Label(
            left, bg=PANEL, fg=FG, font=("Segoe UI", 13, "bold"), cursor="hand2",
            text=("Перетащи сюда запись стрима\nили нажми, чтобы выбрать" if HAS_DND
                  else "Нажми, чтобы выбрать запись стрима"),
            height=5, relief="flat", highlightthickness=2, highlightbackground="#3a3d48")
        self.drop.pack(fill="x", padx=16, pady=(16, 8))
        self.drop.bind("<Button-1>", lambda e: self.pick_files())
        if HAS_DND:
            self.drop.drop_target_register(DND_FILES)
            self.drop.dnd_bind("<<Drop>>", self.on_drop)

        # --- настройки ---
        box = tk.Frame(left, bg=PANEL)
        box.pack(fill="x", padx=16, pady=8)
        s = self.load_settings()

        def row(r, text):
            ttk.Label(box, text=text).grid(row=r, column=0, sticky="w", padx=12, pady=6)

        row(0, "Сколько клипов")
        self.v_clips = tk.IntVar(value=s.get("clips", 10))
        ttk.Spinbox(box, from_=1, to=50, width=6, textvariable=self.v_clips).grid(
            row=0, column=1, sticky="w", pady=6)

        self.v_subs = tk.BooleanVar(value=s.get("subs", True))
        ttk.Checkbutton(box, text="Субтитры", variable=self.v_subs).grid(
            row=1, column=0, sticky="w", padx=12, pady=6)
        self.v_zoom = tk.BooleanVar(value=s.get("zoom", True))
        ttk.Checkbutton(box, text="Зум на эмоциях", variable=self.v_zoom).grid(
            row=1, column=1, sticky="w", pady=6)

        self.v_bleep = tk.BooleanVar(value=s.get("bleep", True))
        ttk.Checkbutton(box, text="Закрывать мат звуком", variable=self.v_bleep).grid(
            row=2, column=0, sticky="w", padx=12, pady=6)
        snd_row = tk.Frame(box, bg=PANEL)
        snd_row.grid(row=2, column=1, sticky="w", pady=6)
        self.v_sound = tk.StringVar(value=s.get("sound", "перелистывание"))
        self.cb_sound = ttk.Combobox(snd_row, textvariable=self.v_sound, width=18,
                                     state="readonly")
        self.cb_sound.pack(side="left")
        tk.Button(snd_row, text="▶", command=self.play_sound, bg=PANEL, fg=FG, bd=0,
                  activebackground="#2c2f38", activeforeground=FG,
                  font=("Segoe UI", 11), cursor="hand2").pack(side="left", padx=6)
        tk.Button(snd_row, text="свои звуки…", command=self.open_sounds, bg=PANEL, fg=MUTED,
                  bd=0, activebackground="#2c2f38", activeforeground=FG,
                  cursor="hand2").pack(side="left")

        row(3, "Раскладка записи")
        self.v_cam = tk.StringVar(value=s.get("cam", "Вебка сверху"))
        ttk.Combobox(box, textvariable=self.v_cam, values=list(WEBCAM), width=18,
                     state="readonly").grid(row=3, column=1, sticky="w", pady=6)

        row(4, "Качество")
        self.v_q = tk.StringVar(value=s.get("quality", "Высокое"))
        ttk.Combobox(box, textvariable=self.v_q, values=list(QUALITY), width=18,
                     state="readonly").grid(row=4, column=1, sticky="w", pady=(6, 12))

        # --- кнопки ---
        self.btn = tk.Button(left, text="✂  Нарезать", command=self.start, bg=ACCENT,
                             fg="white", bd=0, font=("Segoe UI", 13, "bold"),
                             activebackground="#e23e5b", activeforeground="white",
                             cursor="hand2", height=2)
        self.btn.pack(fill="x", padx=16, pady=(8, 6))
        self.prog = ttk.Progressbar(left, mode="determinate", value=0)
        self.prog.pack(fill="x", padx=16)

        # --- лог ---
        self.logbox = tk.Text(left, bg=PANEL, fg=FG, bd=0, wrap="word", height=12,
                              font=("Consolas", 9), insertbackground=FG, padx=10, pady=8)
        self.logbox.pack(fill="both", expand=True, padx=16, pady=8)
        self.logbox.configure(state="disabled")

        self.btn_open = tk.Button(left, text="📂  Открыть папку с клипами",
                                  command=self.open_out, bg=PANEL, fg=FG, bd=0,
                                  activebackground="#2c2f38", activeforeground=FG,
                                  font=("Segoe UI", 11), cursor="hand2", state="disabled",
                                  height=2)
        self.btn_open.pack(fill="x", padx=16, pady=(0, 16))

        autoclip.log = lambda m: self.q.put(str(m))
        sys.stdout = Stream(self.q)
        sys.stderr = Stream(self.q)

        self.ffmpeg_ok = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
        if self.ffmpeg_ok:
            autoclip.prepare_sounds()
        else:
            self.write("❌ Не найден ffmpeg. Положи ffmpeg.exe и ffprobe.exe в папку:\n   " + HERE)
        self.refresh_sounds()
        if not HAS_DND:
            self.write("ℹ️  Перетаскивание не работает — запусти install.bat ещё раз.")
        self.write("Выбери запись и нажми «Нарезать».")
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.pump()

    # ---------- служебное ----------
    def write(self, msg):
        self.logbox.configure(state="normal")
        self.logbox.insert("end", msg + "\n")
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    def pump(self):
        try:
            while True:
                m = self.q.get_nowait()
                if isinstance(m, tuple) and m[0] == "__done__":
                    self.finish(m[1])
                else:
                    self.write(m)
        except queue.Empty:
            pass
        self.root.after(100, self.pump)

    def load_settings(self):
        try:
            with open(SETTINGS, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def save_settings(self):
        data = {"clips": self.v_clips.get(), "subs": self.v_subs.get(),
                "zoom": self.v_zoom.get(), "bleep": self.v_bleep.get(),
                "sound": self.v_sound.get(), "cam": self.v_cam.get(),
                "quality": self.v_q.get()}
        try:
            with open(SETTINGS, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
        except Exception:
            pass

    def refresh_sounds(self):
        names = autoclip.list_sounds()
        self.cb_sound.configure(values=names)
        if self.v_sound.get() not in names:
            self.v_sound.set(names[0])

    def set_files(self, paths):
        paths = [p for p in paths if os.path.isfile(p)]
        if not paths:
            return
        self.files = paths
        names = "\n".join(os.path.basename(p) for p in paths[:4])
        if len(paths) > 4:
            names += f"\n…и ещё {len(paths) - 4}"
        self.drop.configure(text="🎬 " + names, fg=ACCENT)

    def on_drop(self, e):
        self.set_files(self.root.tk.splitlist(e.data))

    def pick_files(self):
        if not self.busy:
            self.set_files(filedialog.askopenfilenames(title="Запись стрима",
                                                       filetypes=VIDEO_TYPES))

    def play_sound(self):
        self.refresh_sounds()
        path = autoclip.sound_path(self.v_sound.get())
        if not path:
            return
        if os.name == "nt":
            if path.lower().endswith(".wav"):
                import winsound
                winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
            else:
                os.startfile(path)

    def open_path(self, path):
        if os.name == "nt":
            os.startfile(path)
        else:
            subprocess.Popen(["xdg-open", path])

    def open_sounds(self):
        os.makedirs(autoclip.SOUNDS_DIR, exist_ok=True)
        self.write("ℹ️  Кинь в открывшуюся папку свой звук (mp3/wav) — он появится в списке.")
        self.open_path(autoclip.SOUNDS_DIR)

    def open_out(self):
        if self.last_out and os.path.isdir(self.last_out):
            self.open_path(self.last_out)

    # ---------- запуск ----------
    def start(self):
        if self.busy:
            return
        if not self.ffmpeg_ok:
            messagebox.showerror("AutoClip", "Не найден ffmpeg — смотри сообщение внизу.")
            return
        if not self.files:
            self.pick_files()
            if not self.files:
                return
        c = autoclip.CONFIG
        try:
            c["clips"] = max(1, int(self.v_clips.get()))
        except (tk.TclError, ValueError):
            c["clips"] = 10
        c["subs"] = self.v_subs.get()
        c["zoom"] = self.v_zoom.get()
        c["bleep"] = self.v_bleep.get()
        c["bleep_sound"] = self.v_sound.get()
        c["zoom_focus_y"] = WEBCAM.get(self.v_cam.get(), 0.3)
        c["quality"] = QUALITY.get(self.v_q.get(), 16)
        self.save_settings()

        self.busy = True
        self.btn.configure(text="Работаю…", state="disabled", bg="#5a3340")
        self.btn_open.configure(state="disabled")
        self.prog.configure(mode="indeterminate")
        self.prog.start(12)
        threading.Thread(target=self.worker, args=(list(self.files),), daemon=True).start()

    def worker(self, files):
        out = None
        for i, f in enumerate(files, 1):
            if len(files) > 1:
                self.q.put(f"\n===== {i}/{len(files)}: {os.path.basename(f)} =====")
            try:
                out = autoclip.process(f) or out
            except SystemExit:
                self.q.put("⛔ Остановлено из-за ошибки выше.")
            except Exception:
                self.q.put("❌ Неожиданная ошибка:\n" + traceback.format_exc()[-1500:])
        self.q.put(("__done__", out))

    def finish(self, out):
        self.busy = False
        self.prog.stop()
        self.prog.configure(mode="determinate", value=0)
        self.btn.configure(text="✂  Нарезать", state="normal", bg=ACCENT)
        if out:
            self.last_out = out
            self.btn_open.configure(state="normal")

    def close(self):
        if self.busy and not messagebox.askyesno(
                "AutoClip", "Нарезка ещё идёт. Точно закрыть?"):
            return
        self.root.destroy()


def main():
    root = TkinterDnD.Tk() if HAS_DND else tk.Tk()
    try:
        App(root)
    except Exception:
        messagebox.showerror("AutoClip", traceback.format_exc()[-1500:])
        raise
    root.mainloop()


if __name__ == "__main__":
    main()
