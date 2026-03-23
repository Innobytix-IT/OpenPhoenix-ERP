"""
core/audit/service.py – GoBD-konformes Audit-Log für OpenPhoenix ERP
=====================================================================
Jede geschäftsrelevante Aktion wird hier protokolliert.
Das Audit-Log ist append-only — es wird nie gelöscht.
"""

import os
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from core.models import AuditLog

logger = logging.getLogger(__name__)


def get_current_user() -> str:
    """Ermittelt den aktuellen Systembenutzer."""
    try:
        return os.getlogin()
    except Exception:
        return os.environ.get("USERNAME") or os.environ.get("USER") or "system"


# ---------------------------------------------------------------------------
# Aktions-Konstanten
# ---------------------------------------------------------------------------

class AuditAction:
    """Alle definierten Audit-Aktionen als Konstanten."""

    # Anwendung
    APP_START = "APP_START"
    APP_END = "APP_END"

    # Kunden
    KUNDE_ERSTELLT = "KUNDE_ERSTELLT"
    KUNDE_GEAENDERT = "KUNDE_GEAENDERT"
    KUNDE_DEAKTIVIERT = "KUNDE_DEAKTIVIERT"
    KUNDE_REAKTIVIERT = "KUNDE_REAKTIVIERT"

    # Rechnungen
    RECHNUNG_ENTWURF_ERSTELLT = "RECHNUNG_ENTWURF_ERSTELLT"
    RECHNUNG_ENTWURF_GEAENDERT = "RECHNUNG_ENTWURF_GEAENDERT"
    RECHNUNG_ENTWURF_GELOESCHT = "RECHNUNG_ENTWURF_GELOESCHT"
    RECHNUNG_FINALISIERT = "RECHNUNG_FINALISIERT"
    RECHNUNG_STATUS_GEAENDERT = "RECHNUNG_STATUS_GEAENDERT"
    RECHNUNG_STATUS_AUTO = "RECHNUNG_STATUS_AUTO"
    RECHNUNG_STORNIERT = "RECHNUNG_STORNIERT"
    GUTSCHRIFT_ERSTELLT    = "GUTSCHRIFT_ERSTELLT"
    TEILZAHLUNG_GEBUCHT    = "TEILZAHLUNG_GEBUCHT"
    SKONTO_GEWAEHRT        = "SKONTO_GEWAEHRT"
    POSITION_KORRIGIERT    = "POSITION_KORRIGIERT"
    MAHNUNG_PDF_ERSTELLT   = "MAHNUNG_PDF_ERSTELLT" 

    # Artikel
    ARTIKEL_ERSTELLT = "ARTIKEL_ERSTELLT"
    ARTIKEL_GEAENDERT = "ARTIKEL_GEAENDERT"
    ARTIKEL_DEAKTIVIERT = "ARTIKEL_DEAKTIVIERT"
    LAGER_GEBUCHT = "LAGER_GEBUCHT"

    # Angebote
    ANGEBOT_ERSTELLT = "ANGEBOT_ERSTELLT"
    ANGEBOT_GEAENDERT = "ANGEBOT_GEAENDERT"
    ANGEBOT_GELOESCHT = "ANGEBOT_GELOESCHT"
    ANGEBOT_STATUS_GEAENDERT = "ANGEBOT_STATUS_GEAENDERT"

    # Notizen
    NOTIZ_ERSTELLT = "NOTIZ_ERSTELLT"
    NOTIZ_GELOESCHT = "NOTIZ_GELOESCHT"

    # Lagerbewegungen
    LAGER_EINGEBUCHT = "LAGER_EINGEBUCHT"
    LAGER_AUSGEBUCHT = "LAGER_AUSGEBUCHT"
    LAGER_KORRIGIERT = "LAGER_KORRIGIERT"
    ARTIKEL_REAKTIVIERT = "ARTIKEL_REAKTIVIERT"

    # Dokumente
    DOKUMENT_ZUGEORDNET = "DOKUMENT_ZUGEORDNET"
    DOKUMENT_GELOESCHT = "DOKUMENT_GELOESCHT"

    # Konfiguration
    KONFIG_GEAENDERT = "KONFIG_GEAENDERT"

    # Mahnwesen
    MAHNUNG_ERSTELLT = "MAHNUNG_ERSTELLT"
    MAHNUNG_GESENDET = "MAHNUNG_GESENDET"

    # Eingangsrechnungen / Belege
    BELEG_ERSTELLT = "BELEG_ERSTELLT"
    BELEG_GEAENDERT = "BELEG_GEAENDERT"
    BELEG_DEAKTIVIERT = "BELEG_DEAKTIVIERT"
    BELEG_STATUS_GEAENDERT = "BELEG_STATUS_GEAENDERT"


# ---------------------------------------------------------------------------
# Audit-Service
# ---------------------------------------------------------------------------

class AuditService:
    """
    Service für GoBD-konforme Audit-Protokollierung.

    Verwendung:
        from core.audit.service import audit

        with db.session() as session:
            audit.log(session, AuditAction.KUNDE_ERSTELLT,
                      record_id=kunde.id,
                      table_name="kunden",
                      details=f"Kunde '{kunde.display_name}' erstellt")
    """

    def __init__(self) -> None:
        self._current_user: str = get_current_user()

    def log(
        self,
        session: Session,
        action: str,
        record_id: Optional[int] = None,
        table_name: Optional[str] = None,
        details: str = "",
        user: Optional[str] = None,
    ) -> None:
        """
        Schreibt einen Eintrag ins Audit-Log.

        Args:
            session:    Aktive Datenbank-Session
            action:     Aktions-Bezeichner (aus AuditAction-Klasse)
            record_id:  ID des betroffenen Datensatzes
            table_name: Name der betroffenen Tabelle
            details:    Freitext-Beschreibung
            user:       Benutzername (Standard: aktueller Systembenutzer)
        """
        entry = AuditLog(
            timestamp=datetime.now(),
            user=user or self._current_user,
            action=action,
            record_id=record_id,
            table_name=table_name,
            details=details,
        )
        session.add(entry)
        # Kein explizites commit — das macht der aufrufende Context-Manager
        logger.debug(
            f"AUDIT | action='{action}' | table='{table_name}' | "
            f"record_id={record_id} | user='{user or self._current_user}'"
        )

    def log_change(
        self,
        session: Session,
        action: str,
        record_id: int,
        table_name: str,
        old_data: dict,
        new_data: dict,
    ) -> None:
        """
        Protokolliert Feldänderungen automatisch.
        Vergleicht old_data und new_data und erstellt eine lesbare Änderungsliste.
        """
        changes = []
        for key, new_val in new_data.items():
            old_val = old_data.get(key)
            old_comp = str(old_val) if old_val is not None else ""
            new_comp = str(new_val) if new_val is not None else ""
            if old_comp != new_comp:
                changes.append(f"'{key}': '{old_comp}' → '{new_comp}'")

        if changes:
            details = "; ".join(changes)
            self.log(session, action, record_id=record_id,
                     table_name=table_name, details=details)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
audit = AuditService()
