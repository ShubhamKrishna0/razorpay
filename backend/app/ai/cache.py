"""Exception fingerprint cache.

The same exception shape recurs constantly across runs — the same merchant, the
same fee delta, the same gateway quirk. Paying a model to re-derive an identical
conclusion is pure waste, so verdicts are keyed by a hash of the *decision-
relevant* fields and reused.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections import OrderedDict
from typing import Any

from app.config import settings

log = logging.getLogger(__name__)

#: Fields that actually change the verdict. Deliberately excludes ids and
#: timestamps, so two structurally identical breaks share one cache entry.
FINGERPRINT_FIELDS = (
    "exception_type", "order_amount_minor", "payment_amount_minor",
    "settlement_amount_minor", "expected_fee_minor", "payment_delta_minor",
    "settlement_delta_minor", "has_order", "has_payment", "has_settlement",
    "is_duplicate", "currency",
)


def fingerprint(case: dict[str, Any]) -> str:
    payload = {k: case.get(k) for k in FINGERPRINT_FIELDS}
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:32]


class VerdictCache:
    """Redis when configured, bounded in-process LRU otherwise.

    Both paths are optional: a cache miss costs a model call, never correctness.
    """

    def __init__(self, max_items: int = 50_000) -> None:
        self._local: OrderedDict[str, dict] = OrderedDict()
        self._max = max_items
        self._redis = None
        if settings.redis_url:
            try:
                import redis  # imported lazily so redis stays an optional dep

                self._redis = redis.Redis.from_url(settings.redis_url, decode_responses=True)
                self._redis.ping()
                log.info("verdict cache: redis")
            except Exception as exc:  # pragma: no cover - env dependent
                log.warning("redis unavailable (%s); using in-process cache", exc)
                self._redis = None

    def get(self, key: str) -> dict | None:
        if self._redis is not None:
            try:
                raw = self._redis.get(f"verdict:{key}")
                return json.loads(raw) if raw else None
            except Exception:
                return None
        val = self._local.get(key)
        if val is not None:
            self._local.move_to_end(key)
        return val

    def set(self, key: str, value: dict) -> None:
        if self._redis is not None:
            try:
                self._redis.setex(f"verdict:{key}", settings.cache_ttl_seconds, json.dumps(value))
                return
            except Exception:
                pass
        self._local[key] = value
        self._local.move_to_end(key)
        while len(self._local) > self._max:
            self._local.popitem(last=False)

    def stats(self) -> dict[str, Any]:
        return {"backend": "redis" if self._redis else "memory", "local_entries": len(self._local)}


_cache: VerdictCache | None = None


def get_cache() -> VerdictCache:
    global _cache
    if _cache is None:
        _cache = VerdictCache()
    return _cache
