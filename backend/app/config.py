import os
import tempfile
from datetime import timedelta


def _normalize_pg_uri(uri):
    """Force the psycopg (v3) driver regardless of how the deploy spells the
    scheme. A bare ``postgres://`` / ``postgresql://`` makes SQLAlchemy load
    psycopg2, and ``+asyncpg`` loads asyncpg — neither is installed, so both
    raise ModuleNotFoundError at first connect. Only psycopg v3 is a dependency.
    """
    if not uri:
        return uri
    for prefix in ('postgresql+asyncpg://', 'postgresql+psycopg2://',
                   'postgresql://', 'postgres://'):
        if uri.startswith(prefix):
            return 'postgresql+psycopg://' + uri[len(prefix):]
    return uri


class Config:
    """Base configuration"""
    # Security
    SECRET_KEY = os.environ.get('SECRET_KEY')
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY')
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=1)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=30)

    # Database — SQLAlchemy / Postgres (sole datastore as of Phase 7).
    # The placeholder default keeps dev hosts without a local Postgres booting;
    # Flask-SQLAlchemy binds lazily and only dials the URL on the first query.
    SQLALCHEMY_DATABASE_URI = _normalize_pg_uri(os.environ.get(
        'SQLALCHEMY_DATABASE_URI',
        'postgresql+psycopg://localhost/unichat',
    ))
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Connection-pool sizing. Flask-SQLAlchemy forwards this dict straight to
    # SQLAlchemy's create_engine. The framework default (pool_size=5,
    # max_overflow=10 → 15 hard cap) starves us: every SSE stream pins one
    # connection for its entire lifetime (up to ~30 min) and arena fan-out pins
    # 3-5 per session. The per-worker stream semaphore
    # (services/stream_concurrency.py, MAX_CONCURRENT_STREAMS_PER_WORKER default
    # 14) now bounds concurrent streams BELOW this pool capacity, so a stream
    # burst can no longer drain the pool. pool_timeout is the wait a NON-stream
    # request tolerates for a free connection before TimeoutError; 10s (was 30s)
    # surfaces genuine saturation as a fast error instead of a 30s stall — safe
    # now that the semaphore caps stream pinning. pool_pre_ping issues a cheap
    # SELECT 1 on checkout so connections silently killed by the outbound proxy or
    # Postgres idle timeout are recycled instead of surfacing as OperationalError.
    # pool_recycle 1800s stays under typical idle cutoffs.
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_size": int(os.environ.get("DB_POOL_SIZE", "20")),
        "max_overflow": int(os.environ.get("DB_MAX_OVERFLOW", "30")),
        "pool_timeout": int(os.environ.get("DB_POOL_TIMEOUT", "10")),
        "pool_recycle": int(os.environ.get("DB_POOL_RECYCLE", "1800")),
        "pool_pre_ping": True,
        # Pin every session's TimeZone to UTC. The whole app stores naive
        # ``datetime.utcnow()`` values into ``timestamptz`` columns and buckets
        # analytics with ``date_trunc``/``to_char`` — all of which only read
        # back correctly when the libpq session TimeZone is UTC. A non-UTC host
        # (e.g. an Asia/Tehran dev box) would otherwise skew window bounds and
        # day/week bucket boundaries. No-op on an already-UTC prod server.
        "connect_args": {"options": "-c timezone=utc"},
    }

    # OpenRouter API
    OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY')
    OPENROUTER_BASE_URL = 'https://openrouter.ai/api/v1'

    # Outbound HTTP proxy for Iran-VPS deploys. When set, the backend rewrites
    # every openrouter.ai + api.elevenlabs.io call to {OUTBOUND_PROXY_URL}<path>
    # with X-Target-Host + X-Proxy-Key headers. See app/utils/outbound_proxy.py.
    OUTBOUND_PROXY_URL = os.environ.get('OUTBOUND_PROXY_URL')
    OUTBOUND_PROXY_KEY = os.environ.get('OUTBOUND_PROXY_KEY')

    # DLP smart-scan local LLM backend (privacy). When DLP_LLM_BASE_URL is set,
    # the DLP second-pass classifier hits a self-hosted Ollama server (native
    # /api/chat) instead of OpenRouter — so scanned text never leaves company
    # infra. Empty => unchanged OpenRouter (google/gemini-3.5-flash-lite) path.
    # The Ollama client (app/services/local_llm_service.py) deliberately bypasses
    # the egress proxy (trust_env=False) since the Ollama host is domestic.
    DLP_LLM_BASE_URL = os.environ.get('DLP_LLM_BASE_URL', '')          # e.g. https://local-ai.example.com:9443
    DLP_LLM_MODEL = os.environ.get('DLP_LLM_MODEL', 'qwen3.6:35b')     # permanently-loaded Ollama model
    # TLS verification for the DLP-scan text sent to the local Ollama host.
    # The Ollama host runs a SELF-SIGNED cert, so the default skips verification —
    # but that leaves the (sensitive) scanned text open to a LAN MITM. PREFERRED:
    # pin the self-signed cert via DLP_LLM_CA_BUNDLE (a PEM path) so verification
    # stays ON against that exact cert. Only set DLP_LLM_VERIFY_SSL=false (no CA
    # bundle) on a FULLY TRUSTED, ISOLATED link where MITM is not in scope.
    DLP_LLM_VERIFY_SSL = os.environ.get('DLP_LLM_VERIFY_SSL', 'false').strip().lower() in ('1', 'true', 'yes', 'on')
    DLP_LLM_CA_BUNDLE = os.environ.get('DLP_LLM_CA_BUNDLE', '').strip()  # PEM path pinning the self-signed Ollama cert
    DLP_LLM_TIMEOUT = int(os.environ.get('DLP_LLM_TIMEOUT', '8'))      # seconds; on the send path, fail-open
    DLP_LLM_NUM_CTX = int(os.environ.get('DLP_LLM_NUM_CTX', '8192'))   # per-request KV window (×OLLAMA_NUM_PARALLEL)
    DLP_LLM_MAX_INPUT_CHARS = int(os.environ.get('DLP_LLM_MAX_INPUT_CHARS', '8000'))  # text truncation before scan

    # File uploads
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB
    UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'uploads')
    # Images + documents extractable to text (markitdown) + native PDF.
    ALLOWED_EXTENSIONS = {
        'png', 'jpg', 'jpeg', 'gif', 'webp', 'pdf', 'doc', 'docx', 'txt',
        'xlsx', 'xls', 'pptx', 'csv', 'tsv', 'html', 'htm', 'md', 'json',
        'jsonl', 'parquet', 'xml',
        'rtf', 'odt', 'epub', 'zip',
        # Audio — stored disk-backed, no text extraction (forwarded to A/V-capable models).
        'mp3', 'wav', 'm4a', 'ogg', 'flac', 'aac', 'aiff',
        # Video — stored disk-backed, no text extraction.
        'mp4', 'webm', 'mov', 'mpeg', 'mpg',
    }

    # Chat attachments — upload byte cap (route streams past MAX_CONTENT_LENGTH)
    # and per-document / per-message extracted-text budgets (chars).
    CHAT_UPLOAD_MAX_BYTES = int(os.environ.get('CHAT_UPLOAD_MAX_BYTES', 32 * 1024 * 1024))
    DOC_EXTRACT_MAX_CHARS = int(os.environ.get('DOC_EXTRACT_MAX_CHARS', 200000))
    DOC_EXTRACT_TOTAL_MAX_CHARS = int(os.environ.get('DOC_EXTRACT_TOTAL_MAX_CHARS', 400000))
    WEB_SEARCH_MAX_RESULTS = int(os.environ.get('WEB_SEARCH_MAX_RESULTS', 5))
    PDF_OCR_ENGINE = os.environ.get('PDF_OCR_ENGINE', 'mistral-ocr')

    # Data Analyzer sandbox (ChatGPT-Code-Interpreter-style pandas execution).
    # LLM-authored pandas code runs on user-uploaded CSV/Excel/txt inside a
    # HARDENED CPython sandbox (bubblewrap in prod, plain subprocess in dev) on a
    # DEDICATED data-science venv — never the backend interpreter. See
    # app/services/sandbox_service.py for the hardening rationale + provisioning.
    #   * MODE 'dev' (default locally) → plain subprocess, NO OS isolation.
    #   * MODE 'prod' (prod sets it)   → bwrap/firejail required; fail-closed.
    # Default lives OUTSIDE the repo (system temp) so the per-conversation
    # ``<workdir>/run/code.py`` the sandbox writes each call does NOT sit under
    # ``backend/`` — else dev's ``uvicorn --reload`` (run-fastapi.bat) sees a new
    # *.py and restarts mid-stream, killing the SSE. Prod sets this explicitly.
    DATA_SANDBOX_ROOT = os.environ.get(
        'DATA_SANDBOX_ROOT',
        os.path.join(tempfile.gettempdir(), 'polymind_data_sandbox'),
    )
    DATA_SANDBOX_MODE = os.environ.get('DATA_SANDBOX_MODE', 'dev').strip().lower()
    DATA_SANDBOX_TIMEOUT_S = int(os.environ.get('DATA_SANDBOX_TIMEOUT_S', '20'))
    DATA_SANDBOX_MEM_MB = int(os.environ.get('DATA_SANDBOX_MEM_MB', '1024'))
    DATA_SANDBOX_MAX_CONCURRENCY = int(os.environ.get('DATA_SANDBOX_MAX_CONCURRENCY', '3'))
    # Path to the dedicated sandbox venv's python (analyst libs: pandas, numpy,
    # scipy, scikit-learn, statsmodels, pyarrow, openpyxl — NO matplotlib).
    DATA_SANDBOX_VENV = os.environ.get(
        'DATA_SANDBOX_VENV',
        os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'sandbox', '.venv-sandbox'),
    )
    # Max LLM<->sandbox code-execution round trips per Data Analyzer turn.
    DATA_PY_MAX_ROUNDS = int(os.environ.get('DATA_PY_MAX_ROUNDS', '14'))
    # Stale per-conversation workdir TTL for prune_workdirs (hours).
    DATA_WORKDIR_TTL_HOURS = float(os.environ.get('DATA_WORKDIR_TTL_HOURS', '24'))
    # Dual-model path: heavy for complex stats/joins; fast for simple describe.
    # DATA_ANALYSIS_DUAL_MODEL=0 forces heavy always.
    DATA_ANALYSIS_MODEL = os.environ.get(
        'DATA_ANALYSIS_MODEL', 'anthropic/claude-sonnet-5',
    ).strip()
    DATA_ANALYSIS_MODEL_FAST = os.environ.get(
        'DATA_ANALYSIS_MODEL_FAST', 'google/gemini-3.5-flash-lite',
    ).strip()
    DATA_ANALYSIS_DUAL_MODEL = os.environ.get(
        'DATA_ANALYSIS_DUAL_MODEL', '1',
    ).strip()

    # Data Analyzer document ingestion (PDFs / images / office docs → text files
    # in the sandbox data/ dir). PDFs + images are transcribed via a one-shot
    # OpenRouter call; office/html formats reuse document_extraction_service.
    #   * DATA_PDF_ENGINE — file-parser OCR engine for the PDF transcription call.
    #     Empty ('') means fall back to PDF_OCR_ENGINE at the call site (so the
    #     Data Analyzer tracks the chat PDF engine unless overridden separately).
    #   * DATA_PDF_EXTRACT_MODEL — vision model that transcribes PDFs/images.
    #   * DATA_OUTPUT_MAX_FILES / DATA_OUTPUT_MAX_BYTES — caps for runner-written
    #     output artifacts (consumed by the sandbox layer; defined here so all
    #     Data Analyzer knobs live together).
    DATA_PDF_ENGINE = os.environ.get('DATA_PDF_ENGINE', '')
    DATA_PDF_EXTRACT_MODEL = os.environ.get('DATA_PDF_EXTRACT_MODEL', 'google/gemini-3.5-flash-lite')
    DATA_OUTPUT_MAX_FILES = int(os.environ.get('DATA_OUTPUT_MAX_FILES', '5'))
    DATA_OUTPUT_MAX_BYTES = int(os.environ.get('DATA_OUTPUT_MAX_BYTES', str(64 * 1024 * 1024)))

    # All-in-one router agent (/agent). Fixed orchestrator model (no FE picker).
    # Sonnet for tool routing + data analysis quality; override via env.
    AGENT_ORCHESTRATOR_MODEL = os.environ.get(
        'AGENT_ORCHESTRATOR_MODEL', 'anthropic/claude-sonnet-5',
    ).strip()
    AGENT_SUBAGENT_MODEL = os.environ.get(
        'AGENT_SUBAGENT_MODEL', 'google/gemini-3.5-flash-lite',
    ).strip()
    # Default off — enable with AGENT_SUBAGENT=1 (adds latency under egress).
    AGENT_SUBAGENT = os.environ.get('AGENT_SUBAGENT', '0').strip()
    AGENT_MAX_ROUNDS = int(os.environ.get('AGENT_MAX_ROUNDS', '12'))
    # Default low — medium/high make some Gemini responses put text only in
    # ``reasoning`` (empty content) and slow simple turns. Override via env.
    AGENT_REASONING_EFFORT = os.environ.get(
        'AGENT_REASONING_EFFORT', 'low',
    ).strip().lower()
    AGENT_IMAGE_MODEL = os.environ.get(
        'AGENT_IMAGE_MODEL', 'google/gemini-3.1-flash-image',
    ).strip()

    # Meetings feature
    ELEVENLABS_API_KEY = os.environ.get('ELEVENLABS_API_KEY', '')
    MEETING_UPLOAD_SUBDIR = 'meetings'
    MEETING_ALLOWED_AUDIO_EXTS = {'mp3', 'wav', 'm4a', 'webm', 'ogg', 'mp4'}
    MEETING_MAX_AUDIO_BYTES = 500 * 1024 * 1024  # 500MB cap; route streams past Flask's MAX_CONTENT_LENGTH

    # Rate limiting
    RATELIMIT_DEFAULT = "100 per minute"
    RATELIMIT_STORAGE_URL = "memory://"

    # CORS — raw env value; no default (production must set, dev gets None → flask-cors allows all)
    CORS_ORIGINS = os.environ.get('CORS_ORIGINS')

    # Keycloak SSO — optional. When KEYCLOAK_URL is blank, SSO is disabled and
    # the backend serves only the legacy HS256 email/password auth path.
    # Token validity check uses claim `azp == client_id` (canonical KC pattern).
    # No separate audience var needed.
    KEYCLOAK_URL = os.environ.get('KEYCLOAK_URL', '').rstrip('/')          # e.g. https://keycloak.example.com
    KEYCLOAK_REALM = os.environ.get('KEYCLOAK_REALM', '')                  # e.g. polymind
    KEYCLOAK_CLIENT_ID = os.environ.get('KEYCLOAK_CLIENT_ID', '')          # e.g. polymind-app

    # Public SPA origin for OIDC redirect_uri / post_logout_redirect_uri
    # (e.g. https://unichat.example.com). Blank → /auth/keycloak/config uses the
    # request Origin header so local/dev still works without extra env.
    APP_PUBLIC_URL = os.environ.get('APP_PUBLIC_URL', '').rstrip('/')

    # When False (default), Keycloak realm roles do NOT drive users.role:
    # brand-new SSO users are created as plain 'user' and an existing user's
    # DB role is NEVER overwritten on login. Roles are then managed in the DB
    # only. Flip to True to restore IdP-as-truth role re-sync on every login.
    KEYCLOAK_SYNC_ROLES = os.environ.get('KEYCLOAK_SYNC_ROLES', 'false').strip().lower() in ('1', 'true', 'yes', 'on')

    @staticmethod
    def validate():
        """Validate required environment variables"""
        required = ['SECRET_KEY', 'JWT_SECRET_KEY', 'OPENROUTER_API_KEY']
        missing = [var for var in required if not os.environ.get(var)]
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

        secret_key = os.environ.get('SECRET_KEY', '')
        if len(secret_key) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters long")

        jwt_secret = os.environ.get('JWT_SECRET_KEY', '')
        if len(jwt_secret) < 32:
            raise ValueError("JWT_SECRET_KEY must be at least 32 characters long")


class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG = True
    FLASK_ENV = 'development'

    # Relaxed settings for development
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=24)
    RATELIMIT_ENABLED = False

    @staticmethod
    def validate():
        # Development can use defaults
        pass


class ProductionConfig(Config):
    """Production configuration"""
    DEBUG = False
    FLASK_ENV = 'production'

    # Stricter settings
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'

    # Rate limiting
    RATELIMIT_ENABLED = True
    RATELIMIT_STORAGE_URL = os.environ.get('REDIS_URL', 'memory://')

    # CORS must be explicit in production — parse comma-separated origins
    CORS_ORIGINS = [o.strip() for o in os.environ.get('CORS_ORIGINS', '').split(',') if o.strip()]

    @staticmethod
    def validate():
        Config.validate()

        # Additional production checks
        # CORS must be explicit in production UNLESS same-origin deploy (Traefik
        # fronts frontend + backend on the same domain → CORS not used).
        # Set SAME_ORIGIN=1 in prod compose env to skip this guard.
        same_origin = os.environ.get('SAME_ORIGIN', '').strip() in {'1', 'true', 'True'}
        if not os.environ.get('CORS_ORIGINS') and not same_origin:
            raise ValueError("CORS_ORIGINS must be set in production (or set SAME_ORIGIN=1)")

        # Postgres URI required in prod — the placeholder in Config base is
        # dev-only; production MUST set this explicitly.
        if not os.environ.get('SQLALCHEMY_DATABASE_URI'):
            raise ValueError("SQLALCHEMY_DATABASE_URI must be set in production")

        # Data Analyzer must not run untrusted model code as a plain subprocess
        # on a production worker. Explicit MODE=prod is required (bwrap path).
        mode = os.environ.get('DATA_SANDBOX_MODE', 'dev').strip().lower()
        if mode != 'prod':
            raise ValueError(
                "DATA_SANDBOX_MODE must be 'prod' when FLASK_ENV=production "
                "(refusing unsandboxed data analysis)"
            )


class TestingConfig(Config):
    """Testing configuration"""
    TESTING = True
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = _normalize_pg_uri(os.environ.get(
        'SQLALCHEMY_DATABASE_URI',
        'postgresql+psycopg://localhost/unichat_test',
    ))
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=5)
    RATELIMIT_ENABLED = False

    # The test suite runs serially with a per-test TRUNCATE; the big production
    # pool would just sit idle and keep extra backends open (the per-test cleanup
    # also terminates idle-in-transaction backends). Keep it small. pool_pre_ping
    # / pool_recycle are inherited from the base Config dict.
    SQLALCHEMY_ENGINE_OPTIONS = {
        **Config.SQLALCHEMY_ENGINE_OPTIONS,
        "pool_size": int(os.environ.get("DB_POOL_SIZE", "5")),
        "max_overflow": int(os.environ.get("DB_MAX_OVERFLOW", "10")),
    }

    @staticmethod
    def validate():
        pass


# Config selector
config_by_name = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}


def get_config():
    """Get configuration based on environment"""
    env = os.environ.get('FLASK_ENV', 'development')
    config_class = config_by_name.get(env, DevelopmentConfig)
    config_class.validate()
    return config_class
