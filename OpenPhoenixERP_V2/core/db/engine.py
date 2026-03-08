"""
core/db/engine.py – Datenbankmotor für OpenPhoenix ERP
=======================================================
Verwaltet die SQLAlchemy-Engine und Session-Factory.
Unterstützt SQLite (Einzelplatz) und PostgreSQL (Netzwerk)
über dieselbe Schnittstelle – der restliche Code merkt nichts davon.
"""

import logging
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker, DeclarativeBase

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Declarative Base – alle Modelle erben davon
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    """Basis-Klasse für alle SQLAlchemy-Modelle."""
    pass


# ---------------------------------------------------------------------------
# Engine-Fabrik
# ---------------------------------------------------------------------------

def create_db_engine(database_url: str, echo: bool = False):
    """
    Erstellt eine SQLAlchemy-Engine mit passenden Einstellungen
    für SQLite oder PostgreSQL.

    Args:
        database_url:  SQLAlchemy-URL (sqlite:/// oder postgresql+psycopg2://)
        echo:          SQL-Statements ins Log schreiben (nur für Debugging)

    Returns:
        SQLAlchemy Engine
    """
    is_sqlite = database_url.startswith("sqlite")

    if is_sqlite:
        engine = create_engine(
            database_url,
            echo=echo,
            connect_args={
                "check_same_thread": False,  # Für mehrere Threads im UI
                "timeout": 30,              # 30s warten bei gesperrter DB
            },
            pool_pre_ping=True,
        )
        # SQLite-spezifische Optimierungen
        @event.listens_for(engine, "connect")
        def set_sqlite_pragmas(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            # WAL-Modus: mehrere gleichzeitige Lesezugriffe, ein Schreibzugriff
            cursor.execute("PRAGMA journal_mode=WAL")
            # Fremdschlüssel-Constraints aktivieren (SQLite ignoriert sie sonst!)
            cursor.execute("PRAGMA foreign_keys=ON")
            # Bessere Performance
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA cache_size=-64000")  # 64 MB Cache
            cursor.execute("PRAGMA temp_store=MEMORY")
            cursor.close()

        logger.info(f"SQLite-Engine erstellt (WAL-Modus): {database_url}")

    else:
        # PostgreSQL
        engine = create_engine(
            database_url,
            echo=echo,
            pool_size=5,           # Verbindungs-Pool für mehrere User
            max_overflow=10,
            pool_pre_ping=True,    # Prüft Verbindung vor Nutzung
            pool_recycle=3600,     # Verbindungen nach 1h erneuern
        )
        logger.info(f"PostgreSQL-Engine erstellt: {database_url}")

    return engine


# ---------------------------------------------------------------------------
# Session-Manager (Singleton)
# ---------------------------------------------------------------------------

class DatabaseManager:
    """
    Zentrale Datenbankverwaltung für OpenPhoenix ERP.

    Verwendung:
        from core.db.engine import db

        # Als Context-Manager (empfohlen):
        with db.session() as session:
            kunde = session.get(Kunde, 1)

        # Initialisierung beim App-Start:
        db.initialize(config.get_database_url())
        db.create_all_tables()
    """

    def __init__(self) -> None:
        self._engine = None
        self._session_factory = None

    def initialize(self, database_url: str, echo: bool = False) -> None:
        """Initialisiert die Datenbankverbindung. Muss beim App-Start aufgerufen werden."""
        self._engine = create_db_engine(database_url, echo=echo)
        self._session_factory = sessionmaker(
            bind=self._engine,
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,  # Objekte nach commit noch lesbar
        )
        logger.info("Datenbank-Manager initialisiert.")

    def create_all_tables(self) -> None:
        """Erstellt alle Tabellen (idempotent – bestehende werden nicht überschrieben)."""
        if self._engine is None:
            raise RuntimeError("DatabaseManager nicht initialisiert. initialize() aufrufen.")
        Base.metadata.create_all(bind=self._engine)
        self._run_migrations()
        logger.info("Alle Datenbanktabellen sichergestellt.")

    def _run_migrations(self) -> None:
        """Führt inkrementelle Spalten-Migrationen durch (idempotent)."""
        migrations = [
            # v2.1: Stornoverweis auf Originalrechnung
            "ALTER TABLE rechnungen ADD COLUMN storno_zu_nr VARCHAR(50)",
            # v2.3: Anrede am Kundenstamm
            "ALTER TABLE kunden ADD COLUMN anrede VARCHAR(20)",
            # v2.2: CRM-Notizen pro Kunde
            """CREATE TABLE IF NOT EXISTS kunden_notizen (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kunde_id INTEGER NOT NULL REFERENCES kunden(id) ON DELETE CASCADE,
                text TEXT NOT NULL,
                autor VARCHAR(100),
                erstellt_am DATETIME DEFAULT CURRENT_TIMESTAMP
            )""",
        ]
        with self._engine.connect() as conn:
            for sql in migrations:
                try:
                    conn.execute(text(sql))
                    conn.commit()
                except Exception:
                    pass  # Spalte existiert bereits – ignorieren

    def test_connection(self) -> bool:
        """Prüft ob die Datenbankverbindung funktioniert."""
        if self._engine is None:
            return False
        try:
            with self._engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.error(f"Datenbankverbindung fehlgeschlagen: {e}")
            return False

    @contextmanager
    def session(self) -> Generator[Session, None, None]:
        """
        Context-Manager für Datenbank-Sessions.

        Automatisches Commit bei Erfolg, Rollback bei Fehler.

        Beispiel:
            with db.session() as s:
                s.add(neuer_kunde)
            # commit passiert automatisch beim Verlassen des Blocks
        """
        if self._session_factory is None:
            raise RuntimeError("DatabaseManager nicht initialisiert. initialize() aufrufen.")

        session: Session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_session(self) -> Session:
        """
        Gibt eine Session zurück (manuelles Management).
        Nur verwenden wenn der Context-Manager nicht passt.
        session.close() muss selbst aufgerufen werden.
        """
        if self._session_factory is None:
            raise RuntimeError("DatabaseManager nicht initialisiert. initialize() aufrufen.")
        return self._session_factory()

    @property
    def engine(self):
        return self._engine

    def dispose(self) -> None:
        """Schließt alle Datenbankverbindungen sauber (beim App-Ende)."""
        if self._engine:
            self._engine.dispose()
            logger.info("Datenbankverbindungen geschlossen.")


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
db = DatabaseManager()
