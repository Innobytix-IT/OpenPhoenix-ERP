import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import sqlite3
import os
from datetime import datetime, timedelta
import subprocess
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib.colors import black, grey
from reportlab.platypus import Paragraph, Table, TableStyle, Image, Spacer, BaseDocTemplate, PageTemplate, Frame
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
import logging
from ttkthemes import ThemedTk
import hashlib
import sys
import uuid
import shutil
import base64
import json

# --- E-Mail Imports (bereits vorhanden) ---
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from email.utils import formatdate
# --- Ende E-Mail Imports ---

logging.basicConfig(filename='mahntool.log', level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# --- Constants ---
CUSTOM_PLACEHOLDERS_FILENAME = "custom_placeholders.json" # Neu für eigene Platzhalter

# --- GoBD-Hilfsfunktionen (Audit Log, User) ---

def get_current_user():
    """Ermittelt den aktuellen Systembenutzer für Audit-Zwecke."""
    try:
        # os.getlogin() ist unter Windows und Unix-Systemen zuverlässig
        return os.getlogin()
    except Exception as e:
        logging.warning(f"Konnte Systembenutzer nicht ermitteln, verwende 'system'. Fehler: {e}")
        return "system"

def log_audit_action(conn, action, record_id=None, details="", user="system"):
    """
    Protokolliert eine Aktion in der audit_log Tabelle gemäß GoBD.
    Args:
        conn (sqlite3.Connection): Die aktive Datenbankverbindung.
        action (str): Eindeutiger Aktions-Bezeichner (z.B. 'MAHNSCHREIBEN_GENERERT').
        record_id (int, optional): Die ID des betroffenen Datensatzes (z.B. rechnungen.id).
        details (str, optional): Detaillierte Beschreibung der Aktion.
        user (str, optional): Der Benutzer, der die Aktion ausgeführt hat.
    """
    if not conn:
        logging.error(f"AUDIT-FEHLER: Keine DB-Verbindung für Aktion '{action}'. Log-Eintrag übersprungen.")
        return

    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO audit_log (timestamp, user, action, record_id, details)
            VALUES (?, ?, ?, ?, ?)
        """, (timestamp, user, action, record_id, details))
        conn.commit()
        logging.info(f"AUDIT LOG: User '{user}' | Aktion '{action}' | Record ID '{record_id}' | Details: {details}")
    except sqlite3.Error as e:
        logging.error(f"Fehler beim Schreiben des Audit-Logs für Aktion '{action}': {e}")
        conn.rollback()
    except Exception as e:
        logging.exception(f"Unerwarteter Fehler beim Schreiben des Audit-Logs für Aktion '{action}':")
        conn.rollback()

# --- Hilfsfunktionen (Lizenz, Hardware ID, DatenSchloss) ---


def _find_daten_schloss_tool():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    tool_name_base = "DatenSchloss"
    tool_exe_path = os.path.join(script_dir, f"{tool_name_base}.exe")
    tool_pyw_path = os.path.join(script_dir, f"{tool_name_base}.pyw")
    if os.path.exists(tool_exe_path):
        logging.info(f"DatenSchloss Tool gefunden (EXE): {tool_exe_path}")
        return [tool_exe_path]
    if os.path.exists(tool_pyw_path):
        interpreter = sys.executable
        if sys.platform == "win32" and interpreter.lower().endswith("python.exe"):
             pythonw_interpreter = os.path.join(os.path.dirname(interpreter), "pythonw.exe")
             if os.path.exists(pythonw_interpreter):
                 interpreter = pythonw_interpreter
             else:
                 logging.warning(f"pythonw.exe nicht gefunden ({pythonw_interpreter}), verwende stattdessen {sys.executable} für .pyw")
        logging.info(f"DatenSchloss Tool gefunden (PYW): {tool_pyw_path} (Interpreter: {interpreter})")
        return [interpreter, tool_pyw_path]
    logging.warning("DatenSchloss Tool nicht gefunden (gesucht: .exe, .pyw im Skript-Verzeichnis).")
    return None

def _run_daten_schloss_startup():
    logging.info("Prüfe und starte DatenSchloss Tool (Startup)...")
    tool_command = _find_daten_schloss_tool()
    if tool_command:
        try:
            logging.info(f"Starte DatenSchloss Tool: {' '.join(tool_command)}")
            process = subprocess.run(tool_command, check=True, cwd=os.path.dirname(os.path.abspath(__file__)), text=True, capture_output=True)
            logging.info(f"DatenSchloss Tool (Startup) erfolgreich beendet. Exit Code: {process.returncode}")
            return True
        except FileNotFoundError:
             logging.error(f"DatenSchloss Tool oder Interpreter nicht gefunden. Command: {' '.join(tool_command)}")
             messagebox.showerror("Fehler", "Das benötigte Tool 'DatenSchloss' wurde nicht gefunden oder kann nicht gestartet werden.\n\nBitte stellen Sie sicher, dass 'DatenSchloss.exe' oder 'DatenSchloss.pyw' im selben Verzeichnis wie die Anwendung liegt.")
             return False
        except subprocess.CalledProcessError as e:
            logging.error(f"DatenSchloss Tool (Startup) beendet mit Fehler (Exit Code: {e.returncode}). Stderr:\n{e.stderr}\nStdout:\n{e.stdout}")
            messagebox.showerror("Fehler", f"Das Tool 'DatenSchloss' ist beim Start unerwartet beendet (Exit Code {e.returncode}).\n\nBitte prüfen Sie die Protokolle des Tools oder kontaktieren Sie den Support.\n\nAnwendung wird beendet.")
            return False
        except Exception as e:
            logging.exception("Unerwarteter Fehler beim Starten des DatenSchloss Tools (Startup):")
            messagebox.showerror("Fehler", f"Ein unerwarteter Fehler ist beim Starten des Tools 'DatenSchloss' aufgetreten:\n{e}\n\nAnwendung wird beendet.")
            return False
    else:
        logging.error("DatenSchloss Tool wurde nicht gefunden. Anwendung kann nicht gestartet werden.")
        messagebox.showerror("Fehler", "Das benötigte Tool 'DatenSchloss' (DatenSchloss.exe oder .pyw) wurde im Anwendungsverzeichnis nicht gefunden.\n\nAnwendung wird beendet.")
        return False

def _run_daten_schloss_shutdown():
    logging.info("Starte DatenSchloss Tool (Shutdown)...")
    tool_command = _find_daten_schloss_tool()
    if tool_command:
        try:
            logging.info(f"Starte DatenSchloss Tool: {' '.join(tool_command)}")
            process = subprocess.run(tool_command, cwd=os.path.dirname(os.path.abspath(__file__)), text=True, capture_output=True)
            logging.info(f"DatenSchloss Tool (Shutdown) beendet. Exit Code: {process.returncode}")
            if process.returncode != 0:
                 logging.warning(f"DatenSchloss Tool (Shutdown) beendet mit Non-Zero Exit Code: {process.returncode}. Stderr:\n{process.stderr}\nStdout:\n{process.stdout}")
        except FileNotFoundError:
             logging.error(f"DatenSchloss Tool (Shutdown) nicht gefunden (oder Interpreter für .pyw): {' '.join(tool_command)}")
        except Exception as e:
            logging.exception("Unerwarteter Fehler beim Starten des DatenSchloss Tools (Shutdown):")
    else:
        logging.warning("DatenSchloss Tool nicht gefunden, kann nicht beim Beenden gestartet werden.")

# --- Lizenz- und DatenSchloss-Prüfung beim Start ---
if not _run_daten_schloss_startup():
     sys.exit(1)


# --- Statische DB-Verbindung und Schema-Check ---
def connect_db_static(db_path):
    conn = None
    try:
        conn = sqlite3.connect(db_path, timeout=15.0)
        cursor = conn.cursor()
        
        # ### GoBD-ÄNDERUNG ###: Sicherstellen, dass die audit_log Tabelle existiert
        # Dies macht die Anwendung robuster, falls sie mit einer älteren DB-Version verbunden wird.
        try:
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    user TEXT,
                    action TEXT NOT NULL,
                    record_id INTEGER,
                    details TEXT
                )
            ''')
            # Index für schnellere Abfragen erstellen, falls nicht vorhanden
            cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_audit_log_timestamp'")
            if not cursor.fetchone():
                cursor.execute("CREATE INDEX idx_audit_log_timestamp ON audit_log(timestamp)")
                logging.info("Datenbank-Schema aktualisiert: Index 'idx_audit_log_timestamp' für 'audit_log' erstellt.")
            conn.commit()
        except sqlite3.Error as e_audit:
            logging.error(f"Konnte GoBD-Tabelle 'audit_log' nicht erstellen oder prüfen: {e_audit}")
            conn.rollback()

        # Reguläre Schema-Prüfungen
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='kunden'")
        if not cursor.fetchone():
             logging.error(f"DB '{db_path}' scheint kein gültiges Schema zu haben (Tabelle 'kunden' fehlt).")
             messagebox.showerror("DB Fehler", f"Datenbank '{db_path}' hat kein gültiges Schema.\nBitte mit 'Kundenverwaltung.exe' initialisieren.")
             return None
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='rechnungen'")
        if not cursor.fetchone():
            logging.error(f"DB '{db_path}' scheint kein gültiges Schema zu haben (Tabelle 'rechnungen' fehlt).")
            messagebox.showerror("DB Fehler", f"Datenbank '{db_path}' hat kein gültiges Schema.\nBitte mit 'Kundenverwaltung.exe' initialisieren.")
            return None

        # Sicherstellen, dass kunden_dokumente existiert
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS kunden_dokumente (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kunde_id INTEGER,
                dokument_pfad TEXT NOT NULL,
                dateiname TEXT NOT NULL,
                FOREIGN KEY (kunde_id) REFERENCES kunden(id) ON DELETE CASCADE
            )
        ''')

        # ### KORREKTUR/MIGRATION START ###
        # Schema-Migration für benötigte Spalten in 'rechnungen' durchführen

        # 1. Spalte 'datum_letzte_mahnung'
        try:
            cursor.execute("SELECT datum_letzte_mahnung FROM rechnungen LIMIT 1")
        except sqlite3.OperationalError:
            try:
                cursor.execute("ALTER TABLE rechnungen ADD COLUMN datum_letzte_mahnung TEXT")
                conn.commit()
                logging.info("Datenbank-Schema aktualisiert: Spalte 'datum_letzte_mahnung' zur Tabelle 'rechnungen' hinzugefügt.")
            except sqlite3.Error as e_alter:
                logging.error(f"Konnte Tabelle 'rechnungen' nicht um Spalte 'datum_letzte_mahnung' erweitern: {e_alter}")
                conn.rollback()

        # 2. Spalte 'mahngebuehren'
        try:
            cursor.execute("SELECT mahngebuehren FROM rechnungen LIMIT 1")
        except sqlite3.OperationalError:
            try:
                cursor.execute("ALTER TABLE rechnungen ADD COLUMN mahngebuehren REAL DEFAULT 0.0")
                conn.commit()
                logging.info("Datenbank-Schema aktualisiert: Spalte 'mahngebuehren' zur Tabelle 'rechnungen' hinzugefügt.")
            except sqlite3.Error as e_alter:
                logging.error(f"Konnte Tabelle 'rechnungen' nicht um Spalte 'mahngebuehren' erweitern: {e_alter}")
                conn.rollback()

        # 3. Spalte 'offener_betrag'
        try:
            cursor.execute("SELECT offener_betrag FROM rechnungen LIMIT 1")
        except sqlite3.OperationalError:
            try:
                cursor.execute("ALTER TABLE rechnungen ADD COLUMN offener_betrag REAL")
                cursor.execute("UPDATE rechnungen SET offener_betrag = summe_brutto WHERE offener_betrag IS NULL")
                conn.commit()
                logging.info("Datenbank-Schema aktualisiert: Spalte 'offener_betrag' in 'rechnungen' hinzugefügt und initialisiert.")
            except sqlite3.Error as e_alter:
                logging.error(f"Konnte Tabelle 'rechnungen' nicht um Spalte 'offener_betrag' erweitern: {e_alter}")
                conn.rollback()
        # ### KORREKTUR/MIGRATION ENDE ###

        logging.info(f"Datenbankschema von '{db_path}' scheint gültig.")
        conn.commit()
        return conn
    except sqlite3.Error as e:
        logging.error(f"Fehler beim Verbinden oder Prüfen der Datenbank '{db_path}': {e}")
        messagebox.showerror("DB Fehler", f"Fehler beim Verbinden oder Prüfen der Datenbank:\n{db_path}\n{e}")
        if conn: conn.rollback()
        return None
    except Exception as e:
         logging.exception(f"Unerwarteter Fehler bei DB Verbindung/Prüfung '{db_path}':")
         messagebox.showerror("Fehler", f"Unerwarteter Fehler bei DB Verbindung/Prüfung:\n{e}")
         return None


# --- Hilfsfunktion zum Parsen von Floats ---
def parse_float(value_str, default=0.0):
    if not isinstance(value_str, str): value_str = str(value_str)
    value_str = value_str.strip()
    if not value_str: return default
    last_dot = value_str.rfind('.'); last_comma = value_str.rfind(',')
    try:
        if last_comma != -1 and last_comma > last_dot: cleaned_str = value_str.replace('.', '').replace(',', '.')
        elif last_dot != -1 and last_dot > last_comma: cleaned_str = value_str.replace(',', '')
        else: cleaned_str = value_str
        return float(cleaned_str)
    except (ValueError, TypeError): logging.warning(f"Konnte '{value_str}' nicht in Float umwandeln."); return default


# --- PDF Textvorlagen (Standardwerte) ---
PDF_TEMPLATES_FILENAME = "pdf_letter_templates.json"
DEFAULT_PDF_LETTER_TEMPLATES = {
    "reminder": {
        "display_name": "Erinnerung",
        "title_text_template": "Erinnerung zu Rechnung Nr. {{RECHNUNGSNUMMER}}",
        "intro_text_template": "Sehr geehrte/r Frau/Herr {{KUNDE_ANREDE_NAME}},\n\nam {{RECHNUNGSDATUM}} haben wir Ihnen Rechnung Nr. {{RECHNUNGSNUMMER}} über einen Betrag von {{BETRAG_BRUTTO_FORM}} gesendet. Das Zahlungsziel war der {{FAELLIGKEITSDATUM}}.\nLeider konnten wir bis heute noch keinen Zahlungseingang auf unserem Konto verzeichnen.\n\nWir möchten Sie hiermit höflich an die Begleichung des ausstehenden Betrags erinnern.\nBitte überweisen Sie den fälligen Gesamtbetrag von {{BETRAG_BRUTTO_FORM}} unter Angabe der Rechnungsnummer auf unser Konto.",
        "closing_text_template": "Wir bitten Sie, die Zahlung so bald wie möglich vorzunehmen, um weitere Schritte zu vermeiden.\n\nSollten Sie die Zahlung zwischenzeitlich veranlasst haben, betrachten Sie dieses Schreiben bitte als gegenstandslos.\n\nMit freundlichen Grüßen,"
    },
    "dunning1": {
        "display_name": "1. Mahnung",
        "title_text_template": "1. Mahnung zu Rechnung Nr. {{RECHNUNGSNUMMER}}",
        "intro_text_template": "Sehr geehrte/r Frau/Herr {{KUNDE_ANREDE_NAME}},\n\ntrotz unserer Erinnerung konnten wir für Ihre Rechnung Nr. {{RECHNUNGSNUMMER}} vom {{RECHNUNGSDATUM}} über {{BETRAG_BRUTTO_FORM}} leider immer noch keinen Zahlungseingang verzeichnen.\nDie Rechnung war am {{FAELLIGKEITSDATUM}} fällig.\n\nFür den hierdurch entstandenen Aufwand müssen wir Ihnen leider Mahnkosten in Höhe von {{MAHNKOSTEN_FORM}} in Rechnung stellen.\nWir fordern Sie hiermit auf, den offenen Gesamtbetrag von {{GESAMTBETRAG_INKL_MAHNKOSTEN_FORM}} umgehend, spätestens jedoch bis zum {{DATUM_IN_7_TAGEN}} zu begleichen. Bitte geben Sie bei der Überweisung unbedingt die Rechnungsnummer an.",
        "closing_text_template": "Sollten Sie die Zahlung bereits veranlasst haben, betrachten Sie dieses Schreiben bitte als gegenstandslos.\nAndernfalls sehen wir uns gezwungen, weitere Schritte einzuleiten.\n\nMit freundlichen Grüßen,"
    },
    "dunning2": {
        "display_name": "2. Mahnung",
        "title_text_template": "2. Mahnung zu Rechnung Nr. {{RECHNUNGSNUMMER}}",
        "intro_text_template": "Sehr geehrte/r Frau/Herr {{KUNDE_ANREDE_NAME}},\n\nbezüglich der offenen Forderung aus Rechnung Nr. {{RECHNUNGSNUMMER}} vom {{RECHNUNGSDATUM}} haben wir Ihnen bereits am {{DATUM_LETZTE_MAHNUNG}} eine 1. Mahnung gesendet.\nTrotz mehrfacher Aufforderung konnten wir bis heute keinen Zahlungseingang feststellen.\n\nZusätzlich zu den bereits angemahnten Kosten fallen für diese Mahnung weitere Gebühren an. Wir setzen Ihnen hiermit eine letzte Frist zur Zahlung des nun offenen Gesamtbetrags von {{GESAMTBETRAG_INKL_MAHNKOSTEN_FORM}} bis zum {{DATUM_IN_5_TAGEN}}.",
        "closing_text_template": "Sollte der Betrag nicht innerhalb dieser Frist bei uns eingehen, sehen wir uns gezwungen, ohne weitere Benachrichtigung rechtliche Schritte einzuleiten oder ein Inkassounternehmen mit der Beitreibung der Forderung zu beauftragen. Dadurch entstehende Kosten gehen zu Ihren Lasten.\n\nMit freundlichen Grüßen,"
    },
    "collection_advice": {
        "display_name": "Inkasso Ankündigung",
        "title_text_template": "Ankündigung der Weiterleitung an Inkasso zu Rechnung Nr. {{RECHNUNGSNUMMER}}",
        "intro_text_template": "Sehr geehrte/r Frau/Herr {{KUNDE_ANREDE_NAME}},\n\ntrotz unserer wiederholten Aufforderungen (Rechnung Nr. {{RECHNUNGSNUMMER}} vom {{RECHNUNGSDATUM}}, Fälligkeit {{FAELLIGKEITSDATUM}}, 1. Mahnung, 2. Mahnung) haben wir den offenen Gesamtbetrag von {{BETRAG_BRUTTO_FORM}} bis heute nicht erhalten.\n\nDa alle bisherigen Bemühungen erfolglos blieben, sehen wir uns gezwungen, diese unbeglichene Forderung an ein Inkassounternehmen zur weiteren Bearbeitung zu übergeben. Die dadurch entstehenden Kosten gehen zu Ihren Lasten.",
        "closing_text_template": "Wir bedauern diesen Schritt, sehen aber keinen anderen Weg, um die offenen Beträge einzuziehen.\n\nMit freundlichen Grüßen,"
    },
    "payment_reminder_open": {
        "display_name": "Zahlungserinnerung (Offen)",
        "title_text_template": "Zahlungserinnerung zu Rechnung Nr. {{RECHNUNGSNUMMER}}",
        "intro_text_template": "Sehr geehrte/r Frau/Herr {{KUNDE_ANREDE_NAME}},\n\nbezüglich Ihrer Rechnung Nr. {{RECHNUNGSNUMMER}} vom {{RECHNUNGSDATUM}} über {{BETRAG_BRUTTO_FORM}} stellen wir fest, dass der Zahlungstermin ({{FAELLIGKEITSDATUM}}) überschritten wurde.\n\nWir möchten Sie hiermit höflich bitten, den ausstehenden Betrag umgehend zu überweisen.",
        "closing_text_template": "Bitte geben Sie bei der Überweisung die Rechnungsnummer an.\n\nSollten Sie die Zahlung zwischenzeitlich veranlasst haben, betrachten Sie dieses Schreiben bitte als gegenstandslos.\n\nMit freundlichen Grüßen,"
    }
}
PDF_TEMPLATE_KEY_MAP = {
    'Steht zur Erinnerung an': 'reminder',
    'Steht zur Mahnung an': 'dunning1',
    'Steht zur Mahnung 2 an': 'dunning2',
    'Bitte an Inkasso weiterleiten': 'collection_advice',
    'Offen': 'payment_reminder_open'
}

# --- Standard-Platzhalter (Eingebaut) ---
PDF_PLACEHOLDERS_BUILTIN = [
    "{{KUNDE_ANREDE_NAME}} (z.B. Herr Mustermann)", "{{KUNDE_VORNAME}}", "{{KUNDE_NACHNAME}}",
    "{{KUNDE_FIRMA_TITEL}} (Firma/Titel des Kunden)", "{{KUNDE_STRASSE_NR}}", "{{KUNDE_PLZ_ORT}}",
    "{{RECHNUNGSNUMMER}}", "{{RECHNUNGSDATUM}} (Format: TT.MM.JJJJ)", "{{FAELLIGKEITSDATUM}} (Format: TT.MM.JJJJ)",
    "{{BETRAG_BRUTTO_FORM}} (z.B. 1.234,56 €)", "{{BETRAG_OFFEN_FORM}} (Offener Rechnungsbetrag, formatiert)",
    "{{MAHNKOSTEN_FORM}} (Anfallende Mahnkosten, formatiert)",
    "{{GESAMTBETRAG_INKL_MAHNKOSTEN_FORM}} (Gesamtforderung inkl. Mahnkosten)",
    "{{HEUTIGES_DATUM}} (Format: TT.MM.JJJJ)", "{{DATUM_IN_7_TAGEN}} (Nur für 1. Mahnung relevant)",
    "{{DATUM_IN_5_TAGEN}} (Nur für 2. Mahnung relevant)", "{{DATUM_LETZTE_MAHNUNG}} (Datum der 1. Mahnung, nur für 2. Mahnung)",
    "{{EIGENE_FIRMA_NAME}}", "{{EIGENE_FIRMA_ADRESSE}}", "{{EIGENE_FIRMA_PLZ_ORT}}",
    "{{EIGENE_FIRMA_TELEFON}}", "{{EIGENE_FIRMA_EMAIL}}", "{{EIGENE_FIRMA_STEUERID}}",
    "{{EIGENE_FIRMA_BANKVERBINDUNG}}"
]

# --- Funktionen für benutzerdefinierte Platzhalter ---

def get_custom_placeholders_path():
    """Gibt den absoluten Pfad zur Datei der benutzerdefinierten Platzhalter zurück."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), CUSTOM_PLACEHOLDERS_FILENAME)

def load_custom_placeholders():
    """Lädt benutzerdefinierte Platzhalter aus der JSON-Datei."""
    placeholders_path = get_custom_placeholders_path()
    custom_placeholders = {}
    try:
        if os.path.exists(placeholders_path):
            with open(placeholders_path, "r", encoding='utf-8') as f:
                loaded_data = json.load(f)
                if isinstance(loaded_data, dict):
                    custom_placeholders = loaded_data
                    logging.info(f"Benutzerdefinierte Platzhalter aus '{placeholders_path}' geladen ({len(custom_placeholders)} Einträge).")
                else:
                    logging.error(f"Fehler beim Laden: '{placeholders_path}' enthält kein gültiges JSON-Objekt (dict).")
        else:
            logging.info(f"Datei für benutzerdefinierte Platzhalter ('{placeholders_path}') nicht gefunden. Starte mit leerer Liste.")
    except json.JSONDecodeError as e:
        logging.error(f"Fehler beim Parsen der benutzerdefinierten Platzhalter-Datei '{placeholders_path}': {e}")
        messagebox.showerror("Dateifehler", f"Fehler beim Lesen der benutzerdefinierten Platzhalter:\n{e}\n\nDie Datei wird ignoriert/überschrieben.", icon='warning')
    except Exception as e:
        logging.exception(f"Unerwarteter Fehler beim Laden der benutzerdefinierten Platzhalter aus '{placeholders_path}':")
        messagebox.showerror("Dateifehler", f"Unerwarteter Fehler beim Laden der benutzerdefinierten Platzhalter:\n{e}", icon='error')
    return custom_placeholders

def save_custom_placeholders(placeholders_dict):
    """Speichert das Dictionary der benutzerdefinierten Platzhalter in der JSON-Datei."""
    placeholders_path = get_custom_placeholders_path()
    try:
        os.makedirs(os.path.dirname(placeholders_path), exist_ok=True)
        # Sortieren für konsistente Dateireihenfolge
        with open(placeholders_path, "w", encoding='utf-8') as f:
            json.dump(placeholders_dict, f, indent=4, ensure_ascii=False, sort_keys=True)
        logging.info(f"Benutzerdefinierte Platzhalter in '{placeholders_path}' gespeichert.")
        return True
    except Exception as e:
        logging.error(f"Fehler beim Speichern der benutzerdefinierten Platzhalter in '{placeholders_path}': {e}")
        messagebox.showerror("Speicherfehler", f"Fehler beim Speichern der benutzerdefinierten Platzhalter:\n{e}")
        return False

# --- Ende Funktionen für benutzerdefinierte Platzhalter ---


class MahnToolApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Mahnwesen (GoBD)")
        self.root.geometry("900x600")
        try:
            icon_path = os.path.join(os.path.dirname(__file__), 'app_icon.ico')
            if os.path.exists(icon_path): self.root.iconbitmap(default=icon_path); logging.info(f"Fenster-Icon gesetzt: {icon_path}")
            else: logging.warning(f"Fenster-Icon-Datei nicht gefunden: {icon_path}. Das Standard-Tkinter-Icon wird verwendet.")
        except tk.TclError as e: logging.error(f"Fehler beim Setzen des Fenster-Icons (TclError): {e}")
        except Exception as e: logging.error(f"Unerwarteter Fehler beim Setzen des Fenster-Icons: {e}")

        # --- Standardwerte und Initialisierung ---
        self.current_user = get_current_user() # ### GoBD-ÄNDERUNG ###: Benutzer für Audit-Log erfassen
        self.db_path = "unternehmen_gobd.db"
        self.pdf_background_path = ""
        self.current_theme = "breeze"
        self.document_base_path = os.path.join(os.path.expanduser("~"), "UnternehmensDokumente")
        self.default_vat_rate = 19.0
        self.company_details = {
            "name": "Ihre Firma GmbH", "address": "Musterstraße 1", "zip_city": "12345 Musterstadt",
            "phone": "0123-456789", "email": "info@ihre-firma.de", "tax_id": "DE123456789",
            "bank_details": "Ihre Bank, IBAN: DE..., BIC: ..."
        }
        self.reminder_days = 7
        self.mahnung1_days = 21
        self.mahnung2_days = 35
        self.inkasso_days = 49
        self.mahnkosten_1 = 5.0
        self.mahnkosten_2 = 10.0
        self.smtp_server = ""
        self.smtp_port = 587
        self.smtp_user = ""
        self.smtp_password = None # Wird nur für die Sitzung gespeichert
        self.smtp_encryption = "STARTTLS"
        self.pdf_letter_templates = {}
        self._load_pdf_letter_templates()

        # --- Benutzerdefinierte Platzhalter laden ---
        self.custom_placeholders_dict = load_custom_placeholders()
        # --- Ende Laden ---

        # --- Konfiguration aus config.txt laden ---
        config_needs_update = False
        config_dict = {}
        config_file_path = "config.txt"
        if os.path.exists(config_file_path):
            try:
                with open(config_file_path, "r", encoding='utf-8') as f:
                    for line in f:
                        if "=" in line and not line.strip().startswith('#'):
                            key, value = line.strip().split("=", 1)
                            if key.startswith("company_"):
                                self.company_details[key.split("company_", 1)[1]] = value
                            elif key != 'smtp_password': # Passwort nie aus Datei laden
                                config_dict[key] = value
            except Exception as e:
                logging.error(f"Fehler beim Lesen von {config_file_path} beim Start: {e}")
                messagebox.showwarning("Konfigurationsfehler", f"Fehler beim Lesen von {config_file_path}:\n{e}\nVerwende Standardeinstellungen.")
        else:
            config_needs_update = True # Datei fehlt, muss erstellt/aktualisiert werden

        # Werte aus config_dict oder Standardwerte übernehmen
        self.db_path = config_dict.get('db_path', self.db_path)
        self.pdf_background_path = config_dict.get('pdf_background_path', self.pdf_background_path)
        self.current_theme = config_dict.get('theme', self.current_theme)
        self.document_base_path = config_dict.get('document_base_path', self.document_base_path)
        self.default_vat_rate = parse_float(config_dict.get('default_vat_rate', str(self.default_vat_rate)), 19.0)
        self.mahnkosten_1 = parse_float(config_dict.get('mahnkosten_1', str(self.mahnkosten_1)), 5.0)
        self.mahnkosten_2 = parse_float(config_dict.get('mahnkosten_2', str(self.mahnkosten_2)), 10.0)
        try: self.reminder_days = int(config_dict.get('reminder_days', self.reminder_days))
        except ValueError: logging.warning("Ungültiger Wert für reminder_days in config.txt.")
        try: self.mahnung1_days = int(config_dict.get('mahnung1_days', self.mahnung1_days))
        except ValueError: logging.warning("Ungültiger Wert für mahnung1_days in config.txt.")
        try: self.mahnung2_days = int(config_dict.get('mahnung2_days', self.mahnung2_days))
        except ValueError: logging.warning("Ungültiger Wert für mahnung2_days in config.txt.")
        try: self.inkasso_days = int(config_dict.get('inkasso_days', self.inkasso_days))
        except ValueError: logging.warning("Ungültiger Wert für inkasso_days in config.txt.")
        self.smtp_server = config_dict.get('smtp_server', self.smtp_server)
        try: self.smtp_port = int(config_dict.get('smtp_port', self.smtp_port))
        except ValueError: logging.warning("Ungültiger Wert für smtp_port in config.txt.")
        self.smtp_user = config_dict.get('smtp_user', self.smtp_user)
        self.smtp_encryption = config_dict.get('smtp_encryption', self.smtp_encryption)

        # --- config.txt aktualisieren, falls nötig ---
        if config_needs_update:
            logging.info("Aktualisiere oder erstelle config.txt...")
            all_settings = {
                'db_path': self.db_path, 'pdf_background_path': self.pdf_background_path, 'theme': self.current_theme,
                'document_base_path': self.document_base_path, 'default_vat_rate': self.default_vat_rate,
                'reminder_days': self.reminder_days, 'mahnung1_days': self.mahnung1_days, 'mahnung2_days': self.mahnung2_days, 'inkasso_days': self.inkasso_days,
                'mahnkosten_1': self.mahnkosten_1, 'mahnkosten_2': self.mahnkosten_2,
                'smtp_server': self.smtp_server, 'smtp_port': self.smtp_port, 'smtp_user': self.smtp_user,
                'smtp_password': "", # Passwort immer leer schreiben
                'smtp_encryption': self.smtp_encryption,
            }
            for key, value in self.company_details.items(): all_settings[f'company_{key}'] = value
            try:
                with open(config_file_path, "w", encoding='utf-8') as f:
                    f.write("# Konfigurationsdatei für Mahnwesen\n")
                    f.write("# Ändern Sie die Werte nach Bedarf.\n# Das SMTP-Passwort wird hier nicht gespeichert.\n\n")
                    for key, value in all_settings.items():
                         f.write(f"{key}={value}\n")
                logging.info(f"{config_file_path} aktualisiert oder neu erstellt.")
            except Exception as e:
                 logging.error(f"Fehler beim Schreiben/Aktualisieren von {config_file_path}: {e}")
                 messagebox.showwarning("Konfigurationsfehler", f"{config_file_path} konnte nicht aktualisiert/geschrieben werden:\n{e}")

        # --- Theme anwenden ---
        try:
            self.available_themes = self.root.get_themes()
        except Exception as e:
            logging.error(f"Fehler beim Abrufen der verfügbaren Themes: {e}")
            self.available_themes = ['clam', 'alt', 'default', 'classic'] # Fallback-Liste
        if self.current_theme not in self.available_themes:
            self.current_theme = "clam" # Fallback, falls gespeichertes Theme nicht existiert
            logging.warning(f"Gespeichertes Theme '{config_dict.get('theme', '')}' nicht verfügbar, verwende Fallback '{self.current_theme}'.")
        try:
            self.root.set_theme(self.current_theme)
        except tk.TclError:
            logging.error(f"Theme '{self.current_theme}' konnte nicht angewendet werden. Verwende Fallback 'clam'.")
            self.current_theme = "clam"
            try:
                self.root.set_theme(self.current_theme)
            except Exception as theme_err:
                 logging.error(f"Konnte auch Fallback-Theme 'clam' nicht laden: {theme_err}")
                 messagebox.showerror("Theme Fehler", "Konnte kein gültiges Theme laden. Darstellungsprobleme möglich.")
        except Exception as theme_err:
             logging.error(f"Allgemeiner Fehler beim Setzen des Themes '{self.current_theme}': {theme_err}")
             messagebox.showerror("Theme Fehler", f"Fehler beim Laden des Themes:\n{theme_err}")

        # --- Weitere Initialisierungen ---
        style = ttk.Style()
        style.map('Treeview', background=[('selected', 'SystemHighlight')], foreground=[('selected', 'SystemHighlightText')])
        self.conn = self.connect_db()
        if self.conn is None:
            self.root.destroy() # Beenden, wenn DB-Verbindung fehlschlägt
            return
        
        # ### GoBD-ÄNDERUNG ###: Start der Anwendung protokollieren
        log_audit_action(self.conn, 'ANWENDUNG_START', details="Mahnwesen-Tool gestartet.", user=self.current_user)

        self.create_widgets()
        self.create_menu()
        logging.info(f"MahnTool gestartet. User: {self.current_user}, Version: 2.0.0-gobd. Theme: {self.current_theme}, Doku: {self.document_base_path}, Mahnfristen: E={self.reminder_days} M1={self.mahnung1_days} M2={self.mahnung2_days} I={self.inkasso_days}")
        self.load_overdue_invoices()

    def save_setting(self, key, value):
        """Speichert eine einzelne Einstellung in der config.txt."""
        config_file_path = "config.txt"
        lines = []
        found = False
        try:
            # Datei lesen, falls vorhanden
            if os.path.exists(config_file_path):
                with open(config_file_path, "r", encoding='utf-8') as f:
                    lines = f.readlines()

            # Datei neu schreiben
            with open(config_file_path, "w", encoding='utf-8') as f:
                # Header schreiben, falls die Datei neu ist oder leer war
                if not lines or not lines[0].startswith("#"):
                     f.write("# Konfigurationsdatei für Mahnwesen\n")
                     f.write("# Ändern Sie die Werte nach Bedarf.\n# Das SMTP-Passwort wird hier nicht gespeichert.\n\n")

                for line in lines:
                    stripped_line = line.strip()
                    # Kommentare und leere Zeilen beibehalten
                    if not stripped_line or stripped_line.startswith('#'):
                        f.write(line)
                        continue
                    # Existierenden Schlüssel aktualisieren
                    if stripped_line.startswith(key + "=") or stripped_line.startswith(key + " ="):
                        # Passwort nicht schreiben
                        if key == 'smtp_password':
                           f.write(f"{key}=\n") # Schreibe leeren Wert für Passwort
                        else:
                           f.write(f"{key}={value}\n")
                        found = True
                    # Andere Schlüssel unverändert schreiben
                    else:
                        f.write(line)

                # Neuen Schlüssel hinzufügen, falls nicht gefunden
                if not found and key != 'smtp_password':
                    f.write(f"{key}={value}\n")

            logging.info(f"Einstellung '{key}' in {config_file_path} gespeichert.")

            # Wert auch im Speicher aktualisieren
            if hasattr(self, key):
                 # Typkonvertierung für spezifische Schlüssel
                 if key in ['reminder_days', 'mahnung1_days', 'mahnung2_days', 'inkasso_days', 'smtp_port']:
                     try:
                         setattr(self, key, int(str(value)))
                     except ValueError:
                         logging.warning(f"Ungültiger Integer-Wert beim Speichern für {key}: {value}")
                 elif key in ['default_vat_rate', 'mahnkosten_1', 'mahnkosten_2']:
                     setattr(self, key, parse_float(str(value), getattr(self, key, 0.0)))
                 elif key.startswith("company_"):
                      company_key = key.split("company_", 1)[1]
                      if company_key in self.company_details:
                          self.company_details[company_key] = str(value)
                 # Passwort nicht im Speicher aktualisieren (nur temporär in self.smtp_password)
                 elif key != 'smtp_password':
                     setattr(self, key, str(value))

        except Exception as e:
            logging.error(f"Fehler beim Speichern der Einstellung '{key}': {e}")
            messagebox.showerror("Fehler", f"Fehler beim Speichern der Einstellung '{key}': {e}")

    def create_menu(self):
        menubar = tk.Menu(self.root)
        settings_menu = tk.Menu(menubar, tearoff=0)
        settings_menu.add_command(label="Datenbankpfad ändern...", command=self.open_change_db_path_window)
        settings_menu.add_command(label="PDF Hintergrundbild ändern...", command=self.open_change_pdf_background_path_window)
        settings_menu.add_command(label="Basisordner Dokumente ändern...", command=self.open_change_document_base_path_window)
        settings_menu.add_command(label="Theme auswählen...", command=self.open_theme_selection_window)
        settings_menu.add_command(label="Mahnfristen anzeigen...", command=self.open_view_dunning_settings_window)
        settings_menu.add_command(label="Mahnkosten einstellen...", command=self.open_dunning_costs_window)
        settings_menu.add_command(label="PDF Textvorlagen bearbeiten...", command=self.open_edit_pdf_templates_window)
        settings_menu.add_command(label="Eigene Platzhalter verwalten...", command=self.open_manage_custom_placeholders_window)
        settings_menu.add_command(label="E-Mail (SMTP) konfigurieren...", command=self.open_configure_smtp_window)
        settings_menu.add_separator()
        settings_menu.add_command(label="Überfällige Rechnungen neu laden", command=self.load_overdue_invoices)
        settings_menu.add_separator()
        settings_menu.add_command(label="Beenden", command=self.on_closing)
        menubar.add_cascade(label="Einstellungen", menu=settings_menu)

        info_menu = tk.Menu(menubar, tearoff=0)
        info_menu.add_command(label="Über MahnTool", command=self.open_about_window)
        menubar.add_cascade(label="Info", menu=info_menu)

        self.root.config(menu=menubar)
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def on_closing(self):
        """Wird aufgerufen, wenn das Fenster geschlossen wird."""
        logging.info("MahnTool wird beendet...")
        if self.conn:
            try:
                # ### GoBD-ÄNDERUNG ###: Ende der Anwendung protokollieren
                log_audit_action(self.conn, 'ANWENDUNG_ENDE', details="Mahnwesen-Tool wurde geschlossen.", user=self.current_user)
                self.conn.close()
                logging.info("Datenbankverbindung geschlossen.")
            except Exception as e:
                logging.error(f"Fehler beim Schließen der Datenbankverbindung: {e}")
        _run_daten_schloss_shutdown()
        self.root.destroy()
        logging.info("Anwendungsfenster zerstört. Programmende.")
        sys.exit(0)

    def open_dunning_costs_window(self):
        """Öffnet ein Fenster zum Einstellen der Mahnkosten."""
        win = tk.Toplevel(self.root)
        win.title("Mahnkosten einstellen")
        win.transient(self.root)
        win.grab_set()
        win.resizable(False, False)

        frame = ttk.Frame(win, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Mahnkosten für die 1. Mahnung (€):").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        entry_cost1 = ttk.Entry(frame, width=15)
        entry_cost1.grid(row=0, column=1, sticky=tk.W, padx=5, pady=5)
        entry_cost1.insert(0, str(self.mahnkosten_1).replace('.', ','))

        ttk.Label(frame, text="Mahnkosten für die 2. Mahnung (€):").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        entry_cost2 = ttk.Entry(frame, width=15)
        entry_cost2.grid(row=1, column=1, sticky=tk.W, padx=5, pady=5)
        entry_cost2.insert(0, str(self.mahnkosten_2).replace('.', ','))

        def save_costs():
            try:
                cost1_val = parse_float(entry_cost1.get(), -1.0)
                cost2_val = parse_float(entry_cost2.get(), -1.0)

                if cost1_val < 0 or cost2_val < 0:
                    messagebox.showerror("Ungültige Eingabe", "Bitte geben Sie gültige, nicht-negative Zahlen für die Mahnkosten ein.", parent=win)
                    return

                self.save_setting('mahnkosten_1', str(cost1_val))
                self.save_setting('mahnkosten_2', str(cost2_val))
                
                self.mahnkosten_1 = cost1_val
                self.mahnkosten_2 = cost2_val

                messagebox.showinfo("Gespeichert", "Die Mahnkosten wurden erfolgreich gespeichert.", parent=win)
                logging.info(f"Mahnkosten aktualisiert: 1. Mahnung = {cost1_val} €, 2. Mahnung = {cost2_val} €")
                win.destroy()

            except Exception as e:
                messagebox.showerror("Fehler", f"Ein Fehler ist beim Speichern aufgetreten:\n{e}", parent=win)
                logging.exception("Fehler beim Speichern der Mahnkosten.")

        button_frame = ttk.Frame(win, padding=(0, 10, 0, 10))
        button_frame.pack(fill=tk.X)
        ttk.Button(button_frame, text="Speichern", command=save_costs).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Abbrechen", command=win.destroy).pack(side=tk.RIGHT, padx=5)

    def open_view_dunning_settings_window(self):
        dunning_window = tk.Toplevel(self.root)
        dunning_window.title("Aktuelle Mahnfristen (Tage überfällig)")
        dunning_window.transient(self.root)
        dunning_window.grab_set()
        dunning_window.resizable(False, False)

        frame = ttk.Frame(dunning_window, padding=10)
        frame.pack()

        labels_dunning_display = {
            "reminder_days": "Status 'Zur Erinnerung an' nach:",
            "mahnung1_days": "Status 'Zur Mahnung an' nach:",
            "mahnung2_days": "Status 'Zur Mahnung 2 an' nach:",
            "inkasso_days": "Status 'Bitte an Inkasso' nach:"
        }

        for i, (key, label_text) in enumerate(labels_dunning_display.items()):
            ttk.Label(frame, text=label_text, anchor='w').grid(row=i, column=0, sticky=tk.W, pady=3, padx=5)
            ttk.Label(frame, text=str(getattr(self, key, "N/A")), anchor='e').grid(row=i, column=1, sticky=tk.E, pady=3, padx=5)
            ttk.Label(frame, text="Tagen", anchor='w').grid(row=i, column=2, sticky=tk.W, pady=3, padx=5)

        ttk.Label(frame, text="\nDiese Einstellungen werden in der Kundenverwaltung konfiguriert.", justify=tk.LEFT, foreground="grey").grid(row=len(labels_dunning_display), column=0, columnspan=3, pady=10, padx=5, sticky=tk.W)

        button_frame = ttk.Frame(dunning_window)
        button_frame.pack(pady=10)
        ttk.Button(button_frame, text="Schließen", command=dunning_window.destroy).pack(padx=5)

    def open_configure_smtp_window(self):
        smtp_window = tk.Toplevel(self.root)
        smtp_window.title("E-Mail (SMTP) konfigurieren")
        smtp_window.transient(self.root)
        smtp_window.grab_set()
        smtp_window.resizable(False, False)

        frame = ttk.Frame(smtp_window, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="SMTP Server:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=3)
        entry_server = ttk.Entry(frame, width=40)
        entry_server.grid(row=0, column=1, columnspan=2, sticky=tk.EW, padx=5, pady=3)
        entry_server.insert(0, self.smtp_server)

        ttk.Label(frame, text="Port:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=3)
        entry_port = ttk.Entry(frame, width=10)
        entry_port.grid(row=1, column=1, sticky=tk.W, padx=5, pady=3)
        entry_port.insert(0, str(self.smtp_port))

        ttk.Label(frame, text="Verschlüsselung:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=3)
        combo_encryption = ttk.Combobox(frame, values=['None', 'SSL/TLS', 'STARTTLS'], width=10, state="readonly")
        combo_encryption.grid(row=2, column=1, sticky=tk.W, padx=5, pady=3)
        combo_encryption.set(self.smtp_encryption if self.smtp_encryption in combo_encryption['values'] else 'STARTTLS')

        ttk.Label(frame, text="Benutzername:").grid(row=3, column=0, sticky=tk.W, padx=5, pady=3)
        entry_user = ttk.Entry(frame, width=40)
        entry_user.grid(row=3, column=1, columnspan=2, sticky=tk.EW, padx=5, pady=3)
        entry_user.insert(0, self.smtp_user)

        ttk.Label(frame, text="Passwort:").grid(row=4, column=0, sticky=tk.W, padx=5, pady=3)
        smtp_password_var = tk.StringVar(smtp_window)
        entry_password = ttk.Entry(frame, width=40, textvariable=smtp_password_var, show='*')
        entry_password.grid(row=4, column=1, columnspan=2, sticky=tk.EW, padx=5, pady=3)

        ttk.Label(frame, text="Hinweis: Passwort wird nur für die aktuelle Sitzung gespeichert.", foreground="grey").grid(row=5, column=0, columnspan=3, sticky=tk.W, padx=5, pady=(10,3))

        def save_smtp_settings():
            server = entry_server.get().strip()
            port_str = entry_port.get().strip()
            user = entry_user.get().strip()
            password = smtp_password_var.get()
            enc = combo_encryption.get()

            try:
                port = int(port_str)
                if not (0 < port < 65536):
                    raise ValueError("Port out of range")
            except ValueError:
                messagebox.showerror("Ungültiger Port", "Bitte geben Sie eine gültige Portnummer (1-65535) ein.", parent=smtp_window)
                return

            self.save_setting('smtp_server', server)
            self.save_setting('smtp_port', str(port))
            self.save_setting('smtp_user', user)
            self.save_setting('smtp_encryption', enc)

            self.smtp_password = password
            messagebox.showinfo("Erfolg", "SMTP-Einstellungen gespeichert (Passwort nur für diese Sitzung).", parent=smtp_window)
            logging.info(f"SMTP-Konfiguration aktualisiert (Server: {server}, Port: {port}, User: {user}, Verschlüsselung: {enc}). Passwort nicht persistent gespeichert.")
            smtp_window.destroy()

        button_frame = ttk.Frame(smtp_window)
        button_frame.pack(pady=10)
        ttk.Button(button_frame, text="Speichern", command=save_smtp_settings).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Abbrechen", command=smtp_window.destroy).pack(side=tk.LEFT, padx=5)

    def open_about_window(self):
        about_window = tk.Toplevel(self.root)
        about_window.title("Über InnoWiseIT")
        about_window.resizable(False, False)
        about_window.transient(self.root)
        about_window.grab_set()
        version_info = "Version: 2.0.0 (GoBD Compliant)" # Angepasste Version
        manufacturer_info = "Hersteller: innowise IT Manuel Person"
        support_contact = "Supportkontakt: manuel.person@outlook.de"
        copyright_info = "© 2025 Alle Rechte vorbehalten."

        labels_text = [
            "Mahnwesen",
            version_info,
            manufacturer_info,
            support_contact,
            copyright_info
        ]

        for i, text in enumerate(labels_text):
            is_title = (i == 0)
            font_spec = ("Arial", 12, "bold") if is_title else None
            pady_spec = 10 if is_title else 5
            ttk.Label(about_window, text=text, font=font_spec).pack(padx=20, pady=pady_spec)

        ttk.Button(about_window, text="Schließen", command=about_window.destroy).pack(pady=15)

    def open_theme_selection_window(self):
        theme_window = tk.Toplevel(self.root)
        theme_window.title("Theme auswählen")
        theme_window.transient(self.root)
        theme_window.grab_set()
        theme_window.resizable(False, False)

        ttk.Label(theme_window, text="Wählen Sie ein Theme:").pack(padx=10, pady=10)

        theme_var = tk.StringVar(theme_window, value=self.current_theme)
        theme_combobox = ttk.Combobox(theme_window, textvariable=theme_var, values=self.available_themes, state="readonly")
        theme_combobox.pack(padx=10, pady=5)

        def apply_selected_theme():
            selected_theme = theme_var.get()
            try:
                self.root.set_theme(selected_theme)
                self.current_theme = selected_theme
                self.save_setting("theme", selected_theme)
                messagebox.showinfo("Info", f"Theme '{selected_theme}' erfolgreich geändert und gespeichert.", parent=theme_window)
                theme_window.destroy()
            except tk.TclError as e:
                messagebox.showerror("Fehler", f"Das ausgewählte Theme '{selected_theme}' konnte nicht geladen werden:\n{e}", parent=theme_window)
                logging.error(f"Fehler beim Anwenden des Themes '{selected_theme}': {e}")
            except Exception as e:
                 messagebox.showerror("Fehler", f"Ein unerwarteter Fehler ist beim Ändern des Themes aufgetreten:\n{e}", parent=theme_window)
                 logging.exception(f"Unerwarteter Fehler beim Ändern des Themes auf '{selected_theme}':")

        button_frame = ttk.Frame(theme_window)
        button_frame.pack(pady=15)
        ttk.Button(button_frame, text="Anwenden & Speichern", command=apply_selected_theme).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Abbrechen", command=theme_window.destroy).pack(side=tk.LEFT, padx=5)

    def open_change_pdf_background_path_window(self):
        win = tk.Toplevel(self.root)
        win.title("PDF Hintergrundbild ändern")
        win.transient(self.root)
        win.grab_set()
        win.resizable(False, False)

        ttk.Label(win, text="Pfad zum Hintergrundbild (für A4 PDFs):").pack(padx=10, pady=(10, 5))
        entry_frame = ttk.Frame(win)
        entry_frame.pack(padx=10, pady=5, fill=tk.X)
        entry = ttk.Entry(entry_frame, width=50)
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        entry.insert(0, self.pdf_background_path)

        def browse():
            f_path = filedialog.askopenfilename(parent=win, title="PDF Hintergrundbild auswählen", filetypes=[("Bilder", "*.png;*.jpg;*.jpeg;*.gif"), ("Alle Dateien", "*.*")])
            if f_path:
                entry.delete(0, tk.END)
                entry.insert(0, f_path)

        ttk.Button(entry_frame, text="...", width=3, command=browse).pack(side=tk.LEFT, padx=(5,0))

        def save():
            new_path = entry.get().strip()
            if new_path and not os.path.exists(new_path):
                if not messagebox.askyesno("Warnung", f"Die Datei '{os.path.basename(new_path)}' wurde nicht gefunden.\nMöchten Sie den Pfad trotzdem speichern?", parent=win, icon=messagebox.WARNING):
                    return
            elif not new_path:
                if not messagebox.askyesno("Bestätigen", "Möchten Sie wirklich kein Hintergrundbild verwenden (Pfad leeren)?", parent=win, icon=messagebox.QUESTION):
                    return

            self.save_setting("pdf_background_path", new_path)
            self.pdf_background_path = new_path
            messagebox.showinfo("Erfolg", "Pfad für PDF-Hintergrundbild wurde gespeichert.", parent=win)
            win.destroy()

        button_frame = ttk.Frame(win)
        button_frame.pack(pady=15)
        ttk.Button(button_frame, text="Speichern", command=save).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Abbrechen", command=win.destroy).pack(side=tk.LEFT, padx=5)

    def open_change_document_base_path_window(self):
        win = tk.Toplevel(self.root)
        win.title("Basisordner für Kundendokumente ändern")
        win.transient(self.root)
        win.grab_set()
        win.resizable(False, False)

        ttk.Label(win, text="Neuer Basisordner für Kundendokumente:\n(Der Unterordner 'Kundendokumente' wird automatisch darin verwaltet)").pack(padx=10, pady=(10, 5))
        entry_frame = ttk.Frame(win)
        entry_frame.pack(padx=10, pady=5, fill=tk.X)
        entry = ttk.Entry(entry_frame, width=50)
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        entry.insert(0, self.document_base_path)

        def browse():
            initial_dir = os.path.dirname(self.document_base_path) if self.document_base_path else os.path.expanduser("~")
            f_path = filedialog.askdirectory(parent=win, title="Basisordner auswählen", initialdir=initial_dir)
            if f_path:
                entry.delete(0, tk.END)
                entry.insert(0, f_path)

        ttk.Button(entry_frame, text="...", width=3, command=browse).pack(side=tk.LEFT, padx=(5,0))

        def save():
            new_path = entry.get().strip()
            if not new_path:
                messagebox.showwarning("Warnung", "Der Pfad darf nicht leer sein.", parent=win)
                return

            if not os.path.isdir(new_path):
                messagebox.showerror("Fehler", f"Der angegebene Pfad ist kein gültiges Verzeichnis:\n{new_path}", parent=win)
                logging.error(f"Ausgewählter Dokumenten-Basisordner '{new_path}' ist kein Verzeichnis.")
                return
            if not os.access(new_path, os.W_OK):
                 messagebox.showerror("Fehler", f"Keine Schreibberechtigung für das Verzeichnis:\n{new_path}", parent=win)
                 logging.error(f"Keine Schreibberechtigung für Dokumenten-Basisordner '{new_path}'.")
                 return

            self.save_setting("document_base_path", new_path)
            self.document_base_path = new_path
            messagebox.showinfo("Erfolg", f"Der Basisordner für Dokumente wurde erfolgreich auf\n'{new_path}'\ngesetzt.", parent=win)
            win.destroy()

        button_frame = ttk.Frame(win)
        button_frame.pack(pady=15)
        ttk.Button(button_frame, text="Speichern", command=save).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Abbrechen", command=win.destroy).pack(side=tk.LEFT, padx=5)

    def connect_db(self):
        conn = connect_db_static(self.db_path)
        if conn is None:
            logging.error(f"Kritischer Fehler: Verbindung zur Datenbank '{self.db_path}' fehlgeschlagen.")
        else:
            logging.info(f"Erfolgreich mit Datenbank '{self.db_path}' verbunden.")
        return conn

    def open_change_db_path_window(self):
        win = tk.Toplevel(self.root)
        win.title("Datenbankpfad ändern")
        win.transient(self.root)
        win.grab_set()
        win.resizable(False, False)

        ttk.Label(win, text="Neuer Pfad zur Datenbankdatei (.db):").pack(padx=10, pady=(10, 5))
        entry_frame = ttk.Frame(win)
        entry_frame.pack(padx=10, pady=5, fill=tk.X)
        entry = ttk.Entry(entry_frame, width=50)
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        entry.insert(0, self.db_path)

        def browse():
            initial_dir = os.path.dirname(self.db_path) if self.db_path else os.getcwd()
            new_p = filedialog.asksaveasfilename(
                parent=win,
                initialdir=initial_dir,
                initialfile=os.path.basename(self.db_path) if self.db_path else "unternehmen_gobd.db",
                defaultextension=".db",
                filetypes=[("SQLite Datenbanken", "*.db"), ("Alle Dateien", "*.*")]
            )
            if new_p:
                entry.delete(0, tk.END)
                entry.insert(0, new_p)

        ttk.Button(entry_frame, text="...", width=3, command=browse).pack(side=tk.LEFT, padx=(5,0))

        def save():
            new_db_path = entry.get().strip()
            if not new_db_path:
                messagebox.showwarning("Warnung", "Der Datenbankpfad darf nicht leer sein.", parent=win)
                return
            if not new_db_path.lower().endswith(".db"):
                messagebox.showwarning("Warnung", "Bitte geben Sie einen gültigen Pfad zu einer .db-Datei an.", parent=win)
                return

            if os.path.abspath(new_db_path) == os.path.abspath(self.db_path):
                messagebox.showinfo("Info", "Der ausgewählte Pfad ist bereits der aktuelle Datenbankpfad.", parent=win)
                win.destroy()
                return

            try:
                if self.conn:
                    # ### GoBD-ÄNDERUNG ###: DB-Wechsel protokollieren
                    log_audit_action(self.conn, 'DB_WECHSEL_START', details=f"Versuch, DB von '{self.db_path}' auf '{new_db_path}' zu wechseln.", user=self.current_user)
                    self.conn.close()
                    logging.info(f"Bestehende DB-Verbindung zu '{self.db_path}' geschlossen.")
                    self.conn = None

                temp_conn = connect_db_static(new_db_path)

                if temp_conn:
                    logging.info(f"Testverbindung und Schema-Check für '{new_db_path}' erfolgreich.")
                    # ### GoBD-ÄNDERUNG ###: Erfolgreichen DB-Wechsel protokollieren
                    log_audit_action(temp_conn, 'DB_WECHSEL_ERFOLG', details=f"DB erfolgreich auf '{new_db_path}' gewechselt.", user=self.current_user)
                    temp_conn.close()
                    
                    self.save_setting("db_path", new_db_path)
                    self.db_path = new_db_path
                    self.conn = self.connect_db()

                    if self.conn:
                        self.load_overdue_invoices()
                        messagebox.showinfo("Erfolg", f"Datenbankpfad erfolgreich geändert auf:\n{self.db_path}\n\nDaten wurden neu geladen.", parent=win)
                        logging.info(f"Datenbankpfad erfolgreich auf '{self.db_path}' geändert.")
                        win.destroy()
                    else:
                        messagebox.showerror("Fehler", "Verbindung zur neuen Datenbank konnte nach erfolgreichem Test nicht hergestellt werden.", parent=win)
                        self.root.quit()
                else:
                    logging.error(f"Fehler beim Testen der neuen Datenbank '{new_db_path}'. Pfad wird nicht geändert.")
                    self.conn = self.connect_db() # Zurück zur alten DB verbinden
                    if self.conn:
                        log_audit_action(self.conn, 'DB_WECHSEL_FEHLER', details=f"Wechsel zu '{new_db_path}' fehlgeschlagen. Zurück zu '{self.db_path}'.", user=self.current_user)
                    if not self.conn:
                         messagebox.showerror("Kritischer Fehler", "Konnte auch die ursprüngliche Datenbank nicht mehr öffnen. Anwendung wird beendet.", parent=win)
                         self.root.quit()

            except Exception as e:
                messagebox.showerror("Fehler", f"Ein unerwarteter Fehler ist beim Wechsel der Datenbank aufgetreten:\n{e}", parent=win)
                logging.exception(f"Unerwarteter Fehler beim Wechsel der Datenbank zu '{new_db_path}':")
                self.conn = self.connect_db()
                if self.conn:
                    log_audit_action(self.conn, 'DB_WECHSEL_FEHLER', details=f"Wechsel zu '{new_db_path}' mit Exception fehlgeschlagen: {e}", user=self.current_user)
                if not self.conn:
                    messagebox.showerror("Kritischer Fehler", "Konnte auch die ursprüngliche Datenbank nicht mehr öffnen. Anwendung wird beendet.", parent=win)
                    self.root.quit()

        button_frame = ttk.Frame(win)
        button_frame.pack(pady=15)
        ttk.Button(button_frame, text="Speichern & Neu verbinden", command=save).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Abbrechen", command=win.destroy).pack(side=tk.LEFT, padx=5)

    def create_customer_document_folder(self, customer_id, zifferncode):
        if not self.document_base_path:
            logging.warning(f"Basisordner für Dokumente nicht konfiguriert. Ordner für Kunde ID {customer_id} (Code {zifferncode}) kann nicht erstellt werden.")
            return None
        if not zifferncode:
             logging.warning(f"Kein Zifferncode für Kunde ID {customer_id} vorhanden. Ordner kann nicht erstellt werden.")
             return None

        safe_foldername = str(zifferncode).strip().replace(os.path.sep, '_').replace('/', '_').replace('\\', '_')
        if not safe_foldername:
             logging.warning(f"Ungültiger oder leerer Zifferncode '{zifferncode}' für Kunde ID {customer_id}. Ordner kann nicht erstellt werden.")
             return None

        customer_folder_path = os.path.join(self.document_base_path, "Kundendokumente", safe_foldername)

        try:
            os.makedirs(customer_folder_path, exist_ok=True)
            logging.info(f"Kundenordner für Kunde ID {customer_id} (Code {zifferncode}) erstellt oder existiert bereits: {customer_folder_path}")
            return customer_folder_path
        except OSError as e:
            logging.error(f"Fehler beim Erstellen des Kundenordners für ID {customer_id} (Code {zifferncode}) unter '{customer_folder_path}': {e}")
            messagebox.showerror("Ordner Fehler", f"Konnte den Ordner für Kunde {zifferncode} nicht erstellen:\n{customer_folder_path}\n\nFehler: {e}", parent=self.root)
            return None
        except Exception as e:
             logging.exception(f"Unerwarteter Fehler beim Erstellen des Kundenordners ID {customer_id} (Code {zifferncode}) unter '{customer_folder_path}':")
             messagebox.showerror("Ordner Fehler", f"Unerwarteter Fehler beim Erstellen des Kundenordners {zifferncode}:\n{e}", parent=self.root)
             return None

    def create_widgets(self):
        logo_frame = ttk.Frame(self.root)
        logo_frame.pack(side=tk.TOP, anchor=tk.NW, padx=10, pady=10)
        try:
            self.logo_image = tk.PhotoImage(file="logo.png")
            ttk.Label(logo_frame, image=self.logo_image).pack()
            logging.info("Logo 'logo.png' erfolgreich geladen.")
        except tk.TclError:
            logging.warning("Logo-Datei 'logo.png' nicht gefunden oder ungültiges Format.")
            ttk.Label(logo_frame, text="[Logo nicht gefunden]", foreground="grey").pack()
        except Exception as e:
            logging.error(f"Fehler beim Laden des Logos 'logo.png': {e}")
            ttk.Label(logo_frame, text="[Logo Fehler]", foreground="red").pack()

        ttk.Label(self.root, text="Mahnwesen", font=("Arial", 20, "bold")).pack(pady=5)

        main_fr = ttk.Frame(self.root)
        main_fr.pack(pady=10, padx=10, fill=tk.BOTH, expand=True)

        search_fr = ttk.Frame(main_fr)
        search_fr.pack(pady=5, fill=tk.X)
        ttk.Label(search_fr, text="Filter (Rechnungsnr, Kunde, Status):").pack(side=tk.LEFT, padx=(0, 5))
        self.entry_filter = ttk.Entry(search_fr, width=40)
        self.entry_filter.pack(side=tk.LEFT, padx=5, expand=True, fill=tk.X)
        self.entry_filter.bind("<Return>", lambda event: self.apply_filter())
        ttk.Button(search_fr, text="Filtern", command=self.apply_filter).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(search_fr, text="Alle anzeigen", command=lambda: (self.entry_filter.delete(0, tk.END), self.apply_filter())).pack(side=tk.LEFT)

        tree_fr = ttk.Frame(main_fr)
        tree_fr.pack(pady=10, fill=tk.BOTH, expand=True)

        cols = ("Re ID", "Kunde ID", "KdNr", "Kunde", "Rechnungsnr", "Datum", "Fällig", "Überfällig (Tage)", "Betrag Brutto", "Status")
        self.tree_overdue = ttk.Treeview(tree_fr, columns=cols, show="headings", selectmode='extended')

        for col in cols:
            width = 100
            anchor = tk.W
            stretch = tk.YES
            is_numeric_sort = False
            is_date_sort = False
            is_currency_sort = False

            if col in ["Re ID", "Kunde ID"]: width, anchor, stretch = 65, tk.E, tk.NO; is_numeric_sort = True
            elif col == "KdNr": width, anchor, stretch = 60, tk.E, tk.NO; is_numeric_sort = True
            elif col == "Kunde": width, stretch = 180, tk.YES
            elif col == "Rechnungsnr": width, stretch = 90, tk.YES
            elif col in ["Datum", "Fällig"]: width, stretch = 85, tk.NO; is_date_sort = True
            elif col == "Überfällig (Tage)": width, anchor, stretch = 105, tk.E, tk.NO; is_numeric_sort = True
            elif col == "Betrag Brutto": width, anchor, stretch = 100, tk.E, tk.NO; is_currency_sort = True
            elif col == "Status": width, stretch = 150, tk.YES

            self.tree_overdue.heading(col, text=col, command=lambda _c=col, num=is_numeric_sort, date=is_date_sort, curr=is_currency_sort: self.sort_treeview_column_mahn(_c, False, num, date, curr))
            self.tree_overdue.column(col, width=width, anchor=anchor, stretch=stretch)

        self.tree_overdue.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrl = ttk.Scrollbar(tree_fr, orient="vertical", command=self.tree_overdue.yview)
        self.tree_overdue.configure(yscrollcommand=scrl.set)
        scrl.pack(side="right", fill="y")

        action_fr = ttk.Frame(self.root)
        action_fr.pack(pady=10, padx=10, fill=tk.X)

        self.btn_generate_letter = ttk.Button(action_fr, text="Schreiben generieren", command=self.generate_selected_letters, state=tk.DISABLED)
        self.btn_generate_letter.pack(side=tk.LEFT, padx=5)
        self.btn_print_letter = ttk.Button(action_fr, text="Schreiben drucken (PDF öffnen)", command=self.print_selected_letters, state=tk.DISABLED)
        self.btn_print_letter.pack(side=tk.LEFT, padx=5)
        self.btn_email_letter = ttk.Button(action_fr, text="Schreiben per E-Mail senden", command=self.email_selected_letters, state=tk.DISABLED)
        self.btn_email_letter.pack(side=tk.LEFT, padx=5)

        self.status_label = ttk.Label(self.root, text="Bereit.", relief=tk.SUNKEN, anchor=tk.W)
        self.status_label.pack(side=tk.BOTTOM, fill=tk.X, padx=5, pady=2)

        self.tree_overdue.bind("<<TreeviewSelect>>", self.on_invoice_select)
        self.tree_overdue.bind("<ButtonRelease-1>", self.on_invoice_select)

    def sort_treeview_column_mahn(self, col, reverse, is_numeric, is_date, is_currency):
        try:
            data = [(self.tree_overdue.set(k, col), k) for k in self.tree_overdue.get_children('')]

            def sort_key(item):
                value_str = item[0]
                if value_str is None: return -float('inf') if reverse else float('inf')

                if is_numeric:
                    try: return int(value_str)
                    except (ValueError, TypeError): return -float('inf') if reverse else float('inf')
                elif is_date:
                    try: return datetime.strptime(value_str, "%d.%m.%Y")
                    except (ValueError, TypeError): return datetime.min if not reverse else datetime.max
                elif is_currency:
                    cleaned_value = value_str.replace('€', '').replace('.', '').replace(',', '.').strip()
                    try: return float(cleaned_value)
                    except (ValueError, TypeError): return -float('inf') if reverse else float('inf')
                else:
                    return str(value_str).lower()

            data.sort(key=sort_key, reverse=reverse)

            for i, (val, k) in enumerate(data):
                self.tree_overdue.move(k, '', i)

            self.tree_overdue.heading(col, command=lambda _c=col, num=is_numeric, date=is_date, curr=is_currency: self.sort_treeview_column_mahn(_c, not reverse, num, date, curr))

        except Exception as e:
            logging.error(f"Fehler beim Sortieren der Spalte '{col}': {e}")
            messagebox.showerror("Sortierfehler", f"Die Spalte '{col}' konnte nicht sortiert werden:\n{e}", parent=self.root)

    def on_invoice_select(self, event=None):
        selected_items = self.tree_overdue.selection()
        num_selected = len(selected_items)

        if num_selected > 0:
            self.btn_generate_letter.config(state=tk.NORMAL)
            self.btn_print_letter.config(state=tk.NORMAL)
            if self._is_smtp_configured():
                self.btn_email_letter.config(state=tk.NORMAL)
            else:
                self.btn_email_letter.config(state=tk.DISABLED)
            status_text = f"{num_selected} Rechnung{'en' if num_selected != 1 else ''} ausgewählt."
            self.status_label.config(text=status_text)
        else:
            self.btn_generate_letter.config(state=tk.DISABLED)
            self.btn_print_letter.config(state=tk.DISABLED)
            self.btn_email_letter.config(state=tk.DISABLED)
            self.status_label.config(text="Keine Rechnung ausgewählt.")

    def load_overdue_invoices(self, filter_text=None):
        if not self.conn:
            logging.error("Keine Datenbankverbindung vorhanden. Ladevorgang abgebrochen.")
            self.status_label.config(text="Fehler: Keine Datenbankverbindung.", foreground="red")
            for row in self.tree_overdue.get_children():
                self.tree_overdue.delete(row)
            return

        for row in self.tree_overdue.get_children():
            self.tree_overdue.delete(row)

        self.status_label.config(text="Lade überfällige Rechnungen...", foreground="blue")
        self.root.update_idletasks()

        cursor = self.conn.cursor()
        today = datetime.now().date()
        loaded_count = 0
        error_count = 0

        try:
            valid_statuses = ('Offen', 'Steht zur Erinnerung an', 'Steht zur Mahnung an', 'Steht zur Mahnung 2 an', 'Bitte an Inkasso weiterleiten')
            # ### GoBD-ÄNDERUNG ###: Nur finalisierte Rechnungen (`is_finalized = 1`) berücksichtigen.
            sql = """
                SELECT
                    r.id, k.id, k.zifferncode, k.vorname, k.name, k.titel_firma,
                    r.rechnungsnummer, r.rechnungsdatum, r.faelligkeitsdatum, r.summe_brutto, r.status
                FROM rechnungen r
                JOIN kunden k ON r.kunde_id = k.id
                WHERE r.status IN ({seq}) AND r.faelligkeitsdatum IS NOT NULL AND r.faelligkeitsdatum != ''
                AND r.is_finalized = 1
            """.format(seq=','.join(['?']*len(valid_statuses)))
            params = list(valid_statuses)

            if filter_text:
                like_pattern = f"%{filter_text}%"
                sql += """
                    AND (
                        r.rechnungsnummer LIKE ? OR
                        CAST(k.zifferncode AS TEXT) LIKE ? OR
                        k.name LIKE ? OR
                        k.vorname LIKE ? OR
                        k.titel_firma LIKE ? OR
                        r.status LIKE ?
                    )
                """
                params.extend([like_pattern] * 6)

            sql += " ORDER BY r.faelligkeitsdatum ASC, k.zifferncode ASC, r.rechnungsnummer ASC"
            cursor.execute(sql, params)

            for row_data in cursor.fetchall():
                (re_id, kunde_id, kd_nr, vorname, nachname, firma,
                 re_nr, re_dat_str, faellig_dat_str, re_brutto_raw, re_status) = row_data

                k_name_parts = [part for part in [vorname, nachname] if part]
                if firma: k_name_parts.append(f"({firma})")
                k_display_name = " ".join(k_name_parts)

                days_overdue_display = "N/A"
                try:
                    if faellig_dat_str:
                        due_date = datetime.strptime(faellig_dat_str, "%d.%m.%Y").date()
                        if due_date < today:
                            days_overdue = (today - due_date).days
                            days_overdue_display = str(days_overdue)
                        else:
                            days_overdue_display = "0"
                except (ValueError, TypeError) as e:
                    logging.warning(f"Ungültiges Fälligkeitsdatum '{faellig_dat_str}' für Rechnung ID {re_id}: {e}")
                    days_overdue_display = "Ungültig"
                    error_count += 1

                brutto_display_str = ""
                try:
                    if re_brutto_raw is not None:
                         brutto_display_str = f"{re_brutto_raw:,.2f} €".replace('.', '#').replace(',', '.').replace('#', ',')
                except (ValueError, TypeError) as e:
                    logging.warning(f"Ungültiger Bruttobetrag '{re_brutto_raw}' für Rechnung ID {re_id}: {e}")
                    brutto_display_str = "Fehler"
                    error_count += 1

                values_tuple = (
                    re_id or "", kunde_id or "", kd_nr or "", k_display_name or "", re_nr or "",
                    re_dat_str or "", faellig_dat_str or "", days_overdue_display,
                    brutto_display_str, re_status or ""
                )
                self.tree_overdue.insert("", "end", values=values_tuple, iid=re_id)
                loaded_count += 1

            status_msg = f"{loaded_count} überfällige Rechnung{'en' if loaded_count != 1 else ''} geladen."
            if filter_text: status_msg += f" (Filter: '{filter_text}')"
            if error_count > 0:
                 status_msg += f" ({error_count} Fehler bei Datums-/Betragsberechnung)"
                 self.status_label.config(text=status_msg, foreground="orange")
            else:
                self.status_label.config(text=status_msg, foreground="black")

            logging.info(f"{loaded_count} überfällige Rechnungen geladen (Filter: '{filter_text or 'Kein'}', Fehler: {error_count}).")

        except sqlite3.Error as e:
            messagebox.showerror("Datenbankfehler", f"Fehler beim Laden der überfälligen Rechnungen aus der Datenbank:\n{e}", parent=self.root)
            logging.error(f"SQLite-Fehler beim Laden überfälliger Rechnungen: {e}")
            self.status_label.config(text="Fehler beim Laden (Datenbank).", foreground="red")
        except Exception as e:
            messagebox.showerror("Fehler", f"Ein unerwarteter Fehler ist beim Laden der überfälligen Rechnungen aufgetreten:\n{e}", parent=self.root)
            logging.exception("Allgemeiner Fehler beim Laden überfälliger Rechnungen:")
            self.status_label.config(text="Fehler beim Laden (Allgemein).", foreground="red")

        self.on_invoice_select()

    def apply_filter(self):
        filter_value = self.entry_filter.get().strip()
        self.load_overdue_invoices(filter_value)

    def generate_selected_letters(self):
        selected_items = self.tree_overdue.selection()
        if not selected_items:
            messagebox.showwarning("Auswahl fehlt", "Bitte wählen Sie mindestens eine Rechnung aus.", parent=self.root)
            return

        generated_count = 0
        error_list = []
        total_items = len(selected_items)
        self.status_label.config(text=f"Generiere {total_items} Schreiben...", foreground="blue")
        self.root.update_idletasks()

        for item_iid in selected_items:
            try:
                re_id = int(item_iid)
                pdf_path = self._generate_and_save_letter(re_id, update_bemerkung=True)
                if pdf_path:
                    generated_count += 1
                    logging.info(f"Schreiben für Rechnung ID {re_id} erfolgreich generiert: {pdf_path}")
                else:
                    error_list.append(f"Rng ID {re_id}: Fehler bei PDF-Erstellung (siehe Log).")
            except (ValueError, IndexError, KeyError) as e:
                 error_list.append(f"Interner Fehler bei Item {item_iid}: {e}")
                 logging.error(f"Fehler beim Extrahieren der Rechnungs-ID aus Treeview Item {item_iid}: {e}")
            except Exception as e:
                 error_list.append(f"Unerwarteter Fehler bei Rng (ID {item_iid}): {e}")
                 logging.exception(f"Unerwarteter Fehler bei der Generierung für Item {item_iid}:")

        if not error_list:
            messagebox.showinfo("Erfolg", f"{generated_count} Schreiben erfolgreich generiert und gespeichert.", parent=self.root)
            status_text = f"{generated_count} Schreiben generiert."
        else:
            error_details = "\n - ".join(error_list)
            messagebox.showerror("Fehler bei Generierung", f"{generated_count} von {total_items} Schreiben generiert.\n\nFehler bei folgenden Einträgen:\n - {error_details}", parent=self.root)
            status_text = f"{generated_count}/{total_items} Schreiben generiert (mit Fehlern)."
        self.status_label.config(text=status_text, foreground="black" if not error_list else "orange")

    def print_selected_letters(self):
        selected_items = self.tree_overdue.selection()
        if not selected_items:
            messagebox.showwarning("Auswahl fehlt", "Bitte wählen Sie mindestens eine Rechnung aus.", parent=self.root)
            return

        opened_count = 0
        error_list = []
        total_items = len(selected_items)
        self.status_label.config(text=f"Öffne {total_items} Schreiben...", foreground="blue")
        self.root.update_idletasks()

        for item_iid in selected_items:
            try:
                re_id = int(item_iid)
                # Erstellt das PDF, aber aktualisiert die Bemerkung nicht (reine Vorschau)
                pdf_path_generated = self._generate_and_save_letter(re_id, update_bemerkung=False)

                if pdf_path_generated and os.path.exists(pdf_path_generated):
                    if self._open_file(pdf_path_generated):
                        opened_count += 1
                        logging.info(f"Schreiben für Rechnung ID {re_id} erfolgreich geöffnet: {pdf_path_generated}")
                        # ### GoBD-ÄNDERUNG ###: Vorschau/Druck protokollieren
                        log_audit_action(self.conn, 'MAHNSCHREIBEN_VORSCHAU', re_id,
                                         f"Dokument '{os.path.basename(pdf_path_generated)}' zur Ansicht/Druck geöffnet.",
                                         user=self.current_user)
                    else:
                        error_list.append(f"Rng ID {re_id}: Fehler beim Öffnen der Datei '{os.path.basename(pdf_path_generated)}'.")
                elif pdf_path_generated:
                     error_list.append(f"Rng ID {re_id}: Generierte PDF nicht gefunden '{os.path.basename(pdf_path_generated)}'.")
                     logging.error(f"Generierte PDF für Rng ID {re_id} nicht gefunden: {pdf_path_generated}")
                else:
                     error_list.append(f"Rng ID {re_id}: Fehler bei PDF-Erstellung (siehe Log).")

            except (ValueError, IndexError, KeyError) as e:
                 error_list.append(f"Interner Fehler bei Item {item_iid}: {e}")
                 logging.error(f"Fehler beim Extrahieren der ID aus Item {item_iid} für Drucken/Öffnen: {e}")
            except Exception as e:
                 error_list.append(f"Unerwarteter Fehler beim Öffnen/Drucken für Item {item_iid}:")

        if not error_list:
            messagebox.showinfo("Erfolg", f"{opened_count} Schreiben erfolgreich zum Drucken geöffnet.", parent=self.root)
            status_text = f"{opened_count} Schreiben geöffnet."
        else:
            error_details = "\n - ".join(error_list)
            messagebox.showerror("Fehler beim Öffnen", f"{opened_count} von {total_items} Schreiben geöffnet.\n\nFehler:\n - {error_details}", parent=self.root)
            status_text = f"{opened_count}/{total_items} Schreiben geöffnet (mit Fehlern)."
        self.status_label.config(text=status_text, foreground="black" if not error_list else "orange")

    def email_selected_letters(self):
        selected_items = self.tree_overdue.selection()
        if not selected_items:
            messagebox.showwarning("Auswahl fehlt", "Bitte wählen Sie eine Rechnung für den E-Mail-Versand aus.", parent=self.root)
            return

        if not self._is_smtp_configured():
            messagebox.showerror("Konfigurationsfehler", "SMTP-Einstellungen sind unvollständig.", parent=self.root)
            return

        if len(selected_items) > 1:
             messagebox.showinfo("Hinweis", "Bitte wählen Sie nur eine Rechnung für den E-Mail-Versand aus.", parent=self.root)
             return

        item_iid = selected_items[0]
        try:
            re_id = int(item_iid)
            inv_data, cust_data, _ = self._get_invoice_and_customer_data(re_id)

            if not inv_data or not cust_data:
                messagebox.showerror("Datenfehler", f"Daten für Rechnung ID {re_id} konnten nicht geladen werden.", parent=self.root)
                return

            cust_email = cust_data.get('email', "")
            if not cust_email:
                messagebox.showwarning("E-Mail fehlt", f"Für Kunde '{cust_data.get('name', 'N/A')}' (KdNr: {cust_data.get('zifferncode', 'N/A')}) ist keine E-Mail hinterlegt.", parent=self.root)
                return
            
            # PDF wird nur für den Versand erstellt, ohne DB-Änderung. Die Änderung erfolgt erst nach erfolgreichem Versand.
            pdf_path = self._generate_and_save_letter(re_id, update_bemerkung=False)

            if pdf_path and os.path.exists(pdf_path):
                re_nr = inv_data.get('rechnungsnummer', 'N/A')
                re_status = inv_data.get('status', 'Rechnung')
                template_key = PDF_TEMPLATE_KEY_MAP.get(re_status)
                subject_type = "Schreiben zu"
                if template_key and template_key in self.pdf_letter_templates:
                    subject_type = self.pdf_letter_templates[template_key].get("display_name", "Schreiben zu")
                default_subject = f"{subject_type} Rechnung Nr. {re_nr} von {self.company_details.get('name', 'Ihrer Firma')}"

                self.open_email_compose_window(
                    parent=self.root, recipient_email=cust_email, attachment_path=pdf_path,
                    attachment_filename=os.path.basename(pdf_path), invoice_id=re_id,
                    invoice_status=re_status, default_subject=default_subject
                )
            elif pdf_path:
                 messagebox.showerror("Fehler", f"Generierte PDF '{os.path.basename(pdf_path)}' nicht gefunden.", parent=self.root)
                 logging.error(f"Generierte PDF für E-Mail (Rng ID {re_id}) nicht gefunden: {pdf_path}")
            else:
                 messagebox.showerror("Fehler", f"PDF für Rechnung ID {re_id} nicht erstellt. E-Mail kann nicht gesendet werden.", parent=self.root)

        except (ValueError, IndexError, KeyError) as e:
             messagebox.showerror("Fehler", f"Interner Fehler bei Daten für Item {item_iid}: {e}", parent=self.root)
             logging.error(f"Fehler beim Extrahieren der ID aus Item {item_iid} für E-Mail: {e}")
        except Exception as e:
             messagebox.showerror("Fehler", f"Unerwarteter Fehler beim Vorbereiten der E-Mail (ID {item_iid}):\n{e}", parent=self.root)
             logging.exception(f"Unerwarteter Fehler beim Starten des E-Mail-Prozesses für Item {item_iid}:")
        finally:
             self.on_invoice_select()

    def _get_invoice_and_customer_data(self, invoice_id):
        if not self.conn:
            logging.error("DB-Verbindung nicht verfügbar in _get_invoice_and_customer_data.")
            return None, None, None
        cursor = self.conn.cursor()
        invoice_dict, customer_dict, items_list = None, None, []
        try:
            # Alle benötigten Spalten explizit abfragen, auch die neue 'datum_letzte_mahnung'
            cursor.execute("SELECT *, datum_letzte_mahnung FROM rechnungen WHERE id=?", (invoice_id,))
            invoice_data = cursor.fetchone()
            if not invoice_data:
                logging.error(f"Rechnung mit ID {invoice_id} nicht gefunden.")
                return None, None, None
            invoice_dict = dict(zip([d[0] for d in cursor.description], invoice_data))

            customer_id = invoice_dict.get('kunde_id')
            if not customer_id:
                 logging.error(f"Keine Kunden-ID in Rechnung ID {invoice_id}.")
                 return invoice_dict, None, None
            cursor.execute("SELECT * FROM kunden WHERE id=?", (customer_id,))
            customer_data = cursor.fetchone()
            if not customer_data:
                logging.error(f"Kunde ID {customer_id} (aus Rng ID {invoice_id}) nicht gefunden.")
                return invoice_dict, None, None
            customer_dict = dict(zip([d[0] for d in cursor.description], customer_data))

            cursor.execute("SELECT * FROM rechnungsposten WHERE rechnung_id=? ORDER BY position ASC", (invoice_id,))
            items_data = cursor.fetchall()
            items_list = [dict(zip([d[0] for d in cursor.description], row)) for row in items_data]

            logging.debug(f"Daten für Rng ID {invoice_id} geladen (Kunde ID: {customer_id}, {len(items_list)} Posten).")
            return invoice_dict, customer_dict, items_list

        except sqlite3.Error as e:
            logging.error(f"SQLite-Fehler beim Laden der Daten für Rng ID {invoice_id}: {e}")
            return None, None, None
        except Exception as e:
            logging.exception(f"Allgemeiner Fehler beim Laden der Daten für Rng ID {invoice_id}:")
            return None, None, None

    def _replace_placeholders(self, template_string, data_dict):
        if not template_string: return ""
        modified_string = template_string
        for placeholder, value in data_dict.items():
            value_str = str(value) if value is not None else ""
            modified_string = modified_string.replace(f"{{{{{placeholder}}}}}", value_str)
        return modified_string

    def _generate_and_save_letter(self, invoice_id, update_bemerkung=True):
        re_data, k_data, p_data = self._get_invoice_and_customer_data(invoice_id)

        if not re_data or not k_data:
            messagebox.showerror("Datenfehler", f"Unvollständige Daten für Rng ID {invoice_id}. PDF kann nicht erstellt werden.", parent=self.root)
            return None

        re_nr = re_data.get('rechnungsnummer', 'FEHLER_NR')
        k_nr = k_data.get('zifferncode', 'KEINE_KDNR')
        inv_status = re_data.get('status', 'Unbekannt')
        
        aktuelle_mahnkosten = 0.0
        if inv_status == 'Steht zur Mahnung an':
            aktuelle_mahnkosten = self.mahnkosten_1
        elif inv_status == 'Steht zur Mahnung 2 an':
            aktuelle_mahnkosten = self.mahnkosten_2
        
        betrag_brutto_raw = re_data.get('summe_brutto', 0.0)
        gesamtbetrag_inkl_mahnkosten = betrag_brutto_raw + aktuelle_mahnkosten

        fstr_curr = lambda val, p=2: f"{val:,.{p}f} €".replace('.', '#').replace(',', '.').replace('#', ',') if val is not None else ""
        
        template_key = PDF_TEMPLATE_KEY_MAP.get(inv_status, 'reminder')
        if template_key not in self.pdf_letter_templates:
            logging.warning(f"Vorlage für Key '{template_key}' nicht gefunden, verwende 'reminder'.")
            template_key = 'reminder'

        current_template = self.pdf_letter_templates[template_key]
        letter_type_display = current_template.get("display_name", "Schreiben")
        pdf_prefix = template_key.capitalize()

        placeholders = {
            "KUNDE_ANREDE_NAME": f"{k_data.get('anrede', '')} {k_data.get('name', 'N/A')}".strip(),
            "KUNDE_VORNAME": k_data.get('vorname', ''),
            "KUNDE_NACHNAME": k_data.get('name', 'N/A'),
            "KUNDE_FIRMA_TITEL": k_data.get('titel_firma', ''),
            "KUNDE_STRASSE_NR": f"{k_data.get('strasse', '')} {k_data.get('hausnummer', '')}".strip(),
            "KUNDE_PLZ_ORT": f"{k_data.get('plz', '')} {k_data.get('ort', '')}".strip(),
            "RECHNUNGSNUMMER": re_nr,
            "RECHNUNGSDATUM": re_data.get('rechnungsdatum', 'N/A'),
            "FAELLIGKEITSDATUM": re_data.get('faelligkeitsdatum', 'N/A'),
            "BETRAG_BRUTTO_FORM": fstr_curr(betrag_brutto_raw),
            "BETRAG_OFFEN_FORM": fstr_curr(betrag_brutto_raw),
            "MAHNKOSTEN_FORM": fstr_curr(aktuelle_mahnkosten),
            "GESAMTBETRAG_INKL_MAHNKOSTEN_FORM": fstr_curr(gesamtbetrag_inkl_mahnkosten),
            "HEUTIGES_DATUM": datetime.now().strftime('%d.%m.%Y')
        }
        for comp_key, comp_val in self.company_details.items():
            placeholders[f"EIGENE_FIRMA_{comp_key.upper()}"] = comp_val if comp_val is not None else ""

        today_date = datetime.now().date()
        if template_key == 'dunning1':
            placeholders["DATUM_IN_7_TAGEN"] = (today_date + timedelta(days=7)).strftime("%d.%m.%Y")
        
        elif template_key == 'dunning2':
            placeholders["DATUM_IN_5_TAGEN"] = (today_date + timedelta(days=5)).strftime("%d.%m.%Y")
            last_mahn_date_str = re_data.get('datum_letzte_mahnung', 'Ihrer letzten Mahnung')
            placeholders["DATUM_LETZTE_MAHNUNG"] = last_mahn_date_str if last_mahn_date_str else "Ihrer letzten Mahnung"

        if hasattr(self, 'custom_placeholders_dict') and self.custom_placeholders_dict:
            for custom_key_full, custom_value_text in self.custom_placeholders_dict.items():
                if custom_key_full.startswith("{{") and custom_key_full.endswith("}}") and len(custom_key_full) > 4:
                    placeholder_name_inner = custom_key_full[2:-2]
                    if placeholder_name_inner not in placeholders:
                        placeholders[placeholder_name_inner] = custom_value_text

        title_text = self._replace_placeholders(current_template.get("title_text_template", ""), placeholders)
        intro_text = self._replace_placeholders(current_template.get("intro_text_template", ""), placeholders)
        closing_text = self._replace_placeholders(current_template.get("closing_text_template", ""), placeholders)

        output_filename = f"{pdf_prefix}_{re_nr}_Kd{k_nr}.pdf"
        output_path = None
        if k_nr and self.document_base_path:
            customer_folder = self.create_customer_document_folder(k_data.get('id'), k_nr)
            if customer_folder:
                output_path = os.path.join(customer_folder, output_filename)
        
        if output_path is None:
            fallback_dir = os.path.dirname(os.path.abspath(__file__))
            output_path = os.path.join(fallback_dir, output_filename)
            logging.warning(f"PDF wird im Fallback-Verzeichnis gespeichert: {output_path}")

        try:
            # Komplette PDF-Erstellungslogik
            page_width, page_height = A4
            styles = getSampleStyleSheet()
            style_normal = ParagraphStyle(name='Normal', parent=styles['Normal'], fontSize=10, leading=12)
            style_sender_line = ParagraphStyle(name='SenderLine', parent=styles['Normal'], fontSize=8, leading=10, alignment=TA_LEFT)
            style_right = ParagraphStyle(name='Right', parent=style_normal, alignment=TA_RIGHT)
            style_title = ParagraphStyle(name='Title', parent=styles['h2'], fontSize=12, alignment=TA_LEFT, spaceAfter=10)
            margin = 20 * mm
            content_width = page_width - 2 * margin
            story = []

            logo_path_pdf = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo_pdf.png")
            if os.path.exists(logo_path_pdf):
                 try:
                     img_temp=Image(logo_path_pdf); aspect_ratio=img_temp._getHeight()/img_temp._getWidth(); logo_width_pdf=40*mm; logo_height_pdf=logo_width_pdf*aspect_ratio; logo=Image(logo_path_pdf,width=logo_width_pdf,height=logo_height_pdf); logo.hAlign='RIGHT'; story.append(logo); story.append(Spacer(1,5*mm))
                 except Exception as logo_err: logging.error(f"Fehler beim Verarbeiten des PDF-Logos '{logo_path_pdf}': {logo_err}")

            story.append(Spacer(1, 25 * mm))
            sender_line = " – ".join(filter(None, [self.company_details.get(k, '') for k in ['name', 'address', 'zip_city']]))
            if sender_line:
                story.append(Paragraph(sender_line, style_sender_line))
                story.append(Spacer(1, 2 * mm))

            address_lines = [ k_data.get('titel_firma', ''), f"{k_data.get('anrede', '')} {k_data.get('vorname', '')} {k_data.get('name', '')}".strip(), f"{k_data.get('strasse', '')} {k_data.get('hausnummer', '')}".strip(), f"{k_data.get('plz', '')} {k_data.get('ort', '')}".strip() ]
            for line in filter(None, address_lines): story.append(Paragraph(line, style_normal))
            story.append(Spacer(1, 15 * mm))
            story.append(Paragraph(f"<b>Kundennummer:</b> {k_nr}", style_right))
            story.append(Paragraph(f"<b>Datum:</b> {placeholders['HEUTIGES_DATUM']}", style_right))
            story.append(Spacer(1, 10 * mm))
            story.append(Paragraph(title_text, style_title))
            story.append(Spacer(1, 10 * mm))
            story.append(Paragraph(intro_text.replace('\n', '<br/>'), style_normal))
            story.append(Spacer(1, 10 * mm))

            if p_data and inv_status == 'Offen':
                 header_row = ["Pos", "ArtNr", "Beschreibung", "Menge", "Einheit", "Einzelpr. Netto", "Gesamtpr. Netto"]
                 table_data = [header_row]
                 fstr_num = lambda v, p=2: f"{v:,.{p}f}".replace('.', '#').replace(',', '.').replace('#', ',') if isinstance(v, (int, float)) else str(v)
                 for item in p_data:
                     row = [item.get('position',''), item.get('artikelnummer',''), Paragraph(item.get('beschreibung',''), style_normal), fstr_num(item.get('menge',0.0)), item.get('einheit',''), fstr_num(item.get('einzelpreis_netto',0.0))+" €", fstr_num(item.get('gesamtpreis_netto',0.0))+" €"]
                     table_data.append(row)
                 col_widths = [15*mm, 25*mm, content_width-(15+25+20+15+30+30)*mm, 20*mm, 15*mm, 30*mm, 30*mm]
                 items_table = Table(table_data, colWidths=col_widths)
                 items_table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),grey), ('TEXTCOLOR',(0,0),(-1,0),black), ('ALIGN',(0,0),(-1,-1),'CENTER'), ('ALIGN',(2,1),(2,-1),'LEFT'), ('ALIGN',(0,1),(1,-1),'RIGHT'), ('ALIGN',(3,1),(3,-1),'RIGHT'), ('ALIGN',(5,1),(-1,-1),'RIGHT'), ('VALIGN',(0,0),(-1,-1),'MIDDLE'), ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'), ('BOTTOMPADDING',(0,0),(-1,0),6), ('GRID',(0,0),(-1,-1),0.5,black)]))
                 story.append(items_table)
                 story.append(Spacer(1,5*mm))

            mwst_satz_re=re_data.get('mwst_prozent',self.default_vat_rate); sum_net_re=re_data.get('summe_netto',0.0); sum_mwst_re=re_data.get('summe_mwst',0.0);
            fstr_num_sum = lambda v, p=2: f"{v:,.{p}f}".replace('.', '#').replace(',', '.').replace('#', ',') if isinstance(v, (int, float)) else str(v)
            
            summary_table = None
            if inv_status in ['Steht zur Mahnung an', 'Steht zur Mahnung 2 an']:
                summary_data = [
                    ['Summe Netto (ursprüngl. Rechnung):', fstr_curr(sum_net_re)],
                    [f'zzgl. {fstr_num_sum(mwst_satz_re, 1)}% MwSt.:', fstr_curr(sum_mwst_re)],
                    ['Rechnungsbetrag Brutto:', fstr_curr(betrag_brutto_raw)],
                    [f'Zzgl. Mahnkosten ({letter_type_display}):', fstr_curr(aktuelle_mahnkosten)],
                    [Paragraph('<b>Neuer fälliger Gesamtbetrag:</b>', style_right), Paragraph(f"<b>{fstr_curr(gesamtbetrag_inkl_mahnkosten)}</b>", style_right)]
                ]
                summary_table = Table(summary_data, colWidths=[content_width - 50 * mm, 50 * mm])
                summary_table.setStyle(TableStyle([ ('ALIGN', (0, 0), (-1, -1), 'RIGHT'), ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0), ('LINEABOVE', (0, 2), (1, 2), 0.5, black), ('TOPPADDING', (0, 2), (-1, 2), 3), ('BOTTOMPADDING', (0, 2), (-1, 2), 3), ('LINEABOVE', (0, 4), (1, 4), 0.5, black), ('TOPPADDING', (0, 4), (-1, 4), 3) ]))
            else: 
                summary_data = [
                    ['Summe Netto:', fstr_curr(sum_net_re)],
                    [f'zzgl. {fstr_num_sum(mwst_satz_re, 1)}% MwSt.:', fstr_curr(sum_mwst_re)],
                    [Paragraph('<b>Rechnungsbetrag Brutto:</b>', style_right), Paragraph(f"<b>{fstr_curr(betrag_brutto_raw)}</b>", style_right)]
                ]
                summary_table = Table(summary_data, colWidths=[content_width - 50 * mm, 50 * mm])
                summary_table.setStyle(TableStyle([ ('ALIGN', (0, 0), (-1, -1), 'RIGHT'), ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0), ('LINEABOVE', (0, 2), (1, 2), 0.5, black), ('TOPPADDING', (0, 2), (-1, 2), 3) ]))
            story.append(summary_table)
            story.append(Spacer(1,10*mm))

            if closing_text:
                story.append(Paragraph(closing_text.replace('\n', '<br/>'), style_normal))
                story.append(Spacer(1, 15 * mm))

            def draw_background_and_footer(canvas_obj, doc_obj):
                canvas_obj.saveState(); bg_path = self.pdf_background_path
                if bg_path and os.path.exists(bg_path):
                    try: canvas_obj.drawImage(bg_path,0,0,width=page_width,height=page_height,preserveAspectRatio=True,anchor='c')
                    except Exception as bg_err: logging.error(f"Fehler Hintergrundbild '{bg_path}' S.{canvas_obj.getPageNumber()}: {bg_err}")
                footer_y_pos = doc_obj.bottomMargin/2; line_y_pos = footer_y_pos+2.5*mm; canvas_obj.setStrokeColor(black); canvas_obj.setLineWidth(0.5); canvas_obj.line(doc_obj.leftMargin,line_y_pos,page_width-doc_obj.rightMargin,line_y_pos)
                footer1=f"{self.company_details.get('name','')} | {self.company_details.get('address','')} | {self.company_details.get('zip_city','')}"
                footer2=f"Bank: {self.company_details.get('bank_details','')} | USt-IdNr: {self.company_details.get('tax_id','')}"
                footer3=f"Tel: {self.company_details.get('phone','')} | E-Mail: {self.company_details.get('email','')} | Seite {canvas_obj.getPageNumber()}"
                canvas_obj.setFont('Helvetica',8); text_y1_pos=footer_y_pos-1*mm; text_y2_pos=text_y1_pos-3*mm; text_y3_pos=text_y2_pos-3*mm
                canvas_obj.drawString(doc_obj.leftMargin,text_y1_pos,footer1); canvas_obj.drawString(doc_obj.leftMargin,text_y2_pos,footer2); canvas_obj.drawString(doc_obj.leftMargin,text_y3_pos,footer3)
                canvas_obj.restoreState()

            doc = BaseDocTemplate(output_path, pagesize=A4, leftMargin=margin, rightMargin=margin, topMargin=margin, bottomMargin=margin * 1.5)
            main_frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id='main_frame')
            main_page_template = PageTemplate(id='mainPage', frames=[main_frame], onPage=draw_background_and_footer)
            doc.addPageTemplates([main_page_template])
            doc.build(story)
            logging.info(f"PDF '{letter_type_display}' erstellt: {output_path}")
            
            # ### GoBD-ÄNDERUNG ###: PDF-Erstellung als Geschäftsvorfall protokollieren
            if update_bemerkung: # Nur loggen, wenn es eine "echte" Generierung ist, keine Vorschau
                log_audit_action(self.conn, 'MAHNSCHREIBEN_GENERERT', invoice_id,
                                 f"'{letter_type_display}' für Rng-Nr '{re_nr}' generiert. Datei: {output_filename}",
                                 user=self.current_user)

            # PDF-Pfad in kunden_dokumente speichern
            try:
                 cursor = self.conn.cursor()
                 cursor.execute("SELECT id FROM kunden_dokumente WHERE kunde_id=? AND dokument_pfad=?",(k_data['id'],output_path))
                 if not cursor.fetchone():
                     cursor.execute("INSERT INTO kunden_dokumente (kunde_id, dokument_pfad, dateiname) VALUES (?, ?, ?)",
                                    (k_data['id'], output_path, output_filename))
                     self.conn.commit()
                     logging.info(f"Doku '{output_filename}' für Kd ID {k_data['id']} in DB hinzugefügt.")
            except sqlite3.Error as db_doc_err:
                logging.error(f"Fehler Speichern von PDF-Pfad in DB: {db_doc_err}")
                self.conn.rollback()

            # Bemerkung, Mahndatum und Mahngebühren aktualisieren
            if update_bemerkung:
                bemerkung_add = f"{datetime.now().strftime('%d.%m.%Y %H:%M')}: '{letter_type_display}' generiert ({os.path.basename(output_path)})."
                self._update_invoice_bemerkung(invoice_id, bemerkung_add)
                
                dunning_date_str = datetime.now().strftime('%d.%m.%Y')
                
                # Nur für die erste Mahnstufe das Datum der "letzten Mahnung" setzen
                if template_key == 'dunning1':
                    self._update_invoice_dunning_date(invoice_id, dunning_date_str)
                
                # Mahngebühren in die Datenbank schreiben und offenen Betrag erhöhen
                if aktuelle_mahnkosten > 0:
                    try:
                        db_cursor = self.conn.cursor()
                        db_cursor.execute("""
                            UPDATE rechnungen 
                            SET 
                                mahngebuehren = ?,
                                offener_betrag = summe_brutto + ?
                            WHERE id = ?
                        """, (aktuelle_mahnkosten, aktuelle_mahnkosten, invoice_id))
                        
                        # ### GoBD-ÄNDERUNG ###: Verbuchung der Mahngebühren protokollieren
                        log_audit_action(self.conn, 'MAHNUNG_GEBUEHR_VERBUCHT', invoice_id,
                                         f"Mahngebühren von {aktuelle_mahnkosten:.2f} € für Rng-Nr '{re_nr}' verbucht. Neuer offener Betrag: {gesamtbetrag_inkl_mahnkosten:.2f} €.",
                                         user=self.current_user)
                        
                        self.conn.commit()
                        logging.info(f"Mahngebühren ({aktuelle_mahnkosten} €) für Rng-ID {invoice_id} in DB gesetzt und offener Betrag neu berechnet.")
                    except sqlite3.Error as e:
                        logging.error(f"Fehler beim Aktualisieren der Mahngebühren für Rng-ID {invoice_id}: {e}")
                        self.conn.rollback()
                        messagebox.showerror("DB-Fehler", f"Konnte Mahngebühren für Rechnung {re_nr} nicht in der Datenbank speichern.", parent=self.root)
            
            return output_path

        except PermissionError:
            logging.error(f"PDF Speicherfehler: Keine Berechtigung für '{output_path}'.")
            messagebox.showerror("PDF Speicherfehler", f"Keine Berechtigung für:\n{output_path}", parent=self.root)
            return None
        except Exception as pdf_err:
            logging.exception(f"Allg. PDF-Erstellungsfehler Rng {re_nr}:")
            messagebox.showerror("PDF Erstellungsfehler", f"Unerwarteter Fehler bei PDF-Erstellung:\n{pdf_err}", parent=self.root)
            return None

    def _update_invoice_bemerkung(self, invoice_id, text_to_add):
        if not self.conn or not invoice_id:
            return False
        cursor = self.conn.cursor()
        try:
            cursor.execute("SELECT bemerkung FROM rechnungen WHERE id=?", (invoice_id,))
            result = cursor.fetchone()
            if result is None:
                return False
            current_bemerkung = result[0] if result[0] else ""
            new_bemerkung = ((current_bemerkung + "\n") if current_bemerkung else "") + text_to_add.strip()
            cursor.execute("UPDATE rechnungen SET bemerkung=? WHERE id=?", (new_bemerkung, invoice_id))
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            logging.error(f"SQLite-Fehler bei Update Bemerkung für Rng ID {invoice_id}: {e}")
            self.conn.rollback()
            return False

    def _update_invoice_dunning_date(self, invoice_id, dunning_date_str):
        """Speichert das Datum der 1. Mahnung in der Datenbank."""
        if not self.conn or not invoice_id:
            return False
        cursor = self.conn.cursor()
        try:
            cursor.execute("UPDATE rechnungen SET datum_letzte_mahnung=? WHERE id=?", (dunning_date_str, invoice_id))
            self.conn.commit()
            logging.info(f"Datum der 1. Mahnung ({dunning_date_str}) für Rechnung ID {invoice_id} gespeichert.")
            return True
        except sqlite3.Error as e:
            logging.error(f"SQLite-Fehler beim Speichern des Mahnungsdatums für Rng ID {invoice_id}: {e}")
            self.conn.rollback()
            return False

    def _get_pdf_templates_path(self):
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), PDF_TEMPLATES_FILENAME)

    def _load_pdf_letter_templates(self):
        templates_path = self._get_pdf_templates_path()
        loaded_templates = {}
        try:
            if os.path.exists(templates_path):
                with open(templates_path, "r", encoding='utf-8') as f:
                    loaded_templates = json.load(f)
            if not isinstance(loaded_templates, dict):
                logging.error(f"Inhalt von '{templates_path}' kein gültiges dict. Verwende Defaults.")
                loaded_templates = {}
        except Exception as e:
            logging.exception(f"Fehler beim Laden der PDF-Vorlagen aus '{templates_path}'. Verwende Defaults.")
            loaded_templates = {}

        final_templates = json.loads(json.dumps(DEFAULT_PDF_LETTER_TEMPLATES))
        for key, default_value_dict in DEFAULT_PDF_LETTER_TEMPLATES.items():
            if key in loaded_templates and isinstance(loaded_templates[key], dict):
                for sub_key, default_sub_value in default_value_dict.items():
                    final_templates[key][sub_key] = loaded_templates[key].get(sub_key, default_sub_value)
        self.pdf_letter_templates = final_templates

    def _save_pdf_letter_templates(self):
        templates_path = self._get_pdf_templates_path()
        try:
            os.makedirs(os.path.dirname(templates_path), exist_ok=True)
            with open(templates_path, "w", encoding='utf-8') as f:
                json.dump(self.pdf_letter_templates, f, indent=4, ensure_ascii=False, sort_keys=True)
            return True
        except Exception as e:
            logging.error(f"Fehler beim Speichern der PDF-Textvorlagen: {e}")
            messagebox.showerror("Dateifehler", f"Fehler beim Speichern der PDF-Textvorlagen:\n{e}", parent=self.root)
            return False

    def open_edit_pdf_templates_window(self):
        editor_window = tk.Toplevel(self.root)
        editor_window.title("PDF Textvorlagen bearbeiten")
        editor_window.geometry("850x650")
        editor_window.transient(self.root)
        editor_window.grab_set()
        editor_window.minsize(700, 500)
        last_focused_text_widget = None
        main_frame = ttk.Frame(editor_window, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        left_frame = ttk.Frame(main_frame)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        ttk.Label(left_frame, text="Vorlagentyp auswählen:").pack(anchor=tk.W, pady=(0, 5))
        template_keys = list(self.pdf_letter_templates.keys())
        template_display_names = [self.pdf_letter_templates[key].get("display_name", key) for key in template_keys]
        self.current_pdf_template_key_var = tk.StringVar()
        template_combobox = ttk.Combobox(left_frame, textvariable=self.current_pdf_template_key_var,
                                         values=template_display_names, state="readonly", width=40)
        template_combobox.pack(fill=tk.X, pady=(0, 10))
        if template_display_names: template_combobox.current(0)
        ttk.Label(left_frame, text="Titel-Text Vorlage:").pack(anchor=tk.W)
        title_text_widget = tk.Text(left_frame, height=3, width=60, wrap=tk.WORD, borderwidth=1, relief="solid", undo=True)
        title_text_widget.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(left_frame, text="Einleitungstext Vorlage:").pack(anchor=tk.W)
        intro_frame = ttk.Frame(left_frame); intro_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        intro_scroll = ttk.Scrollbar(intro_frame, orient=tk.VERTICAL)
        intro_text_widget = tk.Text(intro_frame, height=10, width=60, wrap=tk.WORD, borderwidth=1, relief="solid", undo=True, yscrollcommand=intro_scroll.set)
        intro_scroll.config(command=intro_text_widget.yview); intro_scroll.pack(side=tk.RIGHT, fill=tk.Y); intro_text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ttk.Label(left_frame, text="Schlusstext Vorlage:").pack(anchor=tk.W)
        closing_frame = ttk.Frame(left_frame); closing_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        closing_scroll = ttk.Scrollbar(closing_frame, orient=tk.VERTICAL)
        closing_text_widget = tk.Text(closing_frame, height=6, width=60, wrap=tk.WORD, borderwidth=1, relief="solid", undo=True, yscrollcommand=closing_scroll.set)
        closing_scroll.config(command=closing_text_widget.yview); closing_scroll.pack(side=tk.RIGHT, fill=tk.Y); closing_text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        def _on_text_focus_in(event):
            nonlocal last_focused_text_widget
            if event.widget in [title_text_widget, intro_text_widget, closing_text_widget]:
                last_focused_text_widget = event.widget
        title_text_widget.bind("<FocusIn>", _on_text_focus_in); intro_text_widget.bind("<FocusIn>", _on_text_focus_in); closing_text_widget.bind("<FocusIn>", _on_text_focus_in)
        
        right_frame = ttk.Frame(main_frame)
        right_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=(10, 0))
        ttk.Label(right_frame, text="Verfügbare Platzhalter:").pack(anchor=tk.NW, pady=(0, 5))
        listbox_container_frame = ttk.Frame(right_frame); listbox_container_frame.pack(fill=tk.BOTH, expand=True)
        scrollbar_placeholders_y = ttk.Scrollbar(listbox_container_frame, orient=tk.VERTICAL)
        placeholder_listbox = tk.Listbox(listbox_container_frame, height=20, width=45, borderwidth=1, relief="solid", yscrollcommand=scrollbar_placeholders_y.set, exportselection=False) 
        scrollbar_placeholders_y.config(command=placeholder_listbox.yview); scrollbar_placeholders_y.pack(side=tk.RIGHT, fill=tk.Y); placeholder_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        def refresh_placeholder_listbox():
            placeholder_listbox.delete(0, tk.END)
            for item in PDF_PLACEHOLDERS_BUILTIN: placeholder_listbox.insert(tk.END, item)
            custom_formatted = [f"{key} ({desc})" for key, desc in sorted(self.custom_placeholders_dict.items())]
            if custom_formatted:
                 placeholder_listbox.insert(tk.END, "--- Eigene Platzhalter ---")
                 placeholder_listbox.itemconfig(tk.END, {'fg': 'grey', 'selectbackground': placeholder_listbox.cget('bg'), 'selectforeground': 'grey'})
                 for item in custom_formatted: placeholder_listbox.insert(tk.END, item)
        refresh_placeholder_listbox()

        def copy_placeholder_action():
            if last_focused_text_widget is None:
                messagebox.showwarning("Kein Zielfeld fokussiert", "Bitte klicken Sie zuerst in ein Textfeld.", parent=editor_window)
                return
            selection_indices = placeholder_listbox.curselection()
            if not selection_indices:
                messagebox.showwarning("Kein Platzhalter ausgewählt", "Bitte wählen Sie einen Platzhalter aus.", parent=editor_window)
                return
            placeholder_full = placeholder_listbox.get(selection_indices[0])
            if "---" in placeholder_full: return
            actual_placeholder = placeholder_full.split(" (")[0]
            last_focused_text_widget.insert(tk.INSERT, actual_placeholder); last_focused_text_widget.focus_set()
        copy_button = ttk.Button(right_frame, text="↙️ Platzhalter hier einfügen", command=copy_placeholder_action); copy_button.pack(pady=(5, 0), fill=tk.X)

        def open_manage_and_refresh():
            self.open_manage_custom_placeholders_window(editor_window)
            refresh_placeholder_listbox()
        manage_button = ttk.Button(right_frame, text="Eigene Platzhalter verwalten...", command=open_manage_and_refresh); manage_button.pack(pady=(5, 0), fill=tk.X)

        def get_key_from_display_name(name):
            for k, d in self.pdf_letter_templates.items():
                if d.get("display_name") == name: return k
            return None

        def load_template_texts_for_editor(event=None):
            key = get_key_from_display_name(self.current_pdf_template_key_var.get())
            if key and key in self.pdf_letter_templates:
                template = self.pdf_letter_templates[key]
                title_text_widget.delete("1.0", tk.END); title_text_widget.insert("1.0", template.get("title_text_template", "")); title_text_widget.edit_reset()
                intro_text_widget.delete("1.0", tk.END); intro_text_widget.insert("1.0", template.get("intro_text_template", "")); intro_text_widget.edit_reset()
                closing_text_widget.delete("1.0", tk.END); closing_text_widget.insert("1.0", template.get("closing_text_template", "")); closing_text_widget.edit_reset()
        template_combobox.bind("<<ComboboxSelected>>", load_template_texts_for_editor)
        if template_display_names: load_template_texts_for_editor()

        def save_current_template():
            key = get_key_from_display_name(self.current_pdf_template_key_var.get())
            if key and key in self.pdf_letter_templates:
                self.pdf_letter_templates[key]["title_text_template"] = title_text_widget.get("1.0", tk.END).strip()
                self.pdf_letter_templates[key]["intro_text_template"] = intro_text_widget.get("1.0", tk.END).strip()
                self.pdf_letter_templates[key]["closing_text_template"] = closing_text_widget.get("1.0", tk.END).strip()
                if self._save_pdf_letter_templates(): messagebox.showinfo("Gespeichert", f"Vorlage '{self.current_pdf_template_key_var.get()}' gespeichert.", parent=editor_window)
            else: messagebox.showerror("Fehler", "Keine gültige Vorlage zum Speichern.", parent=editor_window)

        def reset_current_template_to_default():
            key = get_key_from_display_name(self.current_pdf_template_key_var.get())
            if key and key in DEFAULT_PDF_LETTER_TEMPLATES:
                if messagebox.askyesno("Zurücksetzen", f"Vorlage '{self.current_pdf_template_key_var.get()}' auf Standard zurücksetzen?", parent=editor_window, icon=messagebox.WARNING):
                    self.pdf_letter_templates[key] = json.loads(json.dumps(DEFAULT_PDF_LETTER_TEMPLATES[key]))
                    if self._save_pdf_letter_templates():
                         load_template_texts_for_editor()
                         messagebox.showinfo("Zurückgesetzt", f"Vorlage zurückgesetzt.", parent=editor_window)
            else: messagebox.showerror("Fehler", "Vorlage nicht zurücksetzbar.", parent=editor_window)

        button_frame = ttk.Frame(editor_window, padding=(0, 10, 0, 0)); button_frame.pack(fill=tk.X, side=tk.BOTTOM, pady=(0,10))
        ttk.Button(button_frame, text="Speichern", command=save_current_template).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Auf Standard zurücksetzen", command=reset_current_template_to_default).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Schließen", command=editor_window.destroy).pack(side=tk.RIGHT, padx=5)

    def open_manage_custom_placeholders_window(self, parent=None):
        manage_win = tk.Toplevel(parent or self.root); manage_win.title("Eigene Platzhalter verwalten"); manage_win.geometry("550x600"); manage_win.transient(parent or self.root); manage_win.grab_set(); manage_win.resizable(False, True)
        main_frame = ttk.Frame(manage_win, padding=10); main_frame.pack(fill=tk.BOTH, expand=True)
        tree_frame = ttk.LabelFrame(main_frame, text="Benutzerdefinierte Platzhalter"); tree_frame.pack(fill=tk.BOTH, expand=True, pady=(0,10))
        cols = ('key', 'description'); tree = ttk.Treeview(tree_frame, columns=cols, show='headings', selectmode='browse'); tree.heading('key', text='Platzhalter (z.B. {{MEIN_WERT}})'); tree.heading('description', text='Beschreibung'); tree.column('key', width=200, anchor=tk.W, stretch=tk.NO); tree.column('description', width=300, anchor=tk.W, stretch=tk.YES)
        tree_scroll_y = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=tree.yview); tree.configure(yscrollcommand=tree_scroll_y.set); tree_scroll_y.pack(side=tk.RIGHT, fill=tk.Y); tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        def populate_tree():
            for item in tree.get_children(): tree.delete(item)
            for key, desc in sorted(self.custom_placeholders_dict.items()): tree.insert('', tk.END, values=(key, desc), iid=key)
        populate_tree()
        add_frame = ttk.LabelFrame(main_frame, text="Neuen Platzhalter hinzufügen"); add_frame.pack(fill=tk.X, pady=(0,10))
        ttk.Label(add_frame, text="Platzhalter:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W); entry_key = ttk.Entry(add_frame, width=30); entry_key.grid(row=0, column=1, padx=5, pady=5, sticky=tk.EW)
        ttk.Label(add_frame, text="Beschreibung:").grid(row=1, column=0, padx=5, pady=5, sticky=tk.W); entry_desc = ttk.Entry(add_frame, width=40); entry_desc.grid(row=1, column=1, padx=5, pady=5, sticky=tk.EW)
        add_frame.columnconfigure(1, weight=1)
        def add_new_placeholder():
            new_key, new_desc = entry_key.get().strip(), entry_desc.get().strip()
            if not (new_key.startswith("{{") and new_key.endswith("}}") and len(new_key) > 4): messagebox.showerror("Fehler", "Ungültiges Format.", parent=manage_win); return
            if new_key in self.custom_placeholders_dict: messagebox.showerror("Fehler", f"Platzhalter '{new_key}' existiert bereits.", parent=manage_win); return
            builtin_keys = {p.split(" (")[0] for p in PDF_PLACEHOLDERS_BUILTIN}
            if new_key in builtin_keys and not messagebox.askyesno("Warnung", f"'{new_key}' ist System-Platzhalter. Trotzdem hinzufügen?", parent=manage_win, icon=messagebox.WARNING): return
            self.custom_placeholders_dict[new_key] = new_desc or "(keine Beschreibung)"
            if save_custom_placeholders(self.custom_placeholders_dict):
                populate_tree(); entry_key.delete(0, tk.END); entry_desc.delete(0, tk.END); entry_key.focus_set()
                if tree.exists(new_key): tree.selection_set(new_key); tree.focus(new_key); tree.see(new_key)
            else: del self.custom_placeholders_dict[new_key]
        btn_add = ttk.Button(add_frame, text="Hinzufügen", command=add_new_placeholder); btn_add.grid(row=0, column=2, rowspan=2, padx=10, pady=5, sticky=tk.NS); entry_desc.bind("<Return>", lambda event: add_new_placeholder())
        bottom_btn_frame = ttk.Frame(main_frame); bottom_btn_frame.pack(fill=tk.X)
        def delete_selected_placeholder():
            sel_item = tree.selection()
            if not sel_item: return
            key_to_del = tree.item(sel_item[0])['values'][0]
            if messagebox.askyesno("Löschen", f"Platzhalter '{key_to_del}' löschen?", parent=manage_win, icon=messagebox.WARNING):
                del self.custom_placeholders_dict[key_to_del]
                if save_custom_placeholders(self.custom_placeholders_dict): populate_tree()
                else: self.custom_placeholders_dict = load_custom_placeholders(); populate_tree()
        ttk.Button(bottom_btn_frame, text="Ausgewählten löschen", command=delete_selected_placeholder).pack(side=tk.LEFT, padx=5); ttk.Button(bottom_btn_frame, text="Schließen", command=manage_win.destroy).pack(side=tk.RIGHT, padx=5)
        manage_win.wait_window()

    def _get_email_templates_path(self): return os.path.join(os.path.dirname(os.path.abspath(__file__)), "email_templates.json")
    def _load_email_templates(self):
        tpl_path = self._get_email_templates_path(); tpls = {}
        try:
            if os.path.exists(tpl_path):
                with open(tpl_path, "r", encoding='utf-8') as f: tpls = json.load(f)
            if not isinstance(tpls, dict): return {}
        except Exception: return {}
        return tpls
    def _save_email_templates(self, tpls_dict):
        tpl_path = self._get_email_templates_path()
        try:
            os.makedirs(os.path.dirname(tpl_path), exist_ok=True)
            with open(tpl_path, "w", encoding='utf-8') as f: json.dump(tpls_dict, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e: logging.error(f"Fehler Speichern E-Mail-Vorlagen: {e}"); return False

    def open_email_compose_window(self, parent, recipient_email, attachment_path, attachment_filename, invoice_id=None, invoice_status=None, default_subject=""):
        win = tk.Toplevel(parent); win.title("E-Mail senden"); win.geometry("650x600"); win.transient(parent); win.grab_set(); win.resizable(True, True); win.minsize(500,450)
        fr = ttk.Frame(win, padding=10); fr.pack(fill=tk.BOTH, expand=True)
        ttk.Label(fr,text="An:").grid(row=0,column=0,padx=5,pady=5,sticky=tk.W); entry_to=ttk.Entry(fr,width=60); entry_to.grid(row=0,column=1,columnspan=2,padx=5,pady=5,sticky=tk.EW); entry_to.insert(0,recipient_email or "")
        ttk.Label(fr,text="Betreff:").grid(row=1,column=0,padx=5,pady=5,sticky=tk.W); entry_subj=ttk.Entry(fr,width=60); entry_subj.grid(row=1,column=1,columnspan=2,padx=5,pady=5,sticky=tk.EW); entry_subj.insert(0,default_subject)
        ttk.Label(fr,text="Anhang:").grid(row=2,column=0,padx=5,pady=5,sticky=tk.W); lbl_att=ttk.Label(fr,text=attachment_filename,foreground="blue",cursor="hand2",wraplength=450); lbl_att.grid(row=2,column=1,columnspan=2,padx=5,pady=5,sticky=tk.W)
        if attachment_path and os.path.exists(attachment_path): lbl_att.bind("<Button-1>",lambda e,p=attachment_path:self._open_file(p))
        else: lbl_att.config(foreground="grey",cursor="",text=f"{attachment_filename} (nicht gefunden)")
        ttk.Label(fr,text="Nachricht:").grid(row=3,column=0,padx=5,pady=5,sticky=tk.NW); body_fr=ttk.Frame(fr); body_fr.grid(row=3,column=1,columnspan=2,padx=5,pady=5,sticky=tk.NSEW); txt_body=tk.Text(body_fr,height=15,width=60,wrap=tk.WORD,undo=True); scrl_body=ttk.Scrollbar(body_fr,orient=tk.VERTICAL,command=txt_body.yview); txt_body.config(yscrollcommand=scrl_body.set); scrl_body.pack(side=tk.RIGHT,fill=tk.Y); txt_body.pack(side=tk.LEFT,fill=tk.BOTH,expand=True)
        tpl_fr=ttk.LabelFrame(fr,text="Textvorlagen"); tpl_fr.grid(row=4,column=0,columnspan=3,sticky=tk.EW,padx=5,pady=10)
        ttk.Label(tpl_fr,text="Vorlage:").grid(row=0,column=0,padx=5,pady=5,sticky=tk.W); self._email_tpls_combo=ttk.Combobox(tpl_fr,width=30,state="readonly"); self._email_tpls_combo.grid(row=0,column=1,padx=5,pady=5,sticky=tk.EW)
        btn_fr_tpls=ttk.Frame(tpl_fr); btn_fr_tpls.grid(row=0,column=2,padx=5,pady=5,sticky=tk.E)
        btn_load_tpl=ttk.Button(btn_fr_tpls,text="Laden",width=8); btn_load_tpl.pack(side=tk.LEFT,padx=(0,2))
        btn_save_tpl=ttk.Button(btn_fr_tpls,text="Speichern",width=10); btn_save_tpl.pack(side=tk.LEFT,padx=2)
        btn_del_tpl=ttk.Button(btn_fr_tpls,text="Löschen",width=8); btn_del_tpl.pack(side=tk.LEFT,padx=(2,0))
        fr.columnconfigure(1,weight=1); fr.rowconfigure(3,weight=1); tpl_fr.columnconfigure(1,weight=1)
        btn_fr_comp=ttk.Frame(win); btn_fr_comp.pack(pady=10)
        def do_send():
            to,subj,body = entry_to.get().strip(),entry_subj.get().strip(),txt_body.get("1.0",tk.END).strip()
            if not to: messagebox.showerror("Fehler","Empfänger fehlt.",parent=win); return
            btn_send.config(state=tk.DISABLED); btn_cancel.config(state=tk.DISABLED); win.config(cursor="watch"); self.root.update_idletasks()
            succ = self._send_email_actual(to,subj,body,attachment_path,win,invoice_id,invoice_status)
            if win.winfo_exists(): win.config(cursor=""); btn_send.config(state=tk.NORMAL); btn_cancel.config(state=tk.NORMAL);
            if succ: win.destroy()
        def _update_tpl_combo_fn():
            tpls=self._load_email_templates(); tpl_names=sorted(list(tpls.keys()))
            self._email_tpls_combo['values']=tpl_names
            if not tpl_names: self._email_tpls_combo.set(''); btn_load_tpl.config(state=tk.DISABLED); btn_del_tpl.config(state=tk.DISABLED)
            else: self._email_tpls_combo.set(''); btn_load_tpl.config(state=tk.NORMAL); btn_del_tpl.config(state=tk.NORMAL)
        def load_sel_tpl_fn():
            sel_name=self._email_tpls_combo.get()
            if sel_name and sel_name in self._load_email_templates():
                txt_body.delete("1.0",tk.END); txt_body.insert("1.0",self._load_email_templates()[sel_name])
        def save_curr_body_as_tpl_fn():
            curr_body=txt_body.get("1.0",tk.END).strip()
            if not curr_body: return
            tpl_name=simpledialog.askstring("Vorlage speichern","Name für Vorlage:",parent=win)
            if tpl_name:
                tpls=self._load_email_templates(); tpls[tpl_name.strip()]=curr_body
                if self._save_email_templates(tpls): _update_tpl_combo_fn(); self._email_tpls_combo.set(tpl_name.strip())
        def del_sel_tpl_fn():
            sel_name=self._email_tpls_combo.get()
            if sel_name and messagebox.askyesno("Löschen",f"Vorlage '{sel_name}' löschen?",parent=win,icon=messagebox.WARNING):
                tpls=self._load_email_templates()
                if sel_name in tpls: del tpls[sel_name]
                if self._save_email_templates(tpls): _update_tpl_combo_fn()
        btn_load_tpl.config(command=load_sel_tpl_fn); btn_save_tpl.config(command=save_curr_body_as_tpl_fn); btn_del_tpl.config(command=del_sel_tpl_fn)
        btn_send=ttk.Button(btn_fr_comp,text="Senden",command=do_send); btn_send.pack(side=tk.LEFT,padx=10)
        btn_cancel=ttk.Button(btn_fr_comp,text="Abbrechen",command=win.destroy); btn_cancel.pack(side=tk.LEFT,padx=10)
        _update_tpl_combo_fn(); entry_to.focus_set()

    def _is_smtp_configured(self): return bool(self.smtp_server and self.smtp_port and self.smtp_user)

    def _open_file(self, file_path):
        if not file_path or not os.path.exists(file_path): messagebox.showerror("Fehler",f"Datei nicht gefunden:\n{file_path}",parent=self.root); return False
        try:
            if sys.platform=="win32": os.startfile(os.path.normpath(file_path))
            elif sys.platform=="darwin": subprocess.run(["open",file_path],check=True)
            else: subprocess.run(["xdg-open",file_path],check=True)
            return True
        except Exception as e: messagebox.showerror("Fehler",f"Fehler beim Öffnen der Datei:\n{e}",parent=self.root); return False

    def _send_email_actual(self, recipient, subject, body, attachment_path, parent_window, invoice_id=None, invoice_status=None):
        if not self._is_smtp_configured() or not self.smtp_password:
             pw=simpledialog.askstring("SMTP Passwort",f"Passwort für '{self.smtp_user}' eingeben:",show='*',parent=parent_window)
             if not pw: return False
             self.smtp_password=pw
        msg=MIMEMultipart(); msg['From']=self.smtp_user; msg['To']=recipient; msg['Subject']=subject; msg['Date']=formatdate(localtime=True); msg.attach(MIMEText(body,'plain','utf-8'))
        if attachment_path and os.path.exists(attachment_path):
            fname=os.path.basename(attachment_path)
            try:
                with open(attachment_path,"rb") as att_file: part=MIMEBase('application','octet-stream'); part.set_payload(att_file.read())
                encoders.encode_base64(part); part.add_header('Content-Disposition',f"attachment; filename*=UTF-8''{fname}"); msg.attach(part)
            except Exception as e: messagebox.showerror("Fehler",f"Fehler beim Anhängen der Datei:\n{e}",parent=parent_window); return False
        server=None
        try:
            host,port,enc = self.smtp_server,self.smtp_port,self.smtp_encryption.upper(); timeout=15
            if enc=='SSL/TLS': server=smtplib.SMTP_SSL(host,port,timeout=timeout)
            else: server=smtplib.SMTP(host,port,timeout=timeout); server.starttls()
            server.login(self.smtp_user,self.smtp_password)
            server.send_message(msg)
            messagebox.showinfo("Erfolg",f"E-Mail an '{recipient}' gesendet.",parent=parent_window)
            if invoice_id is not None:
                # Nach erfolgreichem Versand werden die DB-Änderungen durchgeführt und protokolliert
                template_key = PDF_TEMPLATE_KEY_MAP.get(invoice_status)
                display_name = "Schreiben"
                if template_key and template_key in self.pdf_letter_templates:
                    display_name = self.pdf_letter_templates[template_key].get('display_name', 'Schreiben')
                
                # Schritt 1: Bemerkung hinzufügen (informell)
                bem_txt = f"'{display_name}' via E-Mail an {recipient} versendet."
                full_bem = f"{datetime.now().strftime('%d.%m.%Y %H:%M')}: {bem_txt}"
                self._update_invoice_bemerkung(invoice_id, full_bem)
                
                # Schritt 2: Formelles Audit-Log für den Versand
                log_audit_action(self.conn, 'MAHNSCHREIBEN_VERSENDET', invoice_id,
                                 f"'{display_name}' für Rng-ID {invoice_id} per E-Mail an {recipient} versendet.",
                                 user=self.current_user)

                # Schritt 3: Mahngebühren und Datum aktualisieren (falls zutreffend) und protokollieren
                # Dies ist die gleiche Logik wie in _generate_and_save_letter, jetzt aber nach dem Versand ausgeführt.
                aktuelle_mahnkosten = 0.0
                if invoice_status == 'Steht zur Mahnung an':
                    aktuelle_mahnkosten = self.mahnkosten_1
                elif invoice_status == 'Steht zur Mahnung 2 an':
                    aktuelle_mahnkosten = self.mahnkosten_2
                
                if invoice_status == 'Steht zur Mahnung an':
                    self._update_invoice_dunning_date(invoice_id, datetime.now().strftime('%d.%m.%Y'))

                if aktuelle_mahnkosten > 0:
                    try:
                        db_cursor = self.conn.cursor()
                        # Hole ursprünglichen Bruttobetrag, um neuen offenen Betrag sicher zu berechnen
                        db_cursor.execute("SELECT summe_brutto FROM rechnungen WHERE id = ?", (invoice_id,))
                        res = db_cursor.fetchone()
                        summe_brutto = res[0] if res else 0.0
                        neuer_offener_betrag = summe_brutto + aktuelle_mahnkosten
                        
                        db_cursor.execute("""
                            UPDATE rechnungen SET mahngebuehren = ?, offener_betrag = ? WHERE id = ?
                        """, (aktuelle_mahnkosten, neuer_offener_betrag, invoice_id))
                        
                        log_audit_action(self.conn, 'MAHNUNG_GEBUEHR_VERBUCHT', invoice_id,
                                         f"Mahngebühren von {aktuelle_mahnkosten:.2f} € nach E-Mail-Versand verbucht. Neuer offener Betrag: {neuer_offener_betrag:.2f} €.",
                                         user=self.current_user)
                        self.conn.commit()
                    except sqlite3.Error as e:
                        logging.error(f"Fehler beim Aktualisieren der Mahngebühren nach E-Mail für Rng-ID {invoice_id}: {e}")
                        self.conn.rollback()

                self.load_overdue_invoices(self.entry_filter.get().strip())
            return True
        except Exception as e: 
            messagebox.showerror("SMTP Fehler",f"E-Mail konnte nicht gesendet werden:\n{e}",parent=parent_window)
            # ### GoBD-ÄNDERUNG ###: Fehlgeschlagenen Versand protokollieren
            if invoice_id:
                log_audit_action(self.conn, 'MAHNSCHREIBEN_VERSAND_FEHLER', invoice_id,
                                 f"Fehler beim E-Mail-Versand an {recipient}: {e}", user=self.current_user)
            return False
        finally:
            if server: server.quit()

if __name__ == "__main__":
    logging.info("=======================================")
    logging.info("Starte Mahnwesen (Tkinter GUI, GoBD)...")
    root = None; app = None
    try:
        root = ThemedTk()
        app = MahnToolApp(root)
        if hasattr(app,'conn') and app.conn:
            try: root.state('zoomed')
            except tk.TclError:
                try: w,h=root.maxsize();root.geometry(f'{w}x{h}+0+0')
                except Exception: pass
            root.mainloop()
        else: logging.critical("Anwendung nicht initialisiert (DB-Fehler?). Beende.")
    except Exception as main_e:
        logging.exception("Kritischer Fehler in der Anwendung:")
        try: 
            messagebox.showerror("Kritischer Fehler",f"Ein unerwarteter Fehler ist aufgetreten:\n{main_e}\n\nDie Anwendung wird beendet. Bitte prüfen Sie die Logdatei 'mahntool.log'.")
        except Exception as msg_e: 
            print(f"FATAL APP ERROR: {main_e}\n(Msgbox Error: {msg_e})",file=sys.stderr)
    finally:
        # ### GoBD-ÄNDERUNG ###: Sicherstellen, dass das Ende auch bei einem Crash geloggt wird, falls möglich.
        if app and app.conn:
             if not app.root.winfo_exists(): # Prüfen, ob Fenster schon weg ist (reguläres Schließen)
                 # Wurde bereits in on_closing() geloggt, also hier nicht noch einmal.
                 pass
             else: # Crash-Fall
                 log_audit_action(app.conn, 'ANWENDUNG_ABSTURZ', details=f"Anwendung unerwartet beendet.", user=app.current_user)
                 app.conn.close()

        if root and root.winfo_exists():
            try: root.destroy()
            except: pass
        logging.info("Anwendungsprozess endet.")
        sys.exit(1)