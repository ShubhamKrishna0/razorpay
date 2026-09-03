from __future__ import annotations

import pytest

from app.store.db import init_db


@pytest.fixture(scope="session", autouse=True)
def _db() -> None:
    init_db()
