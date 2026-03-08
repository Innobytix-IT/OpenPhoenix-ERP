# 🔥 OpenPhoenix ERP v2

**Freies, modulares ERP-System für kleine und mittlere Unternehmen.**

[![Lizenz: GPL v3](https://img.shields.io/badge/Lizenz-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-green.svg)](https://python.org)
[![PySide6](https://img.shields.io/badge/UI-PySide6-orange.svg)](https://doc.qt.io/qtforpython/)

---

## Was ist OpenPhoenix ERP?

OpenPhoenix ERP ist ein kostenloses, quelloffenes Desktop-ERP-System,
das speziell für kleine und mittlere Unternehmen entwickelt wurde.
Es ist GoBD-konform, mehrsprachig vorbereitet und läuft lokal auf Windows,
Linux und macOS.

## Module

| Modul | Beschreibung |
|---|---|
| 👥 Kundenverwaltung | Kundenstamm, Dokumente, GoBD-konform |
| 🧾 Rechnungen | Erstellen, Finalisieren, PDF-Export |
| 📦 Lagerverwaltung | Artikelstamm, Bestandsführung |
| 📨 Mahnwesen | Automatische Mahnstufenverwaltung |
| 📊 Dashboard | Business Intelligence, Auswertungen |
| 🖹 XRechnung | EN16931-konforme XML-Rechnungen |
| ✏️ Rechnungskorrektur | GoBD-konformes Storno mit Gutschrift |
| ⚙️ Einstellungen | Konfiguration, SMTP, Firmendaten |

## Technologie

- **UI:** PySide6 (Qt6)
- **Datenbank (Einzelplatz):** SQLite mit WAL-Modus
- **Datenbank (Netzwerk):** PostgreSQL
- **Abstraktion:** SQLAlchemy 2.0
- **Migrationen:** Alembic
- **Tests:** pytest
- **Config:** TOML

## Installation (Entwicklung)

```bash
# Repository klonen
git clone https://github.com/IhrName/openphoenix-erp.git
cd openphoenix-erp

# Virtuelle Umgebung erstellen
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Abhängigkeiten installieren
pip install -e ".[dev]"

# Anwendung starten
python main.py
```

## Tests ausführen

```bash
pytest tests/ -v --cov=core
```

## Datenbankmodul wechseln

In `config.toml`:

```toml
# Einzelplatz
[database]
mode = "local"
path = "openphoenix.db"

# Netzwerk / KMU
[database]
mode = "server"
host = "192.168.1.10"
port = 5432
name = "openphoenix"
user = "erp_user"
```

## Lizenz

OpenPhoenix ERP ist freie Software, lizenziert unter der
**GNU General Public License v3 (GPL-3.0)**.

Das bedeutet: Du darfst die Software frei nutzen, kopieren, verändern
und weitergeben — solange du Änderungen ebenfalls unter GPL v3
veröffentlichst.

Siehe [LICENSE](LICENSE) für den vollständigen Lizenztext.

## Mitmachen

Pull Requests und Issues sind willkommen.
Bitte lies `CONTRIBUTING.md` bevor du einen Beitrag einreichst.

---

*OpenPhoenix ERP – Die Welt verdient vernünftige Software.*
