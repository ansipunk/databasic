from collections.abc import AsyncIterator, Callable, Iterable, Mapping, Sequence
from contextlib import asynccontextmanager
from typing import Any, LiteralString, cast

from psycopg import AsyncConnection, AsyncCursor
from psycopg_pool import AsyncConnectionPool
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.elements import ClauseElement


class Databasic:
    _pool: AsyncConnectionPool

    def __init__(self, conninfo: str):
        self._pool = AsyncConnectionPool(
            conninfo,
            open=False,
            kwargs={"row_factory": _dict_row_factory},
        )

    async def connect(self) -> None:
        if self._pool._opened:
            raise DatabaseAlreadyConnectedError

        await self._pool.open(wait=True)

    async def disconnect(self) -> None:
        if not self._pool._opened:
            raise DatabaseNotConnectedError

        await self._pool.close()

    @asynccontextmanager
    async def session(self) -> AsyncIterator[Session]:
        if not self._pool._opened:
            raise DatabaseNotConnectedError

        async with self._pool.connection() as conn:  # noqa: SIM117
            async with conn.transaction():
                yield Session(conn)


class Session:
    _conn: AsyncConnection

    def __init__(self, conn: AsyncConnection):
        self._conn = conn

    async def fetch_one(self, query: ClauseElement) -> dict[str, Any] | None:
        cursor = await self._execute(query)
        return cast(dict[str, Any] | None, await cursor.fetchone())

    async def fetch_all(self, query: ClauseElement) -> list[dict[str, Any]]:
        cursor = await self._execute(query)
        return cast(list[dict[str, Any]], await cursor.fetchall())

    async def execute(self, query: ClauseElement) -> None:
        await self._execute(query)

    async def execute_many(
        self,
        query: ClauseElement,
        params: Iterable[Mapping[str, Any]],
    ) -> None:
        """Execute a query multiple times with different paramenters.

        The query must define all values as explicit bind parameters. Values
        must be provided exclusively though `params`, not embedded in the
        SQLAlchemy query itself.

        Usage would roughly be like:

            query = sa.insert(table).values(
                val_a=sa.bindparam("val_a"),
                val_b=sa.bindparam("val_b"),
            )

            await session.execute_many(
                query,
                [
                    {"val_a": 1, "val_2": 2},
                    {"val_a": 3, "val_2": 4},
                ],
            )
        """

        compiled_query, _ = _compile_query(query)

        async with self._conn.cursor() as cursor:
            await cursor.executemany(compiled_query, params)

    async def _execute(self, statement: ClauseElement) -> AsyncCursor:
        query, params = _compile_query(statement)
        return await self._conn.execute(query, params)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        async with self._conn.transaction():
            yield


class DatabasicError(Exception):
    pass


class DatabaseAlreadyConnectedError(DatabasicError):
    pass


class DatabaseNotConnectedError(DatabasicError):
    pass


def _dict_row_factory(
    cursor: AsyncCursor[Any],
) -> Callable[[Sequence[Any]], dict[str, Any] | None]:
    if not cursor.description:
        return lambda _: None

    fields = [c.name for c in cursor.description]

    def make_row(values: Sequence[Any]) -> dict[str, Any]:
        return dict(zip(fields, values))

    return make_row


def _compile_query(statement: ClauseElement) -> tuple[LiteralString, dict[str, Any]]:
    compiled = statement.compile(dialect=postgresql.dialect(paramstyle="pyformat"))
    return cast(LiteralString, compiled.string), compiled.params
