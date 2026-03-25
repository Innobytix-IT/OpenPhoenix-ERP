"""
tests/core/test_database.py – Tests für die Datenbankschicht
============================================================
Testet Engine, Session-Management und Modelle.
"""

import pytest
from decimal import Decimal
from datetime import datetime

from sqlalchemy import text

from core.db.engine import DatabaseManager, Base
from core.models import Kunde, Artikel, Rechnung, Rechnungsposten, AuditLog
from core.audit.service import AuditService, AuditAction


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    """Erstellt eine frische In-Memory-SQLite-Datenbank für jeden Test."""
    manager = DatabaseManager()
    manager.initialize("sqlite:///:memory:", echo=False)
    import core.models  # noqa: F401 – Stellt sicher dass Base alle Modelle kennt
    manager.create_all_tables()
    yield manager
    manager.dispose()


@pytest.fixture
def session(db):
    """Gibt eine Test-Session zurück (wird nach dem Test automatisch gerollt)."""
    with db.session() as s:
        yield s


# ---------------------------------------------------------------------------
# Engine-Tests
# ---------------------------------------------------------------------------

class TestEngine:
    def test_connection_ok(self, db):
        assert db.test_connection() is True

    def test_wal_mode_enabled(self, db):
        with db.session() as session:
            result = session.execute(text("PRAGMA journal_mode")).fetchone()
            # :memory:-Datenbanken unterstützen kein WAL, dort ist 'memory' korrekt
            assert result[0] in ("wal", "memory")

    def test_foreign_keys_enabled(self, db):
        with db.session() as session:
            result = session.execute(text("PRAGMA foreign_keys")).fetchone()
            assert result[0] == 1


# ---------------------------------------------------------------------------
# Kunden-Tests
# ---------------------------------------------------------------------------

class TestKunde:
    def test_kunde_erstellen(self, db):
        with db.session() as session:
            kunde = Kunde(name="Müller", vorname="Hans", zifferncode=1001)
            session.add(kunde)

        with db.session() as session:
            result = session.query(Kunde).filter_by(zifferncode=1001).first()
            assert result is not None
            assert result.name == "Müller"
            assert result.vorname == "Hans"
            assert result.is_active is True

    def test_kunde_display_name(self, db):
        with db.session() as session:
            k = Kunde(name="Schmidt", vorname="Anna", titel_firma="Dr.")
            session.add(k)

        with db.session() as session:
            k = session.query(Kunde).filter_by(name="Schmidt").first()
            assert k.display_name == "Anna Schmidt (Dr.)"

    def test_kunde_deaktivieren(self, db):
        with db.session() as session:
            k = Kunde(name="Test", vorname="User", zifferncode=1002)
            session.add(k)

        with db.session() as session:
            k = session.query(Kunde).filter_by(zifferncode=1002).first()
            k.is_active = False

        with db.session() as session:
            k = session.query(Kunde).filter_by(zifferncode=1002).first()
            assert k.is_active is False

    def test_kundennummer_eindeutig(self, db):
        from sqlalchemy.exc import IntegrityError
        with pytest.raises(IntegrityError):
            with db.session() as session:
                k1 = Kunde(name="A", vorname="A", zifferncode=9999)
                k2 = Kunde(name="B", vorname="B", zifferncode=9999)
                session.add_all([k1, k2])


# ---------------------------------------------------------------------------
# Artikel-Tests
# ---------------------------------------------------------------------------

class TestArtikel:
    def test_artikel_erstellen(self, db):
        with db.session() as session:
            a = Artikel(
                artikelnummer="ART-001",
                beschreibung="Testprodukt",
                einheit="Stück",
                einzelpreis_netto=Decimal("49.99"),
                verfuegbar=Decimal("100"),
            )
            session.add(a)

        with db.session() as session:
            result = session.query(Artikel).filter_by(artikelnummer="ART-001").first()
            assert result is not None
            assert result.einzelpreis_netto == Decimal("49.99")

    def test_artikelnummer_eindeutig(self, db):
        from sqlalchemy.exc import IntegrityError
        with pytest.raises(IntegrityError):
            with db.session() as session:
                a1 = Artikel(artikelnummer="DUP", beschreibung="A")
                a2 = Artikel(artikelnummer="DUP", beschreibung="B")
                session.add_all([a1, a2])


# ---------------------------------------------------------------------------
# Audit-Log-Tests
# ---------------------------------------------------------------------------

class TestAuditLog:
    def test_audit_eintrag_erstellen(self, db):
        audit_svc = AuditService()
        with db.session() as session:
            audit_svc.log(
                session,
                AuditAction.KUNDE_ERSTELLT,
                record_id=1,
                table_name="kunden",
                details="Test-Eintrag"
            )

        with db.session() as session:
            entries = session.query(AuditLog).all()
            assert len(entries) == 1
            assert entries[0].action == AuditAction.KUNDE_ERSTELLT
            assert entries[0].details == "Test-Eintrag"

    def test_audit_aenderungen_vergleich(self, db):
        audit_svc = AuditService()
        old = {"name": "Alt", "email": "alt@test.de"}
        new = {"name": "Neu", "email": "alt@test.de"}

        with db.session() as session:
            audit_svc.log_change(
                session,
                AuditAction.KUNDE_GEAENDERT,
                record_id=1,
                table_name="kunden",
                old_data=old,
                new_data=new,
            )

        with db.session() as session:
            entry = session.query(AuditLog).first()
            assert entry is not None
            assert "Alt" in entry.details
            assert "Neu" in entry.details
            # E-Mail hat sich nicht geändert – sollte nicht im Detail stehen
            assert "email" not in entry.details


# ---------------------------------------------------------------------------
# Konfigurations-Tests
# ---------------------------------------------------------------------------

class TestConfig:
    def test_sqlite_url(self, tmp_path):
        from core.config import Config
        cfg = Config(config_path=tmp_path / "config.toml")
        cfg.set("database", "mode", "local")
        cfg.set("database", "path", "test.db")
        url = cfg.get_database_url()
        assert url.startswith("sqlite:///")
        assert "test.db" in url

    def test_postgresql_url(self, tmp_path):
        from core.config import Config
        cfg = Config(config_path=tmp_path / "config.toml")
        cfg.set("database", "mode", "server")
        cfg.set("database", "host", "192.168.1.10")
        cfg.set("database", "port", 5432)
        cfg.set("database", "name", "openphoenix")
        cfg.set("database", "user", "erp_user")
        url = cfg.get_database_url()
        assert "postgresql" in url
        assert "192.168.1.10" in url
        assert "openphoenix" in url

    def test_config_speichern_laden(self, tmp_path):
        from core.config import Config
        cfg = Config(config_path=tmp_path / "config.toml")
        cfg.set("company", "name", "Test GmbH")
        cfg.save()

        cfg2 = Config(config_path=tmp_path / "config.toml")
        assert cfg2.get("company", "name") == "Test GmbH"

    def test_defaults_als_fallback(self, tmp_path):
        from core.config import Config, DEFAULTS
        cfg = Config(config_path=tmp_path / "nichtvorhanden.toml")
        assert cfg.get("invoice", "default_vat") == DEFAULTS["invoice"]["default_vat"]
