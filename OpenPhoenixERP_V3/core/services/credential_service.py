"""
core/services/credential_service.py – Sichere Passwortverwaltung
=================================================================
Speichert das SMTP-Passwort im OS-eigenen Schlüsselbund:
  • Windows  → Windows Credential Manager
  • macOS    → macOS Keychain
  • Linux    → SecretService (GNOME Keyring / KWallet)

Fällt keyring nicht verfügbar sein (z.B. minimale Server-Umgebung),
wird ein verschlüsselter Fallback in config/ genutzt.
"""

import base64
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_SERVICE_NAME = "OpenPhoenix-ERP"
_ACCOUNT_NAME = "smtp_password"


# ---------------------------------------------------------------------------
# Öffentliche API
# ---------------------------------------------------------------------------

def passwort_speichern(passwort: str) -> bool:
    """
    Speichert das SMTP-Passwort sicher im OS-Schlüsselbund.
    Gibt True zurück wenn erfolgreich.
    """
    if not passwort:
        passwort_loeschen()
        return True
    try:
        import keyring
        keyring.set_password(_SERVICE_NAME, _ACCOUNT_NAME, passwort)
        logger.info("SMTP-Passwort im OS-Schlüsselbund gespeichert.")
        # Sicherstellen dass kein Klartext-Passwort mehr in config.toml steht
        _config_passwort_loeschen()
        return True
    except Exception as e:
        logger.warning(f"keyring nicht verfügbar ({e}), nutze verschlüsselten Fallback.")
        return _fallback_speichern(passwort)


def passwort_laden() -> str:
    """
    Lädt das SMTP-Passwort aus dem OS-Schlüsselbund.
    Gibt '' zurück wenn kein Passwort gespeichert.
    """
    # Zuerst keyring versuchen
    try:
        import keyring
        pw = keyring.get_password(_SERVICE_NAME, _ACCOUNT_NAME)
        if pw is not None:
            return pw
    except Exception as e:
        logger.warning(f"keyring nicht verfügbar ({e}), versuche Fallback.")

    # Fallback: verschlüsselte Datei
    fb = _fallback_laden()
    if fb:
        return fb

    # Migration: altes Klartext-Passwort aus config.toml lesen und übertragen
    return _migration_aus_config()


def passwort_loeschen() -> None:
    """Löscht das SMTP-Passwort aus allen Speicherorten."""
    try:
        import keyring
        keyring.delete_password(_SERVICE_NAME, _ACCOUNT_NAME)
    except Exception:
        pass
    _fallback_loeschen()
    _config_passwort_loeschen()


def keyring_verfuegbar() -> bool:
    """Prüft ob keyring auf diesem System funktioniert."""
    try:
        import keyring
        keyring.get_password(_SERVICE_NAME, "__test__")
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Interne Hilfsfunktionen
# ---------------------------------------------------------------------------

def _fallback_pfad() -> Path:
    p = Path("config")
    p.mkdir(exist_ok=True)
    return p / ".smtp_cred"


def _fallback_speichern(passwort: str) -> bool:
    """
    Einfache Obfuskation als letzter Ausweg (kein echter Schutz,
    aber besser als Klartext — verhindert zufälliges Mitlesen).
    """
    try:
        # XOR mit maschinenspezifischem Schlüssel + base64
        key = _machine_key()
        enc = bytes(b ^ key[i % len(key)] for i, b in enumerate(passwort.encode()))
        _fallback_pfad().write_bytes(base64.b64encode(enc))
        logger.info("SMTP-Passwort im verschlüsselten Fallback gespeichert.")
        return True
    except Exception as e:
        logger.error(f"Fallback-Speicherung fehlgeschlagen: {e}")
        return False


def _fallback_laden() -> str:
    try:
        p = _fallback_pfad()
        if not p.exists():
            return ""
        key = _machine_key()
        enc = base64.b64decode(p.read_bytes())
        return bytes(b ^ key[i % len(key)] for i, b in enumerate(enc)).decode()
    except Exception as e:
        logger.debug(f"Fallback-Laden fehlgeschlagen: {e}")
        return ""


def _fallback_loeschen() -> None:
    try:
        p = _fallback_pfad()
        if p.exists():
            p.unlink()
    except Exception as e:
        logger.debug(f"Fallback-Löschen fehlgeschlagen: {e}")


def _machine_key() -> bytes:
    """Erzeugt einen maschinenspezifischen Schlüssel aus Umgebungsvariablen."""
    import hashlib
    seed = (
        os.environ.get("COMPUTERNAME", "")
        + os.environ.get("USERNAME", "")
        + os.environ.get("USER", "")
        + os.environ.get("HOME", "")
        + "OpenPhoenix-ERP-v2"
    )
    return hashlib.sha256(seed.encode()).digest()


def _config_passwort_loeschen() -> None:
    """Entfernt das Klartext-Passwort aus config.toml falls vorhanden."""
    try:
        from core.config import config
        if config.get("smtp", "password", ""):
            config.set("smtp", "password", "")
            config.save()
            logger.info("Klartext-Passwort aus config.toml entfernt.")
    except Exception as e:
        logger.debug(f"Config-Passwort-Löschung fehlgeschlagen: {e}")


def _migration_aus_config() -> str:
    """
    Einmalige Migration: liest altes Klartext-Passwort aus config.toml,
    speichert es sicher und löscht es aus der config.
    """
    try:
        from core.config import config
        altes_pw = config.get("smtp", "password", "")
        if altes_pw:
            logger.info("Migriere Klartext-SMTP-Passwort in sicheren Speicher...")
            if passwort_speichern(altes_pw):
                return altes_pw
    except Exception as e:
        logger.debug(f"Config-Migration fehlgeschlagen: {e}")
    return ""
