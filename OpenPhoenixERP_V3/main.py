"""
main.py – Einstiegspunkt für OpenPhoenix ERP v3
================================================
Startet die Anwendung, initialisiert Datenbank und UI.
"""

import sys
import logging
from pathlib import Path

# ---------------------------------------------------------------------------
# Logging früh konfigurieren (vor allen anderen Imports)
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[
        logging.FileHandler("openphoenix.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("openphoenix")

# ---------------------------------------------------------------------------
# PySide6 High-DPI aktivieren (vor QApplication)
# ---------------------------------------------------------------------------
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

QApplication.setHighDpiScaleFactorRoundingPolicy(
    Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
)


def main() -> int:
    """Hauptfunktion – gibt Exit-Code zurück."""
    logger.info("=" * 60)
    logger.info("OpenPhoenix ERP v3.0.0 startet...")
    logger.info("=" * 60)

    app = QApplication(sys.argv)
    app.setApplicationName("OpenPhoenix ERP")
    app.setApplicationVersion("3.0.0")
    app.setOrganizationName("OpenPhoenix")

    # --- Theme anwenden ---
    from ui.theme.theme import apply_theme
    apply_theme(app)

    # --- Konfiguration laden ---
    from core.config import config
    logger.info(f"Konfiguration geladen: {config.path}")
    logger.info(f"Datenbankmodus: {config.get('database', 'mode')}")

    # --- Datenbank initialisieren ---
    from core.db.engine import db
    database_url = config.get_database_url()

    try:
        db.initialize(database_url, echo=False)

        if not db.test_connection():
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(
                None,
                "Datenbankfehler",
                f"Verbindung zur Datenbank fehlgeschlagen:\n{database_url}\n\n"
                "Bitte prüfen Sie die Konfiguration."
            )
            return 1

        # Alle Tabellen sicherstellen (idempotent)
        # Modelle importieren damit Base sie kennt
        import core.models  # noqa: F401
        db.create_all_tables()
        logger.info("Datenbank bereit.")

    except Exception as e:
        logger.exception("Kritischer Fehler bei Datenbank-Initialisierung:")
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(
            None,
            "Kritischer Fehler",
            f"Die Anwendung konnte nicht gestartet werden:\n{e}"
        )
        return 1

    # --- Audit-Log: App-Start ---
    try:
        from core.audit.service import audit, AuditAction
        with db.session() as session:
            audit.log(session, AuditAction.APP_START,
                      details=f"OpenPhoenix ERP v3.0.0 gestartet.")
    except Exception as e:
        logger.warning(f"Audit-Log-Fehler beim Start: {e}")

    # --- Mahnwesen: automatische Statusaktualisierung ---
    try:
        from core.services.mahnwesen_service import mahnwesen_service, MahnKonfig
        with db.session() as session:
            konfig = MahnKonfig.aus_config()
            ergebnis = mahnwesen_service.pruefe_und_eskaliere(session, konfig)
        n = ergebnis["eskaliert"]
        if n:
            logger.info(f"Mahnwesen: {n} Rechnung(en) automatisch eskaliert.")
    except Exception as e:
        logger.warning(f"Mahnwesen-Check beim Start fehlgeschlagen: {e}")

    # --- Hauptfenster öffnen ---
    from ui.main_window import MainWindow
    window = MainWindow()
    window.showMaximized()

    logger.info("Hauptfenster geöffnet. Anwendung läuft.")

    # --- Event-Loop starten ---
    exit_code = app.exec()

    # --- Audit-Log: App-Ende ---
    try:
        from core.db.engine import db as db_ref
        from core.audit.service import audit as audit_ref, AuditAction as AA
        with db_ref.session() as session:
            audit_ref.log(session, AA.APP_END,
                          details="OpenPhoenix ERP v3.0.0 beendet.")
    except Exception:
        pass  # Beim Beenden nicht kritisch

    logger.info(f"OpenPhoenix ERP beendet (Exit-Code: {exit_code}).")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
