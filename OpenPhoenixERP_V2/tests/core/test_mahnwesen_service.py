"""
tests/core/test_mahnwesen_service.py – Tests für den MahnwesenService
======================================================================
"""

import pytest
from datetime import date, timedelta
from decimal import Decimal

from core.db.engine import DatabaseManager
from core.models import Kunde, Rechnung
from core.services.rechnungen_service import RechnungsService, RechnungStatus
from core.services.mahnwesen_service import (
    MahnwesenService, MahnKonfig, mahnwesen_service,
)


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
    return MahnwesenService()


@pytest.fixture
def konfig():
    return MahnKonfig(
        reminder_days=7,
        mahnung1_days=21,
        mahnung2_days=35,
        inkasso_days=49,
        cost_erinnerung=Decimal("0.00"),
        cost_mahnung1=Decimal("5.00"),
        cost_mahnung2=Decimal("10.00"),
        cost_inkasso=Decimal("25.00"),
    )


def _mach_rechnung(session, tage_ueberfaellig: int, status=RechnungStatus.OFFEN) -> Rechnung:
    """Hilfsfunktion: Erstellt eine finalisierte Rechnung mit gegebenem Fälligkeitsdatum."""
    faellig = date.today() - timedelta(days=tage_ueberfaellig)

    # Sicherstellen dass Kunde vorhanden
    kunde = session.query(Kunde).first()
    if not kunde:
        kunde = Kunde(
            zifferncode=1001,
            name="Testmann",
            vorname="Hans",
            is_active=True,
        )
        session.add(kunde)
        session.flush()

    rechnung = Rechnung(
        kunde_id=kunde.id,
        rechnungsnummer=f"TEST-{tage_ueberfaellig:04d}-{id(faellig)}",
        rechnungsdatum=date.today().strftime("%d.%m.%Y"),
        faelligkeitsdatum=faellig.strftime("%d.%m.%Y"),
        mwst_prozent=Decimal("19"),
        summe_netto=Decimal("100.00"),
        summe_mwst=Decimal("19.00"),
        summe_brutto=Decimal("119.00"),
        mahngebuehren=Decimal("0"),
        offener_betrag=Decimal("119.00"),
        status=status,
        is_finalized=True,
    )
    session.add(rechnung)
    session.flush()
    return rechnung


# ---------------------------------------------------------------------------
# Eskalation
# ---------------------------------------------------------------------------

class TestEskalation:
    def test_keine_ueberfaelligen(self, db, service, konfig):
        with db.session() as session:
            ergebnis = service.pruefe_und_eskaliere(session, konfig)
        assert ergebnis["eskaliert"] == 0

    def test_offen_wird_erinnerung(self, db, service, konfig):
        """Rechnung 10 Tage überfällig → Erinnerung (>= 7 Tage)."""
        with db.session() as session:
            r = _mach_rechnung(session, tage_ueberfaellig=10)
            rechnung_id = r.id

        with db.session() as session:
            ergebnis = service.pruefe_und_eskaliere(session, konfig)

        assert ergebnis["eskaliert"] == 1
        with db.session() as session:
            r = session.get(Rechnung, rechnung_id)
        assert r.status == RechnungStatus.ERINNERUNG

    def test_offen_wird_mahnung1(self, db, service, konfig):
        """25 Tage überfällig → direkt Mahnung1 (>= 21 Tage)."""
        with db.session() as session:
            r = _mach_rechnung(session, tage_ueberfaellig=25)
            rechnung_id = r.id

        with db.session() as session:
            service.pruefe_und_eskaliere(session, konfig)

        with db.session() as session:
            r = session.get(Rechnung, rechnung_id)
        assert r.status == RechnungStatus.MAHNUNG1

    def test_mahnung1_wird_mahnung2(self, db, service, konfig):
        """Bereits auf Mahnung1, 38 Tage überfällig → Mahnung2."""
        with db.session() as session:
            r = _mach_rechnung(
                session, tage_ueberfaellig=38,
                status=RechnungStatus.MAHNUNG1
            )
            rechnung_id = r.id

        with db.session() as session:
            service.pruefe_und_eskaliere(session, konfig)

        with db.session() as session:
            r = session.get(Rechnung, rechnung_id)
        assert r.status == RechnungStatus.MAHNUNG2

    def test_mahnung2_wird_inkasso(self, db, service, konfig):
        """52 Tage überfällig → Inkasso (>= 49 Tage)."""
        with db.session() as session:
            r = _mach_rechnung(
                session, tage_ueberfaellig=52,
                status=RechnungStatus.MAHNUNG2
            )
            rechnung_id = r.id

        with db.session() as session:
            service.pruefe_und_eskaliere(session, konfig)

        with db.session() as session:
            r = session.get(Rechnung, rechnung_id)
        assert r.status == RechnungStatus.INKASSO

    def test_inkasso_bleibt_inkasso(self, db, service, konfig):
        """Inkasso-Rechnungen werden nicht weiter eskaliert."""
        with db.session() as session:
            r = _mach_rechnung(
                session, tage_ueberfaellig=60,
                status=RechnungStatus.INKASSO
            )
            rechnung_id = r.id

        with db.session() as session:
            ergebnis = service.pruefe_und_eskaliere(session, konfig)

        assert ergebnis["eskaliert"] == 0
        with db.session() as session:
            r = session.get(Rechnung, rechnung_id)
        assert r.status == RechnungStatus.INKASSO

    def test_bezahlte_werden_ignoriert(self, db, service, konfig):
        """Bezahlte Rechnungen werden nicht eskaliert."""
        with db.session() as session:
            _mach_rechnung(
                session, tage_ueberfaellig=30,
                status=RechnungStatus.BEZAHLT
            )

        with db.session() as session:
            ergebnis = service.pruefe_und_eskaliere(session, konfig)

        assert ergebnis["eskaliert"] == 0

    def test_noch_nicht_faellig_wird_ignoriert(self, db, service, konfig):
        """Rechnungen die noch nicht fällig sind werden nicht eskaliert."""
        morgen = date.today() + timedelta(days=5)
        with db.session() as session:
            kunde = Kunde(zifferncode=2001, name="Test", vorname="X", is_active=True)
            session.add(kunde)
            session.flush()
            r = Rechnung(
                kunde_id=kunde.id,
                rechnungsnummer="ZUKUNFT-001",
                rechnungsdatum=date.today().strftime("%d.%m.%Y"),
                faelligkeitsdatum=morgen.strftime("%d.%m.%Y"),
                mwst_prozent=Decimal("19"),
                summe_netto=Decimal("100"), summe_mwst=Decimal("19"),
                summe_brutto=Decimal("119"), mahngebuehren=Decimal("0"),
                offener_betrag=Decimal("119"),
                status=RechnungStatus.OFFEN, is_finalized=True,
            )
            session.add(r)

        with db.session() as session:
            ergebnis = service.pruefe_und_eskaliere(session, konfig)

        assert ergebnis["eskaliert"] == 0

    def test_mahngebuehr_wird_automatisch_gebucht(self, db, service, konfig):
        """Beim Eskalieren auf Mahnung1 wird Mahngebühr 5,00 € automatisch gebucht."""
        with db.session() as session:
            r = _mach_rechnung(session, tage_ueberfaellig=25)
            rechnung_id = r.id

        with db.session() as session:
            ergebnis = service.pruefe_und_eskaliere(session, konfig)

        assert ergebnis["gebuehren"] == 1
        with db.session() as session:
            r = session.get(Rechnung, rechnung_id)
        assert Decimal(str(r.mahngebuehren)) == Decimal("5.00")
        assert Decimal(str(r.offener_betrag)) == Decimal("124.00")


# ---------------------------------------------------------------------------
# Übersicht
# ---------------------------------------------------------------------------

class TestUebersicht:
    def test_leere_uebersicht(self, db, service, konfig):
        with db.session() as session:
            ueb = service.uebersicht(session, konfig)
        assert ueb.gesamt_anzahl == 0
        assert ueb.gesamt_betrag == Decimal("0")

    def test_uebersicht_mit_rechnungen(self, db, service, konfig):
        with db.session() as session:
            _mach_rechnung(session, 10, RechnungStatus.ERINNERUNG)
            _mach_rechnung(session, 25, RechnungStatus.MAHNUNG1)
            _mach_rechnung(session, 38, RechnungStatus.MAHNUNG2)
            _mach_rechnung(session, 55, RechnungStatus.INKASSO)

        with db.session() as session:
            ueb = service.uebersicht(session, konfig)

        assert len(ueb.erinnerung) == 1
        assert len(ueb.mahnung1) == 1
        assert len(ueb.mahnung2) == 1
        assert len(ueb.inkasso) == 1
        assert ueb.gesamt_anzahl == 4

    def test_bald_faellig(self, db, service, konfig):
        """Rechnungen die in 3 Tagen fällig sind erscheinen in bald_faellig."""
        in_drei = date.today() + timedelta(days=3)
        with db.session() as session:
            kunde = Kunde(zifferncode=3001, name="Bald", vorname="Y", is_active=True)
            session.add(kunde)
            session.flush()
            r = Rechnung(
                kunde_id=kunde.id,
                rechnungsnummer="BALD-001",
                rechnungsdatum=date.today().strftime("%d.%m.%Y"),
                faelligkeitsdatum=in_drei.strftime("%d.%m.%Y"),
                mwst_prozent=Decimal("19"),
                summe_netto=Decimal("200"), summe_mwst=Decimal("38"),
                summe_brutto=Decimal("238"), mahngebuehren=Decimal("0"),
                offener_betrag=Decimal("238"),
                status=RechnungStatus.OFFEN, is_finalized=True,
            )
            session.add(r)

        with db.session() as session:
            ueb = service.uebersicht(session, konfig)

        assert len(ueb.bald_faellig) == 1
        assert ueb.bald_faellig[0].rechnungsnummer == "BALD-001"

    def test_statistik(self, db, service, konfig):
        with db.session() as session:
            _mach_rechnung(session, 10, RechnungStatus.ERINNERUNG)
            _mach_rechnung(session, 25, RechnungStatus.MAHNUNG1)

        with db.session() as session:
            ueb = service.uebersicht(session, konfig)
            stats = ueb.statistik

        assert stats["gesamt"] == 2
        assert stats["erinnerung"] == 1
        assert stats["mahnung1"] == 1
        assert stats["betrag"] > 0


# ---------------------------------------------------------------------------
# Mahngebühren
# ---------------------------------------------------------------------------

class TestMahngebuehren:
    def test_gebuehr_buchen(self, db, service, konfig):
        with db.session() as session:
            r = _mach_rechnung(session, 10, RechnungStatus.ERINNERUNG)
            rechnung_id = r.id

        with db.session() as session:
            result = service.mahngebuehr_buchen(
                session, rechnung_id, Decimal("5.00"), "Mahnung 1"
            )

        assert result.success
        with db.session() as session:
            r = session.get(Rechnung, rechnung_id)
        assert Decimal(str(r.mahngebuehren)) == Decimal("5.00")
        assert Decimal(str(r.offener_betrag)) == Decimal("124.00")

    def test_mehrfach_buchen(self, db, service, konfig):
        with db.session() as session:
            r = _mach_rechnung(session, 10, RechnungStatus.MAHNUNG2)
            rechnung_id = r.id

        with db.session() as session:
            service.mahngebuehr_buchen(session, rechnung_id, Decimal("5.00"))
        with db.session() as session:
            service.mahngebuehr_buchen(session, rechnung_id, Decimal("10.00"))

        with db.session() as session:
            r = session.get(Rechnung, rechnung_id)
        assert Decimal(str(r.mahngebuehren)) == Decimal("15.00")

    def test_gebuehr_stornieren(self, db, service, konfig):
        with db.session() as session:
            r = _mach_rechnung(session, 10, RechnungStatus.MAHNUNG1)
            rechnung_id = r.id

        with db.session() as session:
            service.mahngebuehr_buchen(session, rechnung_id, Decimal("5.00"))
        with db.session() as session:
            result = service.mahngebuehr_stornieren(
                session, rechnung_id, Decimal("5.00"), "Kulanz"
            )

        assert result.success
        with db.session() as session:
            r = session.get(Rechnung, rechnung_id)
        assert Decimal(str(r.mahngebuehren)) == Decimal("0.00")

    def test_storno_zu_hoch(self, db, service, konfig):
        with db.session() as session:
            r = _mach_rechnung(session, 10, RechnungStatus.MAHNUNG1)
            rechnung_id = r.id
        with db.session() as session:
            service.mahngebuehr_buchen(session, rechnung_id, Decimal("5.00"))
        with db.session() as session:
            result = service.mahngebuehr_stornieren(
                session, rechnung_id, Decimal("99.00")
            )
        assert not result.success

    def test_null_gebuehr_abgelehnt(self, db, service, konfig):
        with db.session() as session:
            r = _mach_rechnung(session, 10)
            rechnung_id = r.id
        with db.session() as session:
            result = service.mahngebuehr_buchen(
                session, rechnung_id, Decimal("0")
            )
        assert not result.success


# ---------------------------------------------------------------------------
# MahnKonfig
# ---------------------------------------------------------------------------

class TestMahnKonfig:
    def test_gebuehr_fuer_status(self, konfig):
        assert konfig.gebuehr_fuer_status(RechnungStatus.ERINNERUNG) == Decimal("0")
        assert konfig.gebuehr_fuer_status(RechnungStatus.MAHNUNG1) == Decimal("5.00")
        assert konfig.gebuehr_fuer_status(RechnungStatus.MAHNUNG2) == Decimal("10.00")
        assert konfig.gebuehr_fuer_status(RechnungStatus.INKASSO) == Decimal("25.00")
        assert konfig.gebuehr_fuer_status(RechnungStatus.BEZAHLT) == Decimal("0")

    def test_naechste_stufe_berechnung(self, service, konfig):
        naechste, tage = service._naechste_stufe(
            RechnungStatus.OFFEN, tage_ueberfaellig=3, konfig=konfig
        )
        assert naechste == RechnungStatus.ERINNERUNG
        assert tage == 4  # 7 - 3

    def test_naechste_stufe_bei_inkasso(self, service, konfig):
        naechste, tage = service._naechste_stufe(
            RechnungStatus.INKASSO, tage_ueberfaellig=60, konfig=konfig
        )
        assert naechste is None
        assert tage is None
