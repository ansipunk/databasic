# Databasic

A small async database interface built on SQLAlchemy Core and psycopg.
PostgreSQL is the only supported database.

SQLAlchemy Core handles query construction and compilation. Databasic handles
connection and transaction lifetimes and executes the resulting queries directly
through psycopg.

SQLAlchemy bind processors convert input values for psycopg, including
JSON/JSONB values and custom `TypeDecorator` bind processing. Returned values are
decoded by psycopg; SQLAlchemy result processors are not applied.

Keep one Databasic instance and its connection pool open for the lifetime of
your application. Open separate sessions as needed for individual units of work;
each session borrows a connection from the pool, runs a transaction, and returns
the connection when it exits. Close the pool when the application shuts down.

## Installation

```sh
uv add databasic

# or

pip install databasic
```

## Quickstart

You need Python 3.11 or newer and Docker/Podman. Run the following commands from
the root of a local checkout of this repository.

### 1. Install Databasic

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
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
        "postgresql://databasic:databasic@localhost:5432/databasic"
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

```python
import sqlalchemy as sa

from databasic import Databasic

users = sa.Table(
    "users",
    sa.MetaData(),
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("name", sa.Text, nullable=False),
)

db = Databasic("postgresql://user:password@localhost/database")

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
db = Databasic("postgresql://user:password@localhost/database")

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
db = Databasic("postgresql://user:password@localhost/database")

async with db:
    pass

# Will throw an exception.
async with db:
    pass
```

## API

### `Databasic`

```python
db = Databasic(conninfo, force_rollback=False)
```

#### `connect()`

Open the connection pool.

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
supplied exclusively through the parameter mappings. Expanding parameters
(such as variable-length `IN` lists) and literal-execute parameters are not
supported by `execute_many()`.

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

Nested transactions use database savepoints. An exception rolls back the nested
transaction. Catch it within the outer session to preserve earlier work;
otherwise, it also causes the session to roll back.

## Testing

`force_rollback=True` runs all sessions within an outer transaction that is
rolled back when Databasic is disconnected.

```python
async with Databasic(
    "postgresql://user:password@localhost/test_database",
    force_rollback=True,
) as db:
    ...
```

This allows integration tests to use normal sessions and transactions without
leaving persistent database state.
