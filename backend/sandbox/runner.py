"""Data-Analyzer sandbox runner — executes INSIDE the OS sandbox on a dedicated
data-science venv (backend/sandbox/.venv-sandbox), NEVER in the backend process.

Two modes, selected by argv:

* ``--profile``  Parse every file under ``<workdir>/data`` (untrusted bytes are
  parsed ONLY here, inside the sandbox), then write a compact preview + manifest
  to ``<workdir>/run/profile.json``.
* (default, exec) Read the LLM-authored code from ``<workdir>/run/code.py``,
  preload the dataframes + helpers into an exec namespace, run it, capture
  stdout / stderr / traceback, and write artifacts to ``<workdir>/run/result.json``.

Hard rule: keep real dtypes. The whole point of this path (vs. the old stringy
TSV pipe) is that ``df['amount'].mean()`` operates on actual numbers, dates stay
dates, etc. Nothing here stringifies a column.

This module imports pandas/numpy — which is fine, because it only ever runs on
the sandbox interpreter. The backend imports NONE of this; it spawns a
subprocess and reads the JSON. Keep that boundary.
"""
from __future__ import annotations

import codecs
import csv
import datetime as _dt
import io
import json
import math
import os
import re
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout
from typing import Any

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------- #
# Limits (kept generous but bounded so a hostile/huge dataset can't blow the
# result.json or wedge the JSON encoder).
# --------------------------------------------------------------------------- #
PROFILE_HEAD_ROWS = 20
DEFAULT_TABLE_MAX_ROWS = 500
CHART_MAX_POINTS = 5000
CSV_SNIFF_BYTES = 64 * 1024
MAX_FILES = 5

# Honest ingest cap (OOM guard; the sandbox has a ~1GB RAM rlimit). A file that
# would exceed this loads only the first N rows AND is flagged ``truncated`` so the
# preview can WARN the model that aggregates are over a sample, not the full file.
MAX_INGEST_ROWS_DEFAULT = 1_000_000


def _max_ingest_rows() -> int:
    """Resolve the ingest row cap from ``DATA_MAX_INGEST_ROWS`` (default 1,000,000).

    Read fresh from the env each call (cheap) so a test can flip it between passes.
    A non-positive or unparsable value disables the cap (treated as unlimited, 0).
    """
    try:
        n = int(os.environ.get("DATA_MAX_INGEST_ROWS", str(MAX_INGEST_ROWS_DEFAULT)))
    except (TypeError, ValueError):
        return MAX_INGEST_ROWS_DEFAULT
    return n if n > 0 else 0


# --------------------------------------------------------------------------- #
# Downloadable output files. The user code writes deliverables via save_output()
# into ``<workdir>/outputs``; _run_exec validates + enumerates them after exec.
# These caps are a DoS guard: the workdir is bound rw, so a hostile/runaway script
# could otherwise fill the disk or emit thousands of artifacts. The byte cap is
# enforced HERE (post-write) because Windows dev has no RLIMIT_FSIZE and the prod
# RLIMIT_FSIZE (256MB) is a coarser, per-file-handle backstop, not a per-output cap.
# --------------------------------------------------------------------------- #
OUTPUT_MAX_BYTES_DEFAULT = 64 * 1024 * 1024   # 67108864
OUTPUT_MAX_FILES_DEFAULT = 5

# Whitelisted output formats → (validation kind, mime). Anything else written to
# outputs/ is ignored with a stderr note (kept off the download surface).
_OUTPUT_MIME = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv",
    "parquet": "application/vnd.apache.parquet",
    "json": "application/json",
}


def _output_max_bytes() -> int:
    """Per-file output size cap from ``DATA_OUTPUT_MAX_BYTES`` (default 64MiB).

    Mirrors the ``DATA_MAX_INGEST_ROWS`` env pattern. Non-positive/unparsable →
    the default (we never disable this cap — it's a disk-fill guard, not a tunable).
    """
    try:
        n = int(os.environ.get("DATA_OUTPUT_MAX_BYTES", str(OUTPUT_MAX_BYTES_DEFAULT)))
    except (TypeError, ValueError):
        return OUTPUT_MAX_BYTES_DEFAULT
    return n if n > 0 else OUTPUT_MAX_BYTES_DEFAULT


def _output_max_files() -> int:
    """Max number of emitted output files from ``DATA_OUTPUT_MAX_FILES`` (default 5)."""
    try:
        n = int(os.environ.get("DATA_OUTPUT_MAX_FILES", str(OUTPUT_MAX_FILES_DEFAULT)))
    except (TypeError, ValueError):
        return OUTPUT_MAX_FILES_DEFAULT
    return n if n > 0 else OUTPUT_MAX_FILES_DEFAULT


def _safe_output_name(name: str, fmt: str) -> str:
    """A single traversal-free filename for an output deliverable: ``<safe>.<fmt>``.

    Mirrors the service's ``_safe_component`` idea — strip any directory parts and
    any caller-supplied extension, then append the canonical ``.{fmt}``. A hostile
    ``name`` (``../../etc/passwd``, ``a/b``) can never escape OUTPUT_DIR.

    Unicode (Persian etc.) is PRESERVED — most users name deliverables in Persian
    and an ASCII-only charset would collapse every name to "output". Only path
    separators, control chars and Windows-reserved punctuation are replaced.
    """
    base = os.path.basename(str(name or "")).strip()
    # Drop ANY extension the caller passed (we own the suffix), then sanitize.
    stem = os.path.splitext(base)[0]
    stem = re.sub(r'[\x00-\x1f<>:"/\\|?*]+', "_", stem).strip("._ -") or "output"
    return f"{stem[:120]}.{fmt}"
CHART_KINDS = {"bar", "line", "pie", "scatter", "area",
               "histogram", "box", "heatmap", "combo"}
# Validated enums for the metric/insight artifacts (frontend depends on these).
_METRIC_DIRECTIONS = {"up-good", "down-good", "neutral"}
_INSIGHT_LEVELS = {"info", "success", "warning"}


# --------------------------------------------------------------------------- #
# JSON-safe value coercion. pandas/numpy scalars, NaT, Timestamps, Decimals and
# bytes are NOT natively JSON-serializable; normalize every cell here so neither
# the manifest nor an artifact can crash ``json.dump``.
# --------------------------------------------------------------------------- #
def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    # pandas / numpy NA sentinels (NaN, NaT, pd.NA) → null.
    try:
        if value is pd.NaT or (np.isscalar(value) and pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        f = float(value)
        return f if math.isfinite(f) else None
    if isinstance(value, (np.datetime64, pd.Timestamp, _dt.datetime, _dt.date)):
        try:
            return pd.Timestamp(value).isoformat()
        except Exception:
            return str(value)
    if isinstance(value, _dt.timedelta) or isinstance(value, pd.Timedelta):
        return str(value)
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", "replace")
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, np.ndarray):
        return [_jsonable(v) for v in value.tolist()]
    return str(value)


def _dtype_str(series: "pd.Series") -> str:
    return str(series.dtype)


def _columns_meta(frame: "pd.DataFrame") -> list[dict]:
    return [
        {"key": str(col), "label": str(col), "dtype": _dtype_str(frame[col])}
        for col in frame.columns
    ]


def _normalize_table_frame(frame: "pd.DataFrame") -> "pd.DataFrame":
    """Make an arbitrary frame safe + readable as a table artifact.

    corr()/describe()/transpose/join results routinely carry a meaningful index
    (row labels) and/or empty or DUPLICATE column names. An empty or duplicate
    name reaches the frontend grid as a column with no usable id and crashes it
    ('Columns require an id when using an accessorFn'). We:
      1. surface a non-default (labelled or non-RangeIndex) index as a real
         column so row labels are visible, and
      2. force every column name to a non-empty, unique string.
    """
    out = frame
    # 1. Surface a meaningful index (skip the default 0..n RangeIndex).
    idx = out.index
    is_default = isinstance(idx, pd.RangeIndex) and idx.name is None
    if not is_default:
        try:
            out = out.reset_index()
        except ValueError:
            # 'index'/'level_0' already a column → leave the frame as-is.
            pass

    # 2. Non-empty, unique column names.
    new_cols: list[str] = []
    seen: dict[str, int] = {}
    for i, col in enumerate(out.columns):
        key = str(col).strip()
        if key == "" or key.lower() == "nan":
            key = f"column_{i + 1}"
        if key in seen:
            seen[key] += 1
            key = f"{key}_{seen[key]}"
        else:
            seen[key] = 0
        new_cols.append(key)
    if [str(c) for c in out.columns] != new_cols:
        if out is frame:
            out = out.copy()
        out.columns = new_cols
    return out


def _records(frame: "pd.DataFrame", limit: int) -> list[dict]:
    """DataFrame → list[dict] with JSON-safe cells, capped at ``limit`` rows."""
    head = frame.head(limit)
    cols = [str(c) for c in head.columns]
    out: list[dict] = []
    for row in head.itertuples(index=False, name=None):
        out.append({cols[i]: _jsonable(row[i]) for i in range(len(cols))})
    return out


# --------------------------------------------------------------------------- #
# File loading. CSV delimiter sniffing; Excel reads EVERY sheet; txt is treated
# as delimited text (tab/comma/semicolon/pipe sniff) falling back to single col.
# --------------------------------------------------------------------------- #
def _sniff_delimiter(sample: str) -> str:
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
        return dialect.delimiter
    except csv.Error:
        # Heuristic fallback: pick the most frequent candidate on the first line.
        first_line = sample.splitlines()[0] if sample else ""
        counts = {d: first_line.count(d) for d in [",", "\t", ";", "|"]}
        best = max(counts, key=counts.get)
        return best if counts[best] > 0 else ","


# Human-readable notes from the data loaders (parse failures, skipped malformed
# rows). One-shot process: surfaced in the profile preview AND in exec stderr so
# the model always learns WHY a file is missing/partial instead of silently
# seeing an empty `datafiles` and wandering off to debug by hand.
_LOAD_NOTES: list[str] = []


def _read_delimited(path: str, sep: str, enc: str, nrows: "int | None") -> "pd.DataFrame":
    """``pd.read_csv`` with a tolerant retry for ragged rows.

    Real exports routinely contain unquoted delimiters inside a field (e.g. a
    thousands-comma in a revenue column) — strict parsing raises ParserError and
    the whole file used to vanish from ``datafiles``. Retry skipping bad lines
    and record how many were dropped.
    """
    kw: dict = dict(sep=sep, engine="python", encoding=enc, encoding_errors="replace")
    if nrows:
        kw["nrows"] = nrows
    try:
        return pd.read_csv(path, **kw)
    except pd.errors.ParserError:
        bad: list = []
        frame = pd.read_csv(path, on_bad_lines=lambda line: bad.append(line) or None, **kw)
        if bad:
            _LOAD_NOTES.append(
                f"{os.path.basename(path)}: {len(bad)} malformed row(s) skipped "
                "(extra/unquoted delimiter)")
        return frame


def _detect_text_encoding(raw: bytes) -> str:
    """Best-effort encoding for a delimited/plain text file.

    Persian sources are commonly UTF-8, UTF-8-with-BOM or UTF-16 (Excel "Unicode
    Text" export), and legacy Windows exports are cp1256. BOMs win; otherwise a
    strict UTF-8 trial decides between 'utf-8-sig' (also strips a stray BOM so it
    can't leak into the first column name) and the cp1256 fallback. The sample may
    cut a multibyte sequence at its tail (a Persian char is 2 bytes), so the trial
    uses an incremental decoder with ``final=False`` — a truncated tail is fine,
    only genuinely invalid UTF-8 raises. (A naive trim-N-bytes guard here CAUSED
    false cp1256 verdicts whenever the file *ended* in Persian text.)
    """
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return "utf-16"
    try:
        codecs.getincrementaldecoder("utf-8")().decode(raw, final=False)
        return "utf-8-sig"
    except UnicodeDecodeError:
        return "cp1256"


def _read_csv_like(path: str) -> dict[str, "pd.DataFrame"]:
    with open(path, "rb") as fh:
        raw = fh.read(CSV_SNIFF_BYTES)
    enc = _detect_text_encoding(raw)
    sample = raw.decode(enc, "replace")
    sep = _sniff_delimiter(sample)
    # ``sep=None`` + python engine would also auto-sniff, but an explicit sniff
    # gives a deterministic, debuggable delimiter and keeps the C engine.
    cap = _max_ingest_rows()
    # Read one row past the cap so we can DETECT (not just silently slice)
    # whether the file was larger, then trim back to the cap.
    frame = _read_delimited(path, sep, enc, (cap + 1) if cap else None)
    return {"": frame}


def _read_excel(path: str) -> dict[str, "pd.DataFrame"]:
    # sheet_name=None → OrderedDict {sheet_name: DataFrame} for ALL sheets.
    # openpyxl = xlsx/xlsm; xlrd = legacy binary .xls (Excel 97–2003).
    ext = os.path.splitext(path)[1].lower()
    engine = "xlrd" if ext == ".xls" else "openpyxl"
    sheets = pd.read_excel(path, sheet_name=None, engine=engine)
    return {str(name): frame for name, frame in sheets.items()}


def _read_txt(path: str) -> dict[str, "pd.DataFrame"]:
    with open(path, "rb") as fh:
        raw = fh.read(CSV_SNIFF_BYTES)
    enc = _detect_text_encoding(raw)
    sample = raw.decode(enc, "replace")
    sep = _sniff_delimiter(sample)
    cap = _max_ingest_rows()
    try:
        frame = _read_delimited(path, sep, enc, (cap + 1) if cap else None)
        if frame.shape[1] <= 1:
            raise ValueError("single column")
        return {"": frame}
    except Exception:
        # Not actually delimited — one text column, one row per line. Stop reading
        # one line past the cap so the backstop in _load_all can flag truncation.
        lines: list[str] = []
        with open(path, "r", encoding=enc, errors="replace") as fh:
            for ln in fh:
                lines.append(ln.rstrip("\n"))
                if cap and len(lines) > cap:
                    break
        return {"": pd.DataFrame({"text": lines})}


def _read_json(path: str) -> dict[str, "pd.DataFrame"]:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        payload = json.load(fh)
    if isinstance(payload, list):
        return {"": pd.json_normalize(payload)}
    if isinstance(payload, dict):
        # A dict of arrays → columns; otherwise a single-row frame.
        if payload and all(isinstance(v, list) for v in payload.values()):
            return {"": pd.DataFrame(payload)}
        return {"": pd.json_normalize(payload)}
    return {"": pd.DataFrame({"value": [payload]})}


def _read_parquet(path: str) -> dict[str, "pd.DataFrame"]:
    # pyarrow is in the sandbox venv; columnar dtypes are preserved natively.
    # Prefer a row-group-aware read so a huge file is capped before it's fully
    # materialized in memory; fall back to a full read + .head() backstop.
    cap = _max_ingest_rows()
    if cap:
        capped = _read_parquet_capped(path, cap + 1)
        if capped is not None:
            return {"": capped}
    return {"": pd.read_parquet(path)}


def _read_parquet_capped(path: str, limit: int) -> "pd.DataFrame | None":
    """Read at most ``limit`` rows from a parquet file without loading it whole.

    Uses pyarrow's batched iterator so a multi-GB file never fully materializes.
    Returns None (caller falls back to a plain read) if pyarrow is unavailable.
    """
    try:
        import pyarrow.parquet as pq  # available in the sandbox venv
    except Exception:  # noqa: BLE001
        return None
    try:
        pf = pq.ParquetFile(path)
        batches = []
        seen = 0
        for batch in pf.iter_batches(batch_size=min(limit, 65536)):
            batches.append(batch)
            seen += batch.num_rows
            if seen >= limit:
                break
        if not batches:
            return pf.read().to_pandas()
        import pyarrow as pa
        return pa.Table.from_batches(batches).slice(0, limit).to_pandas()
    except Exception:  # noqa: BLE001 — fall back to a plain read on any pyarrow hiccup
        return None


def _read_jsonl(path: str) -> dict[str, "pd.DataFrame"]:
    # Line-delimited JSON (one object per line). Prefer pandas' fast path; on a
    # malformed line fall back to a tolerant per-line parse that skips bad rows.
    cap = _max_ingest_rows()
    try:
        frame = pd.read_json(path, lines=True,
                             nrows=(cap + 1) if cap else None)
        return {"": frame}
    except (ValueError, OSError):
        rows: list[dict] = []
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                rows.append(obj if isinstance(obj, dict) else {"value": obj})
                if cap and len(rows) > cap:
                    break
        return {"": pd.json_normalize(rows) if rows else pd.DataFrame()}


_KIND_BY_EXT = {
    ".csv": _read_csv_like,
    ".tsv": _read_csv_like,
    ".xlsx": _read_excel,
    ".xls": _read_excel,
    ".xlsm": _read_excel,  # macro-enabled workbook; openpyxl reads it like .xlsx
    ".txt": _read_txt,
    ".json": _read_json,
    ".jsonl": _read_jsonl,
    ".parquet": _read_parquet,
}


def _slugify_var(name: str) -> str:
    """Readable python-identifier-ish key for the ``dfs`` dict (and var hint)."""
    stem = re.sub(r"[^0-9a-zA-Z]+", "_", name).strip("_").lower()
    if not stem:
        stem = "df"
    if stem[0].isdigit():
        stem = f"df_{stem}"
    return stem


def _load_all(data_dir: str) -> list[tuple[str, str, "pd.DataFrame", bool]]:
    """Return ``[(readable_name, source_filename, DataFrame, truncated), ...]`` for
    every table found under ``data_dir`` (one entry per CSV/txt/json, one per Excel
    sheet). Capped at MAX_FILES source files.

    ``truncated`` is True when the table was larger than ``DATA_MAX_INGEST_ROWS``
    and only the first N rows were ingested (OOM guard). The readers over-read by
    one row where they can; this is the backstop that trims to the cap and flags it
    so the preview can WARN the model that aggregates are over a sample.
    """
    out: list[tuple[str, str, "pd.DataFrame", bool]] = []
    if not os.path.isdir(data_dir):
        return out
    cap = _max_ingest_rows()
    files = sorted(
        f for f in os.listdir(data_dir)
        if os.path.isfile(os.path.join(data_dir, f))
    )[:MAX_FILES]
    for fname in files:
        ext = os.path.splitext(fname)[1].lower()
        reader = _KIND_BY_EXT.get(ext)
        if reader is None:
            continue
        path = os.path.join(data_dir, fname)
        try:
            tables = reader(path)
        except Exception as exc:  # noqa: BLE001 — surface as a skip, not a crash
            sys.stderr.write(f"[runner] failed to parse {fname}: {exc}\n")
            _LOAD_NOTES.append(f"{fname}: FAILED to parse — {_short_error(exc)}")
            continue
        stem = os.path.splitext(fname)[0]
        multi = len(tables) > 1
        for sheet_name, frame in tables.items():
            truncated = False
            if cap and frame.shape[0] > cap:
                frame = frame.head(cap)
                truncated = True
            if multi and sheet_name:
                readable = f"{stem} [{sheet_name}]"
            else:
                readable = stem
            out.append((readable, fname, frame, truncated))
    return out


# --------------------------------------------------------------------------- #
# Warm parquet cache — profile writes once; exec reloads from cache so multi-
# round tool loops don't re-parse fat Excel/CSV every run_python call.
# Invalidated when any source file under data/ changes size/mtime.
# --------------------------------------------------------------------------- #
_CACHE_VERSION = 1


def _cache_dir(workdir: str) -> str:
    return os.path.join(workdir, "cache")


def _source_fingerprint(data_dir: str) -> list[dict]:
    """Stable list of {name, size, mtime_ns} for files under data/."""
    if not os.path.isdir(data_dir):
        return []
    out: list[dict] = []
    for name in sorted(os.listdir(data_dir)):
        path = os.path.join(data_dir, name)
        if not os.path.isfile(path):
            continue
        try:
            st = os.stat(path)
            out.append({
                "name": name,
                "size": int(st.st_size),
                "mtime_ns": int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))),
            })
        except OSError:
            continue
    return out


def _write_warm_cache(
    workdir: str,
    loaded: list[tuple[str, str, "pd.DataFrame", bool]],
) -> None:
    """Persist loaded frames as parquet under ``<workdir>/cache/``."""
    if not loaded:
        return
    cache = _cache_dir(workdir)
    data_dir = os.path.join(workdir, "data")
    try:
        os.makedirs(cache, exist_ok=True)
        # Drop stale parquet from prior datasets so a smaller load doesn't leave ghosts.
        for old in os.listdir(cache):
            if old.endswith(".parquet") or old == "manifest.json":
                try:
                    os.remove(os.path.join(cache, old))
                except OSError:
                    pass
        tables: list[dict] = []
        seen_slugs: set[str] = set()
        for i, (readable, src, frame, truncated) in enumerate(loaded):
            slug = _slugify_var(readable) or f"t{i}"
            base, n = slug, 2
            while slug in seen_slugs:
                slug, n = f"{base}_{n}", n + 1
            seen_slugs.add(slug)
            rel = f"{slug}.parquet"
            frame.to_parquet(os.path.join(cache, rel), index=False)
            tables.append({
                "readable": readable,
                "source": src,
                "parquet": rel,
                "truncated": bool(truncated),
                "shape": [int(frame.shape[0]), int(frame.shape[1])],
            })
        man = {
            "version": _CACHE_VERSION,
            "sources": _source_fingerprint(data_dir),
            "tables": tables,
        }
        with open(os.path.join(cache, "manifest.json"), "w", encoding="utf-8") as fh:
            json.dump(man, fh, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001 — cache is best-effort, never fail analysis
        sys.stderr.write(f"[runner] warm cache write failed: {exc}\n")


def _try_load_warm_cache(
    workdir: str,
) -> list[tuple[str, str, "pd.DataFrame", bool]] | None:
    """Return loaded tables from cache when fingerprint matches; else None."""
    cache = _cache_dir(workdir)
    man_path = os.path.join(cache, "manifest.json")
    data_dir = os.path.join(workdir, "data")
    if not os.path.isfile(man_path):
        return None
    try:
        with open(man_path, "r", encoding="utf-8") as fh:
            man = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(man, dict) or man.get("version") != _CACHE_VERSION:
        return None
    if man.get("sources") != _source_fingerprint(data_dir):
        return None
    tables = man.get("tables")
    if not isinstance(tables, list) or not tables:
        return None
    out: list[tuple[str, str, "pd.DataFrame", bool]] = []
    try:
        for t in tables:
            if not isinstance(t, dict):
                return None
            rel = t.get("parquet")
            readable = t.get("readable")
            src = t.get("source") or ""
            if not rel or not readable:
                return None
            path = os.path.join(cache, str(rel))
            if not os.path.isfile(path):
                return None
            frame = pd.read_parquet(path)
            out.append((str(readable), str(src), frame, bool(t.get("truncated"))))
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"[runner] warm cache load failed: {exc}\n")
        return None
    return out


def _load_frames(
    workdir: str,
) -> tuple[list[tuple[str, str, "pd.DataFrame", bool]], bool]:
    """Load tables preferring warm cache; rebuild cache on miss.

    Returns ``(loaded, from_cache)``.
    """
    data_dir = os.path.join(workdir, "data")
    cached = _try_load_warm_cache(workdir)
    if cached is not None:
        return cached, True
    loaded = _load_all(data_dir)
    _write_warm_cache(workdir, loaded)
    return loaded, False


def _manifest_entry(var: str, readable: str, frame: "pd.DataFrame",
                    truncated: bool = False) -> dict:
    return {
        "var": var,
        "name": readable,
        "shape": [int(frame.shape[0]), int(frame.shape[1])],
        "columns": [str(c) for c in frame.columns],
        "dtypes": {str(c): _dtype_str(frame[c]) for c in frame.columns},
        # Honest ingest-cap markers: when truncated, ``loaded_rows`` is what's
        # actually in memory (the cap) and aggregates are over a SAMPLE.
        "truncated": bool(truncated),
        "loaded_rows": int(frame.shape[0]),
    }


# --------------------------------------------------------------------------- #
# Preview markdown — compact per-table block: shape, columns+dtypes, null counts,
# numeric/categorical/datetime summaries, head(20). Built as plain text (no pandas
# .to_markdown dependency on tabulate). Kept token-frugal: this goes in the system
# prompt so the model can reason about the data BEFORE writing a line of code.
# --------------------------------------------------------------------------- #
# Caps so a wide/hostile frame can't bloat the system prompt.
PROFILE_NUMERIC_COLS = 20
PROFILE_CATEGORICAL_COLS = 15
PROFILE_CAT_TOP_VALUES = 5
PROFILE_HIGH_CARD = 50          # nunique above this → show examples, not full top-N


def _fmt_stat(value: Any) -> str:
    """Format a summary statistic compactly (~4 significant figures)."""
    val = _jsonable(value)
    if val is None:
        return ""
    if isinstance(val, bool):
        return str(val)
    if isinstance(val, int):
        return str(val)
    if isinstance(val, float):
        if not math.isfinite(val):
            return ""
        if val == 0:
            return "0"
        # 4 significant figures, then strip trailing zeros for compactness.
        try:
            txt = f"{val:.4g}"
        except (ValueError, TypeError):
            return str(val)
        return txt
    text = str(val)
    return text if len(text) <= 40 else text[:37] + "..."


# Persian/Arabic-Indic digit chars (used to flag object cols that are really numeric).
_PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩"
_JALALI_RE = re.compile(r"^\s*1[34]\d\d[/\-.]\d{1,2}([/\-.]\d{1,2})?\s*$")


def _object_col_hint(series: "pd.Series") -> str:
    """Return a short dtype-cell hint for an object column that LOOKS numeric
    (Persian/Arabic digits) or like a Jalali date, else ''. Cheap: samples up to
    200 non-null values. Guarded by the caller."""
    try:
        sample = series.dropna().astype(str).head(200)
    except Exception:  # noqa: BLE001
        return ""
    n = len(sample)
    if n == 0:
        return ""
    persian = 0
    jalali = 0
    for v in sample:
        if any(ch in _PERSIAN_DIGITS for ch in v):
            persian += 1
        if _JALALI_RE.match(v):
            jalali += 1
    if jalali >= n * 0.5:
        return " (likely Jalali date — see PERSIAN DATA rules)"
    if persian >= n * 0.5:
        return " (looks numeric: Persian/Arabic digits — normalize before pd.to_numeric)"
    return ""


def _md_cell(text: str) -> str:
    """Escape a value for a markdown table cell."""
    return str(text).replace("|", "\\|").replace("\n", " ")


def _numeric_summary_lines(frame: "pd.DataFrame") -> list[str]:
    """describe()-style table for numeric columns (count/mean/std/min/quartiles/max)."""
    try:
        num = frame.select_dtypes(include=[np.number])
    except Exception:  # noqa: BLE001
        return []
    cols = list(num.columns)
    if not cols:
        return []
    omitted = max(0, len(cols) - PROFILE_NUMERIC_COLS)
    cols = cols[:PROFILE_NUMERIC_COLS]

    stat_keys = ["count", "mean", "std", "min", "25%", "50%", "75%", "max"]
    lines = ["numeric summary:",
             "| column | " + " | ".join(stat_keys) + " |",
             "| --- | " + " | ".join("---:" for _ in stat_keys) + " |"]
    for col in cols:
        try:
            desc = num[col].describe()
            cells = [_fmt_stat(desc.get(k)) for k in stat_keys]
        except Exception:  # noqa: BLE001 — never let a weird column break the preview
            cells = ["" for _ in stat_keys]
        lines.append("| " + _md_cell(str(col)) + " | " + " | ".join(cells) + " |")
    if omitted:
        lines.append(f"_…and {omitted} more numeric column(s) omitted._")
    lines.append("")
    return lines


def _categorical_summary_lines(frame: "pd.DataFrame") -> list[str]:
    """nunique + top value_counts for low-cardinality object/category/bool columns."""
    try:
        cat = frame.select_dtypes(include=["object", "category", "bool"])
    except Exception:  # noqa: BLE001
        return []
    cols = list(cat.columns)
    if not cols:
        return []
    omitted = max(0, len(cols) - PROFILE_CATEGORICAL_COLS)
    cols = cols[:PROFILE_CATEGORICAL_COLS]

    lines = ["categorical summary (top values):"]
    for col in cols:
        try:
            series = cat[col]
            nunique = int(series.nunique(dropna=True))
            if nunique > PROFILE_HIGH_CARD:
                examples = [
                    _fmt_stat(v) for v in series.dropna().unique()[:3]
                ]
                ex = ", ".join(e for e in examples if e != "")
                lines.append(f"- `{col}`: {nunique} unique (high-cardinality) — e.g. {ex}")
            else:
                vc = series.value_counts(dropna=True).head(PROFILE_CAT_TOP_VALUES)
                pairs = ", ".join(
                    f"{_fmt_stat(idx)}: {int(cnt)}" for idx, cnt in vc.items()
                )
                lines.append(f"- `{col}`: {nunique} unique — {pairs}")
        except Exception:  # noqa: BLE001
            continue
    if omitted:
        lines.append(f"_…and {omitted} more categorical column(s) omitted._")
    lines.append("")
    return lines


def _datetime_summary_lines(frame: "pd.DataFrame") -> list[str]:
    """min → max range (+ nunique) for datetime columns."""
    try:
        dt = frame.select_dtypes(include=["datetime", "datetimetz"])
    except Exception:  # noqa: BLE001
        return []
    cols = list(dt.columns)
    if not cols:
        return []
    lines = ["datetime ranges:"]
    for col in cols:
        try:
            series = dt[col].dropna()
            if series.empty:
                lines.append(f"- `{col}`: all null")
                continue
            lo = _fmt_stat(series.min())
            hi = _fmt_stat(series.max())
            nunique = int(series.nunique())
            lines.append(f"- `{col}`: {lo} → {hi} ({nunique} unique)")
        except Exception:  # noqa: BLE001
            continue
    lines.append("")
    return lines


def _preview_block(readable: str, var: str, frame: "pd.DataFrame",
                   truncated: bool = False) -> str:
    rows, cols = frame.shape
    lines = [f"### `{var}` — {readable}"]
    if truncated:
        # Surface truncation LOUDLY so the model can disclose it: any total/aggregate
        # it computes is over a SAMPLE (the first N rows), not the full file.
        cap = _max_ingest_rows()
        lines.append(
            f"⚠ LARGE FILE: only the first {cap:,} rows were loaded — any "
            f"totals/aggregates are over a SAMPLE, not the full file."
        )
    lines += [f"shape: {rows} rows x {cols} columns", ""]

    lines.append("| column | dtype | non-null | nulls |")
    lines.append("| --- | --- | ---: | ---: |")
    total = len(frame)
    for col in frame.columns:
        non_null = int(frame[col].notna().sum())
        nulls = total - non_null
        dtype_txt = _dtype_str(frame[col])
        if dtype_txt == "object":
            try:
                dtype_txt += _object_col_hint(frame[col])
            except Exception:  # noqa: BLE001
                pass
        lines.append(f"| {col} | {dtype_txt} | {non_null} | {nulls} |")
    lines.append("")

    # Per-type statistical summaries (each guarded internally; empty frame → skip).
    if total:
        lines += _numeric_summary_lines(frame)
        lines += _categorical_summary_lines(frame)
        lines += _datetime_summary_lines(frame)

    head = frame.head(PROFILE_HEAD_ROWS)
    col_names = [str(c) for c in head.columns]
    lines.append("head(%d):" % min(PROFILE_HEAD_ROWS, len(frame)))
    lines.append("| " + " | ".join(col_names) + " |")
    lines.append("| " + " | ".join("---" for _ in col_names) + " |")
    for row in head.itertuples(index=False, name=None):
        cells = []
        for cell in row:
            val = _jsonable(cell)
            text = "" if val is None else str(val)
            if len(text) > 60:
                text = text[:57] + "..."
            cells.append(_md_cell(text))
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    return "\n".join(lines)


def _run_profile(workdir: str) -> int:
    data_dir = os.path.join(workdir, "data")
    run_dir = os.path.join(workdir, "run")
    os.makedirs(run_dir, exist_ok=True)

    # Always parse sources on profile (authoritative) and warm the parquet cache
    # for subsequent exec rounds.
    loaded = _load_all(data_dir)
    _write_warm_cache(workdir, loaded)
    manifest: list[dict] = []
    blocks: list[str] = []
    seen_vars: set[str] = set()

    for readable, _src, frame, truncated in loaded:
        var = _slugify_var(readable)
        base = var
        n = 2
        while var in seen_vars:
            var = f"{base}_{n}"
            n += 1
        seen_vars.add(var)
        manifest.append(_manifest_entry(var, readable, frame, truncated))
        blocks.append(_preview_block(readable, var, frame, truncated))

    if manifest:
        preview = (
            f"{len(manifest)} table(s) loaded. The primary table is available as "
            f"`df`; all tables are in the `dfs` dict keyed by name.\n\n"
            + "\n".join(blocks)
        )
    else:
        preview = "No tabular data could be parsed from the uploaded files."
    if manifest and len(manifest) > 1:
        # Map column name -> set of table vars that contain it; report any shared.
        try:
            col_tables: dict[str, list[str]] = {}
            for entry in manifest:
                for col in entry.get("columns", []):
                    col_tables.setdefault(str(col), []).append(entry["var"])
            shared = [
                f"{col} (in {', '.join(tbls)})"
                for col, tbls in col_tables.items() if len(tbls) > 1
            ]
            if shared:
                preview += (
                    "\n\nShared columns (possible join keys): "
                    + "; ".join(shared[:15])
                    + (" …" if len(shared) > 15 else "")
                )
        except Exception:  # noqa: BLE001
            pass
    # Loader warnings (skipped malformed rows, unparseable files) — the model
    # must hear WHY a file is partial/missing, not just see it absent.
    if _LOAD_NOTES:
        preview += "\n\nDATA LOADING WARNINGS:\n" + "\n".join(
            f"- {note}" for note in _LOAD_NOTES)

    out = {"preview_markdown": preview, "manifest": manifest}
    with open(os.path.join(run_dir, "profile.json"), "w", encoding="utf-8") as fh:
        json.dump(_jsonable(out), fh, ensure_ascii=False)
    return 0


# --------------------------------------------------------------------------- #
# Exec mode.
# --------------------------------------------------------------------------- #
class _ArtifactSink:
    """Collects table/chart artifacts emitted by the user code's helpers."""

    def __init__(self) -> None:
        self.artifacts: list[dict] = []

    def show_table(self, data, name=None, max_rows: int = DEFAULT_TABLE_MAX_ROWS) -> None:
        frame = _normalize_table_frame(_coerce_frame(data))
        total = int(frame.shape[0])
        capped = max(1, int(max_rows))
        self.artifacts.append({
            "type": "table",
            "name": None if name is None else str(name),
            "columns": _columns_meta(frame),
            "rows": _records(frame, capped),
            "total_rows": total,
        })

    def show_chart(self, kind, data, x=None, y=None, series=None, title=None,
                   y2=None) -> None:
        k = str(kind).lower().strip()
        if k not in CHART_KINDS:
            raise ValueError(
                f"unknown chart kind {kind!r}; expected one of {sorted(CHART_KINDS)}"
            )
        frame = _coerce_frame(data)
        points = _records(frame, CHART_MAX_POINTS)
        # ``y2`` carries the secondary measure for combo (line over bars) and the
        # value column for heatmap; None for the kinds that don't use it.
        self.artifacts.append({
            "type": "chart",
            "kind": k,
            "encoding": {
                "x": None if x is None else str(x),
                "y": None if y is None else str(y),
                "series": None if series is None else str(series),
                "y2": None if y2 is None else str(y2),
            },
            "data": points,
            "title": None if title is None else str(title),
        })

    def show_metric(self, label, value, delta=None, unit=None,
                    direction="up-good", spark=None) -> None:
        """Headline KPI card. ``value`` passes through when numeric (int/float),
        else is stringified (e.g. a preformatted '$1.2M'). ``delta`` is fractional
        (0.12 = +12%). ``spark`` is an optional list of numbers for a trend line.
        """
        # Keep real numbers as numbers; coerce anything else to a display string.
        safe_value: Any = value if isinstance(value, (int, float)) and not isinstance(value, bool) else str(value)
        try:
            safe_delta = None if delta is None else float(delta)
        except (TypeError, ValueError):
            safe_delta = None
        dir_str = str(direction).lower().strip()
        if dir_str not in _METRIC_DIRECTIONS:
            dir_str = "up-good"
        safe_spark = None
        if spark is not None:
            try:
                safe_spark = [float(v) for v in spark]
            except (TypeError, ValueError):
                safe_spark = None
        self.artifacts.append({
            "type": "metric",
            "label": str(label),
            "value": safe_value,
            "delta": safe_delta,
            "unit": None if unit is None else str(unit),
            "direction": dir_str,
            "spark": safe_spark,
        })

    def show_insight(self, text, level="info") -> None:
        """One-line takeaway. ``level`` ∈ info|success|warning (else info)."""
        lvl = str(level).lower().strip()
        if lvl not in _INSIGHT_LEVELS:
            lvl = "info"
        self.artifacts.append({
            "type": "insight",
            "text": str(text),
            "level": lvl,
        })


def _coerce_frame(data) -> "pd.DataFrame":
    """Accept a DataFrame, a Series, or a list-of-dicts and return a DataFrame."""
    if isinstance(data, pd.DataFrame):
        return data
    if isinstance(data, pd.Series):
        return data.reset_index()
    if isinstance(data, dict):
        return pd.DataFrame(data)
    if isinstance(data, (list, tuple)):
        return pd.DataFrame(list(data))
    raise TypeError(
        "expected a DataFrame, Series, dict, or list-of-dicts; "
        f"got {type(data).__name__}"
    )


def _short_error(exc: BaseException) -> str:
    """Single-line exception summary for the ``error`` field."""
    name = type(exc).__name__
    msg = str(exc).strip().splitlines()
    head = msg[0] if msg else ""
    return f"{name}: {head}" if head else name


# A small denylist applied to the exec builtins. This is BEST-EFFORT defence in
# depth ONLY — the real isolation is the OS sandbox (bwrap: no network, scrubbed
# env, read-only fs, rlimits). Do not rely on python-level filtering for security.
_BLOCKED_BUILTINS = {"exit", "quit", "input", "breakpoint"}


def _build_globals(sink: _ArtifactSink, frames: list[tuple[str, "pd.DataFrame"]],
                   manifest: list[dict], workdir: str) -> dict:
    # __builtins__ is a module when this file runs as a script, a dict under exec.
    builtins_src = __builtins__ if isinstance(__builtins__, dict) else vars(__builtins__)
    safe_builtins = {k: v for k, v in builtins_src.items() if k not in _BLOCKED_BUILTINS}

    dfs = {readable: frame for readable, frame in frames}
    primary = frames[0][1] if frames else pd.DataFrame()

    output_dir = os.path.join(workdir, "outputs")

    def save_output(obj, name: str, format: str = "xlsx") -> str:
        """Write a downloadable deliverable into ``outputs/`` and return its filename.

        ``format`` ∈ xlsx | csv | parquet | json. ``obj`` is normally a DataFrame;
        for xlsx it may ALSO be a ``{sheet_name: DataFrame}`` dict → one sheet each;
        for json it may also be a plain dict/list (json.dump). The returned filename
        (basename, sanitized + canonical extension) is what surfaces as a download
        card to the user — the post-exec enumerator validates the file before it
        ever reaches them, so a write that "succeeds" here can still be rejected if
        it doesn't re-open cleanly.
        """
        fmt = str(format or "").lower().strip()
        if fmt not in _OUTPUT_MIME:
            raise ValueError(
                f"unknown save_output format {format!r}; "
                f"expected one of {sorted(_OUTPUT_MIME)}"
            )
        os.makedirs(output_dir, exist_ok=True)
        filename = _safe_output_name(name, fmt)
        path = os.path.join(output_dir, filename)

        if fmt == "xlsx":
            # Multi-sheet workbook when handed a dict of frames; else a single sheet.
            with pd.ExcelWriter(path, engine="openpyxl") as writer:
                if isinstance(obj, dict):
                    if not obj:
                        raise ValueError("save_output: empty dict of sheets")
                    for sheet, frame in obj.items():
                        # Excel sheet names: ≤31 chars, no []:*?/\ — sanitize defensively.
                        safe_sheet = re.sub(r"[\[\]:*?/\\]", "_", str(sheet))[:31] or "Sheet1"
                        _coerce_frame(frame).to_excel(writer, sheet_name=safe_sheet, index=False)
                else:
                    _coerce_frame(obj).to_excel(writer, sheet_name="Sheet1", index=False)
        elif fmt == "csv":
            # utf-8-sig: Excel (the typical Persian consumer) mis-decodes plain
            # UTF-8 CSVs as ANSI → mojibake; the BOM makes it pick UTF-8.
            _coerce_frame(obj).to_csv(path, index=False, encoding="utf-8-sig")
        elif fmt == "parquet":
            _coerce_frame(obj).to_parquet(path, index=False)
        else:  # json — a DataFrame (records) OR a raw dict/list dumped verbatim.
            if isinstance(obj, (dict, list)):
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(_jsonable(obj), fh, ensure_ascii=False)
            else:
                _coerce_frame(obj).to_json(path, orient="records", force_ascii=False)
        return filename

    def sql(query: str) -> "pd.DataFrame":
        """Run a DuckDB SQL query over the loaded frames.

        Each table is registered under its readable ``datafiles`` name (quote
        names containing dots/spaces, e.g. ``FROM "sales.csv"``); the primary
        table is ALSO registered as ``df``. Returns a pandas DataFrame.
        """
        import duckdb  # lazy: only paid for when the model actually calls sql()

        con = duckdb.connect()
        try:
            for readable, frame in frames:
                con.register(readable, frame)
            con.register("df", primary)
            return con.execute(query).df()
        finally:
            con.close()

    g: dict = {
        "__builtins__": safe_builtins,
        "__name__": "__sandbox__",
        "pd": pd,
        "np": np,
        "df": primary,
        "dfs": dfs,
        "datafiles": manifest,
        "sql": sql,
        "show_table": sink.show_table,
        "show_chart": sink.show_chart,
        "show_metric": sink.show_metric,
        "show_insight": sink.show_insight,
        "save_output": save_output,
        "OUTPUT_DIR": output_dir,
    }
    return g


def _run_exec(workdir: str) -> int:
    data_dir = os.path.join(workdir, "data")
    run_dir = os.path.join(workdir, "run")
    os.makedirs(run_dir, exist_ok=True)

    code_path = os.path.join(run_dir, "code.py")
    try:
        with open(code_path, "r", encoding="utf-8") as fh:
            code = fh.read()
    except OSError as exc:
        _write_result(run_dir, "", f"runner: cannot read code.py: {exc}",
                      _short_error(exc), [], False)
        return 1

    # Warm cache first (profile wrote it); fall back to full parse + rewrite.
    loaded, from_cache = _load_frames(workdir)
    frames: list[tuple[str, "pd.DataFrame"]] = []
    manifest: list[dict] = []
    seen: set[str] = set()
    for readable, _src, frame, truncated in loaded:
        var = _slugify_var(readable)
        base, n = var, 2
        while var in seen:
            var, n = f"{base}_{n}", n + 1
        seen.add(var)
        frames.append((readable, frame))
        manifest.append(_manifest_entry(var, readable, frame, truncated))

    sink = _ArtifactSink()
    g = _build_globals(sink, frames, manifest, workdir)

    out_buf, err_buf = io.StringIO(), io.StringIO()
    # Loader warnings ride along in stderr so the tool loop sees them every call.
    if from_cache:
        err_buf.write("[runner] loaded frames from warm parquet cache\n")
    for note in _LOAD_NOTES:
        err_buf.write(f"[runner] {note}\n")
    error: str | None = None
    try:
        compiled = compile(code, "<user_code>", "exec")
        with redirect_stdout(out_buf), redirect_stderr(err_buf):
            exec(compiled, g)  # noqa: S102 — sandboxed by the OS, not python
    except BaseException as exc:  # noqa: BLE001 — capture everything incl. SystemExit
        error = _short_error(exc)
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        err_buf.write("\n" + tb)

    # Enumerate downloadable deliverables the code wrote to outputs/. A corrupt
    # file appends a clear line to ``error`` so the model loop sees it and retries.
    validation_error = _collect_outputs(workdir, sink, err_buf)
    if validation_error and error is None:
        error = validation_error

    _write_result(run_dir, out_buf.getvalue(), err_buf.getvalue(),
                  error, sink.artifacts, False)
    return 0 if error is None else 1


def _collect_outputs(workdir: str, sink: "_ArtifactSink", err_buf: io.StringIO) -> str | None:
    """Validate + enumerate files under ``<workdir>/outputs``, append artifacts.

    Whitelisted ext only; per-file size cap + max-file cap (env-driven). Each
    candidate is RE-OPENED with the matching reader (deterministic round-trip
    validation) — a file that won't parse is NOT emitted and a clear error line is
    written so the stateless tool-loop can see it and retry. Returns a short error
    string when at least one file failed validation (for the result ``error`` field
    when exec itself didn't raise), else None.

    Graceful-degradation style: a listdir/stat hiccup is swallowed to stderr, never
    raised — a broken outputs/ scan must not mask a successful analysis.
    """
    output_dir = os.path.join(workdir, "outputs")
    if not os.path.isdir(output_dir):
        return None

    try:
        names = sorted(
            f for f in os.listdir(output_dir)
            if os.path.isfile(os.path.join(output_dir, f))
        )
    except OSError as exc:  # noqa: BLE001
        err_buf.write(f"[runner] could not scan outputs/: {exc}\n")
        return None

    max_bytes = _output_max_bytes()
    max_files = _output_max_files()
    first_error: str | None = None
    emitted = 0

    for fname in names:
        ext = os.path.splitext(fname)[1].lower().lstrip(".")
        if ext not in _OUTPUT_MIME:
            err_buf.write(
                f"[runner] ignoring outputs/{fname}: unsupported type "
                f"(only {sorted(_OUTPUT_MIME)} are downloadable)\n"
            )
            continue
        if emitted >= max_files:
            err_buf.write(
                f"[runner] outputs/{fname} skipped: at most {max_files} output "
                f"file(s) per run.\n"
            )
            continue

        path = os.path.join(output_dir, fname)
        try:
            size = os.path.getsize(path)
        except OSError as exc:  # noqa: BLE001
            err_buf.write(f"[runner] outputs/{fname} stat failed: {exc}\n")
            continue
        if size > max_bytes:
            err_buf.write(
                f"[runner] outputs/{fname} skipped: {size} bytes exceeds the "
                f"{max_bytes}-byte per-file cap. Write fewer rows or use parquet.\n"
            )
            continue

        # Deterministic re-open validation: the file must round-trip cleanly before
        # we surface a download card; a corrupt write is reported, never emitted.
        ok, detail = _validate_output(path, ext)
        if not ok:
            msg = f"outputs/{fname} could not be validated ({detail}); not emitted."
            err_buf.write(f"[runner] {msg}\n")
            if first_error is None:
                first_error = msg
            continue

        sink.artifacts.append({
            "type": "file",
            "name": fname,
            "ext": ext,
            "size": int(size),
            "mime": _OUTPUT_MIME[ext],
            "rel_path": f"outputs/{fname}",
        })
        emitted += 1

    return first_error


def _validate_output(path: str, ext: str) -> tuple[bool, str]:
    """Re-open an output file with the matching reader to prove it's not corrupt.

    Returns ``(ok, detail)``. xlsx → ``pd.read_excel``, csv → ``pd.read_csv(nrows=5)``,
    parquet → ``pd.read_parquet``, json → ``json.load``. Any exception → not ok.
    """
    try:
        if ext == "xlsx":
            pd.read_excel(path, sheet_name=0, nrows=5, engine="openpyxl")
        elif ext == "csv":
            pd.read_csv(path, nrows=5)
        elif ext == "parquet":
            pd.read_parquet(path)
        elif ext == "json":
            with open(path, "r", encoding="utf-8") as fh:
                json.load(fh)
        else:
            return False, "unsupported type"
    except Exception as exc:  # noqa: BLE001 — any read failure means corrupt/unusable
        return False, _short_error(exc)
    return True, ""


def _write_result(run_dir: str, stdout: str, stderr: str, error: str | None,
                  artifacts: list[dict], timed_out: bool) -> None:
    payload = {
        "stdout": stdout,
        "stderr": stderr,
        "error": error,
        "artifacts": _jsonable(artifacts),
        "timed_out": timed_out,
    }
    with open(os.path.join(run_dir, "result.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)


def main(argv: list[str]) -> int:
    if "--workdir" in argv:
        workdir = argv[argv.index("--workdir") + 1]
    else:
        # Fall back to the env var the sandbox launcher sets.
        workdir = os.environ.get("SANDBOX_WORKDIR", os.getcwd())
    if "--profile" in argv:
        return _run_profile(workdir)
    return _run_exec(workdir)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
