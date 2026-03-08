# --- START OF FILE Dashboard.py (ANGEPASST) ---

import os
import sys
import tempfile
import logging
import subprocess
import traceback
import textwrap
from datetime import datetime
import sqlite3
import locale

# --- GUI BIBLIOTHEKEN ---
try:
    import pandas as pd
    from fpdf import FPDF
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    import ttkbootstrap as ttk
    from ttkbootstrap.constants import *
    from ttkbootstrap.widgets import DateEntry
    from ttkbootstrap.scrolled import ScrolledFrame
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    import matplotlib.pyplot as plt
except ImportError as e:
    root = tk.Tk(); root.withdraw()
    messagebox.showerror("Kritischer Fehler: Fehlende Bibliothek", f"Eine benötigte Bibliothek fehlt:\n\n{e}\n\nBitte installieren Sie alle Abhängigkeiten (z.B. mit 'pip install ttkbootstrap pandas fpdf matplotlib').")
    sys.exit(1)

# Setze die lokale Umgebung auf Deutsch für Währungs- und Zahlenformate
try:
    locale.setlocale(locale.LC_ALL, 'de_DE.UTF-8')
except locale.Error:
    try: locale.setlocale(locale.LC_ALL, 'German_Germany.1252')
    except locale.Error: logging.warning("Deutsche Locale konnte nicht gesetzt werden. Zahlenformatierung könnte abweichen.")

# --- LOGGING KONFIGURATION ---
log_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dashboard.log')
logging.basicConfig(filename=log_file_path, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


# --- Erweiterte FPDF-Klasse für UTF-8-Unterstützung (bleibt bestehen) ---
class PDF(FPDF):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Versucht, eine Unicode-fähige Schriftart zu laden.
        # Wenn dies fehlschlägt, wird font_family auf einen Core-Font gesetzt
        # und die PDF-Erstellungsfunktion muss das Encoding manuell handhaben.
        self.font_family = 'Arial' # Standard-Fallback
        try:
            font_path = os.path.dirname(os.path.abspath(__file__))
            dejavu_sans_path = os.path.join(font_path, "DejaVuSans.ttf")
            dejavu_sans_bold_path = os.path.join(font_path, "DejaVuSans-Bold.ttf")

            if os.path.exists(dejavu_sans_path) and os.path.exists(dejavu_sans_bold_path):
                 self.add_font('DejaVu', '', dejavu_sans_path, uni=True)
                 self.add_font('DejaVu', 'B', dejavu_sans_bold_path, uni=True)
                 self.font_family = 'DejaVu' # Setze auf die bessere Schriftart, wenn verfügbar
                 logging.info("DejaVu-Schriftarten für PDF erfolgreich geladen.")
            else:
                 logging.warning("DejaVu-Schriftarten nicht gefunden. PDF-Encoding wird manuell als Fallback durchgeführt.")
        except Exception as e:
            logging.error(f"Fehler beim Hinzufügen der Unicode-Schriftart für PDF: {e}")
            
# --- DATENSCHLOSS UND DATEN-HILFSFUNKTIONEN (unverändert) ---
def _find_daten_schloss_tool():
    script_dir=os.path.dirname(os.path.abspath(__file__));tool_name_base="DatenSchloss";tool_exe_path=os.path.join(script_dir,f"{tool_name_base}.exe");tool_pyw_path=os.path.join(script_dir,f"{tool_name_base}.pyw")
    if os.path.exists(tool_exe_path):return[tool_exe_path]
    if os.path.exists(tool_pyw_path):
        interpreter=sys.executable
        if sys.platform=="win32" and "pythonw.exe" not in interpreter.lower():
            pythonw_path=os.path.join(os.path.dirname(interpreter),"pythonw.exe")
            if os.path.exists(pythonw_path):interpreter=pythonw_path
        return[interpreter,tool_pyw_path]
    return None
def _run_daten_schloss():
    logging.info("Rufe DatenSchloss-Tool auf...");tool_command=_find_daten_schloss_tool()
    if not tool_command:messagebox.showerror("Fehler","Die benötigte Sicherheitskomponente 'DatenSchloss' wurde im Anwendungsverzeichnis nicht gefunden.");return False
    try:
        creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        subprocess.run(tool_command,check=True,cwd=os.path.dirname(os.path.abspath(__file__)),creationflags=creation_flags)
        logging.info("DatenSchloss-Tool erfolgreich beendet.")
        return True
    except Exception as e:
        logging.error(f"Fehler bei der Ausführung des DatenSchloss-Tools: {e}")
        messagebox.showerror("Fehler",f"Ein Fehler ist bei der Ausführung der Sicherheitskomponente aufgetreten: {e}")
        return False
def create_connection(db_file):
    conn=None
    try:conn=sqlite3.connect(db_file)
    except sqlite3.Error as e:logging.error(f"Fehler beim Verbinden mit der Datenbank: {e}");messagebox.showerror("Datenbankfehler",f"Fehler beim Verbinden mit der Datenbank: {e}")
    return conn
def load_data(conn):
    try:
        df_rechnungen=pd.read_sql_query("SELECT * FROM rechnungen",conn);df_kunden=pd.read_sql_query("SELECT id, name, vorname, titel_firma, zifferncode FROM kunden",conn)
        if df_rechnungen.empty:return pd.DataFrame()
        df_merged=pd.merge(df_rechnungen,df_kunden,left_on='kunde_id',right_on='id',how='left',suffixes=('', '_kunde'));df_merged.rename(columns={'id':'kunden_id'},inplace=True)
        df_merged['rechnungsdatum']=pd.to_datetime(df_merged['rechnungsdatum'],format='%d.%m.%Y',errors='coerce');df_merged['faelligkeitsdatum']=pd.to_datetime(df_merged['faelligkeitsdatum'],format='%d.%m.%Y',errors='coerce');return df_merged
    except Exception as e:logging.error(f"Fehler beim Laden der Daten: {e}");messagebox.showerror("Datenfehler",f"Fehler beim Laden oder Verarbeiten der Daten: {e}");return pd.DataFrame()
def get_customer_display_name(row):
    titel,vorname,name=row.get('titel_firma'),row.get('vorname'),row.get('name')
    if pd.isna(vorname) and pd.isna(name) and pd.notna(titel):return titel
    return ' '.join(str(p) for p in[titel,vorname,name] if p and pd.notna(p))

# --- ÜBERARBEITET: PDF-Erstellungsfunktion mit robustem Encoding ---
def create_financial_report_pdf(df_data_for_report, user_start_date, user_end_date, anonymize, save_to_path):
    total_netto = df_data_for_report['summe_netto'].sum()
    total_mwst = df_data_for_report['summe_mwst'].sum()
    total_brutto = df_data_for_report['summe_brutto'].sum()
    anzahl_rechnungen = len(df_data_for_report)
    
    # PDF-Klasse initialisieren
    pdf = PDF()
    
    # Prüfen, welche Schriftart verwendet wird (DejaVu oder Fallback)
    font_name = pdf.font_family
    use_manual_encoding = (font_name.lower() != 'dejavu')

    if use_manual_encoding:
        logging.warning("DejaVu-Schriftart nicht gefunden. Manuelles Encoding wird für PDF verwendet. Sonderzeichen könnten ersetzt werden.")

    # Hilfsfunktion, die Text sicher kodiert, falls nötig
    def encode_text(text_str):
        if use_manual_encoding:
            # Kodiert den Text für Core-Fonts (wie Arial), ersetzt unbekannte Zeichen sicher
            return text_str.encode('latin-1', 'replace').decode('latin-1')
        else:
            # Wenn DejaVu verwendet wird, ist keine manuelle Kodierung nötig
            return text_str

    pdf.add_page()
    pdf.set_font(font_name, 'B', 16)
    pdf.cell(0, 10, encode_text('Finanzbericht'), 0, 1, 'C')
    pdf.set_font(font_name, '', 12)
    pdf.cell(0, 10, f"Zeitraum: {user_start_date.strftime('%d.%m.%Y')} - {user_end_date.strftime('%d.%m.%Y')}", 0, 1, 'C')
    pdf.ln(10)
    
    pdf.set_font(font_name, 'B', 12)
    pdf.cell(0, 10, encode_text('Zusammenfassung:'), 0, 1)
    pdf.set_font(font_name, '', 11)
    pdf.cell(0, 7, encode_text(f"Anzahl der Rechnungen: {anzahl_rechnungen}"), 0, 1)
    pdf.cell(0, 7, encode_text(f"Gesamtumsatz (Netto): {total_netto:,.2f} EUR"), 0, 1)
    pdf.cell(0, 7, encode_text(f"Gesamte Mehrwertsteuer: {total_mwst:,.2f} EUR"), 0, 1)
    pdf.cell(0, 7, encode_text(f"Gesamtumsatz (Brutto): {total_brutto:,.2f} EUR"), 0, 1)
    pdf.ln(10)
    
    # Tabellen-Header kodieren
    pdf.set_font(font_name, 'B', 9)
    pdf.cell(25, 8, encode_text('Re.-Datum'), 1)
    pdf.cell(35, 8, encode_text('Re.-Nummer'), 1)
    pdf.cell(50, 8, encode_text('Kunde'), 1)
    pdf.cell(25, 8, encode_text('Netto'), 1, 0, 'R')
    pdf.cell(25, 8, encode_text('MwSt.'), 1, 0, 'R')
    pdf.cell(30, 8, encode_text('Brutto'), 1, 0, 'R')
    pdf.ln()
    
    # Tabellen-Inhalt kodieren
    pdf.set_font(font_name, '', 9)
    for _, row in df_data_for_report.iterrows():
        kunde_name = f"Kunde-{row.get('zifferncode') or row.get('kunden_id', 'N/A')}" if anonymize else row['kunde_anzeige']
        datum_str = row['rechnungsdatum'].strftime('%d.%m.%Y') if pd.notna(row['rechnungsdatum']) else 'N/A'
        
        pdf.cell(25, 7, encode_text(datum_str), 1)
        pdf.cell(35, 7, encode_text(str(row['rechnungsnummer'])), 1)
        pdf.cell(50, 7, encode_text(kunde_name), 1)
        # Zahlenwerte müssen nicht kodiert werden
        pdf.cell(25, 7, f"{row['summe_netto']:,.2f}", 1, 0, 'R')
        pdf.cell(25, 7, f"{row['summe_mwst']:,.2f}", 1, 0, 'R')
        pdf.cell(30, 7, f"{row['summe_brutto']:,.2f}", 1, 0, 'R')
        pdf.ln()
        
    pdf.set_font(font_name, 'B', 9)
    pdf.cell(110, 8, encode_text('Gesamtsumme:'), 1, 0, 'R')
    pdf.cell(25, 8, f"{total_netto:,.2f}", 1, 0, 'R')
    pdf.cell(25, 8, f"{total_mwst:,.2f}", 1, 0, 'R')
    pdf.cell(30, 8, f"{total_brutto:,.2f}", 1, 1, 'R')
    
    pdf.output(save_to_path)

# --- HAUPTANWENDUNG (TKINTER) - (unverändert) ---
class DashboardApp(ttk.Window):
    def __init__(self, config=None):
        super().__init__(themename="litera", title="Rechnungs-Dashboard")
        self.config = config if config else {}
        self.geometry("1600x950")
        self.protocol("WM_DELETE_WINDOW", self._on_closing)
        self.df_all_data = pd.DataFrame()
        self.df_filtered = pd.DataFrame()
        self._create_widgets()
        self._initialize_ui_state()
        self._auto_load_database_from_config()
        logging.info("Dashboard-GUI erfolgreich initialisiert.")

    def _auto_load_database_from_config(self):
        db_path = self.config.get('db_path')
        if db_path and os.path.exists(db_path):
            logging.info(f"Lade Datenbank automatisch aus config.txt: {db_path}")
            self._load_database(filepath=db_path)
        else:
            logging.warning("Kein gültiger db_path in config.txt gefunden oder Datei existiert nicht. Warte auf manuelle Eingabe.")

    def _on_closing(self):
        if messagebox.askokcancel("Anwendung beenden", "Möchten Sie die Anwendung wirklich beenden?\n\nDies stellt sicher, dass Ihre Datenbank korrekt verschlüsselt wird."):
            self.withdraw(); _run_daten_schloss(); logging.info("DatenSchloss-Shutdown abgeschlossen."); self.destroy(); sys.exit(0)

    def _create_widgets(self):
        self.sidebar=ttk.Frame(self,padding=15,width=300);self.sidebar.pack(side=LEFT,fill=Y);self.sidebar.pack_propagate(False)
        main_separator=ttk.Separator(self,orient=VERTICAL);main_separator.pack(side=LEFT,fill=Y,padx=5)
        self.main_frame = ScrolledFrame(self, padding=15, autohide=True)
        self.main_frame.pack(side=RIGHT,fill=BOTH,expand=True)
        self._create_sidebar_widgets(self.sidebar)
        self._create_main_content_widgets(self.main_frame)
    
    def _create_sidebar_widgets(self, parent):
        ttk.Label(parent,text="1. Datenbank laden",font=("-size 12 -weight bold")).pack(fill=X,pady=(0,5))
        self.db_load_button=ttk.Button(parent,text="'unternehmen.db' auswählen",command=self._load_database,bootstyle=SUCCESS);self.db_load_button.pack(fill=X,pady=5)
        self.db_status_label=ttk.Label(parent,text="Bitte Datenbank laden.",bootstyle=INFO,wraplength=280);self.db_status_label.pack(fill=X,pady=5);ttk.Separator(parent).pack(fill=X,pady=15)
        ttk.Label(parent,text="2. Filteroptionen",font=("-size 12 -weight bold")).pack(fill=X,pady=(0,5))
        status_frame=ttk.LabelFrame(parent,text="Rechnungsstatus",padding=10);status_frame.pack(fill=X,pady=5);self.status_vars={}
        ALL_STATUSES=['Offen','Bezahlt','Entwurf','Gutschrift','Storniert','Steht zur Erinnerung an','Steht zur Mahnung an','Steht zur Mahnung 2 an','Bitte an Inkasso weiterleiten']
        for status in ALL_STATUSES:
            var=tk.BooleanVar(value=True);var.trace_add("write",self._apply_filters);cb=ttk.Checkbutton(status_frame,text=status,variable=var,bootstyle="round-toggle");cb.pack(anchor=W,pady=2);self.status_vars[status]=var
        customer_frame=ttk.LabelFrame(parent,text="Kunde",padding=10);customer_frame.pack(fill=BOTH,expand=True,pady=5);btn_frame=ttk.Frame(customer_frame);btn_frame.pack(fill=X)
        ttk.Button(btn_frame,text="Alle",command=self._select_all_customers,bootstyle=SECONDARY).pack(side=LEFT,expand=True,fill=X,padx=2)
        ttk.Button(btn_frame,text="Keine",command=self._deselect_all_customers,bootstyle=SECONDARY).pack(side=LEFT,expand=True,fill=X,padx=2)
        listbox_frame=ttk.Frame(customer_frame);listbox_frame.pack(fill=BOTH,expand=True,pady=5);self.customer_listbox=tk.Listbox(listbox_frame,selectmode=EXTENDED,exportselection=False);self.customer_listbox.pack(side=LEFT,fill=BOTH,expand=True);self.customer_listbox.bind("<<ListboxSelect>>",self._apply_filters)
        scrollbar=ttk.Scrollbar(listbox_frame,orient=VERTICAL,command=self.customer_listbox.yview);scrollbar.pack(side=RIGHT,fill=Y);self.customer_listbox.config(yscrollcommand=scrollbar.set);ttk.Separator(parent).pack(fill=X,pady=15)
        ttk.Label(parent,text="Anwendung verwalten",font=("-size 12 -weight bold")).pack(fill=X,pady=(0,5))
        alert_text=textwrap.dedent("🔒 WICHTIG: Sicheres Beenden\n\nUm Ihre Datenbank korrekt zu\nverschlüsseln, beenden Sie die\nAnwendung bitte ausschließlich\nüber das [X] des Fensters.\n\n🔴 Achtung: Ein erzwungenes\nSchließen kann zu Datenverlust\nführen!");ttk.Label(parent,text=alert_text,bootstyle=DANGER,justify=LEFT).pack(fill=X,pady=5)

    def _create_main_content_widgets(self, parent):
        ttk.Label(parent,text="📊 Rechnungs-Dashboard",font=("-size 20 -weight bold")).pack(anchor=NW,pady=(0,15))
        ttk.Label(parent,text="📈 Kennzahlen (KPIs)",font=("-size 14 -weight bold")).pack(anchor=NW,pady=(0,5));kpi_frame=ttk.Frame(parent);kpi_frame.pack(fill=X,pady=5)
        self.kpi_revenue=self._create_kpi_metric(kpi_frame,"Gesamtumsatz (Netto)","0,00 €");self.kpi_open_invoices=self._create_kpi_metric(kpi_frame,"Offene Forderungen (Brutto)","0,00 €");self.kpi_total_invoices=self._create_kpi_metric(kpi_frame,"Anzahl Rechnungen (Gesamt)","0");self.kpi_avg_invoice=self._create_kpi_metric(kpi_frame,"Ø Rechnungswert (Brutto)","0,00 €")
        ttk.Separator(parent).pack(fill=X,pady=15)
        ttk.Label(parent,text="🎨 Visualisierungen",font=("-size 14 -weight bold")).pack(anchor=NW,pady=(0,5));vis_frame=ttk.Frame(parent);vis_frame.pack(fill=X,expand=True,pady=5);vis_frame.columnconfigure(0,weight=3);vis_frame.columnconfigure(1,weight=2)
        self.fig_monthly=Figure(figsize=(8,5),dpi=100);self.ax_monthly=self.fig_monthly.add_subplot(111);self.canvas_monthly=FigureCanvasTkAgg(self.fig_monthly,master=vis_frame);self.canvas_monthly.get_tk_widget().grid(row=0,column=0,padx=5,sticky="nsew")
        self.fig_status=Figure(figsize=(5,5),dpi=100);self.ax_status=self.fig_status.add_subplot(111);self.canvas_status=FigureCanvasTkAgg(self.fig_status,master=vis_frame);self.canvas_status.get_tk_widget().grid(row=0,column=1,padx=5,sticky="nsew")
        ttk.Separator(parent).pack(fill=X,pady=15)
        report_frame=ttk.LabelFrame(parent,text="🖨️ Berichte erstellen",padding=10);report_frame.pack(fill=X,pady=(0,10), anchor=N)
        report_inner_frame=ttk.Frame(report_frame);report_inner_frame.pack(fill=X)
        ttk.Label(report_inner_frame,text="Datumsbereich wählen:").pack(side=LEFT,padx=(0,10));self.report_start_date=DateEntry(report_inner_frame,bootstyle=SECONDARY);self.report_start_date.pack(side=LEFT,padx=5);ttk.Label(report_inner_frame,text="-").pack(side=LEFT,padx=5);self.report_end_date=DateEntry(report_inner_frame,bootstyle=SECONDARY);self.report_end_date.pack(side=LEFT,padx=5);self.anonymize_var=tk.BooleanVar(value=False)
        ttk.Checkbutton(report_inner_frame,text="Kundennamen anonymisieren",variable=self.anonymize_var,bootstyle="round-toggle").pack(side=LEFT,padx=20)
        self.pdf_button = ttk.Button(report_inner_frame,text="PDF-Report",command=self._generate_pdf_report,bootstyle=PRIMARY);self.pdf_button.pack(side=LEFT,padx=(10, 5))
        self.csv_button = ttk.Button(report_inner_frame,text="CSV-Report",command=self._generate_csv_report,bootstyle=SECONDARY);self.csv_button.pack(side=LEFT,padx=5)
        table_frame=ttk.LabelFrame(parent,text="📄 Detaillierte Rechnungsübersicht",padding=10);table_frame.pack(fill=BOTH,expand=True,pady=5, anchor=N)
        cols=('rechnungsnummer','rechnungsdatum','kunde_anzeige','status','summe_netto','summe_mwst','summe_brutto');self.tree=ttk.Treeview(table_frame,columns=cols,show='headings')
        self.tree.heading('rechnungsnummer',text='Re.-Nummer',anchor=W);self.tree.column('rechnungsnummer',width=120,anchor=W);self.tree.heading('rechnungsdatum',text='Re.-Datum',anchor=W);self.tree.column('rechnungsdatum',width=100,anchor=W);self.tree.heading('kunde_anzeige',text='Kunde',anchor=W);self.tree.column('kunde_anzeige',width=300,anchor=W);self.tree.heading('status',text='Status',anchor=W);self.tree.column('status',width=200,anchor=W);self.tree.heading('summe_netto',text='Netto (€)',anchor=E);self.tree.column('summe_netto',width=120,anchor=E);self.tree.heading('summe_mwst',text='MwSt. (€)',anchor=E);self.tree.column('summe_mwst',width=120,anchor=E);self.tree.heading('summe_brutto',text='Brutto (€)',anchor=E);self.tree.column('summe_brutto',width=120,anchor=E)
        self.tree.pack(fill=BOTH,expand=True)
    
    def _initialize_ui_state(self):
        for widget in self.sidebar.winfo_children()+self.main_frame.winfo_children():
            if widget==self.db_load_button or widget==self.db_status_label:continue
            self._set_widget_state_recursive(widget,'disabled')
            
    def _enable_ui(self):
        for widget in self.sidebar.winfo_children()+self.main_frame.winfo_children():self._set_widget_state_recursive(widget,'normal')
        
    def _set_widget_state_recursive(self,widget,state_to_set):
        try:widget.configure(state=state_to_set)
        except tk.TclError:pass
        for child in widget.winfo_children():self._set_widget_state_recursive(child,state_to_set)
        
    def _create_kpi_metric(self,parent,title,value):
        frame=ttk.Frame(parent,borderwidth=1,relief="solid");frame.pack(side=LEFT,fill=X,expand=True,padx=5);ttk.Label(frame,text=title,font=("-size 10")).pack(padx=10,pady=(10,0))
        value_label=ttk.Label(frame,text=value,font=("-size 18 -weight bold"),bootstyle=PRIMARY);value_label.pack(padx=10,pady=(0,10));return value_label
        
    def _load_database(self, filepath=None):
        if not filepath:
            filepath=filedialog.askopenfilename(title="Datenbank auswählen",filetypes=(("Database files","*.db *.sqlite *.sqlite3"),("All files","*.*")))
            if not filepath: return
        conn=create_connection(filepath)
        if not conn:return
        df=load_data(conn);conn.close()
        if df.empty or 'rechnungsdatum' not in df.columns:messagebox.showwarning("Leere Datenbank","Die ausgewählte Datenbank ist leer oder hat eine ungültige Struktur.");return
        self.df_all_data=df;self.df_all_data.dropna(subset=['rechnungsdatum'],inplace=True);self.df_all_data['kunde_anzeige']=self.df_all_data.apply(get_customer_display_name,axis=1)
        self.db_status_label.config(text=os.path.basename(filepath),bootstyle=SUCCESS)
        self._enable_ui();self._populate_filters();self._update_kpis_global();self._apply_filters()
        min_date=self.df_all_data['rechnungsdatum'].min().date();max_date=self.df_all_data['rechnungsdatum'].max().date()
        self.report_start_date.entry.delete(0,END);self.report_start_date.entry.insert(0,min_date.strftime('%d.%m.%Y'))
        self.report_end_date.entry.delete(0,END);self.report_end_date.entry.insert(0,max_date.strftime('%d.%m.%Y'))
        
    def _populate_filters(self):
        kunden_liste=sorted(self.df_all_data['kunde_anzeige'].unique());self.customer_listbox.delete(0,END)
        for kunde in kunden_liste:self.customer_listbox.insert(END,kunde)
        self._select_all_customers()
        
    def _select_all_customers(self):self.customer_listbox.selection_set(0,END);self._apply_filters()
    def _deselect_all_customers(self):self.customer_listbox.selection_clear(0,END);self._apply_filters()
    
    def _apply_filters(self, *args):
        if self.df_all_data.empty: return
        selected_stati=[status for status,var in self.status_vars.items() if var.get()]
        selected_indices=self.customer_listbox.curselection();selected_kunden=[self.customer_listbox.get(i) for i in selected_indices]
        self.df_filtered=self.df_all_data[self.df_all_data['status'].isin(selected_stati)&self.df_all_data['kunde_anzeige'].isin(selected_kunden)]
        self._update_charts();self._update_table()
        
    def _update_kpis_global(self):
        df = self.df_all_data
        if df.empty:
            return

        # --- NEUE, GoBD-KONFORME BERECHNUNG DER KPIs ---

        # 1. Gesamtumsatz (Netto): Zählt 'Bezahlt' und 'Offen' positiv, zieht 'Gutschrift' (die negativ ist) ab.
        # 'Storniert' und 'Entwurf' werden ignoriert.
        df_revenue = df[df['status'].isin(['Bezahlt', 'Offen', 'Gutschrift'])]
        total_revenue = df_revenue['summe_netto'].sum()

        # 2. Offene Forderungen (Brutto): Zählt nur Rechnungen mit Status 'Offen'.
        open_invoices_value = df[df['status'] == 'Offen']['summe_brutto'].sum()

        # 3. Anzahl Belege: Zählt alle finalisierten Belege (inkl. Gutschriften und Stornierungen), aber keine Entwürfe.
        total_invoices = len(df[df['is_finalized'] == 1])

        # 4. Durchschnittlicher Rechnungswert: Basiert auf allen finalisierten Belegen.
        avg_invoice_value = df[df['is_finalized'] == 1]['summe_brutto'].mean() if total_invoices > 0 else 0

        self.kpi_revenue.config(text=locale.currency(total_revenue, grouping=True))
        self.kpi_open_invoices.config(text=locale.currency(open_invoices_value, grouping=True))
        self.kpi_total_invoices.config(text=f"{total_invoices}")
        self.kpi_avg_invoice.config(text=locale.currency(avg_invoice_value, grouping=True))
        
    def _update_charts(self):
        plt.style.use('seaborn-v0_8-pastel');df=self.df_filtered;self.ax_monthly.clear()
        if not df.empty:df_monthly=df.copy();df_monthly['monat']=df_monthly['rechnungsdatum'].dt.to_period('M').astype(str);monthly_revenue=df_monthly.groupby('monat')['summe_netto'].sum();monthly_revenue.plot(kind='bar',ax=self.ax_monthly,zorder=3)
        self.ax_monthly.set_title("Monatlicher Netto-Umsatz",fontsize=12);self.ax_monthly.set_ylabel("Netto-Umsatz in €",fontsize=10);self.ax_monthly.set_xlabel("");self.ax_monthly.tick_params(axis='x',rotation=30,labelsize=9);self.ax_monthly.yaxis.grid(True,linestyle='--',alpha=0.6,zorder=0);self.fig_monthly.tight_layout();self.canvas_monthly.draw();self.ax_status.clear()
        if not df.empty:status_counts=df['status'].value_counts();self.ax_status.pie(status_counts,labels=status_counts.index,autopct='%1.1f%%',startangle=90,textprops={'fontsize':9})
        self.ax_status.set_title("Verteilung der Rechnungsstati",fontsize=12);self.fig_status.tight_layout();self.canvas_status.draw()
        
    def _update_table(self):
        for i in self.tree.get_children():self.tree.delete(i)
        df_display=self.df_filtered[['rechnungsnummer','rechnungsdatum','kunde_anzeige','status','summe_netto','summe_mwst','summe_brutto']].copy()
        for _,row in df_display.iterrows():
            re_datum=row['rechnungsdatum'].strftime('%d.%m.%Y');netto_str=f"{row['summe_netto']:.2f}".replace('.',',');mwst_str=f"{row['summe_mwst']:.2f}".replace('.',',');brutto_str=f"{row['summe_brutto']:.2f}".replace('.',',')
            values_tuple=(row['rechnungsnummer'],re_datum,row['kunde_anzeige'],row['status'],netto_str,mwst_str,brutto_str);self.tree.insert("","end",values=values_tuple)
            
    def _get_filtered_report_data(self):
        try:
            start_date_str = self.report_start_date.entry.get()
            end_date_str = self.report_end_date.entry.get()
            start_date = datetime.strptime(start_date_str, '%d.%m.%Y').date()
            end_date = datetime.strptime(end_date_str, '%d.%m.%Y').date()
        except (ValueError, TypeError):
            messagebox.showerror("Ungültiges Datum", "Bitte geben Sie ein gültiges Datum im Format TT.MM.JJJJ ein oder wählen Sie es aus.")
            return None, None, None
        mask=(self.df_filtered['rechnungsdatum'].dt.date>=start_date)&(self.df_filtered['rechnungsdatum'].dt.date<=end_date);df_report_data=self.df_filtered.loc[mask].sort_values(by='rechnungsdatum')
        if df_report_data.empty:messagebox.showwarning("Keine Daten","Im ausgewählten Datumsbereich wurden keine Rechnungen für die aktuelle Filterung gefunden.");return None, None, None
        return df_report_data, start_date, end_date

    def _generate_pdf_report(self):
        df_report_data, start_date, end_date = self._get_filtered_report_data()
        if df_report_data is None: return
        anonymize=self.anonymize_var.get();anonym_suffix = "_anonym" if anonymize else "";default_filename = f"Finanzbericht_{start_date.strftime('%Y%m%d')}-{end_date.strftime('%Y%m%d')}{anonym_suffix}.pdf"
        save_path = filedialog.asksaveasfilename(title="PDF-Report speichern unter...",initialfile=default_filename,defaultextension=".pdf",filetypes=[("PDF-Dokumente", "*.pdf"), ("Alle Dateien", "*.*")])
        if not save_path: return
        try:
            create_financial_report_pdf(df_report_data, start_date, end_date, anonymize, save_to_path=save_path)
            messagebox.showinfo("Erfolg", f"PDF-Report erfolgreich erstellt!\n\nGespeichert als:\n{os.path.abspath(save_path)}")
        except Exception as e:messagebox.showerror("Fehler bei PDF-Erstellung", f"Ein Fehler ist aufgetreten:\n{e}");logging.error(f"Fehler bei PDF-Erstellung: {e}", exc_info=True)

    def _generate_csv_report(self):
        df_report_data, start_date, end_date = self._get_filtered_report_data()
        if df_report_data is None: return
        anonymize=self.anonymize_var.get()
        if anonymize: df_report_data['kunde_anzeige'] = "Kunde-" + df_report_data['zifferncode'].astype(str)
        default_filename = f"Finanzbericht_{start_date.strftime('%Y%m%d')}-{end_date.strftime('%Y%m%d')}.csv"
        save_path = filedialog.asksaveasfilename(title="CSV-Report speichern unter...",initialfile=default_filename,defaultextension=".csv",filetypes=[("CSV-Dateien (Semikolon-getrennt)", "*.csv"), ("Alle Dateien", "*.*")])
        if not save_path: return
        try:
            df_export = df_report_data[['rechnungsdatum', 'rechnungsnummer', 'kunde_anzeige', 'status', 'summe_netto', 'summe_mwst', 'summe_brutto']].copy()
            df_export['rechnungsdatum'] = df_export['rechnungsdatum'].dt.strftime('%d.%m.%Y')
            for col in ['summe_netto', 'summe_mwst', 'summe_brutto']: df_export[col] = df_export[col].apply(lambda x: f'{x:.2f}'.replace('.', ','))
            df_export.to_csv(save_path, index=False, sep=';', encoding='utf-8-sig')
            messagebox.showinfo("Erfolg", f"CSV-Report erfolgreich erstellt!\n\nGespeichert als:\n{os.path.abspath(save_path)}")
        except Exception as e:messagebox.showerror("Fehler bei CSV-Erstellung", f"Ein Fehler ist aufgetreten:\n{e}");logging.error(f"Fehler bei CSV-Erstellung: {e}", exc_info=True)

def load_config(config_filename='config.txt'):
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), config_filename)
    config = {}
    if not os.path.exists(config_path):
        logging.warning(f"Konfigurationsdatei nicht gefunden: {config_path}")
        return config
    with open(config_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                parts = line.split('=', 1)
                if len(parts) == 2: config[parts[0].strip()] = parts[1].strip()
    return config

# --- ANWENDUNG STARTEN (DEBUG-SICHER) ---
if __name__=="__main__":
    try:
        logging.info(f"=======================================\nStarte Rechnungs-Dashboard (Tkinter)...")
        config = load_config()
        if _run_daten_schloss():
            logging.info("DatenSchloss-Startup erfolgreich. Initialisiere GUI...")
            app=DashboardApp(config=config);app.mainloop()
        else:logging.critical("DatenSchloss-Startup fehlgeschlagen.");sys.exit(1)
    except Exception as e:
        logging.error("Ein nicht abgefangener kritischer Fehler ist aufgetreten.",exc_info=True);root=tk.Tk();root.withdraw()
        error_message=f"Ein unerwarteter Fehler hat den Start der Anwendung verhindert:\n\n{traceback.format_exc()}"
        messagebox.showerror("Kritischer Anwendungsfehler",error_message);root.destroy();sys.exit(1)