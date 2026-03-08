import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import sqlite3
import os
from datetime import datetime, timedelta
import subprocess # NEU: Für das Starten externer Prozesse
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas as pdf_canvas # Renamed to avoid conflict
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
import csv # ### GoBD-ÄNDERUNG ###: Für den CSV-Datenexport

# --- E-Mail Imports (bereits vorhanden) ---
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
# --- Ende E-Mail Imports ---

# Logging konfigurieren (Wird früh konfiguriert, damit auch die Tool-Prüfung geloggt wird)
logging.basicConfig(filename='unternehmens_app.log', level=logging.DEBUG, # DEBUG Level für detaillierte Analyse
                    format='%(asctime)s - %(levelname)s - %(module)s - %(funcName)s - %(lineno)d - %(message)s')




# --- NEUE FUNKTIONEN ZUM STARTEN DES EXTERNEN TOOLS ---

def _find_daten_schloss_tool():
    """Sucht nach der DatenSchloss-Anwendung im Skript-Verzeichnis."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    tool_name_base = "DatenSchloss"
    tool_exe_path = os.path.join(script_dir, f"{tool_name_base}.exe")
    tool_pyw_path = os.path.join(script_dir, f"{tool_name_base}.pyw")

    if os.path.exists(tool_exe_path):
        logging.info(f"DatenSchloss Tool gefunden (EXE): {tool_exe_path}")
        # Rückgabe als Liste für subprocess.run ist sicherer bei Pfaden mit Leerzeichen
        return [tool_exe_path]

    if os.path.exists(tool_pyw_path):
        # Finde den Python-Interpreter, der .pyw ausführen kann
        interpreter = sys.executable
        # Versuche, pythonw.exe auf Windows zu finden
        if sys.platform == "win32" and interpreter.lower().endswith("python.exe"):
             pythonw_interpreter = os.path.join(os.path.dirname(interpreter), "pythonw.exe")
             if os.path.exists(pythonw_interpreter):
                 interpreter = pythonw_interpreter
             else:
                 logging.warning(f"pythonw.exe nicht gefunden ({pythonw_interpreter}), verwende stattdessen {sys.executable} für .pyw")
        # Auf anderen Plattformen oder wenn pythonw.exe nicht gefunden, sys.executable verwenden

        logging.info(f"DatenSchloss Tool gefunden (PYW): {tool_pyw_path} (Interpreter: {interpreter})")
        return [interpreter, tool_pyw_path] # Command als Liste

    logging.warning("DatenSchloss Tool nicht gefunden (gesucht: .exe, .pyw im Skript-Verzeichnis).")
    return None

def _run_daten_schloss_startup():
    """Startet das DatenSchloss Tool vor der Hauptanwendung und wartet auf dessen Beendigung."""
    logging.info("Prüfe und starte DatenSchloss Tool (Startup)...")
    tool_command = _find_daten_schloss_tool()

    if tool_command:
        try:
            logging.info(f"Starte DatenSchloss Tool: {' '.join(tool_command)}")
            # subprocess.run blockiert und wartet. check=True wirft Exception bei non-zero Exit Code.
            # cwd setzen, falls das Tool relative Pfade erwartet
            process = subprocess.run(tool_command, check=True, cwd=os.path.dirname(os.path.abspath(__file__)), text=True, capture_output=True)
            logging.info(f"DatenSchloss Tool (Startup) erfolgreich beendet. Exit Code: {process.returncode}")
            return True # Erfolgreich gestartet und beendet
        except FileNotFoundError:
             # Dies sollte von _find_daten_schloss_tool abgefangen werden, aber zur Sicherheit
             logging.error(f"DatenSchloss Tool oder Interpreter nicht gefunden. Command: {' '.join(tool_command)}")
             messagebox.showerror("Fehler", "Das benötigte Tool 'DatenSchloss' wurde nicht gefunden oder kann nicht gestartet werden.\n\nBitte stellen Sie sicher, dass 'DatenSchloss.exe' oder 'DatenSchloss.pyw' im selben Verzeichnis wie die Anwendung liegt.")
             return False # Fehler, Hauptanwendung nicht starten
        except subprocess.CalledProcessError as e:
            logging.error(f"DatenSchloss Tool (Startup) beendet mit Fehler (Exit Code: {e.returncode}). Stderr:\n{e.stderr}\nStdout:\n{e.stdout}")
            messagebox.showerror("Fehler", f"Das Tool 'DatenSchloss' ist beim Start unerwartet beendet (Exit Code {e.returncode}).\n\nBitte prüfen Sie die Protokolle des Tools oder kontaktieren Sie den Support.\n\nAnwendung wird beendet.")
            return False # Fehler, Hauptanwendung nicht starten
        except Exception as e:
            logging.exception("Unerwarteter Fehler beim Starten des DatenSchloss Tools (Startup):")
            messagebox.showerror("Fehler", f"Ein unerwarteter Fehler ist beim Starten des Tools 'DatenSchloss' aufgetreten:\n{e}\n\nAnwendung wird beendet.")
            return False # Fehler, Hauptanwendung nicht starten
    else:
        # Tool nicht gefunden - basierend auf der Anforderung ist das ein kritischer Fehler
        logging.error("DatenSchloss Tool wurde nicht gefunden. Anwendung kann nicht gestartet werden.")
        messagebox.showerror("Fehler", "Das benötigte Tool 'DatenSchloss' (DatenSchloss.exe oder .pyw) wurde im Anwendungsverzeichnis nicht gefunden.\n\nAnwendung wird beendet.")
        return False # Fehler, Hauptanwendung nicht starten

def _run_daten_schloss_shutdown():
    """Startet das DatenSchloss Tool nach Beendigung der Hauptanwendung."""
    logging.info("Starte DatenSchloss Tool (Shutdown)...")
    tool_command = _find_daten_schloss_tool()

    if tool_command:
        try:
            logging.info(f"Starte DatenSchloss Tool: {' '.join(tool_command)}")
            # subprocess.Popen startet das Tool und kehrt sofort zurück.
            # subprocess.run wartet standardmäßig. Da wir hier nach mainloop sind und das Tool beendet werden soll,
            # warten wir darauf, dass es fertig ist. check=False, damit die Hauptanwendung sauber beendet wird,
            # auch wenn das Shutdown-Tool fehlschlägt.
            process = subprocess.run(tool_command, cwd=os.path.dirname(os.path.abspath(__file__)), text=True, capture_output=True)
            logging.info(f"DatenSchloss Tool (Shutdown) beendet. Exit Code: {process.returncode}")
            if process.returncode != 0:
                 logging.warning(f"DatenSchloss Tool (Shutdown) beendet mit Non-Zero Exit Code: {process.returncode}. Stderr:\n{process.stderr}\nStdout:\n{process.stdout}")
        except FileNotFoundError:
             logging.error(f"DatenSchloss Tool (Shutdown) nicht gefunden (oder Interpreter für .pyw): {' '.join(tool_command)}")
             # Optional: Meldung? Eher nicht nötig.
        except Exception as e:
            logging.exception("Unerwarteter Fehler beim Starten des DatenSchloss Tools (Shutdown):")
            # Optional: Meldung? Eher nicht nötig.
    else:
        logging.warning("DatenSchloss Tool nicht gefunden, kann nicht beim Beenden gestartet werden.")

# --- ENDE NEUE FUNKTIONEN ---


# --- AUFRUF DES STARTUP-TOOLS ---
# DIESER BLOCK WIRD ZUERST AUSGEFÜHRT (NACH IMPORTS & BASIS-LOGGING)
if not _run_daten_schloss_startup():
     # Wenn das Startup-Tool fehlschlägt oder nicht gefunden wird, beenden wir die Anwendung sofort.
     sys.exit(1)
# --- ENDE AUFRUF STARTUP-TOOL ---




# Verbindung zur Datenbank herstellen und Tabellen anlegen
def connect_db_static(db_path):
    conn = None
    try:
        # Timeout von Standard 5 Sekunden auf 15 Sekunden erhöhen (gegen "database is locked")
        conn = sqlite3.connect(db_path, timeout=15.0)
        cursor = conn.cursor()
        # Tabelle kunden (ERWEITERT um 'email' und 'titel_firma')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS kunden (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                vorname TEXT NOT NULL,
                titel_firma TEXT,
                geburtsdatum TEXT,
                strasse TEXT,
                hausnummer TEXT,
                plz TEXT,
                ort TEXT,
                telefon TEXT,
                email TEXT,
                zifferncode INTEGER UNIQUE,
                is_active INTEGER DEFAULT 1 -- ### GoBD-ÄNDERUNG ###: Für Deaktivierung statt Löschung
            )
        ''')
        # Tabelle kunden_dokumente (unverändert)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS kunden_dokumente (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kunde_id INTEGER,
                dokument_pfad TEXT NOT NULL,
                dateiname TEXT NOT NULL,
                FOREIGN KEY (kunde_id) REFERENCES kunden(id) ON DELETE CASCADE
            )
        ''') 
        # Tabelle rechnungen (ERWEITERT um is_finalized)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS rechnungen (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kunde_id INTEGER NOT NULL,
                rechnungsnummer TEXT UNIQUE NOT NULL,
                rechnungsdatum TEXT NOT NULL,
                faelligkeitsdatum TEXT,
                mwst_prozent REAL DEFAULT 19.0,
                summe_netto REAL,
                summe_mwst REAL,
                summe_brutto REAL,
                mahngebuehren REAL DEFAULT 0.0,
                offener_betrag REAL,
                status TEXT DEFAULT 'Entwurf', -- z.B. Entwurf, Offen, Bezahlt, Storniert, ...
                bemerkung TEXT,
                is_finalized INTEGER DEFAULT 0, -- ### GoBD-ÄNDERUNG ###: 0 für Entwurf, 1 für finalisiert/unveränderbar
                FOREIGN KEY (kunde_id) REFERENCES kunden(id) ON DELETE RESTRICT -- ### GoBD-ÄNDERUNG ###: Verhindert Löschen von Kunden mit Rechnungen auf DB-Ebene
            )
        ''')
        # Tabelle rechnungsposten (unverändert)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS rechnungsposten (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rechnung_id INTEGER NOT NULL,
                position INTEGER NOT NULL,
                artikelnummer TEXT,
                beschreibung TEXT NOT NULL,
                menge REAL NOT NULL,
                einheit TEXT,
                einzelpreis_netto REAL NOT NULL,
                gesamtpreis_netto REAL NOT NULL,
                FOREIGN KEY (rechnung_id) REFERENCES rechnungen(id) ON DELETE CASCADE
            )
        ''')
        # Tabelle artikel (unverändert)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS artikel (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                artikelnummer TEXT UNIQUE NOT NULL,
                beschreibung TEXT NOT NULL,
                einheit TEXT,
                einzelpreis_netto REAL DEFAULT 0.0,
                verfuegbar REAL DEFAULT 0.0
            )
        ''')
        
        # ### GoBD-ÄNDERUNG ###: Neue Tabelle für das Audit-Protokoll
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                user TEXT, -- Für zukünftige Multi-User-Systeme
                action TEXT NOT NULL, -- z.B. 'KUNDE_ERSTELLT', 'RECHNUNG_FINALISIERT'
                record_id INTEGER, -- ID des betroffenen Datensatzes (z.B. kunden.id, rechnungen.id)
                details TEXT -- Detaillierte Beschreibung der Änderung, z.B. "Feld 'strasse' geändert von 'A' zu 'B'"
            )
        ''')
        # ### Ende GoBD-ÄNDERUNG ###

        conn.commit()

        # --- Migrationen für bestehende Datenbanken (falls Spalten fehlen) ---
        def add_column_if_not_exists(table, column, definition):
            try:
                cursor.execute(f"SELECT {column} FROM {table} LIMIT 1")
            except sqlite3.OperationalError:
                try:
                    cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
                    conn.commit()
                    logging.info(f"Datenbank-Schema aktualisiert: Spalte '{column}' zur Tabelle '{table}' hinzugefügt.")
                except sqlite3.Error as e_alter:
                    logging.error(f"Konnte Tabelle '{table}' nicht um Spalte '{column}' erweitern: {e_alter}")
                    conn.rollback()

        add_column_if_not_exists("kunden", "email", "TEXT")
        add_column_if_not_exists("kunden", "titel_firma", "TEXT")
        add_column_if_not_exists("kunden", "is_active", "INTEGER DEFAULT 1")
        add_column_if_not_exists("artikel", "verfuegbar", "REAL DEFAULT 0.0")
        add_column_if_not_exists("artikel", "einzelpreis_netto", "REAL DEFAULT 0.0")
        add_column_if_not_exists("rechnungen", "mahngebuehren", "REAL DEFAULT 0.0")
        add_column_if_not_exists("rechnungen", "offener_betrag", "REAL")
        add_column_if_not_exists("rechnungen", "is_finalized", "INTEGER DEFAULT 0")

        # Initialisiere 'offener_betrag' für bestehende Rechnungen
        try:
            cursor.execute("UPDATE rechnungen SET offener_betrag = summe_brutto WHERE offener_betrag IS NULL")
            conn.commit()
        except sqlite3.Error:
            pass # Ignoriere Fehler, falls Spalte gerade erst hinzugefügt wurde

        # Indizes (unverändert bis auf neuen Artikel-Index)
        try:
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_zifferncode ON kunden(zifferncode)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_rechnungsnummer ON rechnungen(rechnungsnummer)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_artikelnummer ON artikel(artikelnummer)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp ON audit_log(timestamp)") # ### GoBD-ÄNDERUNG ###
            conn.commit()
        except sqlite3.Error as e:
            logging.warning(f"Konnte Indizes nicht erstellen (existieren evtl. schon): {e}")

        return conn
    except sqlite3.Error as e:
        logging.error(f"Fehler beim Verbinden oder Erstellen der Datenbank: {e}")
        if conn:
            conn.rollback()
        return None

# --- Hilfsfunktion zum Parsen von Zahlen (ROBUSTERE VERSION) ---
def parse_float(value_str, default=0.0):
    """Versucht, einen String (der '.' oder ',' als Dezimaltrennzeichen
       und optional den jeweils anderen als Tausendertrennzeichen enthalten kann)
       in einen Float zu parsen."""
    if isinstance(value_str, (int, float)): # Direkt zurückgeben, wenn schon Zahl
        return float(value_str)
    if not isinstance(value_str, str):
        value_str = str(value_str)
    value_str = value_str.strip()
    if not value_str:
        return default

    last_dot = value_str.rfind('.')
    last_comma = value_str.rfind(',')

    try:
        if last_comma != -1 and last_comma > last_dot:
            cleaned_str = value_str.replace('.', '').replace(',', '.')
            return float(cleaned_str)
        elif last_dot != -1 and last_dot > last_comma:
            cleaned_str = value_str.replace(',', '')
            return float(cleaned_str)
        else:
            # Letzter Versuch: Direkte Konvertierung
            return float(value_str.replace(',', '.')) # Sicherstellen, dass Komma als Punkt interpretiert wird, falls kein anderer Separator da ist
    except (ValueError, TypeError):
        logging.warning(f"Konnte '{value_str}' nicht in Float umwandeln.")
        return default


# --- Hauptanwendungsklasse ---
class UnternehmensApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Kundenverwaltung (GoBD-Version)") # Titel angepasst
        self.root.geometry("800x700")

        # Setzt das Fenster-Icon
        try:
            icon_path = os.path.join(os.path.dirname(__file__), 'app_icon.ico')
            if os.path.exists(icon_path):
                self.root.iconbitmap(default=icon_path)
                logging.info(f"Fenster-Icon gesetzt: {icon_path}")
            else:
                 logging.warning(f"Fenster-Icon-Datei nicht gefunden: {icon_path}. Das Standard-Tkinter-Icon wird verwendet.")
        except tk.TclError as e:
             logging.error(f"Fehler beim Setzen des Fenster-Icons (TclError): {e}")
        except Exception as e:
             logging.error(f"Unerwarteter Fehler beim Setzen des Fenster-Icons: {e}")

        # --- Standardwerte für Konfiguration ---
        self.db_path = "unternehmen_gobd.db" # Standardname geändert
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
        self.smtp_server = ""
        self.smtp_port = 587
        self.smtp_user = ""
        self.smtp_password = None
        self.smtp_encryption = "STARTTLS"

        self.next_invoice_number_suggestion = ""

        # --- Config laden ---
        config_needs_update = False
        config_dict = {}
        config_file_path = "config_gobd.txt" # Config-Datei umbenannt

        if os.path.exists(config_file_path):
            try:
                with open(config_file_path, "r", encoding='utf-8') as f:
                    for line in f:
                        if "=" in line:
                            key, value = line.strip().split("=", 1)
                            if key.startswith("company_"):
                                detail_key = key.split("company_", 1)[1]
                                self.company_details[detail_key] = value
                            else:
                                if key == 'smtp_password':
                                     pass 
                                else:
                                     config_dict[key] = value
            except Exception as e:
                logging.error(f"Fehler beim Lesen von {config_file_path} beim Start: {e}")
                messagebox.showwarning("Konfigurationsfehler", f"Fehler beim Lesen von {config_file_path}:\n{e}\nVerwende Standardeinstellungen.")
        else:
             config_needs_update = True

        self.db_path = config_dict.get('db_path', self.db_path)
        self.pdf_background_path = config_dict.get('pdf_background_path', self.pdf_background_path)
        self.current_theme = config_dict.get('theme', self.current_theme)
        self.document_base_path = config_dict.get('document_base_path', self.document_base_path)
        self.default_vat_rate = parse_float(config_dict.get('default_vat_rate', str(self.default_vat_rate)), 19.0)
        try: self.reminder_days = int(config_dict.get('reminder_days', self.reminder_days))
        except ValueError: logging.warning("Ungültiger Wert für reminder_days in config.txt, verwende Standard.")
        try: self.mahnung1_days = int(config_dict.get('mahnung1_days', self.mahnung1_days))
        except ValueError: logging.warning("Ungültiger Wert für mahnung1_days in config.txt, verwende Standard.")
        try: self.mahnung2_days = int(config_dict.get('mahnung2_days', self.mahnung2_days))
        except ValueError: logging.warning("Ungültiger Wert für mahnung2_days in config.txt, verwende Standard.")
        try: self.inkasso_days = int(config_dict.get('inkasso_days', self.inkasso_days))
        except ValueError: logging.warning("Ungültiger Wert für inkasso_days in config.txt, verwende Standard.")
        self.smtp_server = config_dict.get('smtp_server', self.smtp_server)
        try: self.smtp_port = int(config_dict.get('smtp_port', self.smtp_port))
        except ValueError: logging.warning("Ungültiger Wert für smtp_port in config.txt, verwende Standard.")
        self.smtp_user = config_dict.get('smtp_user', self.smtp_user)
        self.smtp_encryption = config_dict.get('smtp_encryption', self.smtp_encryption)


        config_keys_to_check = ['db_path', 'pdf_background_path', 'theme', 'document_base_path', 'default_vat_rate',
                                'reminder_days', 'mahnung1_days', 'mahnung2_days', 'inkasso_days', 'smtp_server', 'smtp_port', 'smtp_user', 'smtp_password', 'smtp_encryption']
        for key in config_keys_to_check:
            key_present_in_file = False
            if os.path.exists(config_file_path):
                try:
                    with open(config_file_path, "r", encoding='utf-8') as f_check:
                        if any(line.strip().startswith(key + "=") for line in f_check):
                            key_present_in_file = True
                except Exception: pass
            
            if not key_present_in_file:
                config_needs_update = True
                break

        if not config_needs_update:
             for key in self.company_details:
                config_key = f"company_{key}"
                company_key_present_in_file = False
                if os.path.exists(config_file_path):
                    try:
                        with open(config_file_path, "r", encoding='utf-8') as f:
                            if any(line.strip().startswith(config_key + "=") for line in f):
                                company_key_present_in_file = True
                    except Exception: pass
                if not company_key_present_in_file:
                    config_needs_update = True
                    break

        if config_needs_update:
            logging.info(f"Aktualisiere oder erstelle {config_file_path}...")
            all_settings = {
                'db_path': self.db_path, 'pdf_background_path': self.pdf_background_path, 'theme': self.current_theme,
                'document_base_path': self.document_base_path, 'default_vat_rate': self.default_vat_rate,
                'reminder_days': self.reminder_days, 'mahnung1_days': self.mahnung1_days, 'mahnung2_days': self.mahnung2_days, 'inkasso_days': self.inkasso_days,
                'smtp_server': self.smtp_server, 'smtp_port': self.smtp_port, 'smtp_user': self.smtp_user,
                'smtp_password': "",
                'smtp_encryption': self.smtp_encryption,
            }
            for key, value in self.company_details.items():
                all_settings[f'company_{key}'] = value

            try:
                with open(config_file_path, "w", encoding='utf-8') as f:
                    for key, value in all_settings.items():
                        f.write(f"{key}={value}\n")
                logging.info(f"{config_file_path} aktualisiert oder neu erstellt.")
            except Exception as e:
                 logging.error(f"Fehler beim Schreiben/Aktualisieren von {config_file_path}: {e}")
                 messagebox.showwarning("Konfigurationsfehler", f"{config_file_path} konnte nicht aktualisiert/geschrieben werden:\n{e}")

        try:
            self.available_themes = self.root.get_themes()
        except Exception as e:
            logging.error(f"Fehler beim Abrufen der verfügbaren Themes: {e}")
            self.available_themes = ['clam', 'alt', 'default', 'classic', 'breeze']

        if self.current_theme not in self.available_themes:
             logging.warning(f"Gespeichertes Theme '{self.current_theme}' nicht verfügbar. Verwende Standardtheme 'clam'.")
             self.current_theme = "clam"
             if "clam" not in self.available_themes:
                self.current_theme = self.available_themes[0] if self.available_themes else "default"

        try:
             self.root.set_theme(self.current_theme)
        except tk.TclError:
             logging.error(f"Konnte Theme '{self.current_theme}' nicht anwenden. Versuche Fallback 'clam'.")
             try:
                 self.current_theme = "clam"
                 if "clam" not in self.available_themes:
                     self.current_theme = self.available_themes[0] if self.available_themes else "default"
                 self.root.set_theme(self.current_theme)
                 self.save_setting("theme", self.current_theme)
             except Exception as theme_err:
                 logging.error(f"Auch Fallback-Theme konnte nicht geladen werden: {theme_err}")
                 messagebox.showerror("Theme Fehler", "Konnte weder das gespeicherte noch das Standard-Theme laden.")

        style = ttk.Style()
        style.map('Treeview', background=[('selected', 'SystemHighlight')], foreground=[('selected', 'SystemHighlightText')])
        logging.info("Styling für Treeview konfiguriert.")

        self.selected_customer_for_edit = None
        self.hands_free_zifferncode_search = tk.BooleanVar(value=True)
        self.show_inactive_customers = tk.BooleanVar(value=False) # ### GoBD-ÄNDERUNG ###

        self.conn = self.connect_db()
        if self.conn is None:
            messagebox.showerror("Fehler", "Die Datenbank konnte nicht geladen werden. Überprüfen Sie die Logdatei.")
            self.root.destroy() 
            return

        self.check_and_update_invoice_status()

        self.create_widgets() 
        self.create_menu()
        if not hasattr(self, 'update_next_invoice_number_suggestion'):
            self.update_next_invoice_number_suggestion = self._default_update_next_invoice_number_suggestion
        self.update_next_invoice_number_suggestion()

        self.tree.bind("<Button-3>", self.show_context_menu)
        self.tree.bind("<ButtonRelease-1>", self.on_customer_select)
        self.selected_customer_id = None
        logging.info(f"Kundenverwaltung gestartet. Theme: {self.current_theme}, Doku: {self.document_base_path}, MwSt: {self.default_vat_rate}%, Mahnfristen: E={self.reminder_days} M1={self.mahnung1_days} M2={self.mahnung2_days} I={self.inkasso_days}")

    # ### GoBD-ÄNDERUNG ###: Zentrale Funktion für Audit-Protokollierung
    def _log_audit_event(self, action, record_id=None, details=""):
        """Schreibt einen Eintrag in das Audit-Protokoll."""
        if not self.conn:
            logging.error(f"AUDIT LOG FEHLER: Keine DB-Verbindung. Aktion: {action}")
            return
        try:
            # Hier könnte der echte Benutzername stehen, wenn es ein Login-System gäbe
            user = "system" 
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
            
            cursor = self.conn.cursor()
            cursor.execute(
                "INSERT INTO audit_log (timestamp, user, action, record_id, details) VALUES (?, ?, ?, ?, ?)",
                (timestamp, user, action, record_id, details)
            )
            self.conn.commit()
            logging.info(f"AUDIT: {action} | Record ID: {record_id} | Details: {details}")
        except sqlite3.Error as e:
            logging.error(f"Fehler beim Schreiben ins Audit-Log: {e}")
            self.conn.rollback()

    # --- Hilfsfunktion zum Speichern einzelner Einstellungen ---
    def save_setting(self, key, value):
        config_file_path = "config_gobd.txt"
        lines = []
        found = False
        try:
            if os.path.exists(config_file_path):
                with open(config_file_path, "r", encoding='utf-8') as f:
                    lines = f.readlines()

            with open(config_file_path, "w", encoding='utf-8') as f:
                for line in lines:
                    stripped_line = line.strip()
                    if stripped_line.startswith(key + "=") or stripped_line.startswith(key + " ="): 
                        if key == 'smtp_password':
                             f.write(f"{key}=\n")
                        else:
                             f.write(f"{key}={value}\n")
                        found = True
                    elif line.strip(): 
                        f.write(line)
                if not found:
                     if key == 'smtp_password':
                          f.write(f"{key}=\n")
                     else:
                          f.write(f"{key}={value}\n")
            logging.info(f"Einstellung '{key}' in {config_file_path} gespeichert.")
            
            old_value = getattr(self, key, None)
            if key.startswith("company_"):
                detail_key = key.split("company_", 1)[1]
                old_value = self.company_details.get(detail_key)
            
            # GoBD: Protokollierung von Konfigurationsänderungen
            if str(old_value) != str(value) and not key == 'smtp_password':
                self._log_audit_event("KONFIG_GEAENDERT", details=f"Einstellung '{key}' geändert von '{old_value}' zu '{value}'")

            if hasattr(self, key):
                 if key == 'default_vat_rate':
                     setattr(self, key, parse_float(str(value), 19.0)) 
                 elif key in ['reminder_days', 'mahnung1_days', 'mahnung2_days', 'inkasso_days', 'smtp_port']:
                     try: setattr(self, key, int(str(value))) 
                     except ValueError: logging.warning(f"Ungültiger Integerwert beim Speichern für {key}: {value}")
                 elif key == 'smtp_password':
                      pass
                 elif key.startswith("company_"):
                      detail_key = key.split("company_", 1)[1]
                      if detail_key in self.company_details:
                          self.company_details[detail_key] = value
                 else:
                     setattr(self, key, value)
        except Exception as e:
            logging.error(f"Fehler beim Speichern der Einstellung '{key}' in {config_file_path}: {e}")
            messagebox.showerror("Fehler", f"Fehler beim Speichern der Einstellung '{key}': {e}", parent=self.root)


    # --- Menü und Einstellungsfenster (angepasst für GoBD) ---
    def create_menu(self):
        menubar = tk.Menu(self.root)
        
        # ### GoBD-ÄNDERUNG ###: Neues Menü für den Datenexport
        export_menu = tk.Menu(menubar, tearoff=0)
        export_menu.add_command(label="Kunden exportieren (CSV)...", command=lambda: self._export_table_to_csv('kunden'))
        export_menu.add_command(label="Rechnungen exportieren (CSV)...", command=lambda: self._export_table_to_csv('rechnungen'))
        export_menu.add_command(label="Rechnungsposten exportieren (CSV)...", command=lambda: self._export_table_to_csv('rechnungsposten'))
        export_menu.add_command(label="Artikel exportieren (CSV)...", command=lambda: self._export_table_to_csv('artikel'))
        export_menu.add_command(label="Protokoll (Audit-Log) exportieren (CSV)...", command=lambda: self._export_table_to_csv('audit_log'))
        menubar.add_cascade(label="Datenexport (GoBD)", menu=export_menu)

        settings_menu = tk.Menu(menubar, tearoff=0)
        settings_menu.add_command(label="Datenbankpfad ändern...", command=self.open_change_db_path_window)
        settings_menu.add_command(label="PDF Hintergrundbild ändern...", command=self.open_change_pdf_background_path_window)
        settings_menu.add_command(label="Basisordner Dokumente ändern...", command=self.open_change_document_base_path_window)
        settings_menu.add_command(label="Theme auswählen...", command=self.open_theme_selection_window)
        settings_menu.add_command(label="Firmendaten bearbeiten...", command=self.open_edit_company_details_window)
        settings_menu.add_command(label="Standard MwSt.-Satz ändern...", command=self.open_change_default_vat_window)
        settings_menu.add_command(label="Mahnfristen konfigurieren...", command=self.open_configure_dunning_window)
        settings_menu.add_command(label="E-Mail (SMTP) konfigurieren...", command=self.open_configure_smtp_window)
        settings_menu.add_separator()
        settings_menu.add_checkbutton(label="Hands-free Kundennr.-Suche", variable=self.hands_free_zifferncode_search)
        # ### GoBD-ÄNDERUNG ###: Checkbox, um inaktive Kunden anzuzeigen
        settings_menu.add_checkbutton(label="Inaktive Kunden anzeigen", variable=self.show_inactive_customers, command=self.load_customers)
        settings_menu.add_separator()
        settings_menu.add_command(label="Beenden", command=self.root.quit)
        menubar.add_cascade(label="Einstellungen", menu=settings_menu)

        info_menu = tk.Menu(menubar, tearoff=0)
        info_menu.add_command(label="Über Kundenverwaltung", command=self.open_about_window)
        menubar.add_cascade(label="Info", menu=info_menu)

        self.root.config(menu=menubar)

    # ### GoBD-ÄNDERUNG ###: Funktion zum Exportieren von Tabellen in CSV-Dateien
    def _export_table_to_csv(self, table_name):
        """Exportiert eine komplette Datenbanktabelle in eine CSV-Datei."""
        if not self.conn:
            messagebox.showerror("Fehler", "Keine Datenbankverbindung für den Export.", parent=self.root)
            return
        
        default_filename = f"export_{table_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        filepath = filedialog.asksaveasfilename(
            parent=self.root,
            title=f"Tabelle '{table_name}' exportieren als CSV",
            initialfile=default_filename,
            defaultextension=".csv",
            filetypes=[("CSV-Dateien", "*.csv"), ("Alle Dateien", "*.*")]
        )
        
        if not filepath:
            logging.info(f"CSV-Export für Tabelle '{table_name}' abgebrochen.")
            return

        try:
            cursor = self.conn.cursor()
            cursor.execute(f"SELECT * FROM {table_name}")
            
            headers = [description[0] for description in cursor.description]
            rows = cursor.fetchall()
            
            with open(filepath, 'w', newline='', encoding='utf-8-sig') as csvfile:
                # utf-8-sig stellt sicher, dass Excel Umlaute korrekt erkennt
                writer = csv.writer(csvfile, delimiter=';', quotechar='"', quoting=csv.QUOTE_MINIMAL)
                writer.writerow(headers)
                writer.writerows(rows)
            
            logging.info(f"Tabelle '{table_name}' erfolgreich nach '{filepath}' exportiert.")
            messagebox.showinfo("Export erfolgreich", f"Die Tabelle '{table_name}' wurde erfolgreich exportiert.", parent=self.root)
        except sqlite3.Error as e:
            logging.error(f"DB-Fehler beim Export der Tabelle '{table_name}': {e}")
            messagebox.showerror("DB-Fehler", f"Fehler beim Export der Tabelle '{table_name}':\n{e}", parent=self.root)
        except Exception as e:
            logging.exception(f"Allgemeiner Fehler beim Export der Tabelle '{table_name}':")
            messagebox.showerror("Export-Fehler", f"Ein unerwarteter Fehler ist beim Export aufgetreten:\n{e}", parent=self.root)

    def open_edit_company_details_window(self):
        details_window = tk.Toplevel(self.root)
        details_window.title("Firmendaten bearbeiten")
        details_window.transient(self.root); details_window.grab_set(); details_window.geometry("400x400")
        ttk.Label(details_window, text="Eigene Firmendaten für Rechnungs-PDFs:", font=("Arial", 10, "bold")).pack(pady=10)
        entries = {}; frame = ttk.Frame(details_window); frame.pack(fill=tk.X, padx=10, pady=5)
        detail_keys_ordered = ["name", "address", "zip_city", "phone", "email", "tax_id", "bank_details"]
        labels_german = {"name": "Firmenname:", "address": "Straße & Nr.:", "zip_city": "PLZ & Ort:", "phone": "Telefon:", "email": "E-Mail:", "tax_id": "Steuer-ID / USt-IdNr.:", "bank_details": "Bankverbindung (IBAN etc.):"}
        for i, key in enumerate(detail_keys_ordered):
            ttk.Label(frame, text=labels_german.get(key, key.replace("_", " ").title() + ":")).grid(row=i, column=0, sticky=tk.W, padx=5, pady=2)
            entry = ttk.Entry(frame, width=40); entry.grid(row=i, column=1, sticky=tk.EW, padx=5, pady=2); entry.insert(0, self.company_details.get(key, "")); entries[key] = entry
        frame.columnconfigure(1, weight=1)
        def save_details():
            for key, entry_widget in entries.items():
                 new_value = entry_widget.get().strip()
                 # GoBD: Änderungen werden in save_setting protokolliert
                 self.save_setting(f"company_{key}", new_value)
            messagebox.showinfo("Erfolg", "Firmendaten gespeichert.", parent=details_window); details_window.destroy()
        button_frame = ttk.Frame(details_window); button_frame.pack(pady=10)
        ttk.Button(button_frame, text="Speichern", command=save_details).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Abbrechen", command=details_window.destroy).pack(side=tk.LEFT, padx=5)

    def open_change_default_vat_window(self):
        vat_window = tk.Toplevel(self.root); vat_window.title("Standard MwSt.-Satz ändern"); vat_window.transient(self.root); vat_window.grab_set(); vat_window.geometry("300x150")
        ttk.Label(vat_window, text="Neuer Standard MwSt.-Satz (%):").pack(pady=10)
        vat_var = tk.StringVar(value=str(self.default_vat_rate).replace('.', ',')); entry_vat = ttk.Entry(vat_window, textvariable=vat_var, width=10); entry_vat.pack(pady=5)
        def save_vat():
            new_vat = parse_float(vat_var.get(), -1.0)
            if new_vat >= 0:
                self.save_setting("default_vat_rate", str(new_vat)); messagebox.showinfo("Erfolg", f"Standard MwSt.-Satz auf {new_vat:.2f}% geändert.", parent=vat_window); vat_window.destroy()
            else: messagebox.showwarning("Ungültige Eingabe", "Bitte gültigen Prozentsatz (Zahl >= 0) eingeben.", parent=vat_window)
        button_frame = ttk.Frame(vat_window); button_frame.pack(pady=10)
        ttk.Button(button_frame, text="Speichern", command=save_vat).pack(side=tk.LEFT, padx=5); ttk.Button(button_frame, text="Abbrechen", command=vat_window.destroy).pack(side=tk.LEFT, padx=5)

    def open_configure_dunning_window(self):
        dunning_window = tk.Toplevel(self.root)
        dunning_window.title("Mahnfristen konfigurieren (Tage überfällig)")
        dunning_window.transient(self.root)
        dunning_window.grab_set()
        dunning_window.resizable(False, False)

        frame = ttk.Frame(dunning_window, padding=10)
        frame.pack()

        labels_dunning = {
            "reminder_days": "Status 'Zur Erinnerung an' nach:",
            "mahnung1_days": "Status 'Zur Mahnung an' nach:",
            "mahnung2_days": "Status 'Zur Mahnung 2 an' nach:",
            "inkasso_days": "Status 'Bitte an Inkasso' nach:"
        }
        entries = {}
        for i, (key, label) in enumerate(labels_dunning.items()):
            ttk.Label(frame, text=label, anchor='w').grid(row=i, column=0, sticky=tk.W, pady=3)
            entry = ttk.Entry(frame, width=5)
            entry.grid(row=i, column=1, sticky=tk.W, pady=3)
            entry.insert(0, str(getattr(self, key, 0)))
            entries[key] = entry
        ttk.Label(frame, text="Tagen Überfälligkeit").grid(row=0, column=2, rowspan=len(labels_dunning), sticky='nsw', padx=(5,0))

        def save_dunning_settings():
            new_values = {}
            valid = True
            for key, entry_widget in entries.items():
                try:
                    value_str = entry_widget.get().strip()
                    value = int(value_str)
                    if value < 0:
                        raise ValueError("Negative Zahl nicht erlaubt")
                    new_values[key] = value
                except ValueError as ve:
                    logging.warning(f"Ungültige Eingabe für Mahnfrist '{key}': '{entry_widget.get().strip()}' ({ve})")
                    messagebox.showerror("Ungültige Eingabe",
                                         f"Bitte geben Sie eine gültige, nicht-negative ganze Zahl für '{labels_dunning[key]}' ein.",
                                         parent=dunning_window)
                    valid = False
                    break
            if valid:
                if not (new_values['reminder_days'] <= new_values['mahnung1_days'] <= new_values['mahnung2_days'] <= new_values['inkasso_days']):
                     if not messagebox.askyesno("Warnung",
                                                "Die Fristen sind nicht aufsteigend. Trotzdem speichern?",
                                                icon=messagebox.WARNING, parent=dunning_window):
                          return 
                for key, value in new_values.items():
                    # GoBD: Änderungen werden in save_setting protokolliert
                    self.save_setting(key, str(value))
                messagebox.showinfo("Erfolg", "Mahnfristen gespeichert.", parent=dunning_window)
                logging.info(f"Mahnfristen aktualisiert: E={self.reminder_days} M1={self.mahnung1_days} M2={self.mahnung2_days} I={self.inkasso_days}")
                dunning_window.destroy()

        button_frame = ttk.Frame(dunning_window)
        button_frame.pack(pady=10)
        ttk.Button(button_frame, text="Speichern", command=save_dunning_settings).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Abbrechen", command=dunning_window.destroy).pack(side=tk.LEFT, padx=5)

    def open_configure_smtp_window(self):
        smtp_window = tk.Toplevel(self.root); smtp_window.title("E-Mail (SMTP) konfigurieren"); smtp_window.transient(self.root); smtp_window.grab_set(); smtp_window.resizable(False, False)
        frame = ttk.Frame(smtp_window, padding=10); frame.pack(fill=tk.BOTH, expand=True)

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
        if self.smtp_encryption in combo_encryption['values']:
            combo_encryption.set(self.smtp_encryption)
        else:
            combo_encryption.set('STARTTLS') 

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
            password_entered = smtp_password_var.get()
            encryption = combo_encryption.get()
            try:
                port = int(port_str)
                if not (0 < port < 65536): raise ValueError("Port außerhalb des gültigen Bereichs")
            except ValueError:
                messagebox.showerror("Ungültiger Port", "Bitte geben Sie eine gültige Portnummer (1-65535) ein.", parent=smtp_window)
                return

            self.save_setting('smtp_server', server)
            self.save_setting('smtp_port', str(port))
            self.save_setting('smtp_user', user)
            self.save_setting('smtp_encryption', encryption)
            self.smtp_password = password_entered 
            self.save_setting('smtp_password', "") 

            messagebox.showinfo("Erfolg", "SMTP-Einstellungen gespeichert.", parent=smtp_window)
            logging.info(f"SMTP-Einstellungen aktualisiert (Server: {server}, Port: {port}, User: {user}, Encryption: {encryption}). Passwort wird nicht persistent gespeichert.")
            smtp_window.destroy()

        button_frame = ttk.Frame(smtp_window)
        button_frame.pack(pady=10)
        ttk.Button(button_frame, text="Speichern", command=save_smtp_settings).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Abbrechen", command=smtp_window.destroy).pack(side=tk.LEFT, padx=5)

    def open_about_window(self):
        about_window = tk.Toplevel(self.root); about_window.title("Über Kundenverwaltung"); about_window.resizable(False, False); about_window.transient(self.root); about_window.grab_set()
        version_info = "Version: 6.0.0.0 (GoBD-konforme Überarbeitung)"; manufacturer_info = "Hersteller: innowise IT Manuel Person"; support_contact = "Supportkontakt: manuel.person@outlook.de" 
        ttk.Label(about_window, text="Kundenverwaltung", font=("Arial", 12, "bold")).pack(padx=10, pady=10); ttk.Label(about_window, text=version_info).pack(padx=10, pady=5); ttk.Label(about_window, text=manufacturer_info).pack(padx=10, pady=5); ttk.Label(about_window, text=support_contact).pack(padx=10, pady=5); ttk.Label(about_window, text="© 2025 Alle Rechte vorbehalten.").pack(padx=10, pady=10); close_button = ttk.Button(about_window, text="Schließen", command=about_window.destroy); close_button.pack(pady=10)

    def open_theme_selection_window(self):
        theme_window = tk.Toplevel(self.root); theme_window.title("Theme auswählen"); theme_window.transient(self.root); theme_window.grab_set()
        ttk.Label(theme_window, text="Wählen Sie ein Theme:").pack(padx=10, pady=10); theme_var = tk.StringVar(theme_window, value=self.current_theme); theme_combobox = ttk.Combobox(theme_window, textvariable=theme_var, values=self.available_themes, state="readonly"); theme_combobox.pack(padx=10, pady=5)
        def apply_selected_theme():
            selected_theme = theme_var.get()
            try: self.root.set_theme(selected_theme); self.save_setting("theme", selected_theme); messagebox.showinfo("Info", f"Theme auf '{selected_theme}' geändert.", parent=theme_window); theme_window.destroy()
            except tk.TclError as e: messagebox.showerror("Fehler", f"Konnte Theme '{selected_theme}' nicht laden:\n{e}", parent=theme_window); logging.error(f"Fehler beim Anwenden des Themes '{selected_theme}': {e}")
        apply_button = ttk.Button(theme_window, text="Anwenden & Speichern", command=apply_selected_theme); apply_button.pack(pady=10); cancel_button = ttk.Button(theme_window, text="Abbrechen", command=theme_window.destroy); cancel_button.pack(pady=5)

    def open_change_pdf_background_path_window(self):
        change_path_window = tk.Toplevel(self.root)
        change_path_window.title("PDF Hintergrundbild ändern")
        change_path_window.transient(self.root)
        change_path_window.grab_set()

        ttk.Label(change_path_window, text="Neuer Pfad zum Hintergrundbild (für A4 PDFs):").pack(padx=10, pady=10)
        entry_new_pdf_background_path = ttk.Entry(change_path_window, width=40)
        entry_new_pdf_background_path.pack(padx=10, pady=5)
        entry_new_pdf_background_path.insert(0, self.pdf_background_path)

        def browse_path():
            file_path = filedialog.askopenfilename(
                parent=change_path_window,
                title="PDF Hintergrundbild auswählen",
                filetypes=[("Bilddateien", "*.png;*.jpg;*.jpeg;*.gif"), ("Alle Dateien", "*.*")]
            )
            if file_path:
                entry_new_pdf_background_path.delete(0, tk.END)
                entry_new_pdf_background_path.insert(0, file_path)

        def save_path():
            new_path = entry_new_pdf_background_path.get().strip()
            if new_path and not os.path.exists(new_path):
                if not messagebox.askyesno("Warnung", f"Datei '{os.path.basename(new_path)}' nicht gefunden.\nTrotzdem speichern?", parent=change_path_window):
                    return
            self.save_setting("pdf_background_path", new_path)
            messagebox.showinfo("Erfolg", "PDF Hintergrundbildpfad gespeichert.", parent=change_path_window)
            change_path_window.destroy()

        btn_browse = ttk.Button(change_path_window, text="Durchsuchen...", command=browse_path)
        btn_browse.pack(pady=5)
        btn_save = ttk.Button(change_path_window, text="Speichern", command=save_path)
        btn_save.pack(pady=10)
        btn_cancel = ttk.Button(change_path_window, text="Abbrechen", command=change_path_window.destroy)
        btn_cancel.pack(pady=5)

    def connect_db(self):
        conn = connect_db_static(self.db_path)
        if conn is None: logging.error(f"Verbindung zur DB unter '{self.db_path}' fehlgeschlagen.")
        else: logging.info(f"Erfolgreich mit DB unter '{self.db_path}' verbunden.")
        return conn

    def open_change_document_base_path_window(self):
        change_path_window = tk.Toplevel(self.root)
        change_path_window.title("Basisordner für Kundendokumente ändern")
        change_path_window.transient(self.root)
        change_path_window.grab_set()

        ttk.Label(change_path_window, text="Neuer Basisordner:\n(Unterordner 'Kundendokumente' wird darin angelegt)").pack(padx=10, pady=10)
        entry_new_document_base_path = ttk.Entry(change_path_window, width=50)
        entry_new_document_base_path.pack(padx=10, pady=5)
        entry_new_document_base_path.insert(0, self.document_base_path)

        def browse_path():
            folder_path = filedialog.askdirectory(
                parent=change_path_window,
                title="Basisordner auswählen",
                initialdir=os.path.dirname(self.document_base_path or os.path.expanduser("~"))
            )
            if folder_path:
                entry_new_document_base_path.delete(0, tk.END)
                entry_new_document_base_path.insert(0, folder_path)

        def save_path():
            new_path = entry_new_document_base_path.get().strip()
            if not new_path:
                messagebox.showwarning("Warnung", "Pfad darf nicht leer sein.", parent=change_path_window)
                return
            if not os.path.isdir(new_path) or not os.access(new_path, os.W_OK):
                messagebox.showerror("Fehler", f"Pfad ungültig oder nicht beschreibbar:\n{new_path}", parent=change_path_window)
                logging.error(f"Dokumenten-Basisordner '{new_path}' ungültig/nicht beschreibbar.")
                return
            self.save_setting("document_base_path", new_path)
            messagebox.showinfo("Erfolg", "Basisordner gespeichert.", parent=change_path_window)
            change_path_window.destroy()

        btn_browse = ttk.Button(change_path_window, text="Ordner auswählen...", command=browse_path)
        btn_browse.pack(pady=5)
        btn_save = ttk.Button(change_path_window, text="Speichern", command=save_path)
        btn_save.pack(pady=10)
        btn_cancel = ttk.Button(change_path_window, text="Abbrechen", command=change_path_window.destroy)
        btn_cancel.pack(pady=5)

    def create_customer_document_folder(self, customer_id, zifferncode):
        if not self.document_base_path: logging.warning(f"Dokumenten-Basisordner nicht gesetzt. Ordner für Kunde ID {customer_id} (Code {zifferncode}) nicht erstellt."); return None
        main_docs_dir = os.path.join(self.document_base_path, "Kundendokumente"); customer_dir = os.path.join(main_docs_dir, str(zifferncode))
        try: os.makedirs(customer_dir, exist_ok=True); logging.info(f"Kundenordner für ID {customer_id} (Code {zifferncode}) erstellt/existiert: {customer_dir}"); return customer_dir
        except OSError as e: logging.error(f"Fehler beim Erstellen des Kundenordners für ID {customer_id} (Code {zifferncode}) unter '{customer_dir}': {e}"); messagebox.showerror("Ordner Fehler", f"Konnte Ordner für Kunde {zifferncode} nicht erstellen:\n{customer_dir}\nFehler: {e}", parent=self.root); return None


    def create_widgets(self):
        try:
            logo_file_path = os.path.join(os.path.dirname(__file__), "logo.png")
            self.logo_image = tk.PhotoImage(file=logo_file_path); 
            logo_label = ttk.Label(self.root, image=self.logo_image); 
            logo_label.pack(side=tk.TOP, anchor=tk.NW, padx=10, pady=10); 
            logging.info(f"Logo '{logo_file_path}' geladen.")
        except tk.TclError: 
            logging.warning(f"Logo-Datei '{logo_file_path}' nicht gefunden oder ungültig."); 
            ttk.Label(self.root, text="[Logo nicht gefunden]").pack(side=tk.TOP, anchor=tk.NW, padx=10, pady=10)
        except Exception as e: 
            logging.error(f"Fehler beim Laden des Logos '{logo_file_path}': {e}"); 
            ttk.Label(self.root, text="[Logo Fehler]").pack(side=tk.TOP, anchor=tk.NW, padx=10, pady=10)

        ttk.Label(self.root, text="Kundenverwaltung", font=("Arial", 20, "bold")).pack(pady=5)

        search_frame = ttk.Frame(self.root); search_frame.pack(pady=5, padx=10)
        ttk.Label(search_frame, text="Suche:").pack(side=tk.LEFT); self.entry_search = ttk.Entry(search_frame, width=20); self.entry_search.pack(side=tk.LEFT, padx=5)
        ttk.Button(search_frame, text="Suchen", command=self.search_customers).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(search_frame, text="Kundennr.:").pack(side=tk.LEFT, padx=(10, 0)); self.entry_zifferncode_search = ttk.Entry(search_frame, width=10); self.entry_zifferncode_search.pack(side=tk.LEFT, padx=5)
        ttk.Button(search_frame, text="Nr. Suchen", command=self.search_customers_by_zifferncode).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(search_frame, text="Alle anzeigen", command=self.load_customers).pack(side=tk.LEFT, padx=5)

        self.frame_kunde_eingabe = ttk.Frame(self.root); self.frame_kunde_eingabe.pack(pady=10)
        labels_kunden = [
            "Titel / Firma:", "Name:", "Vorname:", "Geburtsdatum (TT.MM.JJJJ):",
            "Straße:", "Hausnummer:", "PLZ:", "Ort:", "Telefon:", "E-Mail:"
        ]
        self.entries_kunden = {}
        for i, label_text in enumerate(labels_kunden):
            ttk.Label(self.frame_kunde_eingabe, text=label_text).grid(row=i, column=0, sticky=tk.E, padx=5, pady=2)
            entry = ttk.Entry(self.frame_kunde_eingabe, width=40)
            entry.grid(row=i, column=1, sticky=tk.EW, padx=5, pady=2)
            self.entries_kunden[label_text] = entry

        self.btn_save_kunde = ttk.Button(self.root, text="Kunde speichern", command=self.save_customer, width=20); self.btn_save_kunde.pack(pady=10)
        ttk.Button(self.root, text="Felder leeren", command=self.clear_customer_fields, width=20).pack(pady=5)
        # ### GoBD-ÄNDERUNG ###: Text des Buttons geändert, um die neue Funktion widerzuspiegeln
        self.btn_delete_customer = ttk.Button(self.root, text="Kunde deaktivieren", command=self.delete_customer, width=20);
        self.btn_delete_customer.pack(pady=5)

        tree_frame = ttk.Frame(self.root); tree_frame.pack(pady=10, padx=10, fill=tk.BOTH, expand=True)
        columns_kunden = ("ID", "Kundennr.", "Name", "Vorname", "Titel / Firma", "Geburtsdatum", "Straße", "Hausnummer", "PLZ", "Ort", "Telefon", "E-Mail", "Status") # ### GoBD-ÄNDERUNG ###: Spalte Status
        self.tree = ttk.Treeview(tree_frame, columns=columns_kunden, show="headings")
        self.tree.tag_configure('inaktiv', foreground='grey') # ### GoBD-ÄNDERUNG ###: Style für inaktive Kunden
        for col in self.tree["columns"]:
            self.tree.heading(col, text=col, command=lambda _col=col: self.sort_treeview_column(_col, False))
            w=120; s=tk.YES; a=tk.W
            if col == "ID": w=40; s=tk.NO; a=tk.E
            elif col == "Kundennr.": w=80; s=tk.NO; a=tk.E
            elif col == "Geburtsdatum": w=100; s=tk.NO
            elif col == "E-Mail": w = 180 
            elif col == "Titel / Firma": w = 150 
            elif col in ["Straße", "Ort"]: w=150
            elif col in ["Hausnummer", "PLZ", "Status"]: w=80; s=tk.NO # ### GoBD-ÄNDERUNG ###: Spalte Status Breite
            self.tree.column(col, width=w, stretch=s, anchor=a)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set); scrollbar.pack(side="right", fill="y")

        self.tree.bind("<Double-1>", self.on_customer_double_click)
        self.entry_zifferncode_search.bind("<Return>", self.zifferncode_search_enter_pressed)
        self.entry_search.bind("<Return>", self.fulltext_search_enter_pressed)

        self.load_customers()

    def sort_treeview_column(self, col, reverse):
        try:
            data_list = [(self.tree.set(k, col), k) for k in self.tree.get_children('')]
            is_numeric = col in ["ID", "Kundennr."]
            if is_numeric:
                try: data_list.sort(key=lambda t: int(t[0] if t[0] else 0), reverse=reverse)
                except ValueError: data_list.sort(key=lambda t: str(t[0]).lower() if t[0] else '', reverse=reverse)
            else: data_list.sort(key=lambda t: str(t[0]).lower() if t[0] else '', reverse=reverse)
            for index, (val, k) in enumerate(data_list): self.tree.move(k, '', index)
            self.tree.heading(col, command=lambda _col=col: self.sort_treeview_column(_col, not reverse))
        except Exception as e: logging.error(f"Fehler beim Sortieren der Spalte '{col}': {e}"); messagebox.showerror("Sortierfehler", f"Spalte '{col}' konnte nicht sortiert werden.", parent=self.root)

    def on_customer_select(self, event):
        selected_item = self.tree.focus()
        if selected_item:
            try: 
                customer_id_str = self.tree.item(selected_item)["values"][0]
                customer_id = int(customer_id_str)
                self.load_customer_data_for_edit(customer_id)
                self.selected_customer_for_edit = customer_id
                self.btn_save_kunde.config(text="Änderungen speichern")
            except (IndexError, KeyError, TypeError, ValueError): 
                logging.warning("Fehler beim Abrufen der Kunden-ID aus Treeview-Auswahl.")
                self.clear_customer_fields()
            except Exception as e: 
                logging.error(f"Fehler in on_customer_select: {e}")
                self.clear_customer_fields()
        else:
            if not self.tree.selection(): 
                self.clear_customer_fields()


    def load_customer_data_for_edit(self, customer_id):
        if not self.conn: return
        cursor = self.conn.cursor()
        try:
            # ### GoBD-ÄNDERUNG ###: is_active wird mit abgefragt, um den Button-Text zu ändern
            cursor.execute("SELECT name, vorname, titel_firma, geburtsdatum, strasse, hausnummer, plz, ort, telefon, email, is_active FROM kunden WHERE id=?", (customer_id,))
            customer_data = cursor.fetchone()
            if customer_data:
                self.clear_customer_fields()
                (name, vorname, titel, geb, strasse, hnr, plz, ort, tel, email, is_active) = customer_data
                self.entries_kunden["Name:"].insert(0, name or "")
                self.entries_kunden["Vorname:"].insert(0, vorname or "")
                self.entries_kunden["Titel / Firma:"].insert(0, titel or "")
                self.entries_kunden["Geburtsdatum (TT.MM.JJJJ):"].insert(0, geb or "")
                self.entries_kunden["Straße:"].insert(0, strasse or "")
                self.entries_kunden["Hausnummer:"].insert(0, hnr or "")
                self.entries_kunden["PLZ:"].insert(0, plz or "")
                self.entries_kunden["Ort:"].insert(0, ort or "")
                self.entries_kunden["Telefon:"].insert(0, tel or "")
                self.entries_kunden["E-Mail:"].insert(0, email or "")
                
                # ### GoBD-ÄNDERUNG ###: Button-Text anpassen
                if is_active:
                    self.btn_delete_customer.config(text="Kunde deaktivieren")
                else:
                    self.btn_delete_customer.config(text="Kunde reaktivieren")

                logging.info(f"Kundendaten für ID {customer_id} zum Bearbeiten geladen.")
                self.select_customer_in_tree(customer_id)
                self.selected_customer_for_edit = customer_id
                self.btn_save_kunde.config(text="Änderungen speichern")
            else: 
                logging.warning(f"Kunde mit ID {customer_id} nicht gefunden zum Laden."); 
                self.clear_customer_fields(); 
                messagebox.showwarning("Fehler", f"Kunde mit ID {customer_id} nicht gefunden.", parent=self.root)
        except sqlite3.Error as e: 
            messagebox.showerror("Fehler", f"DB-Fehler beim Laden der Kundendaten: {e}", parent=self.root); 
            logging.error(f"DB-Fehler beim Laden der Kundendaten für ID {customer_id}: {e}")
        except Exception as e: 
            messagebox.showerror("Fehler", f"Allg. Fehler beim Laden der Kundendaten: {e}", parent=self.root); 
            logging.exception(f"Allg. Fehler beim Laden der Kundendaten für ID {customer_id}:")

    def show_context_menu(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item); self.tree.focus(item)
            try:
                values = self.tree.item(item)["values"]
                if values and len(values) > 4:
                    self.selected_customer_id = int(values[0])
                    customer_name_parts = [values[3], values[2]] 
                    if values[4]: 
                        customer_name_parts.append(f"({values[4]})") 
                    customer_name = " ".join(part for part in customer_name_parts if part)
                    is_active = values[-1] == "Aktiv" # ### GoBD-ÄNDERUNG ###

                    context_menu = tk.Menu(self.root, tearoff=0)
                    context_menu.add_command(label=f"Neue Rechnung für {customer_name}", command=lambda: self.open_rechnungs_window(self.selected_customer_id, create_new=True), state=tk.NORMAL if is_active else tk.DISABLED)
                    context_menu.add_command(label=f"Rechnungen anzeigen für {customer_name}", command=lambda: self.open_rechnungs_window(self.selected_customer_id))
                    context_menu.add_separator()
                    context_menu.add_command(label="Dokument zuordnen", command=self.assign_document_to_customer, state=tk.NORMAL if is_active else tk.DISABLED)
                    context_menu.add_command(label="Dokumente anzeigen", command=self.show_customer_documents)
                    context_menu.add_separator()
                    context_menu.add_command(label="Kunde bearbeiten", command=lambda: self.load_customer_data_for_edit(self.selected_customer_id))
                    # ### GoBD-ÄNDERUNG ###: Menütext anpassen
                    if is_active:
                        context_menu.add_command(label="Kunde deaktivieren", command=self.delete_customer)
                    else:
                        context_menu.add_command(label="Kunde reaktivieren", command=self.delete_customer)
                    context_menu.post(event.x_root, event.y_root)
                else: 
                    logging.warning("Kontextmenü: Item hat nicht genügend Werte."); self.selected_customer_id = None
            except (IndexError, KeyError, TypeError, ValueError) as e: 
                logging.warning(f"Fehler im Kontextmenü - Kundendaten nicht abrufbar: {e}"); self.selected_customer_id = None
            except Exception as e: 
                logging.error(f"Fehler im Kontextmenü: {e}"); self.selected_customer_id = None
        else: self.selected_customer_id = None

    def assign_document_to_customer(self): 
        customer_id_for_doc = None
        if self.selected_customer_id is not None:
            customer_id_for_doc = self.selected_customer_id
        else:
            selected_item = self.tree.focus()
            if selected_item:
                 try: 
                     customer_id_for_doc = int(self.tree.item(selected_item)["values"][0])
                     self.selected_customer_id = customer_id_for_doc
                 except (IndexError, KeyError, TypeError, ValueError): 
                     messagebox.showwarning("Warnung", "Kunden auswählen oder gültigen Kunden selektieren.", parent=self.root); return
            else: 
                messagebox.showwarning("Warnung", "Kunden auswählen.", parent=self.root); return
        
        if customer_id_for_doc is None:
            messagebox.showwarning("Warnung", "Konnte Kunden-ID nicht ermitteln.", parent=self.root); return

        if not self.document_base_path: 
            messagebox.showwarning("Konfigurationsfehler", "Basisordner für Dokumente nicht konfiguriert.", parent=self.root); 
            logging.warning("Doku-Zuordnung: Basisordner fehlt."); return
        
        if not self.conn: return
        cursor = self.conn.cursor()
        try:
            cursor.execute("SELECT zifferncode, name, vorname FROM kunden WHERE id=?", (customer_id_for_doc,)); kunde_data = cursor.fetchone()
            if not kunde_data: 
                messagebox.showerror("Fehler", f"Kunde ID {customer_id_for_doc} nicht gefunden.", parent=self.root); 
                logging.error(f"Kunde ID {customer_id_for_doc} für Doku nicht gefunden."); return
            zifferncode, kunde_name, kunde_vorname = kunde_data
            if zifferncode is None: 
                messagebox.showwarning("Warnung", f"Kunde '{kunde_vorname} {kunde_name}' hat keine Kundennr.", parent=self.root); 
                logging.warning(f"Doku-Zuordnung: Kunde ID {customer_id_for_doc} ohne Zifferncode."); return
            
            customer_docs_dir = self.create_customer_document_folder(customer_id_for_doc, zifferncode)
            if not customer_docs_dir: return

        except sqlite3.Error as e: 
            messagebox.showerror("DB Fehler", f"Fehler beim Abruf der Kundennr. (ID {customer_id_for_doc}):\n{e}", parent=self.root); 
            logging.error(f"DB-Fehler Abruf Zifferncode Kunde ID {customer_id_for_doc}: {e}"); return
        except Exception as e: 
            messagebox.showerror("Systemfehler", f"Unerwarteter Fehler:\n{e}", parent=self.root); 
            logging.exception(f"Unerwarteter Fehler Doku-Zuordnung Kunde ID {customer_id_for_doc}:"); return
        
        source_file_path = filedialog.askopenfilename(title=f"Dokument für Kunde {zifferncode} auswählen", initialdir=os.path.expanduser("~"), parent=self.root)
        if not source_file_path: logging.info("Dokumentenauswahl abgebrochen."); return
        
        original_file_name = os.path.basename(source_file_path); 
        destination_file_name = original_file_name; 
        destination_path = os.path.join(customer_docs_dir, destination_file_name)
        counter = 1; name, ext = os.path.splitext(original_file_name)
        while os.path.exists(destination_path):
            destination_file_name = f"{name}_{counter}{ext}"; 
            destination_path = os.path.join(customer_docs_dir, destination_file_name); 
            counter += 1
            if counter > 100: 
                messagebox.showerror("Fehler", f"Zu viele Kopien von '{original_file_name}'.", parent=self.root); 
                logging.error(f"Zu viele Kopien von '{original_file_name}' in '{customer_docs_dir}'."); return
        try:
            shutil.copy(source_file_path, destination_path); 
            logging.info(f"Doku kopiert: '{source_file_path}' -> '{destination_path}'.")
            cursor.execute("INSERT INTO kunden_dokumente (kunde_id, dokument_pfad, dateiname) VALUES (?, ?, ?)", (customer_id_for_doc, destination_path, destination_file_name))
            self.conn.commit();
            # ### GoBD-ÄNDERUNG ###: Protokollierung der Dokumentzuordnung
            self._log_audit_event("DOKUMENT_ZUGEORDNET", record_id=customer_id_for_doc, details=f"Datei '{destination_file_name}' wurde dem Kunden zugeordnet.")
            messagebox.showinfo("Erfolg", f"Dokument '{original_file_name}' als '{destination_file_name}' zu Kunde {zifferncode} zugeordnet.", parent=self.root)
            logging.info(f"Doku '{destination_file_name}' in DB für Kunde ID {customer_id_for_doc} gespeichert.")
        except shutil.Error as e: 
            messagebox.showerror("Kopierfehler", f"Fehler beim Kopieren:\n{e}", parent=self.root); 
            logging.error(f"Fehler Kopieren '{source_file_path}' -> '{destination_path}': {e}")
        except sqlite3.Error as e: 
            messagebox.showerror("DB Fehler", f"Fehler beim Speichern des Doku-Pfads:\n{e}", parent=self.root); 
            logging.error(f"DB-Fehler Speichern Pfad '{destination_path}' Kunde ID {customer_id_for_doc}: {e}"); 
            logging.warning(f"Doku evtl. kopiert ('{destination_path}'), DB-Eintrag fehlgeschlagen."); 
            self.conn.rollback()
        except Exception as e: 
            messagebox.showerror("Allg. Fehler", f"Unerwarteter Fehler:\n{e}", parent=self.root); 
            logging.exception(f"Unerwarteter Fehler in assign_document_to_customer Kunde ID {customer_id_for_doc}:"); 
            self.conn.rollback()


    def show_customer_documents(self):
        # ... (Diese Funktion bleibt im Wesentlichen unverändert, da sie nur anzeigt)
        # ... (Eine kleine Anpassung: Löschen von Dokumenten wird nun auch protokolliert)
        customer_id_for_show = None
        if self.selected_customer_id is not None:
             customer_id_for_show = self.selected_customer_id
        else:
             selected_item = self.tree.focus()
             if selected_item:
                 try: 
                     customer_id_for_show = int(self.tree.item(selected_item)["values"][0])
                     self.selected_customer_id = customer_id_for_show
                 except (IndexError, KeyError, TypeError, ValueError): 
                     messagebox.showwarning("Warnung", "Kunden auswählen oder gültigen Kunden selektieren.", parent=self.root); return
             else: 
                 messagebox.showwarning("Warnung", "Kunden auswählen.", parent=self.root); return
        
        if customer_id_for_show is None:
            messagebox.showwarning("Warnung", "Konnte Kunden-ID nicht ermitteln.", parent=self.root); return

        documents_window = tk.Toplevel(self.root)
        documents_window.title(f"Dokumente für Kunde ID: {customer_id_for_show}")
        documents_window.geometry("600x450"); 
        documents_window.transient(self.root); documents_window.grab_set()

        if not self.conn: return
        cursor = self.conn.cursor()
        try:
             cursor.execute("SELECT vorname, name, titel_firma, zifferncode FROM kunden WHERE id=?", (customer_id_for_show,)); kunde = cursor.fetchone()
             if kunde:
                 name_parts = [kunde[0], kunde[1]] 
                 if kunde[2]: name_parts.append(f"({kunde[2]})")
                 customer_display_name = " ".join(part for part in name_parts if part)
                 ttk.Label(documents_window, text=f"Kunde: {customer_display_name} (Nr: {kunde[3] or 'N/A'})").pack(padx=10, pady=5)
        except Exception as e: logging.error(f"Fehler Abruf Kundenname für Doku-Fenster: {e}")
        
        doc_frame = ttk.Frame(documents_window); doc_frame.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)
        listbox_docs = tk.Listbox(doc_frame, width=70); listbox_docs.pack(side=tk.LEFT, fill=tk.BOTH, expand=True) 
        scrollbar = ttk.Scrollbar(doc_frame, orient=tk.VERTICAL, command=listbox_docs.yview); listbox_docs.config(yscrollcommand=scrollbar.set); scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        doc_map = {}; missing_files_indices = set()
        try:
            cursor.execute("SELECT id, dateiname, dokument_pfad FROM kunden_dokumente WHERE kunde_id=? ORDER BY dateiname ASC", (customer_id_for_show,)); documents = cursor.fetchall()
            if documents:
                for doc_id, file_name, file_path in documents:
                    display_name = file_name; file_missing = False
                    if not os.path.exists(file_path): display_name += " [FEHLT!]"; file_missing = True
                    listbox_docs.insert(tk.END, display_name); current_index = listbox_docs.size() - 1
                    doc_map[current_index] = (file_path, file_name, doc_id)
                    if file_missing: listbox_docs.itemconfig(current_index, {'fg': 'red'}); missing_files_indices.add(current_index)
            else: listbox_docs.insert(tk.END, "Keine Dokumente zugeordnet."); listbox_docs.config(state=tk.DISABLED)
        except sqlite3.Error as e: 
            messagebox.showerror("Fehler", f"Fehler beim Abrufen der Dokumente: {e}", parent=documents_window); 
            logging.error(f"DB-Fehler Abruf Dokus Kunde {customer_id_for_show}: {e}")

        button_frame_docs = ttk.Frame(documents_window)

        btn_open_doc = ttk.Button(button_frame_docs, text="Öffnen", state=tk.DISABLED)
        btn_delete_doc = ttk.Button(button_frame_docs, text="Löschen", state=tk.DISABLED)
        btn_send_doc = ttk.Button(button_frame_docs, text="Senden", state=tk.DISABLED)

        def get_selected_doc_info():
            selected_indices = listbox_docs.curselection()
            if not selected_indices: return None, None, None, None 
            index = selected_indices[0]
            if index in doc_map:
                file_path, file_name, doc_id = doc_map[index]
                return index, file_path, file_name, doc_id
            return index, None, None, None

        def update_button_states(event=None):
             index, file_path, _, doc_id_val = get_selected_doc_info()
             doc_selected_validly = index is not None and doc_id_val is not None
             file_exists = doc_selected_validly and file_path is not None and os.path.exists(file_path)
             smtp_configured = self._is_smtp_configured()

             btn_open_doc.config(state=tk.NORMAL if file_exists else tk.DISABLED)
             btn_delete_doc.config(state=tk.NORMAL if doc_selected_validly else tk.DISABLED)
             btn_send_doc.config(state=tk.NORMAL if file_exists and smtp_configured else tk.DISABLED)

        def open_selected_document():
            index, file_path, file_name, doc_id = get_selected_doc_info()
            if file_path and file_name and os.path.exists(file_path): 
                self._open_file(file_path) 
            elif index is not None and index in missing_files_indices:
                messagebox.showerror("Fehler", f"Datei nicht gefunden:\n{doc_map.get(index, ('N/A','N/A','N/A'))[0]}", parent=documents_window)
            elif index is None:
                 messagebox.showwarning("Warnung", "Dokument zum Öffnen auswählen.", parent=documents_window)

        def delete_selected_document():
             index, file_path, file_name, doc_id = get_selected_doc_info()
             if doc_id is not None:
                 confirm = messagebox.askyesno("Löschen bestätigen", f"Dokument '{file_name}' wirklich löschen?\n\nLöscht DB-Eintrag UND Datei (falls vorhanden)!", icon=messagebox.WARNING, parent=documents_window)
                 if confirm:
                     try:
                         file_existed_and_deleted = False
                         if file_path and os.path.exists(file_path):
                             try:
                                 os.remove(file_path)
                                 logging.info(f"Dokumentdatei gelöscht: {file_path}")
                                 file_existed_and_deleted = True
                             except OSError as e:
                                 logging.error(f"Fehler beim Löschen der Datei '{file_path}': {e}")
                                 messagebox.showwarning("Datei Fehler", f"Konnte Datei nicht löschen:\n{file_path}\n{e}\nDer Datenbank-Eintrag wird trotzdem entfernt.", parent=documents_window)
                         
                         db_cursor_del = self.conn.cursor()
                         db_cursor_del.execute("DELETE FROM kunden_dokumente WHERE id=?", (doc_id,)); 
                         self.conn.commit(); 
                         # ### GoBD-ÄNDERUNG ###: Protokollierung der Dokumentenlöschung
                         self._log_audit_event("DOKUMENT_GELOESCHT", record_id=customer_id_for_show, details=f"Dateizuordnung für '{file_name}' (Pfad: {file_path}) wurde entfernt.")

                         logging.info(f"Doku-Eintrag ID {doc_id} gelöscht.")
                         listbox_docs.delete(index)
                         
                         temp_doc_map = {}
                         temp_missing_indices = set()
                         original_indices = sorted(doc_map.keys())
                         if index < len(original_indices):
                             key_to_remove = original_indices[index]
                             doc_map.pop(key_to_remove, None)
                         missing_files_indices.discard(index)
                         
                         messagebox.showinfo("Erfolg", f"'{file_name}' {'Datei und Eintrag' if file_existed_and_deleted else 'Eintrag'} gelöscht.", parent=documents_window)
                         if listbox_docs.size() == 0: 
                             listbox_docs.insert(tk.END, "Keine Dokumente zugeordnet."); 
                             listbox_docs.config(state=tk.DISABLED)
                         update_button_states() 
                     except sqlite3.Error as e: 
                         messagebox.showerror("DB Fehler", f"Fehler beim Löschen des Eintrags:\n{e}", parent=documents_window); 
                         logging.error(f"DB-Fehler Löschen Eintrag ID {doc_id}: {e}"); self.conn.rollback()
                     except Exception as e: 
                         messagebox.showerror("Allg. Fehler", f"Unerwarteter Fehler beim Löschen:\n{e}", parent=documents_window); 
                         logging.exception(f"Fehler Löschen Doku ID {doc_id}:")
             else: 
                 messagebox.showwarning("Warnung", "Dokument zum Löschen auswählen.", parent=documents_window)

        def send_selected_document():
            index, file_path, file_name, doc_id = get_selected_doc_info()
            if not (file_path and file_name):
                 messagebox.showwarning("Fehler", "Kein gültiges Dokument zum Senden ausgewählt.", parent=documents_window)
                 return
            if not os.path.exists(file_path):
                 messagebox.showerror("Fehler", f"Datei nicht gefunden:\n{file_path}", parent=documents_window)
                 return
            if not self._is_smtp_configured():
                 messagebox.showerror("Fehler", "SMTP Server, Port oder Benutzername nicht konfiguriert.\nBitte in den Einstellungen anpassen.", parent=documents_window)
                 return

            customer_email = self._get_customer_email(customer_id_for_show)
            self.open_email_compose_window(
                parent=documents_window, 
                recipient_email=customer_email,
                attachment_path=file_path,
                attachment_filename=file_name
            )

        button_frame_docs.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=10)
        
        btn_open_doc.config(command=open_selected_document)
        btn_open_doc.pack(side=tk.LEFT, padx=(0, 5))

        btn_delete_doc.config(command=delete_selected_document)
        btn_delete_doc.pack(side=tk.LEFT, padx=5)
        
        btn_send_doc.config(command=send_selected_document)
        btn_send_doc.pack(side=tk.LEFT, padx=5)
        
        ttk.Button(button_frame_docs, text="Schließen", command=documents_window.destroy).pack(side=tk.RIGHT, padx=5)

        listbox_docs.bind('<<ListboxSelect>>', update_button_states) 
        listbox_docs.bind("<Double-1>", lambda event: open_selected_document()) 

        if not documents:
             btn_open_doc.config(state=tk.DISABLED)
             btn_delete_doc.config(state=tk.DISABLED)
             btn_send_doc.config(state=tk.DISABLED)
        else:
            first_valid_doc_index = None
            for idx in range(listbox_docs.size()):
                 if idx not in missing_files_indices and idx in doc_map:
                     first_valid_doc_index = idx
                     break
            
            if first_valid_doc_index is not None:
                 listbox_docs.select_set(first_valid_doc_index) 
                 listbox_docs.activate(first_valid_doc_index)
            elif listbox_docs.size() > 0:
                 listbox_docs.select_set(0)
                 listbox_docs.activate(0)
            
            update_button_states()


    def save_customer(self):
        if not self.conn: return
        name = self.entries_kunden["Name:"].get().strip()
        vorname = self.entries_kunden["Vorname:"].get().strip()
        titel_firma = self.entries_kunden["Titel / Firma:"].get().strip() 
        geburtsdatum_str = self.entries_kunden["Geburtsdatum (TT.MM.JJJJ):"].get().strip()
        strasse = self.entries_kunden["Straße:"].get().strip()
        hausnummer = self.entries_kunden["Hausnummer:"].get().strip()
        plz = self.entries_kunden["PLZ:"].get().strip()
        ort = self.entries_kunden["Ort:"].get().strip()
        telefon = self.entries_kunden["Telefon:"].get().strip()
        email = self.entries_kunden["E-Mail:"].get().strip() 

        if not (name and vorname): messagebox.showwarning("Fehler", "Name und Vorname sind Pflichtfelder!", parent=self.root); return
        if geburtsdatum_str:
            try: datetime.strptime(geburtsdatum_str, "%d.%m.%Y")
            except ValueError: messagebox.showwarning("Fehler", "Ungültiges Geburtsdatumformat (TT.MM.JJJJ).", parent=self.root); return
        if email and "@" not in email:
            if not messagebox.askyesno("Warnung", f"'{email}' scheint keine gültige E-Mail-Adresse zu sein.\nTrotzdem speichern?", icon=messagebox.WARNING, parent=self.root): return

        cursor = self.conn.cursor()
        try:
            if self.selected_customer_for_edit is not None: # Update
                # ### GoBD-ÄNDERUNG ###: Vorherige Daten für Protokollierung laden
                cursor.execute("SELECT name, vorname, titel_firma, geburtsdatum, strasse, hausnummer, plz, ort, telefon, email FROM kunden WHERE id=?", (self.selected_customer_for_edit,))
                old_data = cursor.fetchone()
                if not old_data:
                    messagebox.showerror("Fehler", "Zu ändernder Kunde nicht gefunden.", parent=self.root)
                    return
                
                old_data_dict = dict(zip(['name', 'vorname', 'titel_firma', 'geburtsdatum', 'strasse', 'hausnummer', 'plz', 'ort', 'telefon', 'email'], old_data))
                new_data_dict = dict(zip(['name', 'vorname', 'titel_firma', 'geburtsdatum', 'strasse', 'hausnummer', 'plz', 'ort', 'telefon', 'email'], 
                                         [name, vorname, titel_firma, geburtsdatum_str, strasse, hausnummer, plz, ort, telefon, email]))

                changes = []
                for key, new_val in new_data_dict.items():
                    old_val = old_data_dict.get(key)
                    # Normalisiere leere Strings und None für den Vergleich
                    old_comp = old_val if old_val is not None else ""
                    new_comp = new_val if new_val is not None else ""
                    if old_comp != new_comp:
                        changes.append(f"Feld '{key}' von '{old_comp}' zu '{new_comp}'")

                if not changes:
                    messagebox.showinfo("Keine Änderungen", "Es wurden keine Änderungen an den Kundendaten vorgenommen.", parent=self.root)
                    return

                if not messagebox.askyesno("Änderung bestätigen", "Kundendaten wirklich ändern?", default=messagebox.YES, icon=messagebox.QUESTION, parent=self.root):
                    logging.info(f"Änderung Kunde ID {self.selected_customer_for_edit} abgebrochen."); return
                
                cursor.execute("UPDATE kunden SET name=?, vorname=?, titel_firma=?, geburtsdatum=?, strasse=?, hausnummer=?, plz=?, ort=?, telefon=?, email=? WHERE id=?",
                               (name, vorname, titel_firma or None, geburtsdatum_str or None, strasse or None, hausnummer or None, plz or None, ort or None, telefon or None, email or None, self.selected_customer_for_edit))
                
                # ### GoBD-ÄNDERUNG ###: Änderungen protokollieren
                self._log_audit_event("KUNDE_GEAENDERT", record_id=self.selected_customer_for_edit, details="; ".join(changes))
                self.conn.commit(); 
                messagebox.showinfo("Erfolg", "Kundendaten geändert!", parent=self.root)
                customer_id_to_reload = self.selected_customer_for_edit
                self.clear_customer_fields(); self.load_customers(); self.select_customer_in_tree(customer_id_to_reload)
            else: # Insert
                cursor.execute("SELECT MAX(zifferncode) FROM kunden"); max_code_result = cursor.fetchone()
                next_zifferncode = max(1001, (max_code_result[0] or 1000) + 1) if max_code_result and max_code_result[0] is not None else 1001
                
                cursor.execute("INSERT INTO kunden (name, vorname, titel_firma, geburtsdatum, strasse, hausnummer, plz, ort, telefon, email, zifferncode) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                               (name, vorname, titel_firma or None, geburtsdatum_str or None, strasse or None, hausnummer or None, plz or None, ort or None, telefon or None, email or None, next_zifferncode))
                new_customer_id = cursor.lastrowid
                
                # ### GoBD-ÄNDERUNG ###: Erstellung protokollieren
                self._log_audit_event("KUNDE_ERSTELLT", record_id=new_customer_id, details=f"Neuer Kunde '{vorname} {name}' mit Kundennr. {next_zifferncode}")
                self.conn.commit()

                if new_customer_id:
                     self.create_customer_document_folder(new_customer_id, next_zifferncode)
                     messagebox.showinfo("Erfolg", f"Kunde gespeichert! Kundennummer: {next_zifferncode}", parent=self.root)
                     logging.info(f"Kunde '{vorname} {name}' gespeichert (ID: {new_customer_id}, Kundennr: {next_zifferncode}).")
                     self.clear_customer_fields(); self.load_customers(); self.select_customer_in_tree(new_customer_id)
                else: 
                    messagebox.showerror("Fehler", "Konnte Kunde nicht speichern.", parent=self.root); 
                    logging.error("Fehler Speichern neuer Kunde: keine lastrowid."); self.conn.rollback()
        except sqlite3.IntegrityError: 
            messagebox.showerror("Fehler", "Kundennummer evtl. schon vergeben.", parent=self.root); 
            logging.error("IntegrityError Speichern Kunde."); self.conn.rollback()
        except sqlite3.Error as e: 
            messagebox.showerror("DB Fehler", f"Fehler Speichern Kunde: {e}", parent=self.root); 
            logging.error(f"DB-Fehler Speichern Kunde: {e}"); self.conn.rollback()
        except Exception as e: 
            messagebox.showerror("Allg. Fehler", f"Unerwarteter Fehler Speichern: {e}", parent=self.root); 
            logging.exception("Unerwarteter Fehler Speichern Kunde:"); self.conn.rollback()

    def delete_customer(self):
        # ### GoBD-ÄNDERUNG ###: Diese Funktion löscht nicht mehr, sondern deaktiviert/reaktiviert.
        if not self.conn: return
        customer_id_to_toggle = None
        customer_name = "Unbekannt"
        
        if self.selected_customer_for_edit is not None:
            customer_id_to_toggle = self.selected_customer_for_edit
            vorname_del = self.entries_kunden['Vorname:'].get()
            name_del = self.entries_kunden['Name:'].get()
            customer_name = f"{vorname_del} {name_del}".strip()
        else:
            selected_item = self.tree.focus()
            if selected_item:
                try: 
                    values = self.tree.item(selected_item)["values"]
                    customer_id_to_toggle = int(values[0])
                    customer_name = f"{values[3]} {values[2]}".strip()
                except (IndexError, KeyError, TypeError, ValueError): 
                    messagebox.showwarning("Fehler", "Kundeninfo nicht lesbar.", parent=self.root); return
            else: 
                messagebox.showwarning("Fehler", "Kein Kunde ausgewählt!", parent=self.root); return
        
        if customer_id_to_toggle is None: 
            messagebox.showwarning("Fehler", "Kunden-ID nicht ermittelbar.", parent=self.root); return

        cursor = self.conn.cursor()
        try:
            cursor.execute("SELECT is_active FROM kunden WHERE id=?", (customer_id_to_toggle,))
            current_status = cursor.fetchone()
            if not current_status:
                messagebox.showerror("Fehler", "Kunde nicht gefunden.", parent=self.root)
                return
            
            is_currently_active = current_status[0] == 1
            
            if is_currently_active: # Deaktivieren
                # Prüfen, ob der Kunde offene Rechnungen hat. Dies ist nur ein Hinweis, keine Blockade.
                cursor.execute("SELECT COUNT(*) FROM rechnungen WHERE kunde_id=? AND status NOT IN ('Bezahlt', 'Storniert')", (customer_id_to_toggle,))
                open_invoices_count = cursor.fetchone()[0]
                
                msg = f"Kunden '{customer_name}' wirklich deaktivieren?"
                if open_invoices_count > 0:
                    msg += f"\n\nWARNUNG: Der Kunde hat noch {open_invoices_count} offene Rechnung(en)!"
                
                if messagebox.askyesno("Deaktivieren bestätigen", msg, default=messagebox.NO, icon=messagebox.WARNING, parent=self.root):
                    cursor.execute("UPDATE kunden SET is_active = 0 WHERE id=?", (customer_id_to_toggle,))
                    self._log_audit_event("KUNDE_DEAKTIVIERT", record_id=customer_id_to_toggle, details=f"Kunde '{customer_name}' wurde deaktiviert.")
                    self.conn.commit()
                    messagebox.showinfo("Erfolg", f"Kunde '{customer_name}' wurde deaktiviert.", parent=self.root)
                else:
                    return # Abbruch durch Benutzer
            
            else: # Reaktivieren
                if messagebox.askyesno("Reaktivieren bestätigen", f"Kunden '{customer_name}' wirklich reaktivieren?", icon=messagebox.QUESTION, parent=self.root):
                    cursor.execute("UPDATE kunden SET is_active = 1 WHERE id=?", (customer_id_to_toggle,))
                    self._log_audit_event("KUNDE_REAKTIVIERT", record_id=customer_id_to_toggle, details=f"Kunde '{customer_name}' wurde reaktiviert.")
                    self.conn.commit()
                    messagebox.showinfo("Erfolg", f"Kunde '{customer_name}' wurde reaktiviert.", parent=self.root)
                else:
                    return # Abbruch durch Benutzer

            self.clear_customer_fields(); self.load_customers()
            self.select_customer_in_tree(customer_id_to_toggle)

        except sqlite3.Error as e:
            messagebox.showerror("DB Fehler", f"Fehler bei Statusänderung des Kunden: {e}", parent=self.root)
            logging.error(f"DB-Fehler bei Statusänderung Kunde ID {customer_id_to_toggle}: {e}")
            self.conn.rollback()
        except Exception as e:
            messagebox.showerror("Allg. Fehler", f"Unerwarteter Fehler bei Statusänderung: {e}", parent=self.root)
            logging.exception(f"Fehler bei Statusänderung Kunde ID {customer_id_to_toggle}:")
            self.conn.rollback()


    def clear_customer_fields(self):
        for entry in self.entries_kunden.values(): entry.delete(0, tk.END)
        self.selected_customer_for_edit = None; self.btn_save_kunde.config(text="Kunde speichern")
        self.btn_delete_customer.config(text="Kunde deaktivieren") # Standardtext
        current_focus = self.tree.focus()
        if current_focus: 
            self.tree.selection_remove(current_focus)
            self.tree.focus("")

    def load_customers(self, query=None, zifferncode_query=None):
        if not self.conn: return
        for row in self.tree.get_children(): self.tree.delete(row)
        cursor = self.conn.cursor()
        # ### GoBD-ÄNDERUNG ###: is_active wird abgefragt und in WHERE-Klausel berücksichtigt
        sql = "SELECT DISTINCT k.id, k.zifferncode, k.name, k.vorname, k.titel_firma, k.geburtsdatum, k.strasse, k.hausnummer, k.plz, k.ort, k.telefon, k.email, k.is_active FROM kunden k"
        params = []
        where_clauses = []

        if not self.show_inactive_customers.get():
            where_clauses.append("k.is_active = 1")

        try:
            if zifferncode_query is not None:
                 where_clauses.append("k.zifferncode = ?")
                 params.append(zifferncode_query)
            elif query:
                like_query = f"%{query}%"
                sql += " LEFT JOIN rechnungen r ON k.id = r.kunde_id" 
                where_clauses.append("(k.name LIKE ? OR k.vorname LIKE ? OR k.titel_firma LIKE ? OR k.geburtsdatum LIKE ? OR k.strasse LIKE ? OR k.hausnummer LIKE ? OR k.plz LIKE ? OR k.ort LIKE ? OR k.telefon LIKE ? OR k.email LIKE ? OR CAST(k.zifferncode AS TEXT) LIKE ? OR r.rechnungsnummer LIKE ?)")
                params.extend([like_query] * 12)
            
            if where_clauses:
                sql += " WHERE " + " AND ".join(where_clauses)
                
            sql += " ORDER BY k.name ASC, k.vorname ASC"
            cursor.execute(sql, params)

            for row in cursor.fetchall():
                # Wandle is_active (0/1) in einen lesbaren Status um
                is_active_status = "Aktiv" if row[-1] == 1 else "Inaktiv"
                display_row = [str(item) if item is not None else "" for item in row[:-1]] + [is_active_status]
                
                # Tag für graue Darstellung inaktiver Kunden setzen
                tag = 'inaktiv' if row[-1] == 0 else ''
                self.tree.insert("", "end", values=display_row, tags=(tag,))

            count = len(self.tree.get_children()); filter_type = ""
            if zifferncode_query is not None: filter_type = "(gefiltert nach Kundennr.)"
            elif query: filter_type = "(gefiltert nach Kundendaten/Rechnungsnr.)"
            logging.info(f"{count} Kunden geladen {filter_type}.")
        except sqlite3.Error as e: 
            messagebox.showerror("Fehler", f"Fehler beim Laden der Kunden: {e}", parent=self.root); 
            logging.error(f"DB-Fehler Laden Kunden: {e}")
        except Exception as e: 
            messagebox.showerror("Fehler", f"Allg. Fehler Laden Kunden: {e}", parent=self.root); 
            logging.exception("Fehler Laden Kunden:")

    def search_customers(self): self.load_customers(query=self.entry_search.get().strip())
    
    def search_customers_by_zifferncode(self): 
        zifferncode_search_term = self.entry_zifferncode_search.get().strip()
        if zifferncode_search_term:
            try:
                zifferncode_int = int(zifferncode_search_term)
                self.load_customers(zifferncode_query=zifferncode_int)
                if self.hands_free_zifferncode_search.get():
                    items = self.tree.get_children()
                    if len(items) == 1: 
                        self.tree.focus(items[0]); 
                        self.tree.selection_set(items[0]); 
                        self.on_customer_select(None);
                        logging.info(f"Hands-free Kundennr.-Suche: Kunde {zifferncode_int} geladen.")
            except ValueError: 
                messagebox.showwarning("Warnung", "Gültige Zahl als Kundennummer eingeben.", parent=self.root)
            except Exception as e: 
                messagebox.showerror("Fehler", f"Fehler bei Kundennr.-Suche: {e}", parent=self.root); 
                logging.error(f"Fehler Suche Kundennr '{zifferncode_search_term}': {e}")
        else: self.load_customers()

    def zifferncode_search_enter_pressed(self, event=None): self.search_customers_by_zifferncode()
    def fulltext_search_enter_pressed(self, event=None): self.search_customers()
    
    def select_customer_in_tree(self, customer_id_to_select):
        for item in self.tree.get_children():
             try:
                 if str(self.tree.item(item)['values'][0]) == str(customer_id_to_select): 
                     self.tree.selection_set(item); 
                     self.tree.focus(item); 
                     self.tree.see(item); 
                     return True
             except (IndexError, KeyError, TypeError): continue
        return False

    def on_customer_double_click(self, event): 
        selected_item = self.tree.focus()
        if selected_item:
            try: 
                customer_id_dbl = int(self.tree.item(selected_item)["values"][0])
                self.open_rechnungs_window(customer_id_dbl)
            except (IndexError, KeyError, TypeError, ValueError): 
                logging.warning("Index/Type/Key/Value Error bei Doppelklick.")
            except Exception as e: 
                logging.error(f"Fehler bei Doppelklick: {e}")

    def open_change_db_path_window(self):
        # ... (Funktion unverändert)
        change_path_window = tk.Toplevel(self.root)
        change_path_window.title("Datenbankpfad ändern")
        change_path_window.transient(self.root)
        change_path_window.grab_set()

        ttk.Label(change_path_window, text="Neuer Datenbankpfad (.db):").pack(padx=10, pady=10)
        entry_new_db_path = ttk.Entry(change_path_window, width=40)
        entry_new_db_path.pack(padx=10, pady=5)
        entry_new_db_path.insert(0, self.db_path)

        def browse_path():
            new_path = filedialog.asksaveasfilename(
                parent=change_path_window,
                initialdir=os.path.dirname(self.db_path),
                defaultextension=".db",
                filetypes=[("SQLite DBs", "*.db"), ("Alle", "*.*")]
            )
            if new_path:
                entry_new_db_path.delete(0, tk.END)
                entry_new_db_path.insert(0, new_path)

        def save_path():
            new_path_val = entry_new_db_path.get().strip()
            if new_path_val and new_path_val.lower().endswith(".db"):
                original_db_path = self.db_path
                try:
                    if self.conn:
                        self.conn.close()
                        logging.info("Alte DB-Verbindung geschlossen.")
                    
                    temp_conn = connect_db_static(new_path_val)
                    if temp_conn:
                        temp_conn.close()
                        logging.info(f"Testverbindung zu '{new_path_val}' ok.")
                        
                        self.save_setting("db_path", new_path_val)
                        self.conn = self.connect_db()
                        
                        if self.conn:
                            self.check_and_update_invoice_status() 
                            self.load_customers() 
                            messagebox.showinfo("Erfolg", f"DB-Pfad geändert: {self.db_path}", parent=change_path_window)
                            logging.info(f"DB-Pfad geändert: {self.db_path}")
                            change_path_window.destroy()
                        else:
                            messagebox.showerror("Fehler", "Verbindung zur neuen DB fehlgeschlagen.", parent=change_path_window)
                            logging.warning("Versuche, alte DB-Verbindung wiederherzustellen.")
                            self.db_path = original_db_path
                            self.save_setting("db_path", original_db_path)
                            self.conn = self.connect_db()
                            if self.conn: logging.info("Alte DB-Verbindung wiederhergestellt.")
                            else: logging.error("Konnte alte DB-Verbindung nicht wiederherstellen. App könnte instabil sein.")
                    else:
                        messagebox.showerror("Fehler", f"Konnte DB nicht öffnen/erstellen:\n{new_path_val}", parent=change_path_window)
                        logging.warning("Versuche, alte DB-Verbindung wiederherzustellen (Test-Connect fehlgeschlagen).")
                        self.conn = connect_db_static(original_db_path)
                        if self.conn: logging.info("Alte DB-Verbindung wiederhergestellt.")
                        else: logging.error("Konnte alte DB-Verbindung nicht wiederherstellen. App könnte instabil sein.")
                except Exception as e:
                    messagebox.showerror("Fehler", f"Fehler beim Wechseln der DB: {e}", parent=change_path_window)
                    logging.error(f"Fehler Wechsel DB zu '{new_path_val}': {e}")
                    logging.warning("Versuche, alte DB-Verbindung wiederherzustellen (Exception).")
                    self.conn = connect_db_static(original_db_path)
                    if self.conn: logging.info("Alte DB-Verbindung wiederhergestellt.")
                    else: logging.error("Konnte alte DB-Verbindung nicht wiederherstellen. App könnte instabil sein.")
            else:
                messagebox.showwarning("Warnung", "Gültigen Pfad zu einer .db-Datei angeben.", parent=change_path_window)

        btn_browse = ttk.Button(change_path_window, text="Durchsuchen...", command=browse_path)
        btn_browse.pack(pady=5)
        btn_save = ttk.Button(change_path_window, text="Speichern & Neu verbinden", command=save_path)
        btn_save.pack(pady=10)
        btn_cancel = ttk.Button(change_path_window, text="Abbrechen", command=change_path_window.destroy)
        btn_cancel.pack(pady=5)

    def check_and_update_invoice_status(self):
        # ... (Funktion unverändert, die Logik hier ist GoBD-konform, da sie nur den Status aktualisiert und protokolliert)
        if not self.conn: logging.error("Statusprüfung übersprungen: Keine DB-Verbindung."); return
        logging.info("Starte Prüfung überfälliger Rechnungen...")
        today = datetime.now().date(); updates_to_perform = []; timestamp = datetime.now().strftime("%d.%m.%Y %H:%M")
        status_levels = {"Entwurf": 0, "Offen": 1, "Steht zur Erinnerung an": 2, "Steht zur Mahnung an": 3, "Steht zur Mahnung 2 an": 4, "Bitte an Inkasso weiterleiten": 5, "Bezahlt": 6, "Storniert": 7}
        try:
            cursor = self.conn.cursor(); cursor.execute("SELECT id, faelligkeitsdatum, status, bemerkung FROM rechnungen WHERE status NOT IN (?, ?, ?) AND faelligkeitsdatum IS NOT NULL AND faelligkeitsdatum != ''", ('Bezahlt', 'Storniert', 'Bitte an Inkasso weiterleiten'))
            for row in cursor.fetchall():
                re_id, due_date_str, current_status, current_remarks = row; target_status = None; remark_text = None
                try: due_date = datetime.strptime(due_date_str, "%d.%m.%Y").date()
                except (ValueError, TypeError): logging.warning(f"Ungültiges Fälligkeitsdatum '{due_date_str}' für Rng-ID {re_id}."); continue
                if due_date < today:
                    days_overdue = (today - due_date).days; current_level = status_levels.get(current_status, 0)
                    if days_overdue >= self.inkasso_days and current_level < status_levels["Bitte an Inkasso weiterleiten"]: target_status = "Bitte an Inkasso weiterleiten"; remark_text = "-> Zur Weiterleitung an Inkasso"
                    elif days_overdue >= self.mahnung2_days and current_level < status_levels["Steht zur Mahnung 2 an"]: target_status = "Steht zur Mahnung 2 an"; remark_text = "-> Zur 2. Mahnung an"
                    elif days_overdue >= self.mahnung1_days and current_level < status_levels["Steht zur Mahnung an"]: target_status = "Steht zur Mahnung an"; remark_text = "-> Zur Mahnung an"
                    elif days_overdue >= self.reminder_days and current_level < status_levels["Steht zur Erinnerung an"]: target_status = "Steht zur Erinnerung an"; remark_text = "-> Zur Erinnerung an"
                    
                    if target_status:
                        new_remark_line = f"{timestamp}: Status automatisch gesetzt auf '{target_status}' ({remark_text})."; 
                        last_remark = (current_remarks or "").split('\n')[-1].strip()
                        if new_remark_line.strip() != last_remark:
                            updated_remarks = ((current_remarks + "\n") if current_remarks else "") + new_remark_line; 
                            updates_to_perform.append((target_status, updated_remarks, re_id)); 
                            logging.info(f"Rng-ID {re_id}: Update geplant - Status: '{target_status}'.")
            if updates_to_perform:
                logging.info(f"Führe {len(updates_to_perform)} Status-Updates durch...")
                try: 
                    for status, remark, re_id in updates_to_perform:
                         self._log_audit_event("RECHNUNG_STATUS_AUTO", record_id=re_id, details=f"Status automatisch auf '{status}' gesetzt.")
                    cursor.executemany("UPDATE rechnungen SET status=?, bemerkung=? WHERE id=?", updates_to_perform); 
                    self.conn.commit(); 
                    logging.info("Status-Updates erfolgreich.")
                except sqlite3.Error as update_err: 
                    logging.error(f"Fehler beim Durchführen der Status-Updates: {update_err}"); self.conn.rollback()
            else: logging.info("Keine Status-Updates für überfällige Rechnungen notwendig.")
        except sqlite3.Error as e: logging.error(f"DB-Fehler beim Prüfen überfälliger Rechnungen: {e}")
        except Exception as e: logging.exception("Allg. Fehler beim Prüfen überfälliger Rechnungen:")

    def update_next_invoice_number_suggestion(self):
        # ... (Funktion unverändert)
        if not self.conn: self.next_invoice_number_suggestion = f"{datetime.now().strftime('%Y')}-???? "; return
        current_year = datetime.now().strftime("%Y")
        try:
            cursor = self.conn.cursor(); 
            cursor.execute("SELECT rechnungsnummer FROM rechnungen WHERE rechnungsnummer LIKE ? ORDER BY rechnungsnummer DESC LIMIT 1", (f"{current_year}-%",)); 
            last_invoice = cursor.fetchone()
            if last_invoice and last_invoice[0]:
                try: 
                    parts = last_invoice[0].split('-'); 
                    next_num = int(parts[1]) + 1 if len(parts) == 2 and parts[0] == current_year and parts[1].isdigit() else 1; 
                    self.next_invoice_number_suggestion = f"{current_year}-{next_num:04d}"
                except (ValueError, IndexError): self.next_invoice_number_suggestion = f"{current_year}-0001"
            else: self.next_invoice_number_suggestion = f"{current_year}-0001"
            logging.info(f"Nächster Rechnungsnummer-Vorschlag: {self.next_invoice_number_suggestion}")
        except sqlite3.Error as e: 
            logging.error(f"Fehler beim Ermitteln der nächsten Rechnungsnummer: {e}"); 
            self.next_invoice_number_suggestion = f"{current_year}-???? "
        except Exception as e: 
            logging.error(f"Allg. Fehler beim Ermitteln der nächsten Rechnungsnummer: {e}"); 
            self.next_invoice_number_suggestion = f"{current_year}-???? "
    
    def _default_update_next_invoice_number_suggestion(self): 
        logging.warning("Fallback für update_next_invoice_number_suggestion."); 
        self.next_invoice_number_suggestion = f"{datetime.now().strftime('%Y')}-???? "
        
    def _book_stock_change(self, cursor, items, direction, invoice_id_for_log=""):
        # ... (Funktion unverändert)
        if not items:
            return

        updates_to_perform = []
        for item in items:
            artikelnummer = item.get('artikelnummer')
            menge = item.get('menge')

            if not artikelnummer or not isinstance(menge, (int, float)) or menge <= 0:
                continue

            change_menge = -menge if direction == 'out' else menge
            updates_to_perform.append((change_menge, artikelnummer))

        if updates_to_perform:
            try:
                for menge_change, artnr in updates_to_perform:
                    cursor.execute("UPDATE artikel SET verfuegbar = verfuegbar + ? WHERE artikelnummer = ?",
                                   (menge_change, artnr))

                log_direction = "abgebucht" if direction == 'out' else "zurückgebucht"
                logging.info(f"Lagerbestand für {len(updates_to_perform)} Artikel für Rng ID {invoice_id_for_log} erfolgreich {log_direction}.")

            except sqlite3.Error as e:
                logging.error(f"DB-Fehler bei Lagerbuchung (Richtung: {direction}, Rng ID: {invoice_id_for_log}): {e}")
                raise e
            except Exception as e:
                logging.exception(f"Allg. Fehler bei Lagerbuchung (Richtung: {direction}, Rng ID: {invoice_id_for_log}):")
                raise e

    def open_rechnungs_window(self, customer_id, create_new=False):
        # ### GoBD-ÄNDERUNG ###: Diese Funktion wird stark überarbeitet, um die Unveränderbarkeit von Rechnungen zu gewährleisten.
        if not self.conn: return
        self.check_and_update_invoice_status()
        cursor = self.conn.cursor()
        try:
            cursor.execute("SELECT id, name, vorname, titel_firma, strasse, hausnummer, plz, ort, zifferncode, is_active FROM kunden WHERE id=?", (customer_id,))
            customer_data = cursor.fetchone()
            if not customer_data:
                messagebox.showerror("Fehler", f"Kunde mit ID {customer_id} nicht gefunden.", parent=self.root)
                return
            *cust_details, is_active = customer_data
            if not is_active and create_new:
                messagebox.showwarning("Inaktiver Kunde", "Für inaktive Kunden können keine neuen Rechnungen erstellt werden.", parent=self.root)
                return

            cust_id, cust_name, cust_vorname, cust_titel_firma, cust_str, cust_hnr, cust_plz, cust_ort, cust_code = cust_details
            name_parts = [cust_vorname, cust_name]
            if cust_titel_firma: name_parts.append(f"({cust_titel_firma})")
            customer_display_name = " ".join(part for part in name_parts if part)
            customer_display_name += f" (Nr: {cust_code or 'N/A'})"
        except sqlite3.Error as e:
            messagebox.showerror("DB Fehler", f"Kundendaten nicht ladbar: {e}", parent=self.root)
            logging.error(f"Fehler Laden Kundendaten Rng-Fenster (ID: {customer_id}): {e}")
            return

        rechnung_window = tk.Toplevel(self.root)
        rechnung_window.title(f"Rechnungen für {customer_display_name}")
        rechnung_window.geometry("1500x750")
        rechnung_window.transient(self.root)
        rechnung_window.grab_set()

        self.current_invoice_id = None
        self.current_invoice_is_finalized = False # GoBD-Flag
        

# ### NEUE FUNKTION HINZUGEFÜGT ###
        def prepare_invoice_for_external_tool():
            """Liest die Rechnungsnummer der ausgewählten Rechnung und schreibt sie in eine temporäre Datei."""
            selected_item_id = self.tree_rechnungen_list.focus()
            if not selected_item_id:
                messagebox.showwarning("Auswahl fehlt", "Bitte wählen Sie eine Rechnung aus der Liste aus.", parent=rechnung_window)
                return

            try:
                # Hole die Rechnungsnummer aus der zweiten Spalte ('Nummer') der ausgewählten Zeile
                rechnungs_nr = self.tree_rechnungen_list.item(selected_item_id, "values")[1]
                temp_file = "temporärspeicher.tmp" # Der Dateiname für den Datenaustausch

                # Schreibe die Rechnungsnummer in die Datei. Bestehende Dateien werden überschrieben.
                with open(temp_file, "w", encoding="utf-8") as f:
                    f.write(rechnungs_nr)

                logging.info(f"Rechnungsnummer '{rechnungs_nr}' in '{temp_file}' geschrieben.")
                messagebox.showinfo(
                    "Vorbereitet",
                    f"Die Rechnungsnummer '{rechnungs_nr}' wurde für die Verwendung in anderen Tools bereitgestellt.\n\n"
                    "Sie können jetzt dieses Fenster schließen und das entsprechende Tool (z.B. Rechnungskorrektur) aus dem Launcher starten.",
                    parent=rechnung_window
                )
            except IndexError:
                 messagebox.showerror("Fehler", "Konnte die Rechnungsnummer aus der Liste nicht auslesen. Bitte versuchen Sie es erneut.", parent=rechnung_window)
                 logging.error("IndexError beim Auslesen der Rechnungsnummer aus der Treeview.")
            except Exception as e:
                messagebox.showerror("Fehler", f"Ein unerwarteter Fehler ist aufgetreten:\n{e}", parent=rechnung_window)
                logging.error(f"Fehler beim Schreiben der temporären Datei '{temp_file}': {e}", exc_info=True)



        left_frame = ttk.LabelFrame(rechnung_window, text="Vorhandene Rechnungen")
        left_frame.pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=10, ipadx=5, ipady=5)
        cols_re_list = ("ID", "Nummer", "Datum", "Betrag", "Status")
        self.tree_rechnungen_list = ttk.Treeview(left_frame, columns=cols_re_list, show="headings", height=10)
        self.tree_rechnungen_list.tag_configure('storniert', foreground='grey')      # Für ungültige Originalrechnungen
        self.tree_rechnungen_list.tag_configure('gutschrift', foreground='blue')     # Für die negative Korrekturrechnung
        self.tree_rechnungen_list.tag_configure('finalized', foreground='darkgreen') # Für normale, offene Rechnungen
        self.tree_rechnungen_list.tag_configure('selektiert', background='SystemHighlight', foreground='SystemHighlightText')
        for col in cols_re_list:
            w=60; a=tk.W; s=tk.NO
            if col == "Nummer": w=100
            elif col == "Betrag": w=90; a=tk.E
            elif col == "Datum": w=80
            elif col == "ID": w=40; a=tk.E
            elif col == "Status": w=180; s=tk.YES
            self.tree_rechnungen_list.heading(col, text=col)
            self.tree_rechnungen_list.column(col, width=w, anchor=a, stretch=s)
        self.tree_rechnungen_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        re_list_scroll = ttk.Scrollbar(left_frame, orient=tk.VERTICAL, command=self.tree_rechnungen_list.yview)
        self.tree_rechnungen_list.configure(yscrollcommand=re_list_scroll.set)
        re_list_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        right_frame = ttk.Frame(rechnung_window)
        right_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        self.rechnung_finalized_label = ttk.Label(right_frame, text="RECHNUNG IST FINALISIERT - KEINE ÄNDERUNGEN MÖGLICH", font=("Arial", 10, "bold"), foreground="red")
        
        header_frame = ttk.LabelFrame(right_frame, text="Rechnungsdetails")
        header_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(header_frame, text="Rechnungsnr.:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        self.entry_re_nr = ttk.Entry(header_frame, width=20)
        self.entry_re_nr.grid(row=0, column=1, padx=5, pady=5, sticky=tk.W)
        ttk.Label(header_frame, text="Rechnungsdatum:").grid(row=0, column=2, padx=5, pady=5, sticky=tk.W)
        self.entry_re_datum = ttk.Entry(header_frame, width=12)
        self.entry_re_datum.grid(row=0, column=3, padx=5, pady=5, sticky=tk.W)
        self.entry_re_datum.insert(0, datetime.now().strftime("%d.%m.%Y"))
        ttk.Label(header_frame, text="Fällig am:").grid(row=0, column=4, padx=5, pady=5, sticky=tk.W)
        self.entry_re_faellig = ttk.Entry(header_frame, width=12)
        self.entry_re_faellig.grid(row=0, column=5, padx=5, pady=5, sticky=tk.W)
        try:
            self.entry_re_faellig.insert(0, (datetime.now() + timedelta(days=14)).strftime("%d.%m.%Y"))
        except Exception: pass
        ttk.Label(header_frame, text="MwSt.-Satz (%):").grid(row=1, column=0, padx=5, pady=5, sticky=tk.W)
        self.entry_re_mwst = ttk.Entry(header_frame, width=6)
        self.entry_re_mwst.grid(row=1, column=1, padx=5, pady=5, sticky=tk.W)
        self.entry_re_mwst.insert(0, str(self.default_vat_rate).replace('.', ','))
        ttk.Label(header_frame, text="Status:").grid(row=1, column=2, padx=5, pady=5, sticky=tk.W)
        status_values = ['Entwurf', 'Offen', 'Bezahlt', 'Steht zur Erinnerung an', 'Steht zur Mahnung an', 'Steht zur Mahnung 2 an', 'Bitte an Inkasso weiterleiten']
        self.combo_re_status = ttk.Combobox(header_frame, values=status_values, width=25, state="readonly")
        self.combo_re_status.grid(row=1, column=3, columnspan=3, padx=5, pady=5, sticky=tk.W)
        self.combo_re_status.set('Entwurf')
        items_frame = ttk.LabelFrame(right_frame, text="Rechnungsposten")
        items_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        cols_items = ("Pos", "ArtNr", "Beschreibung", "Menge", "Einheit", "Einzelpreis (€)", "Gesamt (€)")
        self.tree_re_items = ttk.Treeview(items_frame, columns=cols_items, show="headings", height=15)
        for col in cols_items:
            w=80; anchor=tk.W; stretch=tk.YES
            if col=="Pos": w=40; anchor=tk.E; stretch=tk.NO
            elif col=="Beschreibung": w=350
            elif col=="Menge": w=60; anchor=tk.E; stretch=tk.NO
            elif col=="Einheit": w=60; stretch=tk.NO
            elif col=="Einzelpreis (€)" or col=="Gesamt (€)": w=120; anchor=tk.E; stretch=tk.NO
            elif col=="ArtNr": w=80; stretch=tk.NO
            self.tree_re_items.heading(col, text=col)
            self.tree_re_items.column(col, width=w, anchor=anchor, stretch=stretch)
        self.tree_re_items.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        items_scroll = ttk.Scrollbar(items_frame, orient=tk.VERTICAL, command=self.tree_re_items.yview)
        self.tree_re_items.configure(yscrollcommand=items_scroll.set)
        items_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        item_button_frame = ttk.Frame(right_frame); item_button_frame.pack(fill=tk.X, pady=5)
        self.btn_add_item = ttk.Button(item_button_frame, text="Posten hinzufügen"); self.btn_add_item.pack(side=tk.LEFT, padx=5)
        self.btn_edit_item = ttk.Button(item_button_frame, text="Posten bearbeiten", state=tk.DISABLED); self.btn_edit_item.pack(side=tk.LEFT, padx=5)
        self.btn_delete_item = ttk.Button(item_button_frame, text="Posten löschen", state=tk.DISABLED); self.btn_delete_item.pack(side=tk.LEFT, padx=5)
        summary_frame = ttk.Frame(right_frame); summary_frame.pack(fill=tk.X, pady=5)
        bemerkung_frame = ttk.LabelFrame(summary_frame, text="Bemerkung"); bemerkung_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        self.text_re_bemerkung = tk.Text(bemerkung_frame, height=4, width=40, wrap=tk.WORD); self.text_re_bemerkung.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        summen_frame = ttk.Frame(summary_frame); summen_frame.pack(side=tk.RIGHT, fill=tk.Y)
        self.lbl_sum_netto = ttk.Label(summen_frame, text="Netto: 0,00 €", anchor=tk.E); self.lbl_sum_netto.pack(fill=tk.X, pady=1)
        self.lbl_sum_mwst = ttk.Label(summen_frame, text="MwSt. (19,0%): 0,00 €", anchor=tk.E); self.lbl_sum_mwst.pack(fill=tk.X, pady=1)
        self.lbl_sum_brutto = ttk.Label(summen_frame, text="Brutto: 0,00 €", font=("Arial", 10, "bold"), anchor=tk.E); self.lbl_sum_brutto.pack(fill=tk.X, pady=1)
        main_action_frame = ttk.Frame(right_frame); main_action_frame.pack(fill=tk.X, pady=10)
        self.btn_save_re = ttk.Button(main_action_frame, text="Rechnung speichern"); self.btn_save_re.pack(side=tk.LEFT, padx=5)
        self.btn_finalize_re = ttk.Button(main_action_frame, text="Finalisieren & Buchen", state=tk.DISABLED); self.btn_finalize_re.pack(side=tk.LEFT, padx=5)
        self.btn_print_re = ttk.Button(main_action_frame, text="Drucken (PDF)", state=tk.DISABLED); self.btn_print_re.pack(side=tk.LEFT, padx=5)
        self.btn_new_re = ttk.Button(main_action_frame, text="Neue Rechnung"); self.btn_new_re.pack(side=tk.LEFT, padx=5)
        self.btn_delete_re = ttk.Button(main_action_frame, text="Entwurf löschen", state=tk.DISABLED); self.btn_delete_re.pack(side=tk.LEFT, padx=5)
        self.btn_prepare_for_tool = ttk.Button(main_action_frame, text="Re-Nr. für anderes Tool vorbereiten", state=tk.DISABLED)
        self.btn_prepare_for_tool.pack(side=tk.RIGHT, padx=10)

        def load_rechnungen_list_local():
            # Merken, welche Rechnung gerade ausgewählt ist, um sie wieder zu selektieren.
            selected_invoice_id = None
            focused_item = self.tree_rechnungen_list.focus()
            if focused_item:
                try:
                    selected_invoice_id = int(self.tree_rechnungen_list.item(focused_item)['values'][0])
                except (ValueError, IndexError):
                    pass

            # Liste leeren
            for item_tree in self.tree_rechnungen_list.get_children():
                self.tree_rechnungen_list.delete(item_tree)
            
            try:
                # Lade alle relevanten Rechnungsdaten für den Kunden
                cursor.execute("SELECT id, rechnungsnummer, rechnungsdatum, summe_brutto, status, is_finalized FROM rechnungen WHERE kunde_id=? ORDER BY rechnungsdatum DESC, id DESC", (customer_id,))
                for row_data in cursor.fetchall():
                    re_id, re_nr, re_dat, re_brutto, re_stat, is_final = row_data
                    
                    brutto_str = f"{re_brutto:,.2f} €".replace('.', '#').replace(',', '.').replace('#', ',') if re_brutto is not None else ""
                    
                    # --- HIER IST DIE LOGIK ZUR ZUWEISUNG DER STYLES ---
                    tags_to_apply = []
                    if re_stat == 'Storniert':
                        tags_to_apply.append('storniert')
                    elif re_stat == 'Gutschrift':
                        tags_to_apply.append('gutschrift')
                    elif is_final and re_stat != 'Bezahlt':
                        tags_to_apply.append('finalized')
                    
                    # Wenn dies die zuvor ausgewählte Rechnung war, füge den 'selektiert' Tag hinzu
                    if re_id == selected_invoice_id:
                        tags_to_apply.append('selektiert')

                    self.tree_rechnungen_list.insert("", tk.END, values=(re_id, re_nr, re_dat, brutto_str, re_stat), tags=tuple(tags_to_apply))

                logging.info(f"{len(self.tree_rechnungen_list.get_children())} Rechnungen für Kunde ID {customer_id} geladen und gestylt.")
            except sqlite3.Error as e:
                messagebox.showerror("Fehler", f"Fehler Laden Rechnungsliste: {e}", parent=rechnung_window)
                logging.error(f"DB-Fehler Laden Rng-Liste Kunde ID {customer_id}: {e}")

        def update_totals_local():
            # ... (Funktion bleibt unverändert)
            sum_netto = 0.0
            vat_rate_str = self.entry_re_mwst.get()
            vat_rate = parse_float(vat_rate_str, 0.0) 

            for item_id_tree in self.tree_re_items.get_children():
                try:
                    values = self.tree_re_items.item(item_id_tree)['values']
                    gesamt_netto_str = str(values[-1]).replace(' €', '').strip()
                    sum_netto += parse_float(gesamt_netto_str, 0.0) 
                except (IndexError, TypeError, ValueError, KeyError) as e_sum:
                    logging.warning(f"Konnte Gesamtpreis für Posten {item_id_tree} nicht lesen/parsen: {values if 'values' in locals() else 'N/A'} - Fehler: {e_sum}.")
                    continue
            sum_mwst = sum_netto * (vat_rate / 100.0)
            sum_brutto = sum_netto + sum_mwst
            fstr = lambda v: f"{v:,.2f} €".replace('.', '#').replace(',', '.').replace('#', ',')
            self.lbl_sum_netto.config(text=f"Netto: {fstr(sum_netto)}")
            self.lbl_sum_mwst.config(text=f"MwSt. ({vat_rate:,.1f}%): {fstr(sum_mwst)}".replace('.',',')) 
            self.lbl_sum_brutto.config(text=f"Brutto: {fstr(sum_brutto)}")
            return sum_netto, sum_mwst, sum_brutto

        def clear_invoice_form_local(generate_new_number=False):
            self.current_invoice_id = None
            self.current_invoice_is_finalized = False
            self.rechnung_finalized_label.pack_forget()

            if generate_new_number:
                self.update_next_invoice_number_suggestion()
                self.entry_re_nr.delete(0, tk.END)
                self.entry_re_nr.insert(0, self.next_invoice_number_suggestion)
            else:
                self.entry_re_nr.delete(0, tk.END)
            self.entry_re_datum.delete(0, tk.END)
            self.entry_re_datum.insert(0, datetime.now().strftime("%d.%m.%Y"))
            self.entry_re_faellig.delete(0, tk.END)
            try:
                self.entry_re_faellig.insert(0, (datetime.now() + timedelta(days=14)).strftime("%d.%m.%Y"))
            except Exception: pass 
            self.entry_re_mwst.delete(0, tk.END)
            self.entry_re_mwst.insert(0, str(self.default_vat_rate).replace('.', ','))
            self.combo_re_status.set('Entwurf')
            self.text_re_bemerkung.delete('1.0', tk.END)
            for item_tree in self.tree_re_items.get_children():
                self.tree_re_items.delete(item_tree)
            
            set_form_read_only(False) # GoBD: Formular editierbar machen
            self.btn_delete_re.config(text="Entwurf löschen", state=tk.DISABLED)
            
            current_focus = self.tree_rechnungen_list.focus()
            if current_focus:
                self.tree_rechnungen_list.item(current_focus, tags=())
                self.tree_rechnungen_list.selection_remove(current_focus)
            update_totals_local()
            logging.info("Rechnungsformular zurückgesetzt.")

        def add_or_edit_item_local(item_data_to_edit=None, item_tree_id=None):
            # ... (Funktion bleibt im Wesentlichen unverändert)
            item_dialog = tk.Toplevel(rechnung_window)
            dialog_title = "Posten bearbeiten" if item_data_to_edit else "Posten hinzufügen"
            item_dialog.title(dialog_title)
            item_dialog.transient(rechnung_window)
            item_dialog.grab_set()
            item_dialog.resizable(False, False)

            dialog_frame = ttk.Frame(item_dialog, padding=10)
            dialog_frame.pack(fill=tk.BOTH, expand=True)

            template_frame_dlg = ttk.LabelFrame(dialog_frame, text="Artikelvorlagen")
            template_frame_dlg.grid(row=0, column=0, columnspan=2, sticky=tk.EW, padx=5, pady=5)
            ttk.Label(template_frame_dlg, text="Vorlage wählen:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
            
            _artikel_templates_combobox_dlg = ttk.Combobox(template_frame_dlg, width=30, state="readonly")
            _artikel_templates_combobox_dlg.grid(row=0, column=1, padx=5, pady=5, sticky=tk.EW)
            template_frame_dlg.columnconfigure(1, weight=1)

            btn_frame_templates_dlg = ttk.Frame(template_frame_dlg)
            btn_frame_templates_dlg.grid(row=0, column=2, padx=5, pady=5)
            btn_load_artikel_dlg = ttk.Button(btn_frame_templates_dlg, text="Wählen")
            btn_load_artikel_dlg.pack(side=tk.LEFT, padx=2)
            btn_save_artikel_dlg = ttk.Button(btn_frame_templates_dlg, text="Speichern")
            btn_save_artikel_dlg.pack(side=tk.LEFT, padx=2)
            btn_delete_artikel_dlg = ttk.Button(btn_frame_templates_dlg, text="Löschen")
            btn_delete_artikel_dlg.pack(side=tk.LEFT, padx=2)

            labels_dlg = ["ArtNr:", "Beschreibung:", "Menge:", "Einheit:", "Einzelpreis (€ Netto):"]
            entries_dlg = {}
            row_offset = 1
            for i, txt in enumerate(labels_dlg):
                ttk.Label(dialog_frame, text=txt).grid(row=i + row_offset, column=0, sticky=tk.W, padx=5, pady=3)
                width_val = 10 if txt in ["Menge:", "Einheit:"] else 40
                if txt == "Einzelpreis (€ Netto):": width_val = 15
                entry_widget_dlg = ttk.Entry(dialog_frame, width=width_val)
                entry_widget_dlg.grid(row=i + row_offset, column=1, sticky=tk.EW, padx=5, pady=3)
                entries_dlg[txt] = entry_widget_dlg
            dialog_frame.columnconfigure(1, weight=1)

            if item_data_to_edit:
                try:
                    entries_dlg["ArtNr:"].insert(0, item_data_to_edit[1] or "")
                    entries_dlg["Beschreibung:"].insert(0, item_data_to_edit[2] or "")
                    menge_dialog_val = str(item_data_to_edit[3]).replace('.',',')
                    preis_dialog_val = str(item_data_to_edit[5]).replace(' €','').strip().replace('.',',')
                    entries_dlg["Menge:"].insert(0, menge_dialog_val)
                    entries_dlg["Einheit:"].insert(0, item_data_to_edit[4] or "")
                    entries_dlg["Einzelpreis (€ Netto):"].insert(0, preis_dialog_val)
                except IndexError:
                    messagebox.showerror("Fehler", "Fehler beim Laden der Postendaten.", parent=item_dialog)
                    item_dialog.destroy(); return

            def save_item_dlg():
                art_nr_val = entries_dlg["ArtNr:"].get().strip()
                beschreibung_val = entries_dlg["Beschreibung:"].get().strip()
                menge_str_val = entries_dlg["Menge:"].get().strip()
                einheit_val = entries_dlg["Einheit:"].get().strip()
                preis_str_val = entries_dlg["Einzelpreis (€ Netto):"].get().strip()

                if not beschreibung_val or not menge_str_val or not preis_str_val:
                    messagebox.showwarning("Eingabe fehlt", "Beschreibung, Menge und Einzelpreis sind erforderlich.", parent=item_dialog)
                    return

                menge_val = parse_float(menge_str_val, -1.0)
                preis_val = parse_float(preis_str_val, -1.0)

                if menge_val <= 0: messagebox.showwarning("Ungültige Menge", "Menge muss > 0 sein.", parent=item_dialog); return
                if preis_val < 0: messagebox.showwarning("Ungültiger Preis", "Einzelpreis muss >= 0 sein.", parent=item_dialog); return

                gesamt_netto_val = menge_val * preis_val
                fstr_dlg = lambda v, p=2: f"{v:,.{p}f}".replace('.', '#').replace(',', '.').replace('#', ',')
                fstr_eur_dlg = lambda v: fstr_dlg(v) + " €"
                menge_str_formatted_val = str(menge_val).replace('.',',')
                new_values_dlg = (0, art_nr_val, beschreibung_val, menge_str_formatted_val, einheit_val, fstr_eur_dlg(preis_val), fstr_eur_dlg(gesamt_netto_val))

                if item_tree_id:
                    current_pos = self.tree_re_items.item(item_tree_id)['values'][0]
                    self.tree_re_items.item(item_tree_id, values=(current_pos, ) + new_values_dlg[1:])
                    logging.info(f"Rechnungsposten (TreeID: {item_tree_id}) bearbeitet.")
                else:
                    pos = len(self.tree_re_items.get_children()) + 1
                    self.tree_re_items.insert("", tk.END, values=(pos, ) + new_values_dlg[1:])
                    logging.info(f"Neuer Rechnungsposten hinzugefügt: {beschreibung_val}")
                update_totals_local()
                item_dialog.destroy()

            _artikel_data_map_dlg = {}
            _description_to_artnr_map_dlg = {}

            def _update_artikel_combobox_dlg():
                nonlocal _artikel_data_map_dlg, _description_to_artnr_map_dlg 
                _artikel_data_map_dlg = self._load_artikel_templates_dict() 
                _description_to_artnr_map_dlg.clear()
                artikel_descriptions_dlg = []
                sorted_items_dlg = sorted(_artikel_data_map_dlg.items(), key=lambda item_tuple: item_tuple[1].get('beschreibung', '').lower())
                for artnr_dlg, data_dlg in sorted_items_dlg:
                     desc_dlg = data_dlg.get('beschreibung', '')
                     if desc_dlg:
                        unique_desc_dlg = desc_dlg
                        count_dlg = 1
                        while unique_desc_dlg in _description_to_artnr_map_dlg:
                             count_dlg += 1; unique_desc_dlg = f"{desc_dlg} (ArtNr: {artnr_dlg})"
                        _description_to_artnr_map_dlg[unique_desc_dlg] = artnr_dlg
                        artikel_descriptions_dlg.append(unique_desc_dlg)
                _artikel_templates_combobox_dlg['values'] = artikel_descriptions_dlg
                if not artikel_descriptions_dlg:
                    _artikel_templates_combobox_dlg.set('')
                    btn_load_artikel_dlg.config(state=tk.DISABLED); btn_delete_artikel_dlg.config(state=tk.DISABLED)
                else:
                    btn_load_artikel_dlg.config(state=tk.NORMAL); btn_delete_artikel_dlg.config(state=tk.DISABLED)
            
            def on_artikel_combobox_select_dlg(event):
                 selected_key_dlg = _artikel_templates_combobox_dlg.get()
                 btn_delete_artikel_dlg.config(state=tk.NORMAL if selected_key_dlg in _description_to_artnr_map_dlg else tk.DISABLED)

            def load_selected_artikel_dlg():
                nonlocal _artikel_data_map_dlg, _description_to_artnr_map_dlg 
                selected_key_dlg = _artikel_templates_combobox_dlg.get()
                if not selected_key_dlg: messagebox.showwarning("Auswahl fehlt", "Vorlage wählen.", parent=item_dialog); return
                artnr_dlg = _description_to_artnr_map_dlg.get(selected_key_dlg)
                if artnr_dlg is None: messagebox.showerror("Fehler", "ArtNr nicht gefunden.", parent=item_dialog); return
                artikel_data_dlg = _artikel_data_map_dlg.get(artnr_dlg)
                if artikel_data_dlg:
                    entries_dlg["ArtNr:"].delete(0,tk.END); entries_dlg["ArtNr:"].insert(0, artnr_dlg)
                    entries_dlg["Beschreibung:"].delete(0,tk.END); entries_dlg["Beschreibung:"].insert(0, artikel_data_dlg.get('beschreibung',''))
                    entries_dlg["Einheit:"].delete(0,tk.END); entries_dlg["Einheit:"].insert(0, artikel_data_dlg.get('einheit',''))
                    entries_dlg["Einzelpreis (€ Netto):"].delete(0,tk.END); entries_dlg["Einzelpreis (€ Netto):"].insert(0, str(artikel_data_dlg.get('einzelpreis_netto',0.0)).replace('.',','))
                    if entries_dlg["Beschreibung:"].get() and entries_dlg["Einzelpreis (€ Netto):"].get(): entries_dlg["Menge:"].delete(0,tk.END); entries_dlg["Menge:"].insert(0,"1")
                    logging.info(f"Artikelvorlage '{artnr_dlg}' geladen.")
                else: messagebox.showerror("Fehler", "Details nicht gefunden.", parent=item_dialog)

            def save_current_artikel_as_template_dlg():
                art_nr_dlg_save = entries_dlg["ArtNr:"].get().strip()
                beschreibung_dlg_save = entries_dlg["Beschreibung:"].get().strip()
                einheit_dlg_save = entries_dlg["Einheit:"].get().strip()
                preis_str_dlg_save = entries_dlg["Einzelpreis (€ Netto):"].get().strip()
                if not art_nr_dlg_save or not beschreibung_dlg_save or parse_float(preis_str_dlg_save, -1.0) < 0:
                    messagebox.showwarning("Eingabe fehlt/falsch", "ArtNr, Beschreibung und gültiger Preis sind nötig.", parent=item_dialog)
                    return
                preis_float_dlg_save = parse_float(preis_str_dlg_save)
                if self._save_artikel_template_db(art_nr_dlg_save, beschreibung_dlg_save, einheit_dlg_save, preis_float_dlg_save): 
                    messagebox.showinfo("Erfolg", "Vorlage gespeichert/aktualisiert.", parent=item_dialog)
                    _update_artikel_combobox_dlg()
                    for desc_key, artnr_val_loop in _description_to_artnr_map_dlg.items():
                        if artnr_val_loop == art_nr_dlg_save:
                            _artikel_templates_combobox_dlg.set(desc_key)
                            on_artikel_combobox_select_dlg(None)
                            break
            
            def delete_selected_artikel_dlg():
                selected_key_dlg = _artikel_templates_combobox_dlg.get()
                if not selected_key_dlg: messagebox.showwarning("Auswahl fehlt", "Vorlage zum Löschen wählen.", parent=item_dialog); return
                artnr_to_delete_dlg = _description_to_artnr_map_dlg.get(selected_key_dlg)
                if artnr_to_delete_dlg and messagebox.askyesno("Löschen", f"Vorlage '{selected_key_dlg}' löschen?", parent=item_dialog, icon=messagebox.WARNING):
                    if self._delete_artikel_template_db(artnr_to_delete_dlg): 
                        messagebox.showinfo("Erfolg", "Vorlage gelöscht.", parent=item_dialog)
                        _update_artikel_combobox_dlg()
                        _artikel_templates_combobox_dlg.set('')

            btn_load_artikel_dlg.config(command=load_selected_artikel_dlg)
            btn_save_artikel_dlg.config(command=save_current_artikel_as_template_dlg)
            btn_delete_artikel_dlg.config(command=delete_selected_artikel_dlg)
            _artikel_templates_combobox_dlg.bind("<<ComboboxSelected>>", on_artikel_combobox_select_dlg)
            _update_artikel_combobox_dlg()
            if not _artikel_templates_combobox_dlg['values']:
                 btn_load_artikel_dlg.config(state=tk.DISABLED); btn_delete_artikel_dlg.config(state=tk.DISABLED)
            
            button_frame_ok_cancel = ttk.Frame(item_dialog); button_frame_ok_cancel.pack(pady=10) 
            ttk.Button(button_frame_ok_cancel, text="OK", command=save_item_dlg).pack(side=tk.LEFT, padx=5)
            ttk.Button(button_frame_ok_cancel, text="Abbrechen", command=item_dialog.destroy).pack(side=tk.LEFT, padx=5)
            if entries_dlg: entries_dlg["ArtNr:"].focus_set()


        def edit_selected_item_local():
            selected_tree_item = self.tree_re_items.focus()
            if selected_tree_item:
                item_data_val = self.tree_re_items.item(selected_tree_item)['values']
                add_or_edit_item_local(item_data_to_edit=item_data_val, item_tree_id=selected_tree_item)
            else:
                messagebox.showwarning("Auswahl fehlt", "Posten zum Bearbeiten auswählen.", parent=rechnung_window)

        def delete_selected_item_local():
            selected_tree_item = self.tree_re_items.focus()
            if selected_tree_item:
                if messagebox.askyesno("Löschen bestätigen", "Ausgewählten Posten löschen?", icon=messagebox.QUESTION, parent=rechnung_window):
                    self.tree_re_items.delete(selected_tree_item)
                    logging.info(f"Posten (TreeID: {selected_tree_item}) aus Ansicht gelöscht.")
                    for i, item_id_in_treeview in enumerate(self.tree_re_items.get_children()):
                         current_values_list = list(self.tree_re_items.item(item_id_in_treeview)['values'])
                         current_values_list[0] = i + 1
                         self.tree_re_items.item(item_id_in_treeview, values=tuple(current_values_list))
                    update_totals_local()
                    self.btn_edit_item.config(state=tk.DISABLED)
                    self.btn_delete_item.config(state=tk.DISABLED)
            else:
                messagebox.showwarning("Auswahl fehlt", "Posten zum Löschen auswählen.", parent=rechnung_window)

        def on_item_select_local(event=None):
             # GoBD: Bearbeitung nur wenn Rechnung nicht finalisiert ist
             if self.current_invoice_is_finalized:
                 state_val = tk.DISABLED
             else:
                 state_val = tk.NORMAL if self.tree_re_items.focus() else tk.DISABLED
             self.btn_edit_item.config(state=state_val); self.btn_delete_item.config(state=state_val)

        def set_form_read_only(is_readonly):
            """Hilfsfunktion, um das Formular schreibgeschützt zu machen."""
            self.current_invoice_is_finalized = is_readonly
            state = 'readonly' if is_readonly else 'normal'
            entry_state = 'readonly' if is_readonly else 'normal' # Entries brauchen 'readonly'
            
            self.entry_re_nr.config(state=entry_state)
            self.entry_re_datum.config(state=entry_state)
            self.entry_re_faellig.config(state=entry_state)
            self.entry_re_mwst.config(state=entry_state)
            self.text_re_bemerkung.config(state='disabled' if is_readonly else 'normal')
            
            # Status kann immer geändert werden, außer bei 'Storniert'
            status = self.combo_re_status.get()
            if is_readonly and status in ('Storniert', 'Gutschrift'):
                self.combo_re_status.config(state='disabled')
            else:
                 self.combo_re_status.config(state='readonly')
            
            # Buttons
            self.btn_add_item.config(state='disabled' if is_readonly else 'normal')
            self.btn_edit_item.config(state='disabled') # Wird durch Auswahl gesteuert
            self.btn_delete_item.config(state='disabled') # Wird durch Auswahl gesteuert
            self.btn_save_re.config(state='disabled' if is_readonly else 'normal')
            self.btn_finalize_re.config(state='disabled') # Speziell gesteuert
            self.btn_print_re.config(state='normal' if self.current_invoice_id else 'disabled')
            
            # Löschen-Button nur für Entwürfe
            is_draft = self.combo_re_status.get() == 'Entwurf'
            self.btn_delete_re.config(state='disabled' if is_readonly or not is_draft or not self.current_invoice_id else 'normal')
            
            if is_readonly:
                self.rechnung_finalized_label.pack(side=tk.TOP, fill=tk.X, pady=5)
            else:
                self.rechnung_finalized_label.pack_forget()
        
        def load_invoice_details_local(invoice_id_to_load_val):
            clear_invoice_form_local(generate_new_number=False)
            self.current_invoice_id = invoice_id_to_load_val
            try:
                cursor.execute("SELECT rechnungsnummer, rechnungsdatum, faelligkeitsdatum, mwst_prozent, status, bemerkung, is_finalized FROM rechnungen WHERE id=?", (invoice_id_to_load_val,))
                re_header = cursor.fetchone()
                if not re_header:
                    messagebox.showerror("Fehler", f"Rechnung ID {invoice_id_to_load_val} nicht gefunden.", parent=rechnung_window)
                    self.current_invoice_id = None; return
                
                re_nr, re_dat, re_faell, re_mwst, re_stat, re_bem, is_final = re_header
                self.entry_re_nr.delete(0, tk.END); self.entry_re_nr.insert(0, re_nr or "")
                self.entry_re_datum.delete(0, tk.END); self.entry_re_datum.insert(0, re_dat or "")
                self.entry_re_faellig.delete(0, tk.END); self.entry_re_faellig.insert(0, re_faell or "")
                self.entry_re_mwst.delete(0, tk.END); self.entry_re_mwst.insert(0, str(re_mwst if re_mwst is not None else self.default_vat_rate).replace('.', ','))
                if re_stat not in self.combo_re_status['values']:
                    self.combo_re_status['values'] = list(self.combo_re_status['values']) + [re_stat]
                
                self.combo_re_status.set(re_stat or 'Entwurf')
                self.text_re_bemerkung.delete('1.0', tk.END); self.text_re_bemerkung.insert('1.0', re_bem or "")
                
                cursor.execute("SELECT position, artikelnummer, beschreibung, menge, einheit, einzelpreis_netto, gesamtpreis_netto FROM rechnungsposten WHERE rechnung_id=? ORDER BY position ASC", (invoice_id_to_load_val,))
                fstr_display = lambda v, p=2: f"{v:,.{p}f}".replace('.', '#').replace(',', '.').replace('#', ',')
                for row_item in cursor.fetchall():
                    pos, artnr_item, desc_item, qty_item, unit_item, price_item, total_item = row_item
                    price_str_item = fstr_display(price_item) + " €" if price_item is not None else ""
                    total_str_item = fstr_display(total_item) + " €" if total_item is not None else ""
                    qty_str_item = str(qty_item).replace('.', ',') if qty_item is not None else ""
                    self.tree_re_items.insert("", tk.END, values=(pos, artnr_item or "", desc_item or "", qty_str_item, unit_item or "", price_str_item, total_str_item))
                
                update_totals_local()
                self.btn_save_re.config(text="Änderungen speichern")

                # GoBD: UI-Status setzen
                set_form_read_only(is_final)
                
                # Finalisieren-Button nur anzeigen, wenn es ein gespeicherter Entwurf ist
                if not is_final and self.current_invoice_id and re_stat == 'Entwurf':
                    self.btn_finalize_re.config(state=tk.NORMAL)
                else:
                    self.btn_finalize_re.config(state=tk.DISABLED)

                logging.info(f"Rechnungsdetails für ID {invoice_id_to_load_val} (Nr: {re_nr}) geladen. Finalisiert: {is_final}")
            except sqlite3.Error as e_db:
                messagebox.showerror("DB Fehler", f"Fehler Laden Rng-Details: {e_db}", parent=rechnung_window)
                logging.error(f"DB-Fehler Laden Rng-Details ID {invoice_id_to_load_val}: {e_db}")
                clear_invoice_form_local()
            except Exception as e_gen:
                messagebox.showerror("Allg. Fehler", f"Unerwarteter Fehler Laden Rng: {e_gen}", parent=rechnung_window)
                logging.exception(f"Fehler Laden Rng ID {invoice_id_to_load_val}:")
                clear_invoice_form_local()

        def on_rechnung_list_select_local(event=None):
            selected_tree_item = self.tree_rechnungen_list.focus()
            for item_in_list in self.tree_rechnungen_list.get_children():
                # Behalte bestehende Tags (finalized, storniert) bei
                current_tags = list(self.tree_rechnungen_list.item(item_in_list, 'tags'))
                if 'selektiert' in current_tags:
                    current_tags.remove('selektiert')
                self.tree_rechnungen_list.item(item_in_list, tags=tuple(current_tags))
            if selected_tree_item:
                current_tags = list(self.tree_rechnungen_list.item(selected_tree_item, 'tags'))
                current_tags.append('selektiert')
                self.tree_rechnungen_list.item(selected_tree_item, tags=tuple(current_tags))
                self.btn_prepare_for_tool.config(state=tk.NORMAL if selected_tree_item else tk.DISABLED)

        def on_rechnung_list_double_click_local(event):
            selected_tree_item = self.tree_rechnungen_list.focus()
            if selected_tree_item:
                try:
                    invoice_id_to_load_dbl = int(self.tree_rechnungen_list.item(selected_tree_item)['values'][0])
                    load_invoice_details_local(invoice_id_to_load_dbl)
                except (IndexError, TypeError, KeyError, ValueError):
                    logging.warning("Index/Type/Key/Value Error bei Doppelklick Rng-Liste.")
                except Exception as e_double_click:
                    logging.error(f"Fehler bei Doppelklick Rng-Liste: {e_double_click}")
        
        def save_invoice_local(kunde_id_param_local):
            # GoBD: Diese Funktion speichert nur, finalisiert aber nicht.
            if self.current_invoice_is_finalized:
                # Speichere nur Status- und Bemerkungsänderungen
                new_status = self.combo_re_status.get()
                new_bemerkung = self.text_re_bemerkung.get("1.0", tk.END).strip()
                db_cursor_status = self.conn.cursor()
                try:
                    db_cursor_status.execute("SELECT status, bemerkung FROM rechnungen WHERE id=?", (self.current_invoice_id,))
                    old_status, old_bemerkung = db_cursor_status.fetchone()
                    changes_details = []
                    if old_status != new_status:
                        changes_details.append(f"Status von '{old_status}' zu '{new_status}'")
                    if old_bemerkung != new_bemerkung:
                        changes_details.append("Bemerkung geändert.")
                    
                    if changes_details:
                        db_cursor_status.execute("UPDATE rechnungen SET status=?, bemerkung=? WHERE id=?", (new_status, new_bemerkung, self.current_invoice_id))
                        self._log_audit_event("RECHNUNG_STATUS_AENDERUNG", self.current_invoice_id, details="; ".join(changes_details))
                        self.conn.commit()
                        messagebox.showinfo("Erfolg", "Statusänderung gespeichert.", parent=rechnung_window)
                        load_rechnungen_list_local()
                        load_invoice_details_local(self.current_invoice_id)
                except sqlite3.Error as e:
                    self.conn.rollback()
                    messagebox.showerror("DB Fehler", f"Fehler beim Speichern der Statusänderung:\n{e}", parent=rechnung_window)
                return

            # Regulärer Speichervorgang für Entwürfe
            re_nr = self.entry_re_nr.get().strip()
            re_dat_str = self.entry_re_datum.get().strip()
            re_faell_str = self.entry_re_faellig.get().strip()
            re_mwst_str = self.entry_re_mwst.get().strip()
            re_stat = self.combo_re_status.get()
            re_bem = self.text_re_bemerkung.get("1.0", tk.END).strip()

            if not re_nr: messagebox.showwarning("Eingabe fehlt", "Rechnungsnummer erforderlich.", parent=rechnung_window); return
            try: datetime.strptime(re_dat_str, "%d.%m.%Y")
            except ValueError: messagebox.showwarning("Ungültiges Datum", "Gültiges Rechnungsdatum (TT.MM.JJJJ) eingeben.", parent=rechnung_window); return
            if re_faell_str:
                 try: datetime.strptime(re_faell_str, "%d.%m.%Y")
                 except ValueError: messagebox.showwarning("Ungültiges Datum", "Gültiges Fälligkeitsdatum (TT.MM.JJJJ) oder leer lassen.", parent=rechnung_window); return
            
            re_mwst_val = parse_float(re_mwst_str, -1.0)
            if re_mwst_val < 0: messagebox.showwarning("Ungültiger MwSt.-Satz", "Gültigen MwSt.-Satz (%) eingeben.", parent=rechnung_window); return
            if not self.tree_re_items.get_children(): messagebox.showwarning("Keine Posten", "Mindestens einen Posten hinzufügen.", parent=rechnung_window); return
            if re_stat != 'Entwurf':
                messagebox.showwarning("Statusfehler", "Neue oder geänderte Rechnungen müssen als 'Entwurf' gespeichert werden.\nNutzen Sie 'Finalisieren & Buchen', um die Rechnung festzuschreiben.", parent=rechnung_window)
                self.combo_re_status.set('Entwurf')
                return

            sum_netto, sum_mwst, sum_brutto = update_totals_local()
            
            db_cursor_save = self.conn.cursor()
            try:
                actual_invoice_id_for_this_save = self.current_invoice_id
                
                if actual_invoice_id_for_this_save is not None: # Update eines Entwurfs
                    db_cursor_save.execute("SELECT id FROM rechnungen WHERE rechnungsnummer=? AND id!=?", (re_nr, actual_invoice_id_for_this_save))
                    if db_cursor_save.fetchone():
                        messagebox.showerror("Fehler", f"Rechnungsnummer '{re_nr}' bereits vergeben.", parent=rechnung_window); return
                    
                    db_cursor_save.execute("UPDATE rechnungen SET rechnungsnummer=?, rechnungsdatum=?, faelligkeitsdatum=?, mwst_prozent=?, summe_netto=?, summe_mwst=?, summe_brutto=?, status=?, bemerkung=?, offener_betrag=? WHERE id=?",
                       (re_nr, re_dat_str, re_faell_str or None, re_mwst_val, sum_netto, sum_mwst, sum_brutto, re_stat, re_bem, sum_brutto, actual_invoice_id_for_this_save))
                    db_cursor_save.execute("DELETE FROM rechnungsposten WHERE rechnung_id=?", (actual_invoice_id_for_this_save,))
                    logging.info(f"Rechnungs-Entwurf ID {actual_invoice_id_for_this_save} aktualisiert (Nr: {re_nr}).")
                    self._log_audit_event("RECHNUNG_ENTWURF_GEAENDERT", actual_invoice_id_for_this_save, f"Entwurf Nr. {re_nr} geändert.")

                else: # Erstellen eines neuen Entwurfs
                    db_cursor_save.execute("SELECT id FROM rechnungen WHERE rechnungsnummer=?", (re_nr,))
                    if db_cursor_save.fetchone():
                        messagebox.showerror("Fehler", f"Rechnungsnummer '{re_nr}' existiert bereits.", parent=rechnung_window); return
                    
                    db_cursor_save.execute("INSERT INTO rechnungen (kunde_id, rechnungsnummer, rechnungsdatum, faelligkeitsdatum, mwst_prozent, summe_netto, summe_mwst, summe_brutto, status, bemerkung, offener_betrag, is_finalized) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
                       (kunde_id_param_local, re_nr, re_dat_str, re_faell_str or None, re_mwst_val, sum_netto, sum_mwst, sum_brutto, re_stat, re_bem, sum_brutto))
                    
                    actual_invoice_id_for_this_save = db_cursor_save.lastrowid
                    logging.info(f"Neuer Rechnungs-Entwurf ID {actual_invoice_id_for_this_save} erstellt (Nr: {re_nr}).")
                    self._log_audit_event("RECHNUNG_ENTWURF_ERSTELLT", actual_invoice_id_for_this_save, f"Entwurf Nr. {re_nr} erstellt.")

                new_items_for_db = [] 
                for item_id_in_tree in self.tree_re_items.get_children():
                    vals_item = self.tree_re_items.item(item_id_in_tree)['values']
                    pos_item, artnr_posten, desc_item, qty_str_tree, unit_item, price_netto_str_tree, _ = vals_item[:7]
                    qty_item = parse_float(qty_str_tree, 0.0)
                    price_netto_item = parse_float(price_netto_str_tree.replace(' €',''), 0.0)
                    total_netto_calculated = qty_item * price_netto_item
                    db_item_tuple = (actual_invoice_id_for_this_save, int(pos_item), artnr_posten, desc_item, qty_item, unit_item, price_netto_item, total_netto_calculated)
                    new_items_for_db.append(db_item_tuple)

                if new_items_for_db:
                    db_cursor_save.executemany("INSERT INTO rechnungsposten (rechnung_id, position, artikelnummer, beschreibung, menge, einheit, einzelpreis_netto, gesamtpreis_netto) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", new_items_for_db)
                
                self.conn.commit()
                messagebox.showinfo("Erfolg", "Rechnungs-Entwurf erfolgreich gespeichert.", parent=rechnung_window)
                
                load_rechnungen_list_local()
                if actual_invoice_id_for_this_save:
                    load_invoice_details_local(actual_invoice_id_for_this_save) 
                self.update_next_invoice_number_suggestion()

            except sqlite3.Error as e:
                self.conn.rollback()
                messagebox.showerror("DB Fehler", f"Fehler beim Speichern des Entwurfs:\n{e}", parent=rechnung_window)
            except Exception as e:
                self.conn.rollback()
                messagebox.showerror("Allgemeiner Fehler", f"Unerwarteter Fehler beim Speichern des Entwurfs:\n{e}", parent=rechnung_window)
                logging.exception(f"Fehler Speichern Entwurf (Nr: {re_nr}):")

        def finalize_invoice_local():
            if not self.current_invoice_id or self.current_invoice_is_finalized:
                return
            
            re_nr = self.entry_re_nr.get().strip()
            if not messagebox.askyesno("Rechnung finalisieren", f"Soll die Rechnung Nr. '{re_nr}' jetzt finalisiert und gebucht werden?\n\nDanach sind KEINE Änderungen mehr möglich!", icon=messagebox.WARNING, parent=rechnung_window):
                return
                
            db_cursor_finalize = self.conn.cursor()
            try:
                # Lagerbestände abbuchen
                db_cursor_finalize.execute("SELECT artikelnummer, menge FROM rechnungsposten WHERE rechnung_id=?", (self.current_invoice_id,))
                items_to_book_out = [{'artikelnummer': row[0], 'menge': row[1]} for row in db_cursor_finalize.fetchall()]
                self._book_stock_change(db_cursor_finalize, items_to_book_out, 'out', self.current_invoice_id)
                
                # Rechnung auf finalisiert und 'Offen' setzen
                db_cursor_finalize.execute("UPDATE rechnungen SET is_finalized = 1, status = 'Offen' WHERE id=?", (self.current_invoice_id,))
                
                self._log_audit_event("RECHNUNG_FINALISIERT", self.current_invoice_id, f"Rechnung Nr. {re_nr} finalisiert und auf 'Offen' gesetzt. Lagerbestand gebucht.")
                self.conn.commit()
                
                messagebox.showinfo("Erfolg", "Rechnung wurde finalisiert und ist nun unveränderbar.", parent=rechnung_window)
                load_rechnungen_list_local()
                load_invoice_details_local(self.current_invoice_id)
                
            except sqlite3.Error as e:
                self.conn.rollback()
                messagebox.showerror("DB Fehler", f"Fehler beim Finalisieren der Rechnung:\n{e}", parent=rechnung_window)
            except Exception as e:
                self.conn.rollback()
                messagebox.showerror("Allgemeiner Fehler", f"Unerwarteter Fehler beim Finalisieren:\n{e}", parent=rechnung_window)
                logging.exception(f"Fehler Finalisieren (ID: {self.current_invoice_id}):")

        def print_invoice_local():
            if not self.current_invoice_id: 
                messagebox.showwarning("Keine Rechnung", "Rechnung speichern oder auswählen.", parent=rechnung_window); return
            try:
                pdf_cursor_print = self.conn.cursor()
                pdf_cursor_print.execute("SELECT * FROM rechnungen WHERE id=?", (self.current_invoice_id,)); 
                rechnung_db_data = pdf_cursor_print.fetchone();
                if not rechnung_db_data: raise ValueError("Rechnung nicht in DB gefunden")
                re_col_names = [d[0] for d in pdf_cursor_print.description]; 
                rechnung_dict = dict(zip(re_col_names, rechnung_db_data))
                
                pdf_cursor_print.execute("SELECT * FROM rechnungsposten WHERE rechnung_id=? ORDER BY position ASC", (self.current_invoice_id,)); 
                posten_db_data = pdf_cursor_print.fetchall()
                posten_col_names = [d[0] for d in pdf_cursor_print.description]; 
                posten_list = [dict(zip(posten_col_names, row_val)) for row_val in posten_db_data]
                
                pdf_cursor_print.execute("SELECT id, name, vorname, titel_firma, strasse, hausnummer, plz, ort, zifferncode, email, telefon FROM kunden WHERE id=?", (rechnung_dict['kunde_id'],)); 
                kunde_db_data = pdf_cursor_print.fetchone()
                if not kunde_db_data: raise ValueError("Kunde nicht in DB gefunden")
                kunden_col_names = [d[0] for d in pdf_cursor_print.description]; 
                kunde_dict = dict(zip(kunden_col_names, kunde_db_data))
                
                self.generate_rechnung_pdf(rechnung_dict, posten_list, kunde_dict) 
            except (sqlite3.Error, ValueError) as e: 
                messagebox.showerror("DB/Daten Fehler", f"Fehler Laden PDF-Daten: {e}", parent=rechnung_window); 
                logging.error(f"Fehler Laden PDF-Daten Rng-ID {self.current_invoice_id}: {e}")
            except Exception as e: 
                messagebox.showerror("PDF Fehler", f"Fehler Erstellen PDF: {e}", parent=rechnung_window); 
                logging.exception(f"Fehler Erstellen PDF Rng-ID {self.current_invoice_id}:")


        def delete_invoice_local():
            # GoBD: Nur Entwürfe können gelöscht werden
            if not self.current_invoice_id or self.current_invoice_is_finalized: 
                messagebox.showerror("Fehler", "Nur nicht finalisierte Rechnungs-Entwürfe können gelöscht werden.", parent=rechnung_window)
                return
            
            re_nr_del = self.entry_re_nr.get();
            confirm_del = messagebox.askyesno("Löschen bestätigen", f"Rechnungs-Entwurf '{re_nr_del}' (ID: {self.current_invoice_id}) wirklich löschen?", icon=messagebox.WARNING, parent=rechnung_window)
            if confirm_del:
                db_cursor_del_inv = self.conn.cursor()
                try:
                    db_cursor_del_inv.execute("DELETE FROM rechnungen WHERE id=? AND is_finalized = 0", (self.current_invoice_id,)); 
                    deleted_count = db_cursor_del_inv.rowcount
                    
                    if deleted_count > 0: 
                        self.conn.commit()
                        self._log_audit_event("RECHNUNG_ENTWURF_GELOESCHT", self.current_invoice_id, f"Entwurf Nr. {re_nr_del} gelöscht.")
                        messagebox.showinfo("Erfolg", f"Rechnungs-Entwurf '{re_nr_del}' gelöscht.", parent=rechnung_window); 
                        logging.info(f"Rechnungs-Entwurf ID {self.current_invoice_id} (Nr: {re_nr_del}) gelöscht."); 
                        clear_invoice_form_local(True); 
                        load_rechnungen_list_local()
                    else: 
                        self.conn.rollback()
                        messagebox.showerror("Fehler", "Entwurf nicht gelöscht (evtl. zwischenzeitlich finalisiert?).", parent=rechnung_window); 
                        logging.error(f"Fehler Löschen: Entwurf ID {self.current_invoice_id} nicht gefunden/gelöscht.")
                except sqlite3.Error as e: 
                    self.conn.rollback()
                    messagebox.showerror("DB Fehler", f"Fehler Löschen Entwurf: {e}", parent=rechnung_window); 
                except Exception as e:
                    self.conn.rollback()
                    messagebox.showerror("Allg. Fehler", f"Unerwarteter Fehler Löschen: {e}", parent=rechnung_window); 

  
        def handle_new_rechnung_click():
            """Ruft die Formular-Leerung zweimal mit einer kurzen Pause auf,
               um hartnäckige UI-Timing-Probleme zu umgehen."""
            clear_invoice_form_local(True)
            rechnung_window.after(10, lambda: clear_invoice_form_local(True))

        # --- Zuweisung der Befehle zu den Buttons ---
        self.tree_re_items.bind("<Double-1>", lambda event: edit_selected_item_local())
        self.btn_add_item.config(command=lambda: add_or_edit_item_local())
        self.tree_re_items.bind("<<TreeviewSelect>>", on_item_select_local)
        self.btn_edit_item.config(command=edit_selected_item_local)
        self.btn_delete_item.config(command=delete_selected_item_local)
        self.btn_save_re.config(command=lambda: save_invoice_local(customer_id))
        self.btn_finalize_re.config(command=finalize_invoice_local)
        self.btn_print_re.config(command=print_invoice_local)
        self.btn_new_re.config(command=handle_new_rechnung_click)
        self.btn_delete_re.config(command=delete_invoice_local)
        
        # ### KORRIGIERTE ZUWEISUNG ###
        self.btn_prepare_for_tool.config(command=prepare_invoice_for_external_tool) # <-- Die Klammer war hier das Problem

        # --- Zuweisung der Events zu den Listen ---
        self.tree_rechnungen_list.bind("<<TreeviewSelect>>", on_rechnung_list_select_local)
        self.tree_rechnungen_list.bind("<Double-1>", on_rechnung_list_double_click_local)

        # --- Initiales Laden der Daten ---
        load_rechnungen_list_local()
        if create_new:
            clear_invoice_form_local(True)
        elif self.tree_rechnungen_list.get_children():
            first_invoice_item = self.tree_rechnungen_list.get_children()[0]
            self.tree_rechnungen_list.focus(first_invoice_item)
            self.tree_rechnungen_list.selection_set(first_invoice_item)
            try:
                on_rechnung_list_select_local(None) # Damit Buttons gleich aktiv sind
                invoice_id_initial = int(self.tree_rechnungen_list.item(first_invoice_item)['values'][0])
                load_invoice_details_local(invoice_id_initial)
            except (IndexError, TypeError, KeyError, ValueError):
                logging.error("Fehler Laden initialer Rng-Details.")
                clear_invoice_form_local(True)
        else:
            clear_invoice_form_local(True)
    
    #... Restliche Funktionen (generate_rechnung_pdf, _load_artikel_templates_dict, etc.)
    #... bleiben größtenteils gleich, aber die _save_artikel... und _delete_artikel...
    #... sollten nun auch das Audit-Log verwenden.


    def _create_salutation(self, kunde_data):
        """Erstellt eine professionelle, personalisierte Anrede."""
        titel_firma = kunde_data.get('titel_firma', '').strip()
        vorname = kunde_data.get('vorname', '').strip()
        name = kunde_data.get('name', '').strip()

        # Fall 1: Es ist primär eine Firma.
        if titel_firma and not vorname and not name:
            return "Sehr geehrte Damen und Herren,"

        # Fall 2: Es ist eine Person (ggf. mit Titel/Firma als Zusatz).
        # Wir bauen die Anrede aus den verfügbaren Teilen zusammen.
        anrede_parts = ["Guten Tag"]
        if titel_firma: # Behandelt Titel wie "Dr." oder auch eine Firma
            anrede_parts.append(titel_firma)
        if vorname:
            anrede_parts.append(vorname)
        if name:
            anrede_parts.append(name)
        
        # Füge ein Komma am Ende hinzu, wenn mehr als nur "Guten Tag" da steht.
        if len(anrede_parts) > 1:
            return " ".join(anrede_parts) + ","
        
        # Fallback, falls alle Namensfelder leer sind
        return "Sehr geehrte Damen und Herren,"   
    

    def generate_rechnung_pdf(self, rechnung_data, posten_data, kunde_data):
        # --- ANPASSUNG FÜR GUTSCHRIFTEN: Titel und Dateiname je nach Typ anpassen ---
        is_gutschrift = rechnung_data.get('status') == 'Gutschrift'
        
        rechnungsnummer = rechnung_data.get('rechnungsnummer', 'FEHLER')
        kundennummer = kunde_data.get('zifferncode', 'N/A')

        if is_gutschrift:
            pdf_titel_text = f"Gutschrift Nr. {rechnungsnummer}"
            pdf_dateiname_base = f"Gutschrift_{rechnungsnummer}_Kd{kundennummer}.pdf"
        else:
            pdf_titel_text = f"Rechnung Nr. {rechnungsnummer}"
            pdf_dateiname_base = f"Rechnung_{rechnungsnummer}_Kd{kundennummer}.pdf"

        # --- Dateipfad erstellen (Logik bleibt gleich) ---
        output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), pdf_dateiname_base)
        if kundennummer != 'N/A' and str(kundennummer).strip() and self.document_base_path:
            customer_folder = self.create_customer_document_folder(kunde_data['id'], kundennummer)
            if customer_folder:
                output_path_in_folder = os.path.join(customer_folder, pdf_dateiname_base)
                if os.access(customer_folder, os.W_OK):
                    output_path = output_path_in_folder
        # --- Ende Dateipfad ---

        try:
            width, height = A4
            styles = getSampleStyleSheet()
            style_normal = styles['Normal']
            style_bold = ParagraphStyle(name='BoldLeft', parent=styles['Heading3'], alignment=TA_LEFT, fontSize=10)
            style_normal.fontSize = 10
            style_right = ParagraphStyle(name='RightAlign', parent=style_normal, alignment=TA_RIGHT)
            style_firma = ParagraphStyle(name='Firma', parent=style_normal, fontSize=8)
            style_normal_right = ParagraphStyle(name='NormalRight', parent=style_normal, alignment=TA_RIGHT)
            style_h1 = styles['h1']

            margin = 20 * mm
            content_width = width - 2 * margin
            story = []
            story.append(Spacer(1, 20 * mm))

            # --- Logo (Logik bleibt gleich) ---
            logo_path_for_pdf = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo_pdf.png") 
            if os.path.exists(logo_path_for_pdf):
                # ... (Logo-Code unverändert) ...
                try:
                    img_temp = Image(logo_path_for_pdf) 
                    img_height_pdf = 40 * mm * (img_temp._getHeight() / img_temp._getWidth())
                    logo_img_pdf = Image(logo_path_for_pdf, width=40*mm, height=img_height_pdf)
                    logo_img_pdf.hAlign = 'RIGHT'
                    story.append(logo_img_pdf)
                    story.append(Spacer(1, 5 * mm))
                except Exception as logo_err:
                    logging.error(f"Fehler Laden/Verarbeiten des PDF-Logos: {logo_err}")


            # --- Adressblock (Logik bleibt gleich) ---
            company_line = f"{self.company_details.get('name', '')}, {self.company_details.get('address', '')}, {self.company_details.get('zip_city', '')}"
            story.append(Paragraph(company_line, style_firma))
            story.append(Spacer(1, 5 * mm))

            address_lines = []
            if kunde_data.get('titel_firma'):
                 address_lines.append(Paragraph(kunde_data['titel_firma'], style_normal)) 
            address_lines.extend([
                Paragraph(f"{kunde_data.get('vorname','')} {kunde_data.get('name','')}", style_normal),
                Paragraph(f"{kunde_data.get('strasse','')} {kunde_data.get('hausnummer','')}", style_normal),
                Paragraph(f"{kunde_data.get('plz','')} {kunde_data.get('ort','')}", style_normal)
            ]);
            for line_addr in address_lines:
                if line_addr.getPlainText().strip(): story.append(line_addr)
            
            story.append(Spacer(1, 15 * mm)); 
            
            # --- Rechnungsdetails rechts oben (Logik bleibt gleich) ---
            re_details = [f"<b>Kundennummer:</b> {kundennummer}", f"<b>Belegnummer:</b> {rechnungsnummer}", f"<b>Datum:</b> {rechnung_data.get('rechnungsdatum', '')}"]
            if rechnung_data.get('faelligkeitsdatum'): re_details.append(f"<b>Zahlbar bis:</b> {rechnung_data.get('faelligkeitsdatum', '')}")
            for detail_re in re_details: story.append(Paragraph(detail_re, style_right))
            
            story.append(Spacer(1, 10 * mm)); 

            # --- ANPASSUNG FÜR GUTSCHRIFTEN: Dokumententitel und Einleitungstext ---
            story.append(Paragraph(pdf_titel_text, style_h1)) # Verwendet den oben definierten Titel
            story.append(Spacer(1, 5 * mm))

            # Für eine Gutschrift nutzen wir den Bemerkungstext als Einleitung
            if is_gutschrift:
                bemerkung_text_intro = rechnung_data.get('bemerkung', '').replace('\n', '<br/>')
                story.append(Paragraph(bemerkung_text_intro, style_normal))
            else:
                 # Standard-Einleitung, wenn KEINE Bemerkung vorhanden ist.
                # Ruft die neue, intelligente Funktion für die Anrede auf.
                anrede = self._create_salutation(kunde_data)
                
                story.append(Paragraph(anrede, style_normal))
                story.append(Spacer(1, 3 * mm))
                story.append(Paragraph("vielen Dank für Ihr Vertrauen. Anbei erhalten Sie die Rechnung für die von uns erbrachten Leistungen:", style_normal))
            
            story.append(Spacer(1, 10 * mm))
            
            # --- Tabelle und Summen (Logik bleibt gleich, da sie negative Zahlen korrekt verarbeitet) ---
            table_header = ["Pos", "ArtNr", "Beschreibung", "Menge", "Einheit", "Einzelpr. €", "Gesamt €"]; 
            table_data = [table_header]; 
            fstr_pdf = lambda v, p=2: f"{v:,.{p}f}".replace('.', '#').replace(',', '.').replace('#', ',')
            for item_pdf in posten_data:
                menge_pdf = item_pdf.get('menge', 0.0)
                # Bei Gutschriften die Menge für die Anzeige positiv machen (der Preis ist schon negativ)
                menge_anzeige = -menge_pdf if is_gutschrift and menge_pdf < 0 else menge_pdf
                menge_str_pdf = str(menge_anzeige).replace('.', ',')
                
                table_data.append([
                    item_pdf.get('position', ''),
                    item_pdf.get('artikelnummer', ''),
                    Paragraph(item_pdf.get('beschreibung', ''), style_normal),
                    menge_str_pdf,
                    item_pdf.get('einheit', ''),
                    fstr_pdf(item_pdf.get('einzelpreis_netto', 0.0)),
                    fstr_pdf(item_pdf.get('gesamtpreis_netto', 0.0))
                ])
            
            col_w = [15*mm, 25*mm, content_width - (15+25+20+15+30+30)*mm, 20*mm, 15*mm, 30*mm, 30*mm]; 
            items_table = Table(table_data, colWidths=col_w)
            items_table.setStyle(TableStyle([ ('BACKGROUND', (0,0), (-1,0), grey), ('TEXTCOLOR', (0,0), (-1,0), black), ('ALIGN', (0,0), (-1,-1), 'CENTER'), ('ALIGN', (2,1), (2,-1), 'LEFT'), ('ALIGN', (0,1), (0,-1), 'RIGHT'), ('ALIGN', (3,1), (3,-1), 'RIGHT'), ('ALIGN', (5,1), (-1,-1), 'RIGHT'), ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'), ('BOTTOMPADDING', (0,0), (-1,0), 6), ('BACKGROUND', (0,1), (-1,-1), '#F0F0F0'), ('GRID', (0,0), (-1,-1), 0.5, black), ('VALIGN', (0,0), (-1,-1), 'MIDDLE'), ])); 
            story.append(items_table); 
            story.append(Spacer(1, 5 * mm))

            # Summenblock
            summen_data = [ 
                ['Summe Netto:', fstr_pdf(rechnung_data.get('summe_netto', 0.0)) + " €"], 
                [f'zzgl. {rechnung_data.get("mwst_prozent", 0.0):,.1f}% MwSt.:'.replace('.',','), fstr_pdf(rechnung_data.get('summe_mwst', 0.0)) + " €"], 
                [Paragraph('<b>Gesamtbetrag Brutto:</b>', style_normal_right), Paragraph(f"  <b>{fstr_pdf(rechnung_data.get('summe_brutto', 0.0))} €</b>", style_normal_right)], 
            ]
            summen_table = Table(summen_data, colWidths=[content_width - 40*mm, 40*mm])
            summen_table.setStyle(TableStyle([('ALIGN', (0,0), (-1,-1), 'RIGHT'), ('LEFTPADDING', (0,0), (-1,-1), 0), ('RIGHTPADDING', (0,0), (-1,-1), 0), ])); 
            story.append(summen_table); 
            story.append(Spacer(1, 10 * mm))

            # Bemerkungsfeld (nur für normale Rechnungen, bei Gutschriften steht der Text oben)
            bemerkung_text = rechnung_data.get('bemerkung', '')
            if not is_gutschrift and bemerkung_text:
                story.append(Paragraph("<b>Bemerkung:</b>", style_normal)); 
                story.append(Spacer(1, 2 * mm))
                story.append(Paragraph(bemerkung_text.replace('\n', '<br/>'), style_normal)); 
            
            # --- PDF-Erstellung und Footer (Logik bleibt gleich) ---
            # ... (Rest der Funktion unverändert) ...
            def _draw_pdf_background_and_footer(canvas_param, doc_obj):
                canvas_param.saveState()
                if self.pdf_background_path and os.path.exists(self.pdf_background_path):
                    try:
                        canvas_param.drawImage(self.pdf_background_path, 0, 0, width=A4[0], height=A4[1], preserveAspectRatio=True, anchor='c')
                    except Exception as bg_err: logging.error(f"Fehler Zeichnen Hintergrundbild: {bg_err}")
                canvas_param.restoreState()
                
                canvas_param.saveState(); 
                canvas_param.setFont('Helvetica', 8); 
                page_width_footer, _ = A4
                y_pos_footer = doc_obj.bottomMargin / 2
                canvas_param.line(doc_obj.leftMargin, y_pos_footer + 2*mm, page_width_footer - doc_obj.rightMargin, y_pos_footer + 2*mm)
                line1_footer = f"{self.company_details.get('name', '')} | {self.company_details.get('address', '')} | {self.company_details.get('zip_city', '')}"
                line2_footer = f"Bank: {self.company_details.get('bank_details', '')} | USt-IdNr: {self.company_details.get('tax_id', '')}"
                line3_footer = f"Tel: {self.company_details.get('phone', '')} | E-Mail: {self.company_details.get('email', '')} | Seite {canvas_param.getPageNumber()}"
                canvas_param.drawString(doc_obj.leftMargin, y_pos_footer - 1*mm, line1_footer)
                canvas_param.drawString(doc_obj.leftMargin, y_pos_footer - 4*mm, line2_footer)
                canvas_param.drawString(doc_obj.leftMargin, y_pos_footer - 7*mm, line3_footer)
                canvas_param.restoreState()

            doc = BaseDocTemplate(output_path, pagesize=A4, leftMargin=margin, rightMargin=margin, topMargin=margin, bottomMargin=margin * 1.5)
            main_frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id='main')
            main_page_template = PageTemplate(id='mainPage', frames=[main_frame], onPage=_draw_pdf_background_and_footer)
            doc.addPageTemplates([main_page_template])
            doc.build(story)
            logging.info(f"PDF erstellt: {output_path}")

            try: 
                pdf_db_cursor = self.conn.cursor()
                pdf_db_cursor.execute("SELECT id FROM kunden_dokumente WHERE kunde_id=? AND dokument_pfad=?", (kunde_data['id'], output_path)) 
                existing_doc = pdf_db_cursor.fetchone()
                if not existing_doc: 
                    pdf_db_cursor.execute("INSERT INTO kunden_dokumente (kunde_id, dokument_pfad, dateiname) VALUES (?, ?, ?)",
                                   (kunde_data['id'], output_path, pdf_dateiname_base))
                    self.conn.commit()
                else: 
                    logging.info(f"Eintrag für PDF '{pdf_dateiname_base}' existiert bereits.")
            except sqlite3.Error as db_err: 
                logging.error(f"Fehler Eintragen/Prüfen PDF-Pfad: {db_err}") 
                self.conn.rollback()
            
            try: 
                if sys.platform == "win32": os.startfile(output_path) 
                else: subprocess.run(["open", output_path], check=True, text=True) 
            except Exception as e_open: 
                logging.error(f"Fehler Öffnen PDF: {e_open}") 
        except Exception as e_pdf: 
            logging.exception(f"Allg. Fehler PDF-Erstellung für Rng Nr {rechnungsnummer}:") 
            messagebox.showerror("PDF Fehler", f"Unerwarteter Fehler PDF-Erstellung:\n{e_pdf}", parent=self.root)


    def _load_artikel_templates_dict(self):
        # ... (Funktion unverändert)
        artikel_dict = {}
        if not self.conn:
            logging.error("DB Verbindung fehlt. Artikelvorlagen können nicht geladen werden.")
            return artikel_dict 
        cursor = self.conn.cursor()
        try:
            cursor.execute("SELECT artikelnummer, beschreibung, einheit, einzelpreis_netto, verfuegbar FROM artikel ORDER BY beschreibung ASC") 
            for row in cursor.fetchall():
                artnr, beschreibung, einheit, einzelpreis_netto, verfuegbar = row
                if artnr: 
                     artikel_dict[artnr] = {
                         'beschreibung': beschreibung,
                         'einheit': einheit,
                         'einzelpreis_netto': einzelpreis_netto if einzelpreis_netto is not None else 0.0, 
                         'verfuegbar': verfuegbar if verfuegbar is not None else 0.0
                     }
            logging.info(f"{len(artikel_dict)} Artikelvorlagen geladen.")
        except sqlite3.Error as e:
            logging.error(f"DB-Fehler beim Laden der Artikelvorlagen: {e}")
            messagebox.showerror("DB Fehler", f"Fehler beim Laden der Artikelvorlagen: {e}", parent=self.root)
            return {} 
        except Exception as e:
            logging.exception("Allg. Fehler beim Laden der Artikelvorlagen:")
            messagebox.showerror("Fehler", f"Unerwarteter Fehler beim Laden der Artikelvorlagen: {e}", parent=self.root)
            return {}
        return artikel_dict

    def _save_artikel_template_db(self, artnr, beschreibung, einheit, einzelpreis_netto):
        if not self.conn:
            logging.error("DB Verbindung fehlt. Artikelvorlage kann nicht gespeichert werden.")
            messagebox.showerror("DB Fehler", "Keine DB-Verbindung.", parent=self.root)
            return False
        if not artnr or not beschreibung:
            messagebox.showwarning("Fehler", "Artikelnummer und Beschreibung dürfen nicht leer sein.", parent=self.root)
            return False

        cursor = self.conn.cursor()
        try:
            cursor.execute("SELECT id, beschreibung, einheit, einzelpreis_netto FROM artikel WHERE artikelnummer=?", (artnr,))
            existing_artikel = cursor.fetchone()

            if existing_artikel:
                artikel_id, old_desc, old_einheit, old_preis = existing_artikel
                changes = []
                if old_desc != beschreibung: changes.append(f"Beschreibung von '{old_desc}' zu '{beschreibung}'")
                if old_einheit != einheit: changes.append(f"Einheit von '{old_einheit}' zu '{einheit}'")
                if float(old_preis) != float(einzelpreis_netto): changes.append(f"Preis von '{old_preis}' zu '{einzelpreis_netto}'")
                
                if changes:
                    cursor.execute("UPDATE artikel SET beschreibung=?, einheit=?, einzelpreis_netto=? WHERE id=?",
                                   (beschreibung, einheit, einzelpreis_netto, artikel_id))
                    self._log_audit_event("ARTIKEL_GEAENDERT", record_id=artikel_id, details=f"Artikel '{artnr}': " + "; ".join(changes))
            else:
                cursor.execute("INSERT INTO artikel (artikelnummer, beschreibung, einheit, einzelpreis_netto, verfuegbar) VALUES (?, ?, ?, ?, 0.0)",
                               (artnr, beschreibung, einheit, einzelpreis_netto))
                artikel_id = cursor.lastrowid
                self._log_audit_event("ARTIKEL_ERSTELLT", record_id=artikel_id, details=f"Artikel '{artnr}' ({beschreibung}) erstellt.")

            self.conn.commit()
            return True
        except sqlite3.Error as e:
            logging.error(f"DB-Fehler beim Speichern Artikelvorlage '{artnr}': {e}")
            messagebox.showerror("DB Fehler", f"Fehler beim Speichern der Artikelvorlage:\n{e}", parent=self.root)
            if self.conn: self.conn.rollback()
            return False
        except Exception as e:
            logging.exception(f"Unerwarteter Fehler beim Speichern Artikelvorlage '{artnr}':")
            if self.conn: self.conn.rollback()
            return False

    def _delete_artikel_template_db(self, artnr):
        # GoBD: Löschen von Artikeln ist problematisch. Wir prüfen, ob er in Rechnungen verwendet wird.
        if not self.conn: return False
        if not artnr: return False

        cursor = self.conn.cursor()
        try:
            cursor.execute("SELECT COUNT(*) FROM rechnungsposten WHERE artikelnummer=?", (artnr,))
            usage_count = cursor.fetchone()[0]
            if usage_count > 0:
                messagebox.showerror("Löschen nicht möglich", f"Artikel '{artnr}' wird in {usage_count} Rechnung(en) verwendet und kann aus Gründen der Nachvollziehbarkeit nicht gelöscht werden.", parent=self.root)
                return False

            cursor.execute("SELECT id, beschreibung FROM artikel WHERE artikelnummer=?", (artnr,))
            artikel_data = cursor.fetchone()
            if not artikel_data:
                return False
            
            artikel_id, beschreibung = artikel_data
            
            cursor.execute("DELETE FROM artikel WHERE artikelnummer=?", (artnr,))
            self.conn.commit()
            self._log_audit_event("ARTIKEL_GELOESCHT", record_id=artikel_id, details=f"Artikel '{artnr}' ({beschreibung}) gelöscht (wurde nie in Rechnungen verwendet).")
            return True
        except sqlite3.Error as e:
            logging.error(f"DB-Fehler beim Löschen Artikelvorlage '{artnr}': {e}")
            if self.conn: self.conn.rollback()
            return False
        except Exception as e:
            logging.exception(f"Unerwarteter Fehler beim Löschen Artikelvorlage '{artnr}':")
            if self.conn: self.conn.rollback()
            return False

    #... Die E-Mail Funktionen (_get_email_templates_path, etc.) bleiben unverändert.
    def _get_email_templates_path(self):
        app_dir = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(app_dir, "email_templates.json")

    def _load_email_templates(self):
        templates_path = self._get_email_templates_path()
        templates = {}
        try:
            if os.path.exists(templates_path):
                with open(templates_path, "r", encoding='utf-8') as f:
                    templates = json.load(f)
            if not isinstance(templates, dict):
                 logging.error(f"Vorlagen-Datei '{templates_path}' enthält kein gültiges JSON-Objekt.")
                 return {}
            logging.info(f"E-Mail-Vorlagen aus '{templates_path}' geladen.")
        except FileNotFoundError:
            logging.info(f"Vorlagen-Datei '{templates_path}' nicht gefunden, starte mit leeren Vorlagen.")
        except json.JSONDecodeError as e:
            logging.error(f"Fehler beim Parsen der Vorlagen-Datei '{templates_path}': {e}")
            messagebox.showerror("File Error", f"Fehler beim Lesen der Vorlagen-Datei:\n{e}\nDatei wird ignoriert.", parent=self.root)
            return {} 
        except Exception as e:
            logging.error(f"Unerwarteter Fehler beim Laden der Vorlagen-Datei '{templates_path}': {e}")
            messagebox.showerror("File Error", f"Unerwarteter Fehler beim Laden der Vorlagen:\n{e}", parent=self.root)
            return {}
        return templates

    def _save_email_templates(self, templates_dict):
        templates_path = self._get_email_templates_path()
        try:
            os.makedirs(os.path.dirname(templates_path), exist_ok=True)
            with open(templates_path, "w", encoding='utf-8') as f:
                json.dump(templates_dict, f, indent=4, ensure_ascii=False)
            logging.info(f"E-Mail-Vorlagen in '{templates_path}' gespeichert.")
            return True
        except Exception as e:
            logging.error(f"Fehler beim Speichern der Vorlagen-Datei '{templates_path}': {e}")
            messagebox.showerror("File Error", f"Fehler beim Speichern der Vorlagen:\n{e}", parent=self.root)
            return False

    def open_email_compose_window(self, parent, recipient_email, attachment_path, attachment_filename):
        compose_window = tk.Toplevel(parent) 
        compose_window.title("E-Mail senden")
        compose_window.geometry("600x550") 
        compose_window.transient(parent)
        compose_window.grab_set()
        compose_window.resizable(False, False)

        frame = ttk.Frame(compose_window, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="An:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        entry_to = ttk.Entry(frame, width=60)
        entry_to.grid(row=0, column=1, padx=5, pady=5, sticky=tk.EW)
        entry_to.insert(0, recipient_email or "") 

        ttk.Label(frame, text="Betreff:").grid(row=1, column=0, padx=5, pady=5, sticky=tk.W)
        entry_subject = ttk.Entry(frame, width=60)
        entry_subject.grid(row=1, column=1, padx=5, pady=5, sticky=tk.EW)
        default_subject = f"Dokument von {self.company_details.get('name', 'Ihrer Firma')}: {attachment_filename}"
        entry_subject.insert(0, default_subject)

        ttk.Label(frame, text="Anhang:").grid(row=2, column=0, padx=5, pady=5, sticky=tk.W)
        lbl_attachment = ttk.Label(frame, text=attachment_filename, foreground="blue", cursor="hand2")
        lbl_attachment.grid(row=2, column=1, padx=5, pady=5, sticky=tk.W)
        lbl_attachment.bind("<Button-1>", lambda e: self._open_file(attachment_path)) 

        ttk.Label(frame, text="Nachricht:").grid(row=3, column=0, padx=5, pady=5, sticky=tk.NW)
        text_body = tk.Text(frame, height=10, width=60, wrap=tk.WORD) 
        text_body.grid(row=3, column=1, padx=5, pady=5, sticky=tk.NSEW)
        scrollbar_body = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=text_body.yview)
        scrollbar_body.grid(row=3, column=2, sticky=tk.NS)
        text_body.config(yscrollcommand=scrollbar_body.set)

        template_frame_email = ttk.LabelFrame(frame, text="Textvorlagen") 
        template_frame_email.grid(row=4, column=0, columnspan=3, sticky=tk.EW, padx=5, pady=5)
        ttk.Label(template_frame_email, text="Vorlage wählen:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        email_templates_combobox_dlg = ttk.Combobox(template_frame_email, width=30, state="readonly")
        email_templates_combobox_dlg.grid(row=0, column=1, padx=5, pady=5, sticky=tk.EW)
        
        btn_frame_templates_email = ttk.Frame(template_frame_email) 
        btn_frame_templates_email.grid(row=0, column=2, padx=5, pady=5)
        btn_load_template = ttk.Button(btn_frame_templates_email, text="Wählen")
        btn_load_template.pack(side=tk.LEFT, padx=2)
        btn_save_template = ttk.Button(btn_frame_templates_email, text="Speichern")
        btn_save_template.pack(side=tk.LEFT, padx=2)
        btn_delete_template = ttk.Button(btn_frame_templates_email, text="Löschen")
        btn_delete_template.pack(side=tk.LEFT, padx=2)
        template_frame_email.columnconfigure(1, weight=1)

        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(3, weight=1) 

        button_frame_email_actions = ttk.Frame(compose_window)
        button_frame_email_actions.pack(pady=10)

        btn_send = ttk.Button(button_frame_email_actions, text="Senden")
        btn_cancel = ttk.Button(button_frame_email_actions, text="Abbrechen", command=compose_window.destroy)

        def do_send_email():
            to_addr = entry_to.get().strip()
            subject = entry_subject.get().strip()
            body = text_body.get("1.0", tk.END).strip()
            if not to_addr: messagebox.showerror("Fehler", "Empfänger-Adresse fehlt.", parent=compose_window); return
            if "@" not in to_addr or "." not in to_addr.split("@")[-1]:
                 if not messagebox.askyesno("Warnung", f"'{to_addr}' scheint keine gültige E-Mail-Adresse zu sein.\nTrotzdem senden?", parent=compose_window, icon=messagebox.WARNING): return
            
            btn_send.config(state=tk.DISABLED); btn_cancel.config(state=tk.DISABLED)
            compose_window.config(cursor="wait")
            compose_window.update_idletasks()

            success = self._send_email_actual(recipient=to_addr, subject=subject, body=body, attachment_path=attachment_path, parent_window=compose_window)
            
            compose_window.config(cursor="")
            btn_send.config(state=tk.NORMAL); btn_cancel.config(state=tk.NORMAL)
            if success: compose_window.destroy()
        
        btn_send.config(command=do_send_email)
        btn_send.pack(side=tk.LEFT, padx=10)
        btn_cancel.pack(side=tk.LEFT, padx=10)


        def _update_template_combobox_email():
            templates = self._load_email_templates()
            template_names = sorted(list(templates.keys()))
            email_templates_combobox_dlg['values'] = template_names
            if not template_names:
                email_templates_combobox_dlg.set('')
                btn_load_template.config(state=tk.DISABLED); btn_delete_template.config(state=tk.DISABLED)
            else:
                 btn_load_template.config(state=tk.NORMAL)
                 btn_delete_template.config(state=tk.DISABLED if not email_templates_combobox_dlg.get() else tk.NORMAL)


        def on_email_template_combobox_select(event):
            btn_delete_template.config(state=tk.NORMAL if email_templates_combobox_dlg.get() else tk.DISABLED)

        def load_selected_template_email():
            selected_name = email_templates_combobox_dlg.get()
            if not selected_name: messagebox.showwarning("Auswahl fehlt", "Vorlage wählen.", parent=compose_window); return
            templates = self._load_email_templates()
            template_text = templates.get(selected_name)
            if template_text is not None:
                if messagebox.askyesno("Vorlage laden", "Aktuellen Text ersetzen?", parent=compose_window, icon=messagebox.QUESTION):
                    text_body.delete("1.0", tk.END); text_body.insert("1.0", template_text)
                    logging.info(f"Vorlage '{selected_name}' geladen.")
            else: messagebox.showerror("Fehler", f"Vorlage '{selected_name}' nicht gefunden.", parent=compose_window); _update_template_combobox_email()

        def save_current_body_as_template_email():
            current_body = text_body.get("1.0", tk.END).strip()
            if not current_body: messagebox.showwarning("Leer", "Nachrichtentext ist leer.", parent=compose_window); return
            template_name = simpledialog.askstring("Vorlage speichern", "Namen für Vorlage eingeben:", parent=compose_window)
            if template_name:
                template_name = template_name.strip()
                if not template_name: messagebox.showwarning("Name fehlt", "Kein gültiger Name.", parent=compose_window); return
                templates = self._load_email_templates()
                if template_name in templates and not messagebox.askyesno("Vorlage existiert", f"Vorlage '{template_name}' überschreiben?", parent=compose_window, icon=messagebox.QUESTION): return
                templates[template_name] = current_body
                if self._save_email_templates(templates):
                    messagebox.showinfo("Erfolg", f"Vorlage '{template_name}' gespeichert.", parent=compose_window)
                    _update_template_combobox_email(); email_templates_combobox_dlg.set(template_name)
                    on_email_template_combobox_select(None)

        def delete_selected_template_email():
            selected_name = email_templates_combobox_dlg.get()
            if not selected_name: messagebox.showwarning("Auswahl fehlt", "Vorlage zum Löschen wählen.", parent=compose_window); return
            if messagebox.askyesno("Löschen", f"Vorlage '{selected_name}' löschen?", parent=compose_window, icon=messagebox.WARNING):
                templates = self._load_email_templates()
                if selected_name in templates:
                    del templates[selected_name]
                    if self._save_email_templates(templates):
                        messagebox.showinfo("Erfolg", f"Vorlage '{selected_name}' gelöscht.", parent=compose_window)
                        _update_template_combobox_email(); email_templates_combobox_dlg.set('')
                        on_email_template_combobox_select(None)
                else: messagebox.showerror("Fehler", f"Vorlage '{selected_name}' nicht gefunden.", parent=compose_window); _update_template_combobox_email()
        
        btn_load_template.config(command=load_selected_template_email)
        btn_save_template.config(command=save_current_body_as_template_email)
        btn_delete_template.config(command=delete_selected_template_email)
        email_templates_combobox_dlg.bind("<<ComboboxSelected>>", on_email_template_combobox_select)

        _update_template_combobox_email()
        entry_to.focus_set() 


    def _is_smtp_configured(self):
        return bool(self.smtp_server and self.smtp_port and self.smtp_user)

    def _get_customer_email(self, customer_id):
        if not customer_id or not self.conn: return None
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT email FROM kunden WHERE id=?", (customer_id,))
            result = cursor.fetchone()
            return result[0] if result and result[0] else None
        except sqlite3.Error as e:
            logging.error(f"DB-Fehler Abruf E-Mail Kunde ID {customer_id}: {e}"); return None

    def _open_file(self, file_path):
        try:
            if sys.platform == "win32": os.startfile(file_path)
            elif sys.platform == "darwin": subprocess.run(["open", file_path], check=True)
            else: subprocess.run(["xdg-open", file_path], check=True)
            logging.info(f"Datei geöffnet: {file_path}")
        except FileNotFoundError: 
            messagebox.showerror("Fehler", f"Datei nicht gefunden:\n{file_path}", parent=self.root)
            logging.error(f"Datei nicht gefunden: {file_path}")
        except Exception as e: 
            messagebox.showerror("Fehler", f"Fehler Öffnen Datei:\n{e}", parent=self.root)
            logging.error(f"Fehler Öffnen Datei {file_path}: {e}")

    def _send_email_actual(self, recipient, subject, body, attachment_path, parent_window):
        if self.smtp_user and not self.smtp_password:
             pw = simpledialog.askstring("SMTP Passwort benötigt", f"Passwort für E-Mail-Benutzer '{self.smtp_user}':", show='*', parent=parent_window)
             if pw is None: 
                 logging.info("SMTP PW-Abfrage abgebrochen."); 
                 messagebox.showwarning("Abgebrochen", "E-Mail-Versand abgebrochen.", parent=parent_window); return False
             elif not pw: 
                 logging.warning("Leeres PW für SMTP."); 
                 messagebox.showwarning("Passwort fehlt", "Kein Passwort. E-Mail nicht gesendet.", parent=parent_window); return False
             else: 
                 self.smtp_password = pw; 
                 logging.info("SMTP Passwort für Sitzung erhalten.")
        elif not self.smtp_user: 
            messagebox.showerror("Fehler", "E-Mail-Benutzername nicht konfiguriert.", parent=parent_window); return False
        
        if not self._is_smtp_configured(): 
            messagebox.showerror("Fehler", "SMTP nicht korrekt konfiguriert.", parent=parent_window); return False

        msg = MIMEMultipart(); msg['From'] = self.smtp_user; msg['To'] = recipient; msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain', 'utf-8'))
        filename = os.path.basename(attachment_path)
        try:
            with open(attachment_path, "rb") as attachment: 
                part = MIMEBase('application', 'octet-stream'); 
                part.set_payload(attachment.read())
            encoders.encode_base64(part); 
            try:
                from email.header import Header
                part.add_header('Content-Disposition', 'attachment', filename=Header(filename, 'utf-8').encode())
            except UnicodeEncodeError:
                safe_filename = base64.b64encode(filename.encode('utf-8', 'surrogateescape')).decode('ascii')
                part.add_header('Content-Disposition', f"attachment; filename=\"=?UTF-8?B?{safe_filename}?=\"")

            msg.attach(part); 
            logging.info(f"Anhang '{filename}' zur E-Mail hinzugefügt.")
        except FileNotFoundError: 
            logging.error(f"Anhangdatei nicht gefunden: {attachment_path}"); 
            messagebox.showerror("Fehler", f"Anhangdatei nicht gefunden:\n{filename}", parent=parent_window); return False
        except Exception as e: 
            logging.error(f"Fehler Lesen/Anhängen Datei {filename}: {e}"); 
            messagebox.showerror("Fehler", f"Fehler Hinzufügen Anhang:\n{e}", parent=parent_window); return False

        server = None
        try:
            logging.info(f"Verbinde mit SMTP Server {self.smtp_server}:{self.smtp_port} (Encryption: {self.smtp_encryption})")
            if self.smtp_encryption.upper() == 'SSL/TLS': server = smtplib.SMTP_SSL(self.smtp_server, self.smtp_port, timeout=20)
            elif self.smtp_encryption.upper() == 'STARTTLS': 
                server = smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=20)
                server.starttls()
            else: server = smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=20)
            
            if self.smtp_user and self.smtp_password:
                 logging.info(f"Authentifiziere als Benutzer {self.smtp_user}"); 
                 server.login(self.smtp_user, self.smtp_password)
            
            logging.info(f"Sende E-Mail an {recipient}"); 
            server.send_message(msg)
            logging.info("E-Mail erfolgreich gesendet."); 
            messagebox.showinfo("Erfolg", "E-Mail erfolgreich gesendet.", parent=parent_window)
            return True
        except smtplib.SMTPAuthenticationError as e: 
            logging.error(f"SMTP Authentifizierungsfehler: {e}"); 
            messagebox.showerror("SMTP Fehler", f"Authentifizierung fehlgeschlagen.\nBenutzername/Passwort prüfen.\n({e})", parent=parent_window); 
            self.smtp_password = None
        except smtplib.SMTPConnectError as e: 
            logging.error(f"SMTP Verbindungsfehler: {e}"); 
            messagebox.showerror("SMTP Fehler", f"Verbindung zum Server fehlgeschlagen.\nServer/Port prüfen.\n({e})", parent=parent_window)
        except smtplib.SMTPServerDisconnected as e: 
            logging.error(f"SMTP Serververbindung getrennt: {e}"); 
            messagebox.showerror("SMTP Fehler", f"Verbindung zum Server getrennt.\n({e})", parent=parent_window)
        except smtplib.SMTPException as e: 
            logging.error(f"Allgemeiner SMTP Fehler: {e}"); 
            messagebox.showerror("SMTP Fehler", f"Ein SMTP-Fehler ist aufgetreten:\n{e}", parent=parent_window)
        except OSError as e:
            logging.error(f"Netzwerk-/Socket-Fehler beim E-Mail-Versand: {e}"); 
            messagebox.showerror("Netzwerkfehler", f"Netzwerkfehler beim Senden:\n{e}", parent=parent_window)
        except Exception as e: 
            logging.exception("Unerwarteter Fehler beim E-Mail-Versand:"); 
            messagebox.showerror("Fehler", f"Ein unerwarteter Fehler ist aufgetreten:\n{e}", parent=parent_window)
        finally:
            if server:
                try: server.quit(); logging.info("SMTP Verbindung geschlossen.")
                except Exception as e_quit: logging.error(f"Fehler Schließen SMTP Verbindung: {e_quit}")
        return False


# --- Hauptteil ---
if __name__ == "__main__":
    logging.info("Starte Hauptanwendung (Tkinter GUI)...")
    app_instance = None
    try:
        root = ThemedTk()
        app_instance = UnternehmensApp(root)
        
        try: 
            if sys.platform == "win32":
                root.state('zoomed')
            else:
                w, h = root.winfo_screenwidth(), root.winfo_screenheight()
                root.geometry(f"{w}x{h}+0+0")
        except tk.TclError:
            try: 
                m = root.maxsize() 
                root.geometry('{}x{}+0+0'.format(*m))
            except Exception as e_max: 
                logging.warning(f"Fenster maximieren nicht vollständig unterstützt: {e_max}")
                root.geometry("1200x800")

        app_instance._log_audit_event("ANWENDUNG_START", details="Anwendung wurde gestartet.")
        root.mainloop()

    except Exception as e_mainloop:
        logging.exception("Kritischer Fehler während der Ausführung der Anwendung (mainloop):")
        try: 
            messagebox.showerror("Laufzeitfehler", f"Ein kritischer Fehler ist aufgetreten:\n{e_mainloop}\n\nBitte prüfen Sie die Logdatei 'unternehmens_app.log'.\nAnwendung wird beendet.")
        except:
            print(f"FATAL ERROR during mainloop, Tkinter messagebox failed: {e_mainloop}", file=sys.stderr)
        sys.exit(1)
    finally:
        logging.info("Hauptanwendung (Tkinter GUI) wird beendet. Starte Shutdown-Routine...")
        if app_instance:
            app_instance._log_audit_event("ANWENDUNG_ENDE", details="Anwendung wurde beendet.")
            if hasattr(app_instance, 'conn') and app_instance.conn:
                try: 
                    app_instance.conn.close(); 
                    logging.info("Datenbankverbindung erfolgreich geschlossen.")
                except Exception as e_db_close: 
                    logging.error(f"Fehler beim Schließen der DB-Verbindung: {e_db_close}")
        _run_daten_schloss_shutdown()
        logging.info("Shutdown-Routine beendet.")
    sys.exit(0)