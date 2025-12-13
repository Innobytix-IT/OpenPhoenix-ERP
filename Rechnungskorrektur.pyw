import tkinter as tk
from tkinter import ttk, messagebox
import sqlite3
import os
from datetime import datetime
import logging
from ttkthemes import ThemedTk
import sys  # --- DATENSCHLOSS-ÄNDERUNG ---
import subprocess  # --- DATENSCHLOSS-ÄNDERUNG ---

# --- Grundkonfiguration ---
DB_FILENAME = "unternehmen_gobd.db"
LOG_FILENAME = "storno_tool.log"

# --- Logging Konfigurieren ---
logging.basicConfig(filename=LOG_FILENAME, level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# --- DATENSCHLOSS-ÄNDERUNG: Funktionen zum Starten des externen Tools ---
# (Exakt dieselben Funktionen wie in der Hauptanwendung)

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
        logging.info(f"DatenSchloss Tool gefunden (PYW): {tool_pyw_path} (Interpreter: {interpreter})")
        return [interpreter, tool_pyw_path]

    logging.warning("DatenSchloss Tool nicht gefunden (gesucht: .exe, .pyw).")
    return None

def _run_daten_schloss_startup():
    """Startet das DatenSchloss Tool vor der Hauptanwendung und wartet auf dessen Beendigung."""
    logging.info("Storno-Tool: Prüfe und starte DatenSchloss Tool (Startup)...")
    tool_command = _find_daten_schloss_tool()

    if tool_command:
        try:
            process = subprocess.run(tool_command, check=True, cwd=os.path.dirname(os.path.abspath(__file__)), text=True, capture_output=True)
            logging.info(f"Storno-Tool: DatenSchloss Tool (Startup) erfolgreich beendet. Exit Code: {process.returncode}")
            return True
        except Exception as e:
            logging.error(f"Storno-Tool: Fehler beim Ausführen des DatenSchloss Tools (Startup): {e}")
            messagebox.showerror("Fehler", f"Das Tool 'DatenSchloss' ist beim Start unerwartet beendet.\n\nDetails: {e}\n\nStorno-Tool wird beendet.")
            return False
    else:
        logging.error("Storno-Tool: DatenSchloss Tool wurde nicht gefunden. Storno-Tool kann nicht gestartet werden.")
        messagebox.showerror("Fehler", "Das benötigte Tool 'DatenSchloss' wurde im Anwendungsverzeichnis nicht gefunden.\n\nStorno-Tool wird beendet.")
        return False

def _run_daten_schloss_shutdown():
    """Startet das DatenSchloss Tool nach Beendigung der Hauptanwendung."""
    logging.info("Storno-Tool: Starte DatenSchloss Tool (Shutdown)...")
    tool_command = _find_daten_schloss_tool()
    if tool_command:
        try:
            subprocess.run(tool_command, cwd=os.path.dirname(os.path.abspath(__file__)), text=True, capture_output=True)
            logging.info("Storno-Tool: DatenSchloss Tool (Shutdown) erfolgreich aufgerufen.")
        except Exception as e:
            logging.error(f"Storno-Tool: Fehler beim Starten des DatenSchloss Tools (Shutdown): {e}")
    else:
        logging.warning("Storno-Tool: DatenSchloss Tool nicht gefunden, kann nicht beim Beenden gestartet werden.")

# --- ENDE DATENSCHLOSS-ÄNDERUNG ---


class StornoApp:
    def __init__(self, root):
        self.root = root
        self.root.title("GoBD-konformes Rechnungs-Storno-Tool")
        self.root.geometry("600x550")
        self.root.resizable(False, False)

        # --- Instanzvariablen ---
        self.db_path = self._find_db_path()
        self.conn = None
        self.current_invoice_info = None # Speichert Infos der gefundenen Rechnung

        # --- GUI erstellen ---
        self.create_widgets()

        # --- Datenbankverbindung herstellen ---
        if not self.db_path:
            self.log_message(f"FEHLER: Datenbank '{DB_FILENAME}' nicht gefunden. Bitte stellen Sie sicher, dass das Tool im selben Ordner wie die DB liegt.", "error")
            messagebox.showerror("Datenbankfehler", f"Die Datenbank '{DB_FILENAME}' wurde nicht gefunden.")
            self.root.after(100, self.on_closing)
            return

        self.conn = self.connect_db()
        if not self.conn:
             self.root.after(100, self.on_closing) # Beenden, wenn DB nicht geladen werden kann

    def _find_db_path(self):
        """Sucht die DB-Datei im Skript-Verzeichnis."""
        script_dir = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(script_dir, DB_FILENAME)
        return path if os.path.exists(path) else None

    def connect_db(self):
        """Stellt die Verbindung zur Datenbank her."""
        try:
            conn = sqlite3.connect(self.db_path, timeout=10.0)
            self.log_message(f"Erfolgreich mit Datenbank verbunden: {self.db_path}", "info")
            return conn
        except sqlite3.Error as e:
            self.log_message(f"FEHLER beim Verbinden mit der Datenbank: {e}", "error")
            messagebox.showerror("Datenbankfehler", f"Konnte keine Verbindung zur Datenbank herstellen:\n{e}")
            return None

    def create_widgets(self):
        """Erstellt alle GUI-Elemente."""
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # --- Suchbereich ---
        search_frame = ttk.LabelFrame(main_frame, text="1. Zu stornierende Rechnung suchen")
        search_frame.pack(fill=tk.X, pady=5)

        ttk.Label(search_frame, text="Rechnungsnummer:").pack(side=tk.LEFT, padx=5, pady=10)
        self.entry_re_nr = ttk.Entry(search_frame, width=30)
        self.entry_re_nr.pack(side=tk.LEFT, padx=5, pady=10, fill=tk.X, expand=True)
        self.btn_paste_nr = ttk.Button(search_frame, text="Einfügen", command=self.paste_invoice_number)
        self.btn_paste_nr.pack(side=tk.LEFT, padx=(0, 5), pady=10)
        self.btn_search = ttk.Button(search_frame, text="Suchen", command=self.search_invoice)
        self.btn_search.pack(side=tk.LEFT, padx=5, pady=10)
        self.entry_re_nr.bind("<Return>", lambda event: self.search_invoice())

        # --- Detailbereich ---
        details_frame = ttk.LabelFrame(main_frame, text="2. Details prüfen")
        details_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        self.text_details = tk.Text(details_frame, height=8, width=60, wrap=tk.WORD, state=tk.DISABLED, font=("Consolas", 10))
        self.text_details.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # --- Aktionsbereich ---
        action_frame = ttk.LabelFrame(main_frame, text="3. Aktion ausführen")
        action_frame.pack(fill=tk.X, pady=5)

        self.btn_stornieren = ttk.Button(action_frame, text="Rechnung stornieren", state=tk.DISABLED, command=self.execute_storno)
        self.btn_stornieren.pack(pady=10)

        # --- Protokollbereich ---
        log_frame = ttk.LabelFrame(main_frame, text="Protokoll")
        log_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        log_scrollbar = ttk.Scrollbar(log_frame)
        log_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text = tk.Text(log_frame, height=6, state=tk.DISABLED, wrap=tk.WORD, yscrollcommand=log_scrollbar.set)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        log_scrollbar.config(command=self.log_text.yview)
    

    def paste_invoice_number(self):
        temp_file = "temporärspeicher.tmp"
        try:
            if not os.path.exists(temp_file):
                messagebox.showwarning("Keine Daten", "Es wurde keine Rechnungsnummer vorbereitet (temporärspeicher.tmp nicht gefunden).", parent=self.root)
                return

            with open(temp_file, "r", encoding="utf-8") as f:
                rechnungs_nr = f.read().strip()
        
            self.entry_re_nr.delete(0, tk.END)
            self.entry_re_nr.insert(0, rechnungs_nr)
        
            self.log_message(f"Rechnungsnummer '{rechnungs_nr}' aus temporärer Datei eingefügt.", "info")
            # Optional: direkt die Suche auslösen
            self.search_invoice()

        except Exception as e:
            messagebox.showerror("Fehler", f"Vorbereitete Rechnungsnummer konnte nicht gelesen werden:\n{e}", parent=self.root)
            self.log_message(f"Fehler beim Lesen der temporären Datei: {e}", "error")





    def log_message(self, message, level="info"):
        """Gibt eine Nachricht im GUI-Log und im File-Log aus."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted_message = f"[{timestamp}] {message}\n"

        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, formatted_message)
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

        if level == "error":
            logging.error(message)
        else:
            logging.info(message)

    def search_invoice(self):
        """Sucht die eingegebene Rechnung und prüft, ob sie stornierbar ist."""
        re_nr = self.entry_re_nr.get().strip()
        if not re_nr:
            return

        self.log_message(f"Suche nach Rechnung Nr. '{re_nr}'...")
        self.text_details.config(state=tk.NORMAL)
        self.text_details.delete("1.0", tk.END)
        self.btn_stornieren.config(state=tk.DISABLED)
        self.current_invoice_info = None

        if not self.conn:
            self.log_message("Keine Datenbankverbindung.", "error")
            self.text_details.config(state=tk.DISABLED)
            return

        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT r.id, r.rechnungsdatum, r.summe_brutto, r.status, r.is_finalized, k.vorname, k.name, k.id
                FROM rechnungen r
                JOIN kunden k ON r.kunde_id = k.id
                WHERE r.rechnungsnummer = ?
            """, (re_nr,))
            result = cursor.fetchone()

            if not result:
                self.log_message(f"Rechnung Nr. '{re_nr}' nicht gefunden.", "error")
                self.text_details.insert(tk.END, f"FEHLER: Rechnung '{re_nr}' wurde nicht gefunden.")
                self.text_details.config(state=tk.DISABLED)
                return

            re_id, re_datum, re_brutto, re_status, is_finalized, k_vorname, k_name, k_id = result
            
            # Validierungen
            if not is_finalized:
                self.log_message(f"Rechnung '{re_nr}' ist ein Entwurf und kann nicht storniert werden.", "error")
                details = f"Rechnungs-ID: {re_id}\nKunde:         {k_vorname} {k_name}\n\nFEHLER: Dies ist ein Rechnungs-Entwurf. Entwürfe können im Hauptprogramm gelöscht, aber nicht storniert werden."
                self.text_details.insert(tk.END, details)
                self.text_details.config(state=tk.DISABLED)
                return

            if re_status == 'Storniert':
                self.log_message(f"Rechnung '{re_nr}' wurde bereits storniert.", "info")
                details = f"Rechnungs-ID: {re_id}\nKunde:         {k_vorname} {k_name}\nBetrag:        {re_brutto:,.2f} €\nStatus:        BEREITS STORNIERT"
                self.text_details.insert(tk.END, details)
                self.text_details.config(state=tk.DISABLED)
                return
            
            # Erfolgreich gefunden und validiert
            self.current_invoice_info = {
                're_id': re_id, 're_nr': re_nr, 'kunde_id': k_id,
                'kunde_name': f"{k_vorname} {k_name}"
            }
            details = f"Rechnungs-ID: {re_id}\nRechnungs-Nr:  {re_nr}\nDatum:         {re_datum}\nKunde:         {k_vorname} {k_name}\nBetrag:        {re_brutto:,.2f} €\n\nSTATUS: Rechnung ist finalisiert und kann storniert werden."
            self.text_details.insert(tk.END, details)
            self.btn_stornieren.config(state=tk.NORMAL)
            self.log_message(f"Rechnung '{re_nr}' gefunden und bereit zur Stornierung.")

        except sqlite3.Error as e:
            self.log_message(f"Datenbankfehler bei der Suche: {e}", "error")
            self.text_details.insert(tk.END, f"DATENBANKFEHLER: {e}")
        finally:
            self.text_details.config(state=tk.DISABLED)

    def execute_storno(self):
        """Führt den eigentlichen Stornierungsprozess durch."""
        if not self.current_invoice_info:
            return

        re_nr = self.current_invoice_info['re_nr']
        if not messagebox.askyesno("Stornierung endgültig bestätigen",
                                   f"Soll die Rechnung Nr. '{re_nr}' wirklich und unwiderruflich storniert werden?\n\nDieser Vorgang kann nicht rückgängig gemacht werden!",
                                   icon=messagebox.WARNING):
            self.log_message("Stornierung durch Benutzer abgebrochen.", "info")
            return

        self.btn_stornieren.config(state=tk.DISABLED)
        self.btn_search.config(state=tk.DISABLED)
        self.log_message(f"Starte Stornierungsprozess für Rechnung '{re_nr}'...", "info")

        cursor = self.conn.cursor()
        try:
            # 1. Daten der Originalrechnung laden
            cursor.execute("SELECT * FROM rechnungen WHERE id=?", (self.current_invoice_info['re_id'],))
            re_cols = [d[0] for d in cursor.description]
            original_re_data = dict(zip(re_cols, cursor.fetchone()))

            cursor.execute("SELECT * FROM rechnungsposten WHERE rechnung_id=?", (self.current_invoice_info['re_id'],))
            posten_cols = [d[0] for d in cursor.description]
            original_posten_data = [dict(zip(posten_cols, row)) for row in cursor.fetchall()]
            self.log_message("Originaldaten geladen.", "info")

            # 2. Neue Stornorechnung in DB anlegen
            storno_re_nr = self._get_next_storno_number(cursor)
            storno_bemerkung = f"Korrektur/Stornierung der Rechnung Nr. {original_re_data['rechnungsnummer']} vom {original_re_data['rechnungsdatum']}"
            
            cursor.execute("""
                INSERT INTO rechnungen (kunde_id, rechnungsnummer, rechnungsdatum, summe_netto, summe_mwst, summe_brutto, mwst_prozent, offener_betrag, status, bemerkung, is_finalized)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0.0, 'Gutschrift', ?, 1)
            """, (
                original_re_data['kunde_id'], storno_re_nr, datetime.now().strftime("%d.%m.%Y"),
                -original_re_data['summe_netto'], -original_re_data['summe_mwst'], -original_re_data['summe_brutto'],
                original_re_data['mwst_prozent'], storno_bemerkung
            ))
            storno_re_id = cursor.lastrowid
            self._log_audit_event(cursor, "STORNORECHNUNG_ERSTELLT", storno_re_id, f"Storno-Rg. '{storno_re_nr}' für Original-Rg. ID {self.current_invoice_info['re_id']} erstellt.")
            self.log_message(f"Neue Stornorechnung '{storno_re_nr}' (ID: {storno_re_id}) erstellt.", "info")

            # 3. Negative Posten für Stornorechnung anlegen
            storno_posten_for_db = []
            for posten in original_posten_data:
                storno_posten_for_db.append((
                    storno_re_id, posten['position'], posten['artikelnummer'], posten['beschreibung'],
                    -posten['menge'], posten['einheit'], posten['einzelpreis_netto'], -posten['gesamtpreis_netto']
                ))
            cursor.executemany("""
                INSERT INTO rechnungsposten (rechnung_id, position, artikelnummer, beschreibung, menge, einheit, einzelpreis_netto, gesamtpreis_netto)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, storno_posten_for_db)
            self.log_message("Negative Rechnungsposten für Storno-Rg. erstellt.", "info")

            # 4. Lagerbestand korrigieren (Artikel zurückbuchen)
            items_to_book_back = [{'artikelnummer': p['artikelnummer'], 'menge': p['menge']} for p in original_posten_data if p['artikelnummer']]
            self._book_stock_change(cursor, items_to_book_back, 'in', storno_re_id)
            self.log_message("Lagerbestand korrigiert (Artikel zurückgebucht).", "info")

            # 5. Originalrechnung auf 'Storniert' setzen
            cursor.execute("UPDATE rechnungen SET status='Storniert' WHERE id=?", (self.current_invoice_info['re_id'],))
            self._log_audit_event(cursor, "RECHNUNG_STORNIERT", self.current_invoice_info['re_id'], f"Rechnung '{re_nr}' wurde durch Storno-Rg. ID {storno_re_id} storniert.")
            self.log_message(f"Originalrechnung '{re_nr}' als 'Storniert' markiert.", "info")
            
            self.conn.commit()
            self.log_message("--- Stornierung erfolgreich abgeschlossen! ---", "info")
            messagebox.showinfo("Erfolg", f"Rechnung '{re_nr}' wurde erfolgreich storniert.\n\nNeue Korrekturrechnung:\n{storno_re_nr}")
            
            # UI zurücksetzen
            self.entry_re_nr.delete(0, tk.END)
            self.search_invoice()


        except sqlite3.Error as e:
            self.conn.rollback()
            self.log_message(f"DATENBANKFEHLER bei Stornierung: {e}", "error")
            messagebox.showerror("Datenbankfehler", f"Ein schwerwiegender Datenbankfehler ist aufgetreten:\n{e}\n\nDie Transaktion wurde zurückgerollt. Es wurden keine Änderungen gespeichert.")
        except Exception as e:
            self.conn.rollback()
            self.log_message(f"ALLGEMEINER FEHLER bei Stornierung: {e}", "error")
            messagebox.showerror("Programmfehler", f"Ein unerwarteter Fehler ist aufgetreten:\n{e}\n\nDie Transaktion wurde zurückgerollt. Es wurden keine Änderungen gespeichert.")
        finally:
            self.btn_search.config(state=tk.NORMAL)


    def _get_next_storno_number(self, cursor):
        """Ermittelt die nächste freie Stornorechnungsnummer."""
        current_year = datetime.now().strftime('%Y')
        prefix = f"ST-{current_year}-"
        query = "SELECT rechnungsnummer FROM rechnungen WHERE rechnungsnummer LIKE ? ORDER BY CAST(SUBSTR(rechnungsnummer, 9) AS INTEGER) DESC LIMIT 1"
        cursor.execute(query, (f"{prefix}%",))
        last_storno = cursor.fetchone()
        if last_storno and last_storno[0]:
            parts = last_storno[0].split('-')
            if len(parts) == 3 and parts[2].isdigit():
                return f"{prefix}{int(parts[2]) + 1:04d}"
        return f"{prefix}0001"

    def _log_audit_event(self, cursor, action, record_id=None, details=""):
        """Schreibt einen Eintrag in das Audit-Protokoll."""
        try:
            user = "storno_tool"
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
            cursor.execute(
                "INSERT INTO audit_log (timestamp, user, action, record_id, details) VALUES (?, ?, ?, ?, ?)",
                (timestamp, user, action, record_id, details)
            )
        except sqlite3.Error as e:
            self.log_message(f"Konnte Audit-Log-Eintrag nicht schreiben: {e}", "error")

    def _book_stock_change(self, cursor, items, direction, invoice_id_for_log=""):
        """Bucht Lagerbestände. 'in' für zurückbuchen, 'out' für abbuchen."""
        if not items:
            return
        
        updates_to_perform = [(
            item['menge'] if direction == 'in' else -item['menge'],
            item['artikelnummer']
        ) for item in items]
        
        if updates_to_perform:
            cursor.executemany("UPDATE artikel SET verfuegbar = verfuegbar + ? WHERE artikelnummer = ?", updates_to_perform)
            log_direction = "zurückgebucht" if direction == 'in' else "abgebucht"
            self.log_message(f"Lagerbestand für {len(updates_to_perform)} Artikel für Rg. ID {invoice_id_for_log} {log_direction}.", "info")

    def on_closing(self):
        """Wird aufgerufen, wenn das Fenster geschlossen wird."""
        if self.conn:
            self.conn.close()
            logging.info("Storno-Tool: Datenbankverbindung geschlossen.")
        self.root.destroy()
        # --- DATENSCHLOSS-ÄNDERUNG: Aufruf beim Beenden ---
        _run_daten_schloss_shutdown()


if __name__ == "__main__":
    # --- DATENSCHLOSS-ÄNDERUNG: Aufruf vor dem Start ---
    if not _run_daten_schloss_startup():
        sys.exit(1) # Beenden, wenn das Datenschloss-Tool fehlschlägt

    try:
        logging.info("Storno-Tool: Starte Hauptanwendung (Tkinter GUI)...")
        root = ThemedTk(theme="breeze")
        app = StornoApp(root)
        root.protocol("WM_DELETE_WINDOW", app.on_closing)
        root.mainloop()
    except Exception as e:
        logging.critical(f"Kritischer Fehler im Storno-Tool: {e}", exc_info=True)
        messagebox.showerror("Fataler Fehler", f"Ein kritischer Fehler ist aufgetreten und wurde in '{LOG_FILENAME}' protokolliert:\n\n{e}")
        # --- DATENSCHLOSS-ÄNDERUNG: Aufruf auch bei Fehler ---
        _run_daten_schloss_shutdown()
        sys.exit(1)