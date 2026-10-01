import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
import sqlalchemy as sa


@dataclass
class DatabaseCredentials:
    host: str
    port: int
    username: str
    password: str
    database: str


@pytest.fixture
def test_db_creds() -> DatabaseCredentials:
    return DatabaseCredentials(
        host=os.environ.get("DATABASIC_TEST_DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("DATABASIC_TEST_DB_PORT", "5432")),
        username=os.environ.get("DATABASIC_TEST_DB_USERNAME", "postgres"),
        password=os.environ.get("DATABASIC_TEST_DB_PASSWORD", "postgres"),
        database=os.environ.get("DATABASIC_TEST_DB_DATABASE", "postgres"),
    )


@pytest.fixture
def test_db_conninfo(test_db_creds: DatabaseCredentials) -> str:
    return (
        f"host={test_db_creds.host} "
        f"port={test_db_creds.port} "
        f"user={test_db_creds.username} "
        f"password={test_db_creds.password} "
        f"dbname={test_db_creds.database}"
    )


@pytest.fixture
def test_db_url(test_db_creds: DatabaseCredentials) -> sa.URL:
    return sa.URL.create(
        drivername="postgresql+psycopg",
        username=test_db_creds.username,
        password=test_db_creds.password,
        host=test_db_creds.host,
        port=test_db_creds.port,
        database=test_db_creds.database,
    )


@pytest.fixture
def test_db_engine(test_db_url: sa.URL) -> Iterator[sa.Engine]:
    engine = sa.create_engine(test_db_url)

    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def temp_table(test_db_engine: sa.Engine) -> Iterator[sa.Table]:
    metadata = sa.MetaData()

    table = sa.Table(
        f"databasic_test_{uuid.uuid4().hex}",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("int_val", sa.Integer, nullable=False),
        sa.Column("str_val", sa.Text, nullable=True),
    )

    with test_db_engine.begin() as conn:
        metadata.create_all(conn)

    try:
        yield table
    finally:
        with test_db_engine.begin() as conn:
            table.drop(conn)
