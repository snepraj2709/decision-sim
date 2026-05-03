"""Tests for the development demo cache."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import pytest

from app.pipelines.demo_cache import get_or_create_cached_snapshot_id, should_use_demo_cache


class _ScalarResult:
    def __init__(self, scalar: object | None = None, scalars: Sequence[object] = ()) -> None:
        self._scalar = scalar
        self._scalars = list(scalars)

    def scalar_one_or_none(self) -> object | None:
        return self._scalar

    def scalars(self) -> _ScalarResult:
        return self

    def all(self) -> list[object]:
        return self._scalars


class _FakeDb:
    def __init__(self, results: Sequence[_ScalarResult]) -> None:
        self.results = list(results)
        self.execute_count = 0
        self.added: list[object] = []
        self.commits = 0

    async def execute(self, _stmt: object) -> _ScalarResult:
        self.execute_count += 1
        if not self.results:
            raise AssertionError("Unexpected execute")
        return self.results.pop(0)

    def add(self, value: object) -> None:
        self.added.append(value)

    def add_all(self, values: Sequence[object]) -> None:
        self.added.extend(values)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1


def test_demo_cache_only_matches_root_netflix_urls() -> None:
    assert should_use_demo_cache("https://netflix.com")
    assert should_use_demo_cache("https://www.netflix.com/")
    assert not should_use_demo_cache("https://netflix.com/pricing")
    assert not should_use_demo_cache("https://linear.app")


@pytest.mark.asyncio
async def test_cached_snapshot_hit_returns_existing_id_without_seeding() -> None:
    snapshot_id = uuid.uuid4()
    db = _FakeDb([_ScalarResult(snapshot_id)])

    result = await get_or_create_cached_snapshot_id("https://www.netflix.com", db)  # type: ignore[arg-type]

    assert result == snapshot_id
    assert db.execute_count == 1
    assert db.added == []
    assert db.commits == 0


@pytest.mark.asyncio
async def test_non_demo_url_does_not_touch_database() -> None:
    db = _FakeDb([])

    result = await get_or_create_cached_snapshot_id("https://linear.app", db)  # type: ignore[arg-type]

    assert result is None
    assert db.execute_count == 0
