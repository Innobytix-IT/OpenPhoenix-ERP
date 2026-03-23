#!/bin/bash
# =============================================================================
#  OpenPhoenix ERP v2 – Installationsskript
#  Freies, modulares ERP-System für kleine und mittlere Unternehmen
# =============================================================================

set -e

RED='\\033[0;31m';  GREEN='\\033[0;32m';  YELLOW='\\033[1;33m'
BLUE='\\033[0;34m'; CYAN='\\033[0;36m';   MAGENTA='\\033[0;35m'
BOLD='\\033[1m';    RESET='\\033[0m'

print_header() {
    echo ""
    echo -e "${BLUE}${BOLD}╔══════════════════════════════════════════════════════════════╗${RESET}"
    echo -e "${BLUE}${BOLD}║${RESET}  ${CYAN}${BOLD}$1${RESET}"
    echo -e "${BLUE}${BOLD}╚══════════════════════════════════════════════════════════════╝${RESET}"
    echo ""
}
print_step()  { echo -e "${GREEN}${BOLD}▶  $1${RESET}"; }
print_info()  { echo -e "${CYAN}   ℹ  $1${RESET}"; }
print_warn()  { echo -e "${YELLOW}   ⚠  $1${RESET}"; }
print_ok()    { echo -e "${GREEN}   ✅  $1${RESET}"; }
print_error() { echo -e "${RED}   ❌  $1${RESET}"; }
divider()     { echo -e "${BLUE}──────────────────────────────────────────────────────────────${RESET}"; }

clear
echo ""
echo -e "${MAGENTA}${BOLD}"
echo "   ██████╗ ██████╗ ███████╗███╗   ██╗"
echo "  ██╔═══██╗██╔══██╗██╔════╝████╗  ██║"
echo "  ██║   ██║██████╔╝█████╗  ██╔██╗ ██║"
echo "  ██║   ██║██╔═══╝ ██╔══╝  ██║╚██╗██║"
echo "  ╚██████╔╝██║     ███████╗██║ ╚████║"
echo "   ╚═════╝ ╚═╝     ╚══════╝╚═╝  ╚═══╝"
echo ""
echo "  ██████╗ ██╗  ██╗ ██████╗ ███████╗███╗   ██╗██╗██╗  ██╗"
echo "  ██╔══██╗██║  ██║██╔═══██╗██╔════╝████╗  ██║██║╚██╗██╔╝"
echo "  ██████╔╝███████║██║   ██║█████╗  ██╔██╗ ██║██║ ╚███╔╝ "
echo "  ██╔═══╝ ██╔══██║██║   ██║██╔══╝  ██║╚██╗██║██║ ██╔██╗ "
echo "  ██║     ██║  ██║╚██████╔╝███████╗██║ ╚████║██║██╔╝ ██╗"
echo "  ╚═╝     ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝╚═╝╚═╝  ╚═╝"
echo -e "${RESET}"
echo -e "${CYAN}${BOLD}         OpenPhoenix ERP v3.0.0 – Setup${RESET}"
echo -e "${CYAN}         Freies ERP-System für kleine & mittlere Unternehmen${RESET}"
echo ""; divider; echo ""
echo "  Dieses Skript installiert alle Abhängigkeiten, richtet"
echo "  die Datenbank ein und konfiguriert dein Unternehmen."
echo ""; divider
sleep 1

# =============================================================================
# SCHRITT 0: Installationspfad
# =============================================================================
print_header "SCHRITT 0/8 – Installationspfad"

DEFAULT_INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo -e "  ${BOLD}Wo soll OpenPhoenix ERP installiert werden?${RESET}"
echo ""
echo -e "  Standard: ${CYAN}${DEFAULT_INSTALL_DIR}${RESET}"
echo "  [1] Standard-Pfad verwenden"
echo "  [2] Eigenen Pfad angeben"
echo ""
read -rp "  Deine Wahl [1/2]: " PATH_CHOICE

INSTALL_DIR="$DEFAULT_INSTALL_DIR"
if [ "$PATH_CHOICE" = "2" ]; then
    echo ""
    read -rp "  Pfad eingeben: " CUSTOM_PATH
    CUSTOM_PATH="${CUSTOM_PATH/#\~/$HOME}"
    if [ -n "$CUSTOM_PATH" ]; then
        INSTALL_DIR="$CUSTOM_PATH"
        mkdir -p "$INSTALL_DIR"
        if [ "$INSTALL_DIR" != "$DEFAULT_INSTALL_DIR" ]; then
            print_step "Kopiere Projektdateien nach $INSTALL_DIR ..."
            cp -r "$DEFAULT_INSTALL_DIR"/. "$INSTALL_DIR/"
            print_ok "Dateien kopiert"
        fi
    fi
fi

print_ok "Installationspfad: ${INSTALL_DIR}"
cd "$INSTALL_DIR"

# =============================================================================
# SCHRITT 1: Python prüfen
# =============================================================================
print_header "SCHRITT 1/8 – Python prüfen"

if ! command -v python3 &> /dev/null; then
    print_error "Python3 nicht gefunden!"
    echo ""
    echo "  Installation:"
    echo "    Linux:   sudo apt install python3.11 python3-pip python3-venv"
    echo "    macOS:   brew install python@3.11"
    echo "    Windows: https://python.org/downloads (3.11 oder neuer)"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PYTHON_MAJOR=$(python3 -c 'import sys; print(sys.version_info.major)')
PYTHON_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')

if [ "$PYTHON_MAJOR" -lt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 11 ]; }; then
    print_error "Python $PYTHON_VERSION gefunden – OpenPhoenix benötigt mindestens Python 3.11!"
    echo ""
    echo "  → sudo apt install python3.11"
    exit 1
fi
print_ok "Python $PYTHON_VERSION ✓"

# Tk/Qt-Abhängigkeiten prüfen (Linux)
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    echo ""
    print_info "Prüfe Qt-Systemabhängigkeiten..."
    QT_DEPS_OK=true
    for dep in libxcb-cursor0 libxcb-xinerama0 libxkbcommon-x11-0 libgl1; do
        if ! dpkg -l "$dep" &>/dev/null 2>&1; then
            QT_DEPS_OK=false
            break
        fi
    done
    if [ "$QT_DEPS_OK" = false ]; then
        print_warn "Einige Qt-Systemabhängigkeiten fehlen. Versuche zu installieren..."
        sudo apt-get install -y \
            libxcb-cursor0 libxcb-xinerama0 libxkbcommon-x11-0 \
            libgl1 libglib2.0-0 libfontconfig1 libdbus-1-3 \
            libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 \
            libxcb-render-util0 libxcb-shape0 2>/dev/null \
            && print_ok "Qt-Systemabhängigkeiten installiert" \
            || print_warn "Manuelle Installation nötig: sudo apt install libxcb-cursor0 libgl1"
    else
        print_ok "Qt-Systemabhängigkeiten vorhanden ✓"
    fi
fi

# =============================================================================
# SCHRITT 2: Virtuelle Umgebung & Python-Pakete
# =============================================================================
print_header "SCHRITT 2/8 – Python-Umgebung einrichten"

if [ ! -d "venv" ]; then
    print_step "Erstelle virtuelle Python-Umgebung..."
    python3 -m venv venv
    print_ok "Virtuelle Umgebung erstellt"
else
    print_ok "Virtuelle Umgebung bereits vorhanden"
fi

source venv/bin/activate
print_ok "Virtuelle Umgebung aktiviert"

print_step "Aktualisiere pip..."
pip install --upgrade pip --quiet
print_ok "pip aktualisiert"

echo ""
print_step "Installiere PySide6 (Qt-Framework, ca. 150 MB – bitte warten)..."
print_warn "Dieser Schritt dauert beim ersten Mal 2–5 Minuten..."
pip install "PySide6>=6.7.0" --quiet \
    && print_ok "PySide6 installiert" \
    || { print_error "PySide6-Installation fehlgeschlagen!"; exit 1; }

print_step "Installiere Datenbank & ORM..."
pip install "SQLAlchemy>=2.0.0" "alembic>=1.13.0" --quiet
print_ok "SQLAlchemy & Alembic installiert"

print_step "Installiere PDF-Erzeugung..."
pip install "reportlab>=4.0.0" "Pillow>=10.0.0" --quiet
print_ok "ReportLab & Pillow installiert"

print_step "Installiere Datenverarbeitung & XML..."
pip install "lxml>=5.0.0" "pandas>=2.0.0" --quiet
print_ok "lxml & pandas installiert"

print_step "Installiere Diagramme & Hilfspakete..."
pip install "matplotlib>=3.8.0" "pyperclip>=1.8.0" \
    "cryptography>=42.0.0" "tomli-w>=1.0.0" "psutil>=5.9.0" --quiet
print_ok "Hilfspakete installiert"

echo ""
print_step "Installiere keyring (sichere Passwortverwaltung)..."
pip install "keyring>=24.0.0" --quiet \
    && print_ok "keyring installiert (Passwörter werden im System-Tresor gespeichert)" \
    || print_warn "keyring nicht verfügbar – Fallback-Verschlüsselung wird verwendet"

echo ""
print_info "Optionale PostgreSQL-Unterstützung:"
read -rp "  PostgreSQL-Treiber installieren? (für Netzwerk-Betrieb) [j/N]: " PG_CHOICE
if [[ "$PG_CHOICE" =~ ^[jJ]$ ]]; then
    pip install "psycopg2-binary>=2.9.0" --quiet \
        && print_ok "PostgreSQL-Treiber installiert" \
        || print_warn "psycopg2 fehlgeschlagen – SQLite-Betrieb weiterhin möglich"
else
    print_info "PostgreSQL übersprungen – SQLite (Einzelplatz) wird verwendet."
fi

# =============================================================================
# SCHRITT 3: Unternehmensdaten konfigurieren
# =============================================================================
print_header "SCHRITT 3/8 – Unternehmensdaten"

echo -e "  ${BOLD}Diese Daten erscheinen auf allen Rechnungen und Dokumenten.${RESET}"
echo ""

read -rp "  Firmenname:              " CFG_FIRMA
read -rp "  Straße + Hausnummer:     " CFG_STRASSE
read -rp "  PLZ:                     " CFG_PLZ
read -rp "  Stadt:                   " CFG_STADT
read -rp "  Telefon:                 " CFG_TELEFON
read -rp "  E-Mail:                  " CFG_EMAIL
read -rp "  USt-IdNr (z.B. DE123456789): " CFG_USTID
echo ""
read -rp "  IBAN:                    " CFG_IBAN
read -rp "  Bank (z.B. Sparkasse Freiburg): " CFG_BANK
read -rp "  BIC:                     " CFG_BIC

print_ok "Unternehmensdaten gespeichert"

# =============================================================================
# SCHRITT 4: Rechnungseinstellungen
# =============================================================================
print_header "SCHRITT 4/8 – Rechnungseinstellungen"

echo -e "  ${BOLD}Standardwerte für neue Rechnungen:${RESET}"
echo ""

read -rp "  Mehrwertsteuersatz in % [Standard: 19]: " CFG_MWST
CFG_MWST="${CFG_MWST:-19}"

read -rp "  Zahlungsziel in Tagen [Standard: 14]:   " CFG_ZAHLZIEL
CFG_ZAHLZIEL="${CFG_ZAHLZIEL:-14}"

echo ""
echo -e "  ${BOLD}Rechnungsnummernformat:${RESET}"
echo "  [1] {year}-{number:04d}   → 2026-0001  (Standard, empfohlen)"
echo "  [2] RE{year}{number:04d}  → RE20260001"
echo "  [3] {year}/{number:03d}   → 2026/001"
echo "  [4] Eigenes Format eingeben"
echo ""
read -rp "  Deine Wahl [1-4]: " NR_FORMAT_CHOICE
case $NR_FORMAT_CHOICE in
    2) CFG_NR_FORMAT="RE{year}{number:04d}" ;;
    3) CFG_NR_FORMAT="{year}/{number:03d}" ;;
    4) read -rp "  Format eingeben: " CFG_NR_FORMAT ;;
    *) CFG_NR_FORMAT="{year}-{number:04d}" ;;
esac

print_ok "Rechnungsformat: $CFG_NR_FORMAT"

# =============================================================================
# SCHRITT 5: Mahnwesen konfigurieren
# =============================================================================
print_header "SCHRITT 5/8 – Mahnwesen"

echo -e "  ${BOLD}Wann soll Ilija/das System automatisch eskalieren?${RESET}"
echo "  (Tage nach Fälligkeitsdatum)"
echo ""

read -rp "  Zahlungserinnerung nach [Standard: 7 Tage]:   " CFG_MAHN_ERINNERUNG
CFG_MAHN_ERINNERUNG="${CFG_MAHN_ERINNERUNG:-7}"

read -rp "  1. Mahnung nach          [Standard: 21 Tage]:  " CFG_MAHN_1
CFG_MAHN_1="${CFG_MAHN_1:-21}"

read -rp "  2. Mahnung nach          [Standard: 35 Tage]:  " CFG_MAHN_2
CFG_MAHN_2="${CFG_MAHN_2:-35}"

read -rp "  Inkasso-Stufe nach       [Standard: 49 Tage]:  " CFG_MAHN_INKASSO
CFG_MAHN_INKASSO="${CFG_MAHN_INKASSO:-49}"

echo ""
echo -e "  ${BOLD}Mahngebühren:${RESET}"
read -rp "  Erinnerung      [Standard: 0,00 €]:  " CFG_KOSTEN_ERR
CFG_KOSTEN_ERR="${CFG_KOSTEN_ERR:-0.0}"
read -rp "  1. Mahnung      [Standard: 5,00 €]:  " CFG_KOSTEN_M1
CFG_KOSTEN_M1="${CFG_KOSTEN_M1:-5.0}"
read -rp "  2. Mahnung      [Standard: 10,00 €]: " CFG_KOSTEN_M2
CFG_KOSTEN_M2="${CFG_KOSTEN_M2:-10.0}"
read -rp "  Inkasso         [Standard: 25,00 €]: " CFG_KOSTEN_INK
CFG_KOSTEN_INK="${CFG_KOSTEN_INK:-25.0}"

print_ok "Mahnwesen konfiguriert"

# =============================================================================
# SCHRITT 6: SMTP – E-Mail-Versand
# =============================================================================
print_header "SCHRITT 6/8 – E-Mail-Versand (SMTP)"

echo -e "  ${BOLD}Für den automatischen Versand von Rechnungen und Mahnungen.${RESET}"
echo ""
echo "  Gängige Einstellungen:"
echo "  ┌──────────────────────────────────────────────────────┐"
echo "  │ Gmail:    smtp.gmail.com   Port 587  STARTTLS        │"
echo "  │           (App-Passwort unter myaccount.google.com)  │"
echo "  │ Outlook:  smtp.office365.com  Port 587  STARTTLS     │"
echo "  │ GMX:      mail.gmx.net     Port 587  STARTTLS        │"
echo "  │ Web.de:   smtp.web.de      Port 587  STARTTLS        │"
echo "  │ Strato:   smtp.strato.de   Port 465  SSL/TLS         │"
echo "  │ 1&1 IONOS: smtp.ionos.de   Port 587  STARTTLS        │"
echo "  └──────────────────────────────────────────────────────┘"
echo ""

SMTP_CONFIGURED=false

read -rp "  SMTP jetzt einrichten? [j/N]: " SMTP_CHOICE
if [[ "$SMTP_CHOICE" =~ ^[jJ]$ ]]; then
    echo ""
    read -rp "  SMTP-Server (z.B. smtp.gmail.com):  " CFG_SMTP_SERVER
    read -rp "  SMTP-Port   [587]:                  " CFG_SMTP_PORT
    CFG_SMTP_PORT="${CFG_SMTP_PORT:-587}"
    read -rp "  Benutzername (meist deine E-Mail):  " CFG_SMTP_USER

    echo ""
    echo "  Verschlüsselung:"
    echo "  [1] STARTTLS  (Standard, Port 587)"
    echo "  [2] SSL/TLS   (Port 465)"
    read -rp "  Deine Wahl [1/2]: " ENC_CHOICE
    case $ENC_CHOICE in
        2) CFG_SMTP_ENC="SSL/TLS" ;;
        *) CFG_SMTP_ENC="STARTTLS" ;;
    esac

    echo ""
    echo -n "  SMTP-Passwort (wird sicher gespeichert, nicht im Klartext): "
    read -rs CFG_SMTP_PW
    echo ""

    SMTP_CONFIGURED=true
    print_ok "SMTP-Einstellungen gespeichert"
    print_info "Passwort wird nach dem Start sicher im System-Tresor hinterlegt."
else
    CFG_SMTP_SERVER=""
    CFG_SMTP_PORT="587"
    CFG_SMTP_USER=""
    CFG_SMTP_ENC="STARTTLS"
    CFG_SMTP_PW=""
    print_info "SMTP übersprungen – kann jederzeit unter Einstellungen nachgeholt werden."
fi

# =============================================================================
# SCHRITT 7: Ordnerstruktur & Konfigurationsdateien schreiben
# =============================================================================
print_header "SCHRITT 7/8 – Konfiguration schreiben"

# Dokumentenordner
echo ""
echo -e "  ${BOLD}Wo sollen Dokumente (PDFs, Kundenordner) gespeichert werden?${RESET}"
echo ""
DEFAULT_DOCS="$HOME/OpenPhoenix/Dokumente"
read -rp "  Dokumentenpfad [Standard: $DEFAULT_DOCS]: " CFG_DOCS_PATH
CFG_DOCS_PATH="${CFG_DOCS_PATH:-$DEFAULT_DOCS}"
CFG_DOCS_PATH="${CFG_DOCS_PATH/#\~/$HOME}"
mkdir -p "$CFG_DOCS_PATH"
print_ok "Dokumentenordner: $CFG_DOCS_PATH"

# config.toml schreiben
print_step "Schreibe config.toml..."

CFG_ZIP_CITY="${CFG_PLZ} ${CFG_STADT}"
BANK_DETAILS=""
if [ -n "$CFG_IBAN" ]; then
    BANK_DETAILS="IBAN: ${CFG_IBAN}"
    [ -n "$CFG_BANK" ] && BANK_DETAILS="${BANK_DETAILS} | ${CFG_BANK}"
    [ -n "$CFG_BIC" ]  && BANK_DETAILS="${BANK_DETAILS} | BIC: ${CFG_BIC}"
fi

cat > "$INSTALL_DIR/config.toml" << TOML
[app]
language = "de"
theme = "dark"
version = "3.0.0"

[database]
mode = "local"
path = "openphoenix.db"
host = "localhost"
port = 5432
name = "openphoenix"
user = "erp_user"

[company]
name = "${CFG_FIRMA}"
address = "${CFG_STRASSE}"
zip = "${CFG_PLZ}"
city = "${CFG_STADT}"
zip_city = "${CFG_ZIP_CITY}"
phone = "${CFG_TELEFON}"
email = "${CFG_EMAIL}"
tax_id = "${CFG_USTID}"
bank_details = "${BANK_DETAILS}"

[invoice]
default_vat = ${CFG_MWST}.0
payment_days = ${CFG_ZAHLZIEL}
number_format = "${CFG_NR_FORMAT}"

[dunning]
reminder_days = ${CFG_MAHN_ERINNERUNG}
mahnung1_days = ${CFG_MAHN_1}
mahnung2_days = ${CFG_MAHN_2}
inkasso_days  = ${CFG_MAHN_INKASSO}
cost_erinnerung = ${CFG_KOSTEN_ERR}
cost_mahnung1   = ${CFG_KOSTEN_M1}
cost_mahnung2   = ${CFG_KOSTEN_M2}
cost_inkasso    = ${CFG_KOSTEN_INK}

[smtp]
server     = "${CFG_SMTP_SERVER}"
port       = ${CFG_SMTP_PORT}
user       = "${CFG_SMTP_USER}"
encryption = "${CFG_SMTP_ENC}"
password   = ""

[paths]
documents      = "${CFG_DOCS_PATH}"
pdf_background = ""
xrechnung_output = "${CFG_DOCS_PATH}/XRechnung"
TOML

print_ok "config.toml geschrieben"

# Dokumentenordner anlegen
mkdir -p "$CFG_DOCS_PATH/Rechnungen"
mkdir -p "$CFG_DOCS_PATH/Mahnungen"
mkdir -p "$CFG_DOCS_PATH/XRechnung"
mkdir -p "$CFG_DOCS_PATH/Kunden"
print_ok "Dokumentenordner angelegt unter $CFG_DOCS_PATH"

# SMTP-Passwort sicher speichern (über Python keyring)
if [ "$SMTP_CONFIGURED" = true ] && [ -n "$CFG_SMTP_PW" ]; then
    print_step "Speichere SMTP-Passwort sicher..."
    python3 - << PYEOF
import sys
sys.path.insert(0, "$INSTALL_DIR")
try:
    from core.services.credential_service import passwort_speichern
    passwort_speichern("${CFG_SMTP_PW}")
    print("   ✅  Passwort im System-Tresor gespeichert (keyring)")
except Exception as e:
    # Fallback: Verschlüsselter Datei-Tresor
    try:
        from core.services.credential_service import passwort_speichern
        passwort_speichern("${CFG_SMTP_PW}")
        print("   ✅  Passwort verschlüsselt gespeichert (Fallback)")
    except Exception as e2:
        print(f"   ⚠   Passwort konnte nicht gespeichert werden: {e2}")
        print("   ℹ   Bitte nach dem Start in Einstellungen → SMTP eingeben.")
PYEOF
fi

# Datenbank initialisieren
print_step "Initialisiere Datenbank..."
python3 - << PYEOF
import sys, os
sys.path.insert(0, "$INSTALL_DIR")
os.chdir("$INSTALL_DIR")
try:
    from core.db.engine import db
    from core.config import config
    db.initialize(config.get_database_url())
    db.create_all_tables()
    print("   ✅  Datenbank erfolgreich initialisiert")
except Exception as e:
    print(f"   ❌  Datenbankfehler: {e}")
    sys.exit(1)
PYEOF

# =============================================================================
# Startskript erstellen
# =============================================================================
print_step "Erstelle Startskript (start.sh)..."

cat > "$INSTALL_DIR/start.sh" << STARTSH
#!/bin/bash
# OpenPhoenix ERP v2 – Startskript
cd "\$(dirname "\${BASH_SOURCE[0]}")"
source venv/bin/activate
python3 main.py "\$@"
STARTSH
chmod +x "$INSTALL_DIR/start.sh"
print_ok "start.sh erstellt"

# Desktop-Shortcut (Linux)
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    DESKTOP_DIR="$HOME/.local/share/applications"
    mkdir -p "$DESKTOP_DIR"
    cat > "$DESKTOP_DIR/openphoenix-erp.desktop" << DESKTOP
[Desktop Entry]
Version=1.0
Type=Application
Name=OpenPhoenix ERP
Comment=Freies ERP-System für KMU
Exec=${INSTALL_DIR}/start.sh
Icon=${INSTALL_DIR}/resources/icons/myicon.png
Terminal=false
Categories=Office;Finance;
StartupWMClass=OpenPhoenix
DESKTOP
    chmod +x "$DESKTOP_DIR/openphoenix-erp.desktop"
    print_ok "Desktop-Shortcut erstellt (~/.local/share/applications)"
fi

# =============================================================================
# SCHRITT 8: Abschluss & Start
# =============================================================================
print_header "SCHRITT 8/8 – Installation abgeschlossen"

clear; echo ""
echo -e "${GREEN}${BOLD}"
echo "  ╔══════════════════════════════════════════════════════════════╗"
echo "  ║                                                              ║"
echo "  ║      OpenPhoenix ERP ist bereit!                            ║"
echo "  ║                                                              ║"
echo "  ╚══════════════════════════════════════════════════════════════╝"
echo -e "${RESET}"
sleep 1

echo -e "${CYAN}${BOLD}  Deine Konfiguration:${RESET}"
echo ""
echo -e "  🏢 Firma:          ${BOLD}${CFG_FIRMA:-nicht angegeben}${RESET}"
echo    "  📍 Adresse:        ${CFG_STRASSE}, ${CFG_PLZ} ${CFG_STADT}"
echo    "  📧 E-Mail:         ${CFG_EMAIL:-nicht angegeben}"
echo    "  🧾 MwSt:           ${CFG_MWST}%  |  Zahlungsziel: ${CFG_ZAHLZIEL} Tage"
echo    "  📁 Dokumente:      ${CFG_DOCS_PATH}"
if [ "$SMTP_CONFIGURED" = true ]; then
echo    "  📬 SMTP:           ${CFG_SMTP_SERVER}:${CFG_SMTP_PORT} (${CFG_SMTP_ENC})"
else
echo    "  📬 SMTP:           ⚠  noch nicht konfiguriert (Einstellungen → SMTP)"
fi
echo ""
divider
echo ""
echo -e "  ${BOLD}So startest du OpenPhoenix ERP zukünftig:${RESET}"
echo ""
echo -e "  ${CYAN}cd ${INSTALL_DIR}${RESET}"
echo -e "  ${CYAN}./start.sh${RESET}"
echo ""
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
echo "  Oder über das Anwendungsmenü: OpenPhoenix ERP"
echo ""
fi
divider
echo ""
echo -e "  ${BOLD}Ilija-Integration:${RESET}"
echo "  Damit Ilija OpenPhoenix steuern kann, nach dem Start einmal eingeben:"
echo -e "  ${CYAN}erp_pfad_setzen(pfad=\"${INSTALL_DIR}\")${RESET}"
echo ""
divider

read -rp "  OpenPhoenix ERP jetzt starten? [J/n]: " START_NOW
if [[ ! "$START_NOW" =~ ^[nN]$ ]]; then
    echo ""
    echo -e "${GREEN}${BOLD}  Starte OpenPhoenix ERP...${RESET}"
    sleep 1
    ./start.sh
else
    echo ""
    print_ok "Installation abgeschlossen. Starte mit: ./start.sh"
    echo ""
fi
