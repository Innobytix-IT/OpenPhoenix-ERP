"""
core/services/mahnwesen_service.py – Business-Logik für Mahnwesen
==================================================================
Verwaltet überfällige Rechnungen, Mahngebühren und die
automatische Stufeneskalation.

Ablauf:
1. pruefe_und_eskaliere()  → aktualisiert Status aller überfälligen Rechnungen
2. mahngebuehr_buchen()    → bucht Mahngebühr auf eine Rechnung
3. uebersicht()            → liefert alle überfälligen Rechnungen gruppiert
"""

import logging
from dataclasses import dataclass, field
from core.services import ServiceResult
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import func

from core.models import Rechnung, Kunde
from core.services.rechnungen_service import (
    RechnungsService, RechnungStatus, RechnungDTO
)
from core.utils import parse_datum
from core.audit.service import audit, AuditAction
from core.config import config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Mahnstufen-Konfiguration
# ---------------------------------------------------------------------------

@dataclass
class MahnKonfig:
    """Konfiguration der Mahnstufen aus config.toml."""
    reminder_days: int   = 7
    mahnung1_days: int   = 21
    mahnung2_days: int   = 35
    inkasso_days: int    = 49
    cost_erinnerung: Decimal = Decimal("0.00")
    cost_mahnung1: Decimal   = Decimal("5.00")
    cost_mahnung2: Decimal   = Decimal("10.00")
    cost_inkasso: Decimal    = Decimal("25.00")

    @classmethod
    def aus_config(cls) -> "MahnKonfig":
        d = config.section("dunning")
        return cls(
            reminder_days   = int(d.get("reminder_days", 7)),
            mahnung1_days   = int(d.get("mahnung1_days", 21)),
            mahnung2_days   = int(d.get("mahnung2_days", 35)),
            inkasso_days    = int(d.get("inkasso_days", 49)),
            cost_erinnerung = Decimal(str(d.get("cost_erinnerung", "0.00"))),
            cost_mahnung1   = Decimal(str(d.get("cost_mahnung1", "5.00"))),
            cost_mahnung2   = Decimal(str(d.get("cost_mahnung2", "10.00"))),
            cost_inkasso    = Decimal(str(d.get("cost_inkasso", "25.00"))),
        )

    def gebuehr_fuer_status(self, status: str) -> Decimal:
        return {
            RechnungStatus.ERINNERUNG: self.cost_erinnerung,
            RechnungStatus.MAHNUNG1:   self.cost_mahnung1,
            RechnungStatus.MAHNUNG2:   self.cost_mahnung2,
            RechnungStatus.INKASSO:    self.cost_inkasso,
        }.get(status, Decimal("0"))


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------

@dataclass
class UeberfaelligeDTO:
    """Angereicherte Rechnung für die Mahnwesen-Übersicht."""
    rechnung_id: int
    rechnungsnummer: str
    rechnungsdatum: str
    faelligkeitsdatum: str
    status: str
    summe_brutto: Decimal
    offener_betrag: Decimal
    mahngebuehren: Decimal
    kunde_id: int
    kunde_name: str
    kunde_vorname: str
    kunde_zifferncode: Optional[int]
    tage_ueberfaellig: int
    naechste_stufe: Optional[str]
    tage_bis_naechste_stufe: Optional[int]

    @property
    def kunde_display(self) -> str:
        return f"{self.kunde_vorname} {self.kunde_name}".strip()

    @property
    def stufen_index(self) -> int:
        """0 = Offen, 1 = Erinnerung, 2 = Mahnung1, 3 = Mahnung2, 4 = Inkasso."""
        return {
            RechnungStatus.OFFEN:      0,
            RechnungStatus.ERINNERUNG: 1,
            RechnungStatus.MAHNUNG1:   2,
            RechnungStatus.MAHNUNG2:   3,
            RechnungStatus.INKASSO:    4,
        }.get(self.status, 0)

    @property
    def gesamtforderung(self) -> Decimal:
        return self.offener_betrag + self.mahngebuehren


@dataclass
class MahnUebersicht:
    """Zusammenfassung aller überfälligen Rechnungen nach Stufe."""
    erinnerung:  list[UeberfaelligeDTO] = field(default_factory=list)
    mahnung1:    list[UeberfaelligeDTO] = field(default_factory=list)
    mahnung2:    list[UeberfaelligeDTO] = field(default_factory=list)
    inkasso:     list[UeberfaelligeDTO] = field(default_factory=list)
    # Rechnungen die noch offen sind aber bald eskalieren
    bald_faellig: list[UeberfaelligeDTO] = field(default_factory=list)

    @property
    def alle(self) -> list[UeberfaelligeDTO]:
        return (
            self.inkasso + self.mahnung2 +
            self.mahnung1 + self.erinnerung
        )

    @property
    def gesamt_anzahl(self) -> int:
        return len(self.alle)

    @property
    def gesamt_betrag(self) -> Decimal:
        return sum(r.gesamtforderung for r in self.alle)

    @property
    def statistik(self) -> dict:
        return {
            "erinnerung":  len(self.erinnerung),
            "mahnung1":    len(self.mahnung1),
            "mahnung2":    len(self.mahnung2),
            "inkasso":     len(self.inkasso),
            "gesamt":      self.gesamt_anzahl,
            "betrag":      self.gesamt_betrag,
            "bald_faellig": len(self.bald_faellig),
        }



# ---------------------------------------------------------------------------
# MahnwesenService
# ---------------------------------------------------------------------------

class MahnwesenService:
    """
    Service für das Mahnwesen.

    Workflow:
    1. pruefe_und_eskaliere() beim App-Start aufrufen
    2. uebersicht() gibt gruppierte Übersicht aller überfälligen Rechnungen
    3. mahngebuehr_buchen() wenn eine Mahnstufe abgerechnet wird
    """

    # ------------------------------------------------------------------
    # Automatische Eskalation
    # ------------------------------------------------------------------

    def pruefe_und_eskaliere(
        self,
        session: Session,
        konfig: Optional[MahnKonfig] = None,
    ) -> dict:
        """
        Prüft alle offenen Rechnungen auf Überfälligkeit und eskaliert
        den Status automatisch. Gibt Statistik zurück.

        Delegiert an rechnungen_service.pruefe_ueberfaellige() und
        reichert das Ergebnis mit Mahngebühren an.
        """
        if konfig is None:
            konfig = MahnKonfig.aus_config()

        from core.services.rechnungen_service import rechnungen_service
        geaendert = rechnungen_service.pruefe_ueberfaellige(
            session,
            reminder_days   = konfig.reminder_days,
            mahnung1_days   = konfig.mahnung1_days,
            mahnung2_days   = konfig.mahnung2_days,
            inkasso_days    = konfig.inkasso_days,
        )

        # Mahngebühren für neu eskalierte Rechnungen automatisch buchen
        auto_gebuehren = 0
        for eintrag in geaendert:
            neuer_status = eintrag["neuer_status"]
            gebuehr = konfig.gebuehr_fuer_status(neuer_status)
            if gebuehr > Decimal("0"):
                result = self.mahngebuehr_buchen(
                    session, eintrag["rechnung_id"], gebuehr,
                    f"Auto-Mahngebühr für {neuer_status}"
                )
                if result.success:
                    auto_gebuehren += 1

        return {
            "eskaliert":      len(geaendert),
            "gebuehren":      auto_gebuehren,
            "details":        geaendert,
        }

    # ------------------------------------------------------------------
    # Übersicht & Analyse
    # ------------------------------------------------------------------

    def uebersicht(
        self,
        session: Session,
        konfig: Optional[MahnKonfig] = None,
    ) -> MahnUebersicht:
        """
        Gibt alle überfälligen Rechnungen gruppiert nach Mahnstufe zurück.
        Enthält auch Rechnungen die in den nächsten 7 Tagen fällig werden.
        """
        if konfig is None:
            konfig = MahnKonfig.aus_config()

        heute = date.today()
        uebersicht = MahnUebersicht()

        # Alle relevanten Rechnungen laden
        rechnungen = (
            session.query(Rechnung)
            .join(Kunde, Rechnung.kunde_id == Kunde.id)
            .filter(
                Rechnung.is_finalized == True,
                Rechnung.status.in_(RechnungStatus.MAHNSTUFEN),
            )
            .order_by(Rechnung.faelligkeitsdatum)
            .all()
        )

        for r in rechnungen:
            faellig = parse_datum(r.faelligkeitsdatum)
            tage = (heute - faellig).days if faellig else 0
            naechste, bis_naechste = self._naechste_stufe(
                r.status, tage, konfig
            )

            dto = UeberfaelligeDTO(
                rechnung_id=r.id,
                rechnungsnummer=r.rechnungsnummer or "",
                rechnungsdatum=r.rechnungsdatum or "",
                faelligkeitsdatum=r.faelligkeitsdatum or "",
                status=r.status or "",
                summe_brutto=Decimal(str(r.summe_brutto or "0")),
                offener_betrag=Decimal(str(r.offener_betrag or "0")),
                mahngebuehren=Decimal(str(r.mahngebuehren or "0")),
                kunde_id=r.kunde_id,
                kunde_name=r.kunde.name or "",
                kunde_vorname=r.kunde.vorname or "",
                kunde_zifferncode=r.kunde.zifferncode,
                tage_ueberfaellig=tage,
                naechste_stufe=naechste,
                tage_bis_naechste_stufe=bis_naechste,
            )

            if r.status == RechnungStatus.ERINNERUNG:
                uebersicht.erinnerung.append(dto)
            elif r.status == RechnungStatus.MAHNUNG1:
                uebersicht.mahnung1.append(dto)
            elif r.status == RechnungStatus.MAHNUNG2:
                uebersicht.mahnung2.append(dto)
            elif r.status == RechnungStatus.INKASSO:
                uebersicht.inkasso.append(dto)

        # Rechnungen die bald fällig werden (nächste 7 Tage)
        bald = date.today() + timedelta(days=7)
        bald_rechnungen = (
            session.query(Rechnung)
            .join(Kunde, Rechnung.kunde_id == Kunde.id)
            .filter(
                Rechnung.is_finalized == True,
                Rechnung.status == RechnungStatus.OFFEN,
                Rechnung.faelligkeitsdatum.isnot(None),
            )
            .all()
        )
        for r in bald_rechnungen:
            faellig = parse_datum(r.faelligkeitsdatum)
            if faellig and date.today() < faellig <= bald:
                tage_bis = (faellig - date.today()).days
                dto = UeberfaelligeDTO(
                    rechnung_id=r.id,
                    rechnungsnummer=r.rechnungsnummer or "",
                    rechnungsdatum=r.rechnungsdatum or "",
                    faelligkeitsdatum=r.faelligkeitsdatum or "",
                    status=r.status or "",
                    summe_brutto=Decimal(str(r.summe_brutto or "0")),
                    offener_betrag=Decimal(str(r.offener_betrag or "0")),
                    mahngebuehren=Decimal("0"),
                    kunde_id=r.kunde_id,
                    kunde_name=r.kunde.name or "",
                    kunde_vorname=r.kunde.vorname or "",
                    kunde_zifferncode=r.kunde.zifferncode,
                    tage_ueberfaellig=-tage_bis,
                    naechste_stufe=RechnungStatus.ERINNERUNG,
                    tage_bis_naechste_stufe=tage_bis + konfig.reminder_days,
                )
                uebersicht.bald_faellig.append(dto)

        return uebersicht

    def zusammenfassung_nach_kunde(
        self, session: Session
    ) -> list[dict]:
        """
        Fasst überfällige Rechnungen pro Kunde zusammen.
        Nützlich um Problemkunden zu identifizieren.
        """
        ueb = self.uebersicht(session)
        kunden: dict[int, dict] = {}

        for dto in ueb.alle:
            kid = dto.kunde_id
            if kid not in kunden:
                kunden[kid] = {
                    "kunde_id":       kid,
                    "kunde_name":     dto.kunde_display,
                    "zifferncode":    dto.kunde_zifferncode,
                    "anzahl":         0,
                    "gesamtbetrag":   Decimal("0"),
                    "hoechste_stufe": dto.status,
                    "stufen_index":   dto.stufen_index,
                }
            k = kunden[kid]
            k["anzahl"] += 1
            k["gesamtbetrag"] += dto.gesamtforderung
            if dto.stufen_index > k["stufen_index"]:
                k["hoechste_stufe"] = dto.status
                k["stufen_index"] = dto.stufen_index

        return sorted(
            kunden.values(),
            key=lambda k: (-k["stufen_index"], -k["gesamtbetrag"])
        )

    # ------------------------------------------------------------------
    # Mahngebühren
    # ------------------------------------------------------------------

    def mahngebuehr_buchen(
        self,
        session: Session,
        rechnung_id: int,
        betrag: Decimal,
        grund: str = "",
    ) -> ServiceResult:
        """
        Bucht eine Mahngebühr auf eine Rechnung.
        Erhöht mahngebuehren und offener_betrag.
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
                "Mahngebühren können nur auf finalisierte Rechnungen gebucht werden."
            )
        if betrag <= Decimal("0"):
            return ServiceResult.fail("Mahngebühr muss größer als 0 sein.")

        try:
            rechnung.mahngebuehren = (
                Decimal(str(rechnung.mahngebuehren or "0")) + betrag
            )
            rechnung.offener_betrag = (
                Decimal(str(rechnung.offener_betrag or "0")) + betrag
            )

            ts = datetime.now().strftime("%d.%m.%Y %H:%M")
            zusatz = (
                f"\n[{ts}] Mahngebühr +{betrag:.2f} € gebucht."
                + (f" Grund: {grund}" if grund else "")
            )
            rechnung.bemerkung = (rechnung.bemerkung or "") + zusatz

            audit.log(
                session, AuditAction.MAHNUNG_ERSTELLT,
                record_id=rechnung_id, table_name="rechnungen",
                details=(
                    f"Mahngebühr {betrag:.2f} € auf Rechnung "
                    f"'{rechnung.rechnungsnummer}' gebucht. {grund}"
                ),
            )
            return ServiceResult.ok(
                message=f"Mahngebühr {betrag:.2f} € gebucht.",
                data={
                    "neue_mahngebuehren": rechnung.mahngebuehren,
                    "neuer_offener_betrag": rechnung.offener_betrag,
                },
            )
        except Exception as e:
            return ServiceResult.fail(f"Datenbankfehler: {e}")

    def mahngebuehr_stornieren(
        self,
        session: Session,
        rechnung_id: int,
        betrag: Decimal,
        grund: str = "",
    ) -> ServiceResult:
        """Storniert eine Mahngebühr (z.B. bei Kulanzentscheid)."""
        rechnung = (
            session.query(Rechnung)
            .filter_by(id=rechnung_id)
            .with_for_update()
            .first()
        )
        if not rechnung:
            return ServiceResult.fail("Rechnung nicht gefunden.")

        aktuelle = Decimal(str(rechnung.mahngebuehren or "0"))
        if betrag > aktuelle:
            return ServiceResult.fail(
                f"Storno-Betrag ({betrag:.2f} €) höher als gebuchte "
                f"Mahngebühren ({aktuelle:.2f} €)."
            )

        try:
            rechnung.mahngebuehren = aktuelle - betrag
            rechnung.offener_betrag = (
                Decimal(str(rechnung.offener_betrag or "0")) - betrag
            )
            ts = datetime.now().strftime("%d.%m.%Y %H:%M")
            rechnung.bemerkung = (rechnung.bemerkung or "") + (
                f"\n[{ts}] Mahngebühr -{betrag:.2f} € storniert."
                + (f" Grund: {grund}" if grund else "")
            )
            audit.log(
                session, AuditAction.MAHNUNG_ERSTELLT,
                record_id=rechnung_id, table_name="rechnungen",
                details=f"Mahngebühr {betrag:.2f} € storniert. {grund}",
            )
            return ServiceResult.ok(
                message=f"Mahngebühr {betrag:.2f} € storniert."
            )
        except Exception as e:
            return ServiceResult.fail(f"Datenbankfehler: {e}")

    # ------------------------------------------------------------------
    # Hilfsmethoden
    # ------------------------------------------------------------------

    def _naechste_stufe(
        self,
        aktueller_status: str,
        tage_ueberfaellig: int,
        konfig: MahnKonfig,
    ) -> tuple[Optional[str], Optional[int]]:
        """
        Berechnet die nächste Mahnstufe und wie viele Tage noch bis dahin.
        Returns (naechste_stufe, tage_bis_naechste) oder (None, None) bei Inkasso.
        """
        grenzen = [
            (konfig.reminder_days,  RechnungStatus.ERINNERUNG),
            (konfig.mahnung1_days,  RechnungStatus.MAHNUNG1),
            (konfig.mahnung2_days,  RechnungStatus.MAHNUNG2),
            (konfig.inkasso_days,   RechnungStatus.INKASSO),
        ]

        for grenze, status in grenzen:
            if tage_ueberfaellig < grenze:
                return status, grenze - tage_ueberfaellig

        return None, None  # Bereits auf Inkasso


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
mahnwesen_service = MahnwesenService()
