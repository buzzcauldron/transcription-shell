"""Tucson / decadal .rwl writer and reader."""

from __future__ import annotations

from pathlib import Path

from dendro_shell.series import WidthSeries


def write_rwl(series: WidthSeries, path: Path | str, *, precision: int = 1000) -> None:
    """Write Tucson-format rwl. Widths assumed micrometers; stored as 0.001 mm units (µm).

    Standard Tucson often uses 0.01 mm; we write integer µm (common for digital).
    Missing rings → 0; series terminator → -9999.
    """
    path = Path(path)
    if not series.years:
        path.write_text(f"{series.sample_code[:8]:<8}\n", encoding="utf-8")
        return

    # Pair year→width, sort ascending year
    pairs = sorted(zip(series.years, series.widths_um), key=lambda t: t[0])
    by_year = {int(y): max(0, int(round(w))) for y, w in pairs if y}

    if not by_year:
        path.write_text(f"{series.sample_code[:8]:<8}\n", encoding="utf-8")
        return

    start = min(by_year)
    end = max(by_year)
    # Pad to decade blocks
    decade_start = (start // 10) * 10
    lines: list[str] = []
    code = (series.sample_code or "SERIES")[:8].ljust(8)
    y = decade_start
    while y <= end:
        # First value of decade line includes year
        vals = []
        for i in range(10):
            yy = y + i
            if yy < start or yy > end:
                vals.append("9999")  # placeholder outside series sometimes used; we'll use blanks via skip
            elif yy in by_year:
                vals.append(f"{by_year[yy]:4d}")
            else:
                vals.append("   0")
        # Tucson: 8-char id, year, then 10 measurements
        # Only emit decades that intersect the series
        if any(start <= y + i <= end for i in range(10)):
            row_vals = []
            for i in range(10):
                yy = y + i
                if yy < start or yy > end:
                    row_vals.append(-9999 if yy == end + 1 else None)
                elif yy in by_year:
                    row_vals.append(by_year[yy])
                else:
                    row_vals.append(0)
            # Simpler reliable format: id + year + widths for years in decade that exist
            chunks = []
            for i in range(10):
                yy = y + i
                if start <= yy <= end:
                    chunks.append(f"{by_year.get(yy, 0):4d}")
                else:
                    chunks.append("    ")
            lines.append(f"{code}{y:4d}" + "".join(chunks))
        y += 10
    # Terminator line
    lines.append(f"{code}{end + 1:4d}" + f"{-9999:4d}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_rwl(path: Path | str) -> dict[str, dict[int, float]]:
    """Parse a simple Tucson rwl into {series_id: {year: width_um}}."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    out: dict[str, dict[int, float]] = {}
    for line in text.splitlines():
        if len(line) < 12:
            continue
        sid = line[:8].strip()
        try:
            year = int(line[8:12])
        except ValueError:
            continue
        rest = line[12:]
        # Fixed 4-char fields
        vals = []
        for i in range(0, len(rest), 4):
            chunk = rest[i : i + 4].strip()
            if not chunk:
                continue
            try:
                v = int(chunk)
            except ValueError:
                continue
            if v == -9999 or v == 9999:
                break
            vals.append(v)
        series = out.setdefault(sid, {})
        for i, v in enumerate(vals):
            series[year + i] = float(v)
    return out
