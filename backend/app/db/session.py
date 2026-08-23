"""Veritabanı motoru, oturum fabrikası ve FastAPI bağımlılığı."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


def _create_engine() -> Engine:
    """Ayarlara göre SQLAlchemy motorunu kurar.

    SQLite'a özgü ayarlar yalnızca SQLite kullanılırken uygulanır; böylece
    `DATABASE_URL` PostgreSQL'e çevrildiğinde kod değişikliği gerekmez.
    """
    settings = get_settings()
    url = settings.sqlalchemy_url
    connect_args: dict[str, Any] = {}

    if url.startswith("sqlite"):
        # FastAPI bağımlılıkları oturumu farklı iş parçacıklarında kullanabilir.
        connect_args["check_same_thread"] = False

    return create_engine(
        url,
        connect_args=connect_args,
        echo=False,
        future=True,
        pool_pre_ping=True,
    )


engine: Engine = _create_engine()

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


@event.listens_for(Engine, "connect")
def _set_sqlite_pragmas(dbapi_connection: Any, connection_record: Any) -> None:
    """SQLite bağlantılarında yabancı anahtar denetimini açar.

    SQLite'ta `PRAGMA foreign_keys` varsayılan olarak KAPALIDIR; açılmazsa
    yabancı anahtar kısıtları sessizce uygulanmaz. PostgreSQL'de bu adım
    gereksiz olduğu için sürücü tipine bakılarak atlanır.
    """
    module_name = type(dbapi_connection).__module__
    if "sqlite" not in module_name:
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        # Eşzamanlı okuma/yazma sırasında kilit hatalarını azaltır.
        cursor.execute("PRAGMA journal_mode=WAL")
        # API + urun-kazi aynı anda açıkken anında "database is locked"
        # vermemek için yazmayı kısa süre beklet (ms).
        cursor.execute("PRAGMA busy_timeout=30000")
    finally:
        cursor.close()


def get_db() -> Iterator[Session]:
    """FastAPI bağımlılığı: istek başına bir veritabanı oturumu üretir."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
