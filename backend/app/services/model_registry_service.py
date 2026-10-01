import logging
import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.extensions import db
from app.models.openrouter_model import OpenRouterModelDoc, OpenRouterModel

logger = logging.getLogger(__name__)


class ModelRegistryService:
    """Service wrapping the openrouter_models collection.

    Provides a single read/refresh path for model metadata — modalities,
    pricing, supported parameters, endpoints.  Falls back gracefully when the
    collection is empty (cold-start).
    """

    BASE_URL = 'https://openrouter.ai/api/v1'

    # In-process endpoints cache: model_id -> (fetched_at, payload)
    _endpoints_cache: dict = {}
    _ENDPOINTS_TTL = timedelta(hours=1)
    # Guards the endpoints-cache refresh against a per-model refetch stampede.
    _endpoints_lock = threading.Lock()

    # Separate cache for the IMAGE API endpoints (GET /images/models/{id}/endpoints).
    # Distinct keyspace from the chat /models/{id}/endpoints cache above (an image
    # slug like google/gemini-3.1-flash-image is only valid on the images
    # endpoint), with its own lock so the two don't serialize against each other.
    _image_endpoints_cache: dict = {}
    _image_endpoints_lock = threading.Lock()

    def __init__(self):
        # Resolved lazily so this can be instantiated outside of app context
        # for testing.  Any method that calls _get_headers() must run inside
        # an app context.
        pass

    def _get_headers(self) -> dict:
        """Return OpenRouter auth headers, reusing OpenRouterService pattern."""
        # Lazy import to avoid circular dependency
        from app.services.openrouter_service import OpenRouterService
        return OpenRouterService.get_headers()

    # ------------------------------------------------------------------
    # Registry refresh
    # ------------------------------------------------------------------

    def refresh(self) -> dict:
        """Fetch the full model list from OpenRouter and upsert into Mongo.

        Returns ``{"synced": N, "at": iso_str}`` on success or
        ``{"error": "..."}`` on network/parse failure.
        Never raises.
        """
        try:
            # Route through OpenRouterService._request so the GET reuses the
            # pooled, retry-configured session (one TLS handshake amortized
            # across calls) and the proxy host-swap, instead of a bare
            # requests.get() that opens a fresh connection every refresh.
            from app.services.openrouter_service import OpenRouterService
            resp = OpenRouterService._request(
                'GET',
                f'{self.BASE_URL}/models',
                headers=self._get_headers(),
                timeout=(5, 30),
            )
            resp.raise_for_status()
            data = resp.json()
            items = data.get('data', [])
            synced = OpenRouterModelDoc.upsert_many(items)
            at = datetime.utcnow().isoformat()
            logger.info('model_registry refresh: synced=%d at=%s', synced, at)
            return {'synced': synced, 'at': at}
        except Exception as exc:
            logger.warning('model_registry refresh failed: %s', exc)
            return {'error': str(exc)}

    # ------------------------------------------------------------------
    # Single model access
    # ------------------------------------------------------------------

    def get(self, model_id: str) -> dict | None:
        return OpenRouterModelDoc.get_by_id(model_id)

    @staticmethod
    def load_expiration_map() -> dict:
        """Return ``{model_id: expiration_date}`` for the whole catalog.

        Narrow two-column read used by the chat_completion deprecation memo —
        deliberately avoids fetching the heavy ``raw`` JSONB blob that
        ``get()``/``get_by_id()`` pulls per row. Returns an empty dict when the
        catalog is empty; callers treat a missing key as "not deprecated".
        """
        rows = db.session.execute(
            select(OpenRouterModel.id, OpenRouterModel.expiration_date)
        ).all()
        return {mid: exp for mid, exp in rows}

    # ------------------------------------------------------------------
    # Filtered queries
    # ------------------------------------------------------------------

    def find_by_modality(self, input: list | None = None, output: list | None = None) -> list:
        return OpenRouterModelDoc.find_by_modality(
            input_modalities=input,
            output_modalities=output,
        )

    def find_by_capability(self, param: str) -> list:
        return OpenRouterModelDoc.find_by_capability(param)

    # ------------------------------------------------------------------
    # Capability helpers
    # ------------------------------------------------------------------

    def is_image_capable(self, model_id: str) -> bool:
        """True if the model can produce image output."""
        doc = self.get(model_id)
        if not doc:
            return False
        return 'image' in doc.get('architecture', {}).get('output_modalities', [])

    def is_vision_capable(self, model_id: str) -> bool:
        """True if the model can accept image input."""
        doc = self.get(model_id)
        if not doc:
            return False
        return 'image' in doc.get('architecture', {}).get('input_modalities', [])

    # ------------------------------------------------------------------
    # Pricing
    # ------------------------------------------------------------------

    def get_pricing(self, model_id: str) -> dict:
        """Return per-token and per-million-token pricing for a model.

        Returns a dict with keys:
          prompt, completion, cached  (per-token floats)
          prompt_per_million, completion_per_million, cached_per_million
        Falls back to all-zeros if model not found.
        """
        _zero = {
            'prompt': 0.0,
            'completion': 0.0,
            'cached': 0.0,
            'prompt_per_million': 0.0,
            'completion_per_million': 0.0,
            'cached_per_million': 0.0,
        }
        doc = self.get(model_id)
        if not doc:
            return _zero

        pricing = doc.get('pricing', {})
        prompt = float(pricing.get('prompt', 0) or 0)
        completion = float(pricing.get('completion', 0) or 0)
        cached = float(pricing.get('cached', 0) or 0)

        return {
            'prompt': prompt,
            'completion': completion,
            'cached': cached,
            'prompt_per_million': prompt * 1_000_000,
            'completion_per_million': completion * 1_000_000,
            'cached_per_million': cached * 1_000_000,
        }

    # ------------------------------------------------------------------
    # Endpoints (lazy-fetch, 1h TTL)
    # ------------------------------------------------------------------

    def get_endpoints(self, model_id: str) -> dict | None:
        """Lazy-fetch and cache the /models/{id}/endpoints response.

        Returns the parsed JSON payload or None on error.
        """
        def _fresh():
            entry = ModelRegistryService._endpoints_cache.get(model_id)
            if entry and datetime.utcnow() - entry[0] < self._ENDPOINTS_TTL:
                return entry[1]
            return None

        # Fast path: serve a warm cache entry without locking.
        cached = _fresh()
        if cached is not None:
            return cached

        # Cold/expired: fetch under a lock (double-checked) so concurrent
        # callers for the same model don't all hit the proxy at once.
        with ModelRegistryService._endpoints_lock:
            cached = _fresh()
            if cached is not None:
                return cached
            try:
                # Reuse the pooled session + proxy host-swap via _request.
                from app.services.openrouter_service import OpenRouterService
                resp = OpenRouterService._request(
                    'GET',
                    f'{self.BASE_URL}/models/{model_id}/endpoints',
                    headers=self._get_headers(),
                    timeout=(5, 15),
                )
                resp.raise_for_status()
                payload = resp.json()
                ModelRegistryService._endpoints_cache[model_id] = (datetime.utcnow(), payload)
                return payload
            except Exception as exc:
                logger.warning('get_endpoints(%s) failed: %s', model_id, exc)
                return None

    def get_image_endpoints(self, model_id: str) -> dict | None:
        """Lazy-fetch + cache GET /images/models/{id}/endpoints.

        Mirrors ``get_endpoints`` (warm fast-path, double-checked lock, 1h TTL,
        fail-open ``None``) but hits the dedicated Image API endpoints route. The
        payload shape is ``{id, endpoints:[{provider_*, supported_parameters,
        pricing, ...}]}`` — callers read ``endpoints[0]`` for the typed parameter
        descriptors + ``pricing[]``.
        """
        def _fresh():
            entry = ModelRegistryService._image_endpoints_cache.get(model_id)
            if entry and datetime.utcnow() - entry[0] < self._ENDPOINTS_TTL:
                return entry[1]
            return None

        cached = _fresh()
        if cached is not None:
            return cached

        with ModelRegistryService._image_endpoints_lock:
            cached = _fresh()
            if cached is not None:
                return cached
            try:
                from app.services.openrouter_service import OpenRouterService
                resp = OpenRouterService._request(
                    'GET',
                    f'{self.BASE_URL}/images/models/{model_id}/endpoints',
                    headers=self._get_headers(),
                    timeout=(5, 15),
                )
                resp.raise_for_status()
                payload = resp.json()
                ModelRegistryService._image_endpoints_cache[model_id] = (
                    datetime.utcnow(), payload,
                )
                return payload
            except Exception as exc:
                logger.warning('get_image_endpoints(%s) failed: %s', model_id, exc)
                return None

    # ------------------------------------------------------------------
    # Staleness
    # ------------------------------------------------------------------

    def is_stale(self) -> bool:
        """True if the registry has never been synced or was last synced >1h ago."""
        last = OpenRouterModelDoc.get_last_sync_at()
        if last is None:
            return True
        # ``last`` comes back from a timezone-aware TIMESTAMP column. Compare in
        # UTC-aware space; treat a naive value (legacy rows) as UTC.
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - last > timedelta(hours=1)

    def _lazy_refresh_if_stale(self) -> None:
        """Best-effort refresh when stale.  Swallows all exceptions."""
        try:
            if self.is_stale():
                self.refresh()
        except Exception as exc:
            logger.warning('_lazy_refresh_if_stale failed: %s', exc)
