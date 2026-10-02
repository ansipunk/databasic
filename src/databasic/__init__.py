from collections.abc import AsyncIterator, Callable, Iterable, Mapping, Sequence
from contextlib import asynccontextmanager
from types import TracebackType
from typing import Any, LiteralString, Self, cast

from psycopg import AsyncConnection as BaseAsyncConnection
from psycopg import AsyncCursor as BaseAsyncCursor
from psycopg import AsyncTransaction
from psycopg_pool import AsyncConnectionPool as BaseAsyncConnectionPool
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.elements import ClauseElement

__all__ = [
    "DatabaseAlreadyConnectedError",
    "DatabaseNotConnectedError",
    "Databasic",
    "DatabasicError",
    "Row",
    "Session",
]

Row = dict[str, Any]
AsyncConnection = BaseAsyncConnection[Row]
AsyncConnectionPool = BaseAsyncConnectionPool[AsyncConnection]
AsyncCursor = BaseAsyncCursor[Row]


class Databasic:
    _pool: AsyncConnectionPool
    _conn: AsyncConnection | None = None
    _global_transaction: AsyncTransaction | None = None
    _force_rollback: bool = False

    def __init__(self, conninfo: str, *, force_rollback: bool = False):
        self._pool = AsyncConnectionPool(
            conninfo,
            open=False,
            kwargs={"row_factory": _dict_row_factory},
        )
        self._force_rollback = force_rollback

    async def __aenter__(self) -> Self:
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        _ = exc_type, exc_value, traceback
        await self.disconnect()

    async def connect(self) -> None:
        if not self._pool.closed:
            raise DatabaseAlreadyConnectedError

        await self._pool.open(wait=True)

        if self._force_rollback:
            try:
                self._conn = await self._pool.getconn()
            except BaseException:  # pragma: no cover
                await self.disconnect()
                raise

            self._global_transaction = AsyncTransaction(
                self._conn,
                force_rollback=True,
            )

            try:
                await self._global_transaction.__aenter__()
            except BaseException:  # pragma: no cover
                await self.disconnect()
                raise

    async def disconnect(self) -> None:
        if self._pool.closed:
            raise DatabaseNotConnectedError

        if self._conn is not None:
            if self._global_transaction is not None:
                await self._global_transaction.__aexit__(None, None, None)
                self._global_transaction = None

            await self._pool.putconn(self._conn)
            self._conn = None

        await self._pool.close()

    @asynccontextmanager
    async def session(self) -> AsyncIterator[Session]:
        if self._pool.closed:
            raise DatabaseNotConnectedError

        if self._conn is not None:
            async with self._conn.transaction():
                yield Session(self._conn)
        else:
            async with self._pool.connection() as conn:  # noqa: SIM117
                async with conn.transaction():
                    yield Session(conn)


class Session:
    _conn: AsyncConnection

    def __init__(self, conn: AsyncConnection):
        self._conn = conn

    async def fetch_one(self, query: ClauseElement) -> Row | None:
        async with self._execute(query) as cursor:
            return await cursor.fetchone()

    async def fetch_all(self, query: ClauseElement) -> list[Row]:
        async with self._execute(query) as cursor:
            return await cursor.fetchall()

    async def execute(self, query: ClauseElement) -> int:
        async with self._execute(query) as cursor:
            return cursor.rowcount

    async def execute_many(
        self,
        query: ClauseElement,
        params: Iterable[Mapping[str, Any]],
    ) -> int:
        """Execute a query multiple times with different parameters.

        The query must define all values as explicit bind parameters. Values
        must be provided exclusively through `params`, not embedded in the
        SQLAlchemy query itself.

        Usage would roughly be like:

            query = sa.insert(table).values(
                val_a=sa.bindparam("val_a"),
                val_b=sa.bindparam("val_b"),
            )

            await session.execute_many(
                query,
                [
                    {"val_a": 1, "val_b": 2},
                    {"val_a": 3, "val_b": 4},
                ],
            )
        """

        compiled_query, _ = _compile_query(query)

        async with self._conn.cursor() as cursor:
            await cursor.executemany(compiled_query, params)
            return cursor.rowcount

    @asynccontextmanager
    async def _execute(self, statement: ClauseElement) -> AsyncIterator[AsyncCursor]:
        query, params = _compile_query(statement)

        async with self._conn.cursor() as cursor:
            await cursor.execute(query, params)
            yield cursor

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


def _dict_row_factory(cursor: AsyncCursor) -> Callable[[Sequence[Any]], Row]:
    fields = [c.name for c in cursor.description or ()]

    def make_row(values: Sequence[Any]) -> Row:
        return dict(zip(fields, values))

    return make_row


def _compile_query(statement: ClauseElement) -> tuple[LiteralString, dict[str, Any]]:
    compiled = statement.compile(dialect=postgresql.dialect(paramstyle="pyformat"))
    return cast(LiteralString, compiled.string), compiled.params
