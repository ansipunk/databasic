from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import URL, String, Table, TypeDecorator, literal, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncTransaction
from sqlalchemy.pool import AsyncAdaptedQueuePool

import databasic


class ProcessedString(TypeDecorator[str]):
    impl = String
    cache_ok = True

    def process_result_value(self, value, dialect):
        _ = dialect
        return f"processed:{value}"


@pytest.mark.asyncio
async def test_result_processors(test_db_url: URL):
    async with databasic.Databasic(test_db_url) as db:  # noqa: SIM117
        async with db.session() as session:
            assert isinstance(session._conn, AsyncConnection)
            query = select(literal("Alice", type_=ProcessedString()).label("name"))
            expected = {"name": "processed:Alice"}
            assert await session.fetch_one(query) == expected
            assert await session.fetch_all(query) == [expected]
            assert [row async for row in session.stream(query)] == [expected]


def test_preserves_database_url(test_db_url: URL):
    db = databasic.Databasic(test_db_url)
    assert db._engine.url == test_db_url


@pytest.mark.parametrize("min_size", [0, -1])
def test_invalid_pool_size(test_db_url: URL, min_size: int):
    with pytest.raises(ValueError, match="at least 1"):
        databasic.Databasic(test_db_url, pool_min_size=min_size)


@pytest.mark.asyncio
@pytest.mark.parametrize("force_rollback", [False, True])
async def test_empty_execute_many(test_db_url: URL, force_rollback: bool):
    async with databasic.Databasic(test_db_url, force_rollback=force_rollback) as db:  # noqa: SIM117
        async with db.session() as session:
            assert await session.execute_many(select(literal(1)), iter([])) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("force_rollback", [False, True])
async def test_session_failure(
    test_db_url: URL, temp_table: Table, force_rollback: bool
):
    async with databasic.Databasic(test_db_url, force_rollback=force_rollback) as db:
        async with db.session() as session:
            await session.execute(temp_table.insert().values(int_val=1))
        with pytest.raises(RuntimeError):
            async with db.session() as session:
                await session.execute(temp_table.insert().values(int_val=2))
                raise RuntimeError("roll back this session")
        async with db.session() as session:
            assert await session.fetch_all(select(temp_table.c.int_val)) == [
                {"int_val": 1}
            ]
            with pytest.raises(RuntimeError):
                async with session.transaction():
                    await session.execute(temp_table.insert().values(int_val=3))
                    raise RuntimeError("roll back savepoint")
            assert await session.fetch_all(select(temp_table.c.int_val)) == [
                {"int_val": 1}
            ]

    async with databasic.Databasic(test_db_url) as db:  # noqa: SIM117
        async with db.session() as session:
            assert await session.fetch_all(select(temp_table.c.int_val)) == (
                [] if force_rollback else [{"int_val": 1}]
            )


@pytest.mark.asyncio
async def test_disconnected_database(test_db_url: URL):
    db = databasic.Databasic(test_db_url)
    async with db:
        pass
    with pytest.raises(databasic.DatabaseNotConnectedError):
        await db.disconnect()
    with pytest.raises(databasic.DatabaseNotConnectedError):
        async with db.session():
            pytest.fail("A disconnected database must not yield a session")


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_begin", [False, True])
async def test_failed_connect_can_retry(test_db_url: URL, fail_begin: bool):
    db = databasic.Databasic(test_db_url, force_rollback=fail_begin)
    target, method = (
        (AsyncConnection, "begin") if fail_begin else (AsyncEngine, "connect")
    )
    with (
        patch.object(target, method, side_effect=RuntimeError("connect failed")),
        pytest.raises(RuntimeError, match="connect failed"),
    ):
        await db.connect()
    assert not db._connected
    assert not db._opened
    assert isinstance(db._engine.pool, AsyncAdaptedQueuePool)
    assert db._engine.pool.checkedout() == 0
    async with db:  # noqa: SIM117
        async with db.session() as session:
            assert await session.fetch_one(select(literal(1).label("value"))) == {
                "value": 1
            }


@pytest.mark.asyncio
async def test_disconnect_cleans_up_on_rollback_failure(test_db_url: URL):
    db = databasic.Databasic(test_db_url, force_rollback=True)
    await db.connect()
    with (
        patch.object(
            AsyncTransaction,
            "rollback",
            new=AsyncMock(side_effect=RuntimeError("rollback failed")),
        ),
        pytest.raises(RuntimeError, match="rollback failed"),
    ):
        await db.disconnect()
    assert db._conn is None
    assert db._global_transaction is None
    assert not db._connected
    assert isinstance(db._engine.pool, AsyncAdaptedQueuePool)
    assert db._engine.pool.checkedout() == 0
