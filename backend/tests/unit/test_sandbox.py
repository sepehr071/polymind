"""Unit tests for the Data Analyzer sandbox execution layer.

DB-free on purpose (they live in tests/unit/, not tests/api/, so the api
conftest's autouse Postgres TRUNCATE fixture never loads). They exercise the
real ``backend/sandbox/runner.py`` on the dedicated ``.venv-sandbox`` via
``SandboxService`` in dev mode (plain subprocess, no OS isolation).

OS-isolation assertions (network / env denial) are Linux-only and skipped on
Windows with a note — they run on prod under bubblewrap.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

# Make sure the sandbox runs in dev mode regardless of the ambient env.
os.environ.setdefault("DATA_SANDBOX_MODE", "dev")

from app.services.data_analysis_service import build_chart_payload  # noqa: E402
from app.services.sandbox_service import (  # noqa: E402
    _RUNNER_PATH,
    SandboxService,
    SandboxUnavailableError,
    _sandbox_python,
)

pytestmark = pytest.mark.skipif(
    _sandbox_python() is None,
    reason="sandbox venv (.venv-sandbox) not provisioned — see backend/sandbox/README.md",
)


# --------------------------------------------------------------------------- #
# Fixtures.
# --------------------------------------------------------------------------- #
def _write(workdir: str, *, data: dict[str, str] | None = None, code: str | None = None) -> None:
    data_dir = os.path.join(workdir, "data")
    run_dir = os.path.join(workdir, "run")
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(run_dir, exist_ok=True)
    for name, content in (data or {}).items():
        with open(os.path.join(data_dir, name), "w", encoding="utf-8", newline="") as fh:
            fh.write(content)
    if code is not None:
        with open(os.path.join(run_dir, "code.py"), "w", encoding="utf-8") as fh:
            fh.write(code)


def _write_parquet(data_dir: str, name: str, frame_code: str) -> None:
    """Materialize a parquet fixture USING THE SANDBOX PYTHON.

    The test venv has no pandas/pyarrow (those live only in .venv-sandbox), so we
    can't build a parquet file in-process. Shell out to the sandbox interpreter to
    write one. ``frame_code`` is python that defines a DataFrame ``df``.
    """
    os.makedirs(data_dir, exist_ok=True)
    py = _sandbox_python()
    assert py is not None
    out_path = os.path.join(data_dir, name).replace("\\", "\\\\")
    script = (
        "import pandas as pd\n"
        f"{frame_code}\n"
        f"df.to_parquet(r'''{out_path}''')\n"
    )
    proc = subprocess.run([py, "-c", script], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def _profile_direct(workdir: str, *, env_extra: dict[str, str] | None = None) -> dict:
    """Run runner.py ``--profile`` DIRECTLY on the sandbox python and return its JSON.

    SandboxService scrubs the child env down to a fixed keep-list, so an env var
    like ``DATA_MAX_INGEST_ROWS`` can't be forwarded through ``.profile()``. To
    exercise the env-driven ingest cap we spawn the runner ourselves (mirroring the
    ``_write_parquet`` shell-out pattern) with the var injected.
    """
    py = _sandbox_python()
    assert py is not None
    env = dict(os.environ)
    env.update(env_extra or {})
    proc = subprocess.run(
        [py, _RUNNER_PATH, "--workdir", workdir, "--profile"],
        capture_output=True, text=True, env=env,
    )
    assert proc.returncode == 0, proc.stderr
    with open(os.path.join(workdir, "run", "profile.json"), "r", encoding="utf-8") as fh:
        return json.load(fh)


CSV_SALES = (
    "region,income\n"
    "north,100\n"
    "north,200\n"
    "south,50\n"
    "south,150\n"
    "west,300\n"
)


# --------------------------------------------------------------------------- #
# 1. Dev-mode happy path — real numbers, real dtypes.
# --------------------------------------------------------------------------- #
def test_run_groupby_mean_table_artifact(tmp_path):
    workdir = str(tmp_path)
    _write(workdir, data={"sales.csv": CSV_SALES})
    code = "show_table(df.groupby('region')['income'].mean().reset_index())"

    result = SandboxService.run(workdir=workdir, code=code, timeout_s=20)

    assert result["error"] is None, result
    assert result["timed_out"] is False
    assert len(result["artifacts"]) == 1
    table = result["artifacts"][0]
    assert table["type"] == "table"
    assert table["total_rows"] == 3
    by_region = {r["region"]: r["income"] for r in table["rows"]}
    # north = (100+200)/2 = 150 ; south = (50+150)/2 = 100 ; west = 300
    assert by_region == {"north": 150.0, "south": 100.0, "west": 300.0}
    # Real dtypes preserved (mean of ints → float64), not stringified.
    dtypes = {c["key"]: c["dtype"] for c in table["columns"]}
    assert dtypes["income"] == "float64"


def test_run_captures_stdout(tmp_path):
    workdir = str(tmp_path)
    _write(workdir, data={"sales.csv": CSV_SALES})
    result = SandboxService.run(workdir=workdir, code="print('hello', df.shape[0])", timeout_s=20)
    assert result["error"] is None
    assert "hello 5" in result["stdout"]


def test_run_show_chart_artifact(tmp_path):
    workdir = str(tmp_path)
    _write(workdir, data={"sales.csv": CSV_SALES})
    code = (
        "agg = df.groupby('region')['income'].sum().reset_index()\n"
        "show_chart('bar', agg, x='region', y='income', title='Income by region')\n"
    )
    result = SandboxService.run(workdir=workdir, code=code, timeout_s=20)
    assert result["error"] is None, result
    chart = result["artifacts"][0]
    assert chart["type"] == "chart"
    assert chart["kind"] == "bar"
    # y2 is always present in the encoding now (None when unused).
    assert chart["encoding"] == {"x": "region", "y": "income", "series": None, "y2": None}
    assert chart["title"] == "Income by region"
    assert {row["region"] for row in chart["data"]} == {"north", "south", "west"}


# --------------------------------------------------------------------------- #
# 1b. New artifact kinds + helpers (the upgrade contract).
# --------------------------------------------------------------------------- #
def test_new_chart_kinds_accepted(tmp_path):
    """histogram / box / heatmap / combo are valid kinds, y2 flows through."""
    workdir = str(tmp_path)
    _write(workdir, data={"sales.csv": CSV_SALES})
    code = (
        "show_chart('histogram', df, x='income', title='dist')\n"
        "show_chart('box', df, x='region', y='income')\n"
        "show_chart('heatmap', df, x='region', y='region', y2='income')\n"
        "show_chart('combo', df, x='region', y='income', y2='income', title='combo')\n"
    )
    result = SandboxService.run(workdir=workdir, code=code, timeout_s=20)
    assert result["error"] is None, result
    kinds = [a["kind"] for a in result["artifacts"]]
    assert kinds == ["histogram", "box", "heatmap", "combo"]
    heatmap = result["artifacts"][2]
    assert heatmap["encoding"]["y2"] == "income"
    combo = result["artifacts"][3]
    assert combo["encoding"]["x"] == "region"
    assert combo["encoding"]["y"] == "income"
    assert combo["encoding"]["y2"] == "income"


def test_show_metric_contract_shape(tmp_path):
    workdir = str(tmp_path)
    _write(workdir, data={"sales.csv": CSV_SALES})
    code = (
        "show_metric('Total income', float(df['income'].sum()), delta=0.12, "
        "unit='USD', direction='up-good', spark=[1, 2, 3])\n"
        # value passes through as a string when not numeric; bad direction → default.
        "show_metric('Label', '$1.2M', direction='sideways')\n"
    )
    result = SandboxService.run(workdir=workdir, code=code, timeout_s=20)
    assert result["error"] is None, result
    m0 = result["artifacts"][0]
    assert m0 == {
        "type": "metric", "label": "Total income", "value": 800.0,
        "delta": 0.12, "unit": "USD", "direction": "up-good",
        "spark": [1.0, 2.0, 3.0],
    }
    m1 = result["artifacts"][1]
    assert m1["value"] == "$1.2M"          # non-numeric → stringified
    assert m1["direction"] == "up-good"    # invalid direction → default
    assert m1["delta"] is None and m1["spark"] is None and m1["unit"] is None


def test_show_insight_contract_shape(tmp_path):
    workdir = str(tmp_path)
    _write(workdir, data={"sales.csv": CSV_SALES})
    code = (
        "show_insight('West leads revenue.', level='success')\n"
        "show_insight('Fallback level.', level='bogus')\n"
    )
    result = SandboxService.run(workdir=workdir, code=code, timeout_s=20)
    assert result["error"] is None, result
    a0, a1 = result["artifacts"]
    assert a0 == {"type": "insight", "text": "West leads revenue.", "level": "success"}
    assert a1["level"] == "info"  # invalid level → default


# --------------------------------------------------------------------------- #
# 1c. New file formats (parquet / jsonl) + DuckDB sql().
# --------------------------------------------------------------------------- #
def test_parquet_loads_into_df(tmp_path):
    workdir = str(tmp_path)
    data_dir = os.path.join(workdir, "data")
    _write_parquet(
        data_dir, "metrics.parquet",
        "df = pd.DataFrame({'city': ['a', 'b', 'c'], 'pop': [10, 20, 30]})",
    )
    code = "show_table(df)"
    result = SandboxService.run(workdir=workdir, code=code, timeout_s=20)
    assert result["error"] is None, result
    table = result["artifacts"][0]
    assert table["total_rows"] == 3
    cols = {c["key"] for c in table["columns"]}
    assert cols == {"city", "pop"}
    # int dtype preserved through the parquet round-trip (not stringified).
    dtypes = {c["key"]: c["dtype"] for c in table["columns"]}
    assert dtypes["pop"].startswith("int")


JSONL_DATA = (
    '{"name": "amir", "score": 90}\n'
    '{"name": "sara", "score": 75}\n'
    '{"name": "reza", "score": 85}\n'
)


def test_jsonl_loads_into_df(tmp_path):
    workdir = str(tmp_path)
    _write(workdir, data={"people.jsonl": JSONL_DATA})
    code = "show_table(df)"
    result = SandboxService.run(workdir=workdir, code=code, timeout_s=20)
    assert result["error"] is None, result
    table = result["artifacts"][0]
    assert table["total_rows"] == 3
    cols = {c["key"] for c in table["columns"]}
    assert cols == {"name", "score"}
    by_name = {r["name"]: r["score"] for r in table["rows"]}
    assert by_name == {"amir": 90, "sara": 75, "reza": 85}


def test_sql_joins_two_registered_frames(tmp_path):
    """sql() registers every frame under its readable name; join across two."""
    workdir = str(tmp_path)
    _write(workdir, data={
        "people.csv": "id,name\n1,amir\n2,sara\n",
        "orders.csv": "person_id,amount\n1,100\n1,50\n2,200\n",
    })
    code = (
        "out = sql('''\n"
        "  SELECT p.name, SUM(o.amount) AS total\n"
        '  FROM "people" p JOIN "orders" o ON p.id = o.person_id\n'
        "  GROUP BY p.name ORDER BY total DESC\n"
        "''')\n"
        "show_table(out, name='Totals by person')"
    )
    result = SandboxService.run(workdir=workdir, code=code, timeout_s=20)
    assert result["error"] is None, result
    table = result["artifacts"][0]
    by_name = {r["name"]: r["total"] for r in table["rows"]}
    # amir = 100 + 50 = 150 ; sara = 200
    assert by_name == {"amir": 150, "sara": 200}


def test_sql_df_alias_available(tmp_path):
    """The primary table is queryable as `df` in addition to its readable name."""
    workdir = str(tmp_path)
    _write(workdir, data={"sales.csv": CSV_SALES})
    code = (
        "out = sql('SELECT region, SUM(income) AS s FROM df GROUP BY region')\n"
        "show_table(out)"
    )
    result = SandboxService.run(workdir=workdir, code=code, timeout_s=20)
    assert result["error"] is None, result
    rows = {r["region"]: r["s"] for r in result["artifacts"][0]["rows"]}
    assert rows == {"north": 300, "south": 200, "west": 300}


# --------------------------------------------------------------------------- #
# 2. Profile pass — correct shape / columns / dtypes.
# --------------------------------------------------------------------------- #
def test_profile_shape_columns_dtypes(tmp_path):
    workdir = str(tmp_path)
    _write(workdir, data={"sales.csv": CSV_SALES})

    profile = SandboxService.profile(workdir=workdir, timeout_s=30)

    assert profile["manifest"], profile
    entry = profile["manifest"][0]
    assert entry["shape"] == [5, 2]
    assert entry["columns"] == ["region", "income"]
    assert entry["dtypes"]["income"] == "int64"
    assert entry["dtypes"]["region"] == "object"
    # Preview markdown is compact + mentions shape and column names.
    md = profile["preview_markdown"]
    assert "5 rows x 2 columns" in md
    assert "region" in md and "income" in md


def test_profile_preview_has_numeric_and_categorical_summaries(tmp_path):
    """The enriched preview surfaces a describe()-style numeric table AND a
    categorical top-values section so the model can reason BEFORE writing code."""
    workdir = str(tmp_path)
    _write(workdir, data={"sales.csv": CSV_SALES})

    profile = SandboxService.profile(workdir=workdir, timeout_s=30)
    md = profile["preview_markdown"]

    # Numeric summary: a describe()-style table over `income` (no truncation flag).
    assert "numeric summary:" in md
    assert "| column | count | mean | std | min | 25% | 50% | 75% | max |" in md
    # mean of 100,200,50,150,300 = 160 (4-sig-fig formatting → "160").
    assert "| income | 5 | 160 |" in md

    # Categorical summary: nunique + top value_counts for `region`.
    assert "categorical summary (top values):" in md
    # north appears twice, south twice, west once → "north: 2" / "south: 2".
    assert "`region`: 3 unique" in md
    assert "north: 2" in md and "west: 1" in md

    # Not truncated → no large-file banner.
    assert "LARGE FILE" not in md


def test_profile_ingest_cap_truncates_and_flags(tmp_path):
    """A frame over a tiny DATA_MAX_INGEST_ROWS loads CAPPED, the preview shows the
    loud truncation banner, and the manifest carries truncated=True + loaded_rows."""
    workdir = str(tmp_path)
    # 10 data rows; cap to 3.
    rows = "region,income\n" + "".join(f"r{i},{i * 10}\n" for i in range(10))
    _write(workdir, data={"big.csv": rows})

    profile = _profile_direct(workdir, env_extra={"DATA_MAX_INGEST_ROWS": "3"})

    entry = profile["manifest"][0]
    assert entry["truncated"] is True
    assert entry["loaded_rows"] == 3
    assert entry["shape"][0] == 3          # only the first 3 rows are in memory

    md = profile["preview_markdown"]
    assert "LARGE FILE" in md
    assert "only the first 3 rows were loaded" in md
    assert "over a SAMPLE" in md


def test_profile_no_cap_loads_all_rows(tmp_path):
    """Sanity: with the default (huge) cap, a small frame is NOT flagged truncated."""
    workdir = str(tmp_path)
    rows = "region,income\n" + "".join(f"r{i},{i}\n" for i in range(10))
    _write(workdir, data={"small.csv": rows})

    profile = _profile_direct(workdir)  # no env override → default 1,000,000 cap
    entry = profile["manifest"][0]
    assert entry["truncated"] is False
    assert entry["loaded_rows"] == 10
    assert "LARGE FILE" not in profile["preview_markdown"]


def test_profile_multi_sheet_excel(tmp_path):
    """Excel with 2 sheets → 2 manifest entries (one per sheet)."""
    openpyxl = pytest.importorskip(
        "openpyxl",
        reason="openpyxl is in the sandbox venv, not the test venv; skip if absent here",
    )
    workdir = str(tmp_path)
    data_dir = os.path.join(workdir, "data")
    os.makedirs(data_dir, exist_ok=True)
    wb = openpyxl.Workbook()
    s1 = wb.active
    s1.title = "people"
    s1.append(["name", "age"])
    s1.append(["amir", 30])
    s1.append(["sara", 25])
    s2 = wb.create_sheet("orders")
    s2.append(["id", "total"])
    s2.append([1, 99.5])
    wb.save(os.path.join(data_dir, "book.xlsx"))

    profile = SandboxService.profile(workdir=workdir, timeout_s=30)
    names = {e["name"] for e in profile["manifest"]}
    assert any("people" in n for n in names)
    assert any("orders" in n for n in names)


# --------------------------------------------------------------------------- #
# 3. Exception capture — no crash, error + traceback surfaced.
# --------------------------------------------------------------------------- #
def test_exception_is_captured(tmp_path):
    workdir = str(tmp_path)
    _write(workdir, data={"sales.csv": CSV_SALES})
    code = "raise ValueError('boom from user code')"

    result = SandboxService.run(workdir=workdir, code=code, timeout_s=20)

    assert result["timed_out"] is False
    assert result["error"] is not None
    assert "ValueError" in result["error"]
    assert "boom from user code" in result["error"]
    # Full traceback lands in stderr.
    assert "Traceback" in result["stderr"]
    assert result["artifacts"] == []


def test_missing_column_keyerror_captured(tmp_path):
    workdir = str(tmp_path)
    _write(workdir, data={"sales.csv": CSV_SALES})
    result = SandboxService.run(workdir=workdir, code="print(df['nope'])", timeout_s=20)
    assert result["error"] is not None
    assert "KeyError" in result["error"]


# --------------------------------------------------------------------------- #
# 4. Timeout — wall-clock kill of a busy loop.
# --------------------------------------------------------------------------- #
def test_timeout_kills_busy_loop(tmp_path):
    workdir = str(tmp_path)
    _write(workdir, data={"sales.csv": CSV_SALES})
    result = SandboxService.run(workdir=workdir, code="while True:\n    pass\n", timeout_s=3)
    assert result["timed_out"] is True
    # No result.json was written (process killed) → synthesized timeout result.
    assert result["error"] is not None


# --------------------------------------------------------------------------- #
# Helpers / contract.
# --------------------------------------------------------------------------- #
def test_available_true_in_dev():
    assert SandboxService.available() is True


def test_prod_without_bwrap_fails_closed(tmp_path, monkeypatch):
    """Fail-closed contract: prod mode + no bwrap/firejail → unavailable + raises.

    Simulated on any OS by forcing prod mode and making the launcher lookup miss;
    no real bwrap needed (we never reach the spawn — it raises first).
    """
    import app.services.sandbox_service as svc

    monkeypatch.setattr(svc, "_is_dev_mode", lambda: False)
    monkeypatch.setattr(svc, "_which", lambda name: None)

    assert SandboxService.available() is False

    workdir = str(tmp_path)
    _write(workdir, data={"sales.csv": CSV_SALES})
    with pytest.raises(SandboxUnavailableError):
        SandboxService.run(workdir=workdir, code="print(1)", timeout_s=5)


def test_build_chart_payload_normalizes():
    artifact = {
        "type": "chart",
        "kind": "Line",
        "encoding": {"x": "month", "y": "sales", "series": "region"},
        "data": [{"month": "jan", "sales": 10, "region": "n"}],
        "title": "Trend",
    }
    out = build_chart_payload(artifact)
    assert out["type"] == "chart"
    assert out["kind"] == "line"
    assert out["encoding"] == {"x": "month", "y": "sales", "series": "region"}
    assert out["data"] == artifact["data"]
    assert out["title"] == "Trend"


def test_build_chart_payload_passes_tables_through():
    table = {"type": "table", "columns": [], "rows": [], "total_rows": 0}
    assert build_chart_payload(table) is table


def test_run_no_artifacts_when_code_emits_none(tmp_path):
    workdir = str(tmp_path)
    _write(workdir, data={"sales.csv": CSV_SALES})
    result = SandboxService.run(workdir=workdir, code="x = df.sum(numeric_only=True)", timeout_s=20)
    assert result["error"] is None
    assert result["artifacts"] == []


# --------------------------------------------------------------------------- #
# Linux-only OS-isolation assertions. On Windows (dev) there is NO isolation by
# design, so these are skipped; they run on prod under bubblewrap.
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(
    sys.platform == "win32" or os.environ.get("DATA_SANDBOX_MODE", "dev") == "dev",
    reason="OS isolation only enforced under bwrap in prod (Linux); dev = no isolation",
)
def test_network_is_denied_in_prod(tmp_path):
    workdir = str(tmp_path)
    _write(workdir, data={"sales.csv": CSV_SALES})
    code = (
        "import socket\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1', 53), timeout=3)\n"
        "    print('NET_OK')\n"
        "except Exception as e:\n"
        "    print('NET_BLOCKED', type(e).__name__)\n"
    )
    result = SandboxService.run(workdir=workdir, code=code, timeout_s=20)
    assert "NET_BLOCKED" in result["stdout"], result


@pytest.mark.skipif(
    sys.platform == "win32" or os.environ.get("DATA_SANDBOX_MODE", "dev") == "dev",
    reason="env scrubbing observable only under the real sandbox launch (Linux prod)",
)
def test_secrets_not_leaked_to_sandbox_env(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-should-not-appear")
    workdir = str(tmp_path)
    _write(workdir, data={"sales.csv": CSV_SALES})
    code = "import os; print('KEY=' + os.environ.get('OPENROUTER_API_KEY', 'ABSENT'))"
    result = SandboxService.run(workdir=workdir, code=code, timeout_s=20)
    assert "KEY=ABSENT" in result["stdout"], result
