"""Migracja transfer_probes: session_id unique -> (session_id, probe_type)
unique, wiersze sprzed zmiany oznaczone jako legacy (spec zmian §17)."""

from sqlalchemy import create_engine

from app.migrations import run_migrations


def _make_old_schema_engine():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE transfer_probes (
                id INTEGER PRIMARY KEY,
                session_id INTEGER UNIQUE,
                attempt_id INTEGER,
                outcome TEXT,
                outcome_classified_at TEXT,
                created_at TEXT
            )
            """
        )
        conn.exec_driver_sql(
            "INSERT INTO transfer_probes (id, session_id, attempt_id, outcome, created_at) "
            "VALUES (1, 100, 5, 'answered', '2026-01-01T00:00:00')"
        )
        conn.exec_driver_sql(
            "CREATE TABLE speaking_sessions (id INTEGER PRIMARY KEY, domain_id INTEGER)"
        )
    return engine


def test_old_transfer_probes_migrate_to_legacy():
    engine = _make_old_schema_engine()
    run_migrations(engine)

    with engine.begin() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(transfer_probes)")}
        assert "probe_type" in cols
        assert "prompt" in cols
        assert "order_in_session" in cols

        row = conn.exec_driver_sql(
            "SELECT session_id, probe_type, outcome FROM transfer_probes WHERE id=1"
        ).first()
        assert row == (100, "legacy", "answered")


def test_migration_allows_near_probe_alongside_legacy_row():
    engine = _make_old_schema_engine()
    run_migrations(engine)

    with engine.begin() as conn:
        # session_id=100 już ma wiersz 'legacy' - nowy typ 'near' dla tej samej
        # sesji musi się dać wstawić (unikalność jest teraz złożona)
        conn.exec_driver_sql(
            "INSERT INTO transfer_probes (session_id, probe_type, created_at) "
            "VALUES (100, 'near', '2026-02-01T00:00:00')"
        )
        count = conn.exec_driver_sql(
            "SELECT COUNT(*) FROM transfer_probes WHERE session_id=100"
        ).scalar()
        assert count == 2


def test_migration_is_idempotent():
    engine = _make_old_schema_engine()
    run_migrations(engine)
    run_migrations(engine)  # nie powinno rzucić ani zdublować danych

    with engine.begin() as conn:
        count = conn.exec_driver_sql("SELECT COUNT(*) FROM transfer_probes").scalar()
        assert count == 1


def test_speaking_sessions_gets_new_columns():
    engine = _make_old_schema_engine()
    run_migrations(engine)

    with engine.begin() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(speaking_sessions)")}
        assert "far_transfer_prompt" in cols
        assert "transfer_order" in cols


def test_fresh_database_is_left_for_create_all():
    engine = create_engine("sqlite://")
    run_migrations(engine)  # brak tabel - nic nie robi, nie rzuca

    with engine.begin() as conn:
        row = conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='transfer_probes'"
        ).first()
        assert row is None
