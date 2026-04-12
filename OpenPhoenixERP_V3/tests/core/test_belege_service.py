"""
tests/core/test_belege_service.py – Tests für den BelegeService
================================================================
Abdeckung: CRUD, Zahlungsstatus, Soft-Delete, Betragsberechnung,
Filter, Statistik, Audit-Logging.
"""

import pytest
from decimal import Decimal

from core.db.engine import DatabaseManager
from core.models import EingangsRechnung, AuditLog
from core.services.belege_service import (
    BelegeService, EingangsRechnungDTO, Zahlungsstatus,
    BelegKategorie, _berechne_betraege,
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
    return BelegeService()


def _dto(
    lieferant: str = "Muster GmbH",
    betrag_netto: str = "100.00",
    mwst_satz: str = "19",
    kategorie: str = "Material",
    datum: str = "15.03.2026",
    belegnummer: str = "RE-2026-001",
    zahlungsstatus: str = Zahlungsstatus.OFFEN,
) -> EingangsRechnungDTO:
    netto = Decimal(betrag_netto)
    satz = Decimal(mwst_satz)
    mwst, brutto = _berechne_betraege(netto, satz)
    return EingangsRechnungDTO(
        id=None,
        datum=datum,
        lieferant=lieferant,
        belegnummer=belegnummer,
        betrag_netto=netto,
        mwst_satz=satz,
        mwst_betrag=mwst,
        betrag_brutto=brutto,
        kategorie=kategorie,
        bemerkung="",
        zahlungsstatus=zahlungsstatus,
        beleg_pfad=None,
        beleg_dateiname=None,
    )


# ---------------------------------------------------------------------------
# Betragsberechnung
# ---------------------------------------------------------------------------

class TestBetragsberechnung:
    def test_standard_mwst(self):
        mwst, brutto = _berechne_betraege(Decimal("100.00"), Decimal("19"))
        assert mwst == Decimal("19.00")
        assert brutto == Decimal("119.00")

    def test_reduzierter_steuersatz(self):
        mwst, brutto = _berechne_betraege(Decimal("100.00"), Decimal("7"))
        assert mwst == Decimal("7.00")
        assert brutto == Decimal("107.00")

    def test_null_steuersatz(self):
        mwst, brutto = _berechne_betraege(Decimal("200.00"), Decimal("0"))
        assert mwst == Decimal("0.00")
        assert brutto == Decimal("200.00")

    def test_rundung(self):
        # 99.99 * 19% = 18.9981 → 19.00
        mwst, brutto = _berechne_betraege(Decimal("99.99"), Decimal("19"))
        assert mwst == Decimal("19.00")
        assert brutto == Decimal("118.99")


# ---------------------------------------------------------------------------
# Erstellen
# ---------------------------------------------------------------------------

class TestErstellen:
    def test_erstellen_erfolgreich(self, db, service):
        with db.session() as session:
            result = service.beleg_erstellen(session, _dto())
        assert result.success
        assert result.data is not None
        assert result.data.lieferant == "Muster GmbH"

    def test_mwst_automatisch_berechnet(self, db, service):
        with db.session() as session:
            result = service.beleg_erstellen(session, _dto(betrag_netto="100.00", mwst_satz="19"))
        assert result.data.mwst_betrag == Decimal("19.00")
        assert result.data.betrag_brutto == Decimal("119.00")

    def test_erstellen_ohne_lieferant_fehlschlag(self, db, service):
        with db.session() as session:
            dto = _dto(lieferant="")
            result = service.beleg_erstellen(session, dto)
        assert not result.success
        assert "Lieferant" in result.message

    def test_erstellen_ohne_datum_fehlschlag(self, db, service):
        with db.session() as session:
            dto = _dto(datum="")
            result = service.beleg_erstellen(session, dto)
        assert not result.success

    def test_erstellen_negativer_betrag_fehlschlag(self, db, service):
        with db.session() as session:
            dto = _dto(betrag_netto="-10.00")
            result = service.beleg_erstellen(session, dto)
        assert not result.success

    def test_status_standard_offen(self, db, service):
        with db.session() as session:
            result = service.beleg_erstellen(session, _dto())
        assert result.data.zahlungsstatus == Zahlungsstatus.OFFEN

    def test_audit_log_erstellt(self, db, service):
        with db.session() as session:
            service.beleg_erstellen(session, _dto())
        with db.session() as session:
            logs = session.query(AuditLog).all()
        assert any("BELEG" in l.action for l in logs)

    def test_verschiedene_kategorien(self, db, service):
        with db.session() as session:
            for kat in ["Material", "Kraftstoff", "Bürobedarf"]:
                result = service.beleg_erstellen(session, _dto(kategorie=kat))
                assert result.success
                assert result.data.kategorie == kat


# ---------------------------------------------------------------------------
# Lesen
# ---------------------------------------------------------------------------

class TestLesen:
    def test_alle_belege_leer(self, db, service):
        with db.session() as session:
            belege = service.alle_belege(session)
        assert belege == []

    def test_alle_belege_nach_erstellen(self, db, service):
        with db.session() as session:
            service.beleg_erstellen(session, _dto("A GmbH", belegnummer="001"))
            service.beleg_erstellen(session, _dto("B GmbH", belegnummer="002"))
            belege = service.alle_belege(session)
        assert len(belege) == 2

    def test_nach_id(self, db, service):
        with db.session() as session:
            r = service.beleg_erstellen(session, _dto())
            beleg_id = r.data.id
            beleg = service.beleg_nach_id(session, beleg_id)
        assert beleg is not None
        assert beleg.lieferant == "Muster GmbH"

    def test_nach_id_nicht_gefunden(self, db, service):
        with db.session() as session:
            beleg = service.beleg_nach_id(session, 99999)
        assert beleg is None

    def test_filter_nach_kategorie(self, db, service):
        with db.session() as session:
            service.beleg_erstellen(session, _dto(kategorie="Material", belegnummer="001"))
            service.beleg_erstellen(session, _dto(kategorie="Kraftstoff", belegnummer="002"))
            result = service.alle_belege(session, kategorie="Material")
        assert len(result) == 1
        assert result[0].kategorie == "Material"

    def test_filter_nach_zahlungsstatus(self, db, service):
        with db.session() as session:
            service.beleg_erstellen(session, _dto(zahlungsstatus=Zahlungsstatus.OFFEN, belegnummer="001"))
            service.beleg_erstellen(session, _dto(zahlungsstatus=Zahlungsstatus.BEZAHLT, belegnummer="002"))
            offene = service.alle_belege(session, zahlungsstatus=Zahlungsstatus.OFFEN)
        assert len(offene) == 1

    def test_filter_suchtext_lieferant(self, db, service):
        with db.session() as session:
            service.beleg_erstellen(session, _dto("ABC GmbH", belegnummer="001"))
            service.beleg_erstellen(session, _dto("XYZ AG", belegnummer="002"))
            result = service.alle_belege(session, suchtext="ABC")
        assert len(result) == 1

    def test_filter_suchtext_belegnummer(self, db, service):
        with db.session() as session:
            service.beleg_erstellen(session, _dto(belegnummer="RE-2026-001"))
            service.beleg_erstellen(session, _dto(belegnummer="RE-2026-002"))
            result = service.alle_belege(session, suchtext="RE-2026-001")
        assert len(result) == 1

    def test_inaktive_nicht_angezeigt(self, db, service):
        with db.session() as session:
            r = service.beleg_erstellen(session, _dto())
            service.beleg_deaktivieren(session, r.data.id)
            belege = service.alle_belege(session, nur_aktive=True)
        assert len(belege) == 0

    def test_inaktive_einschliessbar(self, db, service):
        with db.session() as session:
            r = service.beleg_erstellen(session, _dto())
            service.beleg_deaktivieren(session, r.data.id)
            belege = service.alle_belege(session, nur_aktive=False)
        assert len(belege) == 1


# ---------------------------------------------------------------------------
# Aktualisieren
# ---------------------------------------------------------------------------

class TestAktualisieren:
    def test_aktualisieren_erfolgreich(self, db, service):
        with db.session() as session:
            r = service.beleg_erstellen(session, _dto())
            beleg_id = r.data.id

        with db.session() as session:
            neues_dto = _dto(lieferant="Neuer Lieferant", betrag_netto="200.00")
            result = service.beleg_aktualisieren(session, beleg_id, neues_dto)

        assert result.success
        assert result.data.lieferant == "Neuer Lieferant"
        assert result.data.betrag_netto == Decimal("200.00")

    def test_aktualisieren_betraege_neu_berechnet(self, db, service):
        with db.session() as session:
            r = service.beleg_erstellen(session, _dto(betrag_netto="100.00"))
            beleg_id = r.data.id

        with db.session() as session:
            neues_dto = _dto(betrag_netto="200.00", mwst_satz="19")
            service.beleg_aktualisieren(session, beleg_id, neues_dto)
            beleg = service.beleg_nach_id(session, beleg_id)

        assert beleg.betrag_brutto == Decimal("238.00")

    def test_aktualisieren_nicht_gefunden(self, db, service):
        with db.session() as session:
            result = service.beleg_aktualisieren(session, 99999, _dto())
        assert not result.success

    def test_aktualisieren_audit_log(self, db, service):
        with db.session() as session:
            r = service.beleg_erstellen(session, _dto())
            beleg_id = r.data.id

        with db.session() as session:
            service.beleg_aktualisieren(session, beleg_id, _dto(lieferant="Neu"))

        with db.session() as session:
            logs = session.query(AuditLog).filter(AuditLog.record_id == beleg_id).all()
        actions = [l.action for l in logs]
        assert any("GEAENDERT" in a for a in actions)


# ---------------------------------------------------------------------------
# Zahlungsstatus
# ---------------------------------------------------------------------------

class TestZahlungsstatus:
    def test_offen_auf_bezahlt(self, db, service):
        with db.session() as session:
            r = service.beleg_erstellen(session, _dto())
            result = service.zahlungsstatus_setzen(
                session, r.data.id, Zahlungsstatus.BEZAHLT
            )
        assert result.success

        with db.session() as session:
            beleg = service.beleg_nach_id(session, r.data.id)
        assert beleg.zahlungsstatus == Zahlungsstatus.BEZAHLT

    def test_bezahlt_auf_offen(self, db, service):
        with db.session() as session:
            r = service.beleg_erstellen(
                session, _dto(zahlungsstatus=Zahlungsstatus.BEZAHLT)
            )
            result = service.zahlungsstatus_setzen(
                session, r.data.id, Zahlungsstatus.OFFEN
            )
        assert result.success

    def test_gleicher_status_kein_fehler(self, db, service):
        with db.session() as session:
            r = service.beleg_erstellen(session, _dto())
            result = service.zahlungsstatus_setzen(
                session, r.data.id, Zahlungsstatus.OFFEN
            )
        assert result.success

    def test_nicht_gefunden(self, db, service):
        with db.session() as session:
            result = service.zahlungsstatus_setzen(
                session, 99999, Zahlungsstatus.BEZAHLT
            )
        assert not result.success

    def test_audit_log_bei_statuswechsel(self, db, service):
        with db.session() as session:
            r = service.beleg_erstellen(session, _dto())
            beleg_id = r.data.id
        with db.session() as session:
            service.zahlungsstatus_setzen(session, beleg_id, Zahlungsstatus.BEZAHLT)
        with db.session() as session:
            logs = session.query(AuditLog).filter(AuditLog.record_id == beleg_id).all()
        assert any("STATUS" in l.action for l in logs)


# ---------------------------------------------------------------------------
# Soft-Delete
# ---------------------------------------------------------------------------

class TestDeaktivieren:
    def test_deaktivieren_erfolgreich(self, db, service):
        with db.session() as session:
            r = service.beleg_erstellen(session, _dto())
            result = service.beleg_deaktivieren(session, r.data.id)
        assert result.success

    def test_doppelt_deaktivieren_fehlschlag(self, db, service):
        with db.session() as session:
            r = service.beleg_erstellen(session, _dto())
            service.beleg_deaktivieren(session, r.data.id)
            result = service.beleg_deaktivieren(session, r.data.id)
        assert not result.success

    def test_deaktivieren_nicht_gefunden(self, db, service):
        with db.session() as session:
            result = service.beleg_deaktivieren(session, 99999)
        assert not result.success

    def test_audit_log_deaktivierung(self, db, service):
        with db.session() as session:
            r = service.beleg_erstellen(session, _dto())
            beleg_id = r.data.id
        with db.session() as session:
            service.beleg_deaktivieren(session, beleg_id)
        with db.session() as session:
            logs = session.query(AuditLog).filter(AuditLog.record_id == beleg_id).all()
        assert any("DEAKTIVIERT" in l.action for l in logs)


# ---------------------------------------------------------------------------
# Statistik
# ---------------------------------------------------------------------------

class TestStatistik:
    def test_leere_statistik(self, db, service):
        with db.session() as session:
            stats = service.statistik(session)
        assert stats["gesamt"] == 0
        assert stats["offen"] == 0
        assert stats["bezahlt"] == 0
        assert stats["summe_netto"] == Decimal("0.00")
        assert stats["summe_brutto"] == Decimal("0.00")

    def test_statistik_mit_belegen(self, db, service):
        with db.session() as session:
            service.beleg_erstellen(session, _dto("A", betrag_netto="100", belegnummer="001"))
            r = service.beleg_erstellen(session, _dto("B", betrag_netto="200", belegnummer="002"))
            service.zahlungsstatus_setzen(session, r.data.id, Zahlungsstatus.BEZAHLT)
            stats = service.statistik(session)

        assert stats["gesamt"] == 2
        assert stats["offen"] == 1
        assert stats["bezahlt"] == 1

    def test_statistik_ignoriert_inaktive(self, db, service):
        with db.session() as session:
            r = service.beleg_erstellen(session, _dto())
            beleg_id = r.data.id
        with db.session() as session:
            service.beleg_deaktivieren(session, beleg_id)
        with db.session() as session:
            stats = service.statistik(session)
        assert stats["gesamt"] == 0

    def test_statistik_summen(self, db, service):
        with db.session() as session:
            service.beleg_erstellen(session, _dto(betrag_netto="100", belegnummer="001"))
            service.beleg_erstellen(session, _dto(betrag_netto="200", belegnummer="002"))
            stats = service.statistik(session)

        assert stats["summe_netto"] == Decimal("300.00")
        assert stats["summe_brutto"] == Decimal("357.00")  # 300 + 19% = 357


# ---------------------------------------------------------------------------
# BelegKategorie
# ---------------------------------------------------------------------------

class TestBelegKategorie:
    def test_defaults_vorhanden(self):
        defaults = BelegKategorie.DEFAULTS
        assert "Material" in defaults
        assert "Kraftstoff" in defaults
        assert "Sonstiges" in defaults

    def test_alle_gibt_defaults_zurueck(self):
        # Ohne konfigurierten Pfad: nur Defaults
        kategorien = BelegKategorie.alle()
        for d in BelegKategorie.DEFAULTS:
            assert d in kategorien
