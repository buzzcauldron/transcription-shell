"""Desktop GUI: single-page manuscript transcription (tkinter, stdlib only for UI).

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
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext
from tkinter import ttk
import tkinter as tk
from unittest.mock import patch

from transcriber_shell.config import Settings
from transcriber_shell.gui_discovery import format_discovery_report
from transcriber_shell.llm.model_catalog import (
    default_model_for_provider,
    merged_model_ids_for_selector,
    models_for_provider,
)
from transcriber_shell.models.job import TranscribeJob
from transcriber_shell.pipeline.batch import (
    IMAGE_SUFFIXES,
    discover_images,
    run_batch,
)
from transcriber_shell.pipeline.run import load_prompt_cfg, run_pipeline

_NONE_LABEL = "(none — use .env default)"

# Quiet academic palette (paper + ink + restrained accent)
_BG = "#f6f4ef"
_FG = "#1f1f1f"
_MUTED = "#4a4a4a"
_ACCENT = "#2f3f4f"
_FIELD_BG = "#fffcf7"


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
        self.root = tk.Tk()
        self.root.title("Transcriber shell")
        self.root.minsize(560, 720)
        self.root.configure(bg=_BG)

        self._settings = Settings()
        self._q: queue.Queue[tuple[str, object]] = queue.Queue()
        self._run_id = 0
        self._discovered_ollama: list[str] = []
        self._key_entry_widgets: list[ttk.Entry] = []

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
        self._status = tk.StringVar(value="Ready.")

        self._build_ui()
        self._poll_queue()

        default_prompt = _repo_fixtures_prompt()
        if default_prompt:
            self._prompt_path.set(str(default_prompt))

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

        # Same body face as subtitle / labels (title stays Georgia); not monospace
        if sys.platform == "darwin":
            _content_font = ("system", 11)
        elif sys.platform == "win32":
            _content_font = ("Segoe UI", 10)
        else:
            _content_font = ("DejaVu Sans", 10)

        outer = ttk.Frame(self.root, padding=16, style="Main.TFrame")
        outer.pack(fill=tk.BOTH, expand=True)

        ttk.Label(outer, text="Transcriber shell", style="Title.TLabel").pack(anchor=tk.W)
        ttk.Label(
            outer,
            text="Glyph Machina lineation · PageXML gate · protocol LLM transcription",
            style="Sub.TLabel",
        ).pack(anchor=tk.W, pady=(0, 4))
        ttk.Label(
            outer,
            text=(
                "Recommended order: add page images and prompt → pick provider and model → "
                "if using Skip Glyph Machina, set lines XML (folder of <stem>.xml when batch) → "
                "Run transcription, then Open artifacts folder."
            ),
            style="Muted.TLabel",
            wraplength=540,
        ).pack(anchor=tk.W, pady=(0, 2))
        ttk.Label(
            outer,
            text="Session and architecture context: see docs/claude.md in the repository checkout.",
            style="Muted.TLabel",
            wraplength=540,
        ).pack(anchor=tk.W, pady=(0, 8))

        cred = ttk.LabelFrame(outer, text="Provider keys (LLM)", padding=(10, 8))
        cred.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(
            cred,
            text="Anthropic / OpenAI / Gemini keys for transcription, or leave empty to use .env.",
            style="Muted.TLabel",
        ).pack(anchor=tk.W, pady=(0, 6))

        def key_row(parent: ttk.LabelFrame, label: str, var: tk.StringVar) -> None:
            f = ttk.Frame(parent, style="Main.TFrame")
            f.pack(fill=tk.X, pady=3)
            ttk.Label(f, text=label, width=14, anchor=tk.W).pack(side=tk.LEFT)
            show = "*" if self._mask_keys.get() else ""
            e = ttk.Entry(f, textvariable=var, show=show)
            e.pack(side=tk.LEFT, fill=tk.X, expand=True)
            self._key_entry_widgets.append(e)

        key_row(cred, "Anthropic", self._key_anthropic)
        key_row(cred, "OpenAI", self._key_openai)
        key_row(cred, "Google (Gemini)", self._key_google)

        olf = ttk.Frame(cred, style="Main.TFrame")
        olf.pack(fill=tk.X, pady=(4, 2))
        ttk.Label(olf, text="Ollama URL", width=14, anchor=tk.W).pack(side=tk.LEFT)
        ttk.Entry(olf, textvariable=self._ollama_base_url).pack(side=tk.LEFT, fill=tk.X, expand=True)

        optf = ttk.Frame(cred, style="Main.TFrame")
        optf.pack(fill=tk.X, pady=(4, 0))
        ttk.Checkbutton(
            optf,
            text="Mask keys",
            variable=self._mask_keys,
            command=self._toggle_key_visibility,
        ).pack(side=tk.LEFT, padx=(0, 16))
        ttk.Checkbutton(
            optf,
            text="Budget models only (cloud)",
            variable=self._free_only,
            command=self._refresh_model_combos,
        ).pack(side=tk.LEFT)

        for _kv in (self._key_anthropic, self._key_openai, self._key_google):
            _kv.trace_add("write", lambda *_: self._on_credentials_changed())

        disc_row = ttk.Frame(outer, style="Main.TFrame")
        disc_row.pack(fill=tk.X, pady=(0, 4))
        ttk.Button(disc_row, text="Scan for Ollama / local tools", command=self._discover).pack(side=tk.LEFT)
        ttk.Label(
            outer,
            text="Optional HTTP API: run transcriber-shell serve, then open HTTP API docs below.",
            style="Muted.TLabel",
            wraplength=520,
        ).pack(anchor=tk.W, pady=(0, 8))

        if self._key_entry_widgets:
            self._key_entry_widgets[0].focus_set()

        img_frame = ttk.LabelFrame(outer, text="Page images", padding=(8, 6))
        img_frame.pack(fill=tk.BOTH, pady=(0, 4))
        self._image_count_label = ttk.Label(img_frame, text="0 image(s)", style="Muted.TLabel")
        self._image_count_label.pack(anchor=tk.W)
        list_fr = ttk.Frame(img_frame, style="Main.TFrame")
        list_fr.pack(fill=tk.BOTH, expand=True, pady=(4, 4))
        self._image_listbox = tk.Listbox(
            list_fr,
            height=5,
            font=_content_font,
            bg=_FIELD_BG,
            fg=_FG,
            selectmode=tk.EXTENDED,
            relief=tk.FLAT,
        )
        self._image_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(list_fr, orient=tk.VERTICAL, command=self._image_listbox.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._image_listbox.configure(yscrollcommand=sb.set)

        img_btns = ttk.Frame(img_frame, style="Main.TFrame")
        img_btns.pack(fill=tk.X)
        ttk.Button(img_btns, text="Add files…", command=self._add_image_files).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(img_btns, text="Add folder…", command=self._add_image_folder).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(img_btns, text="Remove selected", command=self._remove_selected_images).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(img_btns, text="Clear all", command=self._clear_images).pack(side=tk.LEFT)

        def row(label: str, var: tk.StringVar, browse_cmd, browse_label: str) -> None:
            f = ttk.Frame(outer, style="Main.TFrame")
            f.pack(fill=tk.X, pady=4)
            ttk.Label(f, text=label, width=14, anchor=tk.W).pack(side=tk.LEFT)
            e = ttk.Entry(f, textvariable=var)
            e.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
            ttk.Button(f, text=browse_label, command=browse_cmd).pack(side=tk.RIGHT)

        row("Prompt file", self._prompt_path, self._browse_prompt, "Browse…")

        lines_row = ttk.Frame(outer, style="Main.TFrame")
        lines_row.pack(fill=tk.X, pady=4)
        ttk.Label(lines_row, text="Lines XML file", width=14, anchor=tk.W).pack(side=tk.LEFT)
        self._lines_entry = ttk.Entry(lines_row, textvariable=self._lines_xml_path, state="disabled")
        self._lines_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        self._lines_btn = ttk.Button(lines_row, text="Browse…", command=self._browse_lines, state="disabled")
        self._lines_btn.pack(side=tk.RIGHT)

        lines_dir_row = ttk.Frame(outer, style="Main.TFrame")
        lines_dir_row.pack(fill=tk.X, pady=4)
        ttk.Label(lines_dir_row, text="Lines XML dir", width=14, anchor=tk.W).pack(side=tk.LEFT)
        self._lines_dir_entry = ttk.Entry(lines_dir_row, textvariable=self._lines_xml_dir, state="disabled")
        self._lines_dir_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        self._lines_dir_btn = ttk.Button(
            lines_dir_row, text="Browse…", command=self._browse_lines_dir, state="disabled"
        )
        self._lines_dir_btn.pack(side=tk.RIGHT)

        self._lines_help = ttk.Label(outer, text="", style="Muted.TLabel", wraplength=520)
        self._lines_help.pack(anchor=tk.W, pady=(0, 2))

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

        prov_row = ttk.Frame(outer, style="Main.TFrame")
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

        model_row = ttk.Frame(outer, style="Main.TFrame")
        model_row.pack(fill=tk.X, pady=4)
        ttk.Label(model_row, text="Model", width=14, anchor=tk.W).pack(side=tk.LEFT)
        self._cb_model = ttk.Combobox(
            model_row,
            textvariable=self._model_selected,
            state="readonly",
            width=52,
        )
        self._cb_model.pack(side=tk.LEFT, fill=tk.X, expand=True)

        eff_row = ttk.Frame(outer, style="Main.TFrame")
        eff_row.pack(fill=tk.X, pady=2)
        ttk.Label(eff_row, text="", width=14).pack(side=tk.LEFT)
        ttk.Checkbutton(
            eff_row,
            text="Efficient mode (protocol §2.9 — single pass, core tokens only)",
            variable=self._efficient_mode,
        ).pack(side=tk.LEFT)

        cust_row = ttk.Frame(outer, style="Main.TFrame")
        cust_row.pack(fill=tk.X, pady=4)
        ttk.Label(cust_row, text="Custom model id", width=14, anchor=tk.W).pack(side=tk.LEFT)
        self._model_custom_entry = ttk.Entry(cust_row, textvariable=self._model_custom, width=40)
        self._model_custom_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(
            outer,
            text="Dropdown lists all catalog model IDs (budget + premium). Budget models only (above) narrows the list. Custom overrides the dropdown. Cloud model controls stay disabled until a provider key is entered or present in .env.",
            style="Muted.TLabel",
            wraplength=500,
        ).pack(anchor=tk.W, pady=(0, 4))

        self._all_models_visible = False
        all_models_frame = ttk.LabelFrame(outer, text="All model variations", padding=(8, 6))
        all_models_frame.pack(fill=tk.X, pady=(0, 4))
        am_head = ttk.Frame(all_models_frame, style="Main.TFrame")
        am_head.pack(fill=tk.X)
        self._all_models_toggle = ttk.Button(
            am_head,
            text="▸ Show all model IDs",
            command=self._toggle_all_models_expander,
        )
        self._all_models_toggle.pack(side=tk.LEFT)
        self._all_models_container = ttk.Frame(all_models_frame, style="Main.TFrame")
        am_inner = ttk.Frame(self._all_models_container, style="Main.TFrame")
        y_am = ttk.Scrollbar(am_inner, orient=tk.VERTICAL)
        x_am = ttk.Scrollbar(am_inner, orient=tk.HORIZONTAL)
        self._all_models_text = scrolledtext.ScrolledText(
            am_inner,
            height=8,
            wrap=tk.NONE,
            font=_content_font,
            bg=_FIELD_BG,
            fg=_FG,
            insertbackground=_FG,
            relief=tk.FLAT,
            padx=8,
            pady=8,
        )
        y_am.configure(command=self._all_models_text.yview)
        x_am.configure(command=self._all_models_text.xview)
        self._all_models_text.configure(yscrollcommand=y_am.set, xscrollcommand=x_am.set)
        self._all_models_text.grid(row=0, column=0, sticky="nsew")
        y_am.grid(row=0, column=1, sticky="ns")
        x_am.grid(row=1, column=0, sticky="ew")
        am_inner.rowconfigure(0, weight=1)
        am_inner.columnconfigure(0, weight=1)
        am_inner.pack(fill=tk.BOTH, expand=True)

        skip = ttk.Checkbutton(
            outer,
            text="Skip Glyph Machina — use existing lines XML (offline)",
            variable=self._skip_gm,
            command=self._toggle_skip_gm,
        )
        skip.pack(anchor=tk.W, pady=(8, 4))

        ttk.Label(
            outer,
            text="Outputs: artifacts/<job_id>/  ·  .env still used when fields above are empty.",
            style="Muted.TLabel",
        ).pack(anchor=tk.W, pady=(4, 8))

        btn_row = ttk.Frame(outer, style="Main.TFrame")
        btn_row.pack(fill=tk.X, pady=8)
        ttk.Button(btn_row, text="Run transcription", style="Accent.TButton", command=self._run).pack(
            side=tk.LEFT
        )
        ttk.Button(btn_row, text="Open artifacts folder", command=self._open_artifacts).pack(
            side=tk.LEFT, padx=(12, 0)
        )
        ttk.Button(btn_row, text="HTTP API docs (browser)", command=self._open_api_docs).pack(
            side=tk.LEFT, padx=(12, 0)
        )

        ttk.Label(outer, textvariable=self._status, style="Muted.TLabel").pack(anchor=tk.W, pady=(4, 4))

        self._log = scrolledtext.ScrolledText(
            outer,
            height=12,
            wrap=tk.WORD,
            font=_content_font,
            bg=_FIELD_BG,
            fg=_FG,
            insertbackground=_FG,
            relief=tk.FLAT,
            padx=8,
            pady=8,
        )
        self._log.pack(fill=tk.BOTH, expand=True)

        self._refresh_model_combos()
        self._refresh_image_list()
        self._sync_lines_xml_ui()
        self._sync_model_credentials_state()

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
        self._sync_lines_xml_ui()

    def _sync_lines_xml_ui(self) -> None:
        n = len(self._dedupe_sorted_images())
        skip = self._skip_gm.get()
        if not skip:
            self._lines_entry.configure(state="disabled")
            self._lines_btn.configure(state="disabled")
            self._lines_dir_entry.configure(state="disabled")
            self._lines_dir_btn.configure(state="disabled")
            self._lines_help.configure(text="")
            self._job_entry.configure(state="normal")
            self._job_hint.configure(text="")
            return
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
                text="Batch + skip GM: choose Lines XML dir with one <image_stem>.xml per page."
            )
        if n <= 1:
            self._job_entry.configure(state="normal")
            self._job_hint.configure(text="")
        else:
            self._job_entry.configure(state="disabled")
            self._job_hint.configure(text="Batch uses each filename as job id.")

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
        added = False
        first_new = True
        for s in paths:
            p = Path(s)
            if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES:
                rp = p.resolve()
                if rp not in {x.resolve() for x in self._image_paths}:
                    self._image_paths.append(p)
                    added = True
                    if first_new and len(self._image_paths) == 1:
                        stem = p.stem[:120] or "job"
                        self._job_id.set(stem)
                    first_new = False
        if added:
            self._refresh_image_list()
        elif paths:
            messagebox.showinfo("Add files", "No supported image files were added (check file types).")

    def _add_image_folder(self) -> None:
        d = filedialog.askdirectory(title="Folder containing page images")
        if not d:
            return
        found = discover_images(d)
        if not found:
            messagebox.showinfo("Add folder", "No supported images found in that folder.")
            return
        before = len(self._image_paths)
        existing = {x.resolve() for x in self._image_paths}
        for p in found:
            if p.resolve() not in existing:
                existing.add(p.resolve())
                self._image_paths.append(p)
        self._refresh_image_list()
        if len(self._image_paths) == 1 and before == 0:
            self._job_id.set(self._image_paths[0].stem[:120] or "job")

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

    def _toggle_key_visibility(self) -> None:
        show = "*" if self._mask_keys.get() else ""
        for e in self._key_entry_widgets:
            e.configure(show=show)

    def _toggle_all_models_expander(self) -> None:
        self._all_models_visible = not self._all_models_visible
        if self._all_models_visible:
            self._all_models_container.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
            self._all_models_toggle.configure(text="▾ Hide catalog")
            self._refresh_all_models_catalog()
        else:
            self._all_models_container.pack_forget()
            self._all_models_toggle.configure(text="▸ Show all model IDs")

    def _format_all_models_catalog_text(self) -> str:
        prov = self._provider.get().lower().strip()
        ids = merged_model_ids_for_selector(
            prov,
            free_only=self._free_only.get(),
            discovered_ollama=self._discovered_ollama if prov == "ollama" else None,
        )
        lines: list[str] = ["All model IDs (same as Model dropdown, sorted)", ""]
        for m in ids:
            lines.append(f"  {m}")
        if prov == "ollama" and self._discovered_ollama:
            lines.extend(["", "Ollama: Scan merges extra tags into the list when not in static catalog."])
        return "\n".join(lines)

    def _refresh_all_models_catalog(self) -> None:
        body = self._format_all_models_catalog_text()
        self._all_models_text.configure(state=tk.NORMAL)
        self._all_models_text.delete("1.0", tk.END)
        self._all_models_text.insert("1.0", body)
        self._all_models_text.configure(state=tk.DISABLED)

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

        self._refresh_all_models_catalog()
        self._sync_model_credentials_state()

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
        self._sync_model_credentials_state()

    def _sync_model_credentials_state(self) -> None:
        ok = self._provider_has_llm_credentials()
        st = "readonly" if ok else "disabled"
        self._cb_model.configure(state=st)
        self._model_custom_entry.configure(state="normal" if ok else "disabled")

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
        return out

    def _discover(self) -> None:
        base = self._ollama_base_url.get().strip() or "http://127.0.0.1:11434"

        def work() -> None:
            lines, ollama_models = format_discovery_report(ollama_base=base)
            self._q.put(("discovery", ollama_models))
            for ln in lines:
                self._q.put(("log", ln))
            self._q.put(("status", "Discovery finished."))

        self._q.put(("status", "Discovering…"))
        threading.Thread(target=work, daemon=True).start()

    def _toggle_skip_gm(self) -> None:
        self._sync_lines_xml_ui()

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

    def _log_line(self, text: str) -> None:
        self._log.insert(tk.END, text + "\n")
        self._log.see(tk.END)

    def _poll_queue(self) -> None:
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
                elif kind == "done":
                    if payload is None:
                        messagebox.showinfo("Done", "Run finished. See log for paths.")
                    elif isinstance(payload, dict) and payload.get("batch"):
                        ok_n = int(payload.get("ok", 0))
                        fail_n = int(payload.get("fail", 0))
                        messagebox.showinfo(
                            "Batch finished",
                            f"Succeeded: {ok_n}, failed: {fail_n}. See log for details.",
                        )
                    else:
                        messagebox.showerror("Transcription failed", str(payload))
        except queue.Empty:
            pass
        self.root.after(120, self._poll_queue)

    def _run(self) -> None:
        images = self._dedupe_sorted_images()
        pr = self._prompt_path.get().strip()
        if not images:
            messagebox.showwarning("Missing images", "Add one or more page images, or a folder of images.")
            return
        if not pr or not Path(pr).is_file():
            messagebox.showwarning("Missing prompt", "Choose a prompt YAML or JSON file.")
            return
        skip = self._skip_gm.get()
        lx = self._lines_xml_path.get().strip()
        lx_dir = self._lines_xml_dir.get().strip()
        n = len(images)
        if skip:
            if n == 1:
                lx_path = Path(lx) if lx else None
                dir_path = Path(lx_dir) if lx_dir else None
                has_file = lx_path is not None and lx_path.is_file()
                has_dir = dir_path is not None and dir_path.is_dir()
                if not has_file and not has_dir:
                    messagebox.showwarning(
                        "Lines XML",
                        "When skipping Glyph Machina with one image, choose a lines XML file "
                        "or a folder containing <stem>.xml.",
                    )
                    return
                if has_file and has_dir:
                    messagebox.showwarning(
                        "Lines XML",
                        "Use either a lines XML file or a lines XML folder, not both.",
                    )
                    return
            else:
                if not lx_dir or not Path(lx_dir).is_dir():
                    messagebox.showwarning(
                        "Lines XML folder",
                        "When skipping Glyph Machina with multiple images, choose a folder of "
                        "<stem>.xml files (one per page).",
                    )
                    return

        model_override = self._effective_model_override()
        prov = self._provider.get().strip().lower()
        env_overrides = self._env_overrides_from_form()

        self._run_id += 1
        rid = self._run_id
        self._log.delete("1.0", tk.END)
        self._q.put(("status", "Running…"))
        self._q.put(("log", "---"))

        def worker() -> None:
            try:
                cfg = copy.deepcopy(load_prompt_cfg(Path(pr)))
                if self._efficient_mode.get():
                    cfg["runMode"] = "efficient"
                with patch.dict(os.environ, env_overrides, clear=False):
                    s = Settings()
                    if n == 1:
                        img = images[0]
                        job = TranscribeJob(
                            job_id=self._job_id.get().strip() or "job",
                            image_path=img,
                            prompt_cfg=cfg,
                            provider=prov,
                            model_override=model_override,
                        )
                        lines_path: Path | None = None
                        if skip:
                            lx_one = lx.strip()
                            lxd_one = lx_dir.strip()
                            if lx_one and Path(lx_one).is_file():
                                lines_path = Path(lx_one).resolve()
                            elif lxd_one and Path(lxd_one).is_dir():
                                cand = Path(lxd_one) / f"{img.stem}.xml"
                                if not cand.is_file():
                                    raise FileNotFoundError(
                                        f"Expected lines XML at {cand} (from lines XML dir)"
                                    )
                                lines_path = cand.resolve()
                        res = run_pipeline(
                            job,
                            skip_gm=skip,
                            lines_xml_path=lines_path,
                            require_text_line=True,
                            settings=s,
                        )
                        if rid != self._run_id:
                            return
                        for w in res.warnings:
                            self._q.put(("log", f"warning: {w}"))
                        if res.lines_xml_path:
                            self._q.put(("log", f"lines_xml={res.lines_xml_path}"))
                        if res.transcription_yaml_path:
                            self._q.put(("log", f"transcription_yaml={res.transcription_yaml_path}"))
                        self._q.put(("log", f"text_line_count={res.text_line_count}"))
                        if res.errors:
                            for e in res.errors:
                                self._q.put(("log", f"error: {e}"))
                            self._q.put(("status", "Failed."))
                            self._q.put(("done", "\n".join(res.errors)))
                        else:
                            self._q.put(("status", "Succeeded."))
                            self._q.put(("done", None))
                    else:
                        lines_xml_arg: Path | None = None
                        lines_xml_dir_arg: Path | None = None
                        if skip:
                            lines_xml_dir_arg = Path(lx_dir).resolve()
                        rows = run_batch(
                            images,
                            cfg,
                            provider=prov,
                            model_override=model_override,
                            skip_gm=skip,
                            lines_xml=lines_xml_arg,
                            lines_xml_dir=lines_xml_dir_arg,
                            xsd_path=None,
                            require_text_line=True,
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
                            self._q.put(
                                (
                                    "log",
                                    f"batch job_id={jid} ok={ok} image={row.get('image', '')}",
                                )
                            )
                            for e in errs:
                                self._q.put(("log", f"  error: {e}"))
                            warns = row.get("warnings") or []
                            for w in warns:
                                self._q.put(("log", f"  warning: {w}"))
                            if row.get("lines_xml"):
                                self._q.put(("log", f"  lines_xml={row['lines_xml']}"))
                            if row.get("transcription_yaml"):
                                self._q.put(("log", f"  transcription_yaml={row['transcription_yaml']}"))
                            self._q.put(("log", f"  text_line_count={row.get('text_line_count', 0)}"))
                        self._q.put(("status", f"Finished {len(rows)} jobs ({ok_c} ok, {fail_c} failed)."))
                        self._q.put(("done", {"batch": True, "ok": ok_c, "fail": fail_c}))
            except Exception as e:
                if rid == self._run_id:
                    self._q.put(("log", f"error: {e}"))
                    self._q.put(("status", "Failed."))
                    self._q.put(("done", str(e)))

        threading.Thread(target=worker, daemon=True).start()

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
            messagebox.showinfo("Artifacts", str(d))

    def _open_api_docs(self) -> None:
        host = self._settings.api_host
        port = self._settings.api_port
        url = f"http://{host}:{port}/docs"
        try:
            webbrowser.open(url)
        except Exception:
            messagebox.showinfo("API docs", f"Open in browser:\n{url}")

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    TranscriberGui().run()
