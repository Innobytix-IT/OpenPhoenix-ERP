# Lagerverwaltung.py (Überarbeitet mit DatenSchloss-Integration und GoBD-Konformität)
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import sqlite3
import os
import logging
from ttkthemes import ThemedTk
import sys
import subprocess
import uuid # für Lizenz/Hardware-ID
import hashlib # für Hashing
from datetime import datetime

# Logging konfigurieren
logging.basicConfig(filename='lagerverwaltung.log', level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# --- DATENSCHLOSS FUNKTIONEN (unverändert) ---

def _find_daten_schloss_tool():
    """Sucht nach der DatenSchloss-Anwendung im Skript-Verzeichnis."""
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
    """Startet das DatenSchloss Tool vor der Hauptanwendung und wartet auf dessen Beendigung."""
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
    """Startet das DatenSchloss Tool nach Beendigung der Hauptanwendung."""
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

# --- ENDE DATENSCHLOSS FUNKTIONEN ---


# --- Globale Variable für den Datenbankpfad und Config ---
CONFIG_FILE_PATH_LAGER = "config.txt"
DEFAULT_DB_PATH_LAGER = "unternehmen_gobd.db"

def get_db_path_from_config():
    """Liest den Datenbankpfad aus der config.txt."""
    db_path = DEFAULT_DB_PATH_LAGER
    if os.path.exists(CONFIG_FILE_PATH_LAGER):
        try:
            with open(CONFIG_FILE_PATH_LAGER, "r", encoding='utf-8') as f:
                for line in f:
                    if line.strip().startswith("db_path="):
                        path_from_config = line.strip().split("=", 1)[1]
                        if path_from_config:
                            db_path = path_from_config
                            break
            logging.info(f"DB-Pfad aus {CONFIG_FILE_PATH_LAGER} geladen: {db_path}")
        except Exception as e:
            logging.error(f"Fehler beim Lesen von {CONFIG_FILE_PATH_LAGER} für DB-Pfad: {e}. Verwende Fallback: {db_path}")
    else:
        logging.warning(f"{CONFIG_FILE_PATH_LAGER} nicht gefunden. Verwende Fallback DB-Pfad: {db_path}")
    return db_path

def save_setting_lager(key, value):
    """Speichert eine einzelne Einstellung in config.txt (vereinfachte Version für Lager)."""
    lines = []
    found = False
    try:
        if os.path.exists(CONFIG_FILE_PATH_LAGER):
            with open(CONFIG_FILE_PATH_LAGER, "r", encoding='utf-8') as f:
                lines = f.readlines()
        with open(CONFIG_FILE_PATH_LAGER, "w", encoding='utf-8') as f:
            for line in lines:
                stripped_line = line.strip()
                if stripped_line.startswith(key + "="):
                    f.write(f"{key}={value}\n")
                    found = True
                elif stripped_line:
                    f.write(line)
            if not found:
                f.write(f"{key}={value}\n")
        logging.info(f"Einstellung '{key}' in {CONFIG_FILE_PATH_LAGER} für Lagerverwaltung gespeichert.")
        return True
    except Exception as e:
        logging.error(f"Fehler beim Speichern der Einstellung '{key}' in {CONFIG_FILE_PATH_LAGER}: {e}")
        messagebox.showerror("Fehler", f"Fehler beim Speichern der Einstellung '{key}': {e}")
        return False

# ### GoBD-ÄNDERUNG ###: Funktion zur Protokollierung von Aktionen
def log_audit_event(conn, action, record_id, details):
    """Protokolliert ein Ereignis in der audit_log-Tabelle."""
    try:
        cursor = conn.cursor()
        timestamp = datetime.now().isoformat(sep=' ', timespec='microseconds')
        user = "system" # In einer Multi-User-Umgebung wäre hier der eingeloggte Benutzer
        cursor.execute(
            "INSERT INTO audit_log (timestamp, user, action, record_id, details) VALUES (?, ?, ?, ?, ?)",
            (timestamp, user, action, record_id, details)
        )
        # Wichtig: Das Commit erfolgt durch die aufrufende Funktion, um die Atomarität zu gewährleisten.
        logging.info(f"AUDIT LOG: User='{user}', Action='{action}', RecordID={record_id}, Details='{details}'")
    except sqlite3.Error as e:
        logging.error(f"FATAL: Konnte Audit-Ereignis nicht protokollieren: {e}")
        messagebox.showerror("Kritischer Fehler", f"Ein Audit-Ereignis konnte nicht protokolliert werden: {e}\nDie Anwendung muss möglicherweise beendet werden, um Datenkonsistenz zu wahren.")

# ### GoBD-ÄNDERUNG ###: Funktion zur Überprüfung und Anpassung des DB-Schemas
def check_and_update_db_schema(conn):
    """Stellt sicher, dass die 'artikel'-Tabelle GoBD-konforme Spalten enthält."""
    try:
        cursor = conn.cursor()
        # Prüfen, ob die Spalte 'is_active' existiert
        cursor.execute("PRAGMA table_info(artikel)")
        columns = [info[1] for info in cursor.fetchall()]
        if 'is_active' not in columns:
            logging.warning("DB-Schema veraltet: Spalte 'is_active' in Tabelle 'artikel' fehlt. Füge sie hinzu.")
            cursor.execute("ALTER TABLE artikel ADD COLUMN is_active INTEGER DEFAULT 1")
            conn.commit()
            messagebox.showinfo("Datenbank-Update", "Die Artikel-Tabelle wurde für die GoBD-Konformität aktualisiert (Spalte 'is_active' hinzugefügt).")
        
        # Prüfung für die audit_log Tabelle selbst
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='audit_log';")
        if not cursor.fetchone():
            logging.error("FATAL: Die für die GoBD essentielle Tabelle 'audit_log' fehlt in der Datenbank.")
            messagebox.showerror("DB Strukturfehler", "Die Protokollierungstabelle 'audit_log' fehlt.\nBitte stellen Sie sicher, dass die Datenbank korrekt initialisiert wurde (z.B. durch die Hauptanwendung).")
            return False
            
        logging.info("DB-Schema ist auf dem erwarteten Stand für die Lagerverwaltung.")
        return True
    except sqlite3.Error as e:
        logging.error(f"Fehler bei der Überprüfung/Anpassung des DB-Schemas: {e}")
        messagebox.showerror("Datenbankfehler", f"Fehler bei der Aktualisierung des Datenbankschemas: {e}")
        return False

class LagerApp:
    def __init__(self, root_lager):
        self.root_lager = root_lager
        self.root_lager.title("Lager- und Warenverwaltung (GoBD-konform)")
        self.root_lager.geometry("1100x700")

        self.db_path = get_db_path_from_config()

        try:
            icon_path = os.path.join(os.path.dirname(__file__), 'lager_icon.ico')
            if os.path.exists(icon_path): self.root_lager.iconbitmap(default=icon_path)
            else:
                app_icon_path = os.path.join(os.path.dirname(__file__), 'app_icon.ico')
                if os.path.exists(app_icon_path): self.root_lager.iconbitmap(default=app_icon_path)
                else: logging.warning("Kein Icon für Lagerverwaltung gefunden.")
        except Exception as e: logging.error(f"Fehler beim Setzen des Lager-Icons: {e}")

        self.conn = self.connect_db()
        if self.conn is None:
            messagebox.showerror("Datenbankfehler", f"Konnte keine Verbindung zur Datenbank herstellen: {self.db_path}\nStellen Sie sicher, dass die Datenbank existiert und der Pfad in config.txt korrekt ist.", parent=self.root_lager)
            _run_daten_schloss_shutdown()
            self.root_lager.destroy()
            return
            
        # ### GoBD-ÄNDERUNG ###: Schema prüfen und ggf. anpassen
        if not check_and_update_db_schema(self.conn):
            self.conn.close()
            _run_daten_schloss_shutdown()
            self.root_lager.destroy()
            return

        self.selected_article_id = None
        
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self.filter_articles_live)

        self.create_menu()
        self.create_widgets()
        self.load_articles_from_db()

        self.root_lager.protocol("WM_DELETE_WINDOW", self.on_closing)

    def create_menu(self):
        menubar = tk.Menu(self.root_lager)
        settings_menu = tk.Menu(menubar, tearoff=0)
        settings_menu.add_command(label="Datenbankpfad ändern...", command=self.open_change_db_path_window_lager)
        settings_menu.add_separator()
        settings_menu.add_command(label="Beenden", command=self.on_closing)
        menubar.add_cascade(label="Einstellungen", menu=settings_menu)
        self.root_lager.config(menu=menubar)

    def open_change_db_path_window_lager(self):
        # ... (Diese Funktion ist komplex und bleibt unverändert) ...
        # Logik zum Ändern des DB-Pfads
        change_path_window = tk.Toplevel(self.root_lager)
        change_path_window.title("Datenbankpfad ändern (Lager)")
        change_path_window.transient(self.root_lager)
        change_path_window.grab_set()
        change_path_window.geometry("450x200")
        ttk.Label(change_path_window, text="Neuer Datenbankpfad (.db):").pack(padx=10, pady=10)
        entry_new_db_path_var = tk.StringVar(value=self.db_path)
        entry_new_db_path = ttk.Entry(change_path_window, textvariable=entry_new_db_path_var, width=50)
        entry_new_db_path.pack(padx=10, pady=5)
        def browse_path_lager():
            new_path = filedialog.asksaveasfilename(parent=change_path_window, title="Datenbankdatei auswählen oder erstellen", initialdir=os.path.dirname(self.db_path) if self.db_path else os.getcwd(), defaultextension=".db", filetypes=[("SQLite DBs", "*.db"), ("Alle Dateien", "*.*")])
            if new_path: entry_new_db_path_var.set(new_path)
        def save_path_lager():
            new_path_val = entry_new_db_path_var.get().strip()
            if new_path_val and new_path_val.lower().endswith(".db"):
                can_proceed = False
                if os.path.exists(new_path_val): can_proceed = True
                elif os.access(os.path.dirname(os.path.abspath(new_path_val)) or ".", os.W_OK):
                    if messagebox.askyesno("Datenbank nicht gefunden", f"Die Datei '{os.path.basename(new_path_val)}' existiert nicht.\nSoll versucht werden, sie zu verwenden (könnte neu erstellt werden)?", parent=change_path_window): can_proceed = True
                else: messagebox.showerror("Fehler", f"Pfad ungültig oder Verzeichnis nicht beschreibbar:\n{new_path_val}", parent=change_path_window)
                if can_proceed:
                    if self.conn:
                        try: self.conn.close(); logging.info("Alte DB-Verbindung der Lagerverwaltung geschlossen.")
                        except sqlite3.Error as e_close: logging.error(f"Fehler beim Schließen der alten DB-Verbindung (Lager): {e_close}")
                    self.db_path = new_path_val
                    if save_setting_lager("db_path", self.db_path):
                        self.conn = self.connect_db()
                        if self.conn:
                            self.load_articles_from_db(); messagebox.showinfo("Erfolg", f"Datenbankpfad für Lagerverwaltung geändert und neu verbunden:\n{self.db_path}", parent=change_path_window); change_path_window.destroy()
                        else: messagebox.showerror("Verbindungsfehler", f"Konnte keine Verbindung zur neuen Datenbank herstellen:\n{self.db_path}\nDie Einstellung wurde gespeichert, aber die Verbindung ist fehlgeschlagen.", parent=change_path_window)
                    else: pass
            else: messagebox.showwarning("Ungültiger Pfad", "Bitte einen gültigen Pfad zu einer .db-Datei angeben.", parent=change_path_window)
        button_frame_path = ttk.Frame(change_path_window); button_frame_path.pack(pady=10)
        ttk.Button(button_frame_path, text="Durchsuchen...", command=browse_path_lager).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame_path, text="Speichern & Neu verbinden", command=save_path_lager).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame_path, text="Abbrechen", command=change_path_window.destroy).pack(side=tk.LEFT, padx=5)

    def connect_db(self):
        try:
            conn = sqlite3.connect(self.db_path, timeout=10.0)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='artikel';")
            if not cursor.fetchone():
                logging.error(f"Tabelle 'artikel' nicht in Datenbank '{self.db_path}' gefunden. Wurde die DB von der Kundenverwaltung initialisiert?")
                messagebox.showerror("DB Strukturfehler", f"Tabelle 'artikel' nicht in Datenbank '{self.db_path}' gefunden.\nBitte zuerst die Kundenverwaltung starten, um die Datenbank zu initialisieren.", parent=self.root_lager)
                conn.close()
                return None
            logging.info(f"Erfolgreich mit Datenbank '{self.db_path}' verbunden (Lager).")
            return conn
        except sqlite3.Error as e:
            logging.error(f"Fehler beim Verbinden mit der Datenbank '{self.db_path}' (Lager): {e}")
            return None

    def on_closing(self):
        """Wird aufgerufen, wenn das Fenster geschlossen wird."""
        logging.info("Lagerverwaltung wird geschlossen...")
        if self.conn:
            try:
                self.conn.close()
                logging.info("Datenbankverbindung der Lagerverwaltung geschlossen.")
            except Exception as e:
                logging.error(f"Fehler beim Schließen der DB-Verbindung (Lager): {e}")
        _run_daten_schloss_shutdown()
        self.root_lager.destroy()
        logging.info("Anwendungsfenster zerstört. Programmende.")

    def create_widgets(self):
        # ... (Widget-Erstellung bleibt weitgehend gleich, bis auf Button-Text) ...
        input_frame = ttk.LabelFrame(self.root_lager, text="Artikeldetails")
        input_frame.pack(padx=10, pady=10, fill="x")
        labels_artikel = {"artikelnummer": "Artikelnummer:", "beschreibung": "Beschreibung:", "einheit": "Einheit:", "einzelpreis_netto": "Einzelpreis Netto (€):", "verfuegbar": "Verfügbar (Stk.):"}
        self.entries_artikel = {}
        for i, (key, text) in enumerate(labels_artikel.items()):
            ttk.Label(input_frame, text=text).grid(row=i, column=0, padx=5, pady=5, sticky="w")
            entry = ttk.Entry(input_frame, width=40)
            entry.grid(row=i, column=1, padx=5, pady=5, sticky="ew")
            self.entries_artikel[key] = entry
        input_frame.columnconfigure(1, weight=1)

        button_frame = ttk.Frame(self.root_lager)
        button_frame.pack(padx=10, pady=5, fill="x")
        self.btn_save = ttk.Button(button_frame, text="Neu/Speichern", command=self.save_article_to_db)
        self.btn_save.pack(side="left", padx=5)
        # ### GoBD-ÄNDERUNG ###: Button-Text und -Aktion geändert
        self.btn_deactivate = ttk.Button(button_frame, text="Deaktivieren", command=self.deactivate_article_in_db, state="disabled")
        self.btn_deactivate.pack(side="left", padx=5)
        self.btn_clear = ttk.Button(button_frame, text="Felder leeren", command=self.clear_article_fields)
        self.btn_clear.pack(side="left", padx=5)
        
        search_frame = ttk.Frame(self.root_lager)
        search_frame.pack(padx=10, pady=5, fill="x")
        ttk.Label(search_frame, text="Suche:").pack(side="left", padx=(0, 5))
        self.entry_search = ttk.Entry(search_frame, textvariable=self.search_var)
        self.entry_search.pack(side="left", fill="x", expand=True)
        self.btn_refresh = ttk.Button(search_frame, text="Liste aktualisieren", command=self.load_articles_from_db)
        self.btn_refresh.pack(side="right", padx=5)

        tree_frame = ttk.Frame(self.root_lager)
        tree_frame.pack(padx=10, pady=10, fill="both", expand=True)
        columns_artikel = ("id", "artikelnummer", "beschreibung", "einheit", "preis_netto", "verfuegbar")
        self.tree_articles = ttk.Treeview(tree_frame, columns=columns_artikel, show="headings")
        self.tree_articles.heading("id", text="ID"); self.tree_articles.column("id", width=50, anchor="e")
        self.tree_articles.heading("artikelnummer", text="Art.-Nr."); self.tree_articles.column("artikelnummer", width=120)
        self.tree_articles.heading("beschreibung", text="Beschreibung"); self.tree_articles.column("beschreibung", width=400)
        self.tree_articles.heading("einheit", text="Einheit"); self.tree_articles.column("einheit", width=80)
        self.tree_articles.heading("preis_netto", text="Preis Netto (€)"); self.tree_articles.column("preis_netto", width=120, anchor="e")
        self.tree_articles.heading("verfuegbar", text="Verfügbar"); self.tree_articles.column("verfuegbar", width=80, anchor="e")
        self.tree_articles.pack(side="left", fill="both", expand=True)
        scrollbar_artikel = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree_articles.yview)
        self.tree_articles.configure(yscrollcommand=scrollbar_artikel.set)
        scrollbar_artikel.pack(side="right", fill="y")
        self.tree_articles.bind("<<TreeviewSelect>>", self.on_tree_select)

    def robust_parse_float(self, value_str, default=0.0):
        if isinstance(value_str, (int, float)): return float(value_str)
        if not isinstance(value_str, str): value_str = str(value_str)
        value_str = value_str.strip()
        if not value_str: return default
        last_dot = value_str.rfind('.'); last_comma = value_str.rfind(',')
        try:
            if last_comma > last_dot: cleaned_str = value_str.replace('.', '').replace(',', '.')
            else: cleaned_str = value_str.replace(',', '')
            return float(cleaned_str)
        except (ValueError, TypeError):
            logging.warning(f"Konnte '{value_str}' nicht in Float umwandeln (Lager).")
            return default

    def load_articles_from_db(self):
        self.all_articles_data = []
        if not self.conn:
            logging.error("Keine DB-Verbindung zum Laden der Artikel (Lager).")
            return
        try:
            cursor = self.conn.cursor()
            # ### GoBD-ÄNDERUNG ###: Nur aktive Artikel laden
            cursor.execute("SELECT id, artikelnummer, beschreibung, einheit, einzelpreis_netto, verfuegbar FROM artikel WHERE is_active = 1 ORDER BY beschreibung ASC")
            for row in cursor.fetchall(): self.all_articles_data.append(row)
            logging.info(f"{len(self.all_articles_data)} aktive Artikel in den Cache geladen (Lager).")
            self.filter_articles_live()
        except sqlite3.Error as e:
            messagebox.showerror("Datenbankfehler", f"Fehler beim Laden der Artikel: {e}", parent=self.root_lager)
            logging.error(f"DB-Fehler beim Laden der Artikel (Lager): {e}")
        self.clear_article_fields()
    
    def filter_articles_live(self, *args):
        search_term = self.search_var.get().lower()
        for item in self.tree_articles.get_children(): self.tree_articles.delete(item)
        for row in self.all_articles_data:
            artikelnummer = str(row[1]).lower() if row[1] else ""
            beschreibung = str(row[2]).lower() if row[2] else ""
            if search_term in artikelnummer or search_term in beschreibung:
                preis_netto_str = f"{self.robust_parse_float(row[4]):,.2f}".replace('.', '#').replace(',', '.').replace('#', ',') if row[4] is not None else ""
                verfuegbar_val = self.robust_parse_float(row[5], 0.0)
                verfuegbar_str = f"{verfuegbar_val:n}" if verfuegbar_val is not None else ""
                self.tree_articles.insert("", "end", values=(row[0], row[1], row[2], row[3] or "", preis_netto_str, verfuegbar_str))

    def on_tree_select(self, event=None):
        selected_item = self.tree_articles.focus()
        if not selected_item:
            self.btn_deactivate.config(state="disabled") # ### GoBD-ÄNDERUNG ###
            self.selected_article_id = None
            return
        try:
            values = self.tree_articles.item(selected_item, "values")
            self.selected_article_id = values[0]
            self.entries_artikel["artikelnummer"].delete(0, tk.END); self.entries_artikel["artikelnummer"].insert(0, values[1])
            self.entries_artikel["beschreibung"].delete(0, tk.END); self.entries_artikel["beschreibung"].insert(0, values[2])
            self.entries_artikel["einheit"].delete(0, tk.END); self.entries_artikel["einheit"].insert(0, values[3])
            preis_for_edit = values[4].replace('.', '').replace(',', '.')
            self.entries_artikel["einzelpreis_netto"].delete(0, tk.END); self.entries_artikel["einzelpreis_netto"].insert(0, preis_for_edit.replace('.', ','))
            menge_for_edit = values[5].replace('.', '').replace(',', '.')
            self.entries_artikel["verfuegbar"].delete(0, tk.END); self.entries_artikel["verfuegbar"].insert(0, menge_for_edit.replace('.', ','))
            self.btn_deactivate.config(state="normal") # ### GoBD-ÄNDERUNG ###
            self.btn_save.config(text="Änderungen speichern")
        except IndexError:
            logging.warning("IndexError bei Tree-Auswahl in Lagerverwaltung.")
            self.clear_article_fields()

    def clear_article_fields(self):
        for entry in self.entries_artikel.values(): entry.delete(0, tk.END)
        self.selected_article_id = None
        self.btn_deactivate.config(state="disabled") # ### GoBD-ÄNDERUNG ###
        self.btn_save.config(text="Neu/Speichern")
        if self.tree_articles.selection():
            try: self.tree_articles.selection_remove(self.tree_articles.selection()[0])
            except IndexError: pass
        self.entries_artikel["artikelnummer"].focus()

    def save_article_to_db(self):
        art_nr, beschreibung, einheit = self.entries_artikel["artikelnummer"].get().strip(), self.entries_artikel["beschreibung"].get().strip(), self.entries_artikel["einheit"].get().strip()
        preis_str, verfuegbar_str = self.entries_artikel["einzelpreis_netto"].get().strip(), self.entries_artikel["verfuegbar"].get().strip()
        if not art_nr or not beschreibung: messagebox.showwarning("Eingabe fehlt", "Artikelnummer und Beschreibung sind Pflichtfelder.", parent=self.root_lager); return
        preis_netto = self.robust_parse_float(preis_str, -1.0)
        if preis_netto < 0: messagebox.showwarning("Ungültiger Preis", "Einzelpreis muss eine gültige Zahl (>= 0) sein.", parent=self.root_lager); return
        verfuegbar = self.robust_parse_float(verfuegbar_str, -1.0)
        if verfuegbar < 0: messagebox.showwarning("Ungültige Menge", "Verfügbare Menge muss eine gültige Zahl (>= 0) sein.", parent=self.root_lager); return
        if not self.conn: messagebox.showerror("Datenbankfehler", "Keine Datenbankverbindung.", parent=self.root_lager); return
        
        cursor = self.conn.cursor()
        try:
            if self.selected_article_id:
                # ### GoBD-ÄNDERUNG ###: Alten Datensatz für Audit-Log holen
                cursor.execute("SELECT artikelnummer, beschreibung, einheit, einzelpreis_netto, verfuegbar FROM artikel WHERE id=?", (self.selected_article_id,))
                old_data_row = cursor.fetchone()
                if not old_data_row:
                    messagebox.showerror("Fehler", "Der zu bearbeitende Artikel konnte nicht gefunden werden.", parent=self.root_lager)
                    return
                
                # Prüfen, ob Artikelnummer geändert wurde und bereits existiert
                if art_nr != old_data_row[0]:
                    cursor.execute("SELECT id FROM artikel WHERE artikelnummer = ? AND id != ?", (art_nr, self.selected_article_id))
                    if cursor.fetchone(): messagebox.showerror("Fehler", f"Die neue Artikelnummer '{art_nr}' existiert bereits für einen anderen Artikel!", parent=self.root_lager); return
                
                # Änderungen für Audit-Log zusammenstellen
                changes = []
                if art_nr != old_data_row[0]: changes.append(f"artikelnummer von '{old_data_row[0]}' zu '{art_nr}'")
                if beschreibung != old_data_row[1]: changes.append(f"beschreibung von '{old_data_row[1]}' zu '{beschreibung}'")
                if (einheit or None) != old_data_row[2]: changes.append(f"einheit von '{old_data_row[2]}' zu '{einheit or None}'")
                if preis_netto != self.robust_parse_float(old_data_row[3]): changes.append(f"einzelpreis_netto von '{old_data_row[3]}' zu '{preis_netto}'")
                if verfuegbar != self.robust_parse_float(old_data_row[4]): changes.append(f"verfuegbar von '{old_data_row[4]}' zu '{verfuegbar}'")

                if changes:
                    cursor.execute("UPDATE artikel SET artikelnummer=?, beschreibung=?, einheit=?, einzelpreis_netto=?, verfuegbar=? WHERE id=?", (art_nr, beschreibung, einheit or None, preis_netto, verfuegbar, self.selected_article_id))
                    log_audit_event(self.conn, "ARTIKEL_GEAENDERT", self.selected_article_id, f"Änderungen: {'; '.join(changes)}.")
                    logging.info(f"Artikel ID {self.selected_article_id} aktualisiert: {art_nr}")
                else:
                    messagebox.showinfo("Information", "Keine Änderungen vorgenommen.", parent=self.root_lager)
                    return # Nichts zu tun
            else: # Neuer Artikel
                cursor.execute("SELECT id FROM artikel WHERE artikelnummer = ?", (art_nr,));
                if cursor.fetchone(): messagebox.showerror("Fehler", f"Artikelnummer '{art_nr}' existiert bereits!", parent=self.root_lager); return
                
                # ### GoBD-ÄNDERUNG ###: 'is_active' wird explizit gesetzt.
                cursor.execute("INSERT INTO artikel (artikelnummer, beschreibung, einheit, einzelpreis_netto, verfuegbar, is_active) VALUES (?, ?, ?, ?, ?, 1)", (art_nr, beschreibung, einheit or None, preis_netto, verfuegbar))
                new_id = cursor.lastrowid
                details = f"Artikel '{art_nr}' ({beschreibung}) erstellt. Preis: {preis_netto}, Verfügbar: {verfuegbar}."
                log_audit_event(self.conn, "ARTIKEL_ERSTELLT", new_id, details)
                logging.info(f"Neuer Artikel erstellt (ID {new_id}): {art_nr}")
            
            self.conn.commit()
            messagebox.showinfo("Erfolg", "Artikel erfolgreich gespeichert.", parent=self.root_lager)
            self.load_articles_from_db()
        except sqlite3.IntegrityError as e: messagebox.showerror("Datenbankfehler", f"Fehler bei der Datenbankintegrität (z.B. Artikelnummer bereits vorhanden): {e}", parent=self.root_lager); logging.error(f"IntegrityError beim Speichern von Artikel '{art_nr}': {e}."); self.conn.rollback()
        except sqlite3.Error as e: messagebox.showerror("Datenbankfehler", f"Fehler beim Speichern des Artikels: {e}", parent=self.root_lager); logging.error(f"DB-Fehler beim Speichern von Artikel '{art_nr}': {e}"); self.conn.rollback()

    # ### GoBD-ÄNDERUNG ###: Funktion ersetzt das physische Löschen
    def deactivate_article_in_db(self):
        """Markiert einen Artikel als inaktiv statt ihn zu löschen."""
        if not self.selected_article_id:
            messagebox.showwarning("Auswahl fehlt", "Kein Artikel zum Deaktivieren ausgewählt.", parent=self.root_lager)
            return

        art_nr_display = self.entries_artikel["artikelnummer"].get()
        confirm = messagebox.askyesno("Deaktivieren bestätigen", 
                                      f"Artikel '{art_nr_display}' (ID: {self.selected_article_id}) wirklich deaktivieren?\n\n"
                                      "Der Artikel wird aus den Auswahllisten entfernt, bleibt aber für historische Rechnungen erhalten.",
                                      icon='warning', parent=self.root_lager)
        if not confirm:
            return

        if not self.conn:
            messagebox.showerror("Datenbankfehler", "Keine Datenbankverbindung.", parent=self.root_lager)
            return

        try:
            cursor = self.conn.cursor()
            # Die Prüfung auf Verwendung in Rechnungen ist gut, aber nicht mehr blockierend.
            cursor.execute("SELECT COUNT(*) FROM rechnungsposten WHERE artikelnummer = (SELECT artikelnummer FROM artikel WHERE id=?)", (self.selected_article_id,))
            count_in_rechnungen = cursor.fetchone()[0]
            if count_in_rechnungen > 0:
                logging.warning(f"Artikel ID {self.selected_article_id} wird in {count_in_rechnungen} Rechnungsposten verwendet und wird nun deaktiviert.")

            # Statt DELETE wird UPDATE verwendet, um den Artikel als inaktiv zu markieren.
            cursor.execute("UPDATE artikel SET is_active = 0 WHERE id=?", (self.selected_article_id,))
            
            # Protokollieren der Deaktivierung
            log_audit_event(self.conn, "ARTIKEL_DEAKTIVIERT", self.selected_article_id, f"Artikel '{art_nr_display}' wurde deaktiviert.")
            
            self.conn.commit()
            messagebox.showinfo("Erfolg", f"Artikel '{art_nr_display}' wurde deaktiviert.", parent=self.root_lager)
            logging.info(f"Artikel ID {self.selected_article_id} ('{art_nr_display}') deaktiviert.")
            self.load_articles_from_db()
        except sqlite3.Error as e:
            messagebox.showerror("Datenbankfehler", f"Fehler beim Deaktivieren des Artikels: {e}", parent=self.root_lager)
            logging.error(f"DB-Fehler beim Deaktivieren von Artikel ID {self.selected_article_id}: {e}")
            self.conn.rollback()


# --- Hauptteil ---
if __name__ == "__main__":
    logging.info(f"=======================================\nStarte Lagerverwaltung (Tkinter)...")
    if not _run_daten_schloss_startup():
        logging.critical("DatenSchloss-Startup fehlgeschlagen. Lagerverwaltung wird beendet.")
        sys.exit(1)
    
    try:
        import locale
        try: locale.setlocale(locale.LC_ALL, 'de_DE.UTF-8')
        except locale.Error:
            try: locale.setlocale(locale.LC_ALL, 'German_Germany.1252')
            except locale.Error: logging.warning("Deutsche Locale konnte nicht gesetzt werden. Zahlenformatierung könnte abweichen.")
    except ImportError:
        logging.warning("Modul 'locale' nicht gefunden. Zahlenformatierung könnte abweichen.")

    app_instance = None
    root_lager_main = ThemedTk()
    try:
        root_lager_main.set_theme("breeze") 
    except tk.TclError as e_theme:
        logging.warning(f"ThemedTk Theme konnte nicht gesetzt werden (Lager): {e_theme}. Verwende Standard-Tkinter-Aussehen.")
    except Exception as e:
        logging.error(f"Unerwarteter Fehler beim Setzen des Themes (Lager): {e}")

    try:
        app_instance = LagerApp(root_lager_main)
        if hasattr(app_instance, 'conn') and app_instance.conn is not None:
            root_lager_main.mainloop()
        else:
            logging.critical("LagerApp konnte nicht gestartet werden aufgrund eines Datenbankverbindungsfehlers oder Schema-Fehlers.")
            if root_lager_main.winfo_exists(): root_lager_main.destroy()
            sys.exit(1)
    except Exception as e:
        logging.exception("Ein nicht abgefangener, kritischer Fehler ist in der Lagerverwaltung aufgetreten:")
        if app_instance and hasattr(app_instance, 'conn') and app_instance.conn:
             app_instance.conn.close()
        _run_daten_schloss_shutdown()
        messagebox.showerror("Kritischer Fehler", f"Ein unerwarteter Fehler ist aufgetreten:\n{e}\n\nLagerverwaltung wird beendet.")
        if root_lager_main.winfo_exists(): root_lager_main.destroy()
        sys.exit(1)