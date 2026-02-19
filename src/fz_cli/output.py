"""Output formatting: table, json, jsonl, csv."""

from __future__ import annotations

import csv
import io
import json
import sys
from typing import Any, Sequence

import click
from tabulate import tabulate


def _unwrap(data: Any) -> list[dict]:
    """Normalise API data to a flat list of dicts.

    Handles:
      - bare list
      - paginated envelope  {"items": [...], "total": N}
      - single dict (wrap in list)
    """
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if "items" in data:
            return data["items"]
        return [data]
    return []


def format_output(
    data: Any,
    *,
    columns: list[tuple[str, str]] | None = None,
    fmt: str = "table",
    quiet: bool = False,
) -> None:
    """Write formatted output to stdout.

    Args:
        data: Raw API response (list, paginated envelope, or single dict).
        columns: List of (key, header_label) pairs for table/csv modes.
                 If None, auto-detect from first record.
        fmt: One of "table", "json", "jsonl", "csv".
        quiet: If True, suppress output entirely.
    """
    if quiet:
        return

    if fmt == "json":
        _fmt_json(data)
    elif fmt == "jsonl":
        _fmt_jsonl(data)
    elif fmt == "csv":
        _fmt_csv(data, columns)
    else:
        _fmt_table(data, columns)


def _fmt_json(data: Any) -> None:
    click.echo(json.dumps(data, indent=2, default=str))


def _fmt_jsonl(data: Any) -> None:
    rows = _unwrap(data)
    for row in rows:
        click.echo(json.dumps(row, default=str))


def _fmt_csv(data: Any, columns: list[tuple[str, str]] | None) -> None:
    rows = _unwrap(data)
    if not rows:
        return
    cols = columns or [(k, k) for k in rows[0].keys()]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=[k for k, _ in cols], extrasaction="ignore")
    writer.writerow({k: h for k, h in cols})
    for row in rows:
        writer.writerow(row)
    click.echo(buf.getvalue().rstrip())


def _fmt_table(data: Any, columns: list[tuple[str, str]] | None) -> None:
    rows = _unwrap(data)
    if not rows:
        click.echo("No results.")
        return
    cols = columns or [(k, k.upper()) for k in rows[0].keys()]
    headers = [h for _, h in cols]
    table_rows = []
    for row in rows:
        table_rows.append([_truncate(row.get(k, ""), 60) for k, _ in cols])
    click.echo(tabulate(table_rows, headers=headers, tablefmt="plain"))


def _truncate(value: Any, max_len: int) -> str:
    s = str(value) if value is not None else ""
    if len(s) > max_len:
        return s[: max_len - 3] + "..."
    return s
