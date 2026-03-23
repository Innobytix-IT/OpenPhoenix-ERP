"""
core/services/angebote_service.py – Business-Logik für Angebotswesen
=====================================================================
Vollständige Angebotsverwaltung:
- Angebote erstellen, bearbeiten, löschen
- Status verwalten (Entwurf → Offen → Angenommen/Abgelehnt/Abgelaufen)
- Angebotsnummern vergeben (AG-JJJJ-NNNN)
- Summen berechnen
"""

import logging
from dataclasses import dataclass, field
from core.services import ServiceResult
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from sqlalchemy import or_, func
from sqlalchemy.orm import Session

from core.models import Angebot, AngebotsPosten, Artikel, Kunde
from core.audit.service import audit, AuditAction

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Angebotsstatus-Konstanten
# ---------------------------------------------------------------------------

class AngebotStatus:
    ENTWURF    = "Entwurf"
    OFFEN      = "Offen"
    ANGENOMMEN = "Angenommen"
    ABGELEHNT  = "Abgelehnt"
    ABGELAUFEN = "Abgelaufen"

    ALLE = [ENTWURF, OFFEN, ANGENOMMEN, ABGELEHNT, ABGELAUFEN]

    # Status die manuell gesetzt werden können
    MANUELL_SETZBAR = [OFFEN, ANGENOMMEN, ABGELEHNT, ABGELAUFEN]


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------

@dataclass
class AngebotsPostenDTO:
    """Einzelner Angebotsposten."""
    id: Optional[int]
    angebot_id: Optional[int]
    position: int
    artikelnummer: str
    beschreibung: str
    menge: Decimal
    einheit: str
    einzelpreis_netto: Decimal
    gesamtpreis_netto: Decimal

    @classmethod
    def from_model(cls, p: AngebotsPosten) -> "AngebotsPostenDTO":
        return cls(
            id=p.id,
            angebot_id=p.angebot_id,
            position=p.position,
            artikelnummer=p.artikelnummer or "",
            beschreibung=p.beschreibung or "",
            menge=Decimal(str(p.menge)),
            einheit=p.einheit or "",
            einzelpreis_netto=Decimal(str(p.einzelpreis_netto)),
            gesamtpreis_netto=Decimal(str(p.gesamtpreis_netto)),
        )

    @classmethod
    def neu(cls, position: int = 1) -> "AngebotsPostenDTO":
        return cls(
            id=None, angebot_id=None,
            position=position,
            artikelnummer="", beschreibung="",
            menge=Decimal("1"), einheit="Stück",
            einzelpreis_netto=Decimal("0"),
            gesamtpreis_netto=Decimal("0"),
        )


@dataclass
class AngebotDTO:
    """Vollständiges Angebot mit Posten."""
    id: Optional[int]
    kunde_id: int
    angebotsnummer: str
    angebotsdatum: str        # TT.MM.JJJJ
    gueltig_bis: str          # TT.MM.JJJJ
    mwst_prozent: Decimal
    summe_netto: Decimal
    summe_mwst: Decimal
    summe_brutto: Decimal
    status: str
    bemerkung: str
    posten: list[AngebotsPostenDTO] = field(default_factory=list)

    # Kundendaten (nur für Anzeige)
    kunde_name: str = ""
    kunde_vorname: str = ""
    kunde_zifferncode: Optional[int] = None

    @classmethod
    def from_model(cls, a: Angebot, include_posten: bool = True) -> "AngebotDTO":
        posten = []
        if include_posten and a.posten:
            posten = [AngebotsPostenDTO.from_model(p) for p in sorted(a.posten, key=lambda x: x.position)]

        kunde_name = ""
        kunde_vorname = ""
        kunde_zifferncode = None
        if a.kunde:
            kunde_name = a.kunde.name or ""
            kunde_vorname = a.kunde.vorname or ""
            kunde_zifferncode = a.kunde.zifferncode

        return cls(
            id=a.id,
            kunde_id=a.kunde_id,
            angebotsnummer=a.angebotsnummer or "",
            angebotsdatum=a.angebotsdatum or "",
            gueltig_bis=a.gueltig_bis or "",
            mwst_prozent=Decimal(str(a.mwst_prozent or "19.00")),
            summe_netto=Decimal(str(a.summe_netto or "0")),
            summe_mwst=Decimal(str(a.summe_mwst or "0")),
            summe_brutto=Decimal(str(a.summe_brutto or "0")),
            status=a.status or AngebotStatus.ENTWURF,
            bemerkung=a.bemerkung or "",
            posten=posten,
            kunde_name=kunde_name,
            kunde_vorname=kunde_vorname,
            kunde_zifferncode=kunde_zifferncode,
        )

    @property
    def kunde_display(self) -> str:
        return f"{self.kunde_vorname} {self.kunde_name}".strip()



# ---------------------------------------------------------------------------
# Hilfsrechnungen
# ---------------------------------------------------------------------------

def _round2(value: Decimal) -> Decimal:
    """Rundet auf 2 Dezimalstellen kaufmännisch."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def berechne_summen(
    posten: list[AngebotsPostenDTO],
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
# AngebotsService
# ---------------------------------------------------------------------------

class AngebotsService:
    """
    Service für alle Angebotsoperationen.

    Grundprinzip:
        - Angebote sind frei editierbar und löschbar
        - Status kann jederzeit geändert werden
        - Angebotsnummern im Format AG-JJJJ-NNNN
    """

    # ------------------------------------------------------------------
    # Lesen
    # ------------------------------------------------------------------

    def alle(
        self,
        session: Session,
        kunde_id: Optional[int] = None,
        suchtext: str = "",
        status_filter: Optional[list[str]] = None,
    ) -> list[AngebotDTO]:
        """Gibt Angebote zurück, optional gefiltert."""
        query = (
            session.query(Angebot)
            .join(Angebot.kunde)
            .order_by(Angebot.angebotsdatum.desc(), Angebot.id.desc())
        )

        if kunde_id is not None:
            query = query.filter(Angebot.kunde_id == kunde_id)

        if status_filter:
            query = query.filter(Angebot.status.in_(status_filter))

        if suchtext:
            like = f"%{suchtext}%"
            query = query.filter(
                or_(
                    Angebot.angebotsnummer.ilike(like),
                    Angebot.status.ilike(like),
                    Angebot.bemerkung.ilike(like),
                    Kunde.name.ilike(like),
                    Kunde.vorname.ilike(like),
                )
            )

        angebote = query.all()
        return [AngebotDTO.from_model(a, include_posten=False) for a in angebote]

    def nach_id(
        self, session: Session, angebot_id: int
    ) -> Optional[AngebotDTO]:
        """Gibt ein vollständiges Angebot mit Posten zurück."""
        a = session.get(Angebot, angebot_id)
        if not a:
            return None
        _ = a.kunde
        _ = a.posten
        return AngebotDTO.from_model(a, include_posten=True)

    def naechste_angebotsnummer(
        self, session: Session, jahr: Optional[int] = None
    ) -> str:
        """
        Generiert die nächste Angebotsnummer im Format AG-JJJJ-NNNN.
        Beginnt jedes Jahr bei 0001.

        Verwendet Row-Level-Locking (FOR UPDATE) bei PostgreSQL,
        um Race Conditions im Mehrbenutzerbetrieb zu verhindern.
        """
        if jahr is None:
            jahr = datetime.now().year

        prefix = f"AG-{jahr}-"
        result = (
            session.query(Angebot.angebotsnummer)
            .filter(Angebot.angebotsnummer.like(f"{prefix}%"))
            .order_by(Angebot.angebotsnummer.desc())
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
        """Prüft ob eine Angebotsnummer bereits vergeben ist."""
        return (
            session.query(Angebot)
            .filter_by(angebotsnummer=nummer.strip())
            .first()
        ) is not None

    # ------------------------------------------------------------------
    # Erstellen / Bearbeiten
    # ------------------------------------------------------------------

    def erstellen(
        self,
        session: Session,
        kunde_id: int,
        dto: AngebotDTO,
    ) -> ServiceResult:
        """Legt ein neues Angebot an."""
        fehler = self._validiere(dto, session)
        if fehler:
            return ServiceResult.fail(fehler)

        try:
            netto, mwst, brutto = berechne_summen(dto.posten, dto.mwst_prozent)

            angebot = Angebot(
                kunde_id=kunde_id,
                angebotsnummer=dto.angebotsnummer.strip(),
                angebotsdatum=dto.angebotsdatum.strip(),
                gueltig_bis=dto.gueltig_bis.strip() or None,
                mwst_prozent=dto.mwst_prozent,
                summe_netto=netto,
                summe_mwst=mwst,
                summe_brutto=brutto,
                status=dto.status or AngebotStatus.ENTWURF,
                bemerkung=dto.bemerkung.strip() or None,
            )
            session.add(angebot)
            session.flush()

            for i, p in enumerate(dto.posten, start=1):
                gesamt = berechne_gesamtpreis(p.menge, p.einzelpreis_netto)
                art_nr = p.artikelnummer.strip() or None
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
                posten = AngebotsPosten(
                    angebot_id=angebot.id,
                    position=i,
                    artikelnummer=art_nr,
                    beschreibung=p.beschreibung.strip(),
                    menge=p.menge,
                    einheit=p.einheit.strip() or None,
                    einzelpreis_netto=p.einzelpreis_netto,
                    gesamtpreis_netto=gesamt,
                )
                session.add(posten)
            session.flush()

            audit.log(
                session, AuditAction.ANGEBOT_ERSTELLT,
                record_id=angebot.id,
                table_name="angebote",
                details=f"Angebot {angebot.angebotsnummer} erstellt.",
            )

            result_dto = AngebotDTO.from_model(angebot, include_posten=True)
            return ServiceResult.ok(result_dto, f"Angebot {angebot.angebotsnummer} erstellt.")

        except Exception as e:
            logger.exception("Fehler beim Erstellen des Angebots")
            return ServiceResult.fail(f"Fehler: {e}")

    def aktualisieren(
        self,
        session: Session,
        angebot_id: int,
        dto: AngebotDTO,
    ) -> ServiceResult:
        """Aktualisiert ein bestehendes Angebot."""
        angebot = session.get(Angebot, angebot_id)
        if not angebot:
            return ServiceResult.fail("Angebot nicht gefunden.")

        fehler = self._validiere(dto, session, exclude_id=angebot_id)
        if fehler:
            return ServiceResult.fail(fehler)

        try:
            netto, mwst, brutto = berechne_summen(dto.posten, dto.mwst_prozent)

            angebot.angebotsnummer = dto.angebotsnummer.strip()
            angebot.angebotsdatum = dto.angebotsdatum.strip()
            angebot.gueltig_bis = dto.gueltig_bis.strip() or None
            angebot.mwst_prozent = dto.mwst_prozent
            angebot.summe_netto = netto
            angebot.summe_mwst = mwst
            angebot.summe_brutto = brutto
            angebot.bemerkung = dto.bemerkung.strip() or None

            # Alte Posten löschen, neue anlegen
            for p in list(angebot.posten):
                session.delete(p)
            session.flush()

            for i, p in enumerate(dto.posten, start=1):
                gesamt = berechne_gesamtpreis(p.menge, p.einzelpreis_netto)
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
                posten = AngebotsPosten(
                    angebot_id=angebot.id,
                    position=i,
                    artikelnummer=art_nr,
                    beschreibung=p.beschreibung.strip(),
                    menge=p.menge,
                    einheit=p.einheit.strip() or None,
                    einzelpreis_netto=p.einzelpreis_netto,
                    gesamtpreis_netto=gesamt,
                )
                session.add(posten)
            session.flush()

            audit.log(
                session, AuditAction.ANGEBOT_GEAENDERT,
                record_id=angebot.id,
                table_name="angebote",
                details=f"Angebot {angebot.angebotsnummer} aktualisiert.",
            )

            result_dto = AngebotDTO.from_model(angebot, include_posten=True)
            return ServiceResult.ok(result_dto, f"Angebot {angebot.angebotsnummer} gespeichert.")

        except Exception as e:
            logger.exception("Fehler beim Aktualisieren des Angebots")
            return ServiceResult.fail(f"Fehler: {e}")

    def loeschen(
        self, session: Session, angebot_id: int
    ) -> ServiceResult:
        """Löscht ein Angebot und alle zugehörigen Posten."""
        angebot = session.get(Angebot, angebot_id)
        if not angebot:
            return ServiceResult.fail("Angebot nicht gefunden.")

        nr = angebot.angebotsnummer
        try:
            audit.log(
                session, AuditAction.ANGEBOT_GELOESCHT,
                record_id=angebot.id,
                table_name="angebote",
                details=f"Angebot {nr} gelöscht.",
            )
            session.delete(angebot)
            return ServiceResult.ok(message=f"Angebot {nr} gelöscht.")
        except Exception as e:
            logger.exception("Fehler beim Löschen des Angebots")
            return ServiceResult.fail(f"Fehler: {e}")

    def status_aendern(
        self, session: Session, angebot_id: int, neuer_status: str
    ) -> ServiceResult:
        """Ändert den Status eines Angebots."""
        angebot = session.get(Angebot, angebot_id)
        if not angebot:
            return ServiceResult.fail("Angebot nicht gefunden.")

        if neuer_status not in AngebotStatus.ALLE:
            return ServiceResult.fail(f"Ungültiger Status: {neuer_status}")

        alter_status = angebot.status
        angebot.status = neuer_status

        audit.log(
            session, AuditAction.ANGEBOT_STATUS_GEAENDERT,
            record_id=angebot.id,
            table_name="angebote",
            details=f"Status: '{alter_status}' → '{neuer_status}'",
        )

        return ServiceResult.ok(
            message=f"Status von '{alter_status}' auf '{neuer_status}' geändert."
        )

    def bemerkung_aktualisieren(
        self, session: Session, angebot_id: int, bemerkung: str
    ) -> ServiceResult:
        """Aktualisiert die Bemerkung eines Angebots."""
        angebot = session.get(Angebot, angebot_id)
        if not angebot:
            return ServiceResult.fail("Angebot nicht gefunden.")
        angebot.bemerkung = bemerkung.strip() or None
        return ServiceResult.ok(message="Bemerkung gespeichert.")

    # ------------------------------------------------------------------
    # Validierung
    # ------------------------------------------------------------------

    def _validiere(
        self, dto: AngebotDTO, session: Session, exclude_id: Optional[int] = None
    ) -> Optional[str]:
        """Validiert Angebotsdaten. Gibt Fehlermeldung zurück oder None."""
        if not dto.angebotsnummer or not dto.angebotsnummer.strip():
            return "Angebotsnummer ist erforderlich."

        if not dto.angebotsdatum or not dto.angebotsdatum.strip():
            return "Angebotsdatum ist erforderlich."

        # Prüfe Nummern-Eindeutigkeit
        existing = (
            session.query(Angebot)
            .filter_by(angebotsnummer=dto.angebotsnummer.strip())
            .first()
        )
        if existing and (exclude_id is None or existing.id != exclude_id):
            return f"Angebotsnummer '{dto.angebotsnummer}' ist bereits vergeben."

        return None


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
angebote_service = AngebotsService()
