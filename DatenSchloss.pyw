import tkinter as tk
from tkinter import filedialog, messagebox, ttk, font as tkfont
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.exceptions import InvalidTag
import os
import threading
import queue
import time
import traceback
import json
import pyperclip
import re

# --- Konstanten, Konfigurationsfunktionen, Kryptofunktionen, Ordnerfunktionen ---
SALT_SIZE = 16
NONCE_SIZE = 12
TAG_SIZE = 16
CHUNK_SIZE = 64 * 1024
PBKDF2_ITERATIONS = 100_000
APP_NAME = "DatenbankSchloss"
CONFIG_DIR_NAME = "." + APP_NAME.lower()
CONFIG_FILE_NAME = "config.json"
DEFAULT_DB_FILENAME = "unternehmen.db"
APP_ICON_FILENAME = "app_icon.ico"  # Dateiname für Ihr Icon (z.B. app_icon.ico)

PW_STRENGTH_LEVELS = {
    "empty": {"text": " ", "color": "grey", "value": 0, "bar_color": "grey"},
    "kritisch": {"text": "Kritisch", "color": "red", "value": 20, "bar_color": "red"},
    "verbesserungswürdig": {"text": "Verbesserungswürdig", "color": "orange", "value": 40, "bar_color": "orange"},
    "mittel": {"text": "Mittel", "color": "#CCCC00", "value": 60, "bar_color": "#CCCC00"},
    "okay": {"text": "Okay", "color": "green", "value": 80, "bar_color": "green"},
    "stark": {"text": "Stark", "color": "darkgreen", "value": 100, "bar_color": "darkgreen"}
}

FILE_STATUS_COLORS = {
    "offen": "red",
    "verschlüsselt": "green",
    "gemischt": "orange",
    "unbekannt": "grey",
    "ungültig": "grey"
}

# ... (get_config_path, load_config, save_config, generate_aes_key, Kryptofunktionen bleiben gleich) ...
def get_config_path():
    config_dir = os.path.dirname(os.path.abspath(__file__))
    if not os.path.exists(config_dir):
        try: os.makedirs(config_dir)
        except OSError as e: print(f"Warnung: Konnte Konfigurationsverzeichnis nicht erstellen: {e}")
    return os.path.join(config_dir, CONFIG_FILE_NAME)

def load_config():
    config_path = get_config_path()
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f: return json.load(f)
        except (json.JSONDecodeError, IOError) as e: print(f"Warnung: Konnte Konfigurationsdatei nicht laden: {e}")
    return {}

def save_config(config_data):
    config_path = get_config_path()
    try:
        with open(config_path, "w") as f: json.dump(config_data, f, indent=4)
    except IOError as e: print(f"Warnung: Konnte Konfigurationsdatei nicht speichern: {e}")

def generate_aes_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=PBKDF2_ITERATIONS)
    return kdf.derive(password.encode())

def encrypt_file_chunked(filepath, password, message_queue):
    if not os.path.exists(filepath) or os.path.isdir(filepath): raise FileNotFoundError(f"Zu verschlüsselnde Datei nicht gefunden: {filepath}")
    out_filepath = filepath + ".enc"; salt, nonce = os.urandom(SALT_SIZE), os.urandom(NONCE_SIZE); aes_key = generate_aes_key(password, salt)
    encryptor = Cipher(algorithms.AES(aes_key), modes.GCM(nonce)).encryptor(); total_size, processed_size = os.path.getsize(filepath), 0
    try:
        with open(filepath, "rb") as f_in, open(out_filepath, "wb") as f_out:
            f_out.write(salt); f_out.write(nonce)
            while True:
                chunk = f_in.read(CHUNK_SIZE)
                if not chunk: break
                encrypted_chunk = encryptor.update(chunk); f_out.write(encrypted_chunk); processed_size += len(chunk)
                if message_queue: message_queue.put({'type': 'file_progress', 'filename': os.path.basename(filepath), 'percentage': (processed_size / total_size) * 100 if total_size > 0 else 100})
            f_out.write(encryptor.finalize()); f_out.write(encryptor.tag)
        os.remove(filepath); return out_filepath
    except Exception as e:
        if os.path.exists(out_filepath): os.remove(out_filepath)
        print(f"Fehler beim Verschlüsseln von {filepath}: {e}\n{traceback.format_exc()}"); raise

def decrypt_file_chunked(filepath, password, message_queue):
    if not os.path.exists(filepath) or os.path.isdir(filepath): raise FileNotFoundError(f"Zu entschlüsselnde Datei nicht gefunden: {filepath}")
    if not filepath.endswith(".enc"): raise ValueError("Zum Entschlüsseln .enc-Datei benötigt.")
    out_filepath = filepath[:-4]
    try:
        with open(filepath, "rb") as f_in:
            salt = f_in.read(SALT_SIZE);
            if len(salt) != SALT_SIZE: raise ValueError("Salt unvollständig/Datei zu klein.")
            nonce = f_in.read(NONCE_SIZE);
            if len(nonce) != NONCE_SIZE: raise ValueError("Nonce unvollständig/Datei zu klein.")
            file_size = os.path.getsize(filepath); encrypted_payload_size = file_size - SALT_SIZE - NONCE_SIZE - TAG_SIZE
            if encrypted_payload_size < 0: raise ValueError("Datei zu klein/beschädigt.")
            f_in.seek(SALT_SIZE + NONCE_SIZE + encrypted_payload_size); tag = f_in.read(TAG_SIZE)
            if len(tag) != TAG_SIZE: raise ValueError(f"Tag unvollständig. Erw: {TAG_SIZE}, Bek: {len(tag)}.")
            f_in.seek(SALT_SIZE + NONCE_SIZE); aes_key = generate_aes_key(password, salt)
            decryptor = Cipher(algorithms.AES(aes_key), modes.GCM(nonce, tag)).decryptor()
            processed_size, bytes_read_total = 0, 0
            with open(out_filepath, "wb") as f_out:
                while bytes_read_total < encrypted_payload_size:
                    remaining_payload_bytes = encrypted_payload_size - bytes_read_total; read_amount = min(CHUNK_SIZE, remaining_payload_bytes)
                    encrypted_chunk = f_in.read(read_amount)
                    if not encrypted_chunk: raise EOFError("Unerwartetes Dateiende.")
                    decrypted_chunk = decryptor.update(encrypted_chunk); f_out.write(decrypted_chunk); bytes_read_total += len(encrypted_chunk)
                    processed_size += len(encrypted_chunk)
                    if message_queue: message_queue.put({'type': 'file_progress', 'filename': os.path.basename(filepath), 'percentage': (processed_size / encrypted_payload_size) * 100 if encrypted_payload_size > 0 else 100})
                f_out.write(decryptor.finalize())
        os.remove(filepath); return out_filepath
    except InvalidTag:
        if os.path.exists(out_filepath): os.remove(out_filepath)
        raise ValueError("Falsches Passwort oder Datei korrupt (InvalidTag).")
    except Exception as e:
        if os.path.exists(out_filepath): os.remove(out_filepath)
        print(f"Fehler beim Entschlüsseln von {filepath}: {e}\n{traceback.format_exc()}"); raise

def encrypt_folder(folderpath, password, message_queue):
    success_count, fail_count, files_to_process_list = 0, 0, [];
    for root, dirs, files in os.walk(folderpath):
        for file in files:
            if not file.endswith(".enc"): files_to_process_list.append(os.path.join(root, file))
    total_files_to_process = len(files_to_process_list)
    message_queue.put({'type': 'total_files_in_folder', 'count': total_files_to_process})
    for i, file_path in enumerate(files_to_process_list):
        message_queue.put({'type': 'folder_progress', 'current_file_num': i + 1, 'total_files': total_files_to_process, 'filename': os.path.basename(file_path)})
        try: encrypt_file_chunked(file_path, password, message_queue); success_count += 1
        except Exception as e: fail_count += 1; print(f"DEBUG EncryptF: {file_path}, {e}\n{traceback.format_exc()}"); message_queue.put({'type': 'file_error', 'filename': file_path, 'error': str(e)})
    return success_count, fail_count

def decrypt_folder(folderpath, password, message_queue):
    success_count, fail_count, files_to_process_list = 0, 0, []
    for root, dirs, files in os.walk(folderpath):
        for file in files:
            if file.endswith(".enc"): files_to_process_list.append(os.path.join(root, file))
    total_files_to_process = len(files_to_process_list)
    message_queue.put({'type': 'total_files_in_folder', 'count': total_files_to_process})
    for i, file_path in enumerate(files_to_process_list):
        message_queue.put({'type': 'folder_progress', 'current_file_num': i + 1, 'total_files': total_files_to_process, 'filename': os.path.basename(file_path)})
        try: decrypt_file_chunked(file_path, password, message_queue); success_count += 1
        except ValueError as ve: fail_count +=1; print(f"DEBUG DecryptF: {file_path}, {ve}"); message_queue.put({'type': 'file_error', 'filename': file_path, 'error': str(ve)})
        except Exception as e: fail_count += 1; print(f"DEBUG DecryptF: {file_path}, {e}\n{traceback.format_exc()}"); message_queue.put({'type': 'file_error', 'filename': file_path, 'error': str(e)})
    return success_count, fail_count

class EncryptionApp:
    def __init__(self, root_window):
        self.root = root_window

        # --- Set Window Icon ---
        # Dies sollte früh geschehen.
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            icon_path = os.path.join(script_dir, APP_ICON_FILENAME)
            if os.path.exists(icon_path):
                # Die Methode iconbitmap erwartet eine .ico-Datei unter Windows
                # oder ein .xbm-Bitmap unter X11.
                self.root.iconbitmap(icon_path)
            else:
                # Optional: Eine Warnung ausgeben, wenn das Icon erwartet, aber nicht gefunden wird.
                print(f"Hinweis: Icon-Datei '{icon_path}' nicht gefunden. Standard-Icon wird verwendet.")
        except tk.TclError as e:
            # Dies kann passieren, wenn die Datei kein gültiges .ico/.xbm ist
            # oder wenn das Betriebssystem/Tk-Setup Probleme hat.
            print(f"Warnung: Konnte Icon '{APP_ICON_FILENAME}' nicht setzen. Tk-Fehler: {e}")
        except Exception as e: # Fängt jeden anderen unerwarteten Fehler ab
            print(f"Warnung: Unerwarteter Fehler beim Setzen des Icons '{APP_ICON_FILENAME}': {e}")
        # --- End Set Window Icon ---

        root_window.title(f"{APP_NAME} – Standard GUI")
        root_window.geometry("520x650") # Höhe ggf. anpassen, wenn Buttons mehr Platz brauchen
        root_window.resizable(False, False)
        root_window.protocol("WM_DELETE_WINDOW", self.do_not_close)

        self.outer_padding = 10
        self.inner_padding_y = 3
        self.inner_padding_x = 5 # Standard-Padding zwischen Elementen in einer Reihe
        self.button_padding_x = 3 # Kleineres Padding direkt neben Buttons

        self.config = load_config()
        last_action = self.config.get("last_action", "encrypt")
        initial_action = "decrypt" if last_action == "encrypt" else "encrypt"
        self.operation = tk.StringVar(value=initial_action)

        script_dir = os.path.dirname(os.path.abspath(__file__)) # Bereits definiert, kann hier wiederverwendet werden
        encrypted_path_in_dir = os.path.join(script_dir, DEFAULT_DB_FILENAME + ".enc")
        decrypted_path_in_dir = os.path.join(script_dir, DEFAULT_DB_FILENAME)
        initial_path = ""
        if os.path.exists(encrypted_path_in_dir) and os.path.isfile(encrypted_path_in_dir):
            initial_path = encrypted_path_in_dir
        elif os.path.exists(decrypted_path_in_dir) and os.path.isfile(decrypted_path_in_dir):
             initial_path = decrypted_path_in_dir
        if not initial_path:
            saved_path_from_config = self.config.get("last_path", "")
            if saved_path_from_config and (os.path.exists(saved_path_from_config) and (os.path.isfile(saved_path_from_config) or os.path.isdir(saved_path_from_config))):
                 initial_path = saved_path_from_config
            else: initial_path = ""

        self.path_var = tk.StringVar(value=initial_path)
        self.password_var = tk.StringVar()
        self.confirm_password_var = tk.StringVar()

        # BooleanVars für Passwortsichtbarkeit
        self.password1_visible = tk.BooleanVar(value=False)
        self.password2_visible = tk.BooleanVar(value=False)

        self.message_queue = queue.Queue()
        self.worker_thread = None
        self._after_id_queue_check = None
        self._clipboard_clear_timer_id = None

        self.create_widgets()
        self.root.after(60, self.adjust_layouts) # Etwas mehr Zeit für winfo_width

        self.update_password_strength_indicator()
        self.update_path_status_indicator()

        self.password_var.trace_add("write", lambda *args: self.update_password_strength_indicator())
        self.path_var.trace_add("write", lambda *args: self.update_path_status_indicator())

    def do_not_close(self):
        messagebox.showinfo("Schließen deaktiviert", "Das Schließen des Fensters über das X ist deaktiviert...", parent=self.root)

    def create_widgets(self):
        main_content_frame = ttk.Frame(self.root, padding=self.outer_padding)
        main_content_frame.pack(expand=True, fill=tk.BOTH)

        try:
            temp_label = ttk.Label(main_content_frame)
            default_font_obj = tkfont.nametofont(temp_label.cget("font"))
            self.status_label_font = tkfont.Font(family=default_font_obj.cget("family"),
                                                 size=default_font_obj.cget("size"),
                                                 weight="bold")
            temp_label.destroy()
        except tk.TclError:
            self.status_label_font = ("TkDefaultFont", 9, "bold")

        self.style_engine = ttk.Style()
        for level_name, props in PW_STRENGTH_LEVELS.items():
            style_name = f"{level_name.capitalize()}.Horizontal.TProgressbar"
            self.style_engine.configure(style_name, background=props["bar_color"], troughcolor='SystemButtonFace')

        path_label = ttk.Label(main_content_frame, text="Dateipfad oder Ordner:")
        path_label.pack(anchor=tk.W, pady=(0, self.inner_padding_y))
        self.path_entry = ttk.Entry(main_content_frame, textvariable=self.path_var, width=70)
        self.path_entry.pack(fill=tk.X)
        self.path_status_label = ttk.Label(main_content_frame, text="Dateistatus: Unbekannt", anchor=tk.W, font=self.status_label_font)
        self.path_status_label.pack(fill=tk.X, pady=(2, self.inner_padding_y))
        path_button_frame = ttk.Frame(main_content_frame)
        path_button_frame.pack(pady=self.inner_padding_y, fill=tk.X)
        ttk.Button(path_button_frame, text="Datei auswählen...", command=self.select_file).pack(side=tk.LEFT, padx=(0, self.button_padding_x), expand=True, fill=tk.X)
        ttk.Button(path_button_frame, text="Ordner auswählen...", command=self.select_folder).pack(side=tk.LEFT, expand=True, fill=tk.X)

        pw_label = ttk.Label(main_content_frame, text="Passwort:")
        pw_label.pack(anchor=tk.W, pady=(self.outer_padding, self.inner_padding_y))
        
        # --- Erstes Passwortfeld mit "Zeigen"-Button ---
        self.password_widgets_frame = ttk.Frame(main_content_frame)
        self.password_widgets_frame.pack(fill=tk.X)
        self.password_entry = ttk.Entry(self.password_widgets_frame, textvariable=self.password_var, show="*", width=30) # width ist relativ
        self.password_entry.pack(side=tk.LEFT, expand=True, fill=tk.X)
        
        self.toggle_show_pw1_button = ttk.Button(self.password_widgets_frame, text="Zeigen", width=8,
                                                 command=lambda: self.toggle_password_visibility(
                                                     self.password_entry, self.password1_visible, self.toggle_show_pw1_button))
        self.toggle_show_pw1_button.pack(side=tk.LEFT, padx=(self.inner_padding_x, self.button_padding_x), ipady=2)
        
        self.copy_pw_button = ttk.Button(self.password_widgets_frame, text="📋 Kopieren", width=13, # Breite angepasst
                                         command=self.copy_password_to_clipboard) 
        self.copy_pw_button.pack(side=tk.LEFT, padx=(0, self.button_padding_x), ipady=2) # Weniger Gesamtbreite für Buttons
        
        self.paste_pw_button = ttk.Button(self.password_widgets_frame, text="📥 Einfügen", width=11, # Breite angepasst
                                          command=self.paste_password_from_clipboard)
        self.paste_pw_button.pack(side=tk.LEFT, ipady=2)


        # --- Zweites Passwortfeld mit "Zeigen"-Button ---
        confirm_pw_label = ttk.Label(main_content_frame, text="Passwort bestätigen:")
        confirm_pw_label.pack(anchor=tk.W, pady=(self.inner_padding_y + 2, self.inner_padding_y))
        self.confirm_password_widgets_frame = ttk.Frame(main_content_frame)
        self.confirm_password_widgets_frame.pack(fill=tk.X)
        self.confirm_password_entry = ttk.Entry(self.confirm_password_widgets_frame, textvariable=self.confirm_password_var, show="*")
        self.confirm_password_entry.pack(side=tk.LEFT, expand=True, fill=tk.X)

        self.toggle_show_pw2_button = ttk.Button(self.confirm_password_widgets_frame, text="Zeigen", width=8,
                                                 command=lambda: self.toggle_password_visibility(
                                                     self.confirm_password_entry, self.password2_visible, self.toggle_show_pw2_button))
        self.toggle_show_pw2_button.pack(side=tk.LEFT, padx=(self.inner_padding_x, 0), ipady=2) # Kein rechtes Padding, da Placeholder kommt

        # Placeholder für die Breite der Kopieren/Einfügen Buttons
        self.confirm_pw_button_placeholder = ttk.Frame(self.confirm_password_widgets_frame)
        self.confirm_pw_button_placeholder.pack(side=tk.LEFT)


        self.password_strength_label = ttk.Label(main_content_frame, text="Passwortstärke:", anchor=tk.W, font=self.status_label_font)
        self.password_strength_label.pack(fill=tk.X, pady=(self.inner_padding_y + 2, 0))
        
        self.password_strength_bar_frame = ttk.Frame(main_content_frame)
        self.password_strength_bar_frame.pack(fill=tk.X, pady=(1, self.inner_padding_y + 2))
        self.password_strength_bar = ttk.Progressbar(self.password_strength_bar_frame, orient='horizontal', length=100, mode='determinate', maximum=100)
        self.password_strength_bar.pack(side=tk.LEFT, expand=True, fill=tk.X)
        # Placeholder für die Breite aller drei Buttons (Zeigen, Kopieren, Einfügen)
        self.pw_strength_bar_button_placeholder = ttk.Frame(self.password_strength_bar_frame)
        self.pw_strength_bar_button_placeholder.pack(side=tk.LEFT)

        action_label = ttk.Label(main_content_frame, text="Aktion wählen:")
        action_label.pack(anchor=tk.W, pady=(self.outer_padding, self.inner_padding_y))
        action_radio_frame = ttk.Frame(main_content_frame)
        action_radio_frame.pack(fill=tk.X)
        ttk.Radiobutton(action_radio_frame, text="Verschlüsseln", variable=self.operation, value="encrypt").pack(side=tk.LEFT, padx=(0, 20))
        ttk.Radiobutton(action_radio_frame, text="Entschlüsseln", variable=self.operation, value="decrypt").pack(side=tk.LEFT)
        
        self.style_engine.configure('Run.TButton', font=('Helvetica', 10, 'bold'), padding=6)
        self.run_button = ttk.Button(main_content_frame, text="Ausführen", command=self.start_operation, style='Run.TButton', width=20)
        self.run_button.pack(pady=(self.outer_padding + 5, self.outer_padding))

        progress_frame = ttk.Frame(main_content_frame)
        progress_frame.pack(fill=tk.X, pady=(0, self.inner_padding_y))
        ttk.Label(progress_frame, text="Datei-Fortschritt:").pack(anchor=tk.W)
        self.file_progressbar = ttk.Progressbar(progress_frame, orient='horizontal', length=100, mode='determinate')
        self.file_progressbar.pack(fill=tk.X, pady=(0, self.inner_padding_y))
        ttk.Label(progress_frame, text="Ordner-Fortschritt:").pack(anchor=tk.W)
        self.folder_progressbar = ttk.Progressbar(progress_frame, orient='horizontal', length=100, mode='determinate')
        self.folder_progressbar.pack(fill=tk.X)

        status_bottom_frame = ttk.Frame(self.root, padding=(self.outer_padding, self.inner_padding_y, self.outer_padding, self.outer_padding))
        status_bottom_frame.pack(side=tk.BOTTOM, fill=tk.X)
        self.current_file_label = ttk.Label(status_bottom_frame, text="", anchor=tk.W, wraplength=480)
        self.current_file_label.pack(fill=tk.X)
        self.status_label = ttk.Label(status_bottom_frame, text="Bereit.", relief=tk.SUNKEN, anchor=tk.W, padding=3)
        self.status_label.pack(fill=tk.X, pady=(self.inner_padding_y, 0))

    def toggle_password_visibility(self, entry_widget, visibility_var, button_widget):
        visibility_var.set(not visibility_var.get())
        if visibility_var.get():
            entry_widget.config(show="")
            button_widget.config(text="Verbergen")
        else:
            entry_widget.config(show="*")
            button_widget.config(text="Zeigen")

    def adjust_layouts(self):
        self.root.update_idletasks() # Wichtig, damit winfo_width korrekte Werte liefert
        
        show1_btn_width = self.toggle_show_pw1_button.winfo_width()
        copy_btn_width = self.copy_pw_button.winfo_width()
        paste_btn_width = self.paste_pw_button.winfo_width()
        
        effective_button_group_width_pw1 = (show1_btn_width + self.inner_padding_x + self.button_padding_x +
                                           copy_btn_width + self.button_padding_x +
                                           paste_btn_width)

        show2_btn_width = self.toggle_show_pw2_button.winfo_width()
        confirm_placeholder_needed_width = effective_button_group_width_pw1 - show2_btn_width - self.inner_padding_x
        self.confirm_pw_button_placeholder.config(width=max(0, confirm_placeholder_needed_width))

        self.pw_strength_bar_button_placeholder.config(width=max(0, effective_button_group_width_pw1))


    def check_password_strength(self, password):
        length = len(password)
        score = 0; details = []
        if length == 0:
            level_name = "empty"; props = PW_STRENGTH_LEVELS[level_name]
            return props["text"], level_name, props["color"], props["value"], "", props["bar_color"]
        if length >= 12: score += 2; details.append("Länge (>11)")
        elif length >= 8: score += 1; details.append("Länge (8-11)")
        else: details.append("Zu kurz (<8)")
        if re.search(r"[a-z]", password): score += 1; details.append("Kleinb.")
        if re.search(r"[A-Z]", password): score += 1; details.append("Großb.")
        if re.search(r"[0-9]", password): score += 1; details.append("Ziffern")
        if re.search(r"[^a-zA-Z0-9]", password): score += 1; details.append("Sonderz.")
        if score <= 2: level_name = "kritisch"
        elif score <= 3: level_name = "verbesserungswürdig"
        elif score <= 4: level_name = "mittel"
        elif score <= 5: level_name = "okay"
        else: level_name = "stark"
        props = PW_STRENGTH_LEVELS[level_name]
        detail_str = f" ({', '.join(details)})" if details else ""
        return f"{props['text']}{detail_str}", level_name, props["color"], props["value"], props['text'], props["bar_color"]

    def update_password_strength_indicator(self):
        password = self.password_var.get()
        display_text, level_name, label_text_color, progress_value, _, _ = self.check_password_strength(password)
        self.password_strength_label.config(text=f"Passwortstärke: {display_text}", foreground=label_text_color)
        style_to_apply = f"{level_name.capitalize()}.Horizontal.TProgressbar"
        self.password_strength_bar.config(style=style_to_apply)
        self.password_strength_bar['value'] = progress_value

    def get_path_status(self, path):
        if not path: return "Kein Pfad ausgewählt", FILE_STATUS_COLORS["unbekannt"]
        if not os.path.exists(path): return "Pfad ungültig", FILE_STATUS_COLORS["ungültig"]
        if os.path.isfile(path):
            return ("Verschlüsselt", FILE_STATUS_COLORS["verschlüsselt"]) if path.endswith(".enc") else ("Offen", FILE_STATUS_COLORS["offen"])
        elif os.path.isdir(path):
            try:
                has_enc, has_non_enc, is_empty = False, False, True
                files_in_dir = [f for f in os.listdir(path) if os.path.isfile(os.path.join(path, f))]
                if not files_in_dir: return "Ordner (Leer)", FILE_STATUS_COLORS["unbekannt"]
                for item_name in files_in_dir[:20]:
                    is_empty = False;
                    if item_name.endswith(".enc"): has_enc = True
                    else: has_non_enc = True
                    if has_enc and has_non_enc: break
                if is_empty: return "Ordner (Leer o. nur Unterordner)", FILE_STATUS_COLORS["unbekannt"]
                if has_enc and not has_non_enc: return "Ihr Ordner wirkt derzeit verschlüsselt", FILE_STATUS_COLORS["verschlüsselt"]
                if not has_enc and has_non_enc: return " Ihr Ordner wirkt derzeit offen", FILE_STATUS_COLORS["offen"]
                if has_enc and has_non_enc: return "Ordner (Gemischter Inhalt)", FILE_STATUS_COLORS["gemischt"]
            except OSError: return "Ordner (Zugriffsproblem)", FILE_STATUS_COLORS["unbekannt"]
        return "Unbekannt", FILE_STATUS_COLORS["unbekannt"]

    def update_path_status_indicator(self):
        path = self.path_var.get()
        status_text, color = self.get_path_status(path)
        self.path_status_label.config(text=f"Dateistatus: {status_text}", foreground=color)

    def copy_password_to_clipboard(self):
        password = self.password_var.get();
        if not password: messagebox.showwarning("Leeres Passwort", "Kein Passwort zum Kopieren.", parent=self.root); return
        try:
            pyperclip.copy(password); self.status_label.config(text="Passwort für 60s in Zwischenablage kopiert.")
            if self._clipboard_clear_timer_id: self.root.after_cancel(self._clipboard_clear_timer_id)
            self._clipboard_clear_timer_id = self.root.after(60 * 1000, self.clear_clipboard_if_password_matches, password)
        except pyperclip.PyperclipException as e: messagebox.showerror("Fehler Zwi.-Ablage", f"Zugriff fehlgeschlagen:\n{e}", parent=self.root); self.status_label.config(text="Fehler beim Kopieren in Zwi.-Ablage.")

    def clear_clipboard_if_password_matches(self, original_password_copied):
        try:
            if pyperclip.paste() == original_password_copied: pyperclip.copy(''); self.status_label.config(text="Zwi.-Ablage (Passwort) nach 60s geleert."); print("Zwischenablage nach 60s geleert.")
            else: self.status_label.config(text="Bereit. (Zwi.-Ablage zwischenzeitlich geändert)"); print("Zwi.-Ablage geändert, nicht geleert.")
        except pyperclip.PyperclipException: print("Fehler beim Zwi.-Ablage-Zugriff (Timeout-Clear)."); self.status_label.config(text="Bereit.")
        finally: self._clipboard_clear_timer_id = None

    def paste_password_from_clipboard(self):
        try:
            clipboard_content = pyperclip.paste()
            if clipboard_content:
                self.password_var.set(clipboard_content)
                self.status_label.config(text="Passwort aus Zwi.-Ablage in erstes Feld eingefügt.")
            else: self.status_label.config(text="Zwi.-Ablage ist leer.")
        except pyperclip.PyperclipException as e:
            messagebox.showerror("Fehler Zwi.-Ablage", f"Zugriff fehlgeschlagen:\n{e}", parent=self.root)
            self.status_label.config(text="Fehler beim Einfügen aus Zwi.-Ablage.")

    def select_file(self):
        current_path = self.path_var.get(); initial_dir = os.path.dirname(current_path) if current_path and os.path.isdir(os.path.dirname(current_path)) else os.path.expanduser("~")
        path = filedialog.askopenfilename(title="Datei auswählen", initialdir=initial_dir)
        if path: self.path_var.set(path); self.current_file_label.config(text=""); self.file_progressbar['value'] = 0; self.folder_progressbar['value'] = 0

    def select_folder(self):
        current_path = self.path_var.get(); initial_dir = current_path if current_path and os.path.isdir(current_path) else os.path.expanduser("~")
        path = filedialog.askdirectory(title="Ordner auswählen", initialdir=initial_dir)
        if path: self.path_var.set(path); self.current_file_label.config(text=""); self.file_progressbar['value'] = 0; self.folder_progressbar['value'] = 0

    def start_operation(self):
        filepath, password, confirm_password, action = self.path_var.get(), self.password_var.get(), self.confirm_password_var.get(), self.operation.get()
        if not filepath: messagebox.showwarning("Eingabe fehlt", "Pfad auswählen.", parent=self.root); return
        if not os.path.exists(filepath): messagebox.showerror("Fehler", f"Pfad existiert nicht:\n{filepath}", parent=self.root); return
        if not password: messagebox.showwarning("Eingabe fehlt", "Passwort eingeben.", parent=self.root); return
        if password != confirm_password:
            messagebox.showwarning("Passwortfehler", "Die eingegebenen Passwörter stimmen nicht überein.", parent=self.root)
            self.confirm_password_var.set(""); return
        if action == "encrypt":
            _, _, _, _, level_text_plain, _ = self.check_password_strength(password)
            if level_text_plain.lower() == "kritisch" or level_text_plain.lower() == "verbesserungswürdig":
                if not messagebox.askyesno("Schwaches Passwort", f"Das Passwort ist als '{level_text_plain}' eingestuft.\nMöchten Sie wirklich fortfahren?", icon='warning', parent=self.root): return
        self.config["last_path"] = filepath; self.config["last_action"] = action; save_config(self.config)
        self.run_button.config(state=tk.DISABLED); self.status_label.config(text=f"Starte {action} von {os.path.basename(filepath)}...")
        self.file_progressbar['value'] = 0; self.folder_progressbar['value'] = 0; self.folder_progressbar['maximum'] = 100
        def worker_task(path_to_work_on, pw, act, msg_queue):
            try:
                op_type = "Verschlüssele" if act == "encrypt" else "Entschlüssele"; msg_queue.put({'type': 'status', 'message': f"{op_type} {os.path.basename(path_to_work_on)}..."})
                if os.path.isdir(path_to_work_on):
                    func = encrypt_folder if act == "encrypt" else decrypt_folder; op_name = "verschlüsselt" if act == "encrypt" else "entschlüsselt"
                    success, fail = func(path_to_work_on, pw, msg_queue); msg_queue.put({'type': 'done', 'success': True, 'message': f"Ordner {op_name}. Erfolgreich: {success}, Fehler: {fail}."})
                else:
                    func = encrypt_file_chunked if act == "encrypt" else decrypt_file_chunked; op_name = "verschlüsselt" if act == "encrypt" else "entschlüsselt"
                    if act == "decrypt" and not path_to_work_on.endswith(".enc"): msg_queue.put({'type': 'done', 'success': False, 'message': "Zum Entschlüsseln .enc-Datei benötigt."}); return
                    out_file = func(path_to_work_on, pw, msg_queue); msg_queue.put({'type': 'done', 'success': True, 'message': f"Datei {op_name}:\n{out_file}", 'filepath': out_file})
            except (ValueError, FileNotFoundError) as specific_e: msg_queue.put({'type': 'done', 'success': False, 'message': f"Fehler: {specific_e}"})
            except Exception as e: print(f"DEBUG Worker: {e}\n{traceback.format_exc()}"); msg_queue.put({'type': 'done', 'success': False, 'message': f"Unerwarteter Fehler:\n{str(e)}"})
            finally: msg_queue.put({'type': 'thread_finished'})
        self.worker_thread = threading.Thread(target=worker_task, args=(filepath, password, action, self.message_queue))
        self.worker_thread.start(); self.process_queue()

    def process_queue(self):
        try:
            while not self.message_queue.empty():
                message = self.message_queue.get_nowait(); msg_type = message['type']
                if msg_type == 'status':
                    self.status_label.config(text=message['message']); self.current_file_label.config(text=""); self.file_progressbar['value'] = 0
                elif msg_type == 'file_progress':
                    self.current_file_label.config(text=f"Bearbeite: {message['filename']}"); self.file_progressbar['value'] = message['percentage']
                elif msg_type == 'total_files_in_folder':
                    self.folder_progressbar['maximum'] = message['count'] if message['count'] > 0 else 100; self.folder_progressbar['value'] = 0
                elif msg_type == 'folder_progress':
                    self.current_file_label.config(text=f"Ordner: {message['current_file_num']}/{message['total_files']} ({message['filename']})")
                    self.folder_progressbar['value'] = message['current_file_num']; self.file_progressbar['value'] = 0
                elif msg_type == 'file_error': print(f"GUI Hinweis: Fehler bei {message['filename']} - {message['error']}")
                elif msg_type == 'done':
                    self.run_button.config(state=tk.NORMAL)
                    if self.file_progressbar['maximum'] > 0: self.file_progressbar['value'] = self.file_progressbar['maximum']
                    if self.folder_progressbar['maximum'] > 0: self.folder_progressbar['value'] = self.folder_progressbar['maximum']
                    self.current_file_label.config(text=""); self.status_label.config(text="Bereit.")
                    self.update_path_status_indicator()
                    if message['success']: messagebox.showinfo("Erfolg", message['message'], parent=self.root)
                    else: messagebox.showerror("Fehler", message['message'], parent=self.root)
                    print("Operation beendet. App wird geschlossen."); self.root.destroy(); return
                elif msg_type == 'thread_finished': pass
        except queue.Empty: pass
        except Exception as e:
            print(f"Fehler in GUI-Queue Verarbeitung: {e}\n{traceback.format_exc()}"); self.status_label.config(text=f"GUI Fehler: {e}"); self.run_button.config(state=tk.NORMAL)
        if self.worker_thread and self.worker_thread.is_alive(): self._after_id_queue_check = self.root.after(100, self.process_queue)
        else:
            if not self.message_queue.empty(): self._after_id_queue_check = self.root.after(10, self.process_queue)
            else:
                self.run_button.config(state=tk.NORMAL)
                if self._after_id_queue_check: self.root.after_cancel(self._after_id_queue_check)

if __name__ == "__main__":
    root = tk.Tk()
    app = EncryptionApp(root)
    root.mainloop()