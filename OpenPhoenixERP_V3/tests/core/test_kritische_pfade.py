"""
tests/core/test_kritische_pfade.py – Tests für kritische Geschäftspfade
========================================================================
Abdeckung: Teilzahlungen, Skonto, Teilgutschriften, Storno nach Zahlung,
Edge Cases bei Beträgen, Lagerbestandsintegrität, Audit-Trail-Vollständigkeit.
"""

import pytest
from decimal import Decimal
from datetime import datetime, timedelta, date

from core.db.engine import DatabaseManager, Base
from core.models import (
    Kunde, Rechnung, Rechnungsposten, Artikel,
    LagerBewegung, AuditLog,
)
from core.services.rechnungen_service import (
    RechnungsService, RechnungDTO, PostenDTO, RechnungStatus,
)
from core.services.lager_service import LagerService, Buchungsart
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
def svc():
    return RechnungsService()


@pytest.fixture
def lager_svc():
    return LagerService()


@pytest.fixture
def kunde(db):
    with db.session() as s:
        k = Kunde(name="Testfirma", vorname="Max", zifferncode=2001)
        s.add(k)
    with db.session() as s:
        return s.query(Kunde).filter_by(zifferncode=2001).first().id


@pytest.fixture
def artikel(db):
    with db.session() as s:
        a = Artikel(
            artikelnummer="W-100", beschreibung="Widget",
            einheit="Stück", einzelpreis_netto=Decimal("50.00"),
            verfuegbar=Decimal("200"),
        )
        s.add(a)
    return "W-100"


def _dto(kunde_id, nr, posten_liste):
    """Hilfsfunktion: erzeugt ein Rechnungs-DTO."""
    return RechnungDTO(
        id=None, kunde_id=kunde_id,
        rechnungsnummer=nr,
        rechnungsdatum="01.03.2026",
        faelligkeitsdatum="15.03.2026",
        mwst_prozent=Decimal("19.00"),
        summe_netto=Decimal("0"), summe_mwst=Decimal("0"),
        summe_brutto=Decimal("0"), mahngebuehren=Decimal("0"),
        offener_betrag=Decimal("0"),
        status=RechnungStatus.ENTWURF,
        bemerkung="", is_finalized=False,
        posten=posten_liste,
    )


def _posten(nr="", beschreibung="Dienstleistung", menge=1, preis=100):
    """Hilfsfunktion: erzeugt einen PostenDTO."""
    m = Decimal(str(menge))
    p = Decimal(str(preis))
    return PostenDTO(
        id=None, rechnung_id=None, position=1,
        artikelnummer=nr, beschreibung=beschreibung,
        menge=m, einheit="Stück",
        einzelpreis_netto=p,
        gesamtpreis_netto=m * p,
    )


def _erstelle_finalisierte_rechnung(db, svc, kunde_id, rechnungsnr, posten_liste):
    """Erstellt und finalisiert eine Rechnung. Gibt die Rechnung-ID zurück."""
    dto = _dto(kunde_id, rechnungsnr, posten_liste)
    with db.session() as s:
        r = svc.entwurf_erstellen(s, kunde_id, dto)
    assert r.success, f"Entwurf fehlgeschlagen: {r.message}"
    with db.session() as s:
        r2 = svc.finalisieren(s, r.data.id)
    assert r2.success, f"Finalisierung fehlgeschlagen: {r2.message}"
    return r.data.id


# ===========================================================================
# TEILZAHLUNGEN
# ===========================================================================

class TestTeilzahlungen:
    """Kompletter Lebenszyklus: Teilzahlungen bis zur vollständigen Begleichung."""

    def test_einfache_teilzahlung(self, db, svc, kunde):
        rid = _erstelle_finalisierte_rechnung(
            db, svc, kunde, "TZ-001", [_posten(preis=100)]
        )
        # Brutto = 119 €
        with db.session() as s:
            r = svc.teilzahlung_buchen(s, rid, Decimal("50.00"))
        assert r.success
        with db.session() as s:
            dto = svc.nach_id(s, rid)
        assert dto.offener_betrag == Decimal("69.00")
        assert dto.status == RechnungStatus.OFFEN

    def test_mehrere_teilzahlungen_bis_bezahlt(self, db, svc, kunde):
        rid = _erstelle_finalisierte_rechnung(
            db, svc, kunde, "TZ-002", [_posten(preis=100)]
        )
        # Brutto = 119 €
        with db.session() as s:
            svc.teilzahlung_buchen(s, rid, Decimal("50.00"))
        with db.session() as s:
            svc.teilzahlung_buchen(s, rid, Decimal("50.00"))
        with db.session() as s:
            r = svc.teilzahlung_buchen(s, rid, Decimal("19.00"))
        assert r.success
        with db.session() as s:
            dto = svc.nach_id(s, rid)
        assert dto.offener_betrag == Decimal("0")
        assert dto.status == RechnungStatus.BEZAHLT

    def test_ueberzahlung_abgelehnt(self, db, svc, kunde):
        rid = _erstelle_finalisierte_rechnung(
            db, svc, kunde, "TZ-003", [_posten(preis=100)]
        )
        with db.session() as s:
            r = svc.teilzahlung_buchen(s, rid, Decimal("999.99"))
        assert not r.success
        assert "übersteigt" in r.message.lower()

    def test_null_betrag_abgelehnt(self, db, svc, kunde):
        rid = _erstelle_finalisierte_rechnung(
            db, svc, kunde, "TZ-004", [_posten(preis=100)]
        )
        with db.session() as s:
            r = svc.teilzahlung_buchen(s, rid, Decimal("0"))
        assert not r.success

    def test_negativer_betrag_abgelehnt(self, db, svc, kunde):
        rid = _erstelle_finalisierte_rechnung(
            db, svc, kunde, "TZ-005", [_posten(preis=100)]
        )
        with db.session() as s:
            r = svc.teilzahlung_buchen(s, rid, Decimal("-10"))
        assert not r.success

    def test_auf_entwurf_nicht_buchbar(self, db, svc, kunde):
        dto = _dto(kunde, "TZ-006", [_posten(preis=100)])
        with db.session() as s:
            r = svc.entwurf_erstellen(s, kunde, dto)
        with db.session() as s:
            r2 = svc.teilzahlung_buchen(s, r.data.id, Decimal("10"))
        assert not r2.success

    def test_auf_storniert_nicht_buchbar(self, db, svc, kunde):
        rid = _erstelle_finalisierte_rechnung(
            db, svc, kunde, "TZ-007", [_posten(preis=100)]
        )
        with db.session() as s:
            svc.stornieren(s, rid)
        with db.session() as s:
            r = svc.teilzahlung_buchen(s, rid, Decimal("10"))
        assert not r.success

    def test_auf_gutschrift_nicht_buchbar(self, db, svc, kunde):
        rid = _erstelle_finalisierte_rechnung(
            db, svc, kunde, "TZ-008", [_posten(preis=100)]
        )
        with db.session() as s:
            r = svc.stornieren(s, rid)
        gut_id = r.data["gutschrift_id"]
        with db.session() as s:
            r2 = svc.teilzahlung_buchen(s, gut_id, Decimal("10"))
        assert not r2.success

    def test_teilzahlung_audit_log(self, db, svc, kunde):
        rid = _erstelle_finalisierte_rechnung(
            db, svc, kunde, "TZ-009", [_posten(preis=100)]
        )
        with db.session() as s:
            svc.teilzahlung_buchen(s, rid, Decimal("25.00"))
        with db.session() as s:
            entry = s.query(AuditLog).filter_by(
                action=AuditAction.TEILZAHLUNG_GEBUCHT
            ).first()
        assert entry is not None
        assert "25.00" in entry.details


# ===========================================================================
# SKONTO / RABATT
# ===========================================================================

class TestSkonto:
    """Skonto-Gewährung auf finalisierte Rechnungen."""

    def test_skonto_prozent(self, db, svc, kunde):
        rid = _erstelle_finalisierte_rechnung(
            db, svc, kunde, "SK-001", [_posten(preis=100)]
        )
        # Brutto = 119 €, 3% Skonto = 3.57 €
        with db.session() as s:
            r = svc.skonto_gewaehren(s, rid, prozent=Decimal("3"))
        assert r.success
        with db.session() as s:
            dto = svc.nach_id(s, rid)
        assert dto.offener_betrag == Decimal("115.43")

    def test_skonto_betrag(self, db, svc, kunde):
        rid = _erstelle_finalisierte_rechnung(
            db, svc, kunde, "SK-002", [_posten(preis=100)]
        )
        with db.session() as s:
            r = svc.skonto_gewaehren(s, rid, betrag=Decimal("19.00"))
        assert r.success
        with db.session() as s:
            dto = svc.nach_id(s, rid)
        assert dto.offener_betrag == Decimal("100.00")

    def test_skonto_uebersteigt_offenen_betrag(self, db, svc, kunde):
        rid = _erstelle_finalisierte_rechnung(
            db, svc, kunde, "SK-003", [_posten(preis=100)]
        )
        with db.session() as s:
            r = svc.skonto_gewaehren(s, rid, betrag=Decimal("999"))
        assert not r.success
        assert "übersteigt" in r.message.lower()

    def test_skonto_auf_bezahlt_abgelehnt(self, db, svc, kunde):
        rid = _erstelle_finalisierte_rechnung(
            db, svc, kunde, "SK-004", [_posten(preis=100)]
        )
        with db.session() as s:
            svc.status_aendern(s, rid, RechnungStatus.BEZAHLT)
        with db.session() as s:
            r = svc.skonto_gewaehren(s, rid, prozent=Decimal("2"))
        assert not r.success

    def test_skonto_auf_storniert_abgelehnt(self, db, svc, kunde):
        rid = _erstelle_finalisierte_rechnung(
            db, svc, kunde, "SK-005", [_posten(preis=100)]
        )
        with db.session() as s:
            svc.stornieren(s, rid)
        with db.session() as s:
            r = svc.skonto_gewaehren(s, rid, prozent=Decimal("2"))
        assert not r.success

    def test_skonto_null_prozent_abgelehnt(self, db, svc, kunde):
        rid = _erstelle_finalisierte_rechnung(
            db, svc, kunde, "SK-006", [_posten(preis=100)]
        )
        with db.session() as s:
            r = svc.skonto_gewaehren(s, rid, prozent=Decimal("0"))
        assert not r.success

    def test_skonto_dann_zahlung_bis_bezahlt(self, db, svc, kunde):
        """Kombination: Skonto + Teilzahlung → vollständig bezahlt."""
        rid = _erstelle_finalisierte_rechnung(
            db, svc, kunde, "SK-007", [_posten(preis=100)]
        )
        # Brutto 119 €, 3% Skonto → 115.43 offen
        with db.session() as s:
            svc.skonto_gewaehren(s, rid, prozent=Decimal("3"))
        with db.session() as s:
            dto = svc.nach_id(s, rid)
            rest = dto.offener_betrag
        with db.session() as s:
            r = svc.teilzahlung_buchen(s, rid, rest)
        assert r.success
        with db.session() as s:
            dto = svc.nach_id(s, rid)
        assert dto.status == RechnungStatus.BEZAHLT
        assert dto.offener_betrag == Decimal("0")

    def test_skonto_audit_log(self, db, svc, kunde):
        rid = _erstelle_finalisierte_rechnung(
            db, svc, kunde, "SK-008", [_posten(preis=100)]
        )
        with db.session() as s:
            svc.skonto_gewaehren(s, rid, prozent=Decimal("5"))
        with db.session() as s:
            entry = s.query(AuditLog).filter_by(
                action=AuditAction.SKONTO_GEWAEHRT
            ).first()
        assert entry is not None


# ===========================================================================
# TEILGUTSCHRIFTEN
# ===========================================================================

class TestTeilgutschrift:
    """Teil-Gutschriften: GoBD-konforme Korrekturbelege."""

    def test_teil_gutschrift_erstellt(self, db, svc, kunde):
        rid = _erstelle_finalisierte_rechnung(
            db, svc, kunde, "TG-001", [_posten(preis=100)]
        )
        with db.session() as s:
            r = svc.teilgutschrift_erstellen(
                s, rid, "Teilrücknahme", Decimal("20"), Decimal("19"),
                grund="Kulanz",
            )
        assert r.success
        assert r.data["gutschrift_nummer"].startswith("S-")

    def test_teil_gutschrift_reduziert_offenen_betrag(self, db, svc, kunde):
        rid = _erstelle_finalisierte_rechnung(
            db, svc, kunde, "TG-002", [_posten(preis=100)]
        )
        # Brutto 119 €, Gutschrift 23.80 € (netto 20 + 19% MwSt)
        with db.session() as s:
            svc.teilgutschrift_erstellen(
                s, rid, "Korrektur", Decimal("20"), Decimal("19")
            )
        with db.session() as s:
            dto = svc.nach_id(s, rid)
        assert dto.offener_betrag == Decimal("95.20")  # 119.00 - 23.80

    def test_teil_gutschrift_uebersteigt_offenen_betrag(self, db, svc, kunde):
        rid = _erstelle_finalisierte_rechnung(
            db, svc, kunde, "TG-003", [_posten(preis=100)]
        )
        with db.session() as s:
            r = svc.teilgutschrift_erstellen(
                s, rid, "Zu viel", Decimal("500"), Decimal("19")
            )
        assert not r.success
        assert "übersteigt" in r.message.lower()

    def test_teil_gutschrift_auf_storniert(self, db, svc, kunde):
        rid = _erstelle_finalisierte_rechnung(
            db, svc, kunde, "TG-004", [_posten(preis=100)]
        )
        with db.session() as s:
            svc.stornieren(s, rid)
        with db.session() as s:
            r = svc.teilgutschrift_erstellen(
                s, rid, "Test", Decimal("10"), Decimal("19")
            )
        assert not r.success

    def test_teil_gutschrift_negative_betraege(self, db, svc, kunde):
        """Die erzeugte Gutschrift muss negative Beträge haben."""
        rid = _erstelle_finalisierte_rechnung(
            db, svc, kunde, "TG-005", [_posten(preis=100)]
        )
        with db.session() as s:
            r = svc.teilgutschrift_erstellen(
                s, rid, "Rückgabe", Decimal("30"), Decimal("19")
            )
        gut_nr = r.data["gutschrift_nummer"]
        with db.session() as s:
            gut = s.query(Rechnung).filter_by(rechnungsnummer=gut_nr).first()
        assert gut.summe_netto < 0
        assert gut.summe_brutto < 0
        assert gut.status == RechnungStatus.GUTSCHRIFT

    def test_teil_gutschrift_audit_log(self, db, svc, kunde):
        rid = _erstelle_finalisierte_rechnung(
            db, svc, kunde, "TG-006", [_posten(preis=100)]
        )
        with db.session() as s:
            svc.teilgutschrift_erstellen(
                s, rid, "Audit-Test", Decimal("10"), Decimal("19")
            )
        with db.session() as s:
            entry = s.query(AuditLog).filter_by(
                action=AuditAction.GUTSCHRIFT_ERSTELLT
            ).first()
        assert entry is not None


# ===========================================================================
# STORNO NACH ZAHLUNG
# ===========================================================================

class TestStornoNachZahlung:
    """Storno-Verhalten wenn bereits Zahlungen/Skonto gebucht wurden."""

    def test_storno_nach_teilzahlung(self, db, svc, kunde):
        """Storno nach Teilzahlung: Gutschrift deckt vollen Bruttobetrag."""
        rid = _erstelle_finalisierte_rechnung(
            db, svc, kunde, "SZ-001", [_posten(preis=100)]
        )
        with db.session() as s:
            svc.teilzahlung_buchen(s, rid, Decimal("50.00"))
        with db.session() as s:
            r = svc.stornieren(s, rid, "Storno nach Teilzahlung")
        assert r.success
        # Original auf Storniert
        with db.session() as s:
            orig = svc.nach_id(s, rid)
        assert orig.status == RechnungStatus.STORNIERT
        assert orig.offener_betrag == Decimal("0")
        # Gutschrift = voller negativer Brutto
        gut_id = r.data["gutschrift_id"]
        with db.session() as s:
            gut = svc.nach_id(s, gut_id)
        assert gut.summe_brutto == Decimal("-119.00")

    def test_storno_nach_vollstaendiger_bezahlung(self, db, svc, kunde):
        """Storno einer bereits bezahlten Rechnung muss funktionieren."""
        rid = _erstelle_finalisierte_rechnung(
            db, svc, kunde, "SZ-002", [_posten(preis=100)]
        )
        with db.session() as s:
            svc.teilzahlung_buchen(s, rid, Decimal("119.00"))
        with db.session() as s:
            dto = svc.nach_id(s, rid)
        assert dto.status == RechnungStatus.BEZAHLT

        with db.session() as s:
            r = svc.stornieren(s, rid, "Vollständig bezahlt, trotzdem storniert")
        assert r.success

    def test_storno_nach_skonto(self, db, svc, kunde):
        """Storno nach Skonto-Gewährung."""
        rid = _erstelle_finalisierte_rechnung(
            db, svc, kunde, "SZ-003", [_posten(preis=100)]
        )
        with db.session() as s:
            svc.skonto_gewaehren(s, rid, prozent=Decimal("3"))
        with db.session() as s:
            r = svc.stornieren(s, rid)
        assert r.success
        # Gutschrift enthält Hinweis auf Skonto
        gut_id = r.data["gutschrift_id"]
        with db.session() as s:
            gut = svc.nach_id(s, gut_id)
        assert "Hinweis" in (gut.bemerkung or "")


# ===========================================================================
# LAGERBESTANDSINTEGRITÄT
# ===========================================================================

class TestLagerIntegritaet:
    """Lagerbestand-Konsistenz über Finalisierung + Storno hinweg."""

    def test_finalisierung_bucht_lager_ab(self, db, svc, kunde, artikel):
        rid = _erstelle_finalisierte_rechnung(
            db, svc, kunde, "LI-001", [_posten(nr="W-100", menge=10, preis=50)]
        )
        with db.session() as s:
            a = s.query(Artikel).filter_by(artikelnummer="W-100").first()
        assert a.verfuegbar == Decimal("190")  # 200 - 10

    def test_storno_bucht_lager_zurueck(self, db, svc, kunde, artikel):
        rid = _erstelle_finalisierte_rechnung(
            db, svc, kunde, "LI-002", [_posten(nr="W-100", menge=25, preis=50)]
        )
        with db.session() as s:
            svc.stornieren(s, rid)
        with db.session() as s:
            a = s.query(Artikel).filter_by(artikelnummer="W-100").first()
        assert a.verfuegbar == Decimal("200")  # Zurück auf Ausgang

    def test_lagerbewegungen_lueckenlos(self, db, svc, kunde, artikel):
        """Jede Bestandsänderung muss als LagerBewegung protokolliert sein."""
        rid = _erstelle_finalisierte_rechnung(
            db, svc, kunde, "LI-003", [_posten(nr="W-100", menge=5, preis=50)]
        )
        with db.session() as s:
            svc.stornieren(s, rid)
        with db.session() as s:
            bewegungen = (
                s.query(LagerBewegung)
                .filter_by(artikelnummer="W-100")
                .order_by(LagerBewegung.id)
                .all()
            )
        # Anfangsbestand (200) + Rechnungsabgang (-5) + Stornoeingang (+5)
        assert len(bewegungen) >= 2
        abgang = [b for b in bewegungen if b.buchungsart == "Rechnungsabgang"]
        eingang = [b for b in bewegungen if b.buchungsart == "Stornoeingang"]
        assert len(abgang) == 1
        assert len(eingang) == 1
        assert abs(abgang[0].menge) == Decimal("5")
        assert abs(eingang[0].menge) == Decimal("5")

    def test_mehrere_posten_lager(self, db, svc, lager_svc, kunde):
        """Rechnung mit mehreren Artikelposten bucht korrekt ab."""
        with db.session() as s:
            for nr, bestand in [("A-01", 50), ("A-02", 30)]:
                s.add(Artikel(
                    artikelnummer=nr, beschreibung=f"Artikel {nr}",
                    einheit="Stück", einzelpreis_netto=Decimal("10"),
                    verfuegbar=Decimal(str(bestand)),
                ))

        posten = [
            PostenDTO(None, None, 1, "A-01", "Art 1", Decimal("3"), "Stück",
                      Decimal("10"), Decimal("30")),
            PostenDTO(None, None, 2, "A-02", "Art 2", Decimal("7"), "Stück",
                      Decimal("10"), Decimal("70")),
        ]
        rid = _erstelle_finalisierte_rechnung(
            db, svc, kunde, "LI-004", posten
        )
        with db.session() as s:
            a1 = s.query(Artikel).filter_by(artikelnummer="A-01").first()
            a2 = s.query(Artikel).filter_by(artikelnummer="A-02").first()
        assert a1.verfuegbar == Decimal("47")  # 50 - 3
        assert a2.verfuegbar == Decimal("23")  # 30 - 7


# ===========================================================================
# GOBD-KONFORMITÄT
# ===========================================================================

class TestGoBDKonformitaet:
    """GoBD-relevante Anforderungen: Unveränderbarkeit, Audit-Trail."""

    def test_finalisierte_rechnung_nicht_editierbar(self, db, svc, kunde):
        rid = _erstelle_finalisierte_rechnung(
            db, svc, kunde, "GB-001", [_posten(preis=100)]
        )
        dto = _dto(kunde, "GB-001", [_posten(preis=200)])
        with db.session() as s:
            r = svc.entwurf_aktualisieren(s, rid, dto)
        assert not r.success

    def test_finalisierte_rechnung_nicht_loeschbar(self, db, svc, kunde):
        rid = _erstelle_finalisierte_rechnung(
            db, svc, kunde, "GB-002", [_posten(preis=100)]
        )
        with db.session() as s:
            r = svc.entwurf_loeschen(s, rid)
        assert not r.success
        assert "GoBD" in r.message

    def test_gutschrift_nicht_stornierbar(self, db, svc, kunde):
        rid = _erstelle_finalisierte_rechnung(
            db, svc, kunde, "GB-003", [_posten(preis=100)]
        )
        with db.session() as s:
            r = svc.stornieren(s, rid)
        gut_id = r.data["gutschrift_id"]
        with db.session() as s:
            r2 = svc.stornieren(s, gut_id)
        assert not r2.success

    def test_storno_nummer_fortlaufend(self, db, svc, kunde):
        """Storno-Nummern müssen fortlaufend und einzigartig sein."""
        ids = []
        for i in range(3):
            rid = _erstelle_finalisierte_rechnung(
                db, svc, kunde, f"GB-1{i}", [_posten(preis=50)]
            )
            ids.append(rid)

        nummern = []
        for rid in ids:
            with db.session() as s:
                r = svc.stornieren(s, rid)
            assert r.success
            nummern.append(r.data["gutschrift_nummer"])

        # Alle unterschiedlich
        assert len(set(nummern)) == 3

    def test_vollstaendiger_audit_trail(self, db, svc, kunde):
        """Der gesamte Lebenszyklus einer Rechnung muss im Audit-Log stehen."""
        rid = _erstelle_finalisierte_rechnung(
            db, svc, kunde, "GB-004", [_posten(preis=100)]
        )
        with db.session() as s:
            svc.teilzahlung_buchen(s, rid, Decimal("50"))
        with db.session() as s:
            svc.stornieren(s, rid)

        with db.session() as s:
            actions = [
                log.action for log in
                s.query(AuditLog).order_by(AuditLog.id).all()
            ]
        assert AuditAction.RECHNUNG_ENTWURF_ERSTELLT in actions
        assert AuditAction.RECHNUNG_FINALISIERT in actions
        assert AuditAction.TEILZAHLUNG_GEBUCHT in actions
        assert AuditAction.RECHNUNG_STORNIERT in actions
        assert AuditAction.GUTSCHRIFT_ERSTELLT in actions


# ===========================================================================
# EDGE CASES
# ===========================================================================

class TestEdgeCases:
    """Grenzfälle und Cent-Genauigkeit."""

    def test_cent_genauigkeit(self, db, svc, kunde):
        """Beträge mit ungeraden Cent-Werten werden korrekt gerundet."""
        posten = [_posten(beschreibung="0.01-Test", menge=3, preis="33.33")]
        rid = _erstelle_finalisierte_rechnung(
            db, svc, kunde, "EC-001", posten
        )
        with db.session() as s:
            dto = svc.nach_id(s, rid)
        assert dto.summe_netto == Decimal("99.99")
        brutto = Decimal("99.99") + (Decimal("99.99") * Decimal("19") / Decimal("100")).quantize(Decimal("0.01"))
        assert dto.summe_brutto == brutto

    def test_hoher_betrag(self, db, svc, kunde):
        """Sehr hohe Beträge werden korrekt verarbeitet."""
        posten = [_posten(beschreibung="Großauftrag", menge=1, preis="999999.99")]
        rid = _erstelle_finalisierte_rechnung(
            db, svc, kunde, "EC-002", posten
        )
        with db.session() as s:
            dto = svc.nach_id(s, rid)
        assert dto.summe_netto == Decimal("999999.99")
        assert dto.summe_brutto > Decimal("1000000")

    def test_exakte_restbetrag_zahlung(self, db, svc, kunde):
        """Exakter Restbetrag → Status BEZAHLT."""
        rid = _erstelle_finalisierte_rechnung(
            db, svc, kunde, "EC-003", [_posten(preis=100)]
        )
        with db.session() as s:
            dto = svc.nach_id(s, rid)
            offen = dto.offener_betrag
        with db.session() as s:
            r = svc.teilzahlung_buchen(s, rid, offen)
        assert r.success
        with db.session() as s:
            dto = svc.nach_id(s, rid)
        assert dto.status == RechnungStatus.BEZAHLT
        assert dto.offener_betrag == Decimal("0")

    def test_gutschrift_dann_zahlung_gleich_bezahlt(self, db, svc, kunde):
        """Teilgutschrift + Zahlung des Rests → BEZAHLT."""
        rid = _erstelle_finalisierte_rechnung(
            db, svc, kunde, "EC-004", [_posten(preis=100)]
        )
        # Gutschrift über 20€ netto = 23.80€ brutto
        with db.session() as s:
            svc.teilgutschrift_erstellen(
                s, rid, "Rückgabe", Decimal("20"), Decimal("19")
            )
        with db.session() as s:
            dto = svc.nach_id(s, rid)
            rest = dto.offener_betrag
        with db.session() as s:
            svc.teilzahlung_buchen(s, rid, rest)
        with db.session() as s:
            dto = svc.nach_id(s, rid)
        assert dto.status == RechnungStatus.BEZAHLT
        assert dto.offener_betrag == Decimal("0")

    def test_posten_ohne_artikelnummer(self, db, svc, kunde):
        """Rechnungen ohne Artikelnummer (Freitext) dürfen keine Lagerbuchung auslösen."""
        rid = _erstelle_finalisierte_rechnung(
            db, svc, kunde, "EC-005",
            [_posten(nr="", beschreibung="Freie Leistung", menge=1, preis=500)]
        )
        with db.session() as s:
            bewegungen = s.query(LagerBewegung).all()
        # Keine Lagerbewegung für Freitext-Posten
        assert len(bewegungen) == 0
