"""
core/services/rechnungen_service.py – Business-Logik für Rechnungswesen
========================================================================
Vollständige GoBD-konforme Rechnungsverwaltung:
- Entwürfe erstellen, bearbeiten, löschen
- Finalisieren (unveränderbar nach Buchung)
- Status verwalten (inkl. automatischer Mahnstufenprüfung)
- Rechnungsnummern vergeben
- Lagerabbuchung bei Finalisierung
- Storno / Gutschrift
- Summen berechnen
"""

import logging
from dataclasses import dataclass, field
from core.services import ServiceResult
from datetime import datetime, date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from sqlalchemy import or_, func
from sqlalchemy.orm import Session

from core.models import Rechnung, Rechnungsposten, Artikel, Kunde, AuditLog, LagerBewegung
from core.audit.service import audit, AuditAction
from core.utils import parse_datum

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rechnungsstatus-Konstanten
# ---------------------------------------------------------------------------

class RechnungStatus:
    ENTWURF          = "Entwurf"
    OFFEN            = "Offen"
    BEZAHLT          = "Bezahlt"
    ERINNERUNG       = "Steht zur Erinnerung an"
    MAHNUNG1         = "Steht zur Mahnung an"
    MAHNUNG2         = "Steht zur Mahnung 2 an"
    INKASSO          = "Bitte an Inkasso weiterleiten"
    STORNIERT        = "Storniert"
    GUTSCHRIFT       = "Gutschrift"

    ALLE = [
        ENTWURF, OFFEN, BEZAHLT, ERINNERUNG,
        MAHNUNG1, MAHNUNG2, INKASSO, STORNIERT, GUTSCHRIFT,
    ]

    # Status die nach Finalisierung manuell gesetzt werden können
    MANUELL_SETZBAR = [BEZAHLT, OFFEN, ERINNERUNG, MAHNUNG1, MAHNUNG2, INKASSO]

    # Mahnstufenreihenfolge (für automatisches Eskalieren)
    MAHNSTUFEN = [OFFEN, ERINNERUNG, MAHNUNG1, MAHNUNG2, INKASSO]


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------

@dataclass
class PostenDTO:
    """Einzelner Rechnungsposten."""
    id: Optional[int]
    rechnung_id: Optional[int]
    position: int
    artikelnummer: str
    beschreibung: str
    menge: Decimal
    einheit: str
    einzelpreis_netto: Decimal
    gesamtpreis_netto: Decimal

    @classmethod
    def from_model(cls, p: Rechnungsposten) -> "PostenDTO":
        return cls(
            id=p.id,
            rechnung_id=p.rechnung_id,
            position=p.position,
            artikelnummer=p.artikelnummer or "",
            beschreibung=p.beschreibung or "",
            menge=Decimal(str(p.menge)),
            einheit=p.einheit or "",
            einzelpreis_netto=Decimal(str(p.einzelpreis_netto)),
            gesamtpreis_netto=Decimal(str(p.gesamtpreis_netto)),
        )

    @classmethod
    def neu(cls, position: int = 1) -> "PostenDTO":
        return cls(
            id=None, rechnung_id=None,
            position=position,
            artikelnummer="", beschreibung="",
            menge=Decimal("1"), einheit="Stück",
            einzelpreis_netto=Decimal("0"),
            gesamtpreis_netto=Decimal("0"),
        )


@dataclass
class RechnungDTO:
    """Vollständige Rechnung mit Posten."""
    id: Optional[int]
    kunde_id: int
    rechnungsnummer: str
    rechnungsdatum: str        # TT.MM.JJJJ
    faelligkeitsdatum: str     # TT.MM.JJJJ
    mwst_prozent: Decimal
    summe_netto: Decimal
    summe_mwst: Decimal
    summe_brutto: Decimal
    mahngebuehren: Decimal
    offener_betrag: Decimal
    status: str
    bemerkung: str
    is_finalized: bool
    posten: list[PostenDTO] = field(default_factory=list)

    storno_zu_nr: str = ""  # Originalnummer bei Gutschriften

    # Kundendaten (nur für Anzeige, nicht gespeichert)
    kunde_name: str = ""
    kunde_vorname: str = ""
    kunde_zifferncode: Optional[int] = None

    @classmethod
    def from_model(cls, r: Rechnung, include_posten: bool = True) -> "RechnungDTO":
        posten = []
        if include_posten and r.posten:
            posten = [PostenDTO.from_model(p) for p in sorted(r.posten, key=lambda x: x.position)]

        kunde_name = ""
        kunde_vorname = ""
        kunde_zifferncode = None
        if r.kunde:
            kunde_name = r.kunde.name or ""
            kunde_vorname = r.kunde.vorname or ""
            kunde_zifferncode = r.kunde.zifferncode

        return cls(
            id=r.id,
            kunde_id=r.kunde_id,
            rechnungsnummer=r.rechnungsnummer or "",
            rechnungsdatum=r.rechnungsdatum or "",
            faelligkeitsdatum=r.faelligkeitsdatum or "",
            mwst_prozent=Decimal(str(r.mwst_prozent or "19.00")),
            summe_netto=Decimal(str(r.summe_netto or "0")),
            summe_mwst=Decimal(str(r.summe_mwst or "0")),
            summe_brutto=Decimal(str(r.summe_brutto or "0")),
            mahngebuehren=Decimal(str(r.mahngebuehren or "0")),
            offener_betrag=Decimal(str(r.offener_betrag or "0")),
            status=r.status or RechnungStatus.ENTWURF,
            bemerkung=r.bemerkung or "",
            is_finalized=bool(r.is_finalized),
            storno_zu_nr=r.storno_zu_nr or "",
            posten=posten,
            kunde_name=kunde_name,
            kunde_vorname=kunde_vorname,
            kunde_zifferncode=kunde_zifferncode,
        )

    @property
    def kunde_display(self) -> str:
        return f"{self.kunde_vorname} {self.kunde_name}".strip()

    @property
    def is_storno_or_gutschrift(self) -> bool:
        return self.status in (RechnungStatus.STORNIERT, RechnungStatus.GUTSCHRIFT)



# ---------------------------------------------------------------------------
# Hilfsrechnungen
# ---------------------------------------------------------------------------

def _round2(value: Decimal) -> Decimal:
    """Rundet auf 2 Dezimalstellen kaufmännisch."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def berechne_summen(
    posten: list[PostenDTO],
    mwst_prozent: Decimal,
) -> tuple[Decimal, Decimal, Decimal]:
    """
    Berechnet Netto, MwSt und Brutto aus Posten und MwSt-Satz.

    Returns:
        (summe_netto, summe_mwst, summe_brutto)
    """
    netto = sum((p.gesamtpreis_netto for p in posten), Decimal("0"))
    mwst = _round2(netto * mwst_prozent / Decimal("100"))
    brutto = _round2(netto + mwst)
    return _round2(netto), mwst, brutto


def berechne_gesamtpreis(menge: Decimal, einzelpreis: Decimal) -> Decimal:
    """Berechnet den Gesamtpreis eines Postens."""
    return _round2(menge * einzelpreis)



# ---------------------------------------------------------------------------
# RechnungsService
# ---------------------------------------------------------------------------

class RechnungsService:
    """
    Service für alle Rechnungsoperationen (GoBD-konform).

    Grundprinzip:
        - Entwürfe sind frei editierbar und löschbar
        - Finalisierte Rechnungen sind unveränderbar
        - Status und Bemerkung können an finalisierten Rechnungen geändert werden
        - Storno erzeugt immer eine Gegenbuchungs-Gutschrift
    """

    # ------------------------------------------------------------------
    # Lesen
    # ------------------------------------------------------------------

    def alle(
        self,
        session: Session,
        kunde_id: Optional[int] = None,
        suchtext: str = "",
        nur_offene: bool = False,
        nur_finalisiert: bool = False,
        status_filter: Optional[list[str]] = None,
    ) -> list[RechnungDTO]:
        """Gibt Rechnungen zurück, optional gefiltert."""
        query = (
            session.query(Rechnung)
            .join(Rechnung.kunde)
            .order_by(Rechnung.rechnungsdatum.desc(), Rechnung.id.desc())
        )

        if kunde_id is not None:
            query = query.filter(Rechnung.kunde_id == kunde_id)

        if nur_finalisiert:
            query = query.filter(Rechnung.is_finalized == True)

        if nur_offene:
            query = query.filter(
                Rechnung.is_finalized == True,
                Rechnung.status.notin_([
                    RechnungStatus.BEZAHLT,
                    RechnungStatus.STORNIERT,
                    RechnungStatus.GUTSCHRIFT,
                ])
            )

        if status_filter:
            query = query.filter(Rechnung.status.in_(status_filter))

        if suchtext:
            like = f"%{suchtext}%"
            query = query.filter(
                or_(
                    Rechnung.rechnungsnummer.ilike(like),
                    Rechnung.status.ilike(like),
                    Rechnung.bemerkung.ilike(like),
                    Kunde.name.ilike(like),
                    Kunde.vorname.ilike(like),
                )
            )

        rechnungen = query.all()
        return [RechnungDTO.from_model(r, include_posten=False) for r in rechnungen]

    def nach_id(
        self, session: Session, rechnung_id: int
    ) -> Optional[RechnungDTO]:
        """Gibt eine vollständige Rechnung mit Posten zurück."""
        r = session.get(Rechnung, rechnung_id)
        if not r:
            return None
        # Lade Kunde explizit (lazy loading)
        _ = r.kunde
        _ = r.posten
        return RechnungDTO.from_model(r, include_posten=True)

    def nach_nummer(
        self, session: Session, nummer: str
    ) -> Optional[RechnungDTO]:
        """Gibt eine Rechnung anhand der Rechnungsnummer zurück."""
        r = (
            session.query(Rechnung)
            .filter_by(rechnungsnummer=nummer.strip())
            .first()
        )
        if not r:
            return None
        _ = r.kunde
        _ = r.posten
        return RechnungDTO.from_model(r, include_posten=True)

    def naechste_rechnungsnummer(
        self, session: Session, jahr: Optional[int] = None
    ) -> str:
        """
        Generiert die nächste Rechnungsnummer im Format JJJJ-NNNN.
        Beginnt jedes Jahr bei 0001.

        Verwendet Row-Level-Locking (FOR UPDATE) bei PostgreSQL,
        um Race Conditions im Mehrbenutzerbetrieb zu verhindern.
        """
        if jahr is None:
            jahr = datetime.now().year

        prefix = f"{jahr}-"
        # FOR UPDATE sperrt die betroffenen Zeilen bis zum Commit,
        # sodass parallele Transaktionen warten müssen.
        result = (
            session.query(Rechnung.rechnungsnummer)
            .filter(Rechnung.rechnungsnummer.like(f"{prefix}%"))
            .order_by(Rechnung.rechnungsnummer.desc())
            .with_for_update()
            .first()
        )

        if result:
            try:
                # Laufende Nummer robust vom Ende extrahieren (nach letztem '-')
                letzte_nr = result[0].rsplit("-", 1)[-1]
                laufende_nr = int(letzte_nr) + 1
            except (IndexError, ValueError):
                laufende_nr = 1
        else:
            laufende_nr = 1

        return f"{prefix}{laufende_nr:04d}"

    def nummer_existiert(self, session: Session, nummer: str) -> bool:
        """Prüft ob eine Rechnungsnummer bereits vergeben ist."""
        return (
            session.query(Rechnung)
            .filter_by(rechnungsnummer=nummer.strip())
            .first()
        ) is not None

    # ------------------------------------------------------------------
    # Entwurf erstellen / bearbeiten
    # ------------------------------------------------------------------

    def entwurf_erstellen(
        self,
        session: Session,
        kunde_id: int,
        dto: RechnungDTO,
    ) -> ServiceResult:
        """Legt eine neue Rechnung als Entwurf an."""
        fehler = self._validiere_entwurf(dto, session)
        if fehler:
            return ServiceResult.fail(fehler)

        try:
            netto, mwst, brutto = berechne_summen(dto.posten, dto.mwst_prozent)

            rechnung = Rechnung(
                kunde_id=kunde_id,
                rechnungsnummer=dto.rechnungsnummer.strip(),
                rechnungsdatum=dto.rechnungsdatum.strip(),
                faelligkeitsdatum=dto.faelligkeitsdatum.strip() or None,
                mwst_prozent=dto.mwst_prozent,
                summe_netto=netto,
                summe_mwst=mwst,
                summe_brutto=brutto,
                mahngebuehren=Decimal("0"),
                offener_betrag=brutto,
                status=RechnungStatus.ENTWURF,
                bemerkung=dto.bemerkung.strip() or None,
                is_finalized=False,
            )
            session.add(rechnung)
            session.flush()  # ID generieren

            # Posten anlegen
            for i, p in enumerate(dto.posten, start=1):
                art_nr = p.artikelnummer.strip() or None
                # FK-Prüfung: nur setzen wenn Artikel im Stamm existiert
                if art_nr:
                    exists = session.query(Artikel.artikelnummer).filter(
                        Artikel.artikelnummer == art_nr
                    ).first()
                    if not exists:
                        logger.warning(
                            f"Artikelnummer '{art_nr}' nicht im Stamm gefunden "
                            f"(Position {i}) – FK wird auf NULL gesetzt"
                        )
                        art_nr = None
                posten = Rechnungsposten(
                    rechnung_id=rechnung.id,
                    position=i,
                    artikelnummer=art_nr,
                    beschreibung=p.beschreibung.strip(),
                    menge=p.menge,
                    einheit=p.einheit.strip() or None,
                    einzelpreis_netto=p.einzelpreis_netto,
                    gesamtpreis_netto=berechne_gesamtpreis(p.menge, p.einzelpreis_netto),
                )
                session.add(posten)
            session.flush()  # FK-Fehler hier abfangen statt beim commit

            audit.log(
                session, AuditAction.RECHNUNG_ENTWURF_ERSTELLT,
                record_id=rechnung.id, table_name="rechnungen",
                details=f"Entwurf '{rechnung.rechnungsnummer}' für Kunde ID {kunde_id} erstellt.",
            )

            logger.info(f"Rechnungsentwurf erstellt: {rechnung.rechnungsnummer}")
            return ServiceResult.ok(
                data=RechnungDTO.from_model(rechnung, include_posten=True),
                message=f"Entwurf '{rechnung.rechnungsnummer}' gespeichert.",
            )
        except Exception as e:
            logger.exception("Fehler beim Erstellen des Rechnungsentwurfs:")
            return ServiceResult.fail(f"Datenbankfehler: {e}")

    def entwurf_aktualisieren(
        self,
        session: Session,
        rechnung_id: int,
        dto: RechnungDTO,
    ) -> ServiceResult:
        """Aktualisiert einen bestehenden Entwurf."""
        rechnung = session.get(Rechnung, rechnung_id)
        if not rechnung:
            return ServiceResult.fail("Rechnung nicht gefunden.")
        if rechnung.is_finalized:
            return ServiceResult.fail(
                "Finalisierte Rechnungen können nicht mehr bearbeitet werden."
            )

        fehler = self._validiere_entwurf(dto, session, exclude_id=rechnung_id)
        if fehler:
            return ServiceResult.fail(fehler)

        try:
            netto, mwst, brutto = berechne_summen(dto.posten, dto.mwst_prozent)

            rechnung.rechnungsnummer = dto.rechnungsnummer.strip()
            rechnung.rechnungsdatum = dto.rechnungsdatum.strip()
            rechnung.faelligkeitsdatum = dto.faelligkeitsdatum.strip() or None
            rechnung.mwst_prozent = dto.mwst_prozent
            rechnung.summe_netto = netto
            rechnung.summe_mwst = mwst
            rechnung.summe_brutto = brutto
            rechnung.offener_betrag = brutto
            rechnung.bemerkung = dto.bemerkung.strip() or None

            # Alle alten Posten löschen und neu anlegen
            for p in list(rechnung.posten):
                session.delete(p)
            session.flush()

            for i, p in enumerate(dto.posten, start=1):
                art_nr = p.artikelnummer.strip() or None
                if art_nr:
                    exists = session.query(Artikel.artikelnummer).filter(
                        Artikel.artikelnummer == art_nr
                    ).first()
                    if not exists:
                        logger.warning(
                            f"Artikelnummer '{art_nr}' nicht im Stamm gefunden "
                            f"(Position {i}, Update) – FK wird auf NULL gesetzt"
                        )
                        art_nr = None
                posten = Rechnungsposten(
                    rechnung_id=rechnung.id,
                    position=i,
                    artikelnummer=art_nr,
                    beschreibung=p.beschreibung.strip(),
                    menge=p.menge,
                    einheit=p.einheit.strip() or None,
                    einzelpreis_netto=p.einzelpreis_netto,
                    gesamtpreis_netto=berechne_gesamtpreis(p.menge, p.einzelpreis_netto),
                )
                session.add(posten)
            session.flush()

            audit.log(
                session, AuditAction.RECHNUNG_ENTWURF_GEAENDERT,
                record_id=rechnung_id, table_name="rechnungen",
                details=f"Entwurf '{rechnung.rechnungsnummer}' aktualisiert.",
            )

            return ServiceResult.ok(
                data=RechnungDTO.from_model(rechnung, include_posten=True),
                message=f"Entwurf '{rechnung.rechnungsnummer}' aktualisiert.",
            )
        except Exception as e:
            logger.exception("Fehler beim Aktualisieren des Entwurfs:")
            return ServiceResult.fail(f"Datenbankfehler: {e}")

    def entwurf_loeschen(
        self, session: Session, rechnung_id: int
    ) -> ServiceResult:
        """Löscht einen Entwurf (nur Entwürfe, keine finalisierten!)."""
        rechnung = session.get(Rechnung, rechnung_id)
        if not rechnung:
            return ServiceResult.fail("Rechnung nicht gefunden.")
        if rechnung.is_finalized:
            return ServiceResult.fail(
                "Finalisierte Rechnungen können nicht gelöscht werden (GoBD)."
            )

        nummer = rechnung.rechnungsnummer
        try:
            session.delete(rechnung)
            audit.log(
                session, AuditAction.RECHNUNG_ENTWURF_GELOESCHT,
                record_id=rechnung_id, table_name="rechnungen",
                details=f"Entwurf '{nummer}' gelöscht.",
            )
            return ServiceResult.ok(
                message=f"Entwurf '{nummer}' gelöscht."
            )
        except Exception as e:
            logger.exception("Fehler beim Löschen des Entwurfs:")
            return ServiceResult.fail(f"Datenbankfehler: {e}")

    # ------------------------------------------------------------------
    # Finalisieren (GoBD-konform)
    # ------------------------------------------------------------------

    def finalisieren(
        self, session: Session, rechnung_id: int
    ) -> ServiceResult:
        """
        Finalisiert eine Rechnung (GoBD-konform, danach unveränderbar).

        - Setzt is_finalized = True
        - Status → Offen
        - Bucht Lagerbestände ab
        - Protokolliert im Audit-Log
        """
        rechnung = session.get(Rechnung, rechnung_id)
        if not rechnung:
            return ServiceResult.fail("Rechnung nicht gefunden.")
        if rechnung.is_finalized:
            return ServiceResult.fail("Rechnung ist bereits finalisiert.")
        if not rechnung.posten:
            return ServiceResult.fail(
                "Eine Rechnung ohne Posten kann nicht finalisiert werden."
            )

        try:
            rechnung.is_finalized = True
            rechnung.status = RechnungStatus.OFFEN

            # Lagerbestand abbuchen
            lager_log = []
            for posten in rechnung.posten:
                if posten.artikelnummer:
                    artikel = (
                        session.query(Artikel)
                        .filter_by(artikelnummer=posten.artikelnummer)
                        .first()
                    )
                    if artikel:
                        bestand_vor = Decimal(str(artikel.verfuegbar))
                        menge = Decimal(str(posten.menge))
                        if bestand_vor < menge:
                            return ServiceResult.fail(
                                f"Lagerbestand nicht ausreichend für Artikel "
                                f"'{posten.artikelnummer}': Verfügbar {bestand_vor}, "
                                f"benötigt {menge}."
                            )
                        artikel.verfuegbar = bestand_vor - menge
                        bestand_nach = artikel.verfuegbar
                        lager_log.append(
                            f"{posten.artikelnummer}: {bestand_vor} → {bestand_nach}"
                        )
                        session.add(LagerBewegung(
                            artikelnummer=posten.artikelnummer,
                            buchungsart="Rechnungsabgang",
                            menge=-menge,
                            bestand_vor=bestand_vor,
                            bestand_nach=bestand_nach,
                            referenz=rechnung.rechnungsnummer,
                            notiz=f"Finalisierung Rechnung {rechnung.rechnungsnummer}, Pos. {posten.position}",
                        ))
                    else:
                        logger.warning(
                            f"Artikel '{posten.artikelnummer}' nicht im Lager gefunden "
                            f"(Rechnung {rechnung.rechnungsnummer}, Pos. {posten.position}). "
                            f"Keine Lagerbewegung erstellt."
                        )
                        lager_log.append(
                            f"{posten.artikelnummer}: NICHT IM LAGER (übersprungen)"
                        )

            lager_details = "; ".join(lager_log) if lager_log else "keine Lagerbewegung"

            audit.log(
                session, AuditAction.RECHNUNG_FINALISIERT,
                record_id=rechnung_id, table_name="rechnungen",
                details=(
                    f"Rechnung '{rechnung.rechnungsnummer}' finalisiert. "
                    f"Lager: {lager_details}"
                ),
            )

            logger.info(f"Rechnung finalisiert: {rechnung.rechnungsnummer}")
            return ServiceResult.ok(
                data=RechnungDTO.from_model(rechnung),
                message=(
                    f"Rechnung '{rechnung.rechnungsnummer}' finalisiert und gebucht. "
                    f"Status: Offen."
                ),
            )
        except Exception as e:
            logger.exception("Fehler beim Finalisieren:")
            return ServiceResult.fail(f"Datenbankfehler: {e}")

    # ------------------------------------------------------------------
    # Status ändern
    # ------------------------------------------------------------------

    def status_aendern(
        self,
        session: Session,
        rechnung_id: int,
        neuer_status: str,
        bemerkung_zusatz: str = "",
    ) -> ServiceResult:
        """
        Ändert den Status einer finalisierten Rechnung.
        Entwürfe können nicht manuell einen Status erhalten.
        """
        rechnung = session.get(Rechnung, rechnung_id)
        if not rechnung:
            return ServiceResult.fail("Rechnung nicht gefunden.")
        if not rechnung.is_finalized:
            return ServiceResult.fail(
                "Nur finalisierte Rechnungen können einen Status erhalten."
            )
        if neuer_status not in RechnungStatus.MANUELL_SETZBAR:
            return ServiceResult.fail(
                f"Status '{neuer_status}' kann nicht manuell gesetzt werden."
            )

        alter_status = rechnung.status
        try:
            rechnung.status = neuer_status
            if bemerkung_zusatz:
                timestamp = datetime.now().strftime("%d.%m.%Y %H:%M")
                zusatz = f"\n[{timestamp}] Status → {neuer_status}: {bemerkung_zusatz}"
                rechnung.bemerkung = (rechnung.bemerkung or "") + zusatz

            audit.log(
                session, AuditAction.RECHNUNG_STATUS_GEAENDERT,
                record_id=rechnung_id, table_name="rechnungen",
                details=(
                    f"Status '{rechnung.rechnungsnummer}': "
                    f"'{alter_status}' → '{neuer_status}'"
                ),
            )

            return ServiceResult.ok(
                message=f"Status geändert: {alter_status} → {neuer_status}"
            )
        except Exception as e:
            return ServiceResult.fail(f"Datenbankfehler: {e}")

    def bemerkung_aktualisieren(
        self, session: Session, rechnung_id: int, neue_bemerkung: str
    ) -> ServiceResult:
        """Aktualisiert die Bemerkung (auch an finalisierten Rechnungen erlaubt)."""
        rechnung = session.get(Rechnung, rechnung_id)
        if not rechnung:
            return ServiceResult.fail("Rechnung nicht gefunden.")
        try:
            rechnung.bemerkung = neue_bemerkung.strip() or None
            return ServiceResult.ok(message="Bemerkung aktualisiert.")
        except Exception as e:
            return ServiceResult.fail(f"Datenbankfehler: {e}")

    # ------------------------------------------------------------------
    # Automatische Mahnstufenprüfung
    # ------------------------------------------------------------------

    def pruefe_ueberfaellige(
        self,
        session: Session,
        reminder_days: int = 7,
        mahnung1_days: int = 21,
        mahnung2_days: int = 35,
        inkasso_days: int = 49,
    ) -> list[dict]:
        """
        Prüft alle offenen Rechnungen auf Überfälligkeit und eskaliert
        den Status automatisch. Gibt eine Liste der geänderten Rechnungen zurück.
        """
        heute = date.today()
        geaendert = []

        offene = (
            session.query(Rechnung)
            .filter(
                Rechnung.is_finalized == True,
                Rechnung.status.in_([
                    RechnungStatus.OFFEN,
                    RechnungStatus.ERINNERUNG,
                    RechnungStatus.MAHNUNG1,
                    RechnungStatus.MAHNUNG2,
                ]),
                Rechnung.faelligkeitsdatum.isnot(None),
            )
            .all()
        )

        for rechnung in offene:
            faellig = parse_datum(rechnung.faelligkeitsdatum)
            if faellig is None:
                continue
            tage_ueberfaellig = (heute - faellig).days

            if tage_ueberfaellig <= 0:
                continue  # Noch nicht fällig

            neuer_status = None
            if tage_ueberfaellig >= inkasso_days:
                if rechnung.status != RechnungStatus.INKASSO:
                    neuer_status = RechnungStatus.INKASSO
            elif tage_ueberfaellig >= mahnung2_days:
                if rechnung.status not in (RechnungStatus.MAHNUNG2, RechnungStatus.INKASSO):
                    neuer_status = RechnungStatus.MAHNUNG2
            elif tage_ueberfaellig >= mahnung1_days:
                if rechnung.status not in (
                    RechnungStatus.MAHNUNG1, RechnungStatus.MAHNUNG2, RechnungStatus.INKASSO
                ):
                    neuer_status = RechnungStatus.MAHNUNG1
            elif tage_ueberfaellig >= reminder_days:
                if rechnung.status == RechnungStatus.OFFEN:
                    neuer_status = RechnungStatus.ERINNERUNG

            if neuer_status:
                alter_status = rechnung.status
                rechnung.status = neuer_status
                timestamp = datetime.now().strftime("%d.%m.%Y %H:%M")
                zusatz = (
                    f"\n[{timestamp}] Automatisch: '{alter_status}' → '{neuer_status}' "
                    f"({tage_ueberfaellig} Tage überfällig)"
                )
                rechnung.bemerkung = (rechnung.bemerkung or "") + zusatz

                audit.log(
                    session, AuditAction.RECHNUNG_STATUS_AUTO,
                    record_id=rechnung.id, table_name="rechnungen",
                    details=(
                        f"Auto-Status '{rechnung.rechnungsnummer}': "
                        f"'{alter_status}' → '{neuer_status}' "
                        f"({tage_ueberfaellig}d überfällig)"
                    ),
                )

                geaendert.append({
                    "rechnung_id": rechnung.id,
                    "nummer": rechnung.rechnungsnummer,
                    "alter_status": alter_status,
                    "neuer_status": neuer_status,
                    "tage_ueberfaellig": tage_ueberfaellig,
                })

        if geaendert:
            logger.info(f"Automatische Statusaktualisierung: {len(geaendert)} Rechnungen aktualisiert.")

        return geaendert

    # ------------------------------------------------------------------
    # Storno (GoBD-konform)
    # ------------------------------------------------------------------


    # ------------------------------------------------------------------
    # Zahlungsbuchungen
    # ------------------------------------------------------------------

    def teilzahlung_buchen(
        self,
        session: Session,
        rechnung_id: int,
        betrag: Decimal,
        datum: str = "",
        bemerkung_zusatz: str = "",
    ) -> "ServiceResult":
        """
        Bucht eine Teilzahlung auf eine Rechnung.
        Reduziert den offenen_betrag; bei vollständiger Zahlung → Status BEZAHLT.
        """
        rechnung = (
            session.query(Rechnung)
            .filter_by(id=rechnung_id)
            .with_for_update()
            .first()
        )
        if not rechnung:
            return ServiceResult.fail("Rechnung nicht gefunden.")
        if not rechnung.is_finalized:
            return ServiceResult.fail("Nur auf finalisierte Rechnungen buchbar.")
        if rechnung.status in (RechnungStatus.STORNIERT, RechnungStatus.GUTSCHRIFT):
            return ServiceResult.fail("Stornierte Rechnungen oder Gutschriften können nicht bezahlt werden.")

        offen = Decimal(str(rechnung.offener_betrag or "0"))
        if betrag <= Decimal("0"):
            return ServiceResult.fail("Zahlungsbetrag muss größer als 0 sein.")
        if betrag > offen:
            return ServiceResult.fail(
                f"Zahlungsbetrag ({betrag:.2f} €) übersteigt offenen Betrag ({offen:.2f} €)."
            )

        try:
            rechnung.offener_betrag = offen - betrag
            ts = datum or datetime.now().strftime("%d.%m.%Y")
            notiz = f"\n[{ts}] Zahlung +{betrag:.2f} € erhalten."
            if bemerkung_zusatz:
                notiz += f" {bemerkung_zusatz}"
            rechnung.bemerkung = (rechnung.bemerkung or "") + notiz

            # Vollständig bezahlt?
            if rechnung.offener_betrag <= Decimal("0"):
                rechnung.offener_betrag = Decimal("0")
                rechnung.status = RechnungStatus.BEZAHLT
                rechnung.bemerkung += " → Vollständig bezahlt."

            audit.log(
                session, AuditAction.TEILZAHLUNG_GEBUCHT,
                record_id=rechnung_id, table_name="rechnungen",
                details=f"Zahlung {betrag:.2f} € auf '{rechnung.rechnungsnummer}'. Noch offen: {rechnung.offener_betrag:.2f} €.",
            )
            verbleibend = rechnung.offener_betrag
            msg = (
                f"Zahlung von {betrag:.2f} € gebucht. "
                + (f"Noch offen: {verbleibend:.2f} €." if verbleibend > 0 else "Rechnung vollständig bezahlt.")
            )
            return ServiceResult.ok(message=msg, data={"offener_betrag": rechnung.offener_betrag})
        except Exception as e:
            return ServiceResult.fail(f"Datenbankfehler: {e}")

    def skonto_gewaehren(
        self,
        session: Session,
        rechnung_id: int,
        prozent: Decimal = None,
        betrag: Decimal = None,
        bemerkung_zusatz: str = "",
    ) -> "ServiceResult":
        """
        Gewährt nachträglich Skonto oder Rabatt auf eine finalisierte Rechnung.
        Entweder prozent (0–100) ODER betrag angeben.
        Reduziert offener_betrag (summe_brutto bleibt GoBD-konform unverändert).
        """
        rechnung = (
            session.query(Rechnung)
            .filter_by(id=rechnung_id)
            .with_for_update()
            .first()
        )
        if not rechnung:
            return ServiceResult.fail("Rechnung nicht gefunden.")
        if not rechnung.is_finalized:
            return ServiceResult.fail("Nur auf finalisierte Rechnungen buchbar.")
        if rechnung.status in (RechnungStatus.STORNIERT, RechnungStatus.GUTSCHRIFT, RechnungStatus.BEZAHLT):
            return ServiceResult.fail("Skonto nicht möglich: Rechnung ist bereits abgeschlossen.")

        brutto = Decimal(str(rechnung.summe_brutto or "0"))
        offen  = Decimal(str(rechnung.offener_betrag or "0"))

        if prozent is not None:
            if not (Decimal("0") < prozent <= Decimal("100")):
                return ServiceResult.fail("Skonto-Prozentsatz muss zwischen 0 und 100 liegen.")
            skonto_betrag = (brutto * prozent / Decimal("100")).quantize(Decimal("0.01"))
        elif betrag is not None:
            skonto_betrag = betrag
        else:
            return ServiceResult.fail("Bitte prozent oder betrag angeben.")

        if skonto_betrag <= Decimal("0"):
            return ServiceResult.fail("Skonto-Betrag muss größer als 0 sein.")
        if skonto_betrag > offen:
            return ServiceResult.fail(
                f"Skonto ({skonto_betrag:.2f} €) übersteigt offenen Betrag ({offen:.2f} €)."
            )

        try:
            rechnung.offener_betrag = offen - skonto_betrag
            ts = datetime.now().strftime("%d.%m.%Y")
            label = f"{prozent:.1f} % Skonto" if prozent is not None else "Rabatt"
            notiz = f"\n[{ts}] {label} –{skonto_betrag:.2f} € gewährt."
            if bemerkung_zusatz:
                notiz += f" {bemerkung_zusatz}"
            rechnung.bemerkung = (rechnung.bemerkung or "") + notiz

            if rechnung.offener_betrag <= Decimal("0"):
                rechnung.offener_betrag = Decimal("0")
                rechnung.status = RechnungStatus.BEZAHLT
                rechnung.bemerkung += " → Vollständig bezahlt."

            audit.log(
                session, AuditAction.SKONTO_GEWAEHRT,
                record_id=rechnung_id, table_name="rechnungen",
                details=f"{label} {skonto_betrag:.2f} € auf '{rechnung.rechnungsnummer}'.",
            )
            return ServiceResult.ok(
                message=f"{label} von {skonto_betrag:.2f} € gewährt.",
                data={"skonto_betrag": skonto_betrag, "offener_betrag": rechnung.offener_betrag},
            )
        except Exception as e:
            return ServiceResult.fail(f"Datenbankfehler: {e}")


    def teilgutschrift_erstellen(
        self,
        session: Session,
        rechnung_id: int,
        beschreibung: str,
        netto: Decimal,
        mwst_prozent: Decimal,
        grund: str = "",
    ) -> "ServiceResult":
        """
        Erstellt eine Teil-Gutschrift für eine einzelne Korrekturposition.
        GoBD-konform: Originalrechnung bleibt unverändert.
        """
        rechnung = (
            session.query(Rechnung)
            .filter_by(id=rechnung_id)
            .with_for_update()
            .first()
        )
        if not rechnung:
            return ServiceResult.fail("Rechnung nicht gefunden.")
        if not rechnung.is_finalized:
            return ServiceResult.fail("Nur auf finalisierte Rechnungen buchbar.")
        if rechnung.status in (RechnungStatus.STORNIERT, RechnungStatus.GUTSCHRIFT):
            return ServiceResult.fail("Stornierte Rechnungen oder Gutschriften können nicht korrigiert werden.")

        try:
            mwst_betrag = _round2(netto * mwst_prozent / Decimal("100"))
            brutto      = _round2(netto + mwst_betrag)

            offen = Decimal(str(rechnung.offener_betrag or "0"))
            if brutto > offen:
                return ServiceResult.fail(
                    f"Gutschriftbetrag ({brutto:.2f} €) übersteigt offenen Betrag ({offen:.2f} €)."
                )

            storno_nr = self._naechste_storno_nummer(session)
            gutschrift = Rechnung(
                kunde_id=rechnung.kunde_id,
                rechnungsnummer=storno_nr,
                rechnungsdatum=datetime.now().strftime("%d.%m.%Y"),
                faelligkeitsdatum=None,
                mwst_prozent=mwst_prozent,
                summe_netto=-_round2(netto),
                summe_mwst=-mwst_betrag,
                summe_brutto=-brutto,
                mahngebuehren=Decimal("0"),
                offener_betrag=Decimal("0"),
                status=RechnungStatus.GUTSCHRIFT,
                bemerkung=(
                    f"Teil-Gutschrift zu Rechnung {rechnung.rechnungsnummer}. "
                    f"Beschreibung: {beschreibung}."
                    + (f" Grund: {grund}" if grund else "")
                ),
                storno_zu_nr=rechnung.rechnungsnummer,
                is_finalized=True,
            )
            session.add(gutschrift)
            session.flush()

            # Korrektur-Posten
            gp = Rechnungsposten(
                rechnung_id=gutschrift.id,
                position=1,
                artikelnummer=None,
                beschreibung=beschreibung,
                menge=Decimal("-1"),
                einheit="Stück",
                einzelpreis_netto=_round2(netto),
                gesamtpreis_netto=-_round2(netto),
            )
            session.add(gp)

            # Offenen Betrag der Originalrechnung um Gutschrift reduzieren.
            # Negativer offener_betrag = Verbindlichkeit ggü. Kunde (z.B. bei
            # Gutschrift nach bereits vollständiger Bezahlung → Rückerstattung).
            if rechnung.offener_betrag is not None:
                rechnung.offener_betrag = _round2(
                    Decimal(str(rechnung.offener_betrag)) - brutto
                )
                if rechnung.offener_betrag == Decimal("0"):
                    rechnung.status = RechnungStatus.BEZAHLT

            # Originalbemerkung aktualisieren
            ts = datetime.now().strftime("%d.%m.%Y %H:%M")
            notiz = f"\n[{ts}] Teil-Gutschrift {storno_nr} erstellt. {beschreibung}."
            if grund:
                notiz += f" Grund: {grund}"
            rechnung.bemerkung = (rechnung.bemerkung or "") + notiz

            audit.log(
                session, AuditAction.GUTSCHRIFT_ERSTELLT,
                record_id=gutschrift.id, table_name="rechnungen",
                details=f"Teil-Gutschrift '{storno_nr}' zu '{rechnung.rechnungsnummer}'.",
            )
            return ServiceResult.ok(
                message=f"Teil-Gutschrift {storno_nr} erstellt.",
                data={"gutschrift_nummer": storno_nr},
            )
        except Exception as e:
            return ServiceResult.fail(f"Datenbankfehler: {e}")

    def stornieren(
        self,
        session: Session,
        rechnung_id: int,
        grund: str = "",
    ) -> ServiceResult:
        """
        GoBD-konformes Storno:
        1. Originale Rechnung → Status 'Storniert'
        2. Neue Gutschrift (negative Beträge) wird automatisch angelegt
        3. Lagerbestände werden zurückgebucht
        """
        rechnung = (
            session.query(Rechnung)
            .filter_by(id=rechnung_id)
            .with_for_update()
            .first()
        )
        if not rechnung:
            return ServiceResult.fail("Rechnung nicht gefunden.")
        if not rechnung.is_finalized:
            return ServiceResult.fail(
                "Nur finalisierte Rechnungen können storniert werden."
            )
        if rechnung.status == RechnungStatus.STORNIERT:
            return ServiceResult.fail("Rechnung ist bereits storniert.")
        if rechnung.status == RechnungStatus.GUTSCHRIFT:
            return ServiceResult.fail("Eine Gutschrift kann nicht storniert werden.")

        try:
            original_nummer = rechnung.rechnungsnummer
            alter_status = rechnung.status

            # 1. Skonto/Zahlungsbetrag berechnen BEVOR offener_betrag geändert wird
            brutto = rechnung.summe_brutto or Decimal("0")
            alter_offener_betrag = Decimal(str(rechnung.offener_betrag or "0"))
            skonto_betrag = brutto - alter_offener_betrag
            # skonto_betrag > 0 wenn Teilzahlung oder Skonto erfolgte
            skonto_hinweis = ""
            if skonto_betrag > Decimal("0") and alter_offener_betrag != brutto:
                skonto_hinweis = (
                    f" Hinweis: Auf die Originalrechnung wurden bereits "
                    f"{skonto_betrag:.2f} € (Skonto/Zahlungen) verbucht."
                )

            # 2. Original stornieren (offener_betrag NACH Berechnung auf 0 setzen)
            rechnung.status = RechnungStatus.STORNIERT
            rechnung.offener_betrag = Decimal("0")
            timestamp = datetime.now().strftime("%d.%m.%Y %H:%M")
            storno_notiz = f"\n[{timestamp}] Storniert."
            if grund:
                storno_notiz += f" Grund: {grund}"
            rechnung.bemerkung = (rechnung.bemerkung or "") + storno_notiz

            # 3. Storno-Nummer generieren (fortlaufend, GoBD-konform)
            storno_nummer = self._naechste_storno_nummer(session)

            # 4. Gutschrift anlegen
            #    GoBD-konform: Gutschrift deckt den VOLLEN Rechnungsbetrag ab.
            gutschrift = Rechnung(
                kunde_id=rechnung.kunde_id,
                rechnungsnummer=storno_nummer,
                rechnungsdatum=datetime.now().strftime("%d.%m.%Y"),
                faelligkeitsdatum=None,
                mwst_prozent=rechnung.mwst_prozent,
                summe_netto=-(rechnung.summe_netto or Decimal("0")),
                summe_mwst=-(rechnung.summe_mwst or Decimal("0")),
                summe_brutto=-brutto,
                mahngebuehren=Decimal("0"),
                offener_betrag=Decimal("0"),
                status=RechnungStatus.GUTSCHRIFT,
                bemerkung=(
                    f"Gutschrift zu Rechnung {original_nummer}."
                    + (f" Grund: {grund}" if grund else "")
                    + skonto_hinweis
                ),
                storno_zu_nr=original_nummer,
                is_finalized=True,
            )
            session.add(gutschrift)
            session.flush()

            # 4. Gutschrift-Posten (negierte Mengen/Preise)
            for p in rechnung.posten:
                gp = Rechnungsposten(
                    rechnung_id=gutschrift.id,
                    position=p.position,
                    artikelnummer=p.artikelnummer,
                    beschreibung=p.beschreibung,
                    menge=-Decimal(str(p.menge)),
                    einheit=p.einheit,
                    einzelpreis_netto=p.einzelpreis_netto,
                    gesamtpreis_netto=-Decimal(str(p.gesamtpreis_netto)),
                )
                session.add(gp)

                # 5. Lager zurückbuchen (mit Bestandsvalidierung)
                if p.artikelnummer:
                    artikel = (
                        session.query(Artikel)
                        .filter_by(artikelnummer=p.artikelnummer)
                        .with_for_update()
                        .first()
                    )
                    if artikel:
                        bestand_vor = Decimal(str(artikel.verfuegbar))
                        rueck_menge = Decimal(str(p.menge))
                        bestand_nach = bestand_vor + rueck_menge
                        if bestand_nach < Decimal("0"):
                            logger.warning(
                                f"Storno-Rückbuchung für Artikel '{p.artikelnummer}' "
                                f"ergibt negativen Bestand ({bestand_nach}). "
                                f"Buchung wird trotzdem durchgeführt."
                            )
                        artikel.verfuegbar = bestand_nach
                        session.add(LagerBewegung(
                            artikelnummer=p.artikelnummer,
                            buchungsart="Stornoeingang",
                            menge=rueck_menge,
                            bestand_vor=bestand_vor,
                            bestand_nach=bestand_nach,
                            referenz=storno_nummer,
                            notiz=f"Storno-Rückbuchung zu Rechnung {original_nummer}, Pos. {p.position}",
                        ))
                    else:
                        logger.warning(
                            f"Artikel '{p.artikelnummer}' nicht mehr im Lager vorhanden. "
                            f"Storno-Rückbuchung für Pos. {p.position} übersprungen."
                        )

            audit.log(
                session, AuditAction.RECHNUNG_STORNIERT,
                record_id=rechnung_id, table_name="rechnungen",
                details=(
                    f"Rechnung '{original_nummer}' storniert. "
                    f"Gutschrift: '{storno_nummer}' angelegt."
                    + (f" Grund: {grund}" if grund else "")
                ),
            )
            audit.log(
                session, AuditAction.GUTSCHRIFT_ERSTELLT,
                record_id=gutschrift.id, table_name="rechnungen",
                details=f"Gutschrift '{storno_nummer}' zu '{original_nummer}' erstellt.",
            )

            return ServiceResult.ok(
                data={
                    "original_id": rechnung_id,
                    "gutschrift_id": gutschrift.id,
                    "gutschrift_nummer": storno_nummer,
                },
                message=(
                    f"Rechnung '{original_nummer}' storniert. "
                    f"Gutschrift '{storno_nummer}' erstellt."
                ),
            )
        except Exception as e:
            logger.exception("Fehler beim Stornieren:")
            return ServiceResult.fail(f"Datenbankfehler: {e}")

    # ------------------------------------------------------------------
    # Validierung
    # ------------------------------------------------------------------

    def _validiere_entwurf(
        self,
        dto: RechnungDTO,
        session: Session,
        exclude_id: Optional[int] = None,
    ) -> str:
        """Validiert Rechnungsdaten. Gibt Fehlermeldung oder '' zurück."""
        if not dto.rechnungsnummer.strip():
            return "Rechnungsnummer ist ein Pflichtfeld."

        # Eindeutigkeit der Rechnungsnummer prüfen
        existing = (
            session.query(Rechnung)
            .filter_by(rechnungsnummer=dto.rechnungsnummer.strip())
            .first()
        )
        if existing and existing.id != exclude_id:
            return f"Rechnungsnummer '{dto.rechnungsnummer}' ist bereits vergeben."

        if not dto.rechnungsdatum.strip():
            return "Rechnungsdatum ist ein Pflichtfeld."

        try:
            datetime.strptime(dto.rechnungsdatum.strip(), "%d.%m.%Y")
        except ValueError:
            return "Rechnungsdatum muss im Format TT.MM.JJJJ sein."

        if dto.faelligkeitsdatum.strip():
            try:
                datetime.strptime(dto.faelligkeitsdatum.strip(), "%d.%m.%Y")
            except ValueError:
                return "Fälligkeitsdatum muss im Format TT.MM.JJJJ sein."

        if not dto.posten:
            return "Eine Rechnung muss mindestens einen Posten enthalten."

        for p in dto.posten:
            if not p.beschreibung.strip():
                return f"Posten {p.position}: Beschreibung darf nicht leer sein."

        return ""

    def _naechste_storno_nummer(self, session: Session) -> str:
        """Generiert eine Storno-Nummer im Format S-JJJJ-NNNN.

        Verwendet Row-Level-Locking bei PostgreSQL gegen Race Conditions.
        Fallback auf COUNT-basierte Ermittlung bei malformierten Nummern.
        """
        jahr = datetime.now().year
        prefix = f"S-{jahr}-"
        result = (
            session.query(Rechnung.rechnungsnummer)
            .filter(Rechnung.rechnungsnummer.like(f"{prefix}%"))
            .order_by(Rechnung.rechnungsnummer.desc())
            .with_for_update()
            .first()
        )
        if result:
            try:
                # Laufende Nummer robust vom Ende extrahieren (nach letztem '-')
                letzte_nr = result[0].rsplit("-", 1)[-1]
                nr = int(letzte_nr) + 1
            except (IndexError, ValueError):
                # Fallback: Anzahl aller S-Nummern dieses Jahres + 1
                count = (
                    session.query(Rechnung)
                    .filter(Rechnung.rechnungsnummer.like(f"{prefix}%"))
                    .count()
                )
                nr = count + 1
                logger.warning(
                    f"Malformierte Storno-Nummer '{result[0]}' gefunden. "
                    f"Fallback auf laufende Nr. {nr}."
                )
        else:
            nr = 1

        # Sicherstellen, dass die Nummer noch nicht existiert
        kandidat = f"{prefix}{nr:04d}"
        while session.query(Rechnung).filter_by(rechnungsnummer=kandidat).first():
            nr += 1
            kandidat = f"{prefix}{nr:04d}"

        return kandidat


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
rechnungen_service = RechnungsService()
