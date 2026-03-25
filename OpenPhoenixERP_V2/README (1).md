# 🔥 OpenPhoenix ERP v2

**Freies, modulares ERP-System für kleine und mittlere Unternehmen.**

[![Lizenz: GPL v3](https://img.shields.io/badge/Lizenz-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-green.svg)](https://python.org)
[![PySide6](https://img.shields.io/badge/UI-PySide6-orange.svg)](https://doc.qt.io/qtforpython/)
[![Version](https://img.shields.io/badge/Version-2.0.0-brightgreen.svg)](https://github.com/Innobytix-IT/OpenPhoenix-ERP/releases/tag/v2.0.0)

---

## Was ist OpenPhoenix ERP?

OpenPhoenix ERP ist ein kostenloses, quelloffenes Desktop-ERP-System,
das speziell für kleine und mittlere Unternehmen entwickelt wurde.
Es ist GoBD-konform, mehrsprachig vorbereitet und läuft lokal auf Windows,
Linux und macOS – vollständig offline, ohne Cloud-Zwang.

---

## ⚡ Schnellinstallation (Linux / macOS)

```bash
git clone https://github.com/Innobytix-IT/OpenPhoenix-ERP.git
cd OpenPhoenix-ERP/OpenPhoenixERP_V2
chmod +x install.sh
./install.sh
```

Das Installationsskript führt dich interaktiv durch alle 8 Schritte:
Python-Prüfung · Abhängigkeiten · Firmendaten · Rechnungseinstellungen ·
Mahnwesen · SMTP-E-Mail · Datenbank-Initialisierung · Erster Start.

Am Ende hast du ein vollständig eingerichtetes, sofort einsatzbereites ERP.

> **Windows-Nutzer:** Manuell installieren – siehe Abschnitt [Manuelle Installation](#manuelle-installation).

---

## Module

| Modul | Beschreibung |
|---|---|
| 👥 Kundenverwaltung | Kundenstamm, Dokumente, Notizen, GoBD-konform |
| 🧾 Rechnungen | Erstellen, Finalisieren, PDF-Export, XRechnung |
| 📦 Lagerverwaltung | Artikelstamm, Bestandsführung, Bewegungshistorie |
| 📨 Mahnwesen | Automatische Mahnstufen, Mahnschreiben per E-Mail |
| 📊 Dashboard | Business Intelligence, KPIs, Auswertungen |
| 🖹 XRechnung | EN16931-konforme XML-Rechnungen (B2B/Behörden) |
| ✏️ Rechnungskorrektur | GoBD-konformes Storno mit Gutschrift |
| 📝 Textvorlagen | Anpassbare Vorlagen mit Platzhalter-System |
| 🔒 Einstellungen | SMTP, Firmendaten, sichere Passwortverwaltung |

---

## 🤖 Ilija-Integration – KI-gesteuerte Automatisierung

OpenPhoenix ERP lässt sich vollständig mit dem KI-Agenten
**[Ilija](https://github.com/Innobytix-IT/Ilija-AI-Agent-Public-Edition)**
verbinden. Ilija bekommt dadurch einen eigenen ERP-Skill und kann
autonom handeln:

- Offene und überfällige Rechnungen prüfen
- Mahnläufe automatisch durchführen und Mahnschreiben per E-Mail versenden
- Rechnungsstatus ändern (Zahlung buchen, eskalieren)
- Lagerbestand überwachen und bei kritischen Beständen informieren
- Wirtschafts-KPIs und Berichte abrufen
- Kundendaten suchen und auswerten

**Einrichtung in 2 Schritten:**

1. `openphoenix_erp.py` aus dem
   [Ilija-Repository](https://github.com/Innobytix-IT/Ilija-AI-Agent-Public-Edition)
   nach `ilija_public_final/skills/` kopieren.

2. Einmalig im Ilija-Terminal eingeben:
```
erp_pfad_setzen(pfad="/pfad/zu/OpenPhoenixERP_V2")
```

Ab diesem Moment kennt Ilija das ERP dauerhaft. Beispielbefehle:

```
"Gibt es überfällige Rechnungen?"
"Führe den Mahnlauf durch."
"Wie sieht es im Lager aus?"
"Buche Zahlung für Rechnung 2026-0018."
"Zeig mir den Wirtschaftsbericht."
```

---

## Manuelle Installation

```bash
# 1. Repository klonen
git clone https://github.com/Innobytix-IT/OpenPhoenix-ERP.git
cd OpenPhoenix-ERP/OpenPhoenixERP_V2

# 2. Virtuelle Umgebung erstellen und aktivieren
python -m venv venv

# Windows:
venv\Scripts\activate
# Linux / macOS:
source venv/bin/activate

# 3. Abhängigkeiten installieren
pip install -e .

# Optional: sichere Passwortverwaltung
pip install keyring

# Optional: PostgreSQL-Unterstützung (Netzwerkbetrieb)
pip install psycopg2-binary

# 4. Anwendung starten
python main.py
```

> **Linux:** Falls die Oberfläche nicht startet, fehlen möglicherweise
> Qt-Systemabhängigkeiten:
> ```bash
> sudo apt install libxcb-cursor0 libxcb-xinerama0 libxkbcommon-x11-0 libgl1
> ```

---

## Entwicklung & Tests

```bash
# Dev-Abhängigkeiten installieren
pip install -e .[dev]

# Tests ausführen
pytest tests/ -v --cov=core
```

---

## Datenbankmodus wechseln

In `config.toml`:

```toml
# Einzelplatz (Standard)
[database]
mode = "local"
path = "openphoenix.db"

# Netzwerk / mehrere Arbeitsplätze
[database]
mode = "server"
host = "192.168.1.10"
port = 5432
name = "openphoenix"
user = "erp_user"
```

---

## Technologie

| Komponente | Technologie |
|---|---|
| UI | PySide6 (Qt6) |
| Datenbank Einzelplatz | SQLite mit WAL-Modus |
| Datenbank Netzwerk | PostgreSQL |
| ORM | SQLAlchemy 2.0 |
| Migrationen | Alembic |
| PDF-Erzeugung | ReportLab |
| XRechnung | lxml (EN16931) |
| Konfiguration | TOML |
| Passwortverwaltung | keyring (System-Tresor) |
| Tests | pytest |

---

## Lizenz

OpenPhoenix ERP ist freie Software, lizenziert unter der
**GNU General Public License v3 (GPL-3.0)**.

Du darfst die Software frei nutzen, kopieren, verändern und weitergeben —
solange Änderungen ebenfalls unter GPL v3 veröffentlicht werden.

Siehe [LICENSE](LICENSE) für den vollständigen Lizenztext.

---

## Mitmachen

Pull Requests und Issues sind willkommen.
Bitte lies `CONTRIBUTING.md` bevor du einen Beitrag einreichst.

---

*OpenPhoenix ERP – Einfach weil "Einfach" einfach ist.*
