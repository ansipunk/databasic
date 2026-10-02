# Databasic

A small async database interface built on SQLAlchemy Core and psycopg.

SQLAlchemy Core handles query construction and compilation. Databasic handles
connection and transaction lifetimes and executes the resulting queries directly
through psycopg.

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

Execute a statement without returning rows.

```python
await session.execute(
    users.insert().values(name="Alice")
)
```

#### `execute_many()`

Execute the same statement multiple times with different parameters.

```python
query = users.insert().values(
    name=sa.bindparam("name"),
)

await session.execute_many(
    query,
    [
        {"name": "Alice"},
        {"name": "Bob"},
    ],
)
```

The statement must define its values using explicit bind parameters. Values are
supplied exclusively through the parameter mappings.

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
transaction without rolling back earlier work in the session.

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
