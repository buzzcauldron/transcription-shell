"""Desktop GUI: single-page manuscript transcription (tkinter + tkinterdnd2 for drag-and-drop).

Run: transcriber-shell gui
Academic styling: calm paper background, readable type, minimal chrome.
"""

from __future__ import annotations

import copy
import os
import queue
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from tkinter import filedialog, scrolledtext
from tkinter import ttk
import tkinter as tk
from unittest.mock import patch

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ImportError:
    TkinterDnD = None  # type: ignore[misc, assignment]
    DND_FILES = None  # type: ignore[misc, assignment]

from transcriber_shell.config import Settings
from transcriber_shell.env_persist import merge_dotenv
from transcriber_shell.gui_state import load_gui_state, save_gui_state
from transcriber_shell.gui_discovery import format_discovery_report
from transcriber_shell.llm.model_catalog import (
    default_model_for_provider,
    merged_model_ids_for_selector,
)
from transcriber_shell.models.job import TranscribeJob
from transcriber_shell.pipeline.batch import (
    IMAGE_SUFFIXES,
    discover_images,
    has_successful_transcription,
    run_batch,
    sanitize_job_id,
)
from transcriber_shell.pipeline.run import load_prompt_cfg, run_pipeline
from transcriber_shell.pipeline.transcription_paths import transcription_yaml_path

_NONE_LABEL = "(none — use .env default)"


def _merge_llm_usage(
    acc: dict[str, int] | None, new: dict[str, int] | None
) -> dict[str, int] | None:
    """Sum token fields across batch jobs."""
    if not new:
        return acc
    if not acc:
        return dict(new)
    out = dict(acc)
    for k in ("input_tokens", "output_tokens", "total_tokens"):
        if k in new:
            out[k] = out.get(k, 0) + int(new[k])
    return out


def _format_llm_usage_line(
    u: dict[str, int] | None,
    elapsed_ms: int | None = None,
    lineation_ms: int | None = None,
) -> str:
    parts: list[str] = []
    if u:
        if "input_tokens" in u:
            parts.append(f"in {u['input_tokens']}")
        if "output_tokens" in u:
            parts.append(f"out {u['output_tokens']}")
        if "total_tokens" in u:
            parts.append(f"total {u['total_tokens']}")
    if lineation_ms is not None:
        parts.append(f"lines {lineation_ms / 1000:.1f}s")
    if elapsed_ms is not None:
        parts.append(f"llm {elapsed_ms / 1000:.1f}s")
    if not parts:
        return "Environmental impact: —"
    return "Environmental impact: " + " · ".join(parts)


# Bounded log line queue: avoids unbounded memory if a worker logs very heavily.
_GUI_LOG_QUEUE_MAXSIZE = 4_000

# Quiet academic palette (paper + ink + restrained accent)
_BG = "#f6f4ef"
_FG = "#1f1f1f"
_MUTED = "#4a4a4a"
_ACCENT = "#2f3f4f"
_FIELD_BG = "#fffcf7"
_BANNER_INFO_BG = "#e4edf5"
_BANNER_WARN_BG = "#f2ead2"
_BANNER_ERR_BG = "#edd4d4"


def _repo_fixtures_prompt() -> Path | None:
    """Best-effort default prompt path when running from a git checkout."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        p = parent / "fixtures" / "prompt.example.yaml"
        if p.is_file():
            return p
    return None


class TranscriberGui:
    def __init__(self) -> None:
        self.root = TkinterDnD.Tk() if TkinterDnD is not None else tk.Tk()
        self.root.title("Transcriber shell")
        self.root.minsize(560, 720)
        self.root.configure(bg=_BG)

        self._settings = Settings()
        self._q: queue.Queue[tuple[str, object]] = queue.Queue()
        self._log_q: queue.Queue[str] = queue.Queue(maxsize=_GUI_LOG_QUEUE_MAXSIZE)
        self._log_truncation_notified = False
        self._run_id = 0
        self._discovered_ollama: list[str] = []
        self._key_entry_widgets: list[tk.Entry] = []

        self._key_anthropic = tk.StringVar()
        self._key_openai = tk.StringVar()
        self._key_google = tk.StringVar()
        self._ollama_base_url = tk.StringVar(value="http://127.0.0.1:11434")
        # False = keys visible. True = mask with * (default on).
        self._mask_keys = tk.BooleanVar(value=True)
        self._free_only = tk.BooleanVar(value=False)

        self._image_paths: list[Path] = []
        self._prompt_path = tk.StringVar()
        self._lines_xml_path = tk.StringVar()
        self._lines_xml_dir = tk.StringVar()
        self._job_id = tk.StringVar(value="job1")
        self._provider = tk.StringVar(value=self._settings.default_provider)
        self._model_selected = tk.StringVar(value=_NONE_LABEL)
        self._efficient_mode = tk.BooleanVar(value=False)
        self._model_custom = tk.StringVar(value="")
        self._skip_gm = tk.BooleanVar(value=False)
        _lb_init = str(self._settings.lineation_backend)
        if _lb_init == "kraken":
            _lb_init = "michael-lineator"
        self._lineation_backend = tk.StringVar(value=_lb_init)
        self._xsd_path = tk.StringVar(
            value=str(self._settings.lines_xml_xsd) if self._settings.lines_xml_xsd else ""
        )
        self._require_text_line = tk.BooleanVar(value=self._settings.xml_require_text_line)
        self._skip_lines_xml_validation = tk.BooleanVar(
            value=self._settings.skip_lines_xml_validation
        )
        self._continue_on_lineation_failure = tk.BooleanVar(
            value=self._settings.continue_on_lineation_failure
        )
        self._xml_only = tk.BooleanVar(value=self._settings.xml_only)
        self._persist_keys_after_run = tk.BooleanVar(value=False)
        self._skip_successful = tk.BooleanVar(value=False)
        self._llm_use_proxy = tk.BooleanVar(value=self._settings.llm_use_proxy)
        self._llm_http_proxy = tk.StringVar(value=(self._settings.llm_http_proxy or ""))
        self._gm_persistent_profile = tk.BooleanVar(value=self._settings.gm_persistent_profile)
        self._gm_auto_install_browser = tk.BooleanVar(value=self._settings.gm_auto_install_browser)
        self._gm_user_data_dir = tk.StringVar(value=str(self._settings.gm_user_data_dir))
        self._status = tk.StringVar(value="Ready.")
        self._metrics_elapsed = tk.StringVar(value="Elapsed: —")
        self._metrics_tokens = tk.StringVar(value="LLM tokens: —")
        self._run_t0: float | None = None
        self._run_metrics_active = False
        self._banner_dismiss_after: str | None = None
        self._loading_gui_state = False
        self._save_gui_state_after: str | None = None

        self._hydrate_keys_from_settings()
        self._build_ui()
        self._poll_queue()

        # Install persistence before restore + default prompt so `trace_add` handlers exist when
        # `_prompt_path.set(...)` runs; otherwise the fixture default would not schedule a save.
        self._install_gui_state_persistence()
        self._restore_gui_state()
        default_prompt = _repo_fixtures_prompt()
        if default_prompt and not self._prompt_path.get().strip():
            self._prompt_path.set(str(default_prompt))

    # ── UI construction ──────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Main.TFrame", background=_BG)
        style.configure("TLabel", background=_BG, foreground=_FG, font=("system", 11))
        style.configure("Muted.TLabel", background=_BG, foreground=_MUTED, font=("system", 10))
        style.configure("Title.TLabel", background=_BG, foreground=_ACCENT, font=("Georgia", 18))
        style.configure("Sub.TLabel", background=_BG, foreground=_MUTED, font=("system", 11))
        style.configure("TButton", padding=(10, 6))
        style.configure("Accent.TButton", padding=(12, 8))
        style.configure("TCheckbutton", background=_BG, foreground=_FG)
        style.configure("TEntry", fieldbackground=_FIELD_BG)
        style.configure("TCombobox", fieldbackground=_FIELD_BG)

        if sys.platform == "darwin":
            self._content_font = ("system", 11)
        elif sys.platform == "win32":
            self._content_font = ("Segoe UI", 10)
        else:
            self._content_font = ("DejaVu Sans", 10)

        # Scrollable main column
        self._scroll_canvas = tk.Canvas(self.root, bg=_BG, highlightthickness=0)
        self._scroll_vsb = ttk.Scrollbar(
            self.root, orient=tk.VERTICAL, command=self._scroll_canvas.yview
        )
        self._scroll_canvas.configure(yscrollcommand=self._scroll_vsb.set)

        outer = ttk.Frame(self._scroll_canvas, padding=(16, 16, 16, 8), style="Main.TFrame")
        self._scroll_canvas_window = self._scroll_canvas.create_window(
            (0, 0), window=outer, anchor="nw"
        )

        def _on_outer_configure(_e: tk.Event) -> None:
            self._scroll_canvas.configure(scrollregion=self._scroll_canvas.bbox("all"))

        def _on_canvas_configure(e: tk.Event) -> None:
            self._scroll_canvas.itemconfigure(self._scroll_canvas_window, width=e.width)

        outer.bind("<Configure>", _on_outer_configure)
        self._scroll_canvas.bind("<Configure>", _on_canvas_configure)

        ttk.Label(outer, text="Transcriber shell", style="Title.TLabel").pack(anchor=tk.W)
        ttk.Label(
            outer,
            text="Image → lines XML (default: Glyph Machina) → LLM → <image_stem>_transcription.yaml under artifacts/",
            style="Sub.TLabel",
        ).pack(anchor=tk.W, pady=(0, 4))
        ttk.Label(
            outer,
            text=(
                "Add images and a prompt, set provider/model if needed, then Transcribe. "
                "See docs/simple-workflow.md for the short path; docs/claude.md for repo context."
            ),
            style="Muted.TLabel",
            wraplength=540,
        ).pack(anchor=tk.W, pady=(0, 8))

        self._build_keys_section(outer)
        self._build_llm_section(outer)
        self._build_images_section(outer)

        # Prompt file row
        pf = ttk.Frame(outer, style="Main.TFrame")
        pf.pack(fill=tk.X, pady=4)
        ttk.Label(pf, text="Prompt file", width=14, anchor=tk.W).pack(side=tk.LEFT)
        ttk.Entry(pf, textvariable=self._prompt_path).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8)
        )
        ttk.Button(pf, text="Browse…", command=self._browse_prompt).pack(side=tk.RIGHT)

        self._build_lineation_section(outer)
        self._build_advanced_section(outer)

        # Job ID
        job_block = ttk.Frame(outer, style="Main.TFrame")
        job_block.pack(fill=tk.X, pady=4)
        job_row = ttk.Frame(job_block, style="Main.TFrame")
        job_row.pack(fill=tk.X)
        ttk.Label(job_row, text="Job ID", width=14, anchor=tk.W).pack(side=tk.LEFT)
        self._job_entry = ttk.Entry(job_row, textvariable=self._job_id, width=24)
        self._job_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        job_hint_row = ttk.Frame(job_block, style="Main.TFrame")
        job_hint_row.pack(fill=tk.X)
        ttk.Label(job_hint_row, text="", width=14).pack(side=tk.LEFT)
        self._job_hint = ttk.Label(job_hint_row, text="", style="Muted.TLabel", wraplength=480)
        self._job_hint.pack(side=tk.LEFT, fill=tk.X, expand=True)

        ttk.Label(
            outer,
            text="Outputs: artifacts/<job_id>/  ·  .env still used when fields above are empty.",
            style="Muted.TLabel",
        ).pack(anchor=tk.W, pady=(4, 4))

        self._build_log_section(outer)

        # Bottom bar
        bottom_bar = ttk.Frame(self.root, padding=(16, 10, 16, 14), style="Main.TFrame")

        self._banner_outer = tk.Frame(
            self.root, bd=0, highlightthickness=1, highlightbackground="#b8b0a8"
        )
        self._banner_inner = tk.Frame(self._banner_outer)
        self._banner_label = tk.Label(
            self._banner_inner,
            text="",
            wraplength=540,
            justify=tk.LEFT,
            anchor=tk.W,
            font=self._content_font,
        )
        self._banner_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(self._banner_inner, text="Dismiss", command=self._gui_notify_clear).pack(
            side=tk.RIGHT, padx=(10, 0)
        )
        self._banner_inner.pack(fill=tk.X, padx=14, pady=8)

        eff_bottom = ttk.Frame(bottom_bar, style="Main.TFrame")
        eff_bottom.pack(fill=tk.X, pady=(0, 6))
        ttk.Checkbutton(
            eff_bottom,
            text="Efficient mode (protocol §2.9 — single pass, core tokens only)",
            variable=self._efficient_mode,
        ).pack(side=tk.LEFT)
        ttk.Label(
            eff_bottom,
            text="Sets runMode: efficient on the prompt for this run.",
            style="Muted.TLabel",
        ).pack(side=tk.LEFT, padx=(12, 0))
        btn_row = ttk.Frame(bottom_bar, style="Main.TFrame")
        btn_row.pack(fill=tk.X)
        ttk.Checkbutton(
            btn_row,
            text="XML only (lines XML; no LLM)",
            variable=self._xml_only,
        ).pack(side=tk.LEFT, padx=(0, 12))
        ttk.Button(
            btn_row,
            text="Transcribe",
            style="Accent.TButton",
            command=self._run,
        ).pack(side=tk.LEFT)
        ttk.Button(btn_row, text="Open artifacts folder", command=self._open_artifacts).pack(
            side=tk.LEFT, padx=(12, 0)
        )
        ttk.Button(btn_row, text="HTTP API docs (browser)", command=self._open_api_docs).pack(
            side=tk.LEFT, padx=(12, 0)
        )
        ttk.Button(btn_row, text="Save log…", command=self._save_run_log).pack(side=tk.RIGHT)
        prog_row = ttk.Frame(bottom_bar, style="Main.TFrame")
        prog_row.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(prog_row, textvariable=self._status, style="Muted.TLabel").pack(
            side=tk.LEFT, anchor=tk.W
        )
        ttk.Label(prog_row, textvariable=self._metrics_tokens, style="Muted.TLabel").pack(
            side=tk.RIGHT, padx=(16, 0)
        )
        ttk.Label(prog_row, textvariable=self._metrics_elapsed, style="Muted.TLabel").pack(
            side=tk.RIGHT
        )

        bottom_bar.pack(side=tk.BOTTOM, fill=tk.X)
        self._scroll_vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._scroll_canvas.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self._setup_main_canvas_mousewheel()
        self._refresh_model_combos()
        self._refresh_image_list()
        self._refresh_ui_state()

    def _build_keys_section(self, outer: ttk.Frame) -> None:
        cred = ttk.LabelFrame(outer, text="Provider keys (LLM)", padding=(10, 8))
        cred.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(
            cred,
            text="Anthropic / OpenAI / Gemini keys for transcription, or leave empty to use .env.",
            style="Muted.TLabel",
        ).pack(anchor=tk.W, pady=(0, 6))

        def key_row(label: str, var: tk.StringVar) -> None:
            f = ttk.Frame(cred, style="Main.TFrame")
            f.pack(fill=tk.X, pady=3)
            ttk.Label(f, text=label, width=14, anchor=tk.W).pack(side=tk.LEFT)
            show = "*" if self._mask_keys.get() else ""
            # tk.Entry (not ttk): Cmd/Ctrl+V paste is reliable on macOS/Windows; ttk.Entry often breaks paste.
            e = tk.Entry(
                f,
                textvariable=var,
                show=show,
                bg=_FIELD_BG,
                fg=_FG,
                insertbackground=_FG,
                relief=tk.FLAT,
                borderwidth=1,
                highlightthickness=1,
                highlightbackground="#c8c4bc",
                highlightcolor=_ACCENT,
                font=self._content_font,
            )
            e.pack(side=tk.LEFT, fill=tk.X, expand=True)
            self._key_entry_widgets.append(e)

        key_row("Anthropic", self._key_anthropic)
        key_row("OpenAI", self._key_openai)
        key_row("Google (Gemini)", self._key_google)

        olf = ttk.Frame(cred, style="Main.TFrame")
        olf.pack(fill=tk.X, pady=(4, 2))
        ttk.Label(olf, text="Ollama URL", width=14, anchor=tk.W).pack(side=tk.LEFT)
        ttk.Entry(olf, textvariable=self._ollama_base_url).pack(
            side=tk.LEFT, fill=tk.X, expand=True
        )

        optf = ttk.Frame(cred, style="Main.TFrame")
        optf.pack(fill=tk.X, pady=(4, 0))
        ttk.Checkbutton(
            optf,
            text="Mask keys",
            variable=self._mask_keys,
            command=self._toggle_key_visibility,
        ).pack(side=tk.LEFT)

        save_row = ttk.Frame(cred, style="Main.TFrame")
        save_row.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(save_row, text="Save keys to .env", command=self._save_keys_to_dotenv).pack(
            side=tk.LEFT
        )
        ttk.Checkbutton(
            save_row,
            text="Also save keys to .env after a successful run",
            variable=self._persist_keys_after_run,
        ).pack(side=tk.LEFT, padx=(12, 0))
        ttk.Checkbutton(
            save_row,
            text="Skip jobs that already have a successful transcription",
            variable=self._skip_successful,
        ).pack(side=tk.LEFT, padx=(12, 0))
        ttk.Label(
            cred,
            text="Writes to .env in the process working directory (usually the repo root). Do not commit .env.",
            style="Muted.TLabel",
            wraplength=480,
        ).pack(anchor=tk.W, pady=(4, 0))

        def _key_var_trace(*_a: object) -> None:
            self._sanitize_key_stringvars_on_write()
            self._on_credentials_changed()

        for _kv in (self._key_anthropic, self._key_openai, self._key_google):
            _kv.trace_add("write", _key_var_trace)
        self._bind_key_entry_clipboard_shortcuts()

        if self._key_entry_widgets:
            self._key_entry_widgets[0].focus_set()

    def _build_llm_section(self, outer: ttk.Frame) -> None:
        disc_row = ttk.Frame(outer, style="Main.TFrame")
        disc_row.pack(fill=tk.X, pady=(0, 4))
        ttk.Button(
            disc_row, text="Scan for Ollama / local tools", command=self._discover
        ).pack(side=tk.LEFT)
        ttk.Label(
            outer,
            text="Optional HTTP API: run transcriber-shell serve, then open HTTP API docs below.",
            style="Muted.TLabel",
            wraplength=520,
        ).pack(anchor=tk.W, pady=(0, 8))

        llm = ttk.LabelFrame(outer, text="LLM (provider & model)", padding=(10, 8))
        llm.pack(fill=tk.X, pady=(0, 10))
        ttk.Checkbutton(
            llm,
            text="Budget models only (cloud)",
            variable=self._free_only,
            command=self._refresh_model_combos,
        ).pack(anchor=tk.W, pady=(0, 6))

        prov_row = ttk.Frame(llm, style="Main.TFrame")
        prov_row.pack(fill=tk.X, pady=4)
        ttk.Label(prov_row, text="Provider", width=14, anchor=tk.W).pack(side=tk.LEFT)
        self._cb_provider = ttk.Combobox(
            prov_row,
            textvariable=self._provider,
            values=("anthropic", "openai", "gemini", "ollama"),
            state="readonly",
            width=18,
        )
        self._cb_provider.pack(side=tk.LEFT, padx=(0, 8))
        self._cb_provider.bind("<<ComboboxSelected>>", self._refresh_model_combos)

        model_row = ttk.Frame(llm, style="Main.TFrame")
        model_row.pack(fill=tk.X, pady=4)
        ttk.Label(model_row, text="Model", width=14, anchor=tk.W).pack(side=tk.LEFT)
        self._cb_model = ttk.Combobox(
            model_row,
            textvariable=self._model_selected,
            state="readonly",
            width=52,
        )
        self._cb_model.pack(side=tk.LEFT, fill=tk.X, expand=True)

        cust_row = ttk.Frame(llm, style="Main.TFrame")
        cust_row.pack(fill=tk.X, pady=4)
        ttk.Label(cust_row, text="Custom model id", width=14, anchor=tk.W).pack(side=tk.LEFT)
        self._model_custom_entry = ttk.Entry(cust_row, textvariable=self._model_custom, width=40)
        self._model_custom_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self._llm_credentials_hint = ttk.Label(llm, text="", style="Muted.TLabel", wraplength=500)
        self._llm_credentials_hint.pack(anchor=tk.W, pady=(4, 0))

        ttk.Label(
            llm,
            text=(
                "Custom model id, if set, overrides the dropdown. Controls are disabled until a key is available."
            ),
            style="Muted.TLabel",
            wraplength=500,
        ).pack(anchor=tk.W, pady=(6, 0))

    def _build_images_section(self, outer: ttk.Frame) -> None:
        img_frame = ttk.LabelFrame(outer, text="Page images", padding=(8, 6))
        img_frame.pack(fill=tk.BOTH, pady=(0, 4))
        self._image_count_label = ttk.Label(img_frame, text="0 image(s)", style="Muted.TLabel")
        self._image_count_label.pack(anchor=tk.W)
        ttk.Label(
            img_frame,
            text=(
                "Drag image files or a folder onto the list below (same rules as Add files… / Add folder…)."
                if DND_FILES is not None
                else "Install tkinterdnd2 (declared dependency) to drag files or folders onto the list."
            ),
            style="Muted.TLabel",
            wraplength=520,
        ).pack(anchor=tk.W, pady=(0, 2))
        # Pack the button row at the BOTTOM first so the expanding list cannot compress it vertically.
        img_btns = ttk.Frame(img_frame, style="Main.TFrame")
        img_btns.pack(side=tk.BOTTOM, fill=tk.X, pady=(6, 0))
        ttk.Button(img_btns, text="Add files…", command=self._add_image_files).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(img_btns, text="Add folder…", command=self._add_image_folder).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(img_btns, text="Remove selected", command=self._remove_selected_images).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(img_btns, text="Clear all", command=self._clear_images).pack(side=tk.LEFT)

        list_fr = ttk.Frame(img_frame, style="Main.TFrame")
        list_fr.pack(fill=tk.BOTH, expand=True, pady=(4, 4))
        self._image_listbox = tk.Listbox(
            list_fr,
            height=5,
            font=self._content_font,
            bg=_FIELD_BG,
            fg=_FG,
            selectmode=tk.EXTENDED,
            relief=tk.FLAT,
        )
        self._image_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(list_fr, orient=tk.VERTICAL, command=self._image_listbox.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._image_listbox.configure(yscrollcommand=sb.set)
        self._setup_image_drop_target()

    def _build_lineation_section(self, outer: ttk.Frame) -> None:
        lineation_src = ttk.LabelFrame(outer, text="Lineation source", padding=(8, 6))
        lineation_src.pack(fill=tk.X, pady=(4, 6))
        lb_row = ttk.Frame(lineation_src, style="Main.TFrame")
        lb_row.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(lb_row, text="Draw baselines", width=14, anchor=tk.W).pack(side=tk.LEFT)
        self._lineation_combo = ttk.Combobox(
            lb_row,
            textvariable=self._lineation_backend,
            values=("michael-lineator", "glyph_machina", "mask"),
            state="readonly",
            width=22,
        )
        self._lineation_combo.pack(side=tk.LEFT)
        self._lineation_combo.bind("<<ComboboxSelected>>", self._on_lineation_backend_changed)
        self._lineation_backend_hint = ttk.Label(
            lineation_src,
            text="",
            style="Muted.TLabel",
            wraplength=520,
        )
        self._lineation_backend_hint.pack(anchor=tk.W, pady=(0, 6))
        ttk.Checkbutton(
            lineation_src,
            text="Skip automated lineation — use existing lines XML from disk (no browser)",
            variable=self._skip_gm,
            command=self._toggle_skip_gm,
        ).pack(anchor=tk.W)
        ttk.Label(
            lineation_src,
            text=(
                "Unchecked: run the selected backend. "
                "Checked: set Lines XML file/dir below — no automated lineation."
            ),
            style="Muted.TLabel",
            wraplength=500,
        ).pack(anchor=tk.W, pady=(6, 0))

        lines_row = ttk.Frame(outer, style="Main.TFrame")
        lines_row.pack(fill=tk.X, pady=4)
        ttk.Label(lines_row, text="Lines XML file", width=14, anchor=tk.W).pack(side=tk.LEFT)
        self._lines_entry = ttk.Entry(
            lines_row, textvariable=self._lines_xml_path, state="disabled"
        )
        self._lines_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        self._lines_btn = ttk.Button(
            lines_row, text="Browse…", command=self._browse_lines, state="disabled"
        )
        self._lines_btn.pack(side=tk.RIGHT)

        lines_dir_row = ttk.Frame(outer, style="Main.TFrame")
        lines_dir_row.pack(fill=tk.X, pady=4)
        ttk.Label(lines_dir_row, text="Lines XML dir", width=14, anchor=tk.W).pack(side=tk.LEFT)
        self._lines_dir_entry = ttk.Entry(
            lines_dir_row, textvariable=self._lines_xml_dir, state="disabled"
        )
        self._lines_dir_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        self._lines_dir_btn = ttk.Button(
            lines_dir_row, text="Browse…", command=self._browse_lines_dir, state="disabled"
        )
        self._lines_dir_btn.pack(side=tk.RIGHT)

        self._lines_help = ttk.Label(outer, text="", style="Muted.TLabel", wraplength=520)
        self._lines_help.pack(anchor=tk.W, pady=(0, 2))

    def _build_advanced_section(self, outer: ttk.Frame) -> None:
        """Always-visible advanced settings: proxy, Chromium profile, XML validation."""
        self._advanced_content = ttk.Frame(outer, style="Main.TFrame")
        self._advanced_content.pack(fill=tk.X, pady=(4, 0))

        # Network / proxy subsection
        net = ttk.LabelFrame(
            self._advanced_content,
            text="Network & proxy (LLM APIs) — Glyph Machina browser settings",
            padding=(10, 8),
        )
        net.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(
            net,
            text=(
                "HTTP proxy below applies to cloud LLM calls (Anthropic/OpenAI/Gemini). "
                "Chromium profile applies only when lineation backend is Glyph Machina and skip is off."
            ),
            style="Muted.TLabel",
            wraplength=520,
        ).pack(anchor=tk.W, pady=(0, 6))
        ttk.Checkbutton(
            net,
            text="Route LLM API calls through HTTP proxy",
            variable=self._llm_use_proxy,
        ).pack(anchor=tk.W)
        pxf = ttk.Frame(net, style="Main.TFrame")
        pxf.pack(fill=tk.X, pady=(4, 0))
        ttk.Label(pxf, text="Proxy URL", width=14, anchor=tk.W).pack(side=tk.LEFT)
        show_px = "*" if self._mask_keys.get() else ""
        self._proxy_entry = tk.Entry(
            pxf,
            textvariable=self._llm_http_proxy,
            show=show_px,
            bg=_FIELD_BG,
            fg=_FG,
            insertbackground=_FG,
            relief=tk.FLAT,
            borderwidth=1,
            highlightthickness=1,
            highlightbackground="#c8c4bc",
            highlightcolor=_ACCENT,
            font=self._content_font,
        )
        self._proxy_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._key_entry_widgets.append(self._proxy_entry)
        ttk.Label(
            net,
            text="Anthropic/OpenAI use httpx; Gemini uses HTTP(S)_PROXY for the request. Ollama (local) is unchanged.",
            style="Muted.TLabel",
            wraplength=500,
        ).pack(anchor=tk.W, pady=(6, 0))
        self._gm_auto_install_check = ttk.Checkbutton(
            net,
            text=(
                "Auto-install Playwright Chromium before first browser session "
                "(python -m playwright install chromium; env TRANSCRIBER_SHELL_GM_AUTO_INSTALL_BROWSER)"
            ),
            variable=self._gm_auto_install_browser,
        )
        self._gm_auto_install_check.pack(anchor=tk.W, pady=(8, 0))
        self._gm_profile_check = ttk.Checkbutton(
            net,
            text="Persistent Chromium profile for Glyph Machina lineation (keep site login/cookies between runs)",
            variable=self._gm_persistent_profile,
        )
        self._gm_profile_check.pack(anchor=tk.W, pady=(8, 0))
        gmdf = ttk.Frame(net, style="Main.TFrame")
        gmdf.pack(fill=tk.X, pady=(4, 0))
        ttk.Label(gmdf, text="Profile dir", width=14, anchor=tk.W).pack(side=tk.LEFT)
        self._gm_user_data_entry = ttk.Entry(gmdf, textvariable=self._gm_user_data_dir)
        self._gm_user_data_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        self._gm_profile_browse_btn = ttk.Button(
            gmdf, text="Browse…", command=self._browse_gm_profile_dir
        )
        self._gm_profile_browse_btn.pack(side=tk.RIGHT)
        self._gm_profile_hint = ttk.Label(
            net,
            text="",
            style="Muted.TLabel",
            wraplength=500,
        )
        self._gm_profile_hint.pack(anchor=tk.W, pady=(4, 0))

        # Validation subsection
        val = ttk.LabelFrame(self._advanced_content, text="XML validation", padding=(10, 8))
        val.pack(fill=tk.X, pady=(8, 0))
        xsd_row = ttk.Frame(val, style="Main.TFrame")
        xsd_row.pack(fill=tk.X, pady=4)
        ttk.Label(xsd_row, text="PAGE XSD (opt.)", width=14, anchor=tk.W).pack(side=tk.LEFT)
        ttk.Entry(xsd_row, textvariable=self._xsd_path).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8)
        )
        ttk.Button(xsd_row, text="Browse…", command=self._browse_xsd).pack(side=tk.RIGHT)
        ttk.Label(
            val,
            text="Optional: validate lines XML against a PAGE XSD (install pip extra [xml-xsd] for lxml). Leave empty to skip.",
            style="Muted.TLabel",
            wraplength=520,
        ).pack(anchor=tk.W, pady=(0, 2))
        req_tl_row = ttk.Frame(val, style="Main.TFrame")
        req_tl_row.pack(fill=tk.X, pady=2)
        ttk.Label(req_tl_row, text="", width=14).pack(side=tk.LEFT)
        ttk.Checkbutton(
            req_tl_row,
            text="Require ≥1 TextLine in lines XML (off = CLI --no-require-text-line)",
            variable=self._require_text_line,
        ).pack(side=tk.LEFT)
        skip_xml_row = ttk.Frame(val, style="Main.TFrame")
        skip_xml_row.pack(fill=tk.X, pady=2)
        ttk.Label(skip_xml_row, text="", width=14).pack(side=tk.LEFT)
        ttk.Checkbutton(
            skip_xml_row,
            text="Skip lines XML validation (no checks / XSD before LLM; CLI --skip-lines-xml-validation)",
            variable=self._skip_lines_xml_validation,
        ).pack(side=tk.LEFT)
        cont_line_row = ttk.Frame(val, style="Main.TFrame")
        cont_line_row.pack(fill=tk.X, pady=2)
        ttk.Label(cont_line_row, text="", width=14).pack(side=tk.LEFT)
        ttk.Checkbutton(
            cont_line_row,
            text=(
                "Continue without lines XML if lineation fails (Glyph Machina / mask / Kraken / timeouts; "
                "CLI --continue-on-lineation-failure)"
            ),
            variable=self._continue_on_lineation_failure,
        ).pack(side=tk.LEFT)

    def _build_log_section(self, outer: ttk.Frame) -> None:
        log_head = ttk.Frame(outer, style="Main.TFrame")
        log_head.pack(fill=tk.X, pady=(4, 0))
        ttk.Label(log_head, text="Run log", style="Muted.TLabel").pack(side=tk.LEFT)
        ttk.Label(
            outer,
            text=(
                "Not saved automatically. Use Save log… or copy/paste. Outputs go to artifacts/<job_id>/."
            ),
            style="Muted.TLabel",
            wraplength=520,
        ).pack(anchor=tk.W, pady=(0, 2))

        self._log = scrolledtext.ScrolledText(
            outer,
            height=12,
            wrap=tk.WORD,
            font=self._content_font,
            bg=_FIELD_BG,
            fg=_FG,
            insertbackground=_FG,
            relief=tk.FLAT,
            padx=8,
            pady=8,
        )
        self._log.pack(fill=tk.BOTH, expand=True)


    # ── UI state sync ────────────────────────────────────────────────────────

    def _refresh_ui_state(self) -> None:
        """Single pass: read all relevant state, update all dependent widgets."""
        n = len(self._dedupe_sorted_images())
        skip = self._skip_gm.get()
        backend = self._lineation_backend.get().strip().lower()
        gm_ok = not skip and backend == "glyph_machina"

        # Lines XML / lineation combo / job entry
        if not skip:
            self._lineation_combo.configure(state="readonly")
            self._lines_entry.configure(state="disabled")
            self._lines_btn.configure(state="disabled")
            self._lines_dir_entry.configure(state="disabled")
            self._lines_dir_btn.configure(state="disabled")
            self._lines_help.configure(text="")
            self._job_entry.configure(state="normal")
            self._job_hint.configure(text="")
        else:
            self._lineation_combo.configure(state="disabled")
            if n <= 1:
                self._lines_entry.configure(state="normal")
                self._lines_btn.configure(state="normal")
                self._lines_dir_entry.configure(state="normal")
                self._lines_dir_btn.configure(state="normal")
                self._lines_help.configure(
                    text="One image: set Lines XML file, or Lines XML dir containing <stem>.xml. "
                    "Multiple images: set Lines XML dir only (one .xml per image stem)."
                )
            else:
                self._lines_entry.configure(state="disabled")
                self._lines_btn.configure(state="disabled")
                self._lines_dir_entry.configure(state="normal")
                self._lines_dir_btn.configure(state="normal")
                self._lines_help.configure(
                    text="Batch + skip lineation: choose Lines XML dir with one <image_stem>.xml per page."
                )
            if n <= 1:
                self._job_entry.configure(state="normal")
                self._job_hint.configure(text="")
            else:
                self._job_entry.configure(state="disabled")
                self._job_hint.configure(text="Batch uses each filename as job id.")

        # Lineation backend hint
        kraken_model = str(self._settings.kraken_model_path or "").strip()
        kraken_model_label = kraken_model.split("/")[-1] if kraken_model else ""
        if skip:
            self._lineation_backend_hint.configure(
                text="Baseline detection is skipped — supply an existing lines XML below."
            )
        elif backend == "mask":
            self._lineation_backend_hint.configure(
                text=(
                    "Mask (custom plugin): runs your own model to detect baselines. "
                    "Set TRANSCRIBER_SHELL_MASK_INFERENCE_CALLABLE in .env — see docs/mask-lineation-plugin.md."
                )
            )
        elif backend == "michael-lineator":
            if kraken_model_label:
                self._lineation_backend_hint.configure(
                    text=f"Michael Lineator (local model): detects baselines using {kraken_model_label}."
                )
            else:
                self._lineation_backend_hint.configure(
                    text=(
                        "Michael Lineator (local model): detects baselines offline. "
                        "Set TRANSCRIBER_SHELL_KRAKEN_MODEL_PATH in .env."
                    )
                )
        else:
            self._lineation_backend_hint.configure(
                text=(
                    "Glyph Machina (cloud): opens a browser and uploads the image to glyphmachina.com "
                    "to detect baselines. Requires internet and a site login; "
                    "use TRANSCRIBER_SHELL_GM_HEADLESS=false to log in once."
                )
            )

        # Glyph Machina profile controls (in Advanced section)
        st = "normal" if gm_ok else "disabled"
        self._gm_auto_install_check.configure(state=st)
        self._gm_profile_check.configure(state=st)
        self._gm_user_data_entry.configure(state=st)
        self._gm_profile_browse_btn.configure(state=st)
        if gm_ok:
            self._gm_profile_hint.configure(
                text="Avoid parallel runs sharing one profile directory."
            )
        else:
            self._gm_profile_hint.configure(
                text=(
                    "Only when lineation backend is Glyph Machina and automated lineation is on. "
                    "Not used for mask or Kraken lineation."
                )
            )

        # LLM model / credentials
        ok = self._provider_has_llm_credentials()
        st_llm = "readonly" if ok else "disabled"
        self._cb_model.configure(state=st_llm)
        self._model_custom_entry.configure(state="normal" if ok else "disabled")
        p = self._provider.get().lower().strip()
        if p == "ollama" or ok:
            self._llm_credentials_hint.configure(text="")
        else:
            self._llm_credentials_hint.configure(
                text=(
                    "Enter a provider key above or set .env to enable Model and Custom model id."
                )
            )

    # Thin wrappers kept for call-site compatibility during transition.
    def _sync_lines_xml_ui(self) -> None:
        self._refresh_ui_state()

    def _sync_gm_profile_controls(self) -> None:
        self._refresh_ui_state()

    def _sync_model_credentials_state(self) -> None:
        self._refresh_ui_state()

    def _refresh_lineation_hints(self) -> None:
        self._refresh_ui_state()

    def _on_lineation_backend_changed(self, _event: object | None = None) -> None:
        self._refresh_ui_state()

    def _toggle_skip_gm(self) -> None:
        self._refresh_ui_state()

    # ── Mousewheel routing ───────────────────────────────────────────────────

    def _widget_tree_contains(self, w: tk.Misc, ancestor: tk.Misc) -> bool:
        cur: tk.Misc | None = w
        while cur is not None:
            if cur == ancestor:
                return True
            cur = cur.master  # type: ignore[assignment]
        return False

    def _setup_main_canvas_mousewheel(self) -> None:
        """Route wheel to the main canvas; keep native scroll for log + image list.

        Global bind_all alone lets ``ttk.Combobox`` eat the wheel (cycles model/provider), which feels
        like the form is not scrolling — stop that with ``return 'break'`` on TCombobox.
        """

        def _scroll_main(e: tk.Event) -> None:
            if sys.platform == "darwin":
                self._scroll_canvas.yview_scroll(-1 * int(e.delta), "units")
            else:
                self._scroll_canvas.yview_scroll(-1 * int(e.delta / 120), "units")

        def _native_scroll_widget(w: tk.Widget) -> bool:
            """True for widgets that should keep their own native scroll."""
            if self._widget_tree_contains(w, self._log):
                return True
            if self._widget_tree_contains(w, self._image_listbox):
                return True
            return False

        def on_wheel(e: tk.Event) -> str | None:
            if _native_scroll_widget(e.widget):
                return None
            _scroll_main(e)
            return "break"

        def on_btn4(e: tk.Event) -> str | None:
            if _native_scroll_widget(e.widget):
                return None
            self._scroll_canvas.yview_scroll(-3, "units")
            return "break"

        def on_btn5(e: tk.Event) -> str | None:
            if _native_scroll_widget(e.widget):
                return None
            self._scroll_canvas.yview_scroll(3, "units")
            return "break"

        self.root.bind_all("<MouseWheel>", on_wheel)
        if sys.platform == "linux":
            self.root.bind_all("<Button-4>", on_btn4)
            self.root.bind_all("<Button-5>", on_btn5)

    # ── Banner notifications ──────────────────────────────────────────────────

    def _gui_notify_clear(self) -> None:
        if self._banner_dismiss_after is not None:
            try:
                self.root.after_cancel(self._banner_dismiss_after)
            except (tk.TclError, ValueError):
                pass
            self._banner_dismiss_after = None
        self._banner_outer.pack_forget()

    def _gui_notify(
        self,
        text: str,
        kind: str = "info",
        *,
        auto_dismiss_ms: int | None = None,
    ) -> None:
        """Show a message in the banner above the bottom bar (replaces modal messagebox)."""
        if auto_dismiss_ms is None:
            if kind == "error":
                auto_dismiss_ms = 0
            elif kind == "warning":
                auto_dismiss_ms = 14_000
            else:
                auto_dismiss_ms = 10_000
        if self._banner_dismiss_after is not None:
            try:
                self.root.after_cancel(self._banner_dismiss_after)
            except (tk.TclError, ValueError):
                pass
            self._banner_dismiss_after = None

        bg = {"info": _BANNER_INFO_BG, "warning": _BANNER_WARN_BG, "error": _BANNER_ERR_BG}.get(
            kind, _BANNER_INFO_BG
        )
        hi = {"info": "#a8b8c8", "warning": "#c4b898", "error": "#c89898"}.get(kind, "#a8b8c8")
        self._banner_outer.configure(bg=bg, highlightbackground=hi)
        self._banner_inner.configure(bg=bg)
        if len(text) > 12_000:
            text = text[:12_000] + "\n\n… (message truncated)"
        self._banner_label.configure(text=text, bg=bg, fg=_FG)

        self._banner_outer.pack(side=tk.BOTTOM, fill=tk.X)
        if auto_dismiss_ms and auto_dismiss_ms > 0:
            self._banner_dismiss_after = self.root.after(
                auto_dismiss_ms, self._gui_notify_clear
            )

    # ── Image list management ─────────────────────────────────────────────────

    def _dedupe_sorted_images(self) -> list[Path]:
        seen: set[str] = set()
        out: list[Path] = []
        for p in sorted(self._image_paths, key=lambda x: str(x).lower()):
            key = str(p.resolve())
            if key not in seen:
                seen.add(key)
                out.append(p)
        return out

    def _refresh_image_list(self) -> None:
        self._image_paths = self._dedupe_sorted_images()
        self._image_listbox.delete(0, tk.END)
        for p in self._image_paths:
            self._image_listbox.insert(tk.END, str(p))
        n = len(self._image_paths)
        self._image_count_label.configure(text=f"{n} image(s)")
        self._refresh_ui_state()
        self._schedule_gui_state_save()

    def _setup_image_drop_target(self) -> None:
        if DND_FILES is None:
            return

        def on_drop(event: tk.Event) -> None:
            data = getattr(event, "data", "") or ""
            try:
                raw = self.root.tk.splitlist(data)
            except tk.TclError:
                raw = []
            if not raw:
                return
            self._ingest_paths([Path(s) for s in raw], show_empty_warning=False)

        self._image_listbox.drop_target_register(DND_FILES)
        self._image_listbox.dnd_bind("<<Drop>>", on_drop)

    def _ingest_paths(self, items: list[Path], *, show_empty_warning: bool = True) -> None:
        """Add files or top-level images from folders; dedupe by resolved path."""
        before = len(self._image_paths)
        existing = {x.resolve() for x in self._image_paths}
        added_any = False
        for p in items:
            try:
                p = p.expanduser()
                if not p.exists():
                    continue
            except OSError:
                continue
            if p.is_file():
                if p.suffix.lower() not in IMAGE_SUFFIXES:
                    continue
                rp = p.resolve()
                if rp not in existing:
                    self._image_paths.append(p)
                    existing.add(rp)
                    added_any = True
                    if before == 0 and len(self._image_paths) == 1:
                        self._job_id.set(p.stem[:120] or "job")
            elif p.is_dir():
                for p2 in discover_images(str(p)):
                    r2 = p2.resolve()
                    if r2 not in existing:
                        self._image_paths.append(p2)
                        existing.add(r2)
                        added_any = True
                        if before == 0 and len(self._image_paths) == 1:
                            self._job_id.set(p2.stem[:120] or "job")
        if added_any:
            self._refresh_image_list()
        elif show_empty_warning and items:
            self._gui_notify(
                "Add images: No supported images were added. Use jpg, jpeg, png, webp, tif/tiff, gif, or bmp, "
                "or a folder whose top-level files include those types (subfolders are not scanned).",
                "info",
            )

    def _add_image_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Pre-cropped page images",
            filetypes=[
                ("Images", "*.jpg *.jpeg *.png *.webp *.tif *.tiff *.bmp"),
                ("All", "*.*"),
            ],
        )
        if not paths:
            return
        self._ingest_paths([Path(s) for s in paths], show_empty_warning=True)

    def _add_image_folder(self) -> None:
        d = filedialog.askdirectory(title="Folder containing page images")
        if not d:
            return
        found = discover_images(d)
        if not found:
            self._gui_notify(
                "Add folder: That folder has no supported images in its top level (jpg, png, webp, etc.). "
                "Subfolders are not scanned.",
                "info",
            )
            return
        self._ingest_paths([Path(d)], show_empty_warning=False)

    def _remove_selected_images(self) -> None:
        sel = list(self._image_listbox.curselection())
        if not sel:
            return
        for i in reversed(sel):
            if 0 <= i < len(self._image_paths):
                del self._image_paths[i]
        self._refresh_image_list()

    def _clear_images(self) -> None:
        self._image_paths.clear()
        self._refresh_image_list()

    # ── Key entry helpers ─────────────────────────────────────────────────────

    def _sanitize_key_stringvars_on_write(self) -> None:
        """Strip newlines from pasted keys (password managers often add trailing \\n)."""
        if getattr(self, "_suppress_key_sanitize", False):
            return
        for var in (self._key_anthropic, self._key_openai, self._key_google):
            v = var.get()
            n = v.replace("\n", "").replace("\r", "")
            if n != v:
                self._suppress_key_sanitize = True
                try:
                    var.set(n)
                finally:
                    self._suppress_key_sanitize = False

    def _bind_key_entry_clipboard_shortcuts(self) -> None:
        """Explicit paste: tk.Entry helps macOS; Command-v/<<Paste>> sometimes both fire — debounce."""

        def paste_clipboard(event: tk.Event) -> str:
            w = event.widget
            if w not in self._key_entry_widgets:
                return ""
            now = time.monotonic()
            wid = id(w)
            last = self._key_paste_last_mono.get(wid, 0.0)
            if now - last < 0.06:
                return "break"
            self._key_paste_last_mono[wid] = now
            try:
                clip = self.root.clipboard_get()
            except tk.TclError:
                return "break"
            clip = clip.strip().replace("\n", "").replace("\r", "")
            if not clip:
                return "break"
            try:
                if w.selection_present():
                    w.delete("sel.first", "sel.last")
                w.insert("insert", clip)
            except tk.TclError:
                return "break"
            return "break"

        self._key_paste_last_mono: dict[int, float] = {}
        for e in self._key_entry_widgets:
            e.bind("<<Paste>>", paste_clipboard, add=True)
            e.bind("<Command-v>", paste_clipboard)
            e.bind("<Control-v>", paste_clipboard)
            e.bind("<Shift-Insert>", paste_clipboard)

    def _hydrate_keys_from_settings(self) -> None:
        s = self._settings
        if s.anthropic_api_key:
            self._key_anthropic.set(s.anthropic_api_key)
        if s.openai_api_key:
            self._key_openai.set(s.openai_api_key)
        if s.google_api_key:
            self._key_google.set(s.google_api_key)
        u = (s.ollama_base_url or "").strip()
        if u:
            self._ollama_base_url.set(u)

    def _toggle_key_visibility(self) -> None:
        show = "*" if self._mask_keys.get() else ""
        for e in self._key_entry_widgets:
            e.configure(show=show)

    # ── .env persistence ──────────────────────────────────────────────────────

    def _env_persist_dict(self) -> dict[str, str]:
        return {
            "ANTHROPIC_API_KEY": self._key_anthropic.get().strip(),
            "OPENAI_API_KEY": self._key_openai.get().strip(),
            "GOOGLE_API_KEY": self._key_google.get().strip(),
            "TRANSCRIBER_SHELL_OLLAMA_BASE_URL": self._ollama_base_url.get().strip(),
            "TRANSCRIBER_SHELL_LLM_USE_PROXY": "true" if self._llm_use_proxy.get() else "false",
            "TRANSCRIBER_SHELL_LLM_HTTP_PROXY": self._llm_http_proxy.get().strip(),
            "TRANSCRIBER_SHELL_GM_PERSISTENT_PROFILE": (
                "true" if self._gm_persistent_profile.get() else "false"
            ),
            "TRANSCRIBER_SHELL_GM_AUTO_INSTALL_BROWSER": (
                "true" if self._gm_auto_install_browser.get() else "false"
            ),
            "TRANSCRIBER_SHELL_GM_USER_DATA_DIR": self._gm_user_data_dir.get().strip(),
            "TRANSCRIBER_SHELL_LINEATION_BACKEND": (
                "kraken" if self._lineation_backend.get().strip() == "michael-lineator"
                else self._lineation_backend.get().strip()
            ),
            "TRANSCRIBER_SHELL_SKIP_LINES_XML_VALIDATION": (
                "true" if self._skip_lines_xml_validation.get() else "false"
            ),
            "TRANSCRIBER_SHELL_CONTINUE_ON_LINEATION_FAILURE": (
                "true" if self._continue_on_lineation_failure.get() else "false"
            ),
            "TRANSCRIBER_SHELL_XML_ONLY": "true" if self._xml_only.get() else "false",
        }

    def _save_keys_to_dotenv(self) -> None:
        path = Path(".env").resolve()
        try:
            merge_dotenv(path, self._env_persist_dict())
        except OSError as e:
            self._gui_notify(f"Save keys failed: {e}", "error", auto_dismiss_ms=0)
            return
        self._gui_notify(
            f"Save keys: Saved provider keys, network, lineation backend, and Glyph Machina settings to:\n{path}\n\n"
            "Do not commit .env.",
            "info",
        )

    # ── LLM model / credentials ───────────────────────────────────────────────

    def _refresh_model_combos(self, event: object | None = None) -> None:
        prov = self._provider.get().lower().strip()
        pool = merged_model_ids_for_selector(
            prov,
            free_only=self._free_only.get(),
            discovered_ollama=self._discovered_ollama if prov == "ollama" else None,
        )
        vals = (_NONE_LABEL,) + pool
        self._cb_model["values"] = vals

        default = default_model_for_provider(prov, self._settings)
        if default in pool:
            self._model_selected.set(default)
        else:
            self._model_selected.set(_NONE_LABEL)

        self._refresh_ui_state()

    def _provider_has_llm_credentials(self) -> bool:
        p = self._provider.get().lower().strip()
        if p == "ollama":
            return True
        if p == "anthropic":
            return bool(self._key_anthropic.get().strip() or self._settings.anthropic_api_key)
        if p == "openai":
            return bool(self._key_openai.get().strip() or self._settings.openai_api_key)
        if p == "gemini":
            return bool(self._key_google.get().strip() or self._settings.google_api_key)
        return False

    def _on_credentials_changed(self, *args: object) -> None:
        self._refresh_ui_state()

    def _effective_model_override(self) -> str | None:
        if not self._provider_has_llm_credentials():
            return None
        custom = self._model_custom.get().strip()
        if custom:
            return custom
        v = self._model_selected.get()
        if v and not v.startswith("(none"):
            return v
        return None

    def _env_overrides_from_form(self) -> dict[str, str]:
        out: dict[str, str] = {}
        if k := self._key_anthropic.get().strip():
            out["ANTHROPIC_API_KEY"] = k
        if k := self._key_openai.get().strip():
            out["OPENAI_API_KEY"] = k
        if k := self._key_google.get().strip():
            out["GOOGLE_API_KEY"] = k
        if u := self._ollama_base_url.get().strip():
            out["TRANSCRIBER_SHELL_OLLAMA_BASE_URL"] = u
        out["TRANSCRIBER_SHELL_LLM_USE_PROXY"] = "true" if self._llm_use_proxy.get() else "false"
        if px := self._llm_http_proxy.get().strip():
            out["TRANSCRIBER_SHELL_LLM_HTTP_PROXY"] = px
        out["TRANSCRIBER_SHELL_GM_PERSISTENT_PROFILE"] = (
            "true" if self._gm_persistent_profile.get() else "false"
        )
        out["TRANSCRIBER_SHELL_GM_AUTO_INSTALL_BROWSER"] = (
            "true" if self._gm_auto_install_browser.get() else "false"
        )
        if gd := self._gm_user_data_dir.get().strip():
            out["TRANSCRIBER_SHELL_GM_USER_DATA_DIR"] = gd
        out["TRANSCRIBER_SHELL_LINEATION_BACKEND"] = (
            "kraken" if self._lineation_backend.get().strip() == "michael-lineator"
            else self._lineation_backend.get().strip()
        )
        out["TRANSCRIBER_SHELL_SKIP_LINES_XML_VALIDATION"] = (
            "true" if self._skip_lines_xml_validation.get() else "false"
        )
        out["TRANSCRIBER_SHELL_CONTINUE_ON_LINEATION_FAILURE"] = (
            "true" if self._continue_on_lineation_failure.get() else "false"
        )
        out["TRANSCRIBER_SHELL_XML_ONLY"] = "true" if self._xml_only.get() else "false"
        return out

    # ── Discovery ─────────────────────────────────────────────────────────────

    def _discover(self) -> None:
        base = self._ollama_base_url.get().strip() or "http://127.0.0.1:11434"

        def work() -> None:
            lines, ollama_models = format_discovery_report(ollama_base=base)
            self._q.put(("discovery", ollama_models))
            for ln in lines:
                self._put_log(ln)
            self._q.put(("status", "Discovery finished."))

        self._q.put(("status", "Discovering…"))
        threading.Thread(target=work, daemon=True).start()

    # ── Browse dialogs ────────────────────────────────────────────────────────

    def _browse_prompt(self) -> None:
        p = filedialog.askopenfilename(
            title="Prompt configuration (YAML or JSON)",
            filetypes=[("YAML / JSON", "*.yaml *.yml *.json"), ("All", "*.*")],
        )
        if p:
            self._prompt_path.set(p)

    def _browse_lines(self) -> None:
        p = filedialog.askopenfilename(
            title="Lines XML file",
            filetypes=[("XML", "*.xml"), ("All", "*.*")],
        )
        if p:
            self._lines_xml_path.set(p)

    def _browse_lines_dir(self) -> None:
        d = filedialog.askdirectory(title="Folder of lines XML files (<stem>.xml per image)")
        if d:
            self._lines_xml_dir.set(d)

    def _browse_xsd(self) -> None:
        p = filedialog.askopenfilename(
            title="PAGE XML XSD (optional)",
            filetypes=[("XSD", "*.xsd"), ("All", "*.*")],
        )
        if p:
            self._xsd_path.set(p)

    def _browse_gm_profile_dir(self) -> None:
        d = filedialog.askdirectory(title="Chromium user data directory for Glyph Machina")
        if d:
            self._gm_user_data_dir.set(d)

    def _save_run_log(self) -> None:
        art = self._settings.artifacts_dir.expanduser().resolve()
        art.mkdir(parents=True, exist_ok=True)
        initial = art / "transcriber-shell-run.log"
        path = filedialog.asksaveasfilename(
            title="Save run log",
            defaultextension=".log",
            initialfile=initial.name,
            initialdir=str(art),
            filetypes=[("Log", "*.log"), ("Text", "*.txt"), ("All", "*.*")],
        )
        if not path:
            return
        try:
            Path(path).write_text(self._log.get("1.0", tk.END), encoding="utf-8")
        except OSError as e:
            self._gui_notify(f"Save log failed: {e}", "error", auto_dismiss_ms=0)
            return
        self._gui_notify(f"Save log: Saved:\n{path}", "info")

    # ── Log helpers ───────────────────────────────────────────────────────────

    def _log_line(self, text: str) -> None:
        self._log.insert(tk.END, text + "\n")
        self._log.see(tk.END)

    def _put_log(self, text: str) -> None:
        try:
            self._log_q.put_nowait(text)
        except queue.Full:
            try:
                self._log_q.get_nowait()
            except queue.Empty:
                pass
            try:
                self._log_q.put_nowait(text)
            except queue.Full:
                if not self._log_truncation_notified:
                    self._log_truncation_notified = True
                    try:
                        self._log_q.put_nowait(
                            "… (run log truncated: queue full; older lines dropped)"
                        )
                    except queue.Full:
                        pass

    def _poll_queue(self) -> None:
        if self._run_metrics_active and self._run_t0 is not None:
            dt = time.monotonic() - self._run_t0
            m = int(dt // 60)
            s = int(dt % 60)
            self._metrics_elapsed.set(f"Elapsed: {m}:{s:02d}")
        try:
            while True:
                self._log_line(self._log_q.get_nowait())
        except queue.Empty:
            pass
        try:
            while True:
                kind, payload = self._q.get_nowait()
                if kind == "discovery":
                    self._discovered_ollama = list(payload) if isinstance(payload, list) else []
                    self._refresh_model_combos()
                elif kind == "log":
                    self._log_line(str(payload))
                elif kind == "status":
                    self._status.set(str(payload))
                elif kind == "metrics":
                    u = payload.get("llm_usage") if isinstance(payload, dict) else None
                    ms = payload.get("elapsed_ms") if isinstance(payload, dict) else None
                    lms = payload.get("lineation_ms") if isinstance(payload, dict) else None
                    self._metrics_tokens.set(_format_llm_usage_line(u, ms, lms))
                elif kind == "done":
                    self._run_metrics_active = False
                    if self._run_t0 is not None:
                        dt = time.monotonic() - self._run_t0
                        m = int(dt // 60)
                        sec = int(dt % 60)
                        self._metrics_elapsed.set(f"Elapsed: {m}:{sec:02d}")
                    if payload is None:
                        self._gui_notify(
                            "Done: Run finished successfully. Check the run log above and Open artifacts folder "
                            "for outputs.",
                            "info",
                        )
                    elif isinstance(payload, dict) and payload.get("batch"):
                        ok_n = int(payload.get("ok", 0))
                        fail_n = int(payload.get("fail", 0))
                        self._gui_notify(
                            f"Batch finished: Completed {ok_n + fail_n} job(s): {ok_n} succeeded, {fail_n} failed. "
                            "See the run log for per-image errors.",
                            "warning" if fail_n else "info",
                        )
                    else:
                        self._gui_notify(
                            f"Transcription failed: {payload}\n\nSee the run log above for step-by-step messages.",
                            "error",
                            auto_dismiss_ms=0,
                        )
        except queue.Empty:
            pass
        self.root.after(120, self._poll_queue)

    # ── Run pipeline ──────────────────────────────────────────────────────────

    def _run(self) -> None:
        images = self._dedupe_sorted_images()
        pr = self._prompt_path.get().strip()
        if not images:
            self._gui_notify(
                "Missing images: Add one or more page images using Add files… or Add folder… "
                "(supported: jpg, png, webp, tiff, etc.).",
                "warning",
            )
            return
        if not pr or not Path(pr).expanduser().is_file():
            self._gui_notify(
                "Missing prompt: Browse to a prompt YAML or JSON file (Academic Transcription Protocol CONFIGURATION). "
                "The fixtures/ folder has an example if you cloned the repo.",
                "warning",
            )
            return
        xsd_raw = self._xsd_path.get().strip()
        xsd_path: Path | None = None
        if xsd_raw:
            xp = Path(xsd_raw).expanduser()
            if not xp.is_file():
                self._gui_notify(
                    f"PAGE XSD: Path does not exist or is not a file:\n{xp}\n\n"
                    "Leave the field empty to skip XSD validation.",
                    "warning",
                )
                return
            xsd_path = xp.resolve()
        req_tl = self._require_text_line.get()
        skip_xml_val = self._skip_lines_xml_validation.get()
        skip = self._skip_gm.get()
        lx = self._lines_xml_path.get().strip()
        lx_dir = self._lines_xml_dir.get().strip()
        n = len(images)
        if skip:
            if n == 1:
                lx_path = Path(lx).expanduser() if lx else None
                dir_path = Path(lx_dir).expanduser() if lx_dir else None
                has_file = lx_path is not None and lx_path.is_file()
                has_dir = dir_path is not None and dir_path.is_dir()
                if not has_file and not has_dir:
                    self._gui_notify(
                        "Lines XML: When skipping lineation with one image, choose a lines XML file "
                        "or a folder containing <stem>.xml for that page.",
                        "warning",
                    )
                    return
                if has_file and has_dir:
                    self._gui_notify(
                        "Lines XML: Fill only one of: Lines XML file, or Lines XML dir — not both at once.",
                        "warning",
                    )
                    return
            else:
                if not lx_dir or not Path(lx_dir).expanduser().is_dir():
                    self._gui_notify(
                        "Lines XML folder: With multiple images, set Lines XML dir to a folder of "
                        "<stem>.xml files (one per page, e.g. page01.jpg → page01.xml).",
                        "warning",
                    )
                    return

        model_override = self._effective_model_override()
        prov = self._provider.get().strip().lower()
        env_overrides = self._env_overrides_from_form()
        eff_mode = self._efficient_mode.get()
        persist_after = self._persist_keys_after_run.get()
        skip_successful = self._skip_successful.get()
        persist_snapshot = self._env_persist_dict()

        self._run_id += 1
        rid = self._run_id
        self._log.delete("1.0", tk.END)
        self._log_truncation_notified = False
        self._run_t0 = time.monotonic()
        self._run_metrics_active = True
        self._metrics_elapsed.set("Elapsed: 0:00")
        self._metrics_tokens.set("LLM tokens: —")
        self._q.put(("status", "Running…"))
        self._put_log("---")
        self._put_log(
            f"runMode={'efficient' if eff_mode else 'standard'} (from prompt + Efficient mode checkbox)"
        )
        self._put_log(
            f"xml_only={self._xml_only.get()} (lines XML + validation only; no LLM when true)"
        )

        threading.Thread(
            target=self._run_worker,
            kwargs=dict(
                images=images,
                pr=pr,
                env_overrides=env_overrides,
                eff_mode=eff_mode,
                skip=skip,
                lineation_backend_str=(
                    "kraken" if self._lineation_backend.get() == "michael-lineator"
                    else self._lineation_backend.get()
                ),
                n=n,
                job_id_str=self._job_id.get().strip(),
                model_override=model_override,
                prov=prov,
                skip_successful=skip_successful,
                lx=lx,
                lx_dir=lx_dir,
                xsd_path=xsd_path,
                req_tl=req_tl,
                skip_xml_val=skip_xml_val,
                persist_after=persist_after,
                persist_snapshot=persist_snapshot,
                rid=rid,
            ),
            daemon=True,
        ).start()

    def _run_worker(
        self,
        *,
        images: list[Path],
        pr: str,
        env_overrides: dict[str, str],
        eff_mode: bool,
        skip: bool,
        lineation_backend_str: str,
        n: int,
        job_id_str: str,
        model_override: str | None,
        prov: str,
        skip_successful: bool,
        lx: str,
        lx_dir: str,
        xsd_path: Path | None,
        req_tl: bool,
        skip_xml_val: bool,
        persist_after: bool,
        persist_snapshot: dict[str, str],
        rid: int,
    ) -> None:
        try:
            cfg = copy.deepcopy(load_prompt_cfg(Path(pr).expanduser()))
            if eff_mode:
                cfg["runMode"] = "efficient"
            with patch.dict(os.environ, env_overrides, clear=False):
                s = Settings()
                if not skip:
                    s = s.model_copy(update={"lineation_backend": lineation_backend_str})
                if n == 1:
                    img = images[0]
                    job = TranscribeJob(
                        job_id=sanitize_job_id(job_id_str) if job_id_str else sanitize_job_id(img.stem),
                        image_path=img,
                        prompt_cfg=cfg,
                        provider=prov,
                        model_override=model_override,
                    )
                    if skip_successful and has_successful_transcription(
                        job.job_id, img, settings=s
                    ):
                        out = transcription_yaml_path(s.artifacts_dir, job.job_id, img)
                        self._put_log(f"skipped job_id={job.job_id} (existing valid transcription)")
                        self._put_log(f"transcription_yaml={out}")
                        self._q.put(("metrics", {"llm_usage": None}))
                        self._q.put(("status", "Succeeded (skipped existing)."))
                        self._q.put(("done", None))
                        return
                    lines_path: Path | None = None
                    if skip:
                        lx_one = lx.strip()
                        lxd_one = lx_dir.strip()
                        if lx_one and Path(lx_one).expanduser().is_file():
                            lines_path = Path(lx_one).expanduser().resolve()
                        elif lxd_one and Path(lxd_one).expanduser().is_dir():
                            cand = Path(lxd_one).expanduser() / f"{img.stem}.xml"
                            if not cand.is_file():
                                raise FileNotFoundError(
                                    f"Lines XML dir is set but file is missing: {cand}. "
                                    f"Need '{img.stem}.xml' beside image '{img.name}' (same stem)."
                                )
                            lines_path = cand.resolve()
                    res = run_pipeline(
                        job,
                        skip_gm=skip,
                        lines_xml_path=lines_path,
                        xsd_path=xsd_path,
                        require_text_line=req_tl,
                        skip_lines_xml_validation=skip_xml_val,
                        settings=s,
                    )
                    if rid != self._run_id:
                        return
                    self._q.put(("metrics", {"llm_usage": res.llm_usage, "elapsed_ms": res.elapsed_ms, "lineation_ms": res.lineation_ms}))
                    for w in res.warnings:
                        self._put_log(f"warning: {w}")
                    if res.lines_xml_path:
                        self._put_log(f"lines_xml={res.lines_xml_path}")
                    if res.transcription_yaml_path:
                        self._put_log(f"transcription_yaml={res.transcription_yaml_path}")
                    self._put_log(f"text_line_count={res.text_line_count}")
                    if res.errors:
                        for e in res.errors:
                            self._put_log(f"error: {e}")
                        self._q.put(("status", "Failed."))
                        self._q.put(("done", "\n".join(res.errors)))
                    else:
                        if persist_after:
                            try:
                                merge_dotenv(Path(".env"), persist_snapshot)
                            except OSError as err:
                                self._put_log(f"warning: could not save keys to .env: {err}")
                        self._q.put(("status", "Succeeded."))
                        self._q.put(("done", None))
                else:
                    lines_xml_dir_arg: Path | None = None
                    if skip:
                        lines_xml_dir_arg = Path(lx_dir).expanduser().resolve()
                    rows = run_batch(
                        images,
                        cfg,
                        provider=prov,
                        model_override=model_override,
                        skip_gm=skip,
                        lines_xml=None,
                        lines_xml_dir=lines_xml_dir_arg,
                        xsd_path=xsd_path,
                        require_text_line=req_tl,
                        skip_lines_xml_validation=skip_xml_val,
                        skip_successful=skip_successful,
                        settings=s,
                    )
                    if rid != self._run_id:
                        return
                    ok_c = 0
                    fail_c = 0
                    for row in rows:
                        jid = row.get("job_id", "")
                        ok = bool(row.get("ok"))
                        if ok:
                            ok_c += 1
                        else:
                            fail_c += 1
                        errs = row.get("errors") or []
                        self._put_log(
                            f"batch job_id={jid} ok={ok} image={row.get('image', '')}"
                        )
                        for e in errs:
                            self._put_log(f"  error: {e}")
                        warns = row.get("warnings") or []
                        for w in warns:
                            self._put_log(f"  warning: {w}")
                        if row.get("lines_xml"):
                            self._put_log(f"  lines_xml={row['lines_xml']}")
                        if row.get("transcription_yaml"):
                            self._put_log(f"  transcription_yaml={row['transcription_yaml']}")
                        if row.get("skipped"):
                            seg = row.get("transcription_segment_count")
                            self._put_log(
                                "  text_line_count=n/a (skipped; PageXML not recomputed); "
                                f"transcription_segment_count={seg}"
                            )
                        else:
                            tlc = row.get("text_line_count")
                            self._put_log(
                                f"  text_line_count={tlc if tlc is not None else 0}"
                            )
                    cum_u: dict[str, int] | None = None
                    cum_ms: int | None = None
                    cum_lms: int | None = None
                    for row in rows:
                        cum_u = _merge_llm_usage(cum_u, row.get("llm_usage"))
                        row_ms = row.get("elapsed_ms")
                        if isinstance(row_ms, int):
                            cum_ms = (cum_ms or 0) + row_ms
                        row_lms = row.get("lineation_ms")
                        if isinstance(row_lms, int):
                            cum_lms = (cum_lms or 0) + row_lms
                    self._q.put(("metrics", {"llm_usage": cum_u, "elapsed_ms": cum_ms, "lineation_ms": cum_lms}))
                    if fail_c == 0 and persist_after:
                        try:
                            merge_dotenv(Path(".env"), persist_snapshot)
                        except OSError as err:
                            self._put_log(f"warning: could not save keys to .env: {err}")
                    self._q.put(
                        ("status", f"Finished {len(rows)} jobs ({ok_c} ok, {fail_c} failed).")
                    )
                    self._q.put(("done", {"batch": True, "ok": ok_c, "fail": fail_c}))
        except Exception as e:
            if rid == self._run_id:
                self._put_log(f"error: {type(e).__name__}: {e}")
                self._q.put(("status", "Failed."))
                self._q.put(("done", f"{type(e).__name__}: {e}"))

    # ── Utility actions ───────────────────────────────────────────────────────

    def _open_artifacts(self) -> None:
        d = self._settings.artifacts_dir.expanduser().resolve()
        d.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform == "darwin":
                subprocess.run(["open", str(d)], check=False)
            elif sys.platform == "win32":
                subprocess.run(["explorer", str(d)], check=False)
            else:
                subprocess.run(["xdg-open", str(d)], check=False)
        except Exception:
            self._gui_notify(f"Artifacts folder: {d}", "info")

    def _open_api_docs(self) -> None:
        host = self._settings.api_host
        port = self._settings.api_port
        url = f"http://{host}:{port}/docs"
        try:
            webbrowser.open(url)
        except Exception:
            self._gui_notify(f"API docs: Open in browser:\n{url}", "info")

    # ── GUI state persistence ─────────────────────────────────────────────────

    def _gui_state_dict(self) -> dict[str, object]:
        return {
            "provider": self._provider.get().strip(),
            "model_selected": self._model_selected.get(),
            "model_custom": self._model_custom.get(),
            "free_only": self._free_only.get(),
            "efficient_mode": self._efficient_mode.get(),
            "skip_gm": self._skip_gm.get(),
            "lineation_backend": self._lineation_backend.get().strip(),
            "prompt_path": self._prompt_path.get().strip(),
            "lines_xml_path": self._lines_xml_path.get().strip(),
            "lines_xml_dir": self._lines_xml_dir.get().strip(),
            "job_id": self._job_id.get().strip(),
            "xsd_path": self._xsd_path.get().strip(),
            "require_text_line": self._require_text_line.get(),
            "skip_lines_xml_validation": self._skip_lines_xml_validation.get(),
            "continue_on_lineation_failure": self._continue_on_lineation_failure.get(),
            "xml_only": self._xml_only.get(),
            "mask_keys": self._mask_keys.get(),
            "ollama_base_url": self._ollama_base_url.get().strip(),
            "llm_use_proxy": self._llm_use_proxy.get(),
            "llm_http_proxy": self._llm_http_proxy.get().strip(),
            "gm_persistent_profile": self._gm_persistent_profile.get(),
            "gm_auto_install_browser": self._gm_auto_install_browser.get(),
            "gm_user_data_dir": self._gm_user_data_dir.get().strip(),
            "persist_keys_after_run": self._persist_keys_after_run.get(),
            "skip_successful": self._skip_successful.get(),
            "image_paths": [str(p) for p in self._dedupe_sorted_images()],
        }

    def _schedule_gui_state_save(self) -> None:
        if self._loading_gui_state:
            return
        if self._save_gui_state_after is not None:
            try:
                self.root.after_cancel(self._save_gui_state_after)
            except (tk.TclError, ValueError):
                pass
        self._save_gui_state_after = self.root.after(450, self._flush_gui_state_save)

    def _flush_gui_state_save(self) -> None:
        self._save_gui_state_after = None
        if self._loading_gui_state:
            return
        try:
            save_gui_state(self._gui_state_dict())
        except OSError:
            pass

    def _restore_model_selection_after_load(self, model_selected: str, model_custom: str) -> None:
        self._refresh_model_combos()
        mc = model_custom.strip()
        if mc:
            self._model_custom.set(mc)
            self._refresh_ui_state()
            return
        ms = model_selected.strip()
        if not ms or ms.startswith("(none"):
            self._refresh_ui_state()
            return
        vals = tuple(self._cb_model["values"])
        if ms in vals:
            self._model_selected.set(ms)
        else:
            self._model_custom.set(ms)
        self._refresh_ui_state()

    def _restore_gui_state(self) -> None:
        data = load_gui_state()
        if not data:
            return
        self._loading_gui_state = True
        try:
            pr = str(data.get("provider", "")).strip().lower()
            if pr in ("anthropic", "openai", "gemini", "ollama"):
                self._provider.set(pr)
            if "free_only" in data:
                self._free_only.set(bool(data["free_only"]))
            if "efficient_mode" in data:
                self._efficient_mode.set(bool(data["efficient_mode"]))
            if "skip_gm" in data:
                self._skip_gm.set(bool(data["skip_gm"]))
            lb = str(data.get("lineation_backend", "")).strip().lower()
            if lb == "kraken":
                lb = "michael-lineator"
            if lb in ("mask", "michael-lineator", "glyph_machina"):
                self._lineation_backend.set(lb)
            for key, var in (
                ("prompt_path", self._prompt_path),
                ("lines_xml_path", self._lines_xml_path),
                ("lines_xml_dir", self._lines_xml_dir),
                ("job_id", self._job_id),
                ("xsd_path", self._xsd_path),
            ):
                if key in data and data[key] is not None:
                    var.set(str(data[key]))
            if "require_text_line" in data:
                self._require_text_line.set(bool(data["require_text_line"]))
            if "skip_lines_xml_validation" in data:
                self._skip_lines_xml_validation.set(bool(data["skip_lines_xml_validation"]))
            if "continue_on_lineation_failure" in data:
                self._continue_on_lineation_failure.set(bool(data["continue_on_lineation_failure"]))
            if "xml_only" in data:
                self._xml_only.set(bool(data["xml_only"]))
            if "mask_keys" in data:
                self._mask_keys.set(bool(data["mask_keys"]))
                self._toggle_key_visibility()
            ou = data.get("ollama_base_url")
            if isinstance(ou, str) and ou.strip():
                self._ollama_base_url.set(ou.strip())
            if "llm_use_proxy" in data:
                self._llm_use_proxy.set(bool(data["llm_use_proxy"]))
            lpx = data.get("llm_http_proxy")
            if isinstance(lpx, str):
                self._llm_http_proxy.set(lpx)
            if "gm_persistent_profile" in data:
                self._gm_persistent_profile.set(bool(data["gm_persistent_profile"]))
            if "gm_auto_install_browser" in data:
                self._gm_auto_install_browser.set(bool(data["gm_auto_install_browser"]))
            gud = data.get("gm_user_data_dir")
            if isinstance(gud, str):
                self._gm_user_data_dir.set(gud)
            if "persist_keys_after_run" in data:
                self._persist_keys_after_run.set(bool(data["persist_keys_after_run"]))
            if "skip_successful" in data:
                self._skip_successful.set(bool(data["skip_successful"]))
            imgs = data.get("image_paths")
            if isinstance(imgs, list):
                paths: list[Path] = []
                for x in imgs:
                    if not isinstance(x, str):
                        continue
                    p = Path(x).expanduser()
                    if p.is_file():
                        paths.append(p)
                self._image_paths = paths
                self._refresh_image_list()
            ms = str(data.get("model_selected", "") or "")
            mc = str(data.get("model_custom", "") or "")
            self._restore_model_selection_after_load(ms, mc)
        finally:
            self._loading_gui_state = False
        self._refresh_ui_state()

    def _install_gui_state_persistence(self) -> None:
        def _on_state_var(_a: str, _b: str, _c: str) -> None:
            self._schedule_gui_state_save()

        for v in (
            self._provider,
            self._model_selected,
            self._model_custom,
            self._free_only,
            self._efficient_mode,
            self._skip_gm,
            self._lineation_backend,
            self._prompt_path,
            self._lines_xml_path,
            self._lines_xml_dir,
            self._job_id,
            self._xsd_path,
            self._require_text_line,
            self._skip_lines_xml_validation,
            self._continue_on_lineation_failure,
            self._xml_only,
            self._mask_keys,
            self._ollama_base_url,
            self._llm_use_proxy,
            self._llm_http_proxy,
            self._gm_persistent_profile,
            self._gm_auto_install_browser,
            self._gm_user_data_dir,
            self._persist_keys_after_run,
            self._skip_successful,
        ):
            v.trace_add("write", _on_state_var)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close_request)

    def _on_close_request(self) -> None:
        if self._save_gui_state_after is not None:
            try:
                self.root.after_cancel(self._save_gui_state_after)
            except (tk.TclError, ValueError):
                pass
            self._save_gui_state_after = None
        self._loading_gui_state = False
        try:
            save_gui_state(self._gui_state_dict())
        except OSError:
            pass
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    TranscriberGui().run()
