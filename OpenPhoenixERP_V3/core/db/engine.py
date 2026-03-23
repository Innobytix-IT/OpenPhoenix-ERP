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
            isolation_level="REPEATABLE READ",  # Schutz gegen Phantom-Reads bei Finanzdaten
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
            # v2.4: Änderungszeitpunkt am Kundenstamm
            # SQLite erlaubt kein DEFAULT CURRENT_TIMESTAMP bei ALTER TABLE ADD COLUMN
            "ALTER TABLE kunden ADD COLUMN geaendert_am DATETIME",
            # v2.5: Eingangsrechnungen / Belege
            """CREATE TABLE IF NOT EXISTS eingangsrechnungen (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                datum VARCHAR(10) NOT NULL,
                lieferant VARCHAR(200) NOT NULL,
                belegnummer VARCHAR(100),
                betrag_netto NUMERIC(14,4) NOT NULL,
                mwst_satz NUMERIC(5,2) DEFAULT 19.00,
                mwst_betrag NUMERIC(14,4),
                betrag_brutto NUMERIC(14,4),
                kategorie VARCHAR(50) NOT NULL,
                bemerkung TEXT,
                zahlungsstatus VARCHAR(20) DEFAULT 'Offen',
                beleg_pfad TEXT,
                beleg_dateiname VARCHAR(255),
                is_active BOOLEAN DEFAULT 1,
                erstellt_am DATETIME DEFAULT CURRENT_TIMESTAMP,
                geaendert_am DATETIME DEFAULT CURRENT_TIMESTAMP
            )""",
            "CREATE INDEX IF NOT EXISTS ix_eingangsrechnungen_datum ON eingangsrechnungen(datum)",
            "CREATE INDEX IF NOT EXISTS ix_eingangsrechnungen_kategorie ON eingangsrechnungen(kategorie)",
            "CREATE INDEX IF NOT EXISTS ix_eingangsrechnungen_zahlungsstatus ON eingangsrechnungen(zahlungsstatus)",
        ]
        with self._engine.connect() as conn:
            for sql in migrations:
                try:
                    conn.execute(text(sql))
                    conn.commit()
                    logger.debug(f"Migration ausgeführt: {sql[:60]}…")
                except Exception as e:
                    conn.rollback()
                    err_msg = str(e).lower()
                    # Erwartete Fehler: Spalte/Tabelle existiert bereits
                    if any(kw in err_msg for kw in (
                        "duplicate", "already exists", "already has column",
                        "table", "already", "exists",
                    )):
                        logger.debug(f"Migration übersprungen (existiert): {sql[:60]}…")
                    else:
                        logger.error(
                            f"KRITISCH: Migration fehlgeschlagen: {sql[:60]}… – {e}"
                        )
                        raise RuntimeError(
                            f"Datenbank-Migration fehlgeschlagen: {e}"
                        ) from e

            # v2.5: FK-Constraint von rechnungsposten.artikelnummer entfernen
            # Artikelnummern auf Rechnungen/Angeboten sind informativ (Freitext).
            # Der FK verhinderte das Anlegen von Posten ohne Lager-Artikel.
            if self._engine.dialect.name == "sqlite":
                self._migrate_remove_fk_artikelnummer_sqlite(conn)
            else:
                self._migrate_remove_fk_artikelnummer_pg(conn)

    @staticmethod
    def _migrate_remove_fk_artikelnummer_pg(conn) -> None:
        """Entfernt den FK-Constraint von artikelnummer (PostgreSQL-Variante)."""
        for table in ("rechnungsposten", "angebotsposten"):
            try:
                # FK-Constraint-Name ermitteln (parametrisiert)
                result = conn.execute(text("""
                    SELECT constraint_name
                    FROM information_schema.table_constraints
                    WHERE table_name = :tbl
                      AND constraint_type = 'FOREIGN KEY'
                      AND constraint_name LIKE :pattern
                """), {"tbl": table, "pattern": "%artikelnummer%"}).fetchall()
                if not result:
                    # Auch generisch nach FK auf artikel-Tabelle suchen
                    result = conn.execute(text("""
                        SELECT tc.constraint_name
                        FROM information_schema.table_constraints tc
                        JOIN information_schema.constraint_column_usage ccu
                            ON tc.constraint_name = ccu.constraint_name
                        WHERE tc.table_name = :tbl
                          AND tc.constraint_type = 'FOREIGN KEY'
                          AND ccu.table_name = 'artikel'
                    """), {"tbl": table}).fetchall()
                if not result:
                    logger.debug(f"Migration übersprungen: {table}.artikelnummer hat keinen FK mehr.")
                    continue
                for row in result:
                    # Constraint-Name aus DB-Abfrage – table ist hardcoded constant
                    constraint_name = row[0]
                    conn.execute(text(
                        f"ALTER TABLE {table} DROP CONSTRAINT {constraint_name}"
                    ))
                conn.commit()
                logger.info(f"Migration: FK auf {table}.artikelnummer entfernt (PostgreSQL).")
            except Exception as e:
                conn.rollback()
                logger.warning(f"Migration FK-Entfernung {table} fehlgeschlagen: {e}")

    @staticmethod
    def _migrate_remove_fk_artikelnummer_sqlite(conn) -> None:
        """Entfernt den FK-Constraint von artikelnummer in rechnungsposten/angebotsposten.

        SQLite unterstützt kein ALTER TABLE DROP CONSTRAINT, daher wird die
        Tabelle neu erstellt (ohne FK) und die Daten werden kopiert.
        Prüft vorher ob der FK noch existiert (idempotent).
        """
        for table in ("rechnungsposten", "angebotsposten"):
            try:
                # Prüfe ob der FK noch existiert
                fk_info = conn.execute(text(f"PRAGMA foreign_key_list({table})")).fetchall()
                has_artikel_fk = any(
                    row[2] == "artikel" for row in fk_info  # row[2] = referenced table
                )
                if not has_artikel_fk:
                    logger.debug(f"Migration übersprungen: {table}.artikelnummer hat keinen FK mehr.")
                    continue

                # FK-Referenz-Spalte: angebot_id oder rechnung_id
                parent_fk = "angebot_id" if table == "angebotsposten" else "rechnung_id"
                parent_table = "angebote" if table == "angebotsposten" else "rechnungen"

                conn.execute(text("PRAGMA foreign_keys=OFF"))
                conn.execute(text(f"""
                    CREATE TABLE {table}_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        {parent_fk} INTEGER NOT NULL
                            REFERENCES {parent_table}(id) ON DELETE CASCADE,
                        position INTEGER NOT NULL,
                        artikelnummer VARCHAR(50),
                        beschreibung VARCHAR(500) NOT NULL,
                        menge NUMERIC(12,4) NOT NULL,
                        einheit VARCHAR(20),
                        einzelpreis_netto NUMERIC(12,4) NOT NULL,
                        gesamtpreis_netto NUMERIC(14,4) NOT NULL
                    )
                """))
                conn.execute(text(f"""
                    INSERT INTO {table}_new
                    SELECT id, {parent_fk}, position, artikelnummer,
                           beschreibung, menge, einheit,
                           einzelpreis_netto, gesamtpreis_netto
                    FROM {table}
                """))
                conn.execute(text(f"DROP TABLE {table}"))
                conn.execute(text(f"ALTER TABLE {table}_new RENAME TO {table}"))
                # Index wiederherstellen
                conn.execute(text(
                    f"CREATE INDEX IF NOT EXISTS ix_{table}_artikelnummer "
                    f"ON {table}(artikelnummer)"
                ))
                conn.execute(text("PRAGMA foreign_keys=ON"))
                conn.commit()
                logger.info(f"Migration: FK auf {table}.artikelnummer entfernt.")
            except Exception as e:
                conn.rollback()
                try:
                    conn.execute(text("PRAGMA foreign_keys=ON"))
                    conn.commit()
                except Exception:
                    pass
                logger.warning(f"Migration FK-Entfernung {table} fehlgeschlagen: {e}")

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
