#!/usr/bin/env python3
"""bench_sandbox.py — resource profiler for the Data Analyzer sandbox.

Drives representative analyst workloads (the kinds the LLM generates) through the
ACTUAL ``runner.py`` exec path and measures, per run, **peak RSS, CPU time, and
wall time** — plus an optional **concurrency stress** to answer "how many
simultaneous analyses does this box survive?". This is how you size
``DATA_SANDBOX_MAX_CONCURRENCY`` / ``DATA_SANDBOX_MEM_MB`` for a given host.

It is NOT a pass/fail test — it prints numbers and writes JSON/CSV.

Run it with the SANDBOX venv python (the one that has pandas/numpy/scipy/…):

    cd /opt/unichat/backend/sandbox            # (or backend/sandbox locally)
    ./.venv-sandbox/bin/python bench_sandbox.py                 # full sequential sweep
    ./.venv-sandbox/bin/python bench_sandbox.py --quick         # tiny, ~30s smoke of every workload
    ./.venv-sandbox/bin/python bench_sandbox.py --sizes 100000,1000000 --workloads kmeans,forecast
    ./.venv-sandbox/bin/python bench_sandbox.py --mem-cap-mb 1024     # apply the prod RLIMIT_AS, flag OOMs
    ./.venv-sandbox/bin/python bench_sandbox.py --concurrency 3 --workload kmeans --size 1000000

Measurement notes:
- Each run is a fork+exec of ``python runner.py --workdir <wd>`` (the same entry
  the backend spawns). Per-child resources come from ``os.wait4`` rusage:
  ``ru_maxrss`` = peak RSS (KB on Linux), ``ru_utime+ru_stime`` = CPU seconds.
- ``--mem-cap-mb`` sets ``RLIMIT_AS`` on the child (mirrors the prod sandbox cap),
  so a run that would OOM at that cap fails LOUD here instead of on a user.
- BLAS/OMP threads are pinned (``--threads``, default 2) to match prod.
- bwrap itself adds only a few MB; this measures the *workload* footprint, which
  is what drives box sizing. The numbers are a slight UNDER-estimate of the full
  jailed process (bwrap + tmpfs), so leave headroom.

Linux only (os.fork + /proc). That is the deployment target.
"""
from __future__ import annotations

import argparse
import json
import os
import resource
import shutil
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RUNNER = os.path.join(HERE, "runner.py")
PYTHON = sys.executable  # the venv python running THIS script drives the children


# --------------------------------------------------------------------------- #
# Synthetic dataset — a scalable clone of test-data/sample_sales.csv so the workloads hit
# realistic columns (a datetime spanning ~12 months, low/mid/high-cardinality
# categoricals, and numeric measures).
# --------------------------------------------------------------------------- #
REGIONS = ["North", "South", "East", "West", "Central"]
CATEGORIES = ["Electronics", "Office", "Furniture", "Garden", "Toys", "Sports", "Food", "Apparel"]


def make_dataset(path: str, n_rows: int) -> None:
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(42)
    start = np.datetime64("2025-01-01")
    dates = start + rng.integers(0, 365, n_rows).astype("timedelta64[D]")
    products = [f"P{i:03d}" for i in range(40)]
    reps = [f"rep_{i:02d}" for i in range(20)]
    units = rng.integers(1, 100, n_rows)
    price = np.round(rng.uniform(5, 1000, n_rows), 2)
    df = pd.DataFrame({
        "order_date": dates,
        "region": rng.choice(REGIONS, n_rows),
        "category": rng.choice(CATEGORIES, n_rows),
        "product": rng.choice(products, n_rows),
        "units_sold": units,
        "unit_price": price,
        "revenue": np.round(units * price, 2),
        "sales_rep": rng.choice(reps, n_rows),
    })
    df.to_csv(path, index=False)


# --------------------------------------------------------------------------- #
# Workloads — each is a `code.py` body run against the preloaded `df`. They mirror
# the new analyst capabilities (stats, ML, forecasting, DuckDB, chart artifacts).
# `pd`/`np`/`show_*`/`sql` are injected by the runner.
# --------------------------------------------------------------------------- #
WORKLOADS: dict[str, str] = {
    # Pure data-load cost (the runner always loads df). Subtract this from the
    # others to isolate the analysis cost from the ingest cost.
    "baseline": "pass\n",

    "profile": """
print(df.shape)
print(df.dtypes)
print(df.describe(include='all').head())
print(df['region'].value_counts())
g = df.groupby('region')['revenue'].agg(['sum', 'mean', 'count'])
print(g)
show_table(g.reset_index(), name='By region')
""",

    "groupby": """
top = (df.groupby(['region', 'category'], as_index=False)['revenue']
         .sum().sort_values('revenue', ascending=False).head(20))
print(top)
piv = df.pivot_table(index='region', columns='category', values='revenue', aggfunc='sum')
print(piv)
show_table(top, name='Top region x category')
""",

    "corr": """
num = df.select_dtypes('number')
c = num.corr()
print(c)
m = c.reset_index().melt('index', var_name='col', value_name='r')
show_chart('heatmap', m, x='index', y='col', y2='r', title='Correlation')
""",

    "anova": """
from scipy import stats
groups = [g['revenue'].to_numpy() for _, g in df.groupby('region')]
f, p = stats.f_oneway(*groups)
print('ANOVA F=%.4f p=%.4g' % (f, p))
a = df.loc[df['region'] == 'North', 'revenue']
b = df.loc[df['region'] == 'South', 'revenue']
print('t-test', stats.ttest_ind(a, b))
ct = pd.crosstab(df['region'], df['category'])
print('chi2', stats.chi2_contingency(ct)[:2])
""",

    "ols": """
import statsmodels.api as sm
X = sm.add_constant(df[['units_sold', 'unit_price']])
res = sm.OLS(df['revenue'], X).fit()
print(res.params)
print('R2', res.rsquared)
""",

    "kmeans": """
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
Xs = StandardScaler().fit_transform(df[['units_sold', 'unit_price', 'revenue']])
km = KMeans(n_clusters=5, n_init=3, random_state=0).fit(Xs)
out = df.assign(cluster=km.labels_)
print(out['cluster'].value_counts())
show_table(out.groupby('cluster')[['units_sold', 'unit_price', 'revenue']].mean().reset_index(), name='Clusters')
""",

    "forecast": """
from statsmodels.tsa.holtwinters import ExponentialSmoothing
s = (df.assign(m=pd.to_datetime(df['order_date']).dt.to_period('M'))
       .groupby('m')['revenue'].sum())
s.index = s.index.to_timestamp()
fit = ExponentialSmoothing(s, trend='add', seasonal=None).fit()
fc = fit.forecast(3)
print(s.tail())
print('forecast', fc.to_dict())
fr = pd.concat([s.rename('value').reset_index().assign(series='actual'),
                fc.rename('value').reset_index().assign(series='forecast').rename(columns={'index': 'm'})])
show_chart('line', fr, x='m', y='value', series='series', title='Revenue forecast')
""",

    "duckdb": """
import duckdb
con = duckdb.connect()
con.register('df', df)
print(con.execute("SELECT region, category, SUM(revenue) rev, AVG(unit_price) p "
                  "FROM df GROUP BY 1, 2 ORDER BY rev DESC LIMIT 10").df())
print(con.execute("SELECT region, "
                  "SUM(revenue) OVER (PARTITION BY region ORDER BY order_date) running "
                  "FROM df LIMIT 5").df())
con.close()
""",

    "charts": """
top = df.groupby('product', as_index=False)['revenue'].sum().nlargest(20, 'revenue')
show_chart('bar', top, x='product', y='revenue', title='Top products')
show_table(top, name='Top products')
monthly = (df.assign(m=pd.to_datetime(df['order_date']).dt.to_period('M').astype(str))
             .groupby('m', as_index=False)['revenue'].sum())
show_chart('line', monthly, x='m', y='revenue', title='Monthly')
show_metric('Total revenue', float(df['revenue'].sum()), unit='USD')
show_insight('Top product leads the pack.', level='success')
""",
}


# --------------------------------------------------------------------------- #
# A single measured run (fork + exec the real runner; rusage from wait4).
# --------------------------------------------------------------------------- #
def _prepare_workdir(root: str, dataset_path: str, code: str) -> str:
    wd = tempfile.mkdtemp(prefix="bench_", dir=root)
    os.makedirs(os.path.join(wd, "data"))
    os.makedirs(os.path.join(wd, "run"))
    # Symlink the (possibly large) dataset instead of copying it per run.
    link = os.path.join(wd, "data", os.path.basename(dataset_path))
    try:
        os.symlink(dataset_path, link)
    except OSError:
        shutil.copy2(dataset_path, link)
    with open(os.path.join(wd, "run", "code.py"), "w", encoding="utf-8") as fh:
        fh.write(code)
    return wd


def _child_env(threads: int) -> dict:
    env = dict(os.environ)
    env["OMP_NUM_THREADS"] = str(threads)
    env["OPENBLAS_NUM_THREADS"] = str(threads)
    env["MKL_NUM_THREADS"] = str(threads)
    env["NUMEXPR_NUM_THREADS"] = str(threads)
    return env


def _spawn(wd: str, mem_cap_mb: int, threads: int) -> int:
    """Fork+exec the runner on `wd`; return the child pid (caller reaps)."""
    env = _child_env(threads)
    out_fd = os.open(os.path.join(wd, "run", "stdout.txt"), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    err_fd = os.open(os.path.join(wd, "run", "stderr.txt"), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    pid = os.fork()
    if pid == 0:  # child
        try:
            os.dup2(out_fd, 1)
            os.dup2(err_fd, 2)
            if mem_cap_mb:
                cap = int(mem_cap_mb) * 1024 * 1024
                resource.setrlimit(resource.RLIMIT_AS, (cap, cap))
            os.execve(PYTHON, [PYTHON, RUNNER, "--workdir", wd], env)
        except BaseException:  # noqa: BLE001
            os._exit(127)
    os.close(out_fd)
    os.close(err_fd)
    return pid


def _reap(pid: int) -> tuple[int, "resource.struct_rusage"]:
    _, status, ru = os.wait4(pid, 0)
    return status, ru


def _read_result(wd: str) -> dict:
    try:
        with open(os.path.join(wd, "run", "result.json"), encoding="utf-8") as fh:
            r = json.load(fh)
        return {
            "error": r.get("error"),
            "timed_out": bool(r.get("timed_out")),
            "artifacts": len(r.get("artifacts") or []),
            "stdout_chars": len(r.get("stdout") or ""),
        }
    except (OSError, ValueError):
        # No result.json → the child died before writing (e.g. OOM-killed).
        return {"error": "no result.json (child died — likely OOM at the cap)",
                "timed_out": False, "artifacts": 0, "stdout_chars": 0}


def measure_one(dataset_path: str, code: str, root: str, mem_cap_mb: int, threads: int) -> dict:
    wd = _prepare_workdir(root, dataset_path, code)
    try:
        t0 = time.monotonic()
        pid = _spawn(wd, mem_cap_mb, threads)
        status, ru = _reap(pid)
        wall = time.monotonic() - t0
        res = _read_result(wd)
        ok = (status == 0) and not res["error"]
        return {
            "peak_rss_mb": round(ru.ru_maxrss / 1024.0, 1),  # KB→MB on Linux
            "cpu_s": round(ru.ru_utime + ru.ru_stime, 2),
            "wall_s": round(wall, 2),
            "exit_status": status,
            "ok": ok,
            "error": res["error"],
            "artifacts": res["artifacts"],
        }
    finally:
        shutil.rmtree(wd, ignore_errors=True)


# --------------------------------------------------------------------------- #
# System sampler — peak memory + load while N children run concurrently.
# --------------------------------------------------------------------------- #
def _meminfo_kb(key: str) -> int:
    with open("/proc/meminfo") as fh:
        for line in fh:
            if line.startswith(key + ":"):
                return int(line.split()[1])
    return 0


class _SystemSampler(threading.Thread):
    def __init__(self, interval: float = 0.05):
        super().__init__(daemon=True)
        self.interval = interval
        # NB: must NOT be named `_stop` — that shadows Thread._stop (a method the
        # threading internals call on fork/join), causing 'Event' not callable.
        self._stop_evt = threading.Event()
        self.min_avail_kb = _meminfo_kb("MemAvailable") or 10**12
        self.max_load = 0.0

    def run(self) -> None:
        while not self._stop_evt.is_set():
            self.min_avail_kb = min(self.min_avail_kb, _meminfo_kb("MemAvailable"))
            try:
                with open("/proc/loadavg") as fh:
                    self.max_load = max(self.max_load, float(fh.read().split()[0]))
            except OSError:
                pass
            time.sleep(self.interval)

    def stop(self) -> None:
        self._stop_evt.set()
        self.join(timeout=1)


def run_concurrency(dataset_path: str, code: str, root: str, k: int, mem_cap_mb: int, threads: int) -> dict:
    wds = [_prepare_workdir(root, dataset_path, code) for _ in range(k)]
    start_avail = _meminfo_kb("MemAvailable")
    sampler = _SystemSampler()
    sampler.start()
    t0 = time.monotonic()
    pids = [_spawn(wd, mem_cap_mb, threads) for wd in wds]
    runs = []
    for pid, wd in zip(pids, wds):
        status, ru = _reap(pid)
        res = _read_result(wd)
        runs.append({
            "peak_rss_mb": round(ru.ru_maxrss / 1024.0, 1),
            "cpu_s": round(ru.ru_utime + ru.ru_stime, 2),
            "ok": status == 0 and not res["error"],
            "error": res["error"],
        })
    wall = time.monotonic() - t0
    sampler.stop()
    for wd in wds:
        shutil.rmtree(wd, ignore_errors=True)
    peak_used_mb = round((start_avail - sampler.min_avail_kb) / 1024.0, 1)
    return {
        "concurrency": k,
        "total_wall_s": round(wall, 2),
        "system_peak_used_mb": peak_used_mb,
        "system_min_avail_mb": round(sampler.min_avail_kb / 1024.0, 1),
        "peak_load_1m": round(sampler.max_load, 2),
        "sum_child_rss_mb": round(sum(r["peak_rss_mb"] for r in runs), 1),
        "max_child_rss_mb": round(max(r["peak_rss_mb"] for r in runs), 1),
        "failures": sum(0 if r["ok"] else 1 for r in runs),
        "runs": runs,
    }


# --------------------------------------------------------------------------- #
# Host facts + reporting.
# --------------------------------------------------------------------------- #
def host_facts() -> dict:
    return {
        "cpus": os.cpu_count(),
        "mem_total_mb": round(_meminfo_kb("MemTotal") / 1024.0),
        "mem_available_mb": round(_meminfo_kb("MemAvailable") / 1024.0),
        "python": sys.version.split()[0],
        "runner": RUNNER,
    }


def _fmt_size(n: int) -> str:
    return f"{n//1000}k" if n < 1_000_000 else f"{n/1_000_000:g}M"


def main(argv: list[str]) -> int:
    if not hasattr(os, "fork"):
        print("This benchmark is Linux-only (needs os.fork). Run it on the server.", file=sys.stderr)
        return 2

    ap = argparse.ArgumentParser(description="Data Analyzer sandbox resource profiler.")
    ap.add_argument("--sizes", default="10000,100000,1000000",
                    help="comma list of row counts (default 10k,100k,1M)")
    ap.add_argument("--workloads", default="all",
                    help="comma list from: " + ",".join(WORKLOADS) + " (default all)")
    ap.add_argument("--mem-cap-mb", type=int, default=0,
                    help="apply RLIMIT_AS to each run (mirror DATA_SANDBOX_MEM_MB); 0 = unlimited")
    ap.add_argument("--threads", type=int, default=2,
                    help="BLAS/OMP threads per run (mirror prod; default 2)")
    ap.add_argument("--concurrency", type=int, default=0,
                    help="stress mode: run K copies of ONE --workload/--size at once")
    ap.add_argument("--workload", default="kmeans", help="workload for --concurrency mode")
    ap.add_argument("--size", type=int, default=1_000_000, help="row count for --concurrency mode")
    ap.add_argument("--quick", action="store_true", help="tiny sizes (5k,50k) — fast smoke of all workloads")
    ap.add_argument("--out", default="bench_results.json", help="JSON results path")
    args = ap.parse_args(argv)

    sizes = [5000, 50000] if args.quick else [int(s) for s in args.sizes.split(",") if s.strip()]
    names = list(WORKLOADS) if args.workloads == "all" else [w.strip() for w in args.workloads.split(",")]
    bad = [w for w in names if w not in WORKLOADS]
    if bad:
        print(f"unknown workload(s): {bad}; choose from {list(WORKLOADS)}", file=sys.stderr)
        return 2

    facts = host_facts()
    print("=" * 72)
    print("Data Analyzer sandbox benchmark")
    print(f"  host: {facts['cpus']} CPU · {facts['mem_total_mb']} MB RAM "
          f"({facts['mem_available_mb']} MB free) · py {facts['python']}")
    print(f"  threads/run: {args.threads} · mem cap: "
          f"{args.mem_cap_mb or 'unlimited'} MB")
    print("=" * 72)

    root = tempfile.mkdtemp(prefix="bench_root_")
    report = {"host": facts, "mem_cap_mb": args.mem_cap_mb, "threads": args.threads}
    try:
        # Cache one dataset per size (symlinked into each run's workdir).
        data_paths: dict[int, str] = {}
        needed = {args.size} if args.concurrency else set(sizes)
        for n in sorted(needed):
            p = os.path.join(root, f"data_{n}.csv")
            print(f"  generating dataset: {_fmt_size(n)} rows …", flush=True)
            make_dataset(p, n)
            data_paths[n] = p
            print(f"    {os.path.getsize(p) / 1e6:.1f} MB on disk", flush=True)

        if args.concurrency:
            print(f"\nCONCURRENCY STRESS — {args.concurrency} × '{args.workload}' "
                  f"@ {_fmt_size(args.size)} rows\n" + "-" * 72)
            r = run_concurrency(data_paths[args.size], WORKLOADS[args.workload], root,
                                args.concurrency, args.mem_cap_mb, args.threads)
            report["concurrency_result"] = {"workload": args.workload, "size": args.size, **r}
            print(f"  total wall:           {r['total_wall_s']} s")
            print(f"  system peak RAM used: {r['system_peak_used_mb']} MB "
                  f"(min free {r['system_min_avail_mb']} MB)")
            print(f"  Σ child peak RSS:     {r['sum_child_rss_mb']} MB "
                  f"(max single {r['max_child_rss_mb']} MB)")
            print(f"  peak 1m load:         {r['peak_load_1m']}  (cpus={facts['cpus']})")
            print(f"  failures:             {r['failures']}/{args.concurrency}"
                  + ("  ← OOM/cap hit!" if r["failures"] else ""))
        else:
            header = f"{'workload':<10} {'rows':>6} {'peakRSS_MB':>11} {'CPU_s':>8} {'wall_s':>8} {'art':>4}  status"
            print("\n" + header)
            print("-" * len(header))
            rows = []
            for n in sizes:
                for name in names:
                    m = measure_one(data_paths[n], WORKLOADS[name], root, args.mem_cap_mb, args.threads)
                    status = "ok" if m["ok"] else f"FAIL: {m['error']}"
                    print(f"{name:<10} {_fmt_size(n):>6} {m['peak_rss_mb']:>11} "
                          f"{m['cpu_s']:>8} {m['wall_s']:>8} {m['artifacts']:>4}  {status}", flush=True)
                    rows.append({"workload": name, "rows": n, **m})
            report["runs"] = rows
            # Quick guidance: worst-case peak RSS → suggested mem cap + concurrency.
            oks = [r for r in rows if r["ok"]]
            if oks:
                worst = max(oks, key=lambda r: r["peak_rss_mb"])
                print("-" * len(header))
                print(f"  worst peak RSS: {worst['peak_rss_mb']} MB "
                      f"({worst['workload']} @ {_fmt_size(worst['rows'])})")
                print(f"  → suggested DATA_SANDBOX_MEM_MB ≈ {int(worst['peak_rss_mb'] * 1.4 // 64 * 64 + 64)} "
                      f"(peak ×1.4 headroom); fit concurrency so "
                      f"cap×concurrency < {facts['mem_total_mb']} MB total RAM.")

        out_path = os.path.join(HERE, args.out)
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
        print(f"\nwrote {out_path}")
    finally:
        shutil.rmtree(root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
