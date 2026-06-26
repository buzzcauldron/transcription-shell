"""expand-diplomatic integration (abbreviation expansion post-diplomatic transcription)."""

from transcriber_shell.expand.bridge import (
    build_pagexml_with_lines,
    expand_pagexml_string,
    expand_yaml_artifact,
    extract_unicode_lines,
    maybe_run_expand_stage,
    resolve_expand_root,
)

__all__ = [
    "build_pagexml_with_lines",
    "expand_pagexml_string",
    "expand_yaml_artifact",
    "extract_unicode_lines",
    "maybe_run_expand_stage",
    "resolve_expand_root",
]
