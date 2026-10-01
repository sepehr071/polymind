"""Unit tests for the process-local TTL cache on ``get_features()``.

These patch ``PlatformSettingsModel.get`` (the underlying DB read) so they
exercise only the cache layer — no DB connection required. The cache is
module-global, so every test resets it via ``_invalidate_features_cache``.
"""

from unittest.mock import patch

import pytest

from app.models.platform_settings import (
    DEFAULT_FEATURES,
    PlatformSettingsModel,
    _invalidate_features_cache,
)


@pytest.fixture(autouse=True)
def _reset_cache():
    """Ensure a clean cache before and after every case."""
    _invalidate_features_cache()
    yield
    _invalidate_features_cache()


def _fake_singleton(features: dict) -> dict:
    return {
        '_id': 'singleton',
        'features': features,
        'updated_at': None,
        'updated_by': None,
        'holding_credits_topups_usd': 0.0,
        'holding_credits_transferred_usd': 0.0,
    }


def test_repeated_reads_within_ttl_hit_cache():
    """Second+ ``get_features()`` inside the TTL window must NOT re-read DB."""
    features = dict(DEFAULT_FEATURES)
    with patch.object(
        PlatformSettingsModel, 'get', return_value=_fake_singleton(features)
    ) as mock_get:
        first = PlatformSettingsModel.get_features()
        second = PlatformSettingsModel.get_features()
        third = PlatformSettingsModel.get_features()

    assert first == DEFAULT_FEATURES
    assert second == DEFAULT_FEATURES
    assert third == DEFAULT_FEATURES
    # DB read happened exactly once; the next two came from cache.
    assert mock_get.call_count == 1


def test_invalidate_forces_reread():
    """After invalidation the next read must hit the DB again."""
    features = dict(DEFAULT_FEATURES)
    with patch.object(
        PlatformSettingsModel, 'get', return_value=_fake_singleton(features)
    ) as mock_get:
        PlatformSettingsModel.get_features()
        assert mock_get.call_count == 1

        _invalidate_features_cache()

        PlatformSettingsModel.get_features()
        assert mock_get.call_count == 2


def test_write_invalidates_cache():
    """A features write (``set_feature``) must invalidate so the flip is seen.

    We stub ``_write_features`` to skip the real DB upsert but still run the
    invalidation hook, then assert the post-write read re-fetches from DB and
    observes the new value.
    """
    state = {'data_analyzer': True, **{k: v for k, v in DEFAULT_FEATURES.items()}}

    def fake_get():
        return _fake_singleton(dict(state))

    def fake_write(features, by):
        # Mimic the real chokepoint: persist (here: in-memory) then invalidate.
        state.update(features)
        _invalidate_features_cache()
        return _fake_singleton(dict(state))

    with patch.object(PlatformSettingsModel, 'get', side_effect=fake_get) as mock_get, \
            patch.object(PlatformSettingsModel, '_write_features', side_effect=fake_write):
        # Warm the cache.
        assert PlatformSettingsModel.get_features()['data_analyzer'] is True
        assert mock_get.call_count == 1

        # Flip the flag through the real set_feature path (reads cache, writes).
        PlatformSettingsModel.set_feature('data_analyzer', False, by=None)

        # The write invalidated the cache → this read re-fetches and sees False.
        after = PlatformSettingsModel.get_features()
        assert after['data_analyzer'] is False
        # One warm read + one read inside set_feature + this post-write read.
        assert mock_get.call_count >= 2


def test_caller_mutation_does_not_corrupt_cache():
    """The copy guarantee: mutating a returned dict must not poison the cache."""
    features = dict(DEFAULT_FEATURES)
    with patch.object(
        PlatformSettingsModel, 'get', return_value=_fake_singleton(features)
    ) as mock_get:
        first = PlatformSettingsModel.get_features()
        # Caller mutates the handed-out dict (this is exactly what set_feature
        # does internally: ``features[name] = enabled``).
        first['arena'] = True
        first['data_analyzer'] = False
        first['__injected__'] = 'evil'

        # Next read is still within TTL → served from cache, but must reflect
        # the ORIGINAL values, not the caller's mutations.
        second = PlatformSettingsModel.get_features()

    assert mock_get.call_count == 1  # still a cache hit
    assert second == DEFAULT_FEATURES
    assert second['arena'] is False
    assert second['data_analyzer'] is True
    assert '__injected__' not in second
    # And the two handed-out dicts are distinct objects.
    assert first is not second
