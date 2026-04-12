"""
core/services/belege_service.py – Business-Logik für Eingangsrechnungen / Belege
=================================================================================
Verwaltet Eingangsrechnungen (Tankquittungen, Lieferantenrechnungen etc.)
inklusive Dateispeicherung und GoBD-konformem Audit-Logging.
"""

import logging
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from pathlib import Path
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from core.models import EingangsRechnung
from core.services import ServiceResult
from core.audit.service import audit, AuditAction

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Konstanten
# ---------------------------------------------------------------------------

class BelegKategorie:
    """Kategorien für Belege — werden dynamisch aus Unterordnern ergänzt."""

    # Standard-Kategorien (werden beim ersten Start als Ordner angelegt)
    DEFAULTS = [
        "Material", "Kraftstoff", "Bürobedarf", "Werkzeug",
        "Versicherung", "Miete", "Sonstiges",
    ]
    SONSTIGES = "Sonstiges"

    @classmethod
    def alle(cls) -> list[str]:
        """
        Gibt alle verfügbaren Kategorien zurück.
        Liest Unterordner des Belege-Basispfads + Standard-Kategorien.
        Neue manuell angelegte Ordner erscheinen automatisch.
        """
        from core.config import config

        basis = config.get("paths", "belege", "")
        if not basis:
            return list(cls.DEFAULTS)

        basis_pfad = Path(basis)
        if not basis_pfad.exists():
            return list(cls.DEFAULTS)

        # Unterordner = Kategorien
        ordner_kategorien = sorted([
            d.name for d in basis_pfad.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        ])

        # Defaults + Ordner-Kategorien zusammenführen (ohne Duplikate)
        alle = list(cls.DEFAULTS)
        for kat in ordner_kategorien:
            if kat not in alle:
                alle.append(kat)

        return alle

    @classmethod
    def standard_ordner_anlegen(cls, basis_pfad: Path) -> None:
        """Legt Standard-Kategorie-Ordner an falls sie nicht existieren."""
        if not basis_pfad:
            return
        basis_pfad.mkdir(parents=True, exist_ok=True)
        for kat in cls.DEFAULTS:
            (basis_pfad / kat).mkdir(exist_ok=True)


class Zahlungsstatus:
    OFFEN = "Offen"
    BEZAHLT = "Bezahlt"
    ALLE = [OFFEN, BEZAHLT]


# ---------------------------------------------------------------------------
# DTO
# ---------------------------------------------------------------------------

@dataclass
class EingangsRechnungDTO:
    """Datenobjekt für eine Eingangsrechnung / einen Beleg."""
    id: Optional[int]
    datum: str                     # TT.MM.JJJJ
    lieferant: str
    belegnummer: str
    betrag_netto: Decimal
    mwst_satz: Decimal
    mwst_betrag: Decimal
    betrag_brutto: Decimal
    kategorie: str
    bemerkung: str
    zahlungsstatus: str
    beleg_pfad: Optional[str]
    beleg_dateiname: Optional[str]
    is_active: bool = True
    erstellt_am: Optional[str] = None
    geaendert_am: Optional[str] = None

    @classmethod
    def from_model(cls, m: EingangsRechnung) -> "EingangsRechnungDTO":
        return cls(
            id=m.id,
            datum=m.datum or "",
            lieferant=m.lieferant or "",
            belegnummer=m.belegnummer or "",
            betrag_netto=Decimal(str(m.betrag_netto or "0")),
            mwst_satz=Decimal(str(m.mwst_satz or "19")),
            mwst_betrag=Decimal(str(m.mwst_betrag or "0")),
            betrag_brutto=Decimal(str(m.betrag_brutto or "0")),
            kategorie=m.kategorie or "",
            bemerkung=m.bemerkung or "",
            zahlungsstatus=m.zahlungsstatus or "Offen",
            beleg_pfad=m.beleg_pfad,
            beleg_dateiname=m.beleg_dateiname,
            is_active=bool(m.is_active),
            erstellt_am=(
                m.erstellt_am.strftime("%d.%m.%Y %H:%M")
                if m.erstellt_am else ""
            ),
            geaendert_am=(
                m.geaendert_am.strftime("%d.%m.%Y %H:%M")
                if m.geaendert_am else ""
            ),
        )


def _round2(val: Decimal) -> Decimal:
    """Kaufmännisch auf 2 Nachkommastellen runden."""
    return val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _berechne_betraege(
    netto: Decimal, mwst_satz: Decimal
) -> tuple[Decimal, Decimal]:
    """Berechnet MwSt-Betrag und Brutto aus Netto + MwSt-Satz."""
    mwst = _round2(netto * mwst_satz / Decimal("100"))
    brutto = _round2(netto + mwst)
    return mwst, brutto


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class BelegeService:
    """Service für Eingangsrechnungen / Belege."""

    # ------------------------------------------------------------------
    # Lesen
    # ------------------------------------------------------------------

    def alle_belege(
        self,
        session: Session,
        suchtext: str = "",
        kategorie: str = "",
        zahlungsstatus: str = "",
        datum_von: str = "",
        datum_bis: str = "",
        nur_aktive: bool = True,
    ) -> list[EingangsRechnungDTO]:
        """Alle Belege abfragen mit optionalen Filtern."""
        query = session.query(EingangsRechnung)

        if nur_aktive:
            query = query.filter(EingangsRechnung.is_active.is_(True))

        if suchtext:
            like = f"%{suchtext}%"
            query = query.filter(
                or_(
                    EingangsRechnung.lieferant.ilike(like),
                    EingangsRechnung.belegnummer.ilike(like),
                    EingangsRechnung.bemerkung.ilike(like),
                )
            )

        if kategorie:
            query = query.filter(EingangsRechnung.kategorie == kategorie)

        if zahlungsstatus:
            query = query.filter(
                EingangsRechnung.zahlungsstatus == zahlungsstatus
            )

        # Datumsfilter: TT.MM.JJJJ → vergleiche als String
        # Für korrekte Sortierung konvertieren wir intern
        belege = query.all()

        # Datumsfilter in Python (da TT.MM.JJJJ nicht SQL-sortierbar ist)
        if datum_von or datum_bis:
            gefiltert = []
            try:
                von = (
                    datetime.strptime(datum_von, "%d.%m.%Y")
                    if datum_von else None
                )
                bis = (
                    datetime.strptime(datum_bis, "%d.%m.%Y")
                    if datum_bis else None
                )
            except ValueError:
                von = bis = None

            if von or bis:
                for b in belege:
                    try:
                        d = datetime.strptime(b.datum, "%d.%m.%Y")
                    except ValueError:
                        continue
                    if von and d < von:
                        continue
                    if bis and d > bis:
                        continue
                    gefiltert.append(b)
                belege = gefiltert

        # Nach Datum sortieren (neueste zuerst)
        def _sort_key(b):
            try:
                return datetime.strptime(b.datum, "%d.%m.%Y")
            except ValueError:
                return datetime.min

        belege.sort(key=_sort_key, reverse=True)

        return [EingangsRechnungDTO.from_model(b) for b in belege]

    def beleg_nach_id(
        self, session: Session, beleg_id: int
    ) -> Optional[EingangsRechnungDTO]:
        """Einzelnen Beleg laden."""
        b = session.query(EingangsRechnung).get(beleg_id)
        if not b:
            return None
        return EingangsRechnungDTO.from_model(b)

    def statistik(self, session: Session) -> dict:
        """Zusammenfassung für die Stats-Leiste."""
        belege = (
            session.query(EingangsRechnung)
            .filter(EingangsRechnung.is_active.is_(True))
            .all()
        )
        gesamt = len(belege)
        offen = sum(1 for b in belege if b.zahlungsstatus == Zahlungsstatus.OFFEN)
        bezahlt = sum(1 for b in belege if b.zahlungsstatus == Zahlungsstatus.BEZAHLT)
        summe_netto = sum(
            (Decimal(str(b.betrag_netto or 0)) for b in belege),
            Decimal("0")
        )
        summe_brutto = sum(
            (Decimal(str(b.betrag_brutto or 0)) for b in belege),
            Decimal("0")
        )
        return {
            "gesamt": gesamt,
            "offen": offen,
            "bezahlt": bezahlt,
            "summe_netto": _round2(summe_netto),
            "summe_brutto": _round2(summe_brutto),
        }

    # ------------------------------------------------------------------
    # Erstellen
    # ------------------------------------------------------------------

    def beleg_erstellen(
        self,
        session: Session,
        dto: EingangsRechnungDTO,
        datei_bytes: Optional[bytes] = None,
        datei_name: Optional[str] = None,
    ) -> ServiceResult:
        """Neuen Beleg anlegen."""
        fehler = self._validiere(dto)
        if fehler:
            return ServiceResult.fail(fehler)

        mwst, brutto = _berechne_betraege(dto.betrag_netto, dto.mwst_satz)

        # Datei speichern
        beleg_pfad = None
        beleg_dateiname = None
        if datei_bytes and datei_name:
            try:
                beleg_pfad = self._datei_speichern(
                    dto.datum, datei_bytes, datei_name,
                    kategorie=dto.kategorie,
                )
                beleg_dateiname = datei_name
            except OSError as e:
                logger.error(f"Belegdatei konnte nicht gespeichert werden: {e}")
                return ServiceResult.fail(
                    f"Datei konnte nicht gespeichert werden: {e}"
                )

        beleg = EingangsRechnung(
            datum=dto.datum.strip(),
            lieferant=dto.lieferant.strip(),
            belegnummer=dto.belegnummer.strip() if dto.belegnummer else None,
            betrag_netto=dto.betrag_netto,
            mwst_satz=dto.mwst_satz,
            mwst_betrag=mwst,
            betrag_brutto=brutto,
            kategorie=dto.kategorie,
            bemerkung=dto.bemerkung.strip() if dto.bemerkung else None,
            zahlungsstatus=dto.zahlungsstatus or Zahlungsstatus.OFFEN,
            beleg_pfad=beleg_pfad,
            beleg_dateiname=beleg_dateiname,
        )
        session.add(beleg)
        session.flush()

        audit.log(
            session,
            AuditAction.BELEG_ERSTELLT,
            record_id=beleg.id,
            table_name="eingangsrechnungen",
            details=(
                f"Beleg von '{dto.lieferant}' erstellt. "
                f"Netto: {dto.betrag_netto}, Brutto: {brutto}"
            ),
        )

        result_dto = EingangsRechnungDTO.from_model(beleg)
        logger.info(
            f"Beleg erstellt: ID={beleg.id}, Lieferant='{dto.lieferant}', "
            f"Brutto={brutto}"
        )
        return ServiceResult.ok(
            data=result_dto,
            message=f"Beleg von '{dto.lieferant}' erfolgreich erstellt.",
        )

    # ------------------------------------------------------------------
    # Bearbeiten
    # ------------------------------------------------------------------

    def beleg_aktualisieren(
        self,
        session: Session,
        beleg_id: int,
        dto: EingangsRechnungDTO,
        datei_bytes: Optional[bytes] = None,
        datei_name: Optional[str] = None,
    ) -> ServiceResult:
        """Bestehenden Beleg aktualisieren."""
        fehler = self._validiere(dto)
        if fehler:
            return ServiceResult.fail(fehler)

        beleg = session.get(EingangsRechnung, beleg_id)
        if not beleg:
            return ServiceResult.fail("Beleg nicht gefunden.")

        mwst, brutto = _berechne_betraege(dto.betrag_netto, dto.mwst_satz)

        # Änderungen für Audit-Log
        aenderungen = []
        if beleg.lieferant != dto.lieferant.strip():
            aenderungen.append(f"Lieferant: '{beleg.lieferant}' → '{dto.lieferant.strip()}'")
        if beleg.datum != dto.datum.strip():
            aenderungen.append(f"Datum: '{beleg.datum}' → '{dto.datum.strip()}'")
        if Decimal(str(beleg.betrag_netto)) != dto.betrag_netto:
            aenderungen.append(f"Netto: {beleg.betrag_netto} → {dto.betrag_netto}")
        if beleg.kategorie != dto.kategorie:
            aenderungen.append(f"Kategorie: '{beleg.kategorie}' → '{dto.kategorie}'")

        # Felder aktualisieren
        beleg.datum = dto.datum.strip()
        beleg.lieferant = dto.lieferant.strip()
        beleg.belegnummer = dto.belegnummer.strip() if dto.belegnummer else None
        beleg.betrag_netto = dto.betrag_netto
        beleg.mwst_satz = dto.mwst_satz
        beleg.mwst_betrag = mwst
        beleg.betrag_brutto = brutto
        beleg.kategorie = dto.kategorie
        beleg.bemerkung = dto.bemerkung.strip() if dto.bemerkung else None
        beleg.zahlungsstatus = dto.zahlungsstatus or Zahlungsstatus.OFFEN

        # Neue Datei?
        if datei_bytes and datei_name:
            try:
                beleg.beleg_pfad = self._datei_speichern(
                    dto.datum, datei_bytes, datei_name,
                    kategorie=dto.kategorie,
                )
                beleg.beleg_dateiname = datei_name
                aenderungen.append(f"Neue Belegdatei: '{datei_name}'")
            except OSError as e:
                logger.error(f"Belegdatei konnte nicht gespeichert werden: {e}")
                return ServiceResult.fail(
                    f"Datei konnte nicht gespeichert werden: {e}"
                )

        session.flush()

        audit.log(
            session,
            AuditAction.BELEG_GEAENDERT,
            record_id=beleg.id,
            table_name="eingangsrechnungen",
            details="; ".join(aenderungen) if aenderungen else "Keine Änderungen",
        )

        result_dto = EingangsRechnungDTO.from_model(beleg)
        logger.info(f"Beleg aktualisiert: ID={beleg.id}")
        return ServiceResult.ok(
            data=result_dto,
            message="Beleg erfolgreich aktualisiert.",
        )

    # ------------------------------------------------------------------
    # Status ändern
    # ------------------------------------------------------------------

    def zahlungsstatus_setzen(
        self, session: Session, beleg_id: int, neuer_status: str
    ) -> ServiceResult:
        """Zahlungsstatus eines Belegs ändern (Offen ↔ Bezahlt)."""
        beleg = session.get(EingangsRechnung, beleg_id)
        if not beleg:
            return ServiceResult.fail("Beleg nicht gefunden.")

        alter_status = beleg.zahlungsstatus
        if alter_status == neuer_status:
            return ServiceResult.ok(message="Status ist bereits gesetzt.")

        beleg.zahlungsstatus = neuer_status
        session.flush()

        audit.log(
            session,
            AuditAction.BELEG_STATUS_GEAENDERT,
            record_id=beleg.id,
            table_name="eingangsrechnungen",
            details=f"Status: '{alter_status}' → '{neuer_status}'",
        )

        logger.info(
            f"Beleg {beleg.id} Status: {alter_status} → {neuer_status}"
        )
        return ServiceResult.ok(
            message=f"Status auf '{neuer_status}' geändert.",
        )

    # ------------------------------------------------------------------
    # Deaktivieren (Soft-Delete für GoBD)
    # ------------------------------------------------------------------

    def beleg_deaktivieren(
        self, session: Session, beleg_id: int
    ) -> ServiceResult:
        """Beleg als inaktiv markieren (GoBD-konform, kein Löschen)."""
        beleg = session.get(EingangsRechnung, beleg_id)
        if not beleg:
            return ServiceResult.fail("Beleg nicht gefunden.")

        if not beleg.is_active:
            return ServiceResult.fail("Beleg ist bereits deaktiviert.")

        beleg.is_active = False
        session.flush()

        audit.log(
            session,
            AuditAction.BELEG_DEAKTIVIERT,
            record_id=beleg.id,
            table_name="eingangsrechnungen",
            details=f"Beleg von '{beleg.lieferant}' deaktiviert.",
        )

        logger.info(f"Beleg deaktiviert: ID={beleg.id}")
        return ServiceResult.ok(message="Beleg wurde deaktiviert.")

    # ------------------------------------------------------------------
    # Dateiverwaltung
    # ------------------------------------------------------------------

    def _datei_speichern(
        self, datum_str: str, datei_bytes: bytes, datei_name: str,
        kategorie: str = "",
    ) -> str:
        """
        Speichert eine Belegdatei in der Ordnerstruktur belege/Kategorie/JJJJ/MM/.
        Gibt den relativen Pfad zurück.
        """
        basis = self._belege_basispfad()

        # Jahr/Monat aus Datum extrahieren
        try:
            dt = datetime.strptime(datum_str, "%d.%m.%Y")
            jahr = str(dt.year)
            monat = f"{dt.month:02d}"
        except ValueError:
            # Fallback: aktuelles Datum
            now = datetime.now()
            jahr = str(now.year)
            monat = f"{now.month:02d}"

        # Ordnerstruktur: Kategorie/JJJJ/MM/
        if kategorie:
            ziel_ordner = basis / kategorie / jahr / monat
        else:
            ziel_ordner = basis / BelegKategorie.SONSTIGES / jahr / monat
        ziel_ordner.mkdir(parents=True, exist_ok=True)

        # Dateiname-Kollision vermeiden
        datei_pfad = ziel_ordner / datei_name
        if datei_pfad.exists():
            name, ext = os.path.splitext(datei_name)
            zaehler = 1
            while datei_pfad.exists():
                datei_pfad = ziel_ordner / f"{name}_{zaehler}{ext}"
                zaehler += 1

        datei_pfad.write_bytes(datei_bytes)
        logger.info(f"Belegdatei gespeichert: {datei_pfad}")

        # Relativen Pfad zurückgeben (ab belege/)
        return str(datei_pfad.relative_to(basis))

    def beleg_dateipfad_absolut(self, relativer_pfad: str) -> Path:
        """Gibt den absoluten Pfad zu einer Belegdatei zurück."""
        return self._belege_basispfad() / relativer_pfad

    def _belege_basispfad(self) -> Path:
        """Gibt den konfigurierten Basispfad für Belege zurück."""
        from core.config import config

        pfad = config.get("paths", "belege", "")
        if pfad:
            return Path(pfad)

        # Fallback: belege/ neben der Datenbank
        db_pfad = config.get("database", "path", "openphoenix.db")
        return Path(db_pfad).parent / "belege"

    # ------------------------------------------------------------------
    # Validierung
    # ------------------------------------------------------------------

    @staticmethod
    def _validiere(dto: EingangsRechnungDTO) -> str:
        """Validiert ein Beleg-DTO. Gibt Fehlermeldung oder '' zurück."""
        if not dto.datum or not dto.datum.strip():
            return "Datum ist erforderlich."

        # Datumsformat prüfen
        try:
            datetime.strptime(dto.datum.strip(), "%d.%m.%Y")
        except ValueError:
            return "Ungültiges Datumsformat. Erwartet: TT.MM.JJJJ"

        if not dto.lieferant or not dto.lieferant.strip():
            return "Lieferant / Absender ist erforderlich."

        if dto.betrag_netto is None or dto.betrag_netto <= 0:
            return "Nettobetrag muss größer als 0 sein."

        if dto.kategorie not in BelegKategorie.alle():
            return f"Ungültige Kategorie: '{dto.kategorie}'"

        return ""


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
belege_service = BelegeService()
