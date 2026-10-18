"""
GUI: add / edit / delete / test destination AIs ("AI ปลายทาง").

Used by gui.py. Pure tkinter. All persistence goes through agent_store (config.yaml + .env split).
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import messagebox, scrolledtext, ttk
from typing import Any, Callable

import agent_store
from agents import AgentError, create_agent
from config import APP_NAME, missing_env_vars, substitute_env
from presets import PRESETS, get_preset

# (internal type, label shown in the dropdown)
TYPE_CHOICES = [
    ("http", "http ทั่วไป (webhook / API ใดก็ได้)"),
    ("openai-compatible", "openai-compatible (รูปแบบ OpenAI /chat/completions)"),
    ("grok", "grok (xAI)"),
    ("cursor", "cursor-webhook"),
    ("opencode", "opencode (opencode serve)"),
]
TYPE_ALIASES = {"xai": "grok", "webhook": "http", "openai": "openai-compatible",
                "openai_compatible": "openai-compatible", "cursor-webhook": "cursor"}
AUTH_CHOICES = [("none", "ไม่มี (เช่น โปรแกรมในเครื่อง)"), ("bearer", "Bearer token  (Authorization: Bearer ...)"),
                ("header", "Header กำหนดเอง  (เช่น x-api-key)")]
URL_FIELD = {"http": "url", "openai-compatible": "url", "grok": "base_url", "cursor": "webhook_url",
             "opencode": "base_url"}
URL_LABEL = {
    "http": ("URL ปลายทาง", "URL เต็มที่จะส่งงานไป เช่น https://example.com/api/chat"),
    "openai-compatible": ("Base URL", "เช่น https://api.openai.com/v1  (ใส่ URL เต็มที่ลงท้าย /chat/completions ก็ได้)"),
    "grok": ("Base URL", "เว้นว่าง = https://api.x.ai/v1"),
    "cursor": ("Webhook URL", "URL ของสะพาน (bridge) ที่รับ JSON {message, context, from_agent} แล้วตอบกลับ"),
    "opencode": ("Base URL", "ที่อยู่ของ opencode serve เช่น http://127.0.0.1:4096"),
}
ALL = {"http", "openai-compatible", "grok", "cursor", "opencode", "other"}
BODY_EXAMPLE = {"model": "{model}", "input": "{prompt}", "from": "{from_agent}"}
TEST_MESSAGE = "สวัสดี นี่คือข้อความทดสอบจาก AI Agent Router — ช่วยตอบกลับสั้นๆ ว่า OK"
PLACEHOLDER_HELP = ("ตัวแทนที่ใช้ได้: {message} {prompt}=ข้อความ+context {context} {from_agent} {target} "
                    "{model} {system_prompt} {temperature} {max_tokens} • เว้นว่าง = ส่ง {message, context, "
                    "from_agent, target}")


def norm_type(t: Any) -> str:
    t = str(t or "http").strip().lower()
    return TYPE_ALIASES.get(t, t)


def run_agent_test(name: str, cfg: dict[str, Any], message: str) -> tuple[bool, str, float]:
    """Instantiate an agent from a *resolved* cfg and send one message. (ok, text, seconds)."""
    t0 = time.perf_counter()

    async def go() -> str:
        agent = create_agent(name, cfg)
        try:
            if agent.missing_env:
                raise AgentError(agent.not_configured_reason(), status_code=503, code="agent_not_configured")
            return await agent.invoke(message, {"note": "test from AI Agent Router GUI"}, "router-test")
        finally:
            await agent.aclose()

    try:
        text = asyncio.run(go())
        return True, text, time.perf_counter() - t0
    except AgentError as exc:
        return False, f"[{exc.status_code} {exc.code}] {exc.message}", time.perf_counter() - t0
    except Exception as exc:  # bad config etc.
        return False, f"{exc.__class__.__name__}: {exc}", time.perf_counter() - t0


def resolve_cfg(raw: dict[str, Any], overrides: dict[str, str] | None = None) -> dict[str, Any]:
    """raw config.yaml entry -> what the router would use (${VAR} substituted, missing list attached)."""
    raw = copy.deepcopy(raw)
    for k, v in (overrides or {}).items():
        raw[k] = v
    missing = missing_env_vars(raw)
    cfg = substitute_env(raw)
    cfg["_missing_env"] = missing
    return cfg


class ScrollFrame(ttk.Frame):
    """Vertical scrolling container (dialog content is taller than small laptop screens)."""

    def __init__(self, parent: Any, bg: str) -> None:
        super().__init__(parent)
        self.canvas = tk.Canvas(self, highlightthickness=0, bg=bg)
        sb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas, padding=(12, 8))
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        self.canvas.configure(yscrollcommand=sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.canvas.bind_all(seq, self._wheel, add="+")

    def _wheel(self, e: Any) -> None:
        try:
            if not str(e.widget).startswith(str(self.winfo_toplevel())):
                return
            if isinstance(e.widget, (tk.Text,)):
                return
        except Exception:
            return
        delta = -1 if getattr(e, "num", 0) == 4 or getattr(e, "delta", 0) > 0 else 1
        self.canvas.yview_scroll(delta * 2, "units")


class AgentDialog:
    """Add (name=None) or edit an agent. Calls on_saved(name, env_vars_written) after a successful save."""

    def __init__(self, app: Any, *, name: str | None, raw_cfg: dict[str, Any] | None,
                 existing: list[str], on_saved: Callable[[str, list[str]], None]) -> None:
        self.app = app
        self.old_name = name
        self.existing = existing
        self.on_saved = on_saved
        self.raw = copy.deepcopy(raw_cfg or {})
        self.preset_note = ""

        root = app.root
        self.win = w = tk.Toplevel(root)
        w.title(("แก้ไข AI ปลายทาง: " + name) if name else "เพิ่ม AI ปลายทาง")
        w.transient(root)
        f = getattr(app, "scale", 1.0)
        sw, sh = w.winfo_screenwidth(), w.winfo_screenheight()
        ww, hh = min(int(820 * f), sw - 40), min(int(800 * f), sh - 80)
        w.geometry(f"{ww}x{hh}+{max(0, root.winfo_rootx() + 40)}+{max(0, root.winfo_rooty() + 20)}")
        w.minsize(min(int(640 * f), sw - 40), min(int(480 * f), sh - 80))

        self.sf = ScrollFrame(w, app._bg())
        self.sf.pack(fill="both", expand=True)
        body = self.sf.inner
        body.columnconfigure(1, weight=1)
        self.rows: list[tuple[list[tk.Widget], set[str]]] = []
        self.r = 0

        bar = ttk.Frame(w, padding=(12, 8))
        bar.pack(fill="x", side="bottom")
        ttk.Button(bar, text="🧪  ทดสอบ (ยังไม่บันทึก)", command=self.test).pack(side="left")
        ttk.Button(bar, text="ยกเลิก", command=self.win.destroy).pack(side="right")
        ttk.Button(bar, text="💾  บันทึก", style="Big.TButton", command=self.save).pack(side="right", padx=(0, 8))

        self._build(body)
        self._load(self.raw, name)
        w.bind("<Escape>", lambda e: w.destroy())
        w.after(50, self._grab)

    def _grab(self) -> None:
        try:
            self.win.grab_set()
            self.e_name.focus_set()
        except tk.TclError:
            pass

    # ------------------------------------------------------------------ layout helpers
    def _row(self, label: str, widget: tk.Widget, help_text: str = "", types: set[str] | None = None,
             sticky: str = "we") -> ttk.Label:
        lbl = ttk.Label(self.sf.inner, text=label, font=self.app.f_bold)
        lbl.grid(row=self.r, column=0, sticky="nw", padx=(0, 10), pady=(8, 0))
        widget.grid(row=self.r, column=1, sticky=sticky, pady=(8, 0))
        widgets: list[tk.Widget] = [lbl, widget]
        self.r += 1
        hl = ttk.Label(self.sf.inner, text=help_text, style="Help.TLabel", wraplength=560, justify="left")
        if help_text:
            hl.grid(row=self.r, column=1, sticky="w")
            widgets.append(hl)
            self.r += 1
        self.rows.append((widgets, types or ALL))
        return hl

    def _section(self, text: str, types: set[str] | None = None) -> None:
        lbl = ttk.Label(self.sf.inner, text=text, font=(self.app.f_bold[0], 11, "bold"), foreground="#1a73e8")
        lbl.grid(row=self.r, column=0, columnspan=2, sticky="w", pady=(16, 0))
        sep = ttk.Separator(self.sf.inner)
        self.r += 1
        sep.grid(row=self.r, column=0, columnspan=2, sticky="we", pady=(2, 0))
        self.r += 1
        self.rows.append(([lbl, sep], types or ALL))

    def _build(self, p: ttk.Frame) -> None:
        app = self.app
        # --- preset
        self.preset_var = tk.StringVar(value="— เลือกเพื่อกรอกช่องให้อัตโนมัติ —")
        cb = ttk.Combobox(p, textvariable=self.preset_var, state="readonly", width=40,
                          values=[pr["label"] for pr in PRESETS])
        cb.bind("<<ComboboxSelected>>", lambda e: self.apply_preset())
        self.preset_help = self._row("พรีเซ็ต", cb, "เลือกผู้ให้บริการ แล้วใส่แค่ API key ของคุณเอง "
                                                  "(ทุกช่องแก้ไขได้ภายหลัง)", sticky="w")
        self.key_link = tk.Label(p, text="", fg="#1a73e8", cursor="hand2", font=app.f_small, bg=app._bg())
        self.key_link.grid(row=self.r, column=1, sticky="w")
        self.key_link.bind("<Button-1>", lambda e: self.key_link.cget("text") and
                           webbrowser.open(self.key_link.cget("text").split(" ", 1)[-1]))
        self.r += 1

        # --- basics
        self._section("ข้อมูลหลัก")
        self.name_var = tk.StringVar()
        self.name_var.trace_add("write", lambda *a: self._sync_envname())
        self.e_name = ttk.Entry(p, textvariable=self.name_var, width=30, font=app.f_mono)
        self._row("ชื่อ (target)", self.e_name, "ชื่อที่ AI ตัวอื่นใช้เรียก เช่น claude — ภาษาอังกฤษ ตัวเลข - _ . "
                                               "ไม่มีช่องว่าง", sticky="w")
        self.type_var = tk.StringVar()
        self.type_cb = ttk.Combobox(p, textvariable=self.type_var, state="readonly", width=48,
                                    values=[lbl for _, lbl in TYPE_CHOICES])
        self.type_cb.bind("<<ComboboxSelected>>", lambda e: self.update_visibility())
        self._row("ชนิด", self.type_cb, "รูปแบบการคุยกับปลายทาง — ผู้ให้บริการส่วนใหญ่ใช้ openai-compatible",
                  sticky="w")
        self.enabled_var = tk.BooleanVar(value=True)
        self._row("เปิดใช้งาน", ttk.Checkbutton(p, text="เปิด (ปิดไว้ = เรียกไม่ได้ แต่ยังเก็บการตั้งค่า)",
                                                variable=self.enabled_var), sticky="w")
        self.desc_var = tk.StringVar()
        self._row("คำอธิบาย", ttk.Entry(p, textvariable=self.desc_var), "ข้อความสั้นๆ ที่ AI อื่นเห็นใน list_agents")

        # --- connection
        self._section("การเชื่อมต่อ")
        self.url_var = tk.StringVar()
        self.url_lbl_widgets = None
        self.url_help = self._row("URL", ttk.Entry(p, textvariable=self.url_var, font=app.f_mono), " ")
        self.url_title = self.rows[-1][0][0]
        self.method_var = tk.StringVar(value="POST")
        self._row("HTTP method", ttk.Combobox(p, textvariable=self.method_var, state="readonly", width=8,
                                              values=["POST", "PUT", "PATCH", "GET"]),
                  "ส่วนใหญ่ใช้ POST", types={"http", "cursor", "other"}, sticky="w")
        self.timeout_var = tk.StringVar()
        self._row("หมดเวลา (วินาที)", ttk.Entry(p, textvariable=self.timeout_var, width=8),
                  "รอคำตอบนานสุดกี่วินาที (เว้นว่าง = 120, opencode = 600)", sticky="w")

        # --- auth
        self._section("กุญแจ / การยืนยันตัวตน")
        self.auth_var = tk.StringVar()
        self.auth_cb = ttk.Combobox(p, textvariable=self.auth_var, state="readonly", width=40,
                                    values=[lbl for _, lbl in AUTH_CHOICES])
        self.auth_cb.bind("<<ComboboxSelected>>", lambda e: self.update_visibility())
        self._row("วิธีส่งกุญแจ", self.auth_cb, "", types={"http", "openai-compatible", "cursor", "other"},
                  sticky="w")
        self.auth_header_var = tk.StringVar(value="x-api-key")
        self._row("ชื่อ header", ttk.Entry(p, textvariable=self.auth_header_var, width=24, font=app.f_mono),
                  "เช่น x-api-key (Anthropic) หรือ api-key (Azure)", types={"_header"}, sticky="w")
        kf = ttk.Frame(p)
        self.key_var = tk.StringVar()
        self.key_entry = ttk.Entry(kf, textvariable=self.key_var, show="•", font=app.f_mono)
        self.key_entry.pack(side="left", fill="x", expand=True)
        self.key_show = tk.BooleanVar(value=False)
        ttk.Checkbutton(kf, text="แสดง", variable=self.key_show,
                        command=lambda: self.key_entry.configure(show="" if self.key_show.get() else "•")
                        ).pack(side="left", padx=(6, 0))
        self.key_help = self._row("API key", kf, " ", types={"_key"})
        self.key_title = self.rows[-1][0][0]
        self.envname_var = tk.StringVar()
        self.envname_var.trace_add("write", lambda *a: self._update_key_help())
        self._row("เก็บใน .env ชื่อ", ttk.Entry(p, textvariable=self.envname_var, width=30, font=app.f_mono),
                  "กุญแจจริงถูกเขียนลงไฟล์ .env เท่านั้น — config.yaml เก็บแค่ ${ชื่อนี้}", types={"_key"},
                  sticky="w")

        # --- model
        self._section("โมเดลและคำสั่งระบบ", types={"http", "openai-compatible", "grok", "other"})
        self.model_var = tk.StringVar()
        self._row("model", ttk.Entry(p, textvariable=self.model_var, font=app.f_mono, width=40),
                  "ชื่อรุ่น เช่น gpt-5.5 / claude-sonnet-5-5 (ชนิด http: ใช้ผ่าน {model} ใน body template)",
                  types={"http", "openai-compatible", "grok", "other"}, sticky="w")
        self.sys_text = tk.Text(p, height=3, wrap="word", font=app.f_log, relief="solid", borderwidth=1)
        self._row("System prompt", self.sys_text, "ไม่บังคับ — บอกบทบาทของ AI ตัวนี้ (เว้นว่าง = ข้อความมาตรฐาน)",
                  types={"http", "openai-compatible", "grok", "other"})
        tf = ttk.Frame(p)
        self.temp_var = tk.StringVar()
        self.maxtok_var = tk.StringVar()
        ttk.Entry(tf, textvariable=self.temp_var, width=6).pack(side="left")
        ttk.Label(tf, text="   max_tokens").pack(side="left")
        ttk.Entry(tf, textvariable=self.maxtok_var, width=8).pack(side="left", padx=(6, 0))
        self._row("temperature", tf, "ไม่บังคับ — เว้นว่างได้ (บางรุ่นใหม่ไม่รองรับ temperature)",
                  types={"http", "openai-compatible", "grok", "other"}, sticky="w")

        # --- advanced
        self._section("ขั้นสูง: headers / รูปแบบข้อมูล", types={"http", "openai-compatible", "cursor", "other"})
        hf = ttk.Frame(p)
        self.hdr_box = ttk.Frame(hf)
        self.hdr_box.pack(fill="x")
        self.hdr_box.columnconfigure(0, weight=1)
        self.hdr_box.columnconfigure(1, weight=2)
        ttk.Button(hf, text="+ เพิ่ม header", command=lambda: self.add_header_row("", "")).pack(anchor="w", pady=(4, 0))
        self.hdr_rows: list[tuple[tk.StringVar, tk.StringVar, ttk.Frame]] = []
        self._row("Headers", hf, "ชื่อ / ค่า — ใช้ ${ชื่อตัวแปร} อ้างอิงค่าใน .env ได้ • ถ้าใส่กุญแจจริงในช่อง "
                                 "Authorization / *key* / *token* โปรแกรมจะย้ายไปเก็บใน .env ให้เอง",
                  types={"http", "openai-compatible", "cursor", "other"})
        bf = ttk.Frame(p)
        self.body_text = tk.Text(bf, height=7, wrap="none", font=app.f_mono, relief="solid", borderwidth=1)
        self.body_text.pack(fill="x")
        ttk.Button(bf, text="ใส่ตัวอย่าง", command=self._body_example).pack(anchor="w", pady=(4, 0))
        self._row("Body template (JSON)", bf, PLACEHOLDER_HELP, types={"http", "cursor", "other"})
        self.resp_var = tk.StringVar()
        self.resp_help = self._row("Response path", ttk.Entry(p, textvariable=self.resp_var, font=app.f_mono, width=40),
                                   "ตำแหน่งข้อความคำตอบใน JSON เช่น choices[0].message.content หรือ "
                                   "content[0].text (เว้นว่าง = เดาให้อัตโนมัติ)",
                                   types={"http", "openai-compatible", "cursor", "other"}, sticky="w")

        # --- inline test
        self._section("ทดสอบ")
        self.test_msg = tk.StringVar(value=TEST_MESSAGE)
        self._row("ข้อความทดสอบ", ttk.Entry(p, textvariable=self.test_msg))
        self.result = scrolledtext.ScrolledText(p, height=7, wrap="word", font=app.f_log, state="disabled",
                                                background="#fbfbfb", relief="solid", borderwidth=1)
        self._row("ผลลัพธ์", self.result, "กด \"ทดสอบ\" ด้านล่าง — ส่งข้อความจริง 1 ครั้งด้วยค่าที่กรอก (ยังไม่บันทึก)")
        for tag, color in (("ok", "#1e9e48"), ("err", "#d93025"), ("dim", "#5f6368")):
            self.result.tag_configure(tag, foreground=color)

    # ------------------------------------------------------------------ headers
    def add_header_row(self, k: str, v: str) -> None:
        kv, vv = tk.StringVar(value=k), tk.StringVar(value=v)
        row = ttk.Frame(self.hdr_box)
        row.pack(fill="x", pady=1)
        ttk.Entry(row, textvariable=kv, width=22, font=self.app.f_mono).pack(side="left")
        ttk.Entry(row, textvariable=vv, font=self.app.f_mono).pack(side="left", fill="x", expand=True, padx=(4, 4))
        item = (kv, vv, row)
        ttk.Button(row, text="✖", width=3, command=lambda: self._del_header(item)).pack(side="left")
        self.hdr_rows.append(item)

    def _del_header(self, item: Any) -> None:
        item[2].destroy()
        self.hdr_rows.remove(item)

    def _body_example(self) -> None:
        self.body_text.delete("1.0", "end")
        self.body_text.insert("1.0", json.dumps(BODY_EXAMPLE, indent=2, ensure_ascii=False))

    # ------------------------------------------------------------------ type helpers
    @property
    def type(self) -> str:
        label = self.type_var.get()
        for t, lbl in TYPE_CHOICES:
            if lbl == label:
                return t
        return label or "http"

    def _set_type(self, t: str) -> None:
        t = norm_type(t)
        for tt, lbl in TYPE_CHOICES:
            if tt == t:
                self.type_var.set(lbl)
                return
        # custom "module:Class" type -> keep it, show generic fields
        self.type_cb.configure(values=[lbl for _, lbl in TYPE_CHOICES] + [t])
        self.type_var.set(t)

    @property
    def auth(self) -> str:
        if self.type == "grok":
            return "bearer"
        if self.type == "opencode":
            return "basic"
        label = self.auth_var.get()
        for a, lbl in AUTH_CHOICES:
            if lbl == label:
                return a
        return "none"

    def _set_auth(self, a: str) -> None:
        for aa, lbl in AUTH_CHOICES:
            if aa == a:
                self.auth_var.set(lbl)
                return
        self.auth_var.set(AUTH_CHOICES[0][1])

    def _secret_field(self) -> str:
        return "password" if self.type == "opencode" else "api_key"

    def _default_envname(self) -> str:
        name = self.name_var.get().strip() or "agent"
        if self.type == "grok":
            return "XAI_API_KEY"
        if self.type == "opencode":
            return agent_store.env_var_name(name, "PASSWORD")
        return agent_store.env_var_name(name)

    def update_visibility(self) -> None:
        t = self.type
        tset = t if t in ALL else "other"
        auth = self.auth
        for widgets, types in self.rows:
            if "_header" in types:
                show = tset in ("http", "openai-compatible", "cursor", "other") and auth == "header"
            elif "_key" in types:
                show = t in ("grok", "opencode") or auth in ("bearer", "header")
            else:
                show = tset in types
            for wdg in widgets:
                (wdg.grid if show else wdg.grid_remove)()
        title, help_text = URL_LABEL.get(t, URL_LABEL["http"])
        self.url_title.configure(text=title)
        self.url_help.configure(text=help_text)
        self.key_title.configure(text="รหัสผ่าน opencode" if t == "opencode" else "API key")
        if not self.envname_var.get().strip() or self.envname_var.get() == getattr(self, "_auto_env", None):
            self._auto_env = self._default_envname()
            self.envname_var.set(self._auto_env)
        self._update_key_help()

    def _sync_envname(self) -> None:
        """Keep the suggested .env name in step with the agent name until the user edits it."""
        if not hasattr(self, "envname_var"):
            return
        cur = self.envname_var.get().strip()
        if not cur or cur == getattr(self, "_auto_env", None):
            self._auto_env = self._default_envname()
            self.envname_var.set(self._auto_env)

    def _update_key_help(self) -> None:
        var = self.envname_var.get().strip()
        have = bool(var and os.environ.get(var, "").strip())
        if self.type == "opencode":
            base = "ไม่บังคับ — ใส่เมื่อ opencode serve ตั้ง OPENCODE_SERVER_PASSWORD ไว้"
        else:
            base = "วางกุญแจของคุณ"
        state = (f"✔ มีค่าใน .env แล้ว ({var}) — เว้นว่าง = ใช้ค่าเดิม" if have
                 else f"ยังไม่มีค่าใน .env ({var or '-'})")
        self.key_help.configure(text=f"{base} • {state}")

    # ------------------------------------------------------------------ load / preset
    def _load(self, cfg: dict[str, Any], name: str | None) -> None:
        t = norm_type(cfg.get("type") or (name if name in ("grok", "cursor", "opencode") else "http"))
        self._set_type(t)
        self.name_var.set(name or "")
        self.enabled_var.set(bool(cfg.get("enabled", True)))
        self.desc_var.set(str(cfg.get("description") or ""))
        url_key = URL_FIELD.get(t, "url")
        self.url_var.set(str(cfg.get(url_key) or cfg.get("url") or cfg.get("base_url") or cfg.get("webhook_url") or ""))
        self.method_var.set(str(cfg.get("method") or "POST").upper())
        self.timeout_var.set("" if cfg.get("timeout") in (None, "") else str(cfg.get("timeout")))
        secret_field = "password" if t == "opencode" else "api_key"
        secret = cfg.get(secret_field)
        auth = str(cfg.get("auth_type") or ("bearer" if secret else "none")).lower()
        self._set_auth(auth)
        self.auth_header_var.set(str(cfg.get("auth_header") or "x-api-key"))
        self.key_var.set("")
        ref = agent_store.ref_name(secret) if secret else None
        self._auto_env = None
        self.envname_var.set(ref or "")
        self.model_var.set("" if isinstance(cfg.get("model"), dict) else str(cfg.get("model") or ""))
        self.sys_text.delete("1.0", "end")
        self.sys_text.insert("1.0", str(cfg.get("system_prompt") or ""))
        self.temp_var.set("" if cfg.get("temperature") is None else str(cfg.get("temperature")))
        self.maxtok_var.set("" if cfg.get("max_tokens") is None else str(cfg.get("max_tokens")))
        for item in list(self.hdr_rows):
            self._del_header(item)
        for k, v in (cfg.get("headers") or {}).items():
            self.add_header_row(str(k), "" if v is None else str(v))
        self.body_text.delete("1.0", "end")
        bt = cfg.get("body_template")
        if bt is not None and bt != "":
            self.body_text.insert("1.0", bt if isinstance(bt, str) else json.dumps(bt, indent=2, ensure_ascii=False))
        self.resp_var.set(str(cfg.get("response_path") or cfg.get("response_field") or ""))
        self.update_visibility()

    def apply_preset(self) -> None:
        label = self.preset_var.get()
        pr = next((p for p in PRESETS if p["label"] == label), None)
        if not pr:
            return
        pr = get_preset(pr["id"]) or pr
        name = self.name_var.get().strip()
        if not name or self.old_name is None:
            name = pr["name"]
            base, i = name, 2
            while name in self.existing and name != self.old_name:
                name, i = f"{base}-{i}", i + 1
        keep_key = self.key_var.get()
        cfg = dict(pr["cfg"])
        cfg["enabled"] = self.enabled_var.get()
        self._load(cfg, name)
        self.key_var.set(keep_key)
        self.preset_help.configure(text=pr["note"])
        self.key_link.configure(text=("ขอกุญแจได้ที่ " + pr["key_url"]) if pr["key_url"] else "")
        self._auto_env = self._default_envname()
        self.envname_var.set(self._auto_env)

    # ------------------------------------------------------------------ form -> cfg
    def collect(self) -> tuple[str, dict[str, Any], dict[str, str], dict[str, str]]:
        """Returns (name, raw cfg for config.yaml, typed secrets, env var names). Raises ValueError."""
        name = self.name_var.get().strip()
        err = agent_store.validate_name(name)
        if err:
            raise ValueError(err)
        if name != self.old_name and name in self.existing:
            raise ValueError(f"มี agent ชื่อ '{name}' อยู่แล้ว — ใช้ชื่ออื่น หรือกดแก้ไขตัวเดิม")
        t = self.type
        cfg: dict[str, Any] = {k: v for k, v in self.raw.items()
                               if k not in ("url", "base_url", "webhook_url", "method", "headers", "auth_type",
                                            "auth_header", "api_key", "password", "model", "system_prompt",
                                            "temperature", "max_tokens", "body_template", "response_path",
                                            "response_field", "timeout", "description", "enabled", "type")}
        cfg["type"] = t
        cfg["enabled"] = bool(self.enabled_var.get())
        cfg["description"] = self.desc_var.get().strip()
        url = self.url_var.get().strip()
        if url:
            if not (url.startswith("http://") or url.startswith("https://") or url.startswith("${")):
                raise ValueError("URL ต้องขึ้นต้นด้วย http:// หรือ https://")
            cfg[URL_FIELD.get(t, "url")] = url
        elif t in ("http", "openai-compatible", "cursor"):
            pass  # allowed (agent shows "not configured")
        tm = self.timeout_var.get().strip()
        if tm:
            try:
                cfg["timeout"] = float(tm) if "." in tm else int(tm)
                assert float(tm) > 0
            except (ValueError, AssertionError):
                raise ValueError("หมดเวลา ต้องเป็นตัวเลขวินาที มากกว่า 0")
        tset = t if t in ALL else "other"
        if tset in ("http", "cursor", "other"):
            cfg["method"] = self.method_var.get() or "POST"
        if tset in ("http", "openai-compatible", "grok", "other"):
            cfg["model"] = self.model_var.get().strip()
            sp = self.sys_text.get("1.0", "end").strip()
            if sp:
                cfg["system_prompt"] = sp
            for var, key, kind in ((self.temp_var, "temperature", float), (self.maxtok_var, "max_tokens", int)):
                v = var.get().strip()
                if v:
                    try:
                        cfg[key] = kind(v)
                    except ValueError:
                        raise ValueError(f"{key} ต้องเป็นตัวเลข")
            if isinstance(self.raw.get("model"), dict) and not cfg["model"]:
                cfg["model"] = self.raw["model"]
        if t == "opencode" and isinstance(self.raw.get("model"), dict):
            cfg["model"] = self.raw["model"]
        if tset in ("http", "openai-compatible", "cursor", "other"):
            headers = {}
            for kv, vv, _ in self.hdr_rows:
                k = kv.get().strip()
                if k:
                    if any(c in k for c in " :\r\n"):
                        raise ValueError(f"ชื่อ header '{k}' ต้องไม่มีช่องว่างหรือ :")
                    headers[k] = vv.get().strip()
            if headers:
                cfg["headers"] = headers
            rp = self.resp_var.get().strip()
            if rp:
                cfg["response_path"] = rp
        if tset in ("http", "cursor", "other"):
            bt = self.body_text.get("1.0", "end").strip()
            if bt:
                if bt[:1] in "{[":
                    try:
                        cfg["body_template"] = json.loads(bt)
                    except ValueError as exc:
                        raise ValueError(f"Body template ไม่ใช่ JSON ที่ถูกต้อง: {exc}")
                else:
                    cfg["body_template"] = bt

        # auth + secret
        secrets: dict[str, str] = {}
        env_names: dict[str, str] = {}
        auth = self.auth
        field = self._secret_field()
        envname = self.envname_var.get().strip()
        if envname and not agent_store.re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", envname):
            raise ValueError("ชื่อตัวแปรใน .env ใช้ได้เฉพาะ A-Z 0-9 _ และห้ามขึ้นต้นด้วยตัวเลข")
        typed = self.key_var.get().strip()
        if any(c in typed for c in "\r\n"):
            raise ValueError("API key ต้องเป็นบรรทัดเดียว")
        if tset in ("http", "openai-compatible", "cursor", "other"):
            cfg["auth_type"] = auth
            if auth == "header":
                cfg["auth_header"] = self.auth_header_var.get().strip() or "x-api-key"
        if auth in ("bearer", "header", "basic"):
            envname = envname or self._default_envname()
            env_names[field] = envname
            if typed:
                secrets[field] = typed
            elif auth != "basic" or os.environ.get(envname) or self.raw.get(field):
                # keep / point at the .env variable (missing value -> agent shows "ยังไม่ตั้งค่า")
                if not (t == "grok" and envname == "XAI_API_KEY" and not self.raw.get("api_key")):
                    cfg[field] = "${" + envname + "}"
        return name, cfg, secrets, env_names

    # ------------------------------------------------------------------ actions
    def _show(self, text: str, tag: str) -> None:
        r = self.result
        r.configure(state="normal")
        r.delete("1.0", "end")
        r.insert("end", text, tag)
        r.configure(state="disabled")

    def test(self) -> None:
        try:
            name, cfg, secrets, env_names = self.collect()
        except ValueError as exc:
            messagebox.showwarning(APP_NAME, str(exc), parent=self.win)
            return
        # resolved config in memory only: the typed secret is used directly, nothing is written to disk
        resolved = resolve_cfg(cfg, secrets)
        msg = self.test_msg.get().strip() or TEST_MESSAGE
        self._show("⏳ กำลังส่งข้อความทดสอบ...", "dim")
        self.sf.canvas.yview_moveto(1.0)
        start_test_thread(self.win, name, resolved, msg, self._show)

    def save(self) -> None:
        try:
            name, cfg, secrets, env_names = self.collect()
        except ValueError as exc:
            messagebox.showwarning(APP_NAME, str(exc), parent=self.win)
            return
        try:
            env_updates = agent_store.save_agent(self.app.agents_config_path(), name, cfg, old_name=self.old_name,
                                                 secrets=secrets, env_names=env_names)
        except (OSError, ValueError) as exc:
            messagebox.showerror(APP_NAME, f"บันทึกไม่สำเร็จ:\n{exc}", parent=self.win)
            return
        self.win.destroy()
        self.on_saved(name, list(env_updates))


def start_test_thread(win: tk.Misc, name: str, resolved: dict[str, Any], msg: str,
                      show: Callable[[str, str], None]) -> None:
    def work() -> None:
        ok, text, sec = run_agent_test(name, resolved, msg)
        out = (f"✔ สำเร็จ — ตอบกลับใน {sec:.2f} วินาที\n\n{text}" if ok
               else f"✖ ไม่สำเร็จ ({sec:.2f} วินาที)\n\n{text}")
        try:
            win.after(0, lambda: win.winfo_exists() and show(out, "ok" if ok else "err"))
        except (tk.TclError, RuntimeError):
            pass

    threading.Thread(target=work, name=f"test-{name}", daemon=True).start()


class TestDialog:
    """Main-window "ทดสอบ" button: send a sample message to a *saved* agent and show the reply."""

    def __init__(self, app: Any, name: str, resolved: dict[str, Any]) -> None:
        self.app, self.name, self.resolved = app, name, resolved
        self.win = w = tk.Toplevel(app.root)
        w.title(f"ทดสอบ: {name}")
        w.transient(app.root)
        f = getattr(app, "scale", 1.0)
        w.geometry(f"{int(640 * f)}x{int(420 * f)}+{app.root.winfo_rootx() + 80}+{app.root.winfo_rooty() + 80}")
        top = ttk.Frame(w, padding=10)
        top.pack(fill="x")
        ttk.Label(top, text="ข้อความ:").pack(side="left")
        self.msg = tk.StringVar(value=TEST_MESSAGE)
        ttk.Entry(top, textvariable=self.msg).pack(side="left", fill="x", expand=True, padx=6)
        self.btn = ttk.Button(top, text="ส่งอีกครั้ง", command=self.run)
        self.btn.pack(side="left")
        ttk.Button(w, text="ปิด", command=w.destroy).pack(side="bottom", pady=(0, 10))
        self.out = scrolledtext.ScrolledText(w, wrap="word", font=app.f_log, state="disabled", background="#fbfbfb")
        self.out.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        for tag, color in (("ok", "#1e9e48"), ("err", "#d93025"), ("dim", "#5f6368")):
            self.out.tag_configure(tag, foreground=color)
        w.bind("<Escape>", lambda e: w.destroy())
        self.run()

    def show(self, text: str, tag: str) -> None:
        self.out.configure(state="normal")
        self.out.delete("1.0", "end")
        self.out.insert("end", text, tag)
        self.out.configure(state="disabled")

    def run(self) -> None:
        self.show(f"⏳ กำลังส่งข้อความทดสอบไปที่ {self.name} ...", "dim")
        start_test_thread(self.win, self.name, self.resolved, self.msg.get().strip() or TEST_MESSAGE, self.show)
