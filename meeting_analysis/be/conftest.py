"""Fixture dùng chung cho test của ``be/``: Redis và cache kết quả v3.

Mặc định Redis là fakeredis (không cần server). Đặt ``V3_TEST_REDIS_URL`` (vd.
``redis://localhost:6379/15`` sau ``docker compose up -d redis``) để chạy các test đó trên Redis
thật; mỗi test dùng tiền tố khoá riêng và xoá khoá của mình khi xong.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable, Iterator

import pytest

from services.analysis_cache import (
    AnalysisCache,
    InMemoryAnalysisStore,
    LocalAnalysisBackend,
    RedisAnalysisBackend,
)


@pytest.fixture
def redis_connect() -> Iterator[Callable[[], object]]:
    """Hàm mở thêm kết nối tới CÙNG một Redis (mỗi kết nối giả một worker)."""

    url = os.environ.get("V3_TEST_REDIS_URL", "").strip()
    if url:
        import redis

        clients = []

        def connect():
            client = redis.Redis.from_url(url)
            clients.append(client)
            return client

        yield connect
        for client in clients:
            client.close()
    else:
        import fakeredis

        server = fakeredis.FakeServer()
        yield lambda: fakeredis.FakeRedis(server=server)


@pytest.fixture
def redis_prefix(redis_connect) -> Iterator[str]:
    """Tiền tố khoá riêng của test; khoá dưới tiền tố bị xoá khi test xong."""

    prefix = f"test:{uuid.uuid4().hex}:"
    yield prefix
    client = redis_connect()
    for name in client.scan_iter(match=f"{prefix}*"):
        client.delete(name)


@pytest.fixture(params=["local", "redis"])
def analysis_cache(request, redis_connect, redis_prefix) -> AnalysisCache:
    """Cache v3 trên từng backend: trong tiến trình (bộ nhớ) và Redis."""

    if request.param == "local":
        return AnalysisCache(LocalAnalysisBackend(InMemoryAnalysisStore()))
    return AnalysisCache(RedisAnalysisBackend(redis_connect(), prefix=redis_prefix))
