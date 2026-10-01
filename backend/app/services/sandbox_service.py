"""Hardened execution layer for the Data Analyzer chat mode.

The LLM writes pandas code; this service runs it on a DEDICATED data-science venv
(``backend/sandbox/.venv-sandbox``) inside an OS sandbox, against a user-uploaded
dataset, and reads back JSON artifacts (tables / charts). It NEVER imports pandas
into the backend process — it only spawns ``backend/sandbox/runner.py`` and reads
``<workdir>/run/{result,profile}.json``.

Threat model: the code is attacker-controlled (prompt-injected or hostile user).
Python-level globals filtering in runner.py is defence-in-depth ONLY; the real
isolation is the OS sandbox:

Prod (Linux) — bubblewrap (``bwrap``):
  * ``--unshare-all`` and we DO NOT ``--share-net`` → no network namespace access.
  * ``--die-with-parent`` → child dies if the backend worker dies.
  * ``--ro-bind`` the sandbox venv + the python prefix; ``--bind`` the
    per-conversation ``<workdir>`` then ``--remount-ro`` on ``data/`` so
    uploads cannot be overwritten (run/ + outputs/ stay writable).
  * ``--tmpfs /tmp``; scrubbed env (a minimal PATH + PYTHON* only — NEVER
    OPENROUTER_API_KEY / DB creds / os.environ passthrough); ``--new-session``.
  * rlimits (address space ~= mem_mb, CPU seconds, file size) applied in a
    ``preexec_fn``; a wall-clock kill at ``timeout_s`` reaps the whole tree.
  Firejail is a documented fallback if bwrap is absent (bwrap is primary).

Dev (Windows / ``DATA_SANDBOX_MODE=dev``):
  * plain ``subprocess.run`` of the sandbox python with a timeout + best-effort
    memory cap (Job Object on Windows). NO isolation — logs a loud warning.

Fail closed: in prod, if neither bwrap nor firejail is found, ``available()``
returns False and ``run()`` raises ``SandboxUnavailableError`` — the backend must
refuse the feature rather than execute untrusted code unsandboxed.

Concurrency: a process-wide ``threading.Semaphore(DATA_SANDBOX_MAX_CONCURRENCY)``
bounds simultaneous executions; each call kills its child process tree on
timeout / cancellation. ``run()`` is synchronous + thread-safe (the SSE producer
offloads it via ``anyio.to_thread.run_sync``).

------------------------------------------------------------------------------
Provisioning the dedicated sandbox venv
------------------------------------------------------------------------------
Dev (Windows):
    cd backend/sandbox
    uv venv .venv-sandbox
    uv pip install --python .venv-sandbox/Scripts/python.exe \
        --index-url https://registry.example.com/repository/pypi-proxy/simple/ \
        -r requirements-sandbox.txt

prod (Linux prod) — see backend/sandbox/README.md:
    sudo apt-get install -y bubblewrap
    cd /opt/uni-chat/backend/sandbox        # adjust to the deploy path
    uv venv .venv-sandbox
    uv pip install --python .venv-sandbox/bin/python -r requirements-sandbox.txt
    # set in .env.prod:  DATA_SANDBOX_MODE=prod
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from typing import Optional, TypedDict

from app.settings import settings

logger = logging.getLogger(__name__)

# Where runner.py lives (next to this repo's backend/sandbox dir).
_SANDBOX_DIR = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'sandbox')
)
_RUNNER_PATH = os.path.join(_SANDBOX_DIR, 'runner.py')

# Minimal, scrubbed env handed to the child. Deliberately omits every secret in
# the backend process (OPENROUTER_API_KEY, SQLALCHEMY_DATABASE_URI, JWT secrets,
# proxy creds, ...). PATH is needed so the interpreter can find shared libs on
# some distros; nothing else from os.environ is forwarded.
# Cached result of the one-time live bwrap capability probe (None = not run yet).
_PROBE_RESULT: "Optional[bool]" = None

_SCRUBBED_ENV_KEEP = ('PATH', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TZ', 'SYSTEMROOT',
                      'PYTHONHASHSEED')


class SandboxResult(TypedDict):
    stdout: str
    stderr: str
    error: Optional[str]
    artifacts: list[dict]
    timed_out: bool


class SandboxUnavailableError(RuntimeError):
    """Raised when the sandbox cannot run safely (prod with no bwrap/firejail)."""


# Process-wide concurrency gate. Built lazily so a config change in tests is
# honored and so import stays side-effect-free.
_semaphore: Optional[threading.Semaphore] = None
_semaphore_lock = threading.Lock()


def _get_semaphore() -> threading.Semaphore:
    global _semaphore
    if _semaphore is None:
        with _semaphore_lock:
            if _semaphore is None:
                n = int(settings.get('DATA_SANDBOX_MAX_CONCURRENCY', 3) or 3)
                _semaphore = threading.Semaphore(max(1, n))
    return _semaphore


def _flask_env() -> str:
    return str(
        settings.get('FLASK_ENV') or os.environ.get('FLASK_ENV', 'development')
    ).strip().lower()


def _sandbox_mode() -> str:
    return str(settings.get('DATA_SANDBOX_MODE', 'dev')).strip().lower()


def _prod_requires_sandbox() -> bool:
    """True when production env forbids plain-subprocess (dev) mode."""
    return _flask_env() == 'production' and _sandbox_mode() != 'prod'


def _assert_prod_sandbox_config() -> None:
    """Fail loud if production would otherwise run unsandboxed analyst code.

    ``ProductionConfig.validate()`` is not always auto-run on ASGI boot, so
    this is the runtime backstop on ``run()``: refuse rather than silently
    using plain subprocess isolation.
    """
    if _prod_requires_sandbox():
        raise RuntimeError(
            "DATA_SANDBOX_MODE must be 'prod' when FLASK_ENV=production "
            "(refusing unsandboxed data analysis)"
        )


def _is_dev_mode() -> bool:
    return _sandbox_mode() == 'dev'


def _which(name: str) -> Optional[str]:
    return shutil.which(name)


def _venv_python(venv_path: str) -> Optional[str]:
    """Resolve the interpreter inside a venv for the current OS layout."""
    candidates = (
        os.path.join(venv_path, 'Scripts', 'python.exe'),  # Windows
        os.path.join(venv_path, 'bin', 'python'),          # POSIX
        os.path.join(venv_path, 'bin', 'python3'),
    )
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def _sandbox_python() -> Optional[str]:
    venv = settings.get('DATA_SANDBOX_VENV') or os.path.join(_SANDBOX_DIR, '.venv-sandbox')
    return _venv_python(venv)


class SandboxService:
    """Spawns runner.py inside the OS sandbox; reads JSON artifacts back."""

    @staticmethod
    def available() -> bool:
        """True iff the sandbox can run.

        Dev mode (``DATA_SANDBOX_MODE=dev``) → True as long as the dedicated venv
        python exists. Prod mode → requires the venv python AND an OS sandbox
        binary (bwrap, or firejail as a fallback); otherwise False so the backend
        FAILS CLOSED rather than executing untrusted code unsandboxed.
        """
        if _sandbox_python() is None:
            return False
        # Misconfigured prod: do NOT report available (would run unsandboxed).
        if _prod_requires_sandbox():
            logger.error(
                "DATA_SANDBOX_MODE must be 'prod' when FLASK_ENV=production — "
                "data-analyzer sandbox DISABLED (fail closed)."
            )
            return False
        if _is_dev_mode():
            return True
        if not (_which('bwrap') or _which('firejail')):
            return False
        return SandboxService._sandbox_probe()

    @staticmethod
    def _sandbox_probe() -> bool:
        """One REAL sandbox launch, cached for the worker's lifetime.

        Binary presence is not capability: Ubuntu 24.04 ships bwrap but blocks
        unprivileged user namespaces by default, so every actual run died with
        'no permissions to create new namespace' while available() said True.
        A live probe makes a mis-provisioned host FAIL CLOSED up front (clean
        'sandbox unavailable' instead of a crash message every tool round).
        Host fix: AppArmor profile granting ``userns,`` to /usr/bin/bwrap +
        ``kernel.unprivileged_userns_clone=1`` (see your deployment docs).

        The probe runs the EXACT ``_build_argv`` the real run uses (same bind set
        + the venv interpreter) over a throwaway workdir in ``--profile`` mode, so
        it validates the whole thing: userns permission AND every ``--ro-bind``
        path AND that the interpreter imports numpy/pandas inside the namespace.
        The old probe used a different, simpler argv (``--ro-bind / / /bin/true``)
        that only proved userns was permitted — it masked bind-layout failures
        (e.g. runner.py invisible, a missing ``/lib`` bind) that then crashed every
        real round despite available()==True.
        """
        global _PROBE_RESULT
        if _PROBE_RESULT is not None:
            return _PROBE_RESULT
        bwrap = _which('bwrap')
        if not bwrap:
            _PROBE_RESULT = True  # firejail path: setuid, no userns dependency
            return True
        py = _sandbox_python()
        if py is None:
            _PROBE_RESULT = False
            return False
        import tempfile
        tmp = tempfile.mkdtemp(prefix='sbx-probe-')
        try:
            os.makedirs(os.path.join(tmp, 'data'), exist_ok=True)
            os.makedirs(os.path.join(tmp, 'run'), exist_ok=True)
            argv = SandboxService._build_argv(
                py=os.path.normpath(py), workdir=os.path.abspath(tmp),
                profile=True, mem_mb=512, bwrap=bwrap, firejail=None, dev=False,
            )
            env = SandboxService._scrubbed_env(os.path.abspath(tmp), py)
            proc = subprocess.run(
                argv, capture_output=True, timeout=30, env=env, cwd=tmp,
            )
            # runner --profile over an empty data/ writes profile.json + exits 0;
            # require BOTH so a non-zero exit or a bind/import failure fails closed.
            wrote = os.path.exists(os.path.join(tmp, 'run', 'profile.json'))
            _PROBE_RESULT = proc.returncode == 0 and wrote
            if not _PROBE_RESULT:
                logger.error(
                    'bwrap probe failed (rc=%s, profile_written=%s): %s — '
                    'data-analyzer sandbox DISABLED (fail closed). Check '
                    'unprivileged user namespaces (AppArmor userns profile) and '
                    'the sandbox venv bind set.',
                    proc.returncode, wrote,
                    (proc.stderr or b'').decode('utf-8', 'replace')[:300],
                )
        except Exception as exc:  # noqa: BLE001 — any probe failure = unavailable
            logger.error('bwrap probe crashed: %s — sandbox disabled', exc)
            _PROBE_RESULT = False
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        return _PROBE_RESULT

    @staticmethod
    def run(*, workdir: str, code: str, timeout_s: int = 20,
            mem_mb: int = 1024,
            stop_event: "Optional[threading.Event]" = None) -> SandboxResult:
        """Execute ``code`` (exec mode) in the sandbox and return artifacts.

        Writes ``code`` to ``<workdir>/run/code.py``, spawns runner.py, and reads
        ``<workdir>/run/result.json``. Enforces the process-wide concurrency
        semaphore and a wall-clock timeout that kills the child process tree.

        ``stop_event``: when the SSE turn is cancelled (client disconnect) the
        driver sets this event; the spawn loop polls it and kills the child tree
        promptly instead of holding a scarce concurrency slot until ``timeout_s``.
        """
        return SandboxService._invoke(
            workdir=workdir, code=code, timeout_s=timeout_s, mem_mb=mem_mb,
            profile=False, stop_event=stop_event,
        )

    @staticmethod
    def profile(*, workdir: str, timeout_s: int = 30,
                mem_mb: int = 1024,
                stop_event: "Optional[threading.Event]" = None) -> dict:
        """Run runner.py ``--profile`` to parse ``<workdir>/data`` and return
        ``{'preview_markdown': str, 'manifest': list}``.

        Untrusted bytes are parsed ONLY inside the sandbox. On timeout / failure
        returns an empty manifest with a diagnostic preview rather than raising,
        so dataset preparation degrades gracefully.

        ``stop_event``: when the SSE turn is cancelled (client disconnect) the
        driver sets this; the spawn loop reaps the child promptly instead of
        holding a scarce concurrency slot for the full timeout (mirrors ``run``).
        """
        res = SandboxService._invoke(
            workdir=workdir, code=None, timeout_s=timeout_s, mem_mb=mem_mb,
            profile=True, stop_event=stop_event,
        )
        run_dir = os.path.join(workdir, 'run')
        profile = _read_json(os.path.join(run_dir, 'profile.json'))
        if profile and isinstance(profile.get('manifest'), list):
            return {
                'preview_markdown': str(profile.get('preview_markdown', '')),
                'manifest': profile['manifest'],
            }
        # Profile pass failed (timeout, crash, or no JSON written).
        detail = res.get('error') or ('timed out' if res.get('timed_out') else 'profile failed')
        return {
            'preview_markdown': f'Could not profile the uploaded data ({detail}).',
            'manifest': [],
        }

    # ------------------------------------------------------------------ #
    # Core spawn.
    # ------------------------------------------------------------------ #
    @staticmethod
    def _invoke(*, workdir: str, code: Optional[str], timeout_s: int,
                mem_mb: int, profile: bool,
                stop_event: "Optional[threading.Event]" = None) -> SandboxResult:
        _assert_prod_sandbox_config()
        py = _sandbox_python()
        if py is None:
            raise SandboxUnavailableError(
                'Data Analyzer sandbox venv not found. Provision '
                f'{settings.get("DATA_SANDBOX_VENV")!r} (see sandbox_service.py).'
            )

        dev = _is_dev_mode()
        bwrap = _which('bwrap') if not dev else None
        firejail = _which('firejail') if (not dev and not bwrap) else None
        if not dev and not bwrap and not firejail:
            raise SandboxUnavailableError(
                'Refusing to run untrusted code: DATA_SANDBOX_MODE=prod but '
                'neither bwrap nor firejail is installed. apt-get install '
                'bubblewrap (see backend/sandbox/README.md).'
            )

        workdir = os.path.abspath(workdir)
        data_dir = os.path.join(workdir, 'data')
        run_dir = os.path.join(workdir, 'run')
        os.makedirs(data_dir, exist_ok=True)
        os.makedirs(run_dir, exist_ok=True)
        os.makedirs(os.path.join(workdir, 'cache'), exist_ok=True)

        # Reset prior artifacts so a crash before write can't surface stale data.
        for stale in ('result.json', 'profile.json'):
            try:
                os.remove(os.path.join(run_dir, stale))
            except OSError:
                pass

        if not profile:
            # Clear outputs/ at the START of every exec run: the tool-loop is
            # stateless across rounds, so each round must emit ONLY the files IT
            # wrote — otherwise a deliverable from an earlier round re-surfaces as a
            # stale download card. (profile() never touches outputs/.)
            outputs_dir = os.path.join(workdir, 'outputs')
            shutil.rmtree(outputs_dir, ignore_errors=True)
            os.makedirs(outputs_dir, exist_ok=True)
            with open(os.path.join(run_dir, 'code.py'), 'w', encoding='utf-8') as fh:
                fh.write(code or '')

        argv = SandboxService._build_argv(
            py=py, workdir=workdir, profile=profile, mem_mb=mem_mb,
            bwrap=bwrap, firejail=firejail, dev=dev,
        )
        env = SandboxService._scrubbed_env(workdir, py)

        if dev:
            logger.warning(
                'SANDBOX NOT HARDENED — dev only. Running Data Analyzer code via '
                'plain subprocess with NO OS isolation (DATA_SANDBOX_MODE=dev).'
            )

        sem = _get_semaphore()
        sem.acquire()
        try:
            timed_out, stdout_tail, stderr_tail = SandboxService._spawn(
                argv=argv, env=env, cwd=workdir, timeout_s=timeout_s,
                mem_mb=mem_mb, dev=dev, stop_event=stop_event,
            )
        finally:
            sem.release()

        return SandboxService._collect_result(
            run_dir=run_dir, profile=profile, timed_out=timed_out,
            stdout_tail=stdout_tail, stderr_tail=stderr_tail,
        )

    @staticmethod
    def _build_argv(*, py: str, workdir: str, profile: bool, mem_mb: int,
                    bwrap: Optional[str], firejail: Optional[str], dev: bool) -> list[str]:
        # Lexically normalize: py arrives as ``.../app/../sandbox/.venv-sandbox/
        # bin/python``; inside the bwrap namespace the intermediate ``app`` dir
        # isn't mounted, so the unresolved ``..`` fails execvp. normpath (NOT
        # realpath!) — realpath follows the venv python symlink to
        # /usr/bin/pythonX, which skips pyvenv.cfg discovery and loses the venv
        # site-packages (ModuleNotFoundError: numpy).
        py = os.path.normpath(py)
        runner_args = [_RUNNER_PATH, '--workdir', workdir]
        if profile:
            runner_args.append('--profile')

        if dev or (not bwrap and not firejail):
            return [py, *runner_args]

        if bwrap:
            # Read-only bind the python prefix + venv so the interpreter + stdlib
            # are visible; bind only the workdir rw. No /home, no network, scrubbed
            # env, fresh session, dies with the parent worker.
            prefix = sys.base_prefix
            venv_root = os.path.dirname(os.path.dirname(py))  # .../venv
            cmd = [
                bwrap,
                '--unshare-all',            # no net/ipc/pid/uts/cgroup namespaces
                '--die-with-parent',
                '--new-session',
                '--proc', '/proc',
                '--dev', '/dev',
                '--tmpfs', '/tmp',
                '--ro-bind', '/usr', '/usr',
                '--ro-bind', '/bin', '/bin',
                '--ro-bind', '/lib', '/lib',
            ]
            for opt_path in ('/lib64', '/etc/alternatives', '/etc/ssl/certs'):
                if os.path.exists(opt_path):
                    cmd += ['--ro-bind', opt_path, opt_path]
            # Read-only paths the child needs: interpreter prefix, the venv, AND
            # the sandbox dir holding runner.py (sibling of the venv — binding
            # only the venv left runner.py invisible inside the namespace, which
            # crashed every prod run with ENOENT once user namespaces were
            # enabled). Dedupe nested paths: an outer bind already covers inner.
            ro_paths: list[str] = []
            for cand in (prefix, venv_root, _SANDBOX_DIR):
                cand = os.path.realpath(cand)
                if cand.startswith('/usr'):
                    continue
                if any(cand == p or cand.startswith(p + os.sep) for p in ro_paths):
                    continue
                ro_paths = [p for p in ro_paths
                            if not p.startswith(cand + os.sep)] + [cand]
            for p in sorted(ro_paths):
                cmd += ['--ro-bind', p, p]
            # Bind whole workdir, then remount data/ RO so model code can write
            # run/ + outputs/ but cannot overwrite/delete source uploads.
            data_dir = os.path.join(workdir, 'data')
            os.makedirs(data_dir, exist_ok=True)
            os.makedirs(os.path.join(workdir, 'run'), exist_ok=True)
            os.makedirs(os.path.join(workdir, 'outputs'), exist_ok=True)
            # Warm parquet cache lives here (RW); data/ stays RO after remount.
            os.makedirs(os.path.join(workdir, 'cache'), exist_ok=True)
            # Prefer --ro-bind over --remount-ro: newer kernels (e.g. 6.8) fail
            # remount-ro on a subdirectory of a bind mount ("Unable to find in
            # mount table"). Re-binding data/ RO achieves the same guard.
            cmd += [
                '--bind', workdir, workdir,
                '--ro-bind', data_dir, data_dir,
                '--chdir', workdir,
                py, *runner_args,
            ]
            return cmd

        # Firejail fallback: deny network, private tmp, no sound, seccomp default.
        data_dir = os.path.join(workdir, 'data')
        return [
            firejail,
            '--quiet',
            '--net=none',
            '--private-tmp',
            '--nosound',
            '--no3d',
            '--nodbus',
            '--seccomp',
            f'--read-only={data_dir}',
            f'--rlimit-as={mem_mb * 1024 * 1024}',
            py, *runner_args,
        ]

    @staticmethod
    def _scrubbed_env(workdir: str, py: str) -> dict:
        env = {k: v for k, v in os.environ.items() if k in _SCRUBBED_ENV_KEEP}
        env.setdefault('PATH', os.environ.get('PATH', ''))
        # The runner reads SANDBOX_WORKDIR as a fallback to --workdir.
        env['SANDBOX_WORKDIR'] = workdir
        # Don't let the child write .pyc into the (possibly read-only) venv.
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        env['PYTHONUNBUFFERED'] = '1'
        env['PYTHONNOUSERSITE'] = '1'
        # Force UTF-8 stdio in the child: on Windows dev the subprocess default
        # is cp1252, so a plain print() of Persian text raised UnicodeEncodeError
        # INSIDE user code and killed the round. utf8 mode keeps stdout, stderr
        # and default open() encodings deterministic on every platform.
        env['PYTHONUTF8'] = '1'
        env['PYTHONIOENCODING'] = 'utf-8'
        # Hard-pin the interpreter's home so a relocated bwrap mount still finds
        # the stdlib (no effect in dev). base_prefix of the sandbox venv.
        env.setdefault('OPENBLAS_NUM_THREADS', '2')
        env.setdefault('OMP_NUM_THREADS', '2')
        # The env is scrubbed, so the runner can't read the backend's os.environ.
        # Forward the runner's tunables EXPLICITLY (it reads these by name):
        #   - DATA_MAX_INGEST_ROWS was a latent bug — the runner honored it but it
        #     was never passed through, so the ingest cap always fell back to its
        #     hardcoded default regardless of config.
        #   - DATA_OUTPUT_MAX_{BYTES,FILES} gate the new downloadable-output surface.
        env['DATA_MAX_INGEST_ROWS'] = str(
            settings.get('DATA_MAX_INGEST_ROWS', 1000000) or 1000000)
        env['DATA_OUTPUT_MAX_BYTES'] = str(
            settings.get('DATA_OUTPUT_MAX_BYTES', 67108864) or 67108864)
        env['DATA_OUTPUT_MAX_FILES'] = str(
            settings.get('DATA_OUTPUT_MAX_FILES', 5) or 5)
        return env

    @staticmethod
    def _preexec(mem_mb: int, timeout_s: int = 20):
        """Build a POSIX preexec_fn that applies rlimits + a new session.

        Returns None on platforms without ``resource`` (Windows) — there the
        mem cap is applied via a Job Object in ``_spawn``.

        ``RLIMIT_CPU`` bounds CPU SECONDS (not wall-clock): without it a tight C
        loop pegs a full core for the whole wall-clock budget. Set a touch above
        ``timeout_s`` so the wall-clock killer normally fires first; the CPU
        limit is the backstop (SIGXCPU → SIGKILL) for compute-bound code that the
        wall-clock kill might race.
        """
        try:
            import resource  # POSIX only
        except ImportError:
            return None

        cpu_s = max(1, int(timeout_s) + 1)

        def _apply():
            # New session so the wall-clock killer can signal the whole group.
            try:
                os.setsid()
            except OSError:
                pass
            mem_bytes = max(64, mem_mb) * 1024 * 1024
            for res_name, limit in (
                ('RLIMIT_AS', mem_bytes),
                ('RLIMIT_DATA', mem_bytes),
                ('RLIMIT_CPU', cpu_s),                # CPU seconds (tight-loop guard)
                ('RLIMIT_FSIZE', 256 * 1024 * 1024),  # 256MB max output file
                ('RLIMIT_NOFILE', 256),
                ('RLIMIT_NPROC', 64),
            ):
                rid = getattr(resource, res_name, None)
                if rid is None:
                    continue
                try:
                    soft, hard = resource.getrlimit(rid)
                    new_hard = limit if hard == resource.RLIM_INFINITY else min(limit, hard)
                    resource.setrlimit(rid, (min(limit, new_hard), new_hard))
                except (ValueError, OSError):
                    pass

        return _apply

    @staticmethod
    def _spawn(*, argv: list[str], env: dict, cwd: str, timeout_s: int,
               mem_mb: int, dev: bool,
               stop_event: "Optional[threading.Event]" = None) -> tuple[bool, str, str]:
        """Run the child with a hard wall-clock timeout, killing the whole tree.

        Returns ``(timed_out, stdout_tail, stderr_tail)``. The authoritative
        output is the JSON file the runner writes; the captured stdout/stderr is
        only a diagnostic tail used when the JSON is missing (crash before write).

        When ``stop_event`` is supplied the child is reaped as soon as the event
        is set (turn cancelled), releasing the concurrency slot promptly instead
        of waiting out ``timeout_s``.
        """
        creationflags = 0
        preexec = None
        if os.name == 'nt':
            # New process group so we can signal the tree on Windows.
            creationflags = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
        else:
            preexec = SandboxService._preexec(mem_mb, timeout_s)

        try:
            proc = subprocess.Popen(
                argv,
                cwd=cwd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                preexec_fn=preexec,
                creationflags=creationflags,
                close_fds=True,
            )
        except FileNotFoundError as exc:
            raise SandboxUnavailableError(f'sandbox launcher not found: {exc}') from exc

        # Windows best-effort memory cap via a Job Object bound to the child.
        if os.name == 'nt':
            _apply_windows_job(proc.pid, mem_mb)

        timed_out = False
        # Reader threads so the wall-clock / cancel poll never blocks on a full
        # OS pipe buffer (communicate() can't be interrupted for cancellation).
        out_chunks: list[bytes] = []
        err_chunks: list[bytes] = []
        t_out = threading.Thread(target=_drain_pipe, args=(proc.stdout, out_chunks), daemon=True)
        t_err = threading.Thread(target=_drain_pipe, args=(proc.stderr, err_chunks), daemon=True)
        t_out.start()
        t_err.start()

        deadline = time.monotonic() + max(1, timeout_s)
        cancelled = False
        while True:
            if proc.poll() is not None:
                break
            now = time.monotonic()
            if now >= deadline:
                timed_out = True
                _kill_tree(proc)
                break
            if stop_event is not None and stop_event.is_set():
                cancelled = True
                _kill_tree(proc)
                break
            # Short sleep so cancellation/timeout are observed within ~0.1s.
            time.sleep(min(0.1, max(0.0, deadline - now)))

        # Reap the (possibly killed) child and join the reader threads.
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
        t_out.join(timeout=2)
        t_err.join(timeout=2)

        out = b''.join(out_chunks)
        err = b''.join(err_chunks)
        stdout_tail = out.decode('utf-8', 'replace')[-4000:]
        stderr_tail = err.decode('utf-8', 'replace')[-8000:]
        if cancelled and not stderr_tail:
            stderr_tail = 'cancelled'
        return timed_out, stdout_tail, stderr_tail

    @staticmethod
    def _collect_result(*, run_dir: str, profile: bool, timed_out: bool,
                        stdout_tail: str, stderr_tail: str) -> SandboxResult:
        if profile:
            # profile() reads profile.json itself; surface only run status here.
            return SandboxResult(
                stdout=stdout_tail, stderr=stderr_tail,
                error=None if not timed_out else 'sandbox timed out',
                artifacts=[], timed_out=timed_out,
            )

        result = _read_json(os.path.join(run_dir, 'result.json'))
        if result is not None:
            # Runner wrote a structured result. Overlay the timeout flag (the
            # runner can't know it was wall-clock killed — it never wrote on kill).
            artifacts = result.get('artifacts') or []
            return SandboxResult(
                stdout=str(result.get('stdout', '')),
                stderr=str(result.get('stderr', '')),
                error=result.get('error'),
                artifacts=artifacts if isinstance(artifacts, list) else [],
                timed_out=bool(timed_out or result.get('timed_out')),
            )

        # No JSON → the child was killed (timeout / OOM / sandbox launch error)
        # before it could write. Synthesize a result from the captured tails.
        if timed_out:
            err = 'Execution timed out.'
        else:
            err = 'Sandbox produced no result (the process crashed or was killed).'
        return SandboxResult(
            stdout=stdout_tail, stderr=stderr_tail or err,
            error=err, artifacts=[], timed_out=timed_out,
        )


# --------------------------------------------------------------------------- #
# Module-level helpers (process-tree kill, JSON read, Windows Job Object).
# --------------------------------------------------------------------------- #
def _read_json(path: str) -> Optional[dict]:
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _drain_pipe(pipe, sink: list) -> None:
    """Read a child pipe to EOF into ``sink`` (a reader thread).

    Keeps the OS pipe buffer from filling (which would deadlock a long-running
    child) while the main loop polls for wall-clock timeout / cancellation
    instead of blocking in ``communicate()``.
    """
    if pipe is None:
        return
    try:
        for chunk in iter(lambda: pipe.read(65536), b''):
            sink.append(chunk)
    except (OSError, ValueError):
        pass
    finally:
        try:
            pipe.close()
        except OSError:
            pass


def _kill_tree(proc: "subprocess.Popen") -> None:
    """Kill the child and its descendants, best-effort, cross-platform."""
    if proc.poll() is not None:
        return
    if os.name == 'nt':
        # taskkill /T reaps the whole tree; CREATE_NEW_PROCESS_GROUP made it one.
        try:
            subprocess.run(
                ['taskkill', '/F', '/T', '/PID', str(proc.pid)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=10, check=False,
            )
        except Exception:  # noqa: BLE001
            try:
                proc.kill()
            except OSError:
                pass
        return

    # POSIX: the preexec_fn called setsid(), so the child leads its own process
    # group; signal the whole group. bwrap's --die-with-parent backs this up.
    import signal
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except OSError:
            pass


def _apply_windows_job(pid: int, mem_mb: int) -> None:
    """Best-effort Windows memory cap: bind the child to a Job Object with a
    per-process committed-memory limit. No-op if anything fails (dev only)."""
    try:
        import ctypes
        from ctypes import wintypes

        JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
        JobObjectExtendedLimitInformation = 9
        PROCESS_SET_QUOTA = 0x0100
        PROCESS_TERMINATE = 0x0001

        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in (
                'ReadOperationCount', 'WriteOperationCount', 'OtherOperationCount',
                'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ('PerProcessUserTimeLimit', ctypes.c_int64),
                ('PerJobUserTimeLimit', ctypes.c_int64),
                ('LimitFlags', wintypes.DWORD),
                ('MinimumWorkingSetSize', ctypes.c_size_t),
                ('MaximumWorkingSetSize', ctypes.c_size_t),
                ('ActiveProcessLimit', wintypes.DWORD),
                ('Affinity', ctypes.c_size_t),
                ('PriorityClass', wintypes.DWORD),
                ('SchedulingClass', wintypes.DWORD),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ('BasicLimitInformation', JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ('IoInfo', IO_COUNTERS),
                ('ProcessMemoryLimit', ctypes.c_size_t),
                ('JobMemoryLimit', ctypes.c_size_t),
                ('PeakProcessMemoryUsed', ctypes.c_size_t),
                ('PeakJobMemoryUsed', ctypes.c_size_t),
            ]

        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = (
            JOB_OBJECT_LIMIT_PROCESS_MEMORY | JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        )
        info.ProcessMemoryLimit = ctypes.c_size_t(max(64, mem_mb) * 1024 * 1024)
        if not kernel32.SetInformationJobObject(
            job, JobObjectExtendedLimitInformation,
            ctypes.byref(info), ctypes.sizeof(info),
        ):
            kernel32.CloseHandle(job)
            return
        handle = kernel32.OpenProcess(
            PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, pid)
        if handle:
            kernel32.AssignProcessToJobObject(job, handle)
            kernel32.CloseHandle(handle)
        # Intentionally leak the job handle for the child's lifetime; the OS
        # closes it when the backend process exits (KILL_ON_JOB_CLOSE then reaps).
    except Exception as exc:  # noqa: BLE001 — dev-only best-effort
        logger.debug('windows job-object mem cap skipped: %s', exc)
