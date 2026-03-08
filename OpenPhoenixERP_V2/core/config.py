"""
core/config.py – Einheitliche Konfigurationsverwaltung für OpenPhoenix ERP
==========================================================================
Eine einzige TOML-Datei, ein einziger Ort, alle Module lesen hier.

Beispiel config.toml:

    [app]
    language = "de"
    theme = "dark"
    version = "2.0.0"

    [database]
    mode = "local"          # "local" oder "server"
    path = "openphoenix.db" # nur bei mode = "local"
    host = "localhost"      # nur bei mode = "server"
    port = 5432
    name = "openphoenix"
    user = "erp_user"
    # password wird NICHT in der Config gespeichert

    [company]
    name = "Ihre Firma GmbH"
    address = "Musterstraße 1"
    zip_city = "12345 Musterstadt"
    phone = ""
    email = ""
    tax_id = ""
    bank_details = ""

    [invoice]
    default_vat = 19.0
    payment_days = 14
    number_format = "{year}-{number:04d}"

    [dunning]
    reminder_days = 7
    mahnung1_days = 21
    mahnung2_days = 35
    inkasso_days = 49
    cost_mahnung1 = 5.0
    cost_mahnung2 = 10.0

    [smtp]
    server = ""
    port = 587
    user = ""
    encryption = "STARTTLS"

    [paths]
    documents = ""
    pdf_background = ""
    xrechnung_output = ""
"""

import tomllib
import logging
from copy import deepcopy
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Standardwerte – werden verwendet wenn config.toml fehlt oder unvollständig
# ---------------------------------------------------------------------------
DEFAULTS: dict[str, Any] = {
    "app": {
        "language": "de",
        "theme": "dark",
        "version": "2.0.0",
    },
    "database": {
        "mode": "local",
        "path": "openphoenix.db",
        "host": "localhost",
        "port": 5432,
        "name": "openphoenix",
        "user": "erp_user",
    },
    "company": {
        "name": "Ihre Firma GmbH",
        "address": "",
        "zip_city": "",
        "phone": "",
        "email": "",
        "tax_id": "",
        "bank_details": "",
    },
    "invoice": {
        "default_vat": 19.0,
        "payment_days": 14,
        "number_format": "{year}-{number:04d}",
    },
    "dunning": {
        "reminder_days": 7,
        "mahnung1_days": 21,
        "mahnung2_days": 35,
        "inkasso_days": 49,
        "cost_mahnung1": 5.0,
        "cost_mahnung2": 10.0,
    },
    "smtp": {
        "server": "",
        "port": 587,
        "user": "",
        "encryption": "STARTTLS",
    },
    "paths": {
        "documents": "",
        "pdf_background": "",
        "xrechnung_output": "",
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Führt zwei Dicts tief zusammen. override gewinnt bei Konflikten."""
    result = deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class Config:
    """
    Zentraler Konfigurationsmanager für OpenPhoenix ERP.

    Verwendung:
        from core.config import config

        db_mode = config.get("database", "mode")
        config.set("company", "name", "Muster GmbH")
        config.save()
    """

    def __init__(self, config_path: Path | None = None) -> None:
        self._path: Path = config_path or self._default_path()
        self._data: dict[str, Any] = deepcopy(DEFAULTS)
        self.load()

    # ------------------------------------------------------------------
    # Pfad-Logik
    # ------------------------------------------------------------------

    @staticmethod
    def _default_path() -> Path:
        """
        Sucht die config.toml im folgenden Order:
        1. Neben der main.py (Produktivbetrieb)
        2. Im aktuellen Arbeitsverzeichnis (Entwicklung)
        """
        import sys
        candidates = [
            Path(sys.argv[0]).parent / "config.toml",
            Path.cwd() / "config.toml",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        # Noch nicht vorhanden – wird beim ersten save() erstellt
        return Path(sys.argv[0]).parent / "config.toml"

    @property
    def path(self) -> Path:
        return self._path

    # ------------------------------------------------------------------
    # Laden & Speichern
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Lädt die TOML-Datei und merged mit den Standardwerten."""
        if not self._path.exists():
            logger.info(f"config.toml nicht gefunden unter {self._path}. Nutze Standardwerte.")
            return
        try:
            with open(self._path, "rb") as f:
                loaded = tomllib.load(f)
            self._data = _deep_merge(DEFAULTS, loaded)
            logger.info(f"Konfiguration geladen: {self._path}")
        except Exception as e:
            logger.error(f"Fehler beim Laden der Konfiguration: {e}. Nutze Standardwerte.")

    def save(self) -> bool:
        """Speichert die aktuelle Konfiguration als TOML-Datei."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            toml_str = self._dict_to_toml(self._data)
            with open(self._path, "w", encoding="utf-8") as f:
                f.write(toml_str)
            logger.info(f"Konfiguration gespeichert: {self._path}")
            return True
        except Exception as e:
            logger.error(f"Fehler beim Speichern der Konfiguration: {e}")
            return False

    @staticmethod
    def _dict_to_toml(data: dict, prefix: str = "") -> str:
        """Serialisiert ein Dict in TOML-Format (einfache Implementierung)."""
        lines = []
        # Zuerst flache Werte, dann Sektionen
        flat = {k: v for k, v in data.items() if not isinstance(v, dict)}
        sections = {k: v for k, v in data.items() if isinstance(v, dict)}

        for key, val in flat.items():
            if isinstance(val, str):
                escaped = val.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
                lines.append(f'{key} = "{escaped}"')
            elif isinstance(val, bool):
                lines.append(f"{key} = {'true' if val else 'false'}")
            elif isinstance(val, float):
                lines.append(f"{key} = {val}")
            elif isinstance(val, int):
                lines.append(f"{key} = {val}")
            else:
                lines.append(f'{key} = "{val}"')

        for section, sub in sections.items():
            full = f"{prefix}{section}" if prefix else section
            lines.append(f"\n[{full}]")
            for key, val in sub.items():
                if isinstance(val, str):
                    escaped = val.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
                    lines.append(f'{key} = "{escaped}"')
                elif isinstance(val, bool):
                    lines.append(f"{key} = {'true' if val else 'false'}")
                elif isinstance(val, float):
                    lines.append(f"{key} = {val}")
                elif isinstance(val, int):
                    lines.append(f"{key} = {val}")
                else:
                    lines.append(f'{key} = "{val}"')

        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------------
    # Zugriff
    # ------------------------------------------------------------------

    def get(self, section: str, key: str, fallback: Any = None) -> Any:
        """Liest einen Konfigurationswert."""
        try:
            return self._data[section][key]
        except KeyError:
            if fallback is not None:
                return fallback
            # Aus Defaults nachlesen
            try:
                return DEFAULTS[section][key]
            except KeyError:
                return None

    def set(self, section: str, key: str, value: Any) -> None:
        """Setzt einen Konfigurationswert (ohne sofortiges Speichern)."""
        if section not in self._data:
            self._data[section] = {}
        self._data[section][key] = value

    def section(self, name: str) -> dict[str, Any]:
        """Gibt einen ganzen Konfigurationsabschnitt zurück."""
        return deepcopy(self._data.get(name, DEFAULTS.get(name, {})))

    def get_database_url(self) -> str:
        """
        Erstellt die SQLAlchemy-kompatible Datenbank-URL.

        Einzelplatz:  sqlite:///path/to/openphoenix.db
        Netzwerk:     postgresql+psycopg2://user:pass@host:port/dbname
        """
        mode = self.get("database", "mode")

        if mode == "local":
            db_path = self.get("database", "path", "openphoenix.db")
            # Relativer Pfad → neben der config.toml auflösen
            if not Path(db_path).is_absolute():
                db_path = str(self._path.parent / db_path)
            return f"sqlite:///{db_path}"

        elif mode == "server":
            host = self.get("database", "host", "localhost")
            port = self.get("database", "port", 5432)
            name = self.get("database", "name", "openphoenix")
            user = self.get("database", "user", "erp_user")
            # Passwort kommt zur Laufzeit, nicht aus der Config
            return f"postgresql+psycopg2://{user}@{host}:{port}/{name}"

        else:
            logger.warning(f"Unbekannter Datenbanktyp '{mode}', nutze SQLite-Fallback.")
            return "sqlite:///openphoenix.db"

    def is_local_db(self) -> bool:
        return self.get("database", "mode") == "local"

    def is_server_db(self) -> bool:
        return self.get("database", "mode") == "server"


# ---------------------------------------------------------------------------
# Singleton – wird beim Import einmalig erstellt
# ---------------------------------------------------------------------------
config = Config()
