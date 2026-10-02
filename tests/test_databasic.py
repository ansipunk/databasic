from contextlib import suppress
from typing import Any, cast

import pytest
from sqlalchemy import (
    Engine,
    String,
    Table,
    TypeDecorator,
    bindparam,
    literal,
    select,
    tuple_,
)
from sqlalchemy.schema import CreateTable, DropTable

import databasic


@pytest.mark.asyncio
async def test_get_session_database_not_connected(test_db_conninfo: str):
    db = databasic.Databasic(test_db_conninfo)

    with pytest.raises(databasic.DatabaseNotConnectedError):
        async with db.session():
            pass


@pytest.mark.asyncio
async def test_reuse_instance(test_db_conninfo: str):
    db = databasic.Databasic(test_db_conninfo)

    async with db:
        pass

    with pytest.raises(databasic.DatabaseWasAlreadyOpenedError):
        async with db:
            pass


@pytest.mark.asyncio
async def test_connect_connected_database(test_db_conninfo: str):
    db = databasic.Databasic(test_db_conninfo)

    await db.connect()

    with pytest.raises(databasic.DatabaseWasAlreadyOpenedError):
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
@pytest.mark.parametrize("column_name", ["json_val", "jsonb_val"])
async def test_insert_json(
    temp_table: Table,
    test_db_conninfo: str,
    column_name: str,
    json_value: Any,
):
    async with databasic.Databasic(test_db_conninfo) as db:
        async with db.session() as session:
            query = temp_table.insert().values(int_val=1, **{column_name: json_value})
            assert await session.execute(query) == 1

        async with db.session() as session:
            # None is JSON null with the default JSON type, not SQL NULL.
            query = select(temp_table.c[column_name]).where(
                temp_table.c[column_name].is_not(None)
            )
            assert await session.fetch_one(query) == {column_name: json_value}


@pytest.mark.asyncio
@pytest.mark.parametrize("column_name", ["json_val", "jsonb_val"])
async def test_execute_many_json(
    temp_table: Table,
    test_db_conninfo: str,
    column_name: str,
    json_value: Any,
):
    values = [json_value, {"items": [], "nested": {}}]

    async with databasic.Databasic(test_db_conninfo) as db:
        async with db.session() as session:
            query = temp_table.insert().values(
                int_val=bindparam("int_val"),
                **{column_name: bindparam(column_name)},
            )
            params = [
                {"int_val": index, column_name: value}
                for index, value in enumerate(values)
            ]
            assert await session.execute_many(query, iter(params)) == len(values)

        async with db.session() as session:
            query = (
                select(temp_table.c[column_name])
                .where(temp_table.c[column_name].is_not(None))
                .order_by(temp_table.c.int_val)
            )
            assert await session.fetch_all(query) == [
                {column_name: value} for value in values
            ]


@pytest.mark.asyncio
@pytest.mark.parametrize("column_name", ["json_val", "jsonb_val"])
async def test_fetch_json(
    temp_table: Table,
    test_db_engine: Engine,
    test_db_conninfo: str,
    column_name: str,
    json_value: Any,
):
    with test_db_engine.begin() as conn:
        conn.execute(temp_table.insert().values(int_val=1, **{column_name: json_value}))

    async with databasic.Databasic(test_db_conninfo) as db:  # noqa: SIM117
        async with db.session() as session:
            query = select(temp_table.c[column_name])
            assert await session.fetch_one(query) == {column_name: json_value}
            assert await session.fetch_all(query) == [{column_name: json_value}]


@pytest.mark.asyncio
@pytest.mark.parametrize("tuple_values", [False, True], ids=["single", "tuple"])
async def test_jsonb_expanding_parameters(
    temp_table: Table,
    test_db_conninfo: str,
    json_value: Any,
    tuple_values: bool,
):
    async with databasic.Databasic(test_db_conninfo) as db:  # noqa: SIM117
        async with db.session() as session:
            await session.execute(
                temp_table.insert().values(int_val=1, jsonb_val=json_value)
            )
            if tuple_values:
                columns = tuple_(temp_table.c.int_val, temp_table.c.jsonb_val)
                condition = columns.in_(
                    bindparam(
                        "values", [(1, json_value)], type_=columns.type, expanding=True
                    )
                )
            else:
                condition = temp_table.c.jsonb_val.in_(
                    bindparam(
                        "values",
                        [json_value],
                        type_=temp_table.c.jsonb_val.type,
                        expanding=True,
                    )
                )
            query = select(temp_table.c.jsonb_val).where(condition)
            assert await session.fetch_all(query) == [{"jsonb_val": json_value}]


class PrefixString(TypeDecorator[str]):
    impl = String
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> str:
        _ = dialect
        return f"stored:{value}"


@pytest.mark.asyncio
async def test_custom_bind_processor(test_db_conninfo: str):
    async with databasic.Databasic(test_db_conninfo) as db:  # noqa: SIM117
        async with db.session() as session:
            query = select(literal("Alice", type_=PrefixString()).label("value"))
            assert await session.fetch_one(query) == {"value": "stored:Alice"}


@pytest.mark.asyncio
async def test_execute_many_custom_bind_processor(
    temp_table: Table,
    test_db_conninfo: str,
):
    params = [
        {"int_val": 1, "name.with.dots": "Alice"},
        {"int_val": 2, "name.with.dots": "Bob"},
    ]
    async with databasic.Databasic(test_db_conninfo) as db:  # noqa: SIM117
        async with db.session() as session:
            query = temp_table.insert().values(
                int_val=bindparam("int_val"),
                str_val=bindparam("name.with.dots", type_=PrefixString()),
            )
            assert await session.execute_many(query, iter(params)) == 2
            query = select(temp_table.c.str_val).order_by(temp_table.c.int_val)
            assert await session.fetch_all(query) == [
                {"str_val": "stored:Alice"},
                {"str_val": "stored:Bob"},
            ]
    assert params == [
        {"int_val": 1, "name.with.dots": "Alice"},
        {"int_val": 2, "name.with.dots": "Bob"},
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bind_options",
    [{"expanding": True}, {"literal_execute": True}],
    ids=["expanding", "literal_execute"],
)
async def test_execute_many_postcompile_parameters(
    test_db_conninfo: str,
    bind_options: dict[str, bool],
):
    async with databasic.Databasic(test_db_conninfo) as db:  # noqa: SIM117
        async with db.session() as session:
            query = select(bindparam("value", type_=String, **bind_options))  # ty: ignore[invalid-argument-type]
            with pytest.raises(ValueError, match="does not support"):
                await session.execute_many(query, [{"value": "Alice"}])


@pytest.mark.asyncio
async def test_ddl(temp_table: Table, test_db_conninfo: str):
    async with databasic.Databasic(test_db_conninfo) as db:  # noqa: SIM117
        async with db.session() as session:
            await session.execute(DropTable(temp_table))
            await session.execute(CreateTable(temp_table))
            assert await session.fetch_all(temp_table.select()) == []


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


@pytest.mark.asyncio
async def test_complex_queries(temp_table: Table, test_db_conninfo: str):
    async with databasic.Databasic(test_db_conninfo) as db:  # noqa: SIM117
        async with db.session() as session:
            query = temp_table.select().where(
                temp_table.c.int_val.in_([1, 2]),
            )
            row = await session.fetch_one(query)
            assert row is None
