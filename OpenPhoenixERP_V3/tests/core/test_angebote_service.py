"""
tests/core/test_angebote_service.py – Tests für den AngebotsService
====================================================================
Abdeckung: Angebotsnummern, CRUD, Statusübergänge, Summenberechnung,
Validierung, Duplikaterkennung, Audit-Logging.
"""

import pytest
from decimal import Decimal
from datetime import datetime

from core.db.engine import DatabaseManager
from core.models import Kunde, Angebot, AngebotsPosten, AuditLog
from core.services.angebote_service import (
    AngebotsService, AngebotDTO, AngebotsPostenDTO,
    AngebotStatus, berechne_summen, berechne_gesamtpreis,
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
    return AngebotsService()


@pytest.fixture
def kunde(db):
    with db.session() as session:
        k = Kunde(zifferncode=1001, name="Mustermann", vorname="Max", is_active=True)
        session.add(k)
        session.flush()
        kid = k.id
    return kid


def _posten(
    beschreibung: str = "Testleistung",
    menge: str = "1",
    einzelpreis: str = "100.00",
) -> AngebotsPostenDTO:
    menge_d = Decimal(menge)
    preis_d = Decimal(einzelpreis)
    return AngebotsPostenDTO(
        id=None, angebot_id=None,
        position=1,
        artikelnummer="",
        beschreibung=beschreibung,
        menge=menge_d,
        einheit="Stück",
        einzelpreis_netto=preis_d,
        gesamtpreis_netto=berechne_gesamtpreis(menge_d, preis_d),
    )


def _dto(
    kunde_id: int,
    nummer: str = "AG-2026-0001",
    status: str = AngebotStatus.ENTWURF,
    posten: list | None = None,
    mwst: str = "19",
) -> AngebotDTO:
    p = posten if posten is not None else [_posten()]
    netto, mwst_b, brutto = berechne_summen(p, Decimal(mwst))
    return AngebotDTO(
        id=None,
        kunde_id=kunde_id,
        angebotsnummer=nummer,
        angebotsdatum="01.04.2026",
        gueltig_bis="30.04.2026",
        mwst_prozent=Decimal(mwst),
        summe_netto=netto,
        summe_mwst=mwst_b,
        summe_brutto=brutto,
        status=status,
        bemerkung="",
        posten=p,
    )


# ---------------------------------------------------------------------------
# Summenberechnung
# ---------------------------------------------------------------------------

class TestSummenberechnung:
    def test_einfache_berechnung(self):
        p = [_posten(menge="2", einzelpreis="50.00")]
        netto, mwst, brutto = berechne_summen(p, Decimal("19"))
        assert netto == Decimal("100.00")
        assert mwst == Decimal("19.00")
        assert brutto == Decimal("119.00")

    def test_mehrere_posten(self):
        posten = [
            _posten(menge="3", einzelpreis="10.00"),
            _posten(menge="1", einzelpreis="50.00"),
        ]
        netto, mwst, brutto = berechne_summen(posten, Decimal("19"))
        assert netto == Decimal("80.00")
        assert mwst == Decimal("15.20")
        assert brutto == Decimal("95.20")

    def test_reduzierter_steuersatz(self):
        p = [_posten(menge="1", einzelpreis="100.00")]
        netto, mwst, brutto = berechne_summen(p, Decimal("7"))
        assert mwst == Decimal("7.00")
        assert brutto == Decimal("107.00")

    def test_null_steuersatz(self):
        p = [_posten(menge="1", einzelpreis="200.00")]
        netto, mwst, brutto = berechne_summen(p, Decimal("0"))
        assert mwst == Decimal("0.00")
        assert brutto == Decimal("200.00")

    def test_leere_posten_liste(self):
        netto, mwst, brutto = berechne_summen([], Decimal("19"))
        assert netto == Decimal("0.00")
        assert mwst == Decimal("0.00")
        assert brutto == Decimal("0.00")

    def test_gesamtpreis_posten(self):
        assert berechne_gesamtpreis(Decimal("3"), Decimal("10.00")) == Decimal("30.00")
        assert berechne_gesamtpreis(Decimal("0.5"), Decimal("10.00")) == Decimal("5.00")


# ---------------------------------------------------------------------------
# Angebotsnummern
# ---------------------------------------------------------------------------

class TestAngebotsnummer:
    def test_erste_nummer_im_jahr(self, db, service):
        with db.session() as session:
            nr = service.naechste_angebotsnummer(session, jahr=2026)
        assert nr == "AG-2026-0001"

    def test_fortlaufende_nummerierung(self, db, service, kunde):
        with db.session() as session:
            service.erstellen(session, kunde, _dto(kunde, "AG-2026-0001"))
            nr = service.naechste_angebotsnummer(session, jahr=2026)
        assert nr == "AG-2026-0002"

    def test_jahreswechsel(self, db, service, kunde):
        with db.session() as session:
            service.erstellen(session, kunde, _dto(kunde, "AG-2025-0099"))
            nr = service.naechste_angebotsnummer(session, jahr=2026)
        assert nr == "AG-2026-0001"

    def test_nummer_existiert(self, db, service, kunde):
        with db.session() as session:
            service.erstellen(session, kunde, _dto(kunde, "AG-2026-0001"))
            assert service.nummer_existiert(session, "AG-2026-0001") is True
            assert service.nummer_existiert(session, "AG-2026-0002") is False

    def test_format(self, db, service):
        with db.session() as session:
            for i in range(1, 10):
                nr = service.naechste_angebotsnummer(session, jahr=2026)
                assert nr.startswith("AG-2026-")
                assert len(nr.split("-")[-1]) == 4


# ---------------------------------------------------------------------------
# Erstellen
# ---------------------------------------------------------------------------

class TestErstellen:
    def test_erstellen_einfach(self, db, service, kunde):
        with db.session() as session:
            result = service.erstellen(session, kunde, _dto(kunde))
        assert result.success
        assert result.data is not None
        assert result.data.angebotsnummer == "AG-2026-0001"

    def test_erstellen_mit_posten(self, db, service, kunde):
        with db.session() as session:
            p = [_posten("Pos 1", "2", "50"), _posten("Pos 2", "1", "30")]
            result = service.erstellen(session, kunde, _dto(kunde, posten=p))
        assert result.success
        assert len(result.data.posten) == 2
        assert result.data.summe_netto == Decimal("130.00")

    def test_erstellen_summen_korrekt(self, db, service, kunde):
        with db.session() as session:
            p = [_posten(menge="10", einzelpreis="100.00")]
            result = service.erstellen(session, kunde, _dto(kunde, posten=p))
        assert result.data.summe_netto == Decimal("1000.00")
        assert result.data.summe_mwst == Decimal("190.00")
        assert result.data.summe_brutto == Decimal("1190.00")

    def test_erstellen_ohne_nummer_fehlschlag(self, db, service, kunde):
        with db.session() as session:
            dto = _dto(kunde, nummer="")
            result = service.erstellen(session, kunde, dto)
        assert not result.success
        assert "Angebotsnummer" in result.message

    def test_erstellen_ohne_datum_fehlschlag(self, db, service, kunde):
        with db.session() as session:
            dto = _dto(kunde)
            dto.angebotsdatum = ""
            result = service.erstellen(session, kunde, dto)
        assert not result.success

    def test_duplikatnummer_fehlschlag(self, db, service, kunde):
        with db.session() as session:
            service.erstellen(session, kunde, _dto(kunde, "AG-2026-0001"))
            result = service.erstellen(session, kunde, _dto(kunde, "AG-2026-0001"))
        assert not result.success
        assert "vergeben" in result.message

    def test_audit_log_erstellt(self, db, service, kunde):
        with db.session() as session:
            service.erstellen(session, kunde, _dto(kunde))
        with db.session() as session:
            logs = session.query(AuditLog).all()
        assert any("ANGEBOT" in l.action for l in logs)


# ---------------------------------------------------------------------------
# Lesen
# ---------------------------------------------------------------------------

class TestLesen:
    def test_alle_leer(self, db, service):
        with db.session() as session:
            angebote = service.alle(session)
        assert angebote == []

    def test_alle_nach_erstellen(self, db, service, kunde):
        with db.session() as session:
            service.erstellen(session, kunde, _dto(kunde, "AG-2026-0001"))
            service.erstellen(session, kunde, _dto(kunde, "AG-2026-0002"))
            angebote = service.alle(session)
        assert len(angebote) == 2

    def test_nach_id(self, db, service, kunde):
        with db.session() as session:
            result = service.erstellen(session, kunde, _dto(kunde))
            angebot_id = result.data.id
            dto = service.nach_id(session, angebot_id)
        assert dto is not None
        assert dto.angebotsnummer == "AG-2026-0001"

    def test_nach_id_nicht_gefunden(self, db, service):
        with db.session() as session:
            dto = service.nach_id(session, 99999)
        assert dto is None

    def test_filter_nach_kunde(self, db, service):
        with db.session() as session:
            k1 = Kunde(zifferncode=2001, name="A", vorname="X", is_active=True)
            k2 = Kunde(zifferncode=2002, name="B", vorname="Y", is_active=True)
            session.add_all([k1, k2])
            session.flush()
            service.erstellen(session, k1.id, _dto(k1.id, "AG-2026-0001"))
            service.erstellen(session, k2.id, _dto(k2.id, "AG-2026-0002"))
            result = service.alle(session, kunde_id=k1.id)
        assert len(result) == 1
        assert result[0].angebotsnummer == "AG-2026-0001"

    def test_filter_nach_status(self, db, service, kunde):
        with db.session() as session:
            service.erstellen(session, kunde, _dto(kunde, "AG-2026-0001", AngebotStatus.ENTWURF))
            service.erstellen(session, kunde, _dto(kunde, "AG-2026-0002", AngebotStatus.OFFEN))
            entwuerfe = service.alle(session, status_filter=[AngebotStatus.ENTWURF])
        assert len(entwuerfe) == 1

    def test_suchtext_filter(self, db, service, kunde):
        with db.session() as session:
            service.erstellen(session, kunde, _dto(kunde, "AG-2026-0001"))
            service.erstellen(session, kunde, _dto(kunde, "AG-2026-0002"))
            result = service.alle(session, suchtext="AG-2026-0001")
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Aktualisieren
# ---------------------------------------------------------------------------

class TestAktualisieren:
    def test_aktualisieren_erfolgreich(self, db, service, kunde):
        with db.session() as session:
            result = service.erstellen(session, kunde, _dto(kunde))
            angebot_id = result.data.id

        with db.session() as session:
            neues_dto = _dto(kunde, posten=[_posten(einzelpreis="200.00")])
            neues_dto.bemerkung = "Aktualisiert"
            result = service.aktualisieren(session, angebot_id, neues_dto)

        assert result.success
        assert result.data.summe_netto == Decimal("200.00")

    def test_aktualisieren_posten_ersetzt(self, db, service, kunde):
        with db.session() as session:
            p2 = [_posten("Alt1"), _posten("Alt2")]
            result = service.erstellen(session, kunde, _dto(kunde, posten=p2))
            angebot_id = result.data.id

        with db.session() as session:
            neu = _dto(kunde, posten=[_posten("Neu1")])
            service.aktualisieren(session, angebot_id, neu)

        with db.session() as session:
            dto = service.nach_id(session, angebot_id)
        assert len(dto.posten) == 1
        assert dto.posten[0].beschreibung == "Neu1"

    def test_aktualisieren_nicht_gefunden(self, db, service, kunde):
        with db.session() as session:
            result = service.aktualisieren(session, 99999, _dto(kunde))
        assert not result.success

    def test_aktualisieren_duplikatnummer_fehlschlag(self, db, service, kunde):
        with db.session() as session:
            service.erstellen(session, kunde, _dto(kunde, "AG-2026-0001"))
            r2 = service.erstellen(session, kunde, _dto(kunde, "AG-2026-0002"))
            angebot_id = r2.data.id
            neues_dto = _dto(kunde, "AG-2026-0001")  # Bereits vergeben
            result = service.aktualisieren(session, angebot_id, neues_dto)
        assert not result.success

    def test_eigene_nummer_erlaubt(self, db, service, kunde):
        """Update mit eigener Nummer (exclude_id) darf nicht als Duplikat gelten."""
        with db.session() as session:
            r = service.erstellen(session, kunde, _dto(kunde, "AG-2026-0001"))
            angebot_id = r.data.id
            dto = _dto(kunde, "AG-2026-0001")
            dto.bemerkung = "Neue Bemerkung"
            result = service.aktualisieren(session, angebot_id, dto)
        assert result.success


# ---------------------------------------------------------------------------
# Löschen
# ---------------------------------------------------------------------------

class TestLoeschen:
    def test_loeschen_erfolgreich(self, db, service, kunde):
        with db.session() as session:
            result = service.erstellen(session, kunde, _dto(kunde))
            angebot_id = result.data.id
            result = service.loeschen(session, angebot_id)
        assert result.success

        with db.session() as session:
            assert service.nach_id(session, angebot_id) is None

    def test_loeschen_entfernt_posten(self, db, service, kunde):
        with db.session() as session:
            r = service.erstellen(session, kunde, _dto(kunde, posten=[_posten(), _posten()]))
            angebot_id = r.data.id

        with db.session() as session:
            service.loeschen(session, angebot_id)

        with db.session() as session:
            posten = session.query(AngebotsPosten).filter_by(angebot_id=angebot_id).all()
        assert posten == []

    def test_loeschen_nicht_gefunden(self, db, service):
        with db.session() as session:
            result = service.loeschen(session, 99999)
        assert not result.success


# ---------------------------------------------------------------------------
# Statusübergänge
# ---------------------------------------------------------------------------

class TestStatus:
    def test_status_aendern_gueltig(self, db, service, kunde):
        with db.session() as session:
            r = service.erstellen(session, kunde, _dto(kunde))
            angebot_id = r.data.id
            result = service.status_aendern(session, angebot_id, AngebotStatus.OFFEN)
        assert result.success

        with db.session() as session:
            dto = service.nach_id(session, angebot_id)
        assert dto.status == AngebotStatus.OFFEN

    def test_alle_status_setzbar(self, db, service, kunde):
        with db.session() as session:
            r = service.erstellen(session, kunde, _dto(kunde))
            angebot_id = r.data.id
            for status in AngebotStatus.MANUELL_SETZBAR:
                result = service.status_aendern(session, angebot_id, status)
                assert result.success, f"Status {status} fehlgeschlagen"

    def test_ungültiger_status_fehlschlag(self, db, service, kunde):
        with db.session() as session:
            r = service.erstellen(session, kunde, _dto(kunde))
            result = service.status_aendern(session, r.data.id, "UNGÜLTIG")
        assert not result.success

    def test_status_angenommen(self, db, service, kunde):
        with db.session() as session:
            r = service.erstellen(session, kunde, _dto(kunde))
            service.status_aendern(session, r.data.id, AngebotStatus.ANGENOMMEN)
            dto = service.nach_id(session, r.data.id)
        assert dto.status == AngebotStatus.ANGENOMMEN

    def test_status_nicht_gefunden(self, db, service):
        with db.session() as session:
            result = service.status_aendern(session, 99999, AngebotStatus.OFFEN)
        assert not result.success

    def test_bemerkung_aktualisieren(self, db, service, kunde):
        with db.session() as session:
            r = service.erstellen(session, kunde, _dto(kunde))
            result = service.bemerkung_aktualisieren(session, r.data.id, "Neue Bemerkung")
        assert result.success

        with db.session() as session:
            dto = service.nach_id(session, r.data.id)
        assert dto.bemerkung == "Neue Bemerkung"
