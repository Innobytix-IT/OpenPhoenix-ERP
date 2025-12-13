import sqlite3
import time
import threading
import os
import sys
import logging

# --- Logging Konfiguration ---
log_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bestandswächter.log')
logging.basicConfig(
    filename=log_file_path,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)

# --- Imports mit Fehlerbehandlung ---
try:
    from pystray import MenuItem as item, Icon
    from PIL import Image, ImageDraw
    from plyer import notification
    import tkinter as tk
    from tkinter import messagebox
except ImportError as e:
    logging.critical(f"Kritischer Fehler: Fehlende Bibliothek - {e}")
    root = tk.Tk(); root.withdraw()
    messagebox.showerror("Kritischer Fehler: Fehlende Bibliothek", f"Eine benötigte Bibliothek fehlt:\n\n{e}\n\n"
                         "Bitte führen Sie 'pip install pystray pillow plyer tkinter' in Ihrer Kommandozeile aus.")
    sys.exit(1)

# --- Konfiguration ---
CONFIG_FILENAME = "config.txt"
DEFAULT_DB_NAME = "unternehmen.db"
DB_CHECK_INTERVAL = 60
APP_NAME = "Lager-Monitor"
STOCK_WARN_LEVELS = [100, 90, 80, 70, 60, 50, 40, 30, 20, 10, 0]

# --- Globale Variablen ---
app_is_running = True
last_warned_level_for_article = {}

# --- Hilfsfunktionen ---
def get_db_path_from_config():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, CONFIG_FILENAME)
    if not os.path.exists(config_path):
        return os.path.join(script_dir, DEFAULT_DB_NAME)
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("db_path="):
                    return line.split("=", 1)[1].strip().replace('\\', '/')
    except Exception as e:
        logging.error(f"Fehler beim Lesen der '{CONFIG_FILENAME}': {e}")
    return os.path.join(script_dir, DEFAULT_DB_NAME)

def get_all_articles():
    db_path = get_db_path_from_config()
    if not db_path or not os.path.exists(db_path):
        return [], f"Datenbank nicht gefunden: {db_path}"
    
    try:
        conn = sqlite3.connect(db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT artikelnummer, beschreibung, verfuegbar FROM artikel WHERE is_active = 1")
        articles = cursor.fetchall()
        conn.close()
        return articles, None
    except Exception as e:
        if "no such column: is_active" in str(e).lower():
            logging.warning("Spalte 'is_active' in Tabelle 'artikel' nicht gefunden. Überwache alle Artikel (Alte DB-Version?).")
            try:
                conn_fallback = sqlite3.connect(db_path, timeout=10.0)
                conn_fallback.row_factory = sqlite3.Row
                cursor_fallback = conn_fallback.cursor()
                cursor_fallback.execute("SELECT artikelnummer, beschreibung, verfuegbar FROM artikel")
                articles = cursor_fallback.fetchall()
                conn_fallback.close()
                return articles, None
            except Exception as e_fallback:
                 return [], f"Fehler bei DB-Fallback-Abfrage: {e_fallback}"
        return [], f"Fehler bei DB-Abfrage: {e}"

def create_image(status='ok'):
    width, height = 64, 64
    color_map = {'ok': (0, 128, 0), 'warning': (255, 165, 0), 'critical': (255, 0, 0)}
    main_color = color_map.get(status, (128, 128, 128)) # Grau als Fallback

    image = Image.new('RGB', (width, height), "white")
    dc = ImageDraw.Draw(image)
    dc.rectangle((0, 0, width, height), fill=main_color)
    return image

# --- Tray-Icon Logik ---

def get_current_warn_level(stock_value):
    for level in STOCK_WARN_LEVELS:
        if stock_value <= level:
            return level
    return float('inf')

def update_stock_status(icon):
    """Prüfungs-Loop mit korrigierter Icon-Aktualisierung."""
    global last_warned_level_for_article
    
    # ### KORREKTUR: Variable zum Speichern des aktuellen Icon-Zustands ###
    current_icon_status = 'ok' 
    
    while app_is_running:
        all_articles, error = get_all_articles()
        
        if error:
            logging.error(f"Fehler bei der Lagerprüfung: {error}")
        else:
            notifications_to_send = []
            is_any_article_critical = False
            is_any_article_warning = False

            for article in all_articles:
                art_nr, bestand = article['artikelnummer'], article['verfuegbar']
                current_level = get_current_warn_level(bestand)
                last_level = last_warned_level_for_article.get(art_nr, float('inf'))
                
                if current_level < last_level:
                    bestand_str = int(bestand) if bestand == int(bestand) else f"{bestand:.2f}"
                    message = f"'{article['beschreibung']}' hat die Marke von {current_level} Stk. unterschritten (Aktuell: {bestand_str} Stk.)."
                    notifications_to_send.append(message)
                    last_warned_level_for_article[art_nr] = current_level

                if bestand <= 0:
                    is_any_article_critical = True
                elif bestand <= STOCK_WARN_LEVELS[0]:
                    is_any_article_warning = True

            new_icon_status = 'ok'
            if is_any_article_critical:
                new_icon_status = 'critical'
            elif is_any_article_warning:
                new_icon_status = 'warning'

            # ### KORREKTUR: Logik zur Icon-Aktualisierung ###
            # Nur wenn sich der Status geändert hat, wird das Icon neu gezeichnet.
            if new_icon_status != current_icon_status:
                logging.info(f"Icon-Status ändert sich von '{current_icon_status}' zu '{new_icon_status}'.")
                icon.icon = create_image(new_icon_status)
                current_icon_status = new_icon_status # Den neuen Status merken

            if notifications_to_send:
                full_message = "\n".join(notifications_to_send)
                try:
                    notification.notify(title='Lagerbestands-Information', message=full_message, app_name=APP_NAME, timeout=15)
                    logging.info(f"Benachrichtigung gesendet: {full_message}")
                except Exception as e:
                    logging.error(f"Fehler bei Desktop-Benachrichtigung: {e}")
        
        for _ in range(DB_CHECK_INTERVAL):
            if not app_is_running: break
            time.sleep(1)

def show_current_status(icon, item):
    """Zeigt eine MessageBox mit dem aktuellen detaillierten Status."""
    def show_message():
        root = tk.Tk(); root.withdraw()
        all_articles, error = get_all_articles()
        if error:
            messagebox.showerror("Fehler", error, parent=root)
            root.destroy()
            return
            
        critical_list, warning_list = [], []
        for article in all_articles:
            bestand = article['verfuegbar']
            bestand_str = int(bestand) if bestand == int(bestand) else f"{bestand:.2f}"
            message_part = f"- '{article['beschreibung']}' (Nr: {article['artikelnummer']}): {bestand_str} Stk."
            if bestand <= 0: critical_list.append(message_part)
            elif bestand <= STOCK_WARN_LEVELS[0]: warning_list.append(message_part)

        if not critical_list and not warning_list:
            messagebox.showinfo("Lagerstatus", "Alle Lagerbestände sind im grünen Bereich.", parent=root)
        else:
            full_message = ""
            if critical_list:
                full_message += "KRITISCHE BESTÄNDE (<= 0):\n" + "\n".join(critical_list)
            if warning_list:
                if full_message: full_message += "\n\n"
                full_message += f"WARNSTUFE ERREICHT (<= {STOCK_WARN_LEVELS[0]}):\n" + "\n".join(warning_list)
            messagebox.showwarning("Lagerbestands-Übersicht", full_message, parent=root)
        root.destroy()
    
    threading.Thread(target=show_message).start()

def quit_app(icon, item):
    """Beendet die Anwendung."""
    global app_is_running
    app_is_running = False
    icon.stop()
    logging.info("Anwendung wird beendet.")
    sys.exit(0)

# --- Hauptteil ---
def main():
    menu = (item('Status anzeigen', show_current_status), item('Beenden', quit_app))
    icon = Icon("LagerMonitor", create_image(), "Lagerbestands-Monitor", menu)
    
    monitor_thread = threading.Thread(target=update_stock_status, args=(icon,))
    monitor_thread.daemon = True
    monitor_thread.start()
    
    logging.info("Lager-Monitor gestartet.")
    icon.run()

if __name__ == "__main__":
    main()