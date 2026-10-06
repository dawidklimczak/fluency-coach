"""Lekkie, idempotentne migracje SQLite (repo nie używa Alembic).

Wołane z db.py:init_db() PRZED Base.metadata.create_all() - create_all tworzy
tylko tabele, których jeszcze nie ma, nigdy nie zmienia kształtu istniejących,
więc zmiany schematu na istniejących tabelach (nowe kolumny, zmiana
ograniczenia unikalności) muszą być obsłużone tutaj ręcznie i bezpiecznie na
istniejącym pliku data/app.db użytkownika.
"""

import logging

from sqlalchemy import Connection

logger = logging.getLogger(__name__)


def _table_exists(conn: Connection, table: str) -> bool:
    row = conn.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).first()
    return row is not None


def _columns(conn: Connection, table: str) -> set[str]:
    return {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}


def _add_columns_if_missing(conn: Connection, table: str, columns: dict[str, str]) -> None:
    if not _table_exists(conn, table):
        return
    existing = _columns(conn, table)
    for name, ddl_type in columns.items():
        if name not in existing:
            conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl_type}")
            logger.info("Migracja: dodano kolumnę %s.%s", table, name)


def _migrate_transfer_probes(conn: Connection) -> None:
    """Rozdział Near/Far (spec zmian §6): unikalność session_id -> (session_id,
    probe_type). SQLite nie pozwala zmienić ograniczenia UNIQUE przez ALTER,
    więc tabelę trzeba przebudować. Wiersze sprzed zmiany dostają
    probe_type='legacy' - nigdy nie tracimy dotychczasowych prób (spec §17)."""
    if not _table_exists(conn, "transfer_probes"):
        return  # create_all zbuduje ją od razu w nowym kształcie
    if "probe_type" in _columns(conn, "transfer_probes"):
        return  # już zmigrowana

    conn.exec_driver_sql("ALTER TABLE transfer_probes RENAME TO transfer_probes_old")
    conn.exec_driver_sql(
        """
        CREATE TABLE transfer_probes (
            id INTEGER PRIMARY KEY,
            session_id INTEGER NOT NULL,
            attempt_id INTEGER,
            probe_type TEXT NOT NULL DEFAULT 'legacy',
            prompt TEXT,
            order_in_session INTEGER,
            outcome TEXT,
            outcome_classified_at TEXT,
            created_at TEXT
        )
        """
    )
    conn.exec_driver_sql(
        """
        INSERT INTO transfer_probes
            (id, session_id, attempt_id, probe_type, prompt, order_in_session,
             outcome, outcome_classified_at, created_at)
        SELECT id, session_id, attempt_id, 'legacy', NULL, NULL,
               outcome, outcome_classified_at, created_at
        FROM transfer_probes_old
        """
    )
    conn.exec_driver_sql("DROP TABLE transfer_probes_old")
    conn.exec_driver_sql(
        "CREATE UNIQUE INDEX ux_transfer_probes_session_type "
        "ON transfer_probes(session_id, probe_type)"
    )
    logger.info("Migracja: transfer_probes przebudowana pod Near/Far, istniejące wiersze oznaczone jako legacy")


def run_migrations(engine) -> None:
    with engine.begin() as conn:
        _migrate_transfer_probes(conn)
        _add_columns_if_missing(
            conn,
            "speaking_sessions",
            {"far_transfer_prompt": "TEXT", "transfer_order": "TEXT"},
        )
        # Bottleneck Diagnostic (Etap 2) i Recovery Drill (Etap 3) - attempts
        # jest istniejącą tabelą, nowe FK-kolumny muszą przejść przez ten sam
        # mechanizm; diagnostic_sessions/diagnostic_trials/recovery_attempts
        # są całkiem nowymi tabelami, create_all je zbuduje bez migracji
        _add_columns_if_missing(
            conn,
            "attempts",
            {"diagnostic_trial_id": "INTEGER", "recovery_attempt_id": "INTEGER"},
        )
