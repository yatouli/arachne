"""Item exporters: JSON, JSONL, CSV, and (optionally) Parquet."""

from __future__ import annotations

import csv
import io
import json
import os
from typing import Any, Iterable, Optional

from ..exceptions import ExportError


def export_json(items: Iterable[dict[str, Any]], path: Optional[str] = None, **kwargs) -> str:
    text = json.dumps(list(items), ensure_ascii=False, indent=kwargs.pop("indent", 2), **kwargs)
    if path:
        _write(path, text)
    return text


def export_jsonl(items: Iterable[dict[str, Any]], path: Optional[str] = None) -> str:
    lines = [json.dumps(item, ensure_ascii=False) for item in items]
    text = "\n".join(lines)
    if path:
        _write(path, text + ("\n" if lines else ""))
    return text


def export_csv(items: Iterable[dict[str, Any]], path: Optional[str] = None) -> str:
    rows = list(items)
    if not rows:
        text = ""
    else:
        fieldnames: list[str] = []
        for row in rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: _csvable(row.get(k)) for k in fieldnames})
        text = buf.getvalue()
    if path:
        _write(path, text)
    return text


def export_parquet(items: Iterable[dict[str, Any]], path: str) -> str:
    """Export to Parquet (requires ``pandas`` + ``pyarrow``)."""
    try:
        import pandas as pd
    except ImportError as exc:
        raise ExportError("pandas is required for Parquet export; `pip install arachne[export]`") from exc
    df = pd.DataFrame(list(items))
    df.to_parquet(path, index=False)
    return path


EXPORTERS = {
    "json": export_json,
    "jsonl": export_jsonl,
    "csv": export_csv,
    "parquet": export_parquet,
}


def save_items(items: Iterable[dict[str, Any]], path: str, fmt: Optional[str] = None) -> str:
    """Persist items, choosing the format from the file extension if not given."""
    fmt = (fmt or os.path.splitext(path)[1].lstrip(".") or "json").lower()
    exporter = EXPORTERS.get(fmt)
    if exporter is None:
        raise ExportError(f"unknown export format {fmt!r} (choose from {sorted(EXPORTERS)})")
    return exporter(items, path) if path else exporter(items)


def _csvable(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def _write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
