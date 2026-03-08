"""
tests/core/test_rechnungen_service.py – Tests für den RechnungsService
======================================================================
Vollständige Abdeckung: Erstellen, Bearbeiten, Finalisieren,
Statusänderung, Storno, automatische Mahnstufenprüfung.
"""

import pytest
from decimal import Decimal
from datetime import datetime, timedelta, date

from core.db.engine import DatabaseManager, Base
from core.models import Kunde, Rechnung, Rechnungsposten, Artikel, AuditLog
from core.services.rechnungen_service import (
    RechnungsService, RechnungDTO, PostenDTO, RechnungStatus,
    berechne_summen, berechne_gesamtpreis,
)
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
    return RechnungsService()


@pytest.fixture
def kunde(db):
    """Legt einen Testkunden an."""
    with db.session() as s:
        k = Kunde(name="Müller", vorname="Hans", zifferncode=1001)
        s.add(k)
    with db.session() as s:
        return s.query(Kunde).filter_by(zifferncode=1001).first().id


@pytest.fixture
def artikel(db):
    """Legt einen Testartikel an."""
    with db.session() as s:
        a = Artikel(
            artikelnummer="ART-001", beschreibung="Testprodukt",
            einheit="Stück", einzelpreis_netto=Decimal("49.99"),
            verfuegbar=Decimal("100"),
        )
        s.add(a)
    with db.session() as s:
        return s.query(Artikel).filter_by(artikelnummer="ART-001").first()


@pytest.fixture
def basis_dto(kunde):
    """Ein minimales Rechnungs-DTO."""
    return RechnungDTO(
        id=None, kunde_id=kunde,
        rechnungsnummer="2025-0001",
        rechnungsdatum="15.01.2025",
        faelligkeitsdatum="29.01.2025",
        mwst_prozent=Decimal("19.00"),
        summe_netto=Decimal("0"), summe_mwst=Decimal("0"),
        summe_brutto=Decimal("0"), mahngebuehren=Decimal("0"),
        offener_betrag=Decimal("0"),
        status=RechnungStatus.ENTWURF,
        bemerkung="", is_finalized=False,
        posten=[
            PostenDTO(
                id=None, rechnung_id=None, position=1,
                artikelnummer="", beschreibung="Beratungsleistung",
                menge=Decimal("2"), einheit="h",
                einzelpreis_netto=Decimal("80.00"),
                gesamtpreis_netto=Decimal("160.00"),
            )
        ],
    )


@pytest.fixture
def rechnung_entwurf(db, service, basis_dto, kunde):
    """Legt einen Rechnungsentwurf an."""
    with db.session() as s:
        r = service.entwurf_erstellen(s, kunde, basis_dto)
    assert r.success
    return r.data


@pytest.fixture
def rechnung_finalisiert(db, service, rechnung_entwurf):
    """Finalisiert einen Entwurf."""
    with db.session() as s:
        r = service.finalisieren(s, rechnung_entwurf.id)
    assert r.success
    return r.data


# ---------------------------------------------------------------------------
# Hilfsberechnungen
# ---------------------------------------------------------------------------

class TestBerechnung:
    def test_gesamtpreis(self):
        assert berechne_gesamtpreis(Decimal("3"), Decimal("10")) == Decimal("30.00")

    def test_gesamtpreis_negativ(self):
        assert berechne_gesamtpreis(Decimal("-1"), Decimal("50")) == Decimal("-50.00")

    def test_summen_19_prozent(self):
        posten = [
            PostenDTO(None, None, 1, "", "Test", Decimal("1"), "", Decimal("100"), Decimal("100"))
        ]
        netto, mwst, brutto = berechne_summen(posten, Decimal("19"))
        assert netto == Decimal("100.00")
        assert mwst == Decimal("19.00")
        assert brutto == Decimal("119.00")

    def test_summen_leer(self):
        netto, mwst, brutto = berechne_summen([], Decimal("19"))
        assert netto == Decimal("0.00")
        assert brutto == Decimal("0.00")


# ---------------------------------------------------------------------------
# Rechnungsnummern
# ---------------------------------------------------------------------------

class TestRechnungsnummern:
    def test_erste_nummer(self, db, service):
        with db.session() as s:
            nr = service.naechste_rechnungsnummer(s, 2025)
        assert nr == "2025-0001"

    def test_fortlaufend(self, db, service, rechnung_entwurf):
        with db.session() as s:
            nr = service.naechste_rechnungsnummer(s, 2025)
        assert nr == "2025-0002"

    def test_existiert(self, db, service, rechnung_entwurf):
        with db.session() as s:
            assert service.nummer_existiert(s, "2025-0001") is True
            assert service.nummer_existiert(s, "2025-9999") is False


# ---------------------------------------------------------------------------
# Entwurf erstellen
# ---------------------------------------------------------------------------

class TestEntwurfErstellen:
    def test_erfolg(self, db, service, basis_dto, kunde):
        with db.session() as s:
            r = service.entwurf_erstellen(s, kunde, basis_dto)
        assert r.success
        assert r.data.rechnungsnummer == "2025-0001"
        assert r.data.status == RechnungStatus.ENTWURF
        assert not r.data.is_finalized

    def test_summen_berechnet(self, db, service, rechnung_entwurf):
        assert rechnung_entwurf.summe_netto == Decimal("160.00")
        assert rechnung_entwurf.summe_mwst == Decimal("30.40")
        assert rechnung_entwurf.summe_brutto == Decimal("190.40")

    def test_doppelte_nummer_abgelehnt(self, db, service, basis_dto, kunde, rechnung_entwurf):
        basis_dto.rechnungsnummer = "2025-0001"
        with db.session() as s:
            r = service.entwurf_erstellen(s, kunde, basis_dto)
        assert not r.success
        assert "vergeben" in r.message.lower()

    def test_ohne_nummer_abgelehnt(self, db, service, basis_dto, kunde):
        basis_dto.rechnungsnummer = ""
        with db.session() as s:
            r = service.entwurf_erstellen(s, kunde, basis_dto)
        assert not r.success

    def test_ohne_datum_abgelehnt(self, db, service, basis_dto, kunde):
        basis_dto.rechnungsdatum = ""
        with db.session() as s:
            r = service.entwurf_erstellen(s, kunde, basis_dto)
        assert not r.success

    def test_falsches_datumsformat(self, db, service, basis_dto, kunde):
        basis_dto.rechnungsdatum = "2025-01-15"
        with db.session() as s:
            r = service.entwurf_erstellen(s, kunde, basis_dto)
        assert not r.success

    def test_ohne_posten_abgelehnt(self, db, service, basis_dto, kunde):
        basis_dto.posten = []
        with db.session() as s:
            r = service.entwurf_erstellen(s, kunde, basis_dto)
        assert not r.success

    def test_audit_log(self, db, service, rechnung_entwurf):
        with db.session() as s:
            entry = s.query(AuditLog).filter_by(
                action=AuditAction.RECHNUNG_ENTWURF_ERSTELLT
            ).first()
        assert entry is not None


# ---------------------------------------------------------------------------
# Entwurf bearbeiten
# ---------------------------------------------------------------------------

class TestEntwurfAktualisieren:
    def test_erfolg(self, db, service, rechnung_entwurf, basis_dto):
        basis_dto.rechnungsnummer = "2025-0001"
        basis_dto.bemerkung = "Geänderte Bemerkung"
        basis_dto.posten[0].beschreibung = "Neue Beschreibung"

        with db.session() as s:
            r = service.entwurf_aktualisieren(s, rechnung_entwurf.id, basis_dto)
        assert r.success

        with db.session() as s:
            updated = service.nach_id(s, rechnung_entwurf.id)
        assert updated.bemerkung == "Geänderte Bemerkung"
        assert updated.posten[0].beschreibung == "Neue Beschreibung"

    def test_finalisierte_nicht_editierbar(self, db, service, rechnung_finalisiert, basis_dto):
        basis_dto.rechnungsnummer = "2025-0001"
        with db.session() as s:
            r = service.entwurf_aktualisieren(s, rechnung_finalisiert.id, basis_dto)
        assert not r.success
        assert "finalisiert" in r.message.lower()


# ---------------------------------------------------------------------------
# Entwurf löschen
# ---------------------------------------------------------------------------

class TestEntwurfLoeschen:
    def test_erfolg(self, db, service, rechnung_entwurf):
        with db.session() as s:
            r = service.entwurf_loeschen(s, rechnung_entwurf.id)
        assert r.success

        with db.session() as s:
            assert service.nach_id(s, rechnung_entwurf.id) is None

    def test_finalisierte_nicht_loeschbar(self, db, service, rechnung_finalisiert):
        with db.session() as s:
            r = service.entwurf_loeschen(s, rechnung_finalisiert.id)
        assert not r.success
        assert "GoBD" in r.message


# ---------------------------------------------------------------------------
# Finalisieren
# ---------------------------------------------------------------------------

class TestFinalisieren:
    def test_erfolg(self, db, service, rechnung_entwurf):
        with db.session() as s:
            r = service.finalisieren(s, rechnung_entwurf.id)
        assert r.success

        with db.session() as s:
            dto = service.nach_id(s, rechnung_entwurf.id)
        assert dto.is_finalized
        assert dto.status == RechnungStatus.OFFEN

    def test_lagerabbuchung(self, db, service, artikel, basis_dto, kunde):
        """Lagerbestand wird beim Finalisieren abgebucht."""
        basis_dto.rechnungsnummer = "2025-LAGER"
        basis_dto.posten[0].artikelnummer = "ART-001"
        basis_dto.posten[0].menge = Decimal("5")

        with db.session() as s:
            r = service.entwurf_erstellen(s, kunde, basis_dto)
        rechnung_id = r.data.id

        with db.session() as s:
            service.finalisieren(s, rechnung_id)

        with db.session() as s:
            a = s.query(Artikel).filter_by(artikelnummer="ART-001").first()
        assert a.verfuegbar == Decimal("95")  # 100 - 5

    def test_bereits_finalisiert(self, db, service, rechnung_finalisiert):
        with db.session() as s:
            r = service.finalisieren(s, rechnung_finalisiert.id)
        assert not r.success

    def test_audit_log(self, db, service, rechnung_entwurf):
        with db.session() as s:
            service.finalisieren(s, rechnung_entwurf.id)
        with db.session() as s:
            entry = s.query(AuditLog).filter_by(
                action=AuditAction.RECHNUNG_FINALISIERT
            ).first()
        assert entry is not None


# ---------------------------------------------------------------------------
# Statusänderung
# ---------------------------------------------------------------------------

class TestStatusAenderung:
    def test_auf_bezahlt(self, db, service, rechnung_finalisiert):
        with db.session() as s:
            r = service.status_aendern(s, rechnung_finalisiert.id, RechnungStatus.BEZAHLT)
        assert r.success

        with db.session() as s:
            dto = service.nach_id(s, rechnung_finalisiert.id)
        assert dto.status == RechnungStatus.BEZAHLT

    def test_entwurf_kein_status(self, db, service, rechnung_entwurf):
        with db.session() as s:
            r = service.status_aendern(s, rechnung_entwurf.id, RechnungStatus.BEZAHLT)
        assert not r.success

    def test_storniert_nicht_manuell_setzbar(self, db, service, rechnung_finalisiert):
        with db.session() as s:
            r = service.status_aendern(s, rechnung_finalisiert.id, RechnungStatus.STORNIERT)
        assert not r.success


# ---------------------------------------------------------------------------
# Automatische Mahnstufenprüfung
# ---------------------------------------------------------------------------

class TestMahnstufenpruefung:
    def _erstelle_offene_rechnung(self, db, service, kunde, tage_ueberfaellig: int):
        faellig = (date.today() - timedelta(days=tage_ueberfaellig)).strftime("%d.%m.%Y")
        dto = RechnungDTO(
            id=None, kunde_id=kunde,
            rechnungsnummer=f"2025-TEST-{tage_ueberfaellig}",
            rechnungsdatum="01.01.2025",
            faelligkeitsdatum=faellig,
            mwst_prozent=Decimal("19"),
            summe_netto=Decimal("0"), summe_mwst=Decimal("0"),
            summe_brutto=Decimal("0"), mahngebuehren=Decimal("0"),
            offener_betrag=Decimal("0"),
            status=RechnungStatus.ENTWURF,
            bemerkung="", is_finalized=False,
            posten=[PostenDTO(None, None, 1, "", "Test", Decimal("1"), "", Decimal("10"), Decimal("10"))],
        )
        with db.session() as s:
            r = service.entwurf_erstellen(s, kunde, dto)
        with db.session() as s:
            service.finalisieren(s, r.data.id)
        return r.data.id

    def test_erinnerung_nach_7_tagen(self, db, service, kunde):
        rid = self._erstelle_offene_rechnung(db, service, kunde, 8)
        with db.session() as s:
            geaendert = service.pruefe_ueberfaellige(s, reminder_days=7)
        assert any(g["rechnung_id"] == rid for g in geaendert)
        with db.session() as s:
            dto = service.nach_id(s, rid)
        assert dto.status == RechnungStatus.ERINNERUNG

    def test_mahnung1_nach_21_tagen(self, db, service, kunde):
        rid = self._erstelle_offene_rechnung(db, service, kunde, 22)
        with db.session() as s:
            service.pruefe_ueberfaellige(s)
        with db.session() as s:
            dto = service.nach_id(s, rid)
        assert dto.status == RechnungStatus.MAHNUNG1

    def test_inkasso_nach_49_tagen(self, db, service, kunde):
        rid = self._erstelle_offene_rechnung(db, service, kunde, 50)
        with db.session() as s:
            service.pruefe_ueberfaellige(s)
        with db.session() as s:
            dto = service.nach_id(s, rid)
        assert dto.status == RechnungStatus.INKASSO

    def test_nicht_ueberfaellig_unveraendert(self, db, service, kunde):
        rid = self._erstelle_offene_rechnung(db, service, kunde, 3)
        with db.session() as s:
            geaendert = service.pruefe_ueberfaellige(s)
        assert not any(g["rechnung_id"] == rid for g in geaendert)


# ---------------------------------------------------------------------------
# Storno
# ---------------------------------------------------------------------------

class TestStorno:
    def test_storno_erstellt_gutschrift(self, db, service, rechnung_finalisiert):
        with db.session() as s:
            r = service.stornieren(s, rechnung_finalisiert.id, "Testgrund")
        assert r.success
        assert "gutschrift" in r.message.lower()

        gut_id = r.data["gutschrift_id"]
        with db.session() as s:
            gut = service.nach_id(s, gut_id)
        assert gut.status == RechnungStatus.GUTSCHRIFT
        assert gut.summe_brutto < 0  # Negative Beträge

    def test_original_storniert(self, db, service, rechnung_finalisiert):
        with db.session() as s:
            service.stornieren(s, rechnung_finalisiert.id)
        with db.session() as s:
            dto = service.nach_id(s, rechnung_finalisiert.id)
        assert dto.status == RechnungStatus.STORNIERT

    def test_lager_zurueckgebucht(self, db, service, artikel, basis_dto, kunde):
        basis_dto.rechnungsnummer = "2025-STORNO"
        basis_dto.posten[0].artikelnummer = "ART-001"
        basis_dto.posten[0].menge = Decimal("10")

        with db.session() as s:
            r = service.entwurf_erstellen(s, kunde, basis_dto)
        rechnung_id = r.data.id

        with db.session() as s:
            service.finalisieren(s, rechnung_id)

        with db.session() as s:
            a = s.query(Artikel).filter_by(artikelnummer="ART-001").first()
        assert a.verfuegbar == Decimal("90")  # 100 - 10

        with db.session() as s:
            service.stornieren(s, rechnung_id)

        with db.session() as s:
            a = s.query(Artikel).filter_by(artikelnummer="ART-001").first()
        assert a.verfuegbar == Decimal("100")  # Zurückgebucht

    def test_entwurf_nicht_stornierbar(self, db, service, rechnung_entwurf):
        with db.session() as s:
            r = service.stornieren(s, rechnung_entwurf.id)
        assert not r.success

    def test_bereits_storniert(self, db, service, rechnung_finalisiert):
        with db.session() as s:
            service.stornieren(s, rechnung_finalisiert.id)
        with db.session() as s:
            r = service.stornieren(s, rechnung_finalisiert.id)
        assert not r.success

    def test_storno_nummer_format(self, db, service, rechnung_finalisiert):
        with db.session() as s:
            r = service.stornieren(s, rechnung_finalisiert.id)
        jahr = datetime.now().year
        assert r.data["gutschrift_nummer"].startswith(f"S-{jahr}-")
