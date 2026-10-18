"""
Desktop GUI (Tkinter) for AI Agent Router — the default when the EXE is opened
without arguments (double-click).

* starts/stops the same FastAPI + MCP server in a background *thread* (uvicorn.Server)
* first run: generates a strong ROUTER_API_KEYS key and saves it to the .env next to the EXE
* lets the user paste XAI_API_KEY / edit the router key / change the port (written to .env)
* shows each agent with a status light and a short Thai note
* live, human-friendly log of routing activity (logging.Handler -> queue -> Tk after())
* "คู่มือ / วิธีเชื่อมต่อ" tab with copy-paste MCP config for OpenCode and Cursor

Only stdlib (tkinter) — nothing extra to install.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any, Callable


class GuiUnavailable(ImportError):
    """Raised when a GUI cannot be shown (no tkinter / no display). main.py falls back to headless."""


try:
    import tkinter as tk
    from tkinter import messagebox, scrolledtext, ttk
    from tkinter import font as tkfont
except Exception as _exc:  # pragma: no cover - depends on the Python build
    raise GuiUnavailable(f"tkinter is not available: {_exc}") from _exc

from config import (APP_NAME, APP_VERSION, Settings, app_base_dir, env_file_path, generate_api_key,
                    load_env_files, load_settings, parse_api_keys, setup_logging, update_env_file)
from router_core import Router

log = logging.getLogger("router.gui")

# ---------------------------------------------------------------- look & feel
GREEN, GREY, RED, ORANGE, BLUE = "#1e9e48", "#9aa0a6", "#d93025", "#e37400", "#1a73e8"
FONT_CANDIDATES = ("Leelawadee UI", "Leelawadee", "Tahoma", "Segoe UI", "Noto Sans Thai",
                   "Noto Sans Thai UI", "Loma", "Garuda", "Sawasdee", "DejaVu Sans")
MONO_CANDIDATES = ("Consolas", "Cascadia Mono", "Noto Sans Mono", "DejaVu Sans Mono", "Courier New")

AGENT_NOTES = {
    "grok": "ต้องใส่ XAI_API_KEY (ช่อง \"กุญแจ xAI\" ด้านซ้าย) แล้วกดบันทึก",
    "cursor": "ส่งงานให้ Cursor: ต้องตั้ง webhook (ขั้นสูง) • ส่วน Cursor เรียกโปรแกรมนี้ผ่าน MCP ได้เลย",
    "opencode": "ส่งงานให้ OpenCode: ต้องเปิด opencode serve (ขั้นสูง) • ส่วน OpenCode เรียกโปรแกรมนี้ผ่าน MCP ได้เลย",
    "http": "ส่งงานต่อไปยัง URL ที่ตั้งไว้ใน config.yaml",
}
TRANSPORT_TH = {"http": "REST API", "mcp-http": "MCP", "mcp-stdio": "MCP (stdio)"}
ERROR_TH = {
    400: "คำขอไม่ถูกต้อง (เช่น ส่งงานหาตัวเอง)",
    401: "กุญแจไม่ถูกต้อง",
    403: "กุญแจนี้ใช้แทน agent ตัวนั้นไม่ได้",
    404: "ไม่มี agent ชื่อนี้",
    413: "ข้อความยาวเกินไป",
    502: "ปลายทางตอบผิดพลาด หรือติดต่อไม่ได้",
    503: "ยังไม่ได้ตั้งค่า หรือถูกปิดอยู่",
    504: "ปลายทางตอบช้าเกินกำหนด",
}


# ---------------------------------------------------------------- helpers
def hide_own_console() -> None:
    """Windows: hide the console window if *we* own it (double-click), never the user's terminal.

    build.bat already uses PyInstaller `--hide-console hide-early`; this is a fallback for
    `python main.py` opened from Explorer or builds made without that flag.
    """
    if os.name != "nt":
        return
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        hwnd = k32.GetConsoleWindow()
        if not hwnd:
            return
        procs = (ctypes.c_uint * 16)()
        count = k32.GetConsoleProcessList(procs, 16)
        # onefile EXE = bootloader + child share the console (2). python.exe alone = 1.
        own_limit = 2 if getattr(sys, "frozen", False) else 1
        if 0 < count <= own_limit:
            ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE
    except Exception:
        pass


def enable_dpi_awareness() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()  # type: ignore[name-defined]
        except Exception:
            pass


def port_is_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if os.name != "nt":  # same as uvicorn: ignore sockets left in TIME_WAIT by a previous run
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host if host not in ("0.0.0.0", "") else "0.0.0.0", port))
            return True
        except OSError:
            return False


def env_router_keys() -> dict[str, str | None]:
    return parse_api_keys(os.environ.get("ROUTER_API_KEYS", ""))


def format_env_keys(keys: dict[str, str | None]) -> str:
    return ",".join(f"{k}:{a}" if a else k for k, a in keys.items())


def ensure_router_key(config_path: str | None) -> tuple[str, bool, str | None]:
    """Return (main_key, generated_now, warning). Generates + saves a key on first run."""
    load_env_files()
    keys = env_router_keys()
    if keys:
        return next(iter(keys)), False, None
    try:
        cfg_keys = load_settings(config_path).api_keys
    except Exception:
        cfg_keys = {}
    if cfg_keys:
        return next(iter(cfg_keys)), False, None
    key = generate_api_key()
    try:
        update_env_file({"ROUTER_API_KEYS": key})
        return key, True, None
    except OSError as exc:
        os.environ["ROUTER_API_KEYS"] = key  # still works for this session
        return key, True, f"บันทึกไฟล์ .env ไม่ได้ ({exc}) — กุญแจจะใช้ได้เฉพาะรอบนี้"


# ---------------------------------------------------------------- logging bridge
class QueueLogHandler(logging.Handler):
    """Thread-safe: only puts records into a queue; the Tk thread drains it with after()."""

    def __init__(self, q: "queue.Queue[logging.LogRecord]") -> None:
        super().__init__(level=logging.DEBUG)
        self.q = q

    def emit(self, record: logging.LogRecord) -> None:
        try:
            record.getMessage()  # resolve args now (record is read in another thread)
            self.q.put_nowait(record)
        except Exception:
            pass


def friendly_line(rec: logging.LogRecord, detailed: bool) -> tuple[str, str] | None:
    """Turn a log record into a readable Thai line + colour tag (None = hide)."""
    ts = time.strftime("%H:%M:%S", time.localtime(rec.created))
    ev = getattr(rec, "event", None)
    fa = getattr(rec, "from_agent", "?")
    tg = getattr(rec, "target", "?")
    via = TRANSPORT_TH.get(getattr(rec, "transport", ""), getattr(rec, "transport", ""))
    if ev == "invoke_start":
        return f"{ts}  ➜  {fa} ส่งงานให้ {tg}  (ผ่าน {via})", "info"
    if ev == "invoke_ok":
        sec = float(getattr(rec, "elapsed_ms", 0)) / 1000
        return f"{ts}  ✔  {tg} ตอบกลับ {fa} สำเร็จ  ({sec:.1f} วินาที)", "ok"
    if ev == "invoke_fail":
        code = int(getattr(rec, "status_code", 0) or 0)
        why = ERROR_TH.get(code, "ผิดพลาด")
        err = str(getattr(rec, "error", ""))[:300]
        return f"{ts}  ✖  {fa} → {tg} ไม่สำเร็จ [{code}] {why}\n            รายละเอียด: {err}", "err"
    if ev == "auth_rejected":
        what = "ไม่ได้ส่งกุญแจ (X-API-Key)" if getattr(rec, "reason", "") == "missing" else "กุญแจไม่ถูกต้อง"
        return f"{ts}  ⚠  ปฏิเสธการเชื่อมต่อ: {what}  (ผ่าน {via})", "warn"
    msg = rec.getMessage()
    if rec.name == "router.gui":
        tag = "err" if rec.levelno >= logging.ERROR else "warn" if rec.levelno >= logging.WARNING else "gui"
        return f"{ts}  •  {msg}", tag
    if detailed:
        tag = "err" if rec.levelno >= logging.ERROR else "warn" if rec.levelno >= logging.WARNING else "dim"
        return f"{ts}  {rec.levelname:<7} [{rec.name}] {msg}", tag
    if rec.levelno >= logging.ERROR:
        return f"{ts}  ✖  {msg[:400]}", "err"
    return None


# ---------------------------------------------------------------- server thread
class ServerThread:
    """uvicorn.Server running in a daemon thread (no subprocess)."""

    def __init__(self, create_app: Callable[[Settings], Any], settings: Settings) -> None:
        import uvicorn
        self.settings = settings
        app = create_app(settings)
        cfg = uvicorn.Config(app, host=settings.host, port=settings.port, log_config=None,
                             log_level=settings.log_level.lower(), access_log=False,
                             timeout_graceful_shutdown=3)  # don't hang on open MCP/SSE streams
        self.server = uvicorn.Server(cfg)
        self.error: BaseException | None = None
        self.thread = threading.Thread(target=self._run, name="router-server", daemon=True)

    def _run(self) -> None:
        try:
            self.server.run()
        except BaseException as exc:  # SystemExit from uvicorn on bind failure, etc.
            self.error = exc

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.server.should_exit = True

    @property
    def alive(self) -> bool:
        return self.thread.is_alive()

    @property
    def started(self) -> bool:
        return bool(self.server.started) and self.alive


# ---------------------------------------------------------------- the window
class RouterGUI:
    POLL_MS = 150

    def __init__(self, root: tk.Tk, create_app: Callable[[Settings], Any], *, config_path: str | None,
                 host: str | None, port: int | None, log_level: str | None, log_queue: queue.Queue,
                 router_key: str, key_generated: bool, key_warning: str | None) -> None:
        self.root = root
        self.create_app = create_app
        self.config_path = config_path
        self.cli_host = host
        self.cli_port = port
        self.cli_log_level = log_level
        self.log_queue = log_queue
        self.router_key = router_key
        self.server: ServerThread | None = None
        self.state = "stopped"          # stopped | starting | running | stopping | error
        self.restart_after_stop = False
        self.closing = False
        self.settings = self.load_settings()

        self._setup_fonts()
        self._build()
        self.refresh_all()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(self.POLL_MS, self._drain_logs)
        self.root.after(400, self._poll_server)

        log.info("ยินดีต้อนรับ! โปรแกรมเก็บการตั้งค่าไว้ที่ %s", env_file_path())
        if key_generated:
            log.info("สร้างกุญแจ Router Key ให้อัตโนมัติแล้ว (ดูช่อง \"กุญแจของโปรแกรมนี้\")")
        if key_warning:
            log.warning(key_warning)
        if os.environ.get("ROUTER_GUI_AUTOSTART", "1").strip().lower() not in ("0", "false", "no", "off"):
            self.root.after(300, self.start_server)
        # test hook: close the window automatically after N seconds (used by automated smoke tests)
        autoclose = os.environ.get("ROUTER_GUI_AUTOCLOSE")
        if autoclose:
            self.root.after(int(float(autoclose) * 1000), self.on_close)

    # ------------------------------------------------------------ settings
    def load_settings(self) -> Settings:
        s = load_settings(self.config_path)
        if self.cli_host:
            s.host = self.cli_host
        if self.cli_port:
            s.port = self.cli_port
        if self.cli_log_level:
            s.log_level = self.cli_log_level.upper()
        return s

    @property
    def base_url(self) -> str:
        host = "127.0.0.1" if self.settings.host in ("0.0.0.0", "") else self.settings.host
        return f"http://{host}:{self.settings.port}"

    @property
    def mcp_url(self) -> str:
        return self.base_url + self.settings.mcp_path

    # ------------------------------------------------------------ UI build
    def _setup_fonts(self) -> None:
        families = set(tkfont.families(self.root))
        fam = next((f for f in FONT_CANDIDATES if f in families), None)
        mono = next((f for f in MONO_CANDIDATES if f in families), "TkFixedFont")
        size = 10
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkCaptionFont"):
            try:
                f = tkfont.nametofont(name)
                if fam:
                    f.configure(family=fam)
                f.configure(size=size)
            except tk.TclError:
                pass
        base = fam or tkfont.nametofont("TkDefaultFont").actual("family")
        self.f_title = (base, 18, "bold")
        self.f_sub = (base, 11)
        self.f_bold = (base, size, "bold")
        self.f_small = (base, 9)
        self.f_mono = (mono, 10)
        self.f_log = (base, 10)

    def _build(self) -> None:
        r = self.root
        r.title(f"{APP_NAME} — ตัวกลางส่งงานระหว่าง AI")
        # Tk geometry is in *physical* pixels on a DPI-aware Windows app -> scale by the DPI factor
        try:
            f = max(1.0, r.winfo_fpixels("1i") / 96.0)
        except tk.TclError:
            f = 1.0
        sw, sh = r.winfo_screenwidth(), r.winfo_screenheight()
        w, h = min(int(1200 * f), sw - 40), min(int(820 * f), sh - 80)
        r.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 3)}")
        r.minsize(min(int(960 * f), sw - 40), min(int(620 * f), sh - 80))
        style = ttk.Style(r)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        elif "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Big.TButton", font=self.f_bold, padding=(14, 6))
        style.configure("Help.TLabel", foreground="#5f6368", font=self.f_small)
        style.configure("Head.TLabelframe.Label", font=self.f_bold)

        head = ttk.Frame(r, padding=(14, 10, 14, 4))
        head.pack(fill="x")
        ttk.Label(head, text=f"{APP_NAME}", font=self.f_title).pack(side="left")
        ttk.Label(head, text=f"  v{APP_VERSION}", style="Help.TLabel").pack(side="left", anchor="s", pady=(0, 4))
        ttk.Label(r, text="ตัวกลางให้ AI หลายตัวส่งงานหากันตามชื่อ — เช่น ให้ OpenCode สั่งงาน Grok แล้วรับคำตอบกลับมา",
                  font=self.f_sub, padding=(14, 0, 14, 8)).pack(fill="x")

        nb = ttk.Notebook(r)
        nb.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.nb = nb
        nb.enable_traversal()  # Ctrl+Tab switches tabs
        main = ttk.Frame(nb, padding=8)
        guide = ttk.Frame(nb, padding=8)
        nb.add(main, text="  หน้าหลัก  ")
        nb.add(guide, text="  คู่มือ / วิธีเชื่อมต่อ  ")
        self._build_main(main)
        self._build_guide(guide)

    # ----- main tab
    def _build_main(self, parent: ttk.Frame) -> None:
        top = ttk.Frame(parent)
        top.pack(fill="both", expand=True)
        left = ttk.Frame(top)
        left.pack(side="left", fill="y", padx=(0, 6))
        right = ttk.Frame(top)
        right.pack(side="left", fill="both", expand=True, padx=(6, 0))

        # 1) server
        sf = ttk.LabelFrame(left, text=" 1) เซิร์ฟเวอร์ — ต้องเปิดไว้ตลอดเวลาที่ใช้งาน ", padding=10,
                            style="Head.TLabelframe")
        sf.pack(fill="x")
        row = ttk.Frame(sf)
        row.pack(fill="x")
        self.srv_light = tk.Canvas(row, width=22, height=22, highlightthickness=0, bg=self._bg())
        self.srv_light.pack(side="left")
        self.srv_status = ttk.Label(row, text="หยุดทำงาน", font=self.f_bold)
        self.srv_status.pack(side="left", padx=(4, 16))
        self.srv_btn = ttk.Button(row, text="▶  เริ่มทำงาน", style="Big.TButton", command=self.toggle_server)
        self.srv_btn.pack(side="right")

        row = ttk.Frame(sf)
        row.pack(fill="x", pady=(10, 0))
        ttk.Label(row, text="ที่อยู่:").pack(side="left")
        self.url_lbl = tk.Label(row, text="", fg=BLUE, cursor="hand2", font=self.f_bold, bg=self._bg())
        self.url_lbl.pack(side="left", padx=6)
        self.url_lbl.bind("<Button-1>", lambda e: webbrowser.open(self.base_url))
        self._copy_button(row, lambda: self.base_url).pack(side="left")

        row = ttk.Frame(sf)
        row.pack(fill="x", pady=(8, 0))
        ttk.Label(row, text="พอร์ต:").pack(side="left")
        self.port_var = tk.StringVar()
        self.port_entry = ttk.Entry(row, textvariable=self.port_var, width=7)
        self.port_entry.pack(side="left", padx=6)
        self.port_btn = ttk.Button(row, text="บันทึกพอร์ต", command=self.save_port)
        self.port_btn.pack(side="left")
        self.autostart_var = tk.BooleanVar(
            value=os.environ.get("ROUTER_GUI_AUTOSTART", "1").strip().lower() not in ("0", "false", "no", "off"))
        ttk.Checkbutton(row, text="เริ่มทำงานอัตโนมัติเมื่อเปิดโปรแกรม", variable=self.autostart_var,
                        command=self.save_autostart).pack(side="left", padx=(16, 0))
        ttk.Label(sf, style="Help.TLabel", wraplength=480, justify="left",
                  text="เมื่อไฟเป็นสีเขียว OpenCode / Cursor จะเชื่อมต่อเข้ามาได้ • "
                       "เปลี่ยนพอร์ตเฉพาะเมื่อ 8080 ถูกโปรแกรมอื่นใช้อยู่").pack(fill="x", pady=(8, 0))

        # 2) keys
        kf = ttk.LabelFrame(left, text=" 2) กุญแจ (API Key) ", padding=10, style="Head.TLabelframe")
        kf.pack(fill="x", pady=(10, 0))
        ttk.Label(kf, text="กุญแจของโปรแกรมนี้ (Router Key)", font=self.f_bold).grid(row=0, column=0, columnspan=4, sticky="w")
        self.key_var = tk.StringVar(value=self.router_key)
        self.key_entry = ttk.Entry(kf, textvariable=self.key_var, width=46, font=self.f_mono, state="readonly")
        self.key_entry.grid(row=1, column=0, sticky="we", pady=4)
        self._copy_button(kf, lambda: self.key_var.get()).grid(row=1, column=1, padx=(6, 0))
        self.key_edit_btn = ttk.Button(kf, text="แก้ไข", command=self.toggle_key_edit)
        self.key_edit_btn.grid(row=1, column=2, padx=(6, 0))
        ttk.Button(kf, text="สุ่มใหม่", command=self.regenerate_key).grid(row=1, column=3, padx=(6, 0))
        ttk.Label(kf, style="Help.TLabel", wraplength=480, justify="left",
                  text="เปรียบเหมือนรหัสผ่าน — OpenCode / Cursor ต้องใส่กุญแจนี้ (ใน X-API-Key) จึงจะใช้งานได้ "
                       "โปรแกรมสร้างให้อัตโนมัติแล้ว แค่กด \"คัดลอก\" ไปวาง (ดูแท็บคู่มือ)").grid(
            row=2, column=0, columnspan=4, sticky="w")

        ttk.Label(kf, text="กุญแจ xAI สำหรับ Grok (XAI_API_KEY)", font=self.f_bold).grid(
            row=3, column=0, columnspan=4, sticky="w", pady=(12, 0))
        self.xai_var = tk.StringVar(value=os.environ.get("XAI_API_KEY", ""))
        self.xai_entry = ttk.Entry(kf, textvariable=self.xai_var, width=46, font=self.f_mono, show="•")
        self.xai_entry.grid(row=4, column=0, sticky="we", pady=4)
        self.xai_show = tk.BooleanVar(value=False)
        ttk.Checkbutton(kf, text="แสดง", variable=self.xai_show,
                        command=lambda: self.xai_entry.configure(show="" if self.xai_show.get() else "•")).grid(
            row=4, column=1, padx=(6, 0))
        ttk.Button(kf, text="บันทึก", command=self.save_xai_key).grid(row=4, column=2, columnspan=2, padx=(6, 0), sticky="we")
        hint = ttk.Frame(kf)
        hint.grid(row=5, column=0, columnspan=4, sticky="w")
        ttk.Label(hint, style="Help.TLabel", text="ขอกุญแจได้ที่").pack(side="left")
        link = tk.Label(hint, text="console.x.ai", fg=BLUE, cursor="hand2", font=self.f_small, bg=self._bg())
        link.pack(side="left", padx=3)
        link.bind("<Button-1>", lambda e: webbrowser.open("https://console.x.ai/"))
        ttk.Label(hint, style="Help.TLabel", text="→ API Keys • ไม่ใช้ Grok ก็เว้นว่างได้").pack(side="left")
        self.env_lbl = ttk.Label(kf, style="Help.TLabel", text="")
        self.env_lbl.grid(row=6, column=0, columnspan=4, sticky="w", pady=(8, 0))
        kf.columnconfigure(0, weight=1)

        # 3) agents
        af = ttk.LabelFrame(right, text=" 3) AI ปลายทาง (Agents) — ส่งงานให้ใครได้บ้าง ", padding=10,
                            style="Head.TLabelframe")
        af.pack(fill="x")
        legend = ttk.Frame(af)
        legend.pack(fill="x")
        for color, text in ((GREEN, "พร้อมใช้"), (GREY, "ยังไม่ตั้งค่า"), (RED, "ปิดอยู่")):
            c = tk.Canvas(legend, width=14, height=14, highlightthickness=0, bg=self._bg())
            c.create_oval(2, 2, 12, 12, fill=color, outline=color)
            c.pack(side="left")
            ttk.Label(legend, text=text, style="Help.TLabel").pack(side="left", padx=(2, 12))
        ttk.Button(legend, text="รีเฟรช", command=self.refresh_all).pack(side="right")
        self.agents_box = ttk.Frame(af)
        self.agents_box.pack(fill="x", pady=(8, 0))
        self.agent_notes: list[ttk.Label] = []
        self.agents_box.bind("<Configure>", lambda e: [n.configure(wraplength=max(200, e.width - 40))
                                                       for n in self.agent_notes if n.winfo_exists()])

        # 4) log (right column, takes all remaining height)
        lf = ttk.LabelFrame(right, text=" 4) บันทึกการทำงาน — ใครส่งงานให้ใคร สำเร็จหรือไม่ ", padding=8,
                            style="Head.TLabelframe")
        lf.pack(fill="both", expand=True, pady=(10, 0))
        bar = ttk.Frame(lf)
        bar.pack(fill="x")
        self.detail_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="แสดงรายละเอียดทางเทคนิค", variable=self.detail_var).pack(side="left")
        ttk.Button(bar, text="ล้าง", command=self.clear_log).pack(side="right")
        self.log_text = scrolledtext.ScrolledText(lf, height=8, width=40, wrap="word", font=self.f_log, state="disabled",
                                                  background="#fbfbfb", relief="flat", borderwidth=1)
        self.log_text.pack(fill="both", expand=True, pady=(6, 0))
        for tag, color in (("ok", GREEN), ("err", RED), ("warn", ORANGE), ("info", "#202124"),
                           ("gui", BLUE), ("dim", "#5f6368")):
            self.log_text.tag_configure(tag, foreground=color)

    # ----- guide tab
    def _build_guide(self, parent: ttk.Frame) -> None:
        self.guide = scrolledtext.ScrolledText(parent, wrap="word", font=self.f_log, relief="flat",
                                               background=self._bg(), borderwidth=0, padx=10, pady=6)
        self.guide.pack(fill="both", expand=True)
        self.guide.tag_configure("h1", font=(self.f_bold[0], 14, "bold"), spacing1=10, spacing3=4)
        self.guide.tag_configure("h2", font=(self.f_bold[0], 11, "bold"), spacing1=12, spacing3=2)
        self.guide.tag_configure("code", font=self.f_mono, background="#f1f3f4", lmargin1=12, lmargin2=12,
                                 rmargin=12, spacing1=2, spacing3=2)
        self.guide.tag_configure("help", foreground="#5f6368")

    def render_guide(self) -> None:
        g = self.guide
        g.configure(state="normal")
        g.delete("1.0", "end")
        key = self.key_var.get()
        exe_cmd = self.stdio_command()

        def h1(t: str) -> None: g.insert("end", t + "\n", "h1")
        def h2(t: str) -> None: g.insert("end", t + "\n", "h2")
        def p(t: str, tag: str = "") -> None: g.insert("end", t + "\n", tag)

        def code(text: str, label: str = "คัดลอก") -> None:
            g.insert("end", text.rstrip() + "\n", "code")
            g.window_create("end", window=self._copy_button(g, lambda t=text: t.strip(), label))
            g.insert("end", "\n")

        h1("เริ่มต้นใช้งาน 3 ขั้นตอน")
        p("1.  ที่แท็บ \"หน้าหลัก\" ให้ไฟเซิร์ฟเวอร์เป็นสีเขียว (กด \"เริ่มทำงาน\") และเปิดโปรแกรมนี้ค้างไว้")
        p("2.  คัดลอก config ด้านล่างไปวางในไฟล์ตั้งค่าของ OpenCode หรือ Cursor (กุญแจถูกใส่ให้แล้ว)")
        p("3.  ปิดแล้วเปิด OpenCode / Cursor ใหม่ แล้วสั่งงานได้เลย เช่น \"ใช้ agent-router ส่งงานให้ grok ช่วยรีวิวโค้ดนี้\"")

        h2("ข้อมูลสำหรับเชื่อมต่อ")
        p("MCP URL (ที่อยู่สำหรับ AI):")
        code(self.mcp_url)
        p("X-API-Key (กุญแจของโปรแกรมนี้):")
        code(key)

        oc_remote = {"$schema": "https://opencode.ai/config.json",
                     "mcp": {"agent-router": {"type": "remote", "url": self.mcp_url,
                                              "headers": {"X-API-Key": key}, "oauth": False, "enabled": True}}}
        oc_local = {"$schema": "https://opencode.ai/config.json",
                    "mcp": {"agent-router": {"type": "local", "command": exe_cmd, "enabled": True}}}
        cu_remote = {"mcpServers": {"agent-router": {"url": self.mcp_url, "headers": {"X-API-Key": key}}}}
        cu_local = {"mcpServers": {"agent-router": {"type": "stdio", "command": exe_cmd[0], "args": exe_cmd[1:]}}}

        h1("OpenCode")
        p("วางในไฟล์ opencode.json ที่โฟลเดอร์โปรเจกต์ หรือไฟล์รวมที่ %USERPROFILE%\\.config\\opencode\\opencode.json",
          "help")
        h2("แบบที่ 1 (แนะนำ): เชื่อมผ่าน URL — ต้องเปิดโปรแกรมนี้ไว้")
        code(json.dumps(oc_remote, indent=2, ensure_ascii=False))
        h2("แบบที่ 2: ให้ OpenCode เปิดโปรแกรมนี้เอง (stdio) — ไม่ต้องเปิดหน้าต่างนี้ค้าง")
        code(json.dumps(oc_local, indent=2, ensure_ascii=False))
        p("ตรวจสอบได้ด้วยคำสั่ง  opencode mcp list   • ชื่อ tool ใน OpenCode: agent-router_invoke_agent", "help")

        h1("Cursor")
        p("วางในไฟล์ .cursor\\mcp.json ที่โฟลเดอร์โปรเจกต์ หรือ %USERPROFILE%\\.cursor\\mcp.json (ใช้ทุกโปรเจกต์)",
          "help")
        h2("แบบที่ 1 (แนะนำ): เชื่อมผ่าน URL")
        code(json.dumps(cu_remote, indent=2, ensure_ascii=False))
        h2("แบบที่ 2: ให้ Cursor เปิดโปรแกรมนี้เอง (stdio)")
        code(json.dumps(cu_local, indent=2, ensure_ascii=False))
        p("ถ้าไม่ขึ้น: Cursor → Output → เลือก \"MCP Logs\" เพื่อดูสาเหตุ", "help")

        h1("Tools ที่ AI จะเห็น")
        p("•  invoke_agent(target, message, context, from_agent) — ส่งงานให้ AI ตัวที่ระบุชื่อ แล้วรับคำตอบกลับ")
        p("•  delegate(...) — ชื่อเรียกอีกแบบของ invoke_agent")
        p("•  list_agents() — ดูว่ามี AI ตัวไหนให้ส่งงานได้บ้าง")
        p("ส่งงานได้ทีละตัวตามชื่อเท่านั้น (ไม่มีการส่งหาทุกตัวพร้อมกัน)", "help")

        h1("ทดสอบด้วย PowerShell (ไม่บังคับ)")
        code(f'Invoke-RestMethod {self.base_url}/health')
        code(f'$h = @{{ "X-API-Key" = "{key}" }}\n'
             f'$b = @{{ target = "grok"; message = "สวัสดี ช่วยแนะนำตัวหน่อย" }} | ConvertTo-Json\n'
             f'Invoke-RestMethod -Method Post -Uri {self.base_url}/invoke -Headers $h '
             f'-ContentType "application/json; charset=utf-8" -Body ([Text.Encoding]::UTF8.GetBytes($b))')

        h1("ปัญหาที่พบบ่อย")
        p("•  ไฟเซิร์ฟเวอร์เป็นสีแดง \"พอร์ตถูกใช้งาน\" → อาจเปิดโปรแกรมนี้ซ้ำอยู่แล้ว หรือเปลี่ยนพอร์ตแล้วกดบันทึก (อย่าลืมแก้ URL ใน config)")
        p("•  OpenCode / Cursor เชื่อมไม่ได้ → ตรวจว่าไฟเป็นสีเขียว และกุญแจใน config ตรงกับช่อง Router Key")
        p("•  Grok ตอบว่า \"ยังไม่ได้ตั้งค่า\" → ใส่ XAI_API_KEY ที่หน้าหลักแล้วกดบันทึก")
        p("•  ดูประวัติย้อนหลังได้ในไฟล์ log: " + str(self.log_file_path()), "help")
        g.configure(state="disabled")

    # ------------------------------------------------------------ small widgets
    def _bg(self) -> str:
        try:
            return ttk.Style(self.root).lookup("TFrame", "background") or self.root.cget("bg")
        except tk.TclError:
            return self.root.cget("bg")

    def _copy_button(self, parent: Any, getter: Callable[[], str], label: str = "คัดลอก") -> ttk.Button:
        btn = ttk.Button(parent, text=label)

        def do() -> None:
            self.copy(getter())
            btn.configure(text="คัดลอกแล้ว ✔")
            self.root.after(1500, lambda: btn.winfo_exists() and btn.configure(text=label))

        btn.configure(command=do)
        return btn

    def copy(self, text: str) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update_idletasks()

    @staticmethod
    def _light(canvas: tk.Canvas, color: str, size: int = 22) -> None:
        canvas.delete("all")
        canvas.create_oval(3, 3, size - 3, size - 3, fill=color, outline=color)

    def stdio_command(self) -> list[str]:
        if getattr(sys, "frozen", False):
            return [sys.executable, "--mcp-stdio"]
        return [sys.executable, str(Path(__file__).resolve().parent / "main.py"), "--mcp-stdio"]

    def log_file_path(self) -> Path:
        p = Path(self.settings.log_file or "logs/router.log")
        return p if p.is_absolute() else app_base_dir() / p

    # ------------------------------------------------------------ refresh
    def refresh_all(self) -> None:
        try:
            self.settings = self.load_settings()
        except Exception as exc:
            log.error("อ่านไฟล์ตั้งค่าไม่ได้: %s", exc)
        self.url_lbl.configure(text=self.base_url)
        self.port_var.set(str(self.settings.port))
        self.env_lbl.configure(text=f"บันทึกไว้ที่: {env_file_path()}")
        self.refresh_agents()
        self.render_guide()
        self._update_server_widgets()

    def refresh_agents(self) -> None:
        for w in self.agents_box.winfo_children():
            w.destroy()
        self.agent_notes = []
        wrap = max(200, self.agents_box.winfo_width() - 40) if self.agents_box.winfo_width() > 1 else 420
        try:
            agents = Router(self.settings).list_agents()
        except Exception as exc:
            agents = []
            log.error("สร้างรายการ agent ไม่ได้: %s", exc)
        for i, a in enumerate(agents):
            if not a["enabled"]:
                color, status = RED, "ปิดอยู่"
            elif a["configured"]:
                color, status = GREEN, "พร้อมใช้"
            else:
                color, status = GREY, "ยังไม่ตั้งค่า"
            row = ttk.Frame(self.agents_box, padding=(0, 2))
            row.grid(row=i, column=0, sticky="we")
            c = tk.Canvas(row, width=22, height=22, highlightthickness=0, bg=self._bg())
            self._light(c, color)
            c.grid(row=0, column=0, rowspan=2, sticky="n", padx=(0, 6))
            line = ttk.Frame(row)
            line.grid(row=0, column=1, sticky="w")
            ttk.Label(line, text=a["name"], font=self.f_bold).pack(side="left")
            extra = f"  ({a.get('model')})" if a.get("model") else ""
            ttk.Label(line, text=f"   {status}{extra}", foreground=color).pack(side="left")
            note = a.get("error") or a.get("description") if a["type"] not in AGENT_NOTES else AGENT_NOTES[a["type"]]
            if a["type"] == "grok" and a["configured"]:
                note = "พร้อมใช้งาน — ส่งงานด้วย target = \"" + a["name"] + "\""
            note_lbl = ttk.Label(row, text=note or "", style="Help.TLabel", wraplength=wrap, justify="left")
            note_lbl.grid(row=1, column=1, sticky="w")
            self.agent_notes.append(note_lbl)
        self.agents_box.columnconfigure(0, weight=1)

    # ------------------------------------------------------------ server control
    def toggle_server(self) -> None:
        if self.state in ("running", "starting"):
            self.stop_server()
        elif self.state in ("stopped", "error"):
            self.start_server()

    def start_server(self, retries: int = 0) -> None:
        if self.state in ("running", "starting", "stopping") or self.closing:
            return
        try:
            self.settings = self.load_settings()
        except Exception as exc:
            self._set_state("error", f"ไฟล์ตั้งค่าผิดพลาด: {exc}")
            return
        if not port_is_free(self.settings.host, self.settings.port):
            if retries > 0:  # just restarted: give the OS a moment to release the port
                self.root.after(500, lambda: self.start_server(retries - 1))
                return
            self._set_state("error", f"พอร์ต {self.settings.port} ถูกใช้งานอยู่ (เปิดโปรแกรมซ้ำ หรือโปรแกรมอื่นใช้)")
            log.error("เริ่มไม่สำเร็จ: พอร์ต %s ถูกใช้งานอยู่ — ลองเปลี่ยนพอร์ตแล้วกดบันทึก", self.settings.port)
            return
        try:
            self.server = ServerThread(self.create_app, self.settings)
            self.server.start()
        except Exception as exc:
            log.exception("start failed")
            self._set_state("error", f"เริ่มไม่สำเร็จ: {exc}")
            return
        self.refresh_agents()
        self._set_state("starting")

    def stop_server(self) -> None:
        if self.server and self.server.alive:
            self.server.stop()
            self._set_state("stopping")
        else:
            self._set_state("stopped")

    def restart_server(self) -> None:
        if self.state in ("running", "starting"):
            self.restart_after_stop = True
            self.stop_server()
        else:
            self.refresh_all()

    def _poll_server(self) -> None:
        s = self.server
        if s is not None:
            if self.state == "starting" and s.started:
                self._set_state("running")
                log.info("เซิร์ฟเวอร์พร้อมแล้วที่ %s  (MCP: %s)", self.base_url, self.mcp_url)
            elif self.state in ("starting", "running", "stopping") and not s.alive:
                if s.error is not None and self.state != "stopping":
                    self._set_state("error", "เซิร์ฟเวอร์หยุดเพราะเกิดข้อผิดพลาด (ดูบันทึกด้านล่าง)")
                    log.error("เซิร์ฟเวอร์หยุดทำงาน: %s", s.error)
                else:
                    self._set_state("stopped")
                    log.info("หยุดเซิร์ฟเวอร์แล้ว")
                self.server = None
                if self.closing:
                    self._finish_close()
                    return
                if self.restart_after_stop:
                    self.restart_after_stop = False
                    self.refresh_all()
                    self.start_server(retries=10)
        elif self.closing:
            self._finish_close()
            return
        self.root.after(250, self._poll_server)

    def _set_state(self, state: str, detail: str = "") -> None:
        self.state = state
        self.state_detail = detail
        self._update_server_widgets()

    def _update_server_widgets(self) -> None:
        st = getattr(self, "state", "stopped")
        text, color, btn = {
            "running": ("กำลังทำงาน", GREEN, "■  หยุดทำงาน"),
            "starting": ("กำลังเริ่ม...", ORANGE, "■  หยุดทำงาน"),
            "stopping": ("กำลังหยุด...", ORANGE, "…"),
            "error": (getattr(self, "state_detail", "") or "ผิดพลาด", RED, "▶  ลองอีกครั้ง"),
        }.get(st, ("หยุดทำงาน", GREY, "▶  เริ่มทำงาน"))
        self._light(self.srv_light, color)
        self.srv_status.configure(text=text, foreground=color)
        self.srv_btn.configure(text=btn, state="disabled" if st == "stopping" else "normal")
        editable = "normal" if st in ("stopped", "error") else "disabled"
        self.port_entry.configure(state=editable)
        self.port_btn.configure(state=editable)

    # ------------------------------------------------------------ saving
    def _save_env(self, updates: dict[str, str | None]) -> bool:
        try:
            path = update_env_file(updates)
            log.info("บันทึกการตั้งค่าแล้ว (%s)", path.name)
            return True
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"บันทึกไฟล์ไม่ได้:\n{exc}\n\nลองย้ายโปรแกรมไปไว้ในโฟลเดอร์ที่เขียนได้ "
                                           f"(เช่น Documents หรือ Desktop)")
            return False

    def save_xai_key(self) -> None:
        value = self.xai_var.get().strip()
        if value and not value.startswith("xai-"):
            if not messagebox.askyesno(APP_NAME, "กุญแจ xAI ปกติจะขึ้นต้นด้วย \"xai-\"\nยืนยันจะบันทึกค่านี้หรือไม่?"):
                return
        if self._save_env({"XAI_API_KEY": value or None}):
            log.info("บันทึกกุญแจ xAI แล้ว — %s", "Grok พร้อมใช้" if value else "ลบกุญแจแล้ว")
            self.restart_server()

    def toggle_key_edit(self) -> None:
        if str(self.key_entry.cget("state")) == "readonly":
            self.key_entry.configure(state="normal")
            self.key_entry.focus_set()
            self.key_edit_btn.configure(text="บันทึก")
        else:
            self._apply_router_key(self.key_var.get().strip())

    def regenerate_key(self) -> None:
        if messagebox.askyesno(APP_NAME, "สร้างกุญแจใหม่?\nกุญแจเดิมจะใช้ไม่ได้อีก ต้องไปแก้ config ของ OpenCode / Cursor ด้วย"):
            self.key_var.set(generate_api_key())
            self._apply_router_key(self.key_var.get())

    def _apply_router_key(self, new_key: str) -> None:
        if len(new_key) < 12 or any(c in new_key for c in " ,:\"'"):
            messagebox.showwarning(APP_NAME, "กุญแจต้องยาวอย่างน้อย 12 ตัวอักษร และห้ามมีช่องว่าง , : หรือเครื่องหมายคำพูด")
            return
        keys = env_router_keys()
        if keys:  # replace the first (main) key, keep its agent binding and the other keys
            first, agent = next(iter(keys.items()))
            keys = {(new_key if k == first else k): (agent if k == first else a) for k, a in keys.items()}
        else:
            keys = {new_key: None}
        if self._save_env({"ROUTER_API_KEYS": format_env_keys(keys)}):
            self.router_key = new_key
            self.key_entry.configure(state="readonly")
            self.key_edit_btn.configure(text="แก้ไข")
            log.info("เปลี่ยน Router Key แล้ว — อย่าลืมอัปเดตกุญแจใน config ของ OpenCode / Cursor (แท็บคู่มือ)")
            self.restart_server()

    def save_port(self) -> None:
        try:
            port = int(self.port_var.get())
            assert 1 <= port <= 65535
        except (ValueError, AssertionError):
            messagebox.showwarning(APP_NAME, "พอร์ตต้องเป็นตัวเลข 1 - 65535")
            return
        if self._save_env({"ROUTER_PORT": str(port)}):
            self.cli_port = None  # GUI choice wins over a --port given at launch
            self.refresh_all()

    def save_autostart(self) -> None:
        self._save_env({"ROUTER_GUI_AUTOSTART": "1" if self.autostart_var.get() else "0"})

    # ------------------------------------------------------------ log panel
    def _drain_logs(self) -> None:
        lines: list[tuple[str, str]] = []
        try:
            for _ in range(500):
                rec = self.log_queue.get_nowait()
                item = friendly_line(rec, self.detail_var.get())
                if item:
                    lines.append(item)
        except queue.Empty:
            pass
        if lines:
            t = self.log_text
            t.configure(state="normal")
            for text, tag in lines:
                t.insert("end", text + "\n", tag)
            excess = int(t.index("end-1c").split(".")[0]) - 3000
            if excess > 0:
                t.delete("1.0", f"{excess}.0")
            t.see("end")
            t.configure(state="disabled")
        if not self.closing:
            self.root.after(self.POLL_MS, self._drain_logs)

    def clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    # ------------------------------------------------------------ shutdown
    def on_close(self) -> None:
        if self.closing:
            return
        self.closing = True
        self.root.title(f"{APP_NAME} — กำลังปิด...")
        if self.server and self.server.alive:
            self.server.stop()
            self._set_state("stopping")
            self.root.after(8000, self._finish_close)  # hard limit
        else:
            self._finish_close()

    def _finish_close(self) -> None:
        if getattr(self, "_closed", False):
            return
        self._closed = True
        try:
            self.root.destroy()
        except tk.TclError:
            pass


def run_gui(*, create_app: Callable[[Settings], Any], config_path: str | None = None, host: str | None = None,
            port: int | None = None, log_level: str | None = None) -> int:
    """Entry point used by main.py when started without arguments (or with --gui)."""
    hide_own_console()
    enable_dpi_awareness()

    try:
        root = tk.Tk()
    except tk.TclError as exc:  # e.g. no $DISPLAY on Linux
        raise GuiUnavailable(f"cannot open a window: {exc}") from exc

    key, generated, warning = ensure_router_key(config_path)
    try:
        settings = load_settings(config_path)
    except Exception as exc:
        messagebox.showerror(APP_NAME, f"ไฟล์ตั้งค่าผิดพลาด:\n{exc}")
        root.destroy()
        return 2
    level = (log_level or settings.log_level or "INFO").upper()
    setup_logging(level, settings.log_file or "logs/router.log")
    q: queue.Queue = queue.Queue()
    handler = QueueLogHandler(q)
    logging.getLogger().addHandler(handler)

    try:
        RouterGUI(root, create_app, config_path=config_path, host=host, port=port, log_level=log_level,
                  log_queue=q, router_key=key, key_generated=generated, key_warning=warning)
        root.mainloop()
    finally:
        logging.getLogger().removeHandler(handler)
    return 0
