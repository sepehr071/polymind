# Data Analyzer sandbox

Hardened execution layer for the **Data Analyzer** chat mode (ChatGPT
Code-Interpreter-style). The LLM writes pandas code; it runs on a **dedicated
data-science venv** (`.venv-sandbox`) inside an OS sandbox, against a
user-uploaded CSV / Excel / txt file, and emits chart / table artifacts as JSON.

The backend process **never imports pandas**. It only spawns `runner.py` (under
`bwrap` in prod) and reads `<workdir>/run/{result,profile}.json`.

```
backend/sandbox/
├── runner.py                  # runs INSIDE the sandbox on .venv-sandbox
├── requirements-sandbox.txt   # pandas…duckdb + xlrd — NO matplotlib/seaborn/plotly
├── .venv-sandbox/             # provisioned per-host, git-ignored
└── README.md
```

Also used by **Agent `/agent`** when the user uploads tabular files (`run_python`).

Backend glue:
- `app/services/sandbox_service.py` — spawns the sandbox, hardening + concurrency.
- `app/services/data_analysis_service.py` — copies upload bytes → workdir, profiles, prune.
- `app/services/data_model_router.py` — dual-model pick (Sonnet 5 vs Flash Lite).
- `app/prompts/data_analyst.py` — `SANDBOX_PYTHON_RULES` (shared with Agent).
- `app/config.py` — `DATA_SANDBOX_*`, `DATA_ANALYSIS_MODEL*`, `DATA_WORKDIR_TTL_HOURS`.

Per-conversation scratch dirs live under `DATA_SANDBOX_ROOT`
(`…/<conversation_id>/{data,run,outputs,cache}`), also git-ignored.

**Warm cache:** profile parses sources once → writes `cache/*.parquet` +
`cache/manifest.json`. Each `run_python` reloads parquet when source
name/size/mtime fingerprint still matches (no re-parse of fat Excel every round).

**Dual model:** simple inspect/summary → `DATA_ANALYSIS_MODEL_FAST`
(default `google/gemini-3.1-flash-lite`); complex stats/joins/forecast →
`DATA_ANALYSIS_MODEL` (default `anthropic/claude-sonnet-5`). Set
`DATA_ANALYSIS_DUAL_MODEL=0` to always use heavy.

---

## Provision the dev venv (Windows)

```bash
cd backend/sandbox
uv venv .venv-sandbox
uv pip install --python .venv-sandbox/Scripts/python.exe \
    --index-url https://registry.example.com/repository/pypi-proxy/simple/ \
    -r requirements-sandbox.txt
```

Verify:

```bash
./.venv-sandbox/Scripts/python.exe -c "import pandas, numpy, scipy, sklearn, statsmodels, pyarrow, openpyxl, xlrd, duckdb; print('ok')"
```

Dev mode (`DATA_SANDBOX_MODE=dev`, the local default) runs the code via a plain
`subprocess` with a timeout + a best-effort Windows Job-Object memory cap and
**NO OS isolation** — the service logs a loud warning. This is fine locally; it
is **never** how prod runs.

---

## Provision on a Linux host

```bash
# 1. Install bubblewrap (the sandbox jailer).
sudo apt-get update && sudo apt-get install -y bubblewrap

# 2. Create the dedicated venv next to the backend.
cd /opt/unichat/backend/sandbox
uv venv .venv-sandbox
# Prefer proxy when healthy; else install from wheels
sudo -u unichat env HTTPS_PROXY=http://127.0.0.1:11800 HTTP_PROXY=http://127.0.0.1:11800 \
  /opt/unichat/backend/sandbox/.venv-sandbox/bin/pip install --no-input \
  -r /opt/unichat/backend/sandbox/requirements-sandbox.txt

# 3. Verify the analyst stack imports (must run as unichat).
sudo -u unichat /opt/unichat/backend/sandbox/.venv-sandbox/bin/python -c \
  "import pandas, numpy, scipy, sklearn, statsmodels, pyarrow, openpyxl, xlrd, duckdb; print('ok')"

# 4. Verify bwrap can launch the runner with no network + scrubbed env.
bwrap --version
```

Then set in `.env.prod` (or the systemd unit env) and restart the backend:

```
DATA_SANDBOX_MODE=prod
# optional overrides:
# DATA_SANDBOX_ROOT=/var/lib/unichat/data_sandbox
# DATA_SANDBOX_VENV=/opt/unichat/backend/sandbox/.venv-sandbox
# DATA_SANDBOX_TIMEOUT_S=20
# DATA_SANDBOX_MEM_MB=1024
# DATA_SANDBOX_MAX_CONCURRENCY=3
# DATA_WORKDIR_TTL_HOURS=24
# DATA_ANALYSIS_MODEL=anthropic/claude-sonnet-5
# DATA_ANALYSIS_MODEL_FAST=google/gemini-3.1-flash-lite
# DATA_ANALYSIS_DUAL_MODEL=1
# AGENT_ORCHESTRATOR_MODEL=anthropic/claude-sonnet-5   # Agent /agent
```

**Fail-closed contract:** with `DATA_SANDBOX_MODE=prod`, if neither `bwrap` nor
`firejail` is on `PATH`, `SandboxService.available()` returns `False` and
`run()` raises `SandboxUnavailableError`. When `FLASK_ENV=production` and
`DATA_SANDBOX_MODE!=prod`, available() fails closed and `run()` raises — refuse
unsandboxed analysis. `firejail` is a documented fallback only — **bwrap is primary**.

Stale workdirs: `prune_workdirs()` runs hourly from `app/asgi.py` startup task
and opportunistically in `prepare_dataset`.

### What the bwrap jail enforces
- `--unshare-all` and we do **not** `--share-net` → no network.
- `--die-with-parent` → child dies if the worker dies.
- `--ro-bind` the python prefix + venv; `--bind` whole `<workdir>` then
  `--remount-ro data/` so uploads cannot be overwritten (`run/`, `outputs/`,
  `cache/` stay writable); `--tmpfs /tmp`; `--new-session`.
- **Scrubbed env** — only a minimal `PATH`/`PYTHON*`/locale; `OPENROUTER_API_KEY`,
  DB creds, JWT secrets and proxy creds are **never** passed to the child.
- POSIX `rlimit` (address space ≈ `mem_mb`, file size, NOFILE, NPROC) via a
  `preexec_fn`; a wall-clock kill at `timeout_s` reaps the whole process group.

The Linux-only isolation tests
(`tests/unit/test_sandbox.py::test_network_is_denied_in_prod`,
`test_secrets_not_leaked_to_sandbox_env`) are skipped on Windows/dev and run here
under bwrap with `DATA_SANDBOX_MODE=prod`.
