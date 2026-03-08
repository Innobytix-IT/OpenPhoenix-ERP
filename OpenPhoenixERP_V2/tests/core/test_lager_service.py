"""
tests/core/test_lager_service.py – Tests für den LagerService
=============================================================
"""

import pytest
from decimal import Decimal

from core.db.engine import DatabaseManager, Base
from core.services.lager_service import LagerService, ArtikelDTO, Buchungsart
from core.models import Artikel, LagerBewegung


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
    return LagerService()


@pytest.fixture
def basis_dto():
    return ArtikelDTO(
        id=None,
        artikelnummer="TEST-001",
        beschreibung="Testartikel",
        einheit="Stück",
        einzelpreis_netto=Decimal("19.99"),
        verfuegbar=Decimal("100"),
    )


@pytest.fixture
def artikel_in_db(db, service, basis_dto):
    with db.session() as session:
        result = service.artikel_erstellen(session, basis_dto)
    assert result.success
    return result.data


# ---------------------------------------------------------------------------
# Artikel erstellen
# ---------------------------------------------------------------------------

class TestArtikelErstellen:
    def test_erfolg(self, db, service, basis_dto):
        with db.session() as session:
            result = service.artikel_erstellen(session, basis_dto)
        assert result.success
        assert result.data.artikelnummer == "TEST-001"

    def test_anfangsbestand_als_bewegung(self, db, service, basis_dto):
        with db.session() as session:
            service.artikel_erstellen(session, basis_dto)
        with db.session() as session:
            bewegungen = session.query(LagerBewegung).all()
        assert len(bewegungen) == 1
        assert bewegungen[0].buchungsart == Buchungsart.EINGANG
        assert Decimal(str(bewegungen[0].menge)) == Decimal("100")

    def test_kein_anfangsbestand_keine_bewegung(self, db, service):
        dto = ArtikelDTO(
            id=None, artikelnummer="TEST-ZERO", beschreibung="Null",
            einheit="", einzelpreis_netto=Decimal("0"),
            verfuegbar=Decimal("0"),
        )
        with db.session() as session:
            service.artikel_erstellen(session, dto)
        with db.session() as session:
            count = session.query(LagerBewegung).count()
        assert count == 0

    def test_doppelte_artikelnummer(self, db, service, basis_dto):
        with db.session() as session:
            service.artikel_erstellen(session, basis_dto)
        with db.session() as session:
            result = service.artikel_erstellen(session, basis_dto)
        assert not result.success
        assert "vergeben" in result.message

    def test_fehlende_artikelnummer(self, db, service, basis_dto):
        basis_dto.artikelnummer = ""
        with db.session() as session:
            result = service.artikel_erstellen(session, basis_dto)
        assert not result.success

    def test_fehlende_beschreibung(self, db, service, basis_dto):
        basis_dto.beschreibung = "  "
        with db.session() as session:
            result = service.artikel_erstellen(session, basis_dto)
        assert not result.success


# ---------------------------------------------------------------------------
# Lagerbuchungen
# ---------------------------------------------------------------------------

class TestLagerBuchungen:
    def test_einbuchen(self, db, service, artikel_in_db):
        with db.session() as session:
            result = service.einbuchen(
                session, "TEST-001", Decimal("50"),
                referenz="Lieferschein LS-001"
            )
        assert result.success
        with db.session() as session:
            dto = service.artikel_nach_nummer(session, "TEST-001")
        assert dto.verfuegbar == Decimal("150")

    def test_ausbuchen(self, db, service, artikel_in_db):
        with db.session() as session:
            result = service.ausbuchen(session, "TEST-001", Decimal("30"))
        assert result.success
        with db.session() as session:
            dto = service.artikel_nach_nummer(session, "TEST-001")
        assert dto.verfuegbar == Decimal("70")

    def test_ausbuchen_unter_null_erlaubt(self, db, service, artikel_in_db):
        """Negative Bestände sind erlaubt (werden nur gekennzeichnet)."""
        with db.session() as session:
            result = service.ausbuchen(session, "TEST-001", Decimal("200"))
        assert result.success
        with db.session() as session:
            dto = service.artikel_nach_nummer(session, "TEST-001")
        assert dto.verfuegbar == Decimal("-100")
        assert dto.bestand_negativ

    def test_korrektur(self, db, service, artikel_in_db):
        with db.session() as session:
            result = service.korrektur(session, "TEST-001", Decimal("75"))
        assert result.success
        with db.session() as session:
            dto = service.artikel_nach_nummer(session, "TEST-001")
        assert dto.verfuegbar == Decimal("75")

    def test_buchungen_werden_gespeichert(self, db, service, artikel_in_db):
        with db.session() as session:
            service.einbuchen(session, "TEST-001", Decimal("10"))
            service.ausbuchen(session, "TEST-001", Decimal("5"))
            service.korrektur(session, "TEST-001", Decimal("200"))

        with db.session() as session:
            # +1 für Anfangsbestand beim Erstellen
            count = session.query(LagerBewegung).count()
        assert count == 4

    def test_menge_null_wird_abgelehnt(self, db, service, artikel_in_db):
        with db.session() as session:
            result = service.einbuchen(session, "TEST-001", Decimal("0"))
        assert not result.success

    def test_menge_negativ_wird_abgelehnt(self, db, service, artikel_in_db):
        with db.session() as session:
            result = service.einbuchen(session, "TEST-001", Decimal("-10"))
        assert not result.success

    def test_unbekannter_artikel(self, db, service):
        with db.session() as session:
            result = service.einbuchen(session, "NICHTEXISTENT", Decimal("5"))
        assert not result.success


# ---------------------------------------------------------------------------
# Bewegungshistorie
# ---------------------------------------------------------------------------

class TestBewegungsHistorie:
    def test_bewegungen_lesen(self, db, service, artikel_in_db):
        with db.session() as session:
            service.einbuchen(session, "TEST-001", Decimal("10"))
            service.ausbuchen(session, "TEST-001", Decimal("3"))

        with db.session() as session:
            bewegungen = service.bewegungen(session, artikelnummer="TEST-001")
        # Anfangsbestand + 2 Buchungen
        assert len(bewegungen) == 3

    def test_menge_anzeige_eingang(self, db, service, artikel_in_db):
        with db.session() as session:
            service.einbuchen(session, "TEST-001", Decimal("25"))
        with db.session() as session:
            bewegungen = service.bewegungen(session, artikelnummer="TEST-001")
        eingang = next(b for b in bewegungen if b.buchungsart == Buchungsart.EINGANG
                       and b.menge == Decimal("25"))
        assert eingang.menge_anzeige.startswith("+")

    def test_menge_anzeige_ausgang(self, db, service, artikel_in_db):
        with db.session() as session:
            service.ausbuchen(session, "TEST-001", Decimal("10"))
        with db.session() as session:
            bewegungen = service.bewegungen(session, artikelnummer="TEST-001")
        ausgang = next(b for b in bewegungen if b.buchungsart == Buchungsart.AUSGANG)
        assert ausgang.menge_anzeige.startswith("-")


# ---------------------------------------------------------------------------
# Statistik
# ---------------------------------------------------------------------------

class TestStatistik:
    def test_statistik_leer(self, db, service):
        with db.session() as session:
            stats = service.artikel_statistik(session)
        assert stats["gesamt"] == 0
        assert stats["aktiv"] == 0

    def test_statistik_mit_daten(self, db, service, basis_dto):
        with db.session() as session:
            service.artikel_erstellen(session, basis_dto)
            # Zweiter Artikel mit kritischem Bestand
            krit = ArtikelDTO(
                id=None, artikelnummer="KRIT-001", beschreibung="Kritisch",
                einheit="kg", einzelpreis_netto=Decimal("5"),
                verfuegbar=Decimal("3"),  # unter 5 = kritisch
            )
            service.artikel_erstellen(session, krit)

        with db.session() as session:
            stats = service.artikel_statistik(session)

        assert stats["aktiv"] == 2
        assert stats["kritisch"] == 1
        assert stats["negativ"] == 0
        assert stats["lagerwert"] > 0

    def test_deaktivieren_reaktivieren(self, db, service, artikel_in_db):
        with db.session() as session:
            result = service.artikel_deaktivieren(session, artikel_in_db.id)
        assert result.success

        with db.session() as session:
            aktive = service.alle_artikel(session, nur_aktive=True)
        assert len(aktive) == 0

        with db.session() as session:
            result = service.artikel_reaktivieren(session, artikel_in_db.id)
        assert result.success

        with db.session() as session:
            aktive = service.alle_artikel(session, nur_aktive=True)
        assert len(aktive) == 1
