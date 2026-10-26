from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import inspect, text
from sqlmodel import Session, SQLModel, create_engine

from .config import get_settings

_settings = get_settings()

if _settings.DATABASE_URL.startswith("sqlite"):
    db_path = _settings.DATABASE_URL.split("///", 1)[-1]
    if db_path and db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

connect_args = {"check_same_thread": False} if _settings.DATABASE_URL.startswith("sqlite") else {}
# Синхронные обработчики FastAPI работают в пуле из 40 потоков. Если соединений с базой меньше,
# под нагрузкой потоки ждут соединение, а занявшим его не хватает потока, чтобы вернуть, —
# взаимная блокировка до тайм-аута пула. Поэтому соединений не меньше, чем потоков.
pool_args = {} if ":memory:" in _settings.DATABASE_URL else {"pool_size": 20, "max_overflow": 30, "pool_timeout": 10}
engine = create_engine(_settings.DATABASE_URL, echo=False, connect_args=connect_args, **pool_args)


def _column_ddl(col) -> str:
    ddl = f'"{col.name}" {col.type.compile(engine.dialect)}'
    default = getattr(col.default, "arg", None)
    if default is not None and not callable(default):
        if isinstance(default, bool):
            ddl += f" DEFAULT {1 if default else 0}"
        elif isinstance(default, (int, float)):
            ddl += f" DEFAULT {default}"
        else:
            ddl += f" DEFAULT '{default}'"
    return ddl


def _ensure_columns() -> None:
    if engine.dialect.name != "sqlite":
        return
    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())
    with engine.begin() as conn:
        for table in SQLModel.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            existing_cols = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing_cols:
                    continue
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN {_column_ddl(col)}'))


def init_db() -> None:
    from . import models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    _ensure_columns()


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session


def reset_db() -> None:
    from . import models  # noqa: F401

    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)


__all__ = ["engine", "init_db", "get_session", "reset_db", "Session"]
