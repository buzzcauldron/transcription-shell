"""Optional XSD validation using lxml (extra: pip install transcriber-shell[xml-xsd])."""

from __future__ import annotations

from pathlib import Path
from typing import List, Tuple


def validate_xsd_optional(xml_path: Path, xsd_path: Path) -> Tuple[bool, List[str]]:
    """Validate XML against XSD if lxml is installed; otherwise return error message."""
    try:
        from lxml import etree  # type: ignore[attr-defined]
    except ImportError:
        return False, [
            "lxml not installed; install with: pip install 'transcriber-shell[xml-xsd]'"
        ]

    errs: List[str] = []
    try:
        schema_doc = etree.parse(str(xsd_path))
        schema = etree.XMLSchema(schema_doc)
        doc = etree.parse(str(xml_path))
        schema.assertValid(doc)
    except etree.XMLSyntaxError as e:
        errs.append(f"XML syntax: {e}")
    except etree.DocumentInvalid as e:
        errs.append(f"XSD validation failed: {e}")
    except OSError as e:
        errs.append(str(e))
    return (len(errs) == 0, errs)
