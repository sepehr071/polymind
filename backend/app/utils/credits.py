"""Polymind Credits — the user-facing normalized usage unit.

A pure display transform of the (marked-up) ``cost_usd`` price:
``credits = round(cost_usd × credits_per_usd)``. No storage, no migration — it
is computed on read wherever a non-$ viewer (a normal employee) sees usage, so
the dollar figure never leaves the backend. ``credits_per_usd`` is a platform
knob (``platform_settings``, default 1000 → $0.001 = 1 credit).

Profit redesign 2026-06-29 — see docs spec + the plan file.
"""

from app.models.platform_settings import PlatformSettingsModel


def to_credits(cost_usd) -> int:
    """One price ($) → whole Polymind Credits. Non-numeric / None → 0."""
    try:
        c = float(cost_usd or 0)
    except (TypeError, ValueError):
        return 0
    return int(round(c * PlatformSettingsModel.get_credits_per_usd()))


def to_credits_each(values) -> list:
    """Vectorized :func:`to_credits` — one cached knob read amortized over the
    whole list (use for per-row mapping of an aggregate)."""
    rate = PlatformSettingsModel.get_credits_per_usd()
    out: list = []
    for v in values:
        try:
            out.append(int(round(float(v or 0) * rate)))
        except (TypeError, ValueError):
            out.append(0)
    return out
