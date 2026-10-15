from collections.abc import AsyncGenerator, AsyncIterator, Iterable, Mapping
from contextlib import asynccontextmanager
from types import TracebackType
from typing import Any, Self

from sqlalchemy import URL, Executable
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncTransaction,
    create_async_engine,
)
from sqlalchemy.pool import AsyncAdaptedQueuePool

__all__ = [
    "DatabaseNotConnectedError",
    "DatabaseWasAlreadyOpenedError",
    "Databasic",
    "DatabasicError",
    "Session",
]


class Databasic:
    _engine: AsyncEngine
    _conn: AsyncConnection | None = None
    _global_transaction: AsyncTransaction | None = None
    _force_rollback: bool = False
    _opened: bool = False
    _connected: bool = False

    def __init__(
        self,
        url: str | URL,
        *,
        force_rollback: bool = False,
        pool_min_size: int = 4,
        pool_max_size: int = 4,
    ):
        if pool_min_size > pool_max_size:
            raise ValueError("Pool max size cannot be less than min size")
        if pool_min_size < 1:
            raise ValueError("Pool min size must be at least 1")

        self._engine = create_async_engine(
            url,
            poolclass=AsyncAdaptedQueuePool,
            pool_size=pool_min_size,
            max_overflow=pool_max_size - pool_min_size,
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
        if self._opened:
            raise DatabaseWasAlreadyOpenedError

        try:
            conn = await self._engine.connect()
            try:
                if self._force_rollback:
                    self._global_transaction = await conn.begin()
                    self._conn = conn
            finally:
                if self._conn is None:
                    await conn.close()
        except BaseException:
            await self._engine.dispose()
            raise

        self._opened = True
        self._connected = True

    async def disconnect(self) -> None:
        if not self._connected:
            raise DatabaseNotConnectedError

        try:
            if self._conn is not None:
                try:
                    if self._global_transaction is not None:
                        await self._global_transaction.rollback()
                finally:
                    await self._conn.close()
        finally:
            self._global_transaction = None
            self._conn = None
            self._connected = False
            await self._engine.dispose()

    @asynccontextmanager
    async def session(self) -> AsyncGenerator["Session"]:
        if not self._connected:
            raise DatabaseNotConnectedError

        if self._conn is not None:
            async with self._conn.begin_nested():
                yield Session(self._conn)
        else:
            async with self._engine.begin() as conn:
                yield Session(conn)


class Session:
    _conn: AsyncConnection

    def __init__(self, conn: AsyncConnection):
        self._conn = conn

    async def fetch_one(self, query: Executable) -> dict[str, Any] | None:
        with await self._conn.execute(query) as result:
            row = result.mappings().first()
            return dict(row) if row is not None else None

    async def fetch_all(self, query: Executable) -> list[dict[str, Any]]:
        with await self._conn.execute(query) as result:
            return [dict(row) for row in result.mappings()]

    async def execute(self, query: Executable) -> int:
        with await self._conn.execute(
            query, execution_options={"preserve_rowcount": True}
        ) as result:
            return result.rowcount

    async def stream(
        self, query: Executable, *, prefetch_size: int = 256
    ) -> AsyncIterator[dict[str, Any]]:
        if prefetch_size < 1:
            raise ValueError("prefetch_size must be at least 1")

        # SQLAlchemy's stream context manager skips result.close() on
        # GeneratorExit, which aclose() injects when this generator is suspended
        # at yield. Close explicitly in finally so early closure frees the cursor.
        result = await self._conn.stream(
            query, execution_options={"yield_per": prefetch_size}
        )
        try:
            async for row in result.mappings():
                yield dict(row)
        finally:
            await result.close()

    async def execute_many(
        self,
        query: Executable,
        params: Iterable[Mapping[str, Any]],
    ) -> int:
        """Execute a statement with multiple parameter mappings.

        Define values using explicit bind parameters and supply them through
        `params`. SQLAlchemy executemany does not support expanding or
        literal-execute parameters. An empty iterable returns zero.
        """

        values = [dict(value) for value in params]
        if not values:
            return 0

        with await self._conn.execute(
            query, values, execution_options={"preserve_rowcount": True}
        ) as result:
            return result.rowcount

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[None]:
        async with self._conn.begin_nested():
            yield


class DatabasicError(Exception):
    pass


class DatabaseWasAlreadyOpenedError(DatabasicError):
    pass


class DatabaseNotConnectedError(DatabasicError):
    pass
