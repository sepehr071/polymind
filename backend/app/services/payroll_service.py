"""Parse the monthly all-employees payroll Excel export and build per-employee
Persian salary-slip PDFs.

Pure functions — no DB, no FastAPI. The Excel is a fixed software export with a
3-row merged header (group bands / column names / sub-names for the ``مزایای
مستمر`` block) followed by one row per employee and a final ``جمع کل`` totals
row.

The tricky part: labels like ``حق مسکن`` / ``حق بن`` / ``حقوق ثابت ماهیانه``
appear BOTH in the ``حکم`` (decree/contract base) group and in the
``مزایای مستمر`` (actually-paid) group. We must take the *paid* amounts, so
columns are resolved by the **(group band, header name)** pair, not by header
name alone. ``openpyxl`` exposes merged ranges with the value only in the
top-left cell, so the group bands (row 1) and the ``مستمر`` sub-headers (row 3)
are forward-filled across their spans before mapping.
"""
from __future__ import annotations

import io
import os
import re
import zipfile

import openpyxl

from app.services.document_extraction_service import (
    _ZipBombError,
    _guard_office_xml,
)
from app.services.payslip_render import render_payslip

# A real monthly payroll export is small and bounded: at most a few thousand
# employees (one row each) and well under a hundred columns. openpyxl's default
# (non-read-only) loader materializes a Cell object per populated cell, so a
# legitimately-compressed but absurdly large sheet (passing the zip-bomb byte
# guard yet declaring millions of cells) would still explode the worker heap.
# These caps bound the *used range* AFTER the zip-bomb guard so neither vector
# can OOM the single bare-metal worker. Generous vs. any genuine payroll file.
_MAX_PAYROLL_ROWS = 20_000
_MAX_PAYROLL_COLS = 256

# Header text constants (normalized: collapsed whitespace, ي/ك→ی/ک).
_GROUP_HEKM = "حکم"
_GROUP_KARKARD = "کارکرد"
_GROUP_MOSTAMAR = "مزایای مستمر"
_GROUP_GHEYR_MOSTAMAR = "مزایای غیر مستمر"
_GROUP_KOSURAT = "کسورات"

_DEFAULT_EMPLOYER = "شرکت نمونه"

_HEADER_ROW_GROUP = 1   # merged group bands
_HEADER_ROW_MAIN = 2    # main column names
_HEADER_ROW_SUB = 3     # sub-names (مزایای مستمر block only)
_FIRST_DATA_ROW = 4

_ARABIC_TO_PERSIAN = str.maketrans({"ي": "ی", "ك": "ک", "‌": " ", "ي": "ی"})


def _norm(text: object) -> str:
    """Normalize a header cell: str, Arabic→Persian letters, collapse spaces."""
    if text is None:
        return ""
    s = str(text).translate(_ARABIC_TO_PERSIAN)
    return re.sub(r"\s+", " ", s).strip()


def _num(value: object) -> int:
    """Coerce a cell to a rounded int; blank / NaN / non-numeric → 0."""
    if value is None or value == "":
        return 0
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0
    if f != f:  # NaN
        return 0
    return int(round(f))


def _raw_num(value: object) -> float | int:
    """Numeric passthrough for work_days / overtime (keep fractional hours)."""
    if value is None or value == "":
        return 0
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0
    if f != f:
        return 0
    return int(f) if float(f).is_integer() else f


# ---------------------------------------------------------------------------
# Filename sanitizer — UNICODE-PRESERVING (mirrors utils.files.display_filename
# but inlined to keep this module self-contained / DB-free importable).
# ---------------------------------------------------------------------------
def _safe_component(name: object) -> str:
    base = os.path.basename(str(name or "")).strip()
    base = re.sub(r'[\x00-\x1f<>:"/\\|?*]+', "_", base)
    base = "_".join(base.split()).strip("._")
    return base or "payslip"


# ---------------------------------------------------------------------------
# Column mapping from merged header.
# ---------------------------------------------------------------------------
def _forward_fill_row(ws, row: int, n_cols: int) -> list[str]:
    """Return normalized values for ``row`` with merged spans forward-filled.

    openpyxl only stores the value in the top-left cell of a merged range; the
    rest read as ``None``. We propagate each horizontal merge's value across
    its columns so every column index has its band/sub label.
    """
    values = [_norm(ws.cell(row=row, column=c).value) for c in range(1, n_cols + 1)]
    for rng in ws.merged_cells.ranges:
        if rng.min_row <= row <= rng.max_row:
            top_left = _norm(ws.cell(row=rng.min_row, column=rng.min_col).value)
            if top_left:
                for c in range(rng.min_col, rng.max_col + 1):
                    if 1 <= c <= n_cols:
                        values[c - 1] = top_left
    return values


def _build_column_index(ws, n_cols: int) -> dict:
    """Map every column to its (group, name) and build reverse lookups.

    Returns a dict with:
      - ``by_group_name``: {(group, name): col_idx}  (first wins)
      - ``by_name``:       {name: col_idx}            (ungrouped fallback)
    """
    groups = _forward_fill_row(ws, _HEADER_ROW_GROUP, n_cols)
    mains = _forward_fill_row(ws, _HEADER_ROW_MAIN, n_cols)
    subs = [_norm(ws.cell(row=_HEADER_ROW_SUB, column=c).value) for c in range(1, n_cols + 1)]

    by_group_name: dict[tuple[str, str], int] = {}
    by_name: dict[str, int] = {}
    for i in range(n_cols):
        col = i + 1
        group = groups[i]
        # The most-specific column label: sub-name (row 3) if present else main.
        name = subs[i] or mains[i]
        if not name:
            continue
        by_group_name.setdefault((group, name), col)
        by_name.setdefault(name, col)
    return {"by_group_name": by_group_name, "by_name": by_name}


def _find(idx: dict, name: str, *, group: str | None = None) -> int | None:
    """Resolve a column index by name, optionally pinned to a group band."""
    name = _norm(name)
    if group is not None:
        col = idx["by_group_name"].get((_norm(group), name))
        if col is not None:
            return col
    return idx["by_name"].get(name)


# Earnings spec: (display_label, group, source_header, always_show)
_EARNINGS_SPEC = [
    ("حقوق پایه", _GROUP_MOSTAMAR, "حقوق ثابت ماهیانه", True),
    ("حق مسکن", _GROUP_MOSTAMAR, "حق مسکن", False),
    ("حق خواروبار", _GROUP_MOSTAMAR, "حق بن", False),
    ("حق مسئولیت", _GROUP_MOSTAMAR, "حق مسئولیت", False),
    ("حق اولاد", _GROUP_MOSTAMAR, "حق اولاد", False),
    ("حق تاهل", _GROUP_MOSTAMAR, "حق تاهل", False),
    ("پایه سنوات", _GROUP_MOSTAMAR, "پایه سنوات", False),
    ("مبلغ اضافه کاری", _GROUP_GHEYR_MOSTAMAR, "اضافه کار", False),
    ("جمعه کاری", _GROUP_GHEYR_MOSTAMAR, "جمعه کاری", False),
    ("شبکاری", _GROUP_GHEYR_MOSTAMAR, "شبکاری", False),
    ("عیدی", _GROUP_GHEYR_MOSTAMAR, "عیدی 1404", False),
    ("پاداش بهره وری", _GROUP_GHEYR_MOSTAMAR, "پاداش بهره وری", False),
    ("مرخصی استفاده نشده", _GROUP_GHEYR_MOSTAMAR, "مرخصی استفاده نشده", False),
    ("فوق العاده ماموریت", _GROUP_GHEYR_MOSTAMAR, "فوق العاده ماموریت", False),
]


def _resolve_earning_col(idx: dict, group: str, header: str) -> int | None:
    """Group-pinned lookup with light fuzzy fallback for drifting headers."""
    col = _find(idx, header, group=group)
    if col is not None:
        return col
    # Fuzzy: any column in this group whose name contains the header stem.
    stem = _norm(header).split(" ")[0]
    for (g, name), c in idx["by_group_name"].items():
        if g == _norm(group) and stem and stem in name:
            return c
    return None


def parse_payroll(
    xlsx_bytes: bytes,
    *,
    employer: str | None = None,
    month_override: str | None = None,
) -> dict:
    """Parse the payroll workbook into per-employee payslip records.

    Returns ``{'month', 'employer', 'records', 'warnings', 'columns_ok'}``.
    Missing expected group/column → ``columns_ok=False`` + a warning naming the
    missing header (never raises on a recoverable structural gap).
    """
    warnings: list[str] = []
    columns_ok = True

    # Zip-bomb guard BEFORE openpyxl inflates the archive in memory (a payroll
    # .xlsx is a zip container — a crafted small upload can otherwise OOM the
    # worker). Reuses the chat-attachment guard; map its rejection to a plain
    # ValueError so the payroll routers' ``except Exception`` surfaces a clean
    # legacy 400 (this module stays DB-/FastAPI-free, so no HTTP imports here).
    try:
        _guard_office_xml(xlsx_bytes)
    except _ZipBombError as exc:
        raise ValueError(f"payroll file rejected by zip-bomb guard: {exc}") from exc

    # NOTE: read_only=True is NOT usable here — openpyxl's ReadOnlyWorksheet
    # exposes no ``merged_cells`` attribute, and the 3-row merged header bands
    # are resolved via ``ws.merged_cells.ranges`` (_forward_fill_row). So we
    # keep the default loader but only AFTER the zip-bomb guard, and bound the
    # used range below.
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), data_only=True)
    ws = wb.active
    month = month_override or ws.title
    employer_name = employer or _DEFAULT_EMPLOYER

    n_cols = ws.max_column or 0
    n_rows = ws.max_row or 0
    if n_rows > _MAX_PAYROLL_ROWS or n_cols > _MAX_PAYROLL_COLS:
        raise ValueError(
            f"payroll sheet too large: {n_rows} rows x {n_cols} cols "
            f"(max {_MAX_PAYROLL_ROWS} x {_MAX_PAYROLL_COLS})"
        )

    idx = _build_column_index(ws, n_cols)

    # --- Resolve the columns we depend on ---------------------------------
    col_radif = _find(idx, "ردیف")
    col_name = _find(idx, "نام و نام خانوادگی")
    col_code = _find(idx, "کد پرسنلی")
    col_workdays = _find(idx, "تعداد روز کارکرد")
    col_overtime = _find(idx, "ساعت اضافه کار")
    col_total_mostamar = _find(idx, "جمع کل مزایا مستمر نقدی")
    col_total_gheyr = _find(idx, "جمع کل مزایا غیر مستمر نقدی")
    col_insurance = _find(idx, "حق بیمه سهم کارکنان (7%)")
    col_tax = _find(idx, "مالیات حقوق")
    col_loan = _find(idx, "وام")
    col_advance = _find(idx, "مساعده")
    col_net = _find(idx, "خالص پرداختنی")

    required = {
        "ردیف": col_radif,
        "نام و نام خانوادگی": col_name,
        "کد پرسنلی": col_code,
        "جمع کل مزایا مستمر نقدی": col_total_mostamar,
        "جمع کل مزایا غیر مستمر نقدی": col_total_gheyr,
        "حق بیمه سهم کارکنان (7%)": col_insurance,
        "خالص پرداختنی": col_net,
    }
    for header, col in required.items():
        if col is None:
            columns_ok = False
            warnings.append(f"ستون مورد انتظار یافت نشد: «{header}»")

    if col_radif is None or col_name is None:
        # Cannot identify employee rows at all — bail with empty records.
        return {
            "month": month,
            "employer": employer_name,
            "records": [],
            "warnings": warnings,
            "columns_ok": False,
        }

    # Pre-resolve earning columns once.
    earning_cols: list[tuple[str, int | None, bool]] = []
    for label, group, header, always in _EARNINGS_SPEC:
        col = _resolve_earning_col(idx, group, header)
        earning_cols.append((label, col, always))

    records: list[dict] = []
    for row in range(_FIRST_DATA_ROW, ws.max_row + 1):
        radif = ws.cell(row=row, column=col_radif).value
        name_val = ws.cell(row=row, column=col_name).value
        name = _norm(name_val)

        # Employee iff ردیف is an int AND name non-empty AND not the totals row.
        if not isinstance(radif, int):
            continue
        if not name or name == "جمع کل":
            continue

        def g(col: int | None) -> object:
            return ws.cell(row=row, column=col).value if col else None

        # Earnings: ordered, non-zero only (حقوق پایه always present).
        earnings: list[dict] = []
        for label, col, always in earning_cols:
            amount = _num(g(col))
            if amount or always:
                earnings.append({"label": label, "amount": amount})

        earnings_total = _num(g(col_total_mostamar)) + _num(g(col_total_gheyr))
        line_sum = sum(e["amount"] for e in earnings)
        if abs(line_sum - earnings_total) > 1:
            warnings.append(
                f"ردیف {radif} ({name}): جمع مزایا ({earnings_total:,}) با مجموع "
                f"خطوط ({line_sum:,}) همخوانی ندارد"
            )

        # Deductions: بیمه always, then مالیات + any non-zero.
        deductions: list[dict] = []
        insurance = _num(g(col_insurance))
        deductions.append({"label": "بیمه تامین اجتماعی سهم کارمند", "amount": insurance})
        tax = _num(g(col_tax))
        deductions.append({"label": "مالیات", "amount": tax})
        deductions_total = insurance + tax

        installment = _num(g(col_loan))
        advance = _num(g(col_advance))
        net = _num(g(col_net))

        records.append({
            "code": _norm(g(col_code)),
            "name": name,
            "work_days": _raw_num(g(col_workdays)),
            "overtime_hours": _raw_num(g(col_overtime)),
            "earnings": earnings,
            "earnings_total": earnings_total,
            "deductions": deductions,
            "deductions_total": deductions_total,
            "installment": installment,
            "advance": advance,
            "net": net,
        })

    return {
        "month": month,
        "employer": employer_name,
        "records": records,
        "warnings": warnings,
        "columns_ok": columns_ok,
    }


def build_payslip_zip(
    records: list[dict],
    *,
    employer: str,
    month: str,
    progress_cb=None,
) -> bytes:
    """Render every record to PDF and pack into an in-memory zip.

    Entry name = ``f"{name}-{code}.pdf"`` (unicode-preserving sanitize, basename
    only). Duplicate names get a ``-N`` suffix so no slip silently overwrites
    another. ``progress_cb(done, total)`` fires after each rendered slip.
    """
    total = len(records)
    buf = io.BytesIO()
    used: dict[str, int] = {}
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for i, record in enumerate(records, start=1):
            pdf = render_payslip(record, employer=employer, month=month)
            stem = _safe_component(f"{record.get('name', '')}-{record.get('code', '')}")
            entry = f"{stem}.pdf"
            if entry in used:
                used[entry] += 1
                entry = f"{stem}-{used[entry]}.pdf"
            else:
                used[entry] = 0
            zf.writestr(entry, pdf)
            if progress_cb is not None:
                progress_cb(i, total)
    return buf.getvalue()


__all__ = ["parse_payroll", "build_payslip_zip"]
