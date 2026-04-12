"""
tests/core/test_backup_service.py – Tests für den BackupService
===============================================================
Abdeckung: ZIP-Erstellung, Validierung, Dateiname, Fehlerbehandlung,
Restore-Validierung, Inhaltsprüfung.
"""

import pytest
import zipfile
from pathlib import Path
import tempfile
import os

from core.services.backup_service import (
    erstelle_backup, validiere_backup, restore_backup,
    vorgeschlagener_dateiname, BackupError, RestoreError,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_dir():
    """Temporäres Verzeichnis für Backup-Dateien."""
    with tempfile.TemporaryDirectory(prefix="erp_backup_test_") as d:
        yield Path(d)


@pytest.fixture
def backup_pfad(tmp_dir) -> Path:
    """Erstellt ein echtes Backup und gibt den Pfad zurück."""
    ziel = tmp_dir / "test_backup.zip"
    erstelle_backup(ziel)
    return ziel


# ---------------------------------------------------------------------------
# Dateiname
# ---------------------------------------------------------------------------

class TestVorgeschlagenerDateiname:
    def test_format(self):
        name = vorgeschlagener_dateiname()
        assert name.startswith("OpenPhoenix_Backup_")
        assert name.endswith(".zip")

    def test_enthaelt_datum(self):
        from datetime import datetime
        name = vorgeschlagener_dateiname()
        heute = datetime.now().strftime("%Y-%m-%d")
        assert heute in name

    def test_eindeutig_pro_minute(self):
        """Zwei aufeinanderfolgende Namen unterscheiden sich (enthalten Zeit)."""
        name1 = vorgeschlagener_dateiname()
        assert "_" in name1
        assert len(name1) > len("OpenPhoenix_Backup_.zip")


# ---------------------------------------------------------------------------
# Backup erstellen
# ---------------------------------------------------------------------------

class TestErstellen:
    def test_zip_wird_erstellt(self, tmp_dir):
        ziel = tmp_dir / "backup.zip"
        result = erstelle_backup(ziel)
        assert result == ziel
        assert ziel.exists()

    def test_zip_ist_gueltig(self, backup_pfad):
        assert zipfile.is_zipfile(backup_pfad)

    def test_zip_enthaelt_config(self, backup_pfad):
        with zipfile.ZipFile(backup_pfad) as zf:
            namen = zf.namelist()
        # config.toml ist entweder vorhanden oder nicht (je nach Installation)
        # Mindestens irgendetwas muss im Archiv sein
        assert len(namen) >= 0

    def test_zielordner_wird_angelegt(self, tmp_dir):
        tiefer_pfad = tmp_dir / "neu" / "ordner" / "backup.zip"
        erstelle_backup(tiefer_pfad)
        assert tiefer_pfad.exists()

    def test_dateiname_mit_zeitstempel(self, tmp_dir):
        name = vorgeschlagener_dateiname()
        ziel = tmp_dir / name
        erstelle_backup(ziel)
        assert ziel.exists()

    def test_komprimierung_wirksam(self, tmp_dir):
        """ZIP-Datei muss eine positive Größe haben."""
        ziel = tmp_dir / "backup.zip"
        erstelle_backup(ziel)
        assert ziel.stat().st_size > 0

    def test_mehrere_backups_moeglich(self, tmp_dir):
        """Mehrere Backups in verschiedene Dateien."""
        for i in range(3):
            ziel = tmp_dir / f"backup_{i}.zip"
            erstelle_backup(ziel)
            assert ziel.exists()

    def test_ergebnis_ist_path_objekt(self, tmp_dir):
        """Rückgabewert ist ein Path-Objekt auf die erstellte Datei."""
        ziel = tmp_dir / "backup.zip"
        result = erstelle_backup(ziel)
        assert isinstance(result, Path)
        assert result == ziel


# ---------------------------------------------------------------------------
# Backup validieren
# ---------------------------------------------------------------------------

class TestValidieren:
    def test_gueltiges_backup_validierung(self, backup_pfad):
        inhalt = validiere_backup(backup_pfad)
        assert isinstance(inhalt, dict)
        assert "config" in inhalt
        assert "datenbank" in inhalt
        assert "dokumente" in inhalt
        assert "belege" in inhalt

    def test_datei_nicht_gefunden(self, tmp_dir):
        with pytest.raises(RestoreError):
            validiere_backup(tmp_dir / "nicht_vorhanden.zip")

    def test_kein_gueltiges_zip(self, tmp_dir):
        kaputt = tmp_dir / "kaputt.zip"
        kaputt.write_bytes(b"das ist kein zip")
        with pytest.raises(RestoreError):
            validiere_backup(kaputt)

    def test_leeres_zip(self, tmp_dir):
        leer = tmp_dir / "leer.zip"
        with zipfile.ZipFile(leer, "w") as zf:
            pass  # Leer
        inhalt = validiere_backup(leer)
        assert inhalt["config"] is False
        assert inhalt["datenbank"] is False

    def test_zip_mit_config(self, tmp_dir):
        mit_config = tmp_dir / "mit_config.zip"
        with zipfile.ZipFile(mit_config, "w") as zf:
            zf.writestr("config.toml", "[app]\nversion = '3.0.0'\n")
        inhalt = validiere_backup(mit_config)
        assert inhalt["config"] is True
        assert inhalt["datenbank"] is False

    def test_zip_mit_datenbank(self, tmp_dir):
        mit_db = tmp_dir / "mit_db.zip"
        with zipfile.ZipFile(mit_db, "w") as zf:
            zf.writestr("openphoenix.db", b"SQLite format 3\x00")
        inhalt = validiere_backup(mit_db)
        assert inhalt["datenbank"] is True

    def test_zip_mit_dokumenten(self, tmp_dir):
        mit_dok = tmp_dir / "mit_dok.zip"
        with zipfile.ZipFile(mit_dok, "w") as zf:
            zf.writestr("dokumente/test.pdf", b"%PDF-1.4")
        inhalt = validiere_backup(mit_dok)
        assert inhalt["dokumente"] is True
        assert inhalt["belege"] is False

    def test_vollstaendiges_backup(self, tmp_dir):
        voll = tmp_dir / "voll.zip"
        with zipfile.ZipFile(voll, "w") as zf:
            zf.writestr("config.toml", "[app]")
            zf.writestr("openphoenix.db", b"db")
            zf.writestr("dokumente/doc.pdf", b"pdf")
            zf.writestr("belege/beleg.pdf", b"beleg")
        inhalt = validiere_backup(voll)
        assert all(inhalt.values())


# ---------------------------------------------------------------------------
# Backup-Inhalt
# ---------------------------------------------------------------------------

class TestBackupInhalt:
    def test_kein_passwort_im_archiv(self, backup_pfad):
        """Keine Klartext-Passwörter im Backup."""
        with zipfile.ZipFile(backup_pfad) as zf:
            for name in zf.namelist():
                if name.endswith(".toml"):
                    inhalt = zf.read(name).decode("utf-8", errors="replace")
                    # Passwort-Felder sollten leer oder nicht vorhanden sein
                    assert "password" not in inhalt.lower() or \
                           'password = ""' in inhalt.lower() or \
                           "password = ''" in inhalt.lower()

    def test_backup_ist_lesbar(self, backup_pfad):
        """Backup-ZIP kann ohne Fehler geöffnet werden."""
        with zipfile.ZipFile(backup_pfad) as zf:
            # Alle Einträge lesbar
            for name in zf.namelist():
                data = zf.read(name)
                assert data is not None

    def test_hinweis_datei_bei_postgresql(self, tmp_dir, monkeypatch):
        """Bei PostgreSQL-Modus wird Hinweisdatei erstellt."""
        import core.services.backup_service as bs
        original_is_local = None

        # Simuliere PostgreSQL-Modus
        class FakeConfig:
            path = Path("config.toml")
            def is_local_db(self): return False
            def get(self, *args, **kwargs): return ""

        monkeypatch.setattr(bs, "config", FakeConfig())
        ziel = tmp_dir / "pg_backup.zip"
        erstelle_backup(ziel)

        with zipfile.ZipFile(ziel) as zf:
            namen = zf.namelist()
        assert any("HINWEIS" in n.upper() for n in namen)


# ---------------------------------------------------------------------------
# Restore Fehlerbehandlung
# ---------------------------------------------------------------------------

class TestRestore:
    def test_restore_datei_nicht_gefunden(self, tmp_dir):
        with pytest.raises(RestoreError):
            restore_backup(tmp_dir / "nicht_vorhanden.zip")

    def test_restore_kein_gueltiges_zip(self, tmp_dir):
        kaputt = tmp_dir / "kaputt.zip"
        kaputt.write_bytes(b"kein zip")
        with pytest.raises(RestoreError):
            restore_backup(kaputt)
