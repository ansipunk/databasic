from contextlib import suppress
from typing import Any, cast

import pytest
from sqlalchemy import Table, bindparam

import databasic


@pytest.mark.asyncio
async def test_get_session_database_not_connected(test_db_conninfo: str):
    db = databasic.Databasic(test_db_conninfo)

    with pytest.raises(databasic.DatabaseNotConnectedError):
        async with db.session():
            pass


@pytest.mark.asyncio
async def test_connect_connected_database(test_db_conninfo: str):
    db = databasic.Databasic(test_db_conninfo)

    await db.connect()

    with pytest.raises(databasic.DatabaseAlreadyConnectedError):
        await db.connect()

    await db.disconnect()


@pytest.mark.asyncio
async def test_disconnect_not_connected_database(test_db_conninfo: str):
    db = databasic.Databasic(test_db_conninfo)

    with pytest.raises(databasic.DatabaseNotConnectedError):
        await db.disconnect()


@pytest.mark.asyncio
async def test_successful_transaction(temp_table: Table, test_db_conninfo: str):
    db = databasic.Databasic(test_db_conninfo)

    await db.connect()

    async with db.session() as session:
        async with session.transaction():
            query = temp_table.insert().values(int_val=1)
            await session.execute(query)

        query = temp_table.select()
        rows = await session.fetch_all(query)

        assert len(rows) == 1

    await db.disconnect()


@pytest.mark.asyncio
async def test_failed_transaction(temp_table: Table, test_db_conninfo: str):
    db = databasic.Databasic(test_db_conninfo)

    await db.connect()

    async with db.session() as session:
        with suppress(RuntimeError):
            async with session.transaction():
                query = temp_table.insert().values(int_val=1)
                await session.execute(query)
                raise RuntimeError

        query = temp_table.select()
        rows = await session.fetch_all(query)

        assert len(rows) == 0

    await db.disconnect()


@pytest.mark.asyncio
async def test_execute_many(temp_table: Table, test_db_conninfo: str):
    db = databasic.Databasic(test_db_conninfo)

    await db.connect()

    async with db.session() as session:
        query = temp_table.insert().values(
            int_val=bindparam("int_val"),
            str_val=bindparam("str_val"),
        )

        await session.execute_many(
            query,
            [
                {"int_val": 1, "str_val": "1"},
                {"int_val": 2, "str_val": "2"},
            ],
        )

        query = temp_table.select()
        rows_in_db = await session.fetch_all(query)

        assert len(rows_in_db) == 2

        for row in rows_in_db:
            assert row["int_val"] in (1, 2)
            assert row["str_val"] in ("1", "2")

            assert str(row["int_val"]) == row["str_val"]

    await db.disconnect()


@pytest.mark.asyncio
async def test_basic_operations(temp_table: Table, test_db_conninfo: str):
    db = databasic.Databasic(test_db_conninfo)

    await db.connect()

    int_val = 5
    str_val = "Test"

    async with db.session() as session:
        insert_query = (
            temp_table.insert()
            .values(
                int_val=int_val,
                str_val=str_val,
            )
            .returning(*temp_table.c)
        )
        inserted_row = cast(dict[str, Any], await session.fetch_one(insert_query))

        assert inserted_row["id"] is not None
        assert inserted_row["int_val"] == int_val
        assert inserted_row["str_val"] == str_val

        fetch_all_query = temp_table.select()
        fetched_rows = await session.fetch_all(fetch_all_query)

        assert len(fetched_rows) == 1

        assert fetched_rows[0]["id"] == inserted_row["id"]
        assert fetched_rows[0]["int_val"] == inserted_row["int_val"]
        assert fetched_rows[0]["str_val"] == inserted_row["str_val"]

        fetch_one_query = temp_table.select().where(
            temp_table.c.id == inserted_row["id"]
        )
        fetched_row = cast(dict[str, Any], await session.fetch_one(fetch_one_query))

        assert fetched_row["id"] == inserted_row["id"]
        assert fetched_row["int_val"] == inserted_row["int_val"]
        assert fetched_row["str_val"] == inserted_row["str_val"]

        delete_query = temp_table.delete()
        await session.execute(delete_query)

        fetch_all_query = temp_table.select()
        fetched_rows = await session.fetch_all(fetch_all_query)

        assert len(fetched_rows) == 0

    await db.disconnect()


@pytest.mark.asyncio
async def test_context_manager(temp_table: Table, test_db_conninfo: str):
    async with databasic.Databasic(test_db_conninfo) as db:  # noqa: SIM117
        async with db.session() as session:
            query = temp_table.select()
            row = await session.fetch_one(query)
            assert row is None


@pytest.mark.asyncio
async def test_force_rollback_disabled(temp_table: Table, test_db_conninfo: str):
    async with databasic.Databasic(test_db_conninfo, force_rollback=False) as db:  # noqa: SIM117
        async with db.session() as session:
            query = temp_table.insert().values(int_val=0)
            await session.execute(query)

    async with databasic.Databasic(test_db_conninfo) as db:  # noqa: SIM117
        async with db.session() as session:
            query = temp_table.select()
            row = await session.fetch_one(query)
            assert row is not None


@pytest.mark.asyncio
async def test_force_rollback_enabled(temp_table: Table, test_db_conninfo: str):
    async with databasic.Databasic(test_db_conninfo, force_rollback=True) as db:  # noqa: SIM117
        async with db.session() as session:
            query = temp_table.insert().values(int_val=0)
            await session.execute(query)

    async with databasic.Databasic(test_db_conninfo) as db:  # noqa: SIM117
        async with db.session() as session:
            query = temp_table.select()
            row = await session.fetch_one(query)
            assert row is None
