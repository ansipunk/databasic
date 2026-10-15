import os
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

DATABASE_URLS = [pytest.param(None, id="aiosqlite")]
for driver, env_var in [
    ("asyncmy", "DATABASIC_TEST_DB_MYSQL_URL"),
    ("psycopg", "DATABASIC_TEST_DB_POSTGRESQL_URL"),
]:
    if url := os.environ.get(env_var):
        DATABASE_URLS.append(pytest.param(url, id=driver))


@pytest.fixture
def test_db_conninfo(test_db_url: sa.URL) -> str:
    return test_db_url.render_as_string(hide_password=False)


@pytest.fixture(params=DATABASE_URLS)
def test_db_url(request: pytest.FixtureRequest, tmp_path: Path) -> sa.URL:
    if request.param is None:
        return sa.URL.create(
            "sqlite+aiosqlite", database=str(tmp_path / "databasic.db")
        )
    return sa.make_url(request.param)


@pytest.fixture(autouse=True)
def sqlite_transactions(test_db_url: sa.URL) -> Iterator[None]:
    if test_db_url.get_backend_name() != "sqlite":
        yield
        return

    # Disable SQLite's legacy transaction control so savepoints participate in
    # the outer transaction, including in Databasic's force_rollback mode.
    def on_connect(dbapi_connection: Any, connection_record: Any) -> None:
        _ = connection_record
        dbapi_connection.isolation_level = None

    def on_begin(conn: sa.Connection) -> None:
        conn.exec_driver_sql("BEGIN")

    event.listen(sa.Engine, "connect", on_connect)
    event.listen(sa.Engine, "begin", on_begin)
    try:
        yield
    finally:
        event.remove(sa.Engine, "begin", on_begin)
        event.remove(sa.Engine, "connect", on_connect)


@pytest_asyncio.fixture
async def test_db_engine(test_db_url: sa.URL) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(test_db_url)

    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def temp_table(test_db_engine: AsyncEngine) -> AsyncIterator[sa.Table]:
    metadata = sa.MetaData()

    table = sa.Table(
        f"databasic_test_{uuid.uuid4().hex}",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("int_val", sa.Integer, nullable=False),
        sa.Column("str_val", sa.Text, nullable=True),
        sa.Column("json_val", sa.JSON, nullable=True),
        sa.Column(
            "jsonb_val", sa.JSON().with_variant(JSONB, "postgresql"), nullable=True
        ),
    )

    async with test_db_engine.begin() as conn:
        await conn.run_sync(metadata.create_all)

    try:
        yield table
    finally:
        async with test_db_engine.begin() as conn:
            await conn.run_sync(table.drop)


@pytest.fixture(
    params=[
        pytest.param(
            {
                "name": "Alice",
                "count": 42,
                "ratio": 1.5,
                "active": True,
                "missing": None,
                "nested": {"items": [1, "two", False, None]},
            },
            id="object",
        ),
        pytest.param([1, "two", {"nested": []}, False, None], id="array"),
        pytest.param("Hello, 世界", id="string"),
        pytest.param(42, id="integer"),
        pytest.param(1.5, id="float"),
        pytest.param(True, id="boolean"),
        pytest.param(None, id="null"),
    ]
)
def json_value(request: pytest.FixtureRequest) -> Any:
    return request.param
