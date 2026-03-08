"""
core/services/lager_service.py – Business-Logik für Lagerverwaltung
====================================================================
Verwaltet den Artikelstamm und alle Lagerbewegungen.
Jede Bestandsänderung erzeugt einen unveränderlichen Buchungssatz.

Buchungsarten:
    "Eingang"          – manuelle Einbuchung (Lieferung, Erstbestand)
    "Ausgang"          – manuelle Ausbuchung (Verlust, Verbrauch)
    "Korrektur"        – manuelle Bestandskorrektur auf einen Zielwert
    "Rechnungsabgang"  – automatisch beim Finalisieren einer Rechnung
    "Stornoeingang"    – automatisch beim Stornieren einer Rechnung
"""

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from core.models import Artikel, LagerBewegung
from core.audit.service import audit, AuditAction

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Buchungsarten-Konstanten
# ---------------------------------------------------------------------------

class Buchungsart:
    EINGANG         = "Eingang"
    AUSGANG         = "Ausgang"
    KORREKTUR       = "Korrektur"
    RECHNUNGSABGANG = "Rechnungsabgang"
    STORNOEINGANG   = "Stornoeingang"

    ALLE = [EINGANG, AUSGANG, KORREKTUR, RECHNUNGSABGANG, STORNOEINGANG]
    MANUELL = [EINGANG, AUSGANG, KORREKTUR]


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------

@dataclass
class ArtikelDTO:
    """Datenobjekt für einen Artikel."""
    id: Optional[int]
    artikelnummer: str
    beschreibung: str
    einheit: str
    einzelpreis_netto: Decimal
    verfuegbar: Decimal
    is_active: bool = True
    erstellt_am: Optional[str] = None

    @classmethod
    def from_model(cls, a: Artikel) -> "ArtikelDTO":
        return cls(
            id=a.id,
            artikelnummer=a.artikelnummer or "",
            beschreibung=a.beschreibung or "",
            einheit=a.einheit or "",
            einzelpreis_netto=Decimal(str(a.einzelpreis_netto or "0")),
            verfuegbar=Decimal(str(a.verfuegbar or "0")),
            is_active=bool(a.is_active),
            erstellt_am=(
                a.erstellt_am.strftime("%d.%m.%Y %H:%M")
                if a.erstellt_am else ""
            ),
        )

    @property
    def bestand_anzeige(self) -> str:
        """Gibt Bestand mit Einheit formatiert zurück."""
        # Decimal :g gibt zu viele Stellen aus → float konvertieren
        v = float(self.verfuegbar)
        s = f"{v:g}"
        if self.einheit:
            return f"{s} {self.einheit}"
        return s

    @property
    def bestand_kritisch(self) -> bool:
        """True wenn Bestand unter 5 liegt (einfache Warnschwelle)."""
        return self.verfuegbar <= Decimal("5")

    @property
    def bestand_negativ(self) -> bool:
        return self.verfuegbar < Decimal("0")


@dataclass
class BewegungDTO:
    """Datenobjekt für eine Lagerbewegung."""
    id: int
    artikelnummer: str
    buchungsart: str
    menge: Decimal
    bestand_vor: Decimal
    bestand_nach: Decimal
    referenz: str
    notiz: str
    user: str
    erstellt_am: str

    @classmethod
    def from_model(cls, b: LagerBewegung) -> "BewegungDTO":
        return cls(
            id=b.id,
            artikelnummer=b.artikelnummer or "",
            buchungsart=b.buchungsart or "",
            menge=Decimal(str(b.menge)),
            bestand_vor=Decimal(str(b.bestand_vor)),
            bestand_nach=Decimal(str(b.bestand_nach)),
            referenz=b.referenz or "",
            notiz=b.notiz or "",
            user=b.user or "",
            erstellt_am=(
                b.erstellt_am.strftime("%d.%m.%Y %H:%M")
                if b.erstellt_am else ""
            ),
        )

    @property
    def menge_anzeige(self) -> str:
        """+5 für Eingang, -3 für Ausgang."""
        m = float(self.menge)
        if self.buchungsart in (Buchungsart.EINGANG, Buchungsart.STORNOEINGANG):
            return f"+{m:g}"
        elif self.buchungsart in (Buchungsart.AUSGANG, Buchungsart.RECHNUNGSABGANG):
            return f"-{abs(m):g}"
        else:  # Korrektur
            diff = float(self.bestand_nach - self.bestand_vor)
            return f"+{diff:g}" if diff >= 0 else f"{diff:g}"


@dataclass
class ServiceResult:
    success: bool
    message: str = ""
    data: object = None

    @classmethod
    def ok(cls, data=None, message: str = "") -> "ServiceResult":
        return cls(success=True, message=message, data=data)

    @classmethod
    def fail(cls, message: str) -> "ServiceResult":
        return cls(success=False, message=message)


# ---------------------------------------------------------------------------
# LagerService
# ---------------------------------------------------------------------------

class LagerService:
    """
    Service für Artikelstamm und Lagerbewegungen.

    Kernprinzip: Jede Bestandsänderung erzeugt einen LagerBewegung-Datensatz.
    Der Bestand in `artikel.verfuegbar` ist immer der aktuelle Stand.
    Die lager_bewegungen-Tabelle ist die unveränderliche Buchungshistorie.
    """

    # ------------------------------------------------------------------
    # Artikel lesen
    # ------------------------------------------------------------------

    def alle_artikel(
        self,
        session: Session,
        nur_aktive: bool = True,
        suchtext: str = "",
    ) -> list[ArtikelDTO]:
        """Gibt alle Artikel zurück, optional gefiltert."""
        query = session.query(Artikel)
        if nur_aktive:
            query = query.filter(Artikel.is_active == True)
        if suchtext:
            like = f"%{suchtext}%"
            query = query.filter(
                or_(
                    Artikel.artikelnummer.ilike(like),
                    Artikel.beschreibung.ilike(like),
                    Artikel.einheit.ilike(like),
                )
            )
        return [
            ArtikelDTO.from_model(a)
            for a in query.order_by(Artikel.beschreibung).all()
        ]

    def artikel_nach_id(
        self, session: Session, artikel_id: int
    ) -> Optional[ArtikelDTO]:
        a = session.get(Artikel, artikel_id)
        return ArtikelDTO.from_model(a) if a else None

    def artikel_nach_nummer(
        self, session: Session, artikelnummer: str
    ) -> Optional[ArtikelDTO]:
        a = session.query(Artikel).filter_by(artikelnummer=artikelnummer).first()
        return ArtikelDTO.from_model(a) if a else None

    def artikel_statistik(self, session: Session) -> dict:
        """Gibt Übersichtszahlen für das Dashboard zurück."""
        gesamt = session.query(func.count(Artikel.id)).scalar() or 0
        aktiv = (
            session.query(func.count(Artikel.id))
            .filter(Artikel.is_active == True)
            .scalar() or 0
        )
        negativ = (
            session.query(func.count(Artikel.id))
            .filter(Artikel.is_active == True, Artikel.verfuegbar < 0)
            .scalar() or 0
        )
        kritisch = (
            session.query(func.count(Artikel.id))
            .filter(
                Artikel.is_active == True,
                Artikel.verfuegbar >= 0,
                Artikel.verfuegbar <= 5,
            )
            .scalar() or 0
        )
        lagerwert = (
            session.query(
                func.sum(Artikel.verfuegbar * Artikel.einzelpreis_netto)
            )
            .filter(Artikel.is_active == True, Artikel.verfuegbar > 0)
            .scalar() or Decimal("0")
        )
        return {
            "gesamt":    gesamt,
            "aktiv":     aktiv,
            "negativ":   negativ,
            "kritisch":  kritisch,
            "lagerwert": Decimal(str(lagerwert)),
        }

    # ------------------------------------------------------------------
    # Artikel erstellen / bearbeiten
    # ------------------------------------------------------------------

    def artikel_erstellen(
        self, session: Session, dto: ArtikelDTO
    ) -> ServiceResult:
        """Legt einen neuen Artikel an."""
        fehler = self._validiere_artikel(dto)
        if fehler:
            return ServiceResult.fail(fehler)

        existing = session.query(Artikel).filter_by(
            artikelnummer=dto.artikelnummer.strip()
        ).first()
        if existing:
            return ServiceResult.fail(
                f"Artikelnummer '{dto.artikelnummer}' ist bereits vergeben."
            )

        try:
            artikel = Artikel(
                artikelnummer=dto.artikelnummer.strip(),
                beschreibung=dto.beschreibung.strip(),
                einheit=dto.einheit.strip() or None,
                einzelpreis_netto=dto.einzelpreis_netto,
                verfuegbar=dto.verfuegbar,
                is_active=True,
            )
            session.add(artikel)
            session.flush()

            # Anfangsbestand als Lagerbewegung buchen
            if dto.verfuegbar != Decimal("0"):
                self._bewegung_buchen(
                    session,
                    artikelnummer=dto.artikelnummer.strip(),
                    buchungsart=Buchungsart.EINGANG,
                    menge=dto.verfuegbar,
                    bestand_vor=Decimal("0"),
                    bestand_nach=dto.verfuegbar,
                    referenz="Erstbestand",
                )

            audit.log(
                session, AuditAction.ARTIKEL_ERSTELLT,
                record_id=artikel.id, table_name="artikel",
                details=(
                    f"Artikel '{dto.artikelnummer}' erstellt. "
                    f"Anfangsbestand: {dto.verfuegbar} {dto.einheit}"
                ),
            )
            return ServiceResult.ok(
                data=ArtikelDTO.from_model(artikel),
                message=f"Artikel '{dto.artikelnummer}' erstellt.",
            )
        except Exception as e:
            logger.exception("Fehler beim Erstellen des Artikels:")
            return ServiceResult.fail(f"Datenbankfehler: {e}")

    def artikel_aktualisieren(
        self, session: Session, artikel_id: int, dto: ArtikelDTO
    ) -> ServiceResult:
        """Aktualisiert Stammdaten eines Artikels (nicht den Bestand)."""
        artikel = session.get(Artikel, artikel_id)
        if not artikel:
            return ServiceResult.fail("Artikel nicht gefunden.")

        fehler = self._validiere_artikel(dto, exclude_id=artikel_id)
        if fehler:
            return ServiceResult.fail(fehler)

        # Artikelnummer darf nicht geändert werden wenn in Rechnungen
        if artikel.artikelnummer != dto.artikelnummer.strip():
            if artikel.rechnungsposten:
                return ServiceResult.fail(
                    "Artikelnummer kann nicht geändert werden, "
                    "da der Artikel bereits in Rechnungen verwendet wird."
                )

        try:
            artikel.artikelnummer = dto.artikelnummer.strip()
            artikel.beschreibung = dto.beschreibung.strip()
            artikel.einheit = dto.einheit.strip() or None
            artikel.einzelpreis_netto = dto.einzelpreis_netto

            audit.log(
                session, AuditAction.ARTIKEL_GEAENDERT,
                record_id=artikel_id, table_name="artikel",
                details=f"Artikel '{artikel.artikelnummer}' Stammdaten aktualisiert.",
            )
            return ServiceResult.ok(
                data=ArtikelDTO.from_model(artikel),
                message="Artikel aktualisiert.",
            )
        except Exception as e:
            return ServiceResult.fail(f"Datenbankfehler: {e}")

    def artikel_deaktivieren(
        self, session: Session, artikel_id: int
    ) -> ServiceResult:
        """Deaktiviert einen Artikel. GoBD: kein Löschen."""
        artikel = session.get(Artikel, artikel_id)
        if not artikel:
            return ServiceResult.fail("Artikel nicht gefunden.")
        if not artikel.is_active:
            return ServiceResult.fail("Artikel ist bereits inaktiv.")
        try:
            artikel.is_active = False
            audit.log(
                session, AuditAction.ARTIKEL_DEAKTIVIERT,
                record_id=artikel_id, table_name="artikel",
                details=f"Artikel '{artikel.artikelnummer}' deaktiviert.",
            )
            return ServiceResult.ok(
                message=f"Artikel '{artikel.artikelnummer}' deaktiviert."
            )
        except Exception as e:
            return ServiceResult.fail(f"Datenbankfehler: {e}")

    def artikel_reaktivieren(
        self, session: Session, artikel_id: int
    ) -> ServiceResult:
        """Reaktiviert einen deaktivierten Artikel."""
        artikel = session.get(Artikel, artikel_id)
        if not artikel:
            return ServiceResult.fail("Artikel nicht gefunden.")
        if artikel.is_active:
            return ServiceResult.fail("Artikel ist bereits aktiv.")
        try:
            artikel.is_active = True
            audit.log(
                session, AuditAction.ARTIKEL_GEAENDERT,
                record_id=artikel_id, table_name="artikel",
                details=f"Artikel '{artikel.artikelnummer}' reaktiviert.",
            )
            return ServiceResult.ok(message="Artikel reaktiviert.")
        except Exception as e:
            return ServiceResult.fail(f"Datenbankfehler: {e}")

    # ------------------------------------------------------------------
    # Lagerbewegungen
    # ------------------------------------------------------------------

    def einbuchen(
        self,
        session: Session,
        artikelnummer: str,
        menge: Decimal,
        referenz: str = "",
        notiz: str = "",
    ) -> ServiceResult:
        """Bucht eine Menge auf einen Artikel ein (Wareneingang)."""
        if menge <= Decimal("0"):
            return ServiceResult.fail("Menge muss größer als 0 sein.")

        artikel = session.query(Artikel).filter_by(
            artikelnummer=artikelnummer
        ).first()
        if not artikel:
            return ServiceResult.fail(f"Artikel '{artikelnummer}' nicht gefunden.")

        try:
            bestand_vor = Decimal(str(artikel.verfuegbar))
            bestand_nach = bestand_vor + menge
            artikel.verfuegbar = bestand_nach

            self._bewegung_buchen(
                session,
                artikelnummer=artikelnummer,
                buchungsart=Buchungsart.EINGANG,
                menge=menge,
                bestand_vor=bestand_vor,
                bestand_nach=bestand_nach,
                referenz=referenz,
                notiz=notiz,
            )
            audit.log(
                session, AuditAction.LAGER_GEBUCHT,
                table_name="artikel",
                details=(
                    f"Eingang: {artikelnummer} +{menge} "
                    f"(Bestand: {bestand_vor} → {bestand_nach}) "
                    f"Ref: {referenz or '–'}"
                ),
            )
            return ServiceResult.ok(
                data=ArtikelDTO.from_model(artikel),
                message=(
                    f"+{menge:g} {artikel.einheit or ''} eingebucht. "
                    f"Neuer Bestand: {bestand_nach:g} {artikel.einheit or ''}".strip()
                ),
            )
        except Exception as e:
            return ServiceResult.fail(f"Datenbankfehler: {e}")

    def ausbuchen(
        self,
        session: Session,
        artikelnummer: str,
        menge: Decimal,
        referenz: str = "",
        notiz: str = "",
    ) -> ServiceResult:
        """Bucht eine Menge aus einem Artikel aus (Verbrauch, Verlust)."""
        if menge <= Decimal("0"):
            return ServiceResult.fail("Menge muss größer als 0 sein.")

        artikel = session.query(Artikel).filter_by(
            artikelnummer=artikelnummer
        ).first()
        if not artikel:
            return ServiceResult.fail(f"Artikel '{artikelnummer}' nicht gefunden.")

        try:
            bestand_vor = Decimal(str(artikel.verfuegbar))
            bestand_nach = bestand_vor - menge
            artikel.verfuegbar = bestand_nach

            self._bewegung_buchen(
                session,
                artikelnummer=artikelnummer,
                buchungsart=Buchungsart.AUSGANG,
                menge=menge,
                bestand_vor=bestand_vor,
                bestand_nach=bestand_nach,
                referenz=referenz,
                notiz=notiz,
            )
            audit.log(
                session, AuditAction.LAGER_GEBUCHT,
                table_name="artikel",
                details=(
                    f"Ausgang: {artikelnummer} -{menge} "
                    f"(Bestand: {bestand_vor} → {bestand_nach}) "
                    f"Ref: {referenz or '–'}"
                ),
            )
            warnung = ""
            if bestand_nach < 0:
                warnung = " ⚠ Bestand ist jetzt negativ!"
            elif bestand_nach <= 5:
                warnung = " ⚠ Bestand ist kritisch niedrig."

            return ServiceResult.ok(
                data=ArtikelDTO.from_model(artikel),
                message=(
                    f"-{menge:g} {artikel.einheit or ''} ausgebucht. "
                    f"Neuer Bestand: {bestand_nach:g} {artikel.einheit or ''}"
                    + warnung
                ).strip(),
            )
        except Exception as e:
            return ServiceResult.fail(f"Datenbankfehler: {e}")

    def korrektur(
        self,
        session: Session,
        artikelnummer: str,
        neuer_bestand: Decimal,
        notiz: str = "",
    ) -> ServiceResult:
        """
        Setzt den Bestand auf einen exakten Wert (z.B. nach Inventur).
        Bucht die Differenz als Korrektur.
        """
        artikel = session.query(Artikel).filter_by(
            artikelnummer=artikelnummer
        ).first()
        if not artikel:
            return ServiceResult.fail(f"Artikel '{artikelnummer}' nicht gefunden.")

        try:
            bestand_vor = Decimal(str(artikel.verfuegbar))
            differenz = neuer_bestand - bestand_vor
            artikel.verfuegbar = neuer_bestand

            self._bewegung_buchen(
                session,
                artikelnummer=artikelnummer,
                buchungsart=Buchungsart.KORREKTUR,
                menge=abs(differenz),
                bestand_vor=bestand_vor,
                bestand_nach=neuer_bestand,
                referenz="Manuelle Korrektur",
                notiz=notiz or f"Differenz: {differenz:+g}",
            )
            audit.log(
                session, AuditAction.LAGER_GEBUCHT,
                table_name="artikel",
                details=(
                    f"Korrektur: {artikelnummer} "
                    f"{bestand_vor} → {neuer_bestand} (Δ {differenz:+g})"
                ),
            )
            vorzeichen = "+" if differenz >= 0 else ""
            return ServiceResult.ok(
                data=ArtikelDTO.from_model(artikel),
                message=(
                    f"Bestand korrigiert: {bestand_vor:g} → {neuer_bestand:g} "
                    f"({vorzeichen}{differenz:g})"
                ),
            )
        except Exception as e:
            return ServiceResult.fail(f"Datenbankfehler: {e}")

    # ------------------------------------------------------------------
    # Bewegungshistorie lesen
    # ------------------------------------------------------------------

    def bewegungen(
        self,
        session: Session,
        artikelnummer: Optional[str] = None,
        buchungsart: Optional[str] = None,
        limit: int = 200,
    ) -> list[BewegungDTO]:
        """Gibt Lagerbewegungen zurück, optional gefiltert."""
        query = session.query(LagerBewegung)
        if artikelnummer:
            query = query.filter_by(artikelnummer=artikelnummer)
        if buchungsart:
            query = query.filter_by(buchungsart=buchungsart)
        bewegungen = (
            query
            .order_by(LagerBewegung.erstellt_am.desc())
            .limit(limit)
            .all()
        )
        return [BewegungDTO.from_model(b) for b in bewegungen]

    # ------------------------------------------------------------------
    # Interne Hilfsmethoden
    # ------------------------------------------------------------------

    def _bewegung_buchen(
        self,
        session: Session,
        artikelnummer: str,
        buchungsart: str,
        menge: Decimal,
        bestand_vor: Decimal,
        bestand_nach: Decimal,
        referenz: str = "",
        notiz: str = "",
    ) -> None:
        """Schreibt einen LagerBewegung-Datensatz."""
        try:
            user = os.getlogin()
        except Exception:
            user = os.environ.get("USERNAME") or os.environ.get("USER") or "system"

        b = LagerBewegung(
            artikelnummer=artikelnummer,
            buchungsart=buchungsart,
            menge=menge,
            bestand_vor=bestand_vor,
            bestand_nach=bestand_nach,
            referenz=referenz or None,
            notiz=notiz or None,
            user=user,
        )
        session.add(b)

    def _validiere_artikel(
        self, dto: ArtikelDTO, exclude_id: Optional[int] = None
    ) -> str:
        """Gibt Fehlermeldung zurück oder ''."""
        if not dto.artikelnummer.strip():
            return "Artikelnummer ist ein Pflichtfeld."
        if len(dto.artikelnummer.strip()) > 50:
            return "Artikelnummer darf maximal 50 Zeichen haben."
        if not dto.beschreibung.strip():
            return "Beschreibung ist ein Pflichtfeld."
        if dto.einzelpreis_netto < Decimal("0"):
            return "Der Einzelpreis darf nicht negativ sein."
        return ""


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
lager_service = LagerService()
