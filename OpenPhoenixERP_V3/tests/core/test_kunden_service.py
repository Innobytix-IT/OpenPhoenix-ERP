"""
tests/core/test_kunden_service.py – Tests für den KundenService
===============================================================
Vollständige Abdeckung der Business-Logik ohne UI.
"""

import pytest
import tempfile
import shutil
from pathlib import Path
from decimal import Decimal

from core.db.engine import DatabaseManager, Base
from core.models import Kunde, Rechnung, AuditLog
from core.services.kunden_service import KundenService, KundeDTO
from core.audit.service import AuditAction


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    manager = DatabaseManager()
    manager.initialize("sqlite:///:memory:", echo=False)
    import core.models
    manager.create_all_tables()
    yield manager
    manager.dispose()


@pytest.fixture
def service():
    return KundenService()


@pytest.fixture
def basis_dto():
    return KundeDTO(
        id=None, zifferncode=None,
        anrede="Herr",
        name="Müller", vorname="Hans",
        titel_firma="", geburtsdatum="",
        strasse="Hauptstraße", hausnummer="5",
        plz="12345", ort="Berlin",
        telefon="030-123456", email="hans@mueller.de",
    )


@pytest.fixture
def kunde_in_db(db, service, basis_dto):
    """Legt einen Kunden in der DB an und gibt das DTO zurück."""
    with db.session() as session:
        result = service.erstellen(session, basis_dto)
    assert result.success
    return result.data


# ---------------------------------------------------------------------------
# Erstellen
# ---------------------------------------------------------------------------

class TestErstellen:
    def test_erfolg(self, db, service, basis_dto):
        with db.session() as session:
            result = service.erstellen(session, basis_dto)
        assert result.success
        assert result.data.id is not None
        assert result.data.zifferncode == 1001
        assert result.data.name == "Müller"

    def test_kundennummer_fortlaufend(self, db, service, basis_dto):
        with db.session() as session:
            r1 = service.erstellen(session, basis_dto)
        with db.session() as session:
            basis_dto.vorname = "Klaus"
            r2 = service.erstellen(session, basis_dto)
        assert r1.data.zifferncode == 1001
        assert r2.data.zifferncode == 1002

    def test_pflichtfeld_name_fehlt(self, db, service, basis_dto):
        basis_dto.name = ""
        with db.session() as session:
            result = service.erstellen(session, basis_dto)
        assert not result.success
        assert "Name" in result.message

    def test_pflichtfeld_vorname_fehlt(self, db, service, basis_dto):
        basis_dto.vorname = "   "
        with db.session() as session:
            result = service.erstellen(session, basis_dto)
        assert not result.success
        assert "Vorname" in result.message

    def test_ungültiges_geburtsdatum(self, db, service, basis_dto):
        basis_dto.geburtsdatum = "1990-01-15"  # falsches Format
        with db.session() as session:
            result = service.erstellen(session, basis_dto)
        assert not result.success
        assert "Geburtsdatum" in result.message

    def test_richtiges_geburtsdatum(self, db, service, basis_dto):
        basis_dto.geburtsdatum = "15.01.1990"  # richtiges Format
        with db.session() as session:
            result = service.erstellen(session, basis_dto)
        assert result.success

    def test_ungültige_email(self, db, service, basis_dto):
        basis_dto.email = "keine-email"
        with db.session() as session:
            result = service.erstellen(session, basis_dto)
        assert not result.success

    def test_audit_log_eintrag(self, db, service, basis_dto):
        with db.session() as session:
            service.erstellen(session, basis_dto)
        with db.session() as session:
            entry = session.query(AuditLog).filter_by(
                action=AuditAction.KUNDE_ERSTELLT
            ).first()
        assert entry is not None


# ---------------------------------------------------------------------------
# Lesen
# ---------------------------------------------------------------------------

class TestLesen:
    def test_alle_kunden(self, db, service, basis_dto):
        with db.session() as session:
            service.erstellen(session, basis_dto)
        with db.session() as session:
            kunden = service.alle(session, nur_aktive=True)
        assert len(kunden) == 1

    def test_suche_nach_name(self, db, service, basis_dto):
        with db.session() as session:
            service.erstellen(session, basis_dto)
        with db.session() as session:
            result = service.alle(session, suchtext="Müller")
        assert len(result) == 1
        result_leer = service.alle(session, suchtext="Nichtexistent")
        assert len(result_leer) == 0

    def test_nach_id(self, db, service, kunde_in_db):
        with db.session() as session:
            dto = service.nach_id(session, kunde_in_db.id)
        assert dto is not None
        assert dto.name == "Müller"

    def test_nach_id_nichtexistent(self, db, service):
        with db.session() as session:
            dto = service.nach_id(session, 9999)
        assert dto is None

    def test_naechste_kundennummer_leer(self, db, service):
        with db.session() as session:
            nr = service.naechste_kundennummer(session)
        assert nr == 1001

    def test_naechste_kundennummer_nach_anlage(self, db, service, kunde_in_db):
        with db.session() as session:
            nr = service.naechste_kundennummer(session)
        assert nr == 1002


# ---------------------------------------------------------------------------
# Aktualisieren
# ---------------------------------------------------------------------------

class TestAktualisieren:
    def test_erfolg(self, db, service, kunde_in_db):
        updated = KundeDTO(
            id=kunde_in_db.id, zifferncode=kunde_in_db.zifferncode,
            anrede="Frau",
            name="Schmidt", vorname="Anna",
            titel_firma="Dr.", geburtsdatum="",
            strasse="Neue Str.", hausnummer="10",
            plz="54321", ort="Hamburg",
            telefon="040-999", email="anna@schmidt.de",
        )
        with db.session() as session:
            result = service.aktualisieren(session, kunde_in_db.id, updated)
        assert result.success

        with db.session() as session:
            dto = service.nach_id(session, kunde_in_db.id)
        assert dto.name == "Schmidt"
        assert dto.vorname == "Anna"
        assert dto.titel_firma == "Dr."

    def test_keine_aenderung(self, db, service, kunde_in_db):
        with db.session() as session:
            result = service.aktualisieren(session, kunde_in_db.id, kunde_in_db)
        assert not result.success
        assert "keine" in result.message.lower()

    def test_nichtexistenter_kunde(self, db, service, basis_dto):
        with db.session() as session:
            result = service.aktualisieren(session, 9999, basis_dto)
        assert not result.success

    def test_audit_log_bei_änderung(self, db, service, kunde_in_db):
        updated = KundeDTO(
            id=kunde_in_db.id, zifferncode=kunde_in_db.zifferncode,
            anrede="Herr",
            name="NeuerName", vorname=kunde_in_db.vorname,
            titel_firma="", geburtsdatum="",
            strasse="", hausnummer="", plz="", ort="",
            telefon="", email="",
        )
        with db.session() as session:
            service.aktualisieren(session, kunde_in_db.id, updated)
        with db.session() as session:
            entry = session.query(AuditLog).filter_by(
                action=AuditAction.KUNDE_GEAENDERT
            ).first()
        assert entry is not None
        assert "NeuerName" in entry.details


# ---------------------------------------------------------------------------
# Deaktivieren / Reaktivieren
# ---------------------------------------------------------------------------

class TestStatusAenderung:
    def test_deaktivieren(self, db, service, kunde_in_db):
        with db.session() as session:
            result = service.deaktivieren(session, kunde_in_db.id)
        assert result.success
        with db.session() as session:
            dto = service.nach_id(session, kunde_in_db.id)
        assert not dto.is_active

    def test_inaktiver_kunde_sichtbar_mit_flag(self, db, service, kunde_in_db):
        with db.session() as session:
            service.deaktivieren(session, kunde_in_db.id)
        with db.session() as session:
            alle = service.alle(session, nur_aktive=False)
        assert len(alle) == 1
        assert not alle[0].is_active

    def test_reaktivieren(self, db, service, kunde_in_db):
        with db.session() as session:
            service.deaktivieren(session, kunde_in_db.id)
        with db.session() as session:
            result = service.reaktivieren(session, kunde_in_db.id)
        assert result.success
        with db.session() as session:
            dto = service.nach_id(session, kunde_in_db.id)
        assert dto.is_active

    def test_bereits_inaktiv_deaktivieren(self, db, service, kunde_in_db):
        with db.session() as session:
            service.deaktivieren(session, kunde_in_db.id)
        with db.session() as session:
            result = service.deaktivieren(session, kunde_in_db.id)
        assert not result.success


# ---------------------------------------------------------------------------
# Dokumente
# ---------------------------------------------------------------------------

class TestDokumente:
    def test_dokument_zuordnen(self, db, service, kunde_in_db, tmp_path):
        # Testdatei erstellen
        test_file = tmp_path / "rechnung.pdf"
        test_file.write_bytes(b"Fake PDF content")

        docs_basis = str(tmp_path / "dokumente")

        with db.session() as session:
            result = service.dokument_zuordnen(
                session, kunde_in_db.id,
                str(test_file), docs_basis
            )
        assert result.success

        # Datei wurde kopiert?
        with db.session() as session:
            docs = service.dokumente(session, kunde_in_db.id)
        assert len(docs) == 1
        assert docs[0].exists

    def test_dokument_loeschen(self, db, service, kunde_in_db, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("test")
        docs_basis = str(tmp_path / "dokumente")

        with db.session() as session:
            service.dokument_zuordnen(
                session, kunde_in_db.id, str(test_file), docs_basis
            )
        with db.session() as session:
            docs = service.dokumente(session, kunde_in_db.id)
        doc_id = docs[0].id

        with db.session() as session:
            result = service.dokument_loeschen(session, doc_id)
        assert result.success

        with db.session() as session:
            docs_after = service.dokumente(session, kunde_in_db.id)
        assert len(docs_after) == 0

    def test_duplikate_werden_umbenannt(self, db, service, kunde_in_db, tmp_path):
        docs_basis = str(tmp_path / "dokumente")
        for _ in range(3):
            f = tmp_path / "dokument.pdf"
            f.write_bytes(b"content")
            with db.session() as session:
                service.dokument_zuordnen(
                    session, kunde_in_db.id, str(f), docs_basis
                )

        with db.session() as session:
            docs = service.dokumente(session, kunde_in_db.id)
        namen = {d.dateiname for d in docs}
        assert len(namen) == 3  # alle unterschiedlich
