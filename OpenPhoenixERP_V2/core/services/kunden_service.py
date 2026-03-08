"""
core/services/kunden_service.py – Business-Logik für Kundenverwaltung
=====================================================================
Alle Operationen auf Kunden und Kundendokumenten.
Kein UI-Code, keine tkinter/PySide6-Imports.
Kann vollständig unabhängig getestet werden.
"""

import os
import shutil
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import or_, func, String, cast

from core.models import Kunde, KundenDokument, KundenNotiz, Rechnung
from core.audit.service import audit, AuditAction

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Daten-Transfer-Objekte (DTOs)
# ---------------------------------------------------------------------------

@dataclass
class KundeDTO:
    """Unveränderliches Datenobjekt für einen Kunden (UI ↔ Service)."""
    id: Optional[int]
    zifferncode: Optional[int]
    anrede: str
    name: str
    vorname: str
    titel_firma: str
    geburtsdatum: str
    strasse: str
    hausnummer: str
    plz: str
    ort: str
    telefon: str
    email: str
    is_active: bool = True

    @classmethod
    def from_model(cls, k: Kunde) -> "KundeDTO":
        return cls(
            id=k.id,
            zifferncode=k.zifferncode,
            anrede=k.anrede or "",
            name=k.name or "",
            vorname=k.vorname or "",
            titel_firma=k.titel_firma or "",
            geburtsdatum=k.geburtsdatum or "",
            strasse=k.strasse or "",
            hausnummer=k.hausnummer or "",
            plz=k.plz or "",
            ort=k.ort or "",
            telefon=k.telefon or "",
            email=k.email or "",
            is_active=k.is_active,
        )

    @property
    def display_name(self) -> str:
        parts = [self.vorname, self.name]
        if self.titel_firma:
            parts.append(f"({self.titel_firma})")
        return " ".join(p for p in parts if p)


@dataclass
class DokumentDTO:
    """Datenobjekt für ein Kundendokument."""
    id: int
    kunde_id: int
    dateiname: str
    dokument_pfad: str
    exists: bool = False

    @classmethod
    def from_model(cls, d: KundenDokument) -> "DokumentDTO":
        return cls(
            id=d.id,
            kunde_id=d.kunde_id,
            dateiname=d.dateiname,
            dokument_pfad=d.dokument_pfad,
            exists=Path(d.dokument_pfad).exists(),
        )


@dataclass
class NotizDTO:
    """Datenobjekt für eine Kundennotiz."""
    id: int
    kunde_id: int
    text: str
    autor: str
    erstellt_am: str  # TT.MM.JJJJ HH:MM

    @classmethod
    def from_model(cls, n) -> "NotizDTO":
        return cls(
            id=n.id,
            kunde_id=n.kunde_id,
            text=n.text,
            autor=n.autor or "",
            erstellt_am=(
                n.erstellt_am.strftime("%d.%m.%Y %H:%M")
                if n.erstellt_am else ""
            ),
        )


@dataclass
class ServiceResult:
    """Rückgabewert jeder Service-Operation."""
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
# KundenService
# ---------------------------------------------------------------------------

class KundenService:
    """
    Service für alle Kunden-Operationen.

    Jede Methode erhält eine Session und gibt ein ServiceResult zurück.
    Die Session-Verwaltung (commit/rollback) liegt beim Aufrufer.

    Beispiel:
        with db.session() as session:
            result = kunden_service.erstellen(session, dto)
            if result.success:
                print(f"Kunde erstellt: {result.data.zifferncode}")
    """

    # ------------------------------------------------------------------
    # Lesen
    # ------------------------------------------------------------------

    def alle(
        self,
        session: Session,
        nur_aktive: bool = True,
        suchtext: str = "",
    ) -> list[KundeDTO]:
        """
        Gibt alle Kunden zurück, optional gefiltert.

        Args:
            nur_aktive: Wenn True, nur aktive Kunden
            suchtext:   Freitextsuche über Name, Vorname, Kundennr., E-Mail, Ort
        """
        query = session.query(Kunde)

        if nur_aktive:
            query = query.filter(Kunde.is_active == True)

        if suchtext:
            like = f"%{suchtext}%"
            query = query.filter(
                or_(
                    Kunde.name.ilike(like),
                    Kunde.vorname.ilike(like),
                    Kunde.titel_firma.ilike(like),
                    Kunde.email.ilike(like),
                    Kunde.ort.ilike(like),
                    Kunde.telefon.ilike(like),
                    cast(Kunde.zifferncode, String).ilike(like),
                )
            )

        kunden = query.order_by(Kunde.name, Kunde.vorname).all()
        return [KundeDTO.from_model(k) for k in kunden]

    def nach_id(self, session: Session, kunde_id: int) -> Optional[KundeDTO]:
        """Gibt einen Kunden anhand der ID zurück."""
        k = session.get(Kunde, kunde_id)
        return KundeDTO.from_model(k) if k else None

    def nach_zifferncode(
        self, session: Session, zifferncode: int
    ) -> Optional[KundeDTO]:
        """Gibt einen Kunden anhand der Kundennummer zurück."""
        k = session.query(Kunde).filter_by(zifferncode=zifferncode).first()
        return KundeDTO.from_model(k) if k else None

    def naechste_kundennummer(self, session: Session) -> int:
        """Berechnet die nächste freie Kundennummer (ab 1001)."""
        result = session.query(func.max(Kunde.zifferncode)).scalar()
        return max(1001, (result or 1000) + 1)

    def offene_rechnungen_anzahl(self, session: Session, kunde_id: int) -> int:
        """Gibt die Anzahl offener Rechnungen eines Kunden zurück."""
        return (
            session.query(Rechnung)
            .filter(
                Rechnung.kunde_id == kunde_id,
                Rechnung.status.notin_(["Bezahlt", "Storniert"]),
            )
            .count()
        )

    # ------------------------------------------------------------------
    # Schreiben
    # ------------------------------------------------------------------

    def erstellen(self, session: Session, dto: KundeDTO) -> ServiceResult:
        """Legt einen neuen Kunden an."""
        # Validierung
        fehler = self._validiere(dto)
        if fehler:
            return ServiceResult.fail(fehler)

        try:
            zifferncode = self.naechste_kundennummer(session)
            kunde = Kunde(
                zifferncode=zifferncode,
                anrede=dto.anrede.strip() or None,
                name=dto.name.strip(),
                vorname=dto.vorname.strip(),
                titel_firma=dto.titel_firma.strip() or None,
                geburtsdatum=dto.geburtsdatum.strip() or None,
                strasse=dto.strasse.strip() or None,
                hausnummer=dto.hausnummer.strip() or None,
                plz=dto.plz.strip() or None,
                ort=dto.ort.strip() or None,
                telefon=dto.telefon.strip() or None,
                email=dto.email.strip() or None,
                is_active=True,
            )
            session.add(kunde)
            session.flush()  # ID generieren ohne commit

            audit.log(
                session,
                AuditAction.KUNDE_ERSTELLT,
                record_id=kunde.id,
                table_name="kunden",
                details=f"Kunde '{kunde.vorname} {kunde.name}' "
                        f"mit Kundennr. {zifferncode} erstellt.",
            )

            logger.info(f"Kunde erstellt: ID={kunde.id}, Nr={zifferncode}")
            return ServiceResult.ok(
                data=KundeDTO.from_model(kunde),
                message=f"Kunde gespeichert. Kundennummer: {zifferncode}",
            )
        except Exception as e:
            logger.exception("Fehler beim Erstellen des Kunden:")
            return ServiceResult.fail(f"Datenbankfehler: {e}")

    def aktualisieren(
        self, session: Session, kunde_id: int, dto: KundeDTO
    ) -> ServiceResult:
        """Aktualisiert einen bestehenden Kunden."""
        fehler = self._validiere(dto)
        if fehler:
            return ServiceResult.fail(fehler)

        kunde = session.get(Kunde, kunde_id)
        if not kunde:
            return ServiceResult.fail(f"Kunde mit ID {kunde_id} nicht gefunden.")

        # Änderungen erfassen für Audit-Log
        old = {
            "anrede": kunde.anrede, "name": kunde.name, "vorname": kunde.vorname,
            "titel_firma": kunde.titel_firma, "geburtsdatum": kunde.geburtsdatum,
            "strasse": kunde.strasse, "hausnummer": kunde.hausnummer,
            "plz": kunde.plz, "ort": kunde.ort,
            "telefon": kunde.telefon, "email": kunde.email,
        }
        new = {
            "anrede": dto.anrede.strip() or None,
            "name": dto.name.strip(), "vorname": dto.vorname.strip(),
            "titel_firma": dto.titel_firma.strip() or None,
            "geburtsdatum": dto.geburtsdatum.strip() or None,
            "strasse": dto.strasse.strip() or None,
            "hausnummer": dto.hausnummer.strip() or None,
            "plz": dto.plz.strip() or None,
            "ort": dto.ort.strip() or None,
            "telefon": dto.telefon.strip() or None,
            "email": dto.email.strip() or None,
        }

        # Keine Änderungen?
        if all(str(old.get(k)) == str(new.get(k)) for k in new):
            return ServiceResult.fail("Keine Änderungen vorgenommen.")

        try:
            for key, value in new.items():
                setattr(kunde, key, value)

            audit.log_change(
                session, AuditAction.KUNDE_GEAENDERT,
                record_id=kunde_id, table_name="kunden",
                old_data=old, new_data=new,
            )

            logger.info(f"Kunde aktualisiert: ID={kunde_id}")
            return ServiceResult.ok(
                data=KundeDTO.from_model(kunde),
                message="Kundendaten aktualisiert.",
            )
        except Exception as e:
            logger.exception(f"Fehler beim Aktualisieren Kunde ID={kunde_id}:")
            return ServiceResult.fail(f"Datenbankfehler: {e}")

    def deaktivieren(self, session: Session, kunde_id: int) -> ServiceResult:
        """Deaktiviert einen Kunden (GoBD: kein echtes Löschen)."""
        kunde = session.get(Kunde, kunde_id)
        if not kunde:
            return ServiceResult.fail("Kunde nicht gefunden.")
        if not kunde.is_active:
            return ServiceResult.fail("Kunde ist bereits inaktiv.")

        offene = self.offene_rechnungen_anzahl(session, kunde_id)

        try:
            kunde.is_active = False
            audit.log(
                session, AuditAction.KUNDE_DEAKTIVIERT,
                record_id=kunde_id, table_name="kunden",
                details=f"Kunde '{kunde.display_name}' deaktiviert. "
                        f"Offene Rechnungen: {offene}",
            )
            return ServiceResult.ok(
                message=f"Kunde deaktiviert.",
                data={"offene_rechnungen": offene},
            )
        except Exception as e:
            return ServiceResult.fail(f"Datenbankfehler: {e}")

    def reaktivieren(self, session: Session, kunde_id: int) -> ServiceResult:
        """Reaktiviert einen deaktivierten Kunden."""
        kunde = session.get(Kunde, kunde_id)
        if not kunde:
            return ServiceResult.fail("Kunde nicht gefunden.")
        if kunde.is_active:
            return ServiceResult.fail("Kunde ist bereits aktiv.")
        try:
            kunde.is_active = True
            audit.log(
                session, AuditAction.KUNDE_REAKTIVIERT,
                record_id=kunde_id, table_name="kunden",
                details=f"Kunde '{kunde.display_name}' reaktiviert.",
            )
            return ServiceResult.ok(message="Kunde reaktiviert.")
        except Exception as e:
            return ServiceResult.fail(f"Datenbankfehler: {e}")

    # ------------------------------------------------------------------
    # Dokumente
    # ------------------------------------------------------------------

    def dokumente(self, session: Session, kunde_id: int) -> list[DokumentDTO]:
        """Gibt alle Dokumente eines Kunden zurück."""
        docs = (
            session.query(KundenDokument)
            .filter_by(kunde_id=kunde_id)
            .order_by(KundenDokument.dateiname)
            .all()
        )
        return [DokumentDTO.from_model(d) for d in docs]

    def dokument_zuordnen(
        self,
        session: Session,
        kunde_id: int,
        quell_pfad: str,
        dokument_basis_pfad: str,
    ) -> ServiceResult:
        """
        Kopiert eine Datei in den Kundenordner und legt einen DB-Eintrag an.

        Args:
            session:              Aktive Datenbank-Session
            kunde_id:             ID des Kunden
            quell_pfad:           Originaldatei (wird kopiert, nicht verschoben)
            dokument_basis_pfad:  Basisordner für alle Kundendokumente
        """
        kunde = session.get(Kunde, kunde_id)
        if not kunde:
            return ServiceResult.fail("Kunde nicht gefunden.")
        if not Path(quell_pfad).exists():
            return ServiceResult.fail(f"Quelldatei nicht gefunden: {quell_pfad}")

        ziel_ordner = self._kunden_ordner(kunde, dokument_basis_pfad)
        if not ziel_ordner:
            return ServiceResult.fail("Dokumentenordner konnte nicht erstellt werden.")

        try:
            original_name = Path(quell_pfad).name
            ziel_pfad = self._eindeutiger_pfad(ziel_ordner, original_name)
            shutil.copy2(quell_pfad, ziel_pfad)

            doc = KundenDokument(
                kunde_id=kunde_id,
                dokument_pfad=str(ziel_pfad),
                dateiname=ziel_pfad.name,
            )
            session.add(doc)
            session.flush()

            audit.log(
                session, AuditAction.DOKUMENT_ZUGEORDNET,
                record_id=kunde_id, table_name="kunden_dokumente",
                details=f"Datei '{ziel_pfad.name}' zugeordnet.",
            )

            return ServiceResult.ok(
                data=DokumentDTO.from_model(doc),
                message=f"Dokument '{original_name}' zugeordnet.",
            )
        except Exception as e:
            logger.exception("Fehler beim Zuordnen des Dokuments:")
            return ServiceResult.fail(f"Fehler: {e}")

    def dokument_loeschen(
        self, session: Session, dokument_id: int
    ) -> ServiceResult:
        """Löscht einen Dokument-Eintrag und die Datei (falls vorhanden)."""
        doc = session.get(KundenDokument, dokument_id)
        if not doc:
            return ServiceResult.fail("Dokument nicht gefunden.")

        dateiname = doc.dateiname
        pfad = Path(doc.dokument_pfad)
        datei_geloescht = False

        try:
            if pfad.exists():
                pfad.unlink()
                datei_geloescht = True

            audit.log(
                session, AuditAction.DOKUMENT_GELOESCHT,
                record_id=doc.kunde_id, table_name="kunden_dokumente",
                details=f"Dokument '{dateiname}' entfernt. Datei gelöscht: {datei_geloescht}",
            )
            session.delete(doc)

            msg = f"'{dateiname}' gelöscht."
            if not datei_geloescht:
                msg += " (Datei war bereits nicht mehr vorhanden.)"
            return ServiceResult.ok(message=msg)

        except Exception as e:
            logger.exception("Fehler beim Löschen des Dokuments:")
            return ServiceResult.fail(f"Fehler: {e}")

    # ------------------------------------------------------------------
    # Hilfsmethoden (privat)
    # ------------------------------------------------------------------

    def _validiere(self, dto: KundeDTO) -> str:
        """Validiert die Kundendaten. Gibt Fehlermeldung oder '' zurück."""
        if not dto.name.strip():
            return "Name ist ein Pflichtfeld."
        if not dto.vorname.strip():
            return "Vorname ist ein Pflichtfeld."
        if dto.geburtsdatum.strip():
            try:
                datetime.strptime(dto.geburtsdatum.strip(), "%d.%m.%Y")
            except ValueError:
                return "Geburtsdatum muss im Format TT.MM.JJJJ eingegeben werden."
        if dto.email.strip() and "@" not in dto.email:
            return "Die E-Mail-Adresse scheint ungültig zu sein."
        return ""

    def kunden_ordner_pfad(
        self, session: Session, kunde_id: int
    ) -> Optional[Path]:
        """
        Gibt den Kundenordner-Pfad zurück und erstellt ihn wenn nötig.
        Nutzt ausschließlich config paths.documents als Basis.
        Alle Module (PDF, XRechnung, DMS) sollen diese Methode verwenden.
        """
        from core.config import config as _config
        basis = _config.get("paths", "documents", "")
        if not basis:
            return None
        kunde = session.get(Kunde, kunde_id)
        if not kunde:
            return None
        return self._kunden_ordner(kunde, basis)

    def dokument_in_kundenordner_erstellen(
        self,
        session: Session,
        kunde_id: int,
        dateiname: str,
        dateiinhalt: bytes,
    ) -> Optional[Path]:
        """
        Schreibt eine Datei direkt in den Kundenordner und legt einen
        DMS-Eintrag an. Gibt den finalen Dateipfad zurück oder None.
        Zentrale Methode für PDF und XRechnung.
        """
        ordner = self.kunden_ordner_pfad(session, kunde_id)
        if not ordner:
            return None
        ziel_pfad = self._eindeutiger_pfad(ordner, dateiname)
        try:
            ziel_pfad.write_bytes(dateiinhalt)

            doc = KundenDokument(
                kunde_id=kunde_id,
                dokument_pfad=str(ziel_pfad),
                dateiname=ziel_pfad.name,
            )
            session.add(doc)
            session.flush()

            audit.log(
                session, AuditAction.DOKUMENT_ZUGEORDNET,
                record_id=kunde_id, table_name="kunden_dokumente",
                details=f"Datei '{ziel_pfad.name}' automatisch erstellt.",
            )
            return ziel_pfad
        except Exception as e:
            logger.exception(f"Fehler beim Erstellen der Datei '{dateiname}':")
            return None

    def _kunden_ordner(
        self, kunde: Kunde, basis_pfad: str
    ) -> Optional[Path]:
        """Erstellt den Kundenordner und gibt ihn zurück."""
        if not basis_pfad or not kunde.zifferncode:
            return None
        # Anführungszeichen entfernen (Windows config.toml-Schutz)
        basis_pfad = basis_pfad.strip('"').strip("'")
        ordner = Path(basis_pfad) / "Kundendokumente" / str(kunde.zifferncode)
        try:
            ordner.mkdir(parents=True, exist_ok=True)
            return ordner
        except OSError as e:
            logger.error(f"Kundenordner konnte nicht erstellt werden: {e}")
            return None

    def _eindeutiger_pfad(self, ordner: Path, dateiname: str) -> Path:
        """Gibt einen eindeutigen Ziel-Pfad zurück (fügt ggf. _1, _2 an)."""
        ziel = ordner / dateiname
        if not ziel.exists():
            return ziel
        stem = Path(dateiname).stem
        suffix = Path(dateiname).suffix
        counter = 1
        while ziel.exists() and counter < 1000:
            ziel = ordner / f"{stem}_{counter}{suffix}"
            counter += 1
        return ziel

    # ------------------------------------------------------------------
    # CRM-Notizen
    # ------------------------------------------------------------------

    def notizen(self, session: Session, kunde_id: int) -> list:
        """Lädt alle Notizen eines Kunden, neueste zuerst."""
        result = (
            session.query(KundenNotiz)
            .filter_by(kunde_id=kunde_id)
            .order_by(KundenNotiz.erstellt_am.desc())
            .all()
        )
        return [NotizDTO.from_model(n) for n in result]

    def notiz_hinzufuegen(
        self, session: Session, kunde_id: int, text: str, autor: str = ""
    ) -> ServiceResult:
        """Legt eine neue Notiz an."""
        text = text.strip()
        if not text:
            return ServiceResult.fail("Notiztext darf nicht leer sein.")
        kunde = session.get(Kunde, kunde_id)
        if not kunde:
            return ServiceResult.fail("Kunde nicht gefunden.")
        notiz = KundenNotiz(kunde_id=kunde_id, text=text, autor=autor or None)
        session.add(notiz)
        session.flush()
        return ServiceResult.ok(
            data=NotizDTO.from_model(notiz),
            message="Notiz gespeichert.",
        )

    def notiz_loeschen(self, session: Session, notiz_id: int) -> ServiceResult:
        """Löscht eine Notiz."""
        notiz = session.get(KundenNotiz, notiz_id)
        if not notiz:
            return ServiceResult.fail("Notiz nicht gefunden.")
        session.delete(notiz)
        return ServiceResult.ok(message="Notiz gelöscht.")


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
kunden_service = KundenService()