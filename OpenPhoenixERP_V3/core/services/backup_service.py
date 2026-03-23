"""
core/services/backup_service.py – Komplettes ERP-Backup & Restore
==================================================================
Backup: Erstellt ein ZIP-Archiv mit:
  - SQLite-Datenbank (sicherer Snapshot via sqlite3 backup API)
  - config.toml
  - Dokumentenordner (Kundendokumente)
  - Belege-Ordner

Restore: Stellt ein zuvor erstelltes Backup vollständig wieder her.
  - Validiert das ZIP-Archiv vor dem Überschreiben
  - Erstellt automatisch ein Sicherheits-Backup vor dem Restore
  - Schreibt DB, Config und Ordner an die richtigen Stellen zurück

Bei PostgreSQL wird nur die config.toml + Dokumentenordner gesichert/restored,
da ein DB-Dump dort separat erfolgen muss (pg_dump).
"""

import logging
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

import os

from core.config import config

logger = logging.getLogger(__name__)


class BackupError(Exception):
    """Fehler beim Erstellen oder Wiederherstellen des Backups."""


class RestoreError(Exception):
    """Fehler beim Wiederherstellen des Backups."""


def erstelle_backup(ziel_pfad: str | Path) -> Path:
    """
    Erstellt ein vollständiges Backup als ZIP-Datei.

    Args:
        ziel_pfad: Pfad der zu erstellenden ZIP-Datei.

    Returns:
        Path zum erstellten ZIP-Archiv.

    Raises:
        BackupError: Bei Fehlern während des Backups.
    """
    ziel = Path(ziel_pfad)
    ziel.parent.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(ziel, "w", zipfile.ZIP_DEFLATED,
                             compresslevel=6) as zf:
            # 1) config.toml
            _backup_config(zf)

            # 2) Datenbank
            _backup_datenbank(zf)

            # 3) Dokumentenordner
            _backup_ordner(zf, "documents", "dokumente")

            # 4) Belege-Ordner
            _backup_ordner(zf, "belege", "belege")

        groesse_mb = ziel.stat().st_size / (1024 * 1024)
        logger.info(
            f"Backup erstellt: {ziel} ({groesse_mb:.1f} MB)"
        )
        return ziel

    except Exception as e:
        # Unvollständiges Archiv aufräumen
        if ziel.exists():
            try:
                ziel.unlink()
            except OSError:
                pass
        raise BackupError(f"Backup fehlgeschlagen: {e}") from e


def _backup_config(zf: zipfile.ZipFile) -> None:
    """Sichert die config.toml ins Archiv."""
    config_path = config.path
    if config_path.exists():
        zf.write(config_path, "config.toml")
        logger.debug("config.toml gesichert.")
    else:
        logger.warning("config.toml nicht gefunden – übersprungen.")


def _backup_datenbank(zf: zipfile.ZipFile) -> None:
    """
    Sichert die SQLite-Datenbank per sqlite3 backup API.

    Die backup-API erstellt einen konsistenten Snapshot,
    auch wenn die DB gerade geöffnet ist.
    Bei PostgreSQL wird ein Hinweis ins Archiv geschrieben.
    """
    if not config.is_local_db():
        # PostgreSQL – kein automatischer DB-Dump
        zf.writestr(
            "HINWEIS_DATENBANK.txt",
            "Diese Installation nutzt PostgreSQL.\n"
            "Die Datenbank ist NICHT in diesem Backup enthalten.\n"
            "Bitte erstellen Sie separat einen Dump mit pg_dump.\n"
            f"\nHost: {config.get('database', 'host', 'localhost')}\n"
            f"Datenbank: {config.get('database', 'name', 'openphoenix')}\n"
            f"Datum: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        )
        logger.info("PostgreSQL erkannt – DB-Backup übersprungen (Hinweis erstellt).")
        return

    db_path_str = config.get("database", "path", "openphoenix.db")
    db_path = Path(db_path_str)
    if not db_path.is_absolute():
        db_path = config.path.parent / db_path_str

    if not db_path.exists():
        logger.warning(f"Datenbank nicht gefunden: {db_path} – übersprungen.")
        return

    # Temporäre Kopie via sqlite3 backup (konsistenter Snapshot)
    tmp_dir = Path(tempfile.mkdtemp(prefix="erp_backup_"))
    tmp_db = tmp_dir / "openphoenix.db"
    try:
        src = sqlite3.connect(str(db_path))
        dst = sqlite3.connect(str(tmp_db))
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        zf.write(tmp_db, "openphoenix.db")
        logger.debug("Datenbank-Snapshot gesichert.")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _backup_ordner(
    zf: zipfile.ZipFile,
    config_key: str,
    archiv_prefix: str,
) -> None:
    """Sichert einen Ordner rekursiv ins ZIP-Archiv."""
    ordner_pfad = config.get("paths", config_key, "")
    if not ordner_pfad:
        logger.debug(f"Pfad '{config_key}' nicht konfiguriert – übersprungen.")
        return

    ordner = Path(ordner_pfad)
    if not ordner.exists() or not ordner.is_dir():
        logger.warning(f"Ordner existiert nicht: {ordner} – übersprungen.")
        return

    dateien_count = 0
    for datei in ordner.rglob("*"):
        if datei.is_file():
            arcname = f"{archiv_prefix}/{datei.relative_to(ordner)}"
            zf.write(datei, arcname)
            dateien_count += 1

    logger.debug(f"{dateien_count} Dateien aus '{config_key}' gesichert.")


def vorgeschlagener_dateiname() -> str:
    """Gibt einen Dateinamen mit Zeitstempel vor."""
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
    return f"OpenPhoenix_Backup_{ts}.zip"


# ===================================================================
# RESTORE
# ===================================================================

def validiere_backup(zip_pfad: str | Path) -> dict[str, bool]:
    """
    Prüft den Inhalt eines Backup-ZIP und gibt zurück,
    welche Komponenten enthalten sind.

    Returns:
        Dict mit Schlüsseln: config, datenbank, dokumente, belege
    """
    pfad = Path(zip_pfad)
    if not pfad.exists():
        raise RestoreError(f"Datei nicht gefunden: {pfad}")

    try:
        with zipfile.ZipFile(pfad, "r") as zf:
            namen = zf.namelist()
    except zipfile.BadZipFile:
        raise RestoreError("Die Datei ist kein gültiges ZIP-Archiv.")

    return {
        "config": "config.toml" in namen,
        "datenbank": "openphoenix.db" in namen,
        "dokumente": any(n.startswith("dokumente/") for n in namen),
        "belege": any(n.startswith("belege/") for n in namen),
    }


def restore_backup(zip_pfad: str | Path) -> dict[str, str]:
    """
    Stellt ein Backup aus einem ZIP-Archiv wieder her.

    Ablauf:
      1. ZIP validieren
      2. Sicherheits-Backup des aktuellen Zustands erstellen
      3. config.toml überschreiben
      4. SQLite-Datenbank überschreiben (nur bei lokalem Modus)
      5. Dokumenten- und Belege-Ordner wiederherstellen

    Args:
        zip_pfad: Pfad zum Backup-ZIP.

    Returns:
        Dict mit Infos: sicherheits_backup, wiederhergestellt (Liste)

    Raises:
        RestoreError: Bei Fehlern während der Wiederherstellung.
    """
    pfad = Path(zip_pfad)
    inhalt = validiere_backup(pfad)
    ergebnis: dict[str, str] = {}
    wiederhergestellt: list[str] = []

    # --- Sicherheits-Backup vor dem Überschreiben ---
    try:
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        sicherung = config.path.parent / f".pre_restore_backup_{ts}.zip"
        erstelle_backup(sicherung)
        ergebnis["sicherheits_backup"] = str(sicherung)
        logger.info(f"Sicherheits-Backup erstellt: {sicherung}")
    except Exception as e:
        raise RestoreError(
            f"Konnte kein Sicherheits-Backup erstellen: {e}\n"
            "Restore abgebrochen — keine Daten wurden verändert."
        ) from e

    # --- Restore ---
    try:
        with zipfile.ZipFile(pfad, "r") as zf:
            # 1) config.toml
            if inhalt["config"]:
                _restore_config(zf)
                wiederhergestellt.append("config.toml")

            # 2) Datenbank
            if inhalt["datenbank"] and config.is_local_db():
                _restore_datenbank(zf)
                wiederhergestellt.append("Datenbank")

            # 3) Dokumentenordner
            if inhalt["dokumente"]:
                count = _restore_ordner(zf, "dokumente", "documents")
                wiederhergestellt.append(f"Dokumente ({count} Dateien)")

            # 4) Belege
            if inhalt["belege"]:
                count = _restore_ordner(zf, "belege", "belege")
                wiederhergestellt.append(f"Belege ({count} Dateien)")

    except RestoreError:
        raise
    except Exception as e:
        raise RestoreError(
            f"Fehler beim Wiederherstellen: {e}\n"
            f"Sicherheits-Backup liegt unter: {sicherung}"
        ) from e

    ergebnis["wiederhergestellt"] = ", ".join(wiederhergestellt)
    logger.info(f"Restore abgeschlossen: {wiederhergestellt}")
    return ergebnis


def _restore_config(zf: zipfile.ZipFile) -> None:
    """Stellt die config.toml wieder her."""
    ziel = config.path
    daten = zf.read("config.toml")
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_bytes(daten)
    logger.debug("config.toml wiederhergestellt.")


def _restore_datenbank(zf: zipfile.ZipFile) -> None:
    """
    Stellt die SQLite-Datenbank wieder her.

    Schließt die aktive SQLAlchemy-Engine, damit Windows die Datei
    freigibt, ersetzt die DB-Datei, und initialisiert die Engine neu.
    """
    from core.db.engine import db

    db_path_str = config.get("database", "path", "openphoenix.db")
    db_path = Path(db_path_str)
    if not db_path.is_absolute():
        db_path = config.path.parent / db_path_str

    db_path.parent.mkdir(parents=True, exist_ok=True)

    # In temporäre Datei extrahieren und validieren
    tmp_dir = Path(tempfile.mkdtemp(prefix="erp_restore_"))
    tmp_db = tmp_dir / "openphoenix.db"
    try:
        daten = zf.read("openphoenix.db")
        tmp_db.write_bytes(daten)

        # Validierung: Ist es eine gültige SQLite-Datei?
        try:
            conn = sqlite3.connect(str(tmp_db))
            conn.execute("SELECT count(*) FROM sqlite_master")
            conn.close()
        except sqlite3.Error as e:
            raise RestoreError(
                f"Die Datenbank im Backup ist beschädigt: {e}"
            )

        # Engine schließen → Datei-Lock freigeben
        db.dispose()
        logger.debug("DB-Engine geschlossen für Restore.")

        # Atomares Ersetzen
        os.replace(str(tmp_db), str(db_path))
        logger.debug(f"Datenbank wiederhergestellt: {db_path}")

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

        # Engine immer wieder öffnen (auch bei Fehler)
        try:
            db.initialize(config.get_database_url())
            db.create_all_tables()
            logger.debug("DB-Engine nach Restore neu initialisiert.")
        except Exception as e:
            logger.error(f"Fehler bei DB-Neuinitialisierung: {e}")


def _restore_ordner(
    zf: zipfile.ZipFile,
    archiv_prefix: str,
    config_key: str,
) -> int:
    """
    Stellt einen Ordner aus dem Backup wieder her.

    Vorhandene Dateien werden überschrieben, zusätzliche Dateien
    im Zielordner bleiben erhalten (kein Löschen).

    Returns:
        Anzahl wiederhergestellter Dateien.
    """
    ordner_pfad = config.get("paths", config_key, "")
    if not ordner_pfad:
        logger.warning(
            f"Pfad '{config_key}' nicht konfiguriert – "
            f"Ordner '{archiv_prefix}' kann nicht wiederhergestellt werden."
        )
        return 0

    ziel = Path(ordner_pfad)
    ziel.mkdir(parents=True, exist_ok=True)

    prefix = f"{archiv_prefix}/"
    count = 0
    for info in zf.infolist():
        if not info.filename.startswith(prefix):
            continue
        # Nur Dateien, keine leeren Verzeichnis-Einträge
        if info.filename.endswith("/"):
            continue

        rel_pfad = info.filename[len(prefix):]
        ziel_datei = ziel / rel_pfad

        # Sicherheit: Path-Traversal verhindern
        try:
            ziel_datei.resolve().relative_to(ziel.resolve())
        except ValueError:
            logger.warning(f"Übersprungen (Path-Traversal): {info.filename}")
            continue

        ziel_datei.parent.mkdir(parents=True, exist_ok=True)
        ziel_datei.write_bytes(zf.read(info.filename))
        count += 1

    logger.debug(f"{count} Dateien in '{config_key}' wiederhergestellt.")
    return count
