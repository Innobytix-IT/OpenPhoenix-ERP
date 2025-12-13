import tkinter as tk
import tkinter.ttk as ttk
from tkinter import filedialog, messagebox, Toplevel, Label, Entry, Button
import os
import subprocess
import json
import sys
import psutil # Neues Modul importieren

# --- Konfiguration ---
# Liste der standardmäßigen Tools, die der Launcher finden soll
STANDARD_TOOLS = [
    "Kundenverwaltung",
    "Lagerverwaltung",
    "Mahnwesen",
    "4XRechnung",
    "Dashboard",
    "Datenschloss"
    
]

# Name der Anwendung, die automatisch gestartet werden soll ### NEU ###
AUTOSTART_APP_NAME = "Bestandswächter"

# Name der Konfigurationsdatei für benutzerdefinierte Buttons
CONFIG_FILE = "launcher_config.json"

# --- Helper Function: Prüfen ob App läuft ---
def is_app_running(app_path):
    """Prüft, ob eine Anwendung mit dem gegebenen Pfad bereits als Prozess läuft."""
    # Normalisiere den Pfad für einen zuverlässigen Vergleich (Case-Insensitive auf Windows)
    normalized_app_path = os.path.normcase(os.path.normpath(app_path))
    print(f"Prüfe, ob '{normalized_app_path}' läuft...")

    for proc in psutil.process_iter(['cmdline']):
        try:
            # Rufe die Befehlszeile des Prozesses ab
            # cmdline() gibt eine Liste von Argumenten zurück, das erste ist oft der Pfad zur ausführbaren Datei
            cmdline = proc.cmdline()
            
            if not cmdline: # Manche Prozesse haben keine cmdline (z.B. System Idle Process)
                continue

            # Normalisiere jeden Teil der Befehlszeile und prüfe, ob unser app_path enthalten ist
            # Dies ist robuster, da bei Skripten (py, pyw) der Interpreter (python.exe)
            # das erste Element ist und das Skript selbst ein späteres Argument.
            normalized_cmdline_parts = [os.path.normcase(os.path.normpath(arg)) for arg in cmdline]

            if normalized_app_path in normalized_cmdline_parts:
                 # Zusätzliche Logik: Manchmal enthält cmdline den Pfad als Teil eines Arguments (z.B. `--file C:\App\script.py`).
                 # Ein einfacher 'in' Check könnte falsch positive Ergebnisse liefern.
                 # Eine bessere Prüfung könnte sein, ob der Pfad als erstes Argument (für .exe) oder
                 # als das Skript-Argument nach dem Interpreter (für .py/.pyw) auftritt.
                 # Für die meisten Fälle, besonders .exe, ist der erste Teil ausschlaggebend.
                 # Für .pyw/py, die mit os.startfile gestartet werden, ist psutil.cmdline
                 # oft [pythonw.exe, C:\Pfad\zum\Skript.pyw].
                 # Wir können prüfen, ob der normalisierte App-Pfad
                 # 1. Das erste Element ist ODER
                 # 2. Ein Element nach dem ersten Element ist (typisch für Skripte)
                 
                 # Normalisierter Pfad des ausführbaren Teils (oft cmdline[0])
                 executable_part_norm = normalized_cmdline_parts[0] if normalized_cmdline_parts else ""

                 # Annahme 1: App-Pfad ist das Haupt-Executable (typisch für .exe)
                 if executable_part_norm == normalized_app_path:
                     print(f"  - Prozess gefunden mit übereinstimmendem Executable-Pfad: {cmdline}")
                     return True

                 # Annahme 2: App-Pfad ist ein Argument nach dem Executable (typisch für Skripte .py/.pyw)
                 # Prüfe die restlichen Argumente
                 for arg_norm in normalized_cmdline_parts[1:]:
                     if arg_norm == normalized_app_path:
                         print(f"  - Prozess gefunden mit übereinstimmendem Skript-Pfad in Argumenten: {cmdline}")
                         return True

                 # Wenn der normalisierte Pfad irgendwo anders auftaucht (z.B. in einem Argument),
                 # aber nicht als Executable oder Skript-Argument, ist es wahrscheinlich
                 # eine falsche Übereinstimmung. Wir ignorieren das erstmal für die Sicherheit,
                 # nur die oben genannten Fälle zu erfassen.

        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            # Prozess existiert nicht mehr oder Zugriffsfehler, überspringen
            continue
        except Exception as e:
            # Unerwarteter Fehler beim Abrufen von Prozessinfos
            print(f"Fehler beim Prüfen eines Prozesses: {e}")
            continue # Nächsten Prozess prüfen

    print("  - Anwendung scheint nicht zu laufen.")
    return False # Kein Prozess mit passendem Pfad gefunden


# --- Helper Function: App starten ---
def launch_application(app_path):
    """Startet die gegebene Anwendung, falls sie noch nicht läuft."""

    # 1. Prüfen, ob die Anwendung bereits läuft
    if is_app_running(app_path):
        messagebox.showinfo("Info", f"'{os.path.basename(app_path)}' läuft bereits.")
        print(f"Start abgebrochen: '{app_path}' läuft bereits.")
        return False # ### GEÄNDERT ### Gibt False zurück, wenn nicht gestartet wurde

    # 2. Anwendung starten, da sie nicht läuft
    print(f"Versuche zu starten: {app_path}")
    try:
        if sys.platform == "win32":
            os.startfile(app_path)
            print(f"  - Gestartet mit os.startfile (Windows): {app_path}")
        else:
            subprocess.Popen([app_path], shell=False)
            print(f"  - Gestartet mit subprocess.Popen shell=False (Andere OS / Fallback): {app_path}")
        
        return True # ### GEÄNDERT ### Gibt True zurück, wenn Start erfolgreich war

    except FileNotFoundError:
        messagebox.showerror("Fehler", f"Anwendung nicht gefunden: {app_path}")
        print(f"Fehler: Datei nicht gefunden - {app_path}")
    except Exception as e:
        error_message = str(e)
        messagebox.showerror("Fehler beim Starten", f"Konnte Anwendung {app_path} nicht starten:\n{error_message}")
        print(f"Fehler beim Starten von {app_path}: {error_message}")
    
    return False # ### GEÄNDERT ### Gibt False zurück, wenn ein Fehler aufgetreten ist


# --- Launcher App Klasse ---
class LauncherApp:
    def __init__(self, root):
        self.root = root
        root.title("Mein Software Launcher")
        root.geometry("400x500")
        root.resizable(False, False)

        self.base_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        print(f"Basisverzeichnis des Launchers: {self.base_dir}")

        self.user_buttons_data = []

        main_frame = ttk.Frame(root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        standard_frame = ttk.LabelFrame(main_frame, text="Standard Tools", padding="10")
        standard_frame.pack(pady=10, padx=10, fill=tk.X)

        user_frame = ttk.LabelFrame(main_frame, text="Benutzerdefinierte Tools", padding="10")
        user_frame.pack(pady=10, padx=10, fill=tk.BOTH, expand=True)
        user_frame.columnconfigure(0, weight=1)

        add_button_frame = ttk.Frame(main_frame, padding="10 0 0 0")
        add_button_frame.pack(pady=5, padx=10, fill=tk.X)

        self.create_standard_buttons(standard_frame)
        self.user_buttons_frame = user_frame
        self.create_add_button(add_button_frame)

        self.load_config()
        self.create_user_buttons_from_config()

        # ### NEU ### Autostart-Anwendung nach dem Initialisieren der GUI starten
        self.auto_start_background_app()

        root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
    # ### NEU ### Neue Methode zum Starten einer App und anschließendem Minimieren des Launchers
    def launch_and_minimize(self, app_path):
        """Wrapper, der eine Anwendung startet und den Launcher minimiert."""
        # Die globale Funktion gibt jetzt True zurück, wenn der Startversuch erfolgreich war.
        # So minimieren wir nicht, wenn die App schon läuft oder nicht gefunden wurde.
        was_launched = launch_application(app_path)
        if was_launched:
            print("Anwendung wurde gestartet. Minimiere Launcher.")
            self.root.iconify() # Minimiert das Hauptfenster

    # ### NEU ### Neue Methode zum automatischen Starten des Bestandswächters
    def auto_start_background_app(self):
        """Sucht nach 'Bestandswächter' mit verschiedenen Endungen und startet ihn."""
        print(f"\n--- Suche nach Autostart-Anwendung: '{AUTOSTART_APP_NAME}' ---")
        
        # Priorisierte Liste der Endungen
        extensions = [".exe", ".pyw", ".py"]
        app_to_start = None

        for ext in extensions:
            path_check = os.path.join(self.base_dir, f"{AUTOSTART_APP_NAME}{ext}")
            if os.path.exists(path_check):
                app_to_start = path_check
                print(f"'{AUTOSTART_APP_NAME}' gefunden unter: {app_to_start}")
                break # Die erste gefundene Version wird verwendet

        if app_to_start:
            # Wir rufen hier die normale 'launch_application' auf, da der Launcher
            # beim Autostart nicht minimiert werden soll.
            print(f"Starte '{AUTOSTART_APP_NAME}' im Hintergrund...")
            launch_application(app_to_start)
        else:
            print(f"Keine Autostart-Anwendung '{AUTOSTART_APP_NAME}' gefunden.")
        print("--- Suche abgeschlossen ---\n")


    def create_standard_buttons(self, parent_frame):
        """Erstellt die Buttons für die Standard-Tools."""
        print("Erstelle Standard-Buttons...")
        row = 0
        for tool_name in STANDARD_TOOLS:
            exe_path = os.path.join(self.base_dir, f"{tool_name}.exe")
            pyw_path = os.path.join(self.base_dir, f"{tool_name}.pyw")
            py_path = os.path.join(self.base_dir, f"{tool_name}.py")

            app_path = None
            button_state = tk.DISABLED
            
            if os.path.exists(exe_path):
                app_path = exe_path
                button_state = tk.NORMAL
                print(f"  - {tool_name}: .exe gefunden ({app_path})")
            elif os.path.exists(pyw_path):
                app_path = pyw_path
                button_state = tk.NORMAL
                print(f"  - {tool_name}: .pyw gefunden ({app_path})")
            elif os.path.exists(py_path): # ### NEU ### Auch auf .py prüfen
                app_path = py_path
                button_state = tk.NORMAL
                print(f"  - {tool_name}: .py gefunden ({app_path})")
            else:
                print(f"  - {tool_name}: nicht gefunden")

            button = ttk.Button(parent_frame, text=tool_name, state=button_state)
            if app_path:
                # ### GEÄNDERT ### Verwendet jetzt die neue Methode, die das Fenster minimiert.
                button.config(command=lambda path=app_path: self.launch_and_minimize(path))

            button.pack(pady=5, fill=tk.X)

    def create_add_button(self, parent_frame):
        """Erstellt den Button zum Hinzufügen neuer Tools."""
        add_btn = ttk.Button(parent_frame, text="Neuen Button hinzufügen...", command=self.open_add_button_dialog)
        add_btn.pack(fill=tk.X)

    def open_add_button_dialog(self):
        """Öffnet ein neues Fenster/Dialog zum Hinzufügen eines Buttons."""
        print("Öffne 'Button hinzufügen' Dialog...")
        dialog = Toplevel(self.root)
        dialog.title("Neuen Button hinzufügen")
        dialog.geometry("400x200")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        dialog_frame = ttk.Frame(dialog, padding="10")
        dialog_frame.pack(fill=tk.BOTH, expand=True)
        dialog_frame.columnconfigure(1, weight=1)

        ttk.Label(dialog_frame, text="Button Label:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        label_entry = ttk.Entry(dialog_frame, width=40)
        label_entry.grid(row=0, column=1, padx=5, pady=5, sticky=(tk.W, tk.E))

        ttk.Label(dialog_frame, text="Anwendungspfad:").grid(row=1, column=0, padx=5, pady=5, sticky=tk.W)
        path_entry = ttk.Entry(dialog_frame, width=40, state='readonly')
        path_entry.grid(row=1, column=1, padx=5, pady=5, sticky=(tk.W, tk.E))

        browse_btn = ttk.Button(dialog_frame, text="Durchsuchen...", command=lambda: self.browse_file(path_entry))
        browse_btn.grid(row=1, column=2, padx=5, pady=5)

        button_frame = ttk.Frame(dialog_frame)
        button_frame.grid(row=2, column=0, columnspan=3, pady=10)

        save_btn = ttk.Button(button_frame, text="Speichern", command=lambda: self.save_new_button(dialog, label_entry.get(), path_entry.get()))
        save_btn.pack(side=tk.LEFT, padx=5)

        cancel_btn = ttk.Button(button_frame, text="Abbrechen", command=dialog.destroy)
        cancel_btn.pack(side=tk.LEFT, padx=5)
        
        label_entry.focus_set()

    def browse_file(self, path_entry_widget):
        """Öffnet einen Dateidialog zur Auswahl einer ausführbaren Datei."""
        file_path = filedialog.askopenfilename(
            title="Anwendung auswählen",
            filetypes=[
                ("Ausführbare Dateien", "*.exe *.pyw *.py *.bat *.cmd *.sh"),
                ("Alle Dateien", "*.*")
            ]
        )
        if file_path:
            path_entry_widget.config(state='normal')
            path_entry_widget.delete(0, tk.END)
            path_entry_widget.insert(0, file_path)
            path_entry_widget.config(state='readonly')
            print(f"Datei ausgewählt: {file_path}")

    def save_new_button(self, dialog, label, path):
        """Speichert die Daten des neuen Buttons und erstellt den Button im GUI."""
        if not label:
            messagebox.showwarning("Eingabe fehlt", "Bitte geben Sie ein Label für den Button ein.")
            return
        if not path:
            messagebox.showwarning("Eingabe fehlt", "Bitte wählen Sie einen Anwendungspfad aus.")
            return

        new_button_data = {"label": label, "path": path}
        self.user_buttons_data.append(new_button_data)
        self.create_user_button(label, path)
        self.save_config()
        dialog.destroy()
        print(f"Neuer Button gespeichert: Label='{label}', Pfad='{path}'")


    def create_user_button(self, label, path):
        """Erstellt einen einzelnen benutzerdefinierten Button im GUI."""
        # ### GEÄNDERT ### Verwendet jetzt auch die Methode zum Minimieren.
        btn = ttk.Button(self.user_buttons_frame, text=label, command=lambda p=path: self.launch_and_minimize(p))
        btn.pack(pady=5, fill=tk.X)
        print(f"  - Benutzer-Button erstellt: Label='{label}'")


    def load_config(self):
        """Lädt die Konfiguration der benutzerdefinierten Buttons aus der Datei."""
        config_path = os.path.join(self.base_dir, CONFIG_FILE)
        print(f"Lade Konfiguration von: {config_path}")
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    self.user_buttons_data = json.load(f)
                print(f"  - Konfiguration erfolgreich geladen. {len(self.user_buttons_data)} benutzerdefinierte Buttons gefunden.")
            except json.JSONDecodeError:
                messagebox.showerror("Konfigurationsfehler", f"Fehler beim Lesen der Konfigurationsdatei '{CONFIG_FILE}'. Sie könnte beschädigt sein.")
                print(f"  - Fehler: Konfigurationsdatei '{CONFIG_FILE}' ist kein gültiges JSON.")
                self.user_buttons_data = []
            except Exception as e:
                messagebox.showerror("Konfigurationsfehler", f"Fehler beim Laden der Konfigurationsdatei '{CONFIG_FILE}':\n{e}")
                print(f"  - Fehler beim Laden der Konfiguration: {e}")
                self.user_buttons_data = []
        else:
            print("  - Konfigurationsdatei nicht gefunden. Starte ohne benutzerdefinierte Buttons.")
            self.user_buttons_data = []


    def save_config(self):
        """Speichert die aktuelle Konfiguration der benutzerdefinierten Buttons in die Datei."""
        config_path = os.path.join(self.base_dir, CONFIG_FILE)
        print(f"Speichere Konfiguration nach: {config_path}")
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(self.user_buttons_data, f, indent=4)
            print("  - Konfiguration erfolgreich gespeichert.")
        except Exception as e:
            messagebox.showerror("Speicherfehler", f"Fehler beim Speichern der Konfigurationsdatei '{CONFIG_FILE}':\n{e}")
            print(f"  - Fehler beim Speichern der Konfiguration: {e}")

    def create_user_buttons_from_config(self):
        """Erstellt die benutzerdefinierten Buttons basierend auf der geladenen Konfiguration."""
        print("Erstelle benutzerdefinierte Buttons aus Konfiguration...")
        if self.user_buttons_data:
            for item in self.user_buttons_data:
                if "label" in item and "path" in item:
                    self.create_user_button(item["label"], item["path"])
                else:
                    print(f"  - Warnung: Ungültiges Datenformat in Konfiguration: {item}")
        else:
             print("  - Keine benutzerdefinierten Buttons in Konfiguration gefunden.")


    def on_closing(self):
        """Wird aufgerufen, wenn das Fenster geschlossen wird. Speichert die Konfiguration."""
        print("Fenster wird geschlossen. Speichere Konfiguration...")
        self.save_config()
        self.root.destroy()


# --- Hauptausführung ---
if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    os.chdir(script_dir)
    print(f"Aktuelles Arbeitsverzeichnis geändert zu: {os.getcwd()}")

    try:
        import psutil
    except ImportError:
        messagebox.showerror("Fehler: psutil fehlt",
                             "Das 'psutil'-Modul wird benötigt, um laufende Anwendungen zu prüfen.\n"
                             "Bitte installieren Sie es über die Kommandozeile mit:\n"
                             "pip install psutil\n"
                             "Der Launcher wird ohne diese Funktion gestartet.")
        def is_app_running(app_path):
             print("ACHTUNG: psutil nicht installiert. Prüfung auf laufende Prozesse deaktiviert.")
             return False

    root = tk.Tk()
    app = LauncherApp(root)
    root.mainloop()