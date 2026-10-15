# Databasic

An opinionated async database API built on SQLAlchemy Core. Write SQLAlchemy
queries, run them with straightforward methods, and get plain Python data back.

## Why Databasic?

SQLAlchemy is a powerful SQL toolkit. Databasic keeps that foundation while
providing a small execution API with sensible defaults and fewer decisions to
make. Its purpose is not to add database capabilities, but to make everyday
database work pleasant without exposing every option SQLAlchemy supports.

- **Plain data:** fetch a dictionary, a list of dictionaries, or `None`. No row
  proxies or result wrappers to work with.
- **Straightforward methods:** `fetch_one()`, `fetch_all()`, `execute()`, and
  `execute_many()` say what they do.
- **Transactional sessions:** successful exit commits; an exception rolls back.
  No separate `commit()` call. Use `transaction()` for a nested transaction.
- **Simple streaming:** iterate over dictionaries and control the batch size
  with `prefetch_size` (256 by default).
- **Managed connections:** connect at application startup, open sessions for
  units of work, and disconnect at shutdown. No engines or pools to manipulate.

You still use SQLAlchemy Core to define tables and construct queries. SQLAlchemy
handles pooling, query execution, streaming, and type processing, including
JSON/JSONB and custom `TypeDecorator` types. Databasic handles connection and
transaction lifetimes and converts rows into dictionaries.

Use a database with an async SQLAlchemy dialect and driver. Install your chosen
driver separately; Databasic does not bundle or select one.

## Installation

```sh
uv add databasic

# or

pip install databasic
```

Also install the async driver for your database, such as `psycopg[binary]` for
PostgreSQL, `asyncmy` for MySQL, or `aiosqlite` for SQLite. Use an explicit
SQLAlchemy driver URL such as `postgresql+psycopg://...`, `mysql+asyncmy://...`,
or `sqlite+aiosqlite:///database.db`.

## Quickstart

This example uses PostgreSQL with psycopg. You need Python 3.11 or newer and
Docker/Podman. Run the following commands from the root of a local checkout of
this repository.

### 1. Install Databasic

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install . "psycopg[binary]"
```

### 2. Start PostgreSQL

Start a disposable local database (port 5432 must be available):

```bash
docker run --name databasic-quickstart \
  -e POSTGRES_USER=databasic \
  -e POSTGRES_PASSWORD=databasic \
  -e POSTGRES_DB=databasic \
  -p 127.0.0.1:5432:5432 \
  -d postgres:17

until docker exec databasic-quickstart pg_isready -U databasic -d databasic; do
  sleep 1
done
```

These credentials are for local development only.

### 3. Create a table, insert a row, and read it back

Save this as `quickstart.py`:

```python
import asyncio

import sqlalchemy as sa

from databasic import Databasic


users = sa.Table(
    "quickstart_users",
    sa.MetaData(),
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("name", sa.Text, nullable=False),
)


async def main():
    async with Databasic(
        "postgresql+psycopg://databasic:databasic@localhost:5432/databasic"
    ) as db:
        async with db.session() as session:
            await session.execute(sa.schema.CreateTable(users, if_not_exists=True))
            inserted = await session.fetch_one(
                users.insert().values(name="Alice").returning(users.c.id)
            )
            assert inserted is not None

        # The first session has committed. Read the row in a new transaction.
        async with db.session() as session:
            user = await session.fetch_one(
                users.select().where(users.c.id == inserted["id"])
            )
            print(user)


if __name__ == "__main__":
    asyncio.run(main())
```

Run it:

```bash
python quickstart.py
```

On a fresh database, the output is:

```python
{'id': 1, 'name': 'Alice'}
```

Each run inserts another row, so its ID will increase. The table is created by
`CreateTable`, not by defining the SQLAlchemy `Table` object. Sessions commit on
successful exit and roll back on exceptions; the outer `async with` closes the
connection pool when the program finishes.

### 4. Clean up

When you are done, remove the container and its database storage:

```bash
docker rm -fv databasic-quickstart
```

## Usage

Keep one Databasic instance and its connection pool open for the lifetime of
your application. Open separate sessions as needed for individual units of work;
each session borrows a connection from the pool, runs a transaction, and returns
the connection when it exits. Close the pool when the application shuts down.

```python
import sqlalchemy as sa

from databasic import Databasic

users = sa.Table(
    "users",
    sa.MetaData(),
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("name", sa.Text, nullable=False),
)

db = Databasic("postgresql+psycopg://user:password@localhost/database")

async with db:
    async with db.session() as session:
        rows = await session.fetch_all(
            users.select().where(users.c.name == "Alice")
        )
```

`Databasic` can also be connected and disconnected explicitly. Both forms have
the same semantics; explicit lifecycle management is useful when the lifetime is
controlled by an application or framework.

```python
db = Databasic("postgresql+psycopg://user:password@localhost/database")

await db.connect()

try:
    async with db.session() as session:
        rows = await session.fetch_all(users.select())
finally:
    await db.disconnect()
```

A session is a transaction. It commits when the context exits successfully and
rolls back when it exits with an exception.

A previously closed database cannot be reused. This will throw an exception.

```python
db = Databasic("postgresql+psycopg://user:password@localhost/database")

async with db:
    pass

# Will throw an exception.
async with db:
    pass
```

## API

### `Databasic`

```python
db = Databasic(
    url,
    force_rollback=False,
    pool_min_size=4,
    pool_max_size=4,
)
```

`url` must be a SQLAlchemy URL string or `sqlalchemy.URL` object naming an
async driver, not a libpq `host=... dbname=...` connection string. The URL is
passed unchanged to SQLAlchemy; install the driver it specifies separately.

Databasic uses SQLAlchemy's async queue pool. Connections are created lazily.
`pool_min_size` is the retained
pool capacity (at least 1), not a number of connections opened eagerly.
`pool_max_size` is the total connection limit, including overflow connections,
and must be at least `pool_min_size`.

#### `connect()`

Validate connectivity and enable sessions. Additional connections open on demand.

```python
await db.connect()
```

#### `disconnect()`

Close the connection pool.

```python
await db.disconnect()
```

#### `session()`

Create a transactional session.

```python
async with db.session() as session:
    ...
```

Successful exit commits the transaction. An exception rolls it back.

### `Session`

#### `execute()`

Execute a statement without returning rows. Returns an `int` containing the
number of rows affected, or `-1` if the row count cannot be determined (for
example, for DDL statements).

```python
rows_affected = await session.execute(
    users.insert().values(name="Alice")
)
assert rows_affected == 1
```

#### `execute_many()`

Execute the same statement multiple times with different parameters. Returns an
`int` containing the total number of rows affected across all executions, or
`-1` if the row count cannot be determined.

```python
query = users.insert().values(
    name=sa.bindparam("name"),
)

rows_affected = await session.execute_many(
    query,
    [
        {"name": "Alice"},
        {"name": "Bob"},
    ],
)
assert rows_affected == 2
```

The statement must define its values using explicit bind parameters. Values are
supplied exclusively through the parameter mappings. The iterable is materialized
before execution; an empty iterable returns `0`. SQLAlchemy does not support
expanding parameters (such as variable-length `IN` lists) or literal-execute
parameters when executing multiple parameter sets. Execution errors are exposed
as SQLAlchemy exceptions.

#### `fetch_one()`

Execute a statement and return one row, or `None` if there is no row.

```python
user = await session.fetch_one(
    users.select().where(users.c.id == 1)
)
```

A row is simply a `dict[str, Any]`:

```python
{"id": 1, "name": "Alice"}
```

There is no result or row wrapper.

#### `fetch_all()`

Execute a statement and return all rows as a list of dictionaries.

```python
users = await session.fetch_all(
    users.select()
)
```

The result has the shape:

```python
[
    {"id": 1, "name": "Alice"},
    {"id": 2, "name": "Bob"},
]
```

#### `stream()`

Stream dictionaries using a server-side cursor without buffering all rows:

```python
async for row in session.stream(users.select(), prefetch_size=256):
    print(row)
```

`prefetch_size` must be at least 1. Streaming requires support from the selected
dialect and driver. If stopping early, close the async generator with
`contextlib.aclosing()` so its cursor is released immediately.

#### `transaction()`

Create a nested transaction within the current session.

```python
async with db.session() as session:
    await session.execute(
        users.insert().values(name="Alice")
    )

    async with session.transaction():
        await session.execute(
            users.insert().values(name="Bob")
        )
```

Nested transactions require database savepoint support. An exception rolls back the nested
transaction. Catch it within the outer session to preserve earlier work;
otherwise, it also causes the session to roll back.

## Testing

`force_rollback=True` runs all sessions within an outer transaction that is
rolled back when Databasic is disconnected.

```python
async with Databasic(
    "postgresql+psycopg://user:password@localhost/test_database",
    force_rollback=True,
) as db:
    ...
```

This allows integration tests to use normal sessions and transactions without
leaving persistent database state, subject to the database's transaction semantics
(for example, some databases auto-commit DDL). This mode requires savepoint
support. Sessions share one connection and must not run concurrently.

The repository's integration tests use PostgreSQL and psycopg. Install the dev
dependency group with `uv sync --group dev` to run them.
