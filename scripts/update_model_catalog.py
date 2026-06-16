#!/usr/bin/env python3
"""
Update src/transcriber_shell/llm/model_catalog.py by querying live provider APIs.

Run from the project root:
    python3 scripts/update_model_catalog.py [--dry-run] [--providers anthropic openai gemini]

Requires API keys in the environment or .env file. Only providers with a valid
key are queried; others are skipped. Adds newly discovered models to the appropriate
budget/premium tuple without removing existing entries.

Vision-capable determination:
  Anthropic  — all models returned by /v1/models (all support vision as of claude-3+)
  OpenAI     — filters for models whose id contains "gpt-4", "gpt-4o", "o1", "o3",
               "gpt-4.1" (vision-capable families); skips text-only/embedding/moderation
  Gemini     — filters for models that support generateContent and contain "gemini"

Models are classified budget vs premium by name heuristics:
  flash / lite / mini / nano / haiku → budget
  pro / opus / sonnet / gpt-4o / o1 / o3 → premium (when not flash/lite/mini/nano)
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import sys
from pathlib import Path


# ── Load .env ────────────────────────────────────────────────────────────────

def load_env(root: Path) -> None:
    env_file = root / ".env"
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


# ── Provider queries ──────────────────────────────────────────────────────────

def _is_budget(model_id: str) -> bool:
    lo = model_id.lower()
    return any(tok in lo for tok in ("flash", "lite", "mini", "nano", "haiku"))


def list_anthropic_models() -> tuple[list[str], list[str]]:
    import anthropic
    key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("TRANSCRIBER_SHELL_ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    client = anthropic.Anthropic(api_key=key)
    budget, premium = [], []
    for m in client.models.list():
        mid = m.id
        if _is_budget(mid):
            budget.append(mid)
        else:
            premium.append(mid)
    return budget, premium


_OPENAI_VISION_PREFIXES = (
    "gpt-4o", "gpt-4-turbo", "gpt-4.1", "chatgpt-4o",
    "o1", "o3", "o4",
)


def list_openai_models() -> tuple[list[str], list[str]]:
    from openai import OpenAI
    key = os.environ.get("OPENAI_API_KEY") or os.environ.get("TRANSCRIBER_SHELL_OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY not set")
    client = OpenAI(api_key=key)
    budget, premium = [], []
    for m in client.models.list():
        mid = m.id
        if not any(mid.startswith(p) or mid == p for p in _OPENAI_VISION_PREFIXES):
            continue
        if _is_budget(mid):
            budget.append(mid)
        else:
            premium.append(mid)
    return budget, premium


def list_gemini_models() -> tuple[list[str], list[str]]:
    import google.genai as genai
    key = (os.environ.get("GOOGLE_API_KEY")
           or os.environ.get("TRANSCRIBER_SHELL_GOOGLE_API_KEY"))
    if not key:
        raise RuntimeError("GOOGLE_API_KEY not set")
    client = genai.Client(api_key=key)
    budget, premium = [], []
    for m in client.models.list():
        name = m.name  # e.g. "models/gemini-2.5-flash"
        mid = name.removeprefix("models/") if name.startswith("models/") else name
        if "gemini" not in mid.lower():
            continue
        # skip embedding / image-gen / etc
        actions = getattr(m, "supported_actions", None) or []
        if actions and "generateContent" not in actions:
            continue
        if _is_budget(mid):
            budget.append(mid)
        else:
            premium.append(mid)
    return budget, premium


PROVIDER_FNS = {
    "anthropic": list_anthropic_models,
    "openai": list_openai_models,
    "gemini": list_gemini_models,
}

# Map provider → (budget_var, premium_var) in model_catalog.py
CATALOG_VARS = {
    "anthropic": ("ANTHROPIC_BUDGET_MODELS", "ANTHROPIC_PREMIUM_MODELS"),
    "openai": ("OPENAI_BUDGET_MODELS", "OPENAI_PREMIUM_MODELS"),
    "gemini": ("GEMINI_BUDGET_MODELS", "GEMINI_PREMIUM_MODELS"),
}


# ── Catalog update ────────────────────────────────────────────────────────────

def _read_catalog(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _extract_tuple_ids(source: str, var_name: str) -> list[str]:
    """Parse the tuple assigned to var_name from Python source and return the string values."""
    m = re.search(
        rf'{re.escape(var_name)}\s*:\s*tuple\[str,\s*\.\.\.\]\s*=\s*\(([^)]*)\)',
        source,
        re.DOTALL,
    )
    if not m:
        return []
    inner = "(" + m.group(1) + ")"
    try:
        vals = ast.literal_eval(inner)
        return list(vals)
    except Exception:
        return []


def _replace_tuple(source: str, var_name: str, new_ids: list[str]) -> str:
    """Replace the tuple body in source for var_name with new_ids, preserving surrounding code."""
    items = ",\n    ".join(f'"{mid}"' for mid in new_ids)
    new_tuple = f"(\n    {items},\n)"
    # Match the existing tuple assignment (possibly multi-line)
    pattern = rf'({re.escape(var_name)}\s*:\s*tuple\[str,\s*\.\.\.\]\s*=\s*)\([^)]*\)'
    replacement = rf'\g<1>{new_tuple}'
    updated, count = re.subn(pattern, replacement, source, count=1, flags=re.DOTALL)
    if count == 0:
        raise ValueError(f"Could not find tuple assignment for {var_name!r} in catalog")
    return updated


def update_catalog(
    catalog_path: Path,
    provider: str,
    live_budget: list[str],
    live_premium: list[str],
    *,
    dry_run: bool = False,
) -> tuple[list[str], list[str]]:
    """Merge live models into the catalog tuples and optionally write back.

    Returns (added_budget, added_premium).
    """
    source = _read_catalog(catalog_path)
    bvar, pvar = CATALOG_VARS[provider]

    existing_budget = _extract_tuple_ids(source, bvar)
    existing_premium = _extract_tuple_ids(source, pvar)
    existing_all = set(existing_budget) | set(existing_premium)

    # New models not already in catalog
    new_budget = [m for m in live_budget if m not in existing_all]
    new_premium = [m for m in live_premium if m not in existing_all]

    if not new_budget and not new_premium:
        return [], []

    # Prepend new ids (most recent first convention)
    merged_budget = new_budget + existing_budget
    merged_premium = new_premium + existing_premium

    updated = source
    if new_budget:
        updated = _replace_tuple(updated, bvar, merged_budget)
    if new_premium:
        updated = _replace_tuple(updated, pvar, merged_premium)

    if not dry_run:
        catalog_path.write_text(updated, encoding="utf-8")

    return new_budget, new_premium


# ── CLI ───────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Update model_catalog.py from live provider APIs")
    ap.add_argument("--dry-run", action="store_true", help="Print changes without writing")
    ap.add_argument(
        "--providers", nargs="*",
        default=["anthropic", "openai", "gemini"],
        choices=["anthropic", "openai", "gemini"],
        help="Which providers to query (default: all)",
    )
    args = ap.parse_args(argv)

    root = Path(__file__).parent.parent
    load_env(root)

    catalog_path = root / "src" / "transcriber_shell" / "llm" / "model_catalog.py"
    if not catalog_path.is_file():
        print(f"ERROR: catalog not found at {catalog_path}", file=sys.stderr)
        return 1

    any_changes = False
    for provider in args.providers:
        fn = PROVIDER_FNS[provider]
        print(f"\n── {provider} ──")
        try:
            live_budget, live_premium = fn()
        except Exception as e:
            print(f"  skip ({e})")
            continue

        print(f"  live models: {len(live_budget)} budget, {len(live_premium)} premium")

        added_b, added_p = update_catalog(
            catalog_path, provider, live_budget, live_premium, dry_run=args.dry_run
        )
        if added_b or added_p:
            any_changes = True
            if added_b:
                print(f"  + budget:  {added_b}")
            if added_p:
                print(f"  + premium: {added_p}")
            action = "would add" if args.dry_run else "added"
            print(f"  {action} {len(added_b) + len(added_p)} model(s)")
        else:
            print("  catalog already up to date")

    if any_changes and not args.dry_run:
        print(f"\nCatalog updated: {catalog_path}")
    elif any_changes:
        print("\n(dry-run — no files written)")
    else:
        print("\nNo new models found across all providers.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
