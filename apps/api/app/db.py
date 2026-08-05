from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    f"sqlite:///{settings.db_path}",
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from . import models  # noqa: F401 - rejestracja tabel
    from .services.seed import ensure_seeded

    Base.metadata.create_all(engine)
    _migrate(engine)
    with SessionLocal() as db:
        ensure_seeded(db)


def _migrate(engine) -> None:
    """Dodawanie kolumn do istniejącej bazy SQLite (create_all ich nie dodaje)."""
    from sqlalchemy import text

    added_columns = {
        "sessions": [
            ("structure_filter", "TEXT"),
            ("learning_session_id", "INTEGER"),
        ],
    }
    with engine.begin() as conn:
        for table, cols in added_columns.items():
            existing = {
                row[1]
                for row in conn.execute(text(f"PRAGMA table_info({table})"))
            }
            for name, sql_type in cols:
                if name not in existing:
                    conn.execute(
                        text(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}")
                    )


def db_session() -> Session:
    return SessionLocal()
