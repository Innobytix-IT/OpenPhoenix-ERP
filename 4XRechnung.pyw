import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import sqlite3
from lxml import etree
from datetime import datetime
import os
import traceback # Für detaillierte Fehlerdiagnose

# --- NEUE IMPORTS FÜR DATENSCHLOSS UND LIZENZ ---
import uuid
import hashlib
import subprocess
import sys
import logging # Empfohlen für Logging der DatenSchloss-Aktionen
# --- ENDE NEUE IMPORTS ---

# --- Logging Konfiguration (empfohlen) ---
logging.basicConfig(filename='xrechnung_generator.log', level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
# --- Ende Logging ---


# --- KONSTANTEN ---
APP_NAME = "XRechnung Generator"
CONFIG_FILE_NAME = "config.txt" # Bleibt bestehen

NSMAP = {
    "rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
    "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
    "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100",
    "qdt": "urn:un:unece:uncefact:data:standard:QualifiedDataType:100"
}

UNIT_CODE_MAP = {
    "stück": "H87", "stk": "H87", "std": "HUR", "kg": "KGM",
    "liter": "LTR", "l": "LTR", "meter": "MTR", "m": "MTR",
    "einheit": "C62", "pauschal": "C62", "": "C62"
}

DEFAULT_CONFIG_FLAT = {
    'db_path': 'Unternehmen.db',
    'document_base_path': './UnternehmensDokumente',
    'company_name': 'Meine Firma GmbH',
    'company_street': 'Musterstraße',
    'company_housenumber': '1',
    'company_postal_code': '12345',
    'company_city': 'Musterstadt',
    'company_country_id': 'DE',
    'company_phone': '0123-456789',
    'company_email': 'info@meine-firma.de',
    'company_tax_id': 'DE123456789',
    'company_fiscal_number': '123/456/7890',
    'company_bank_details_iban': 'DE89370400440532013000',
    'company_bank_details_bic': 'COBADEFFXXX',
    'company_contact_person': 'Max Mustermann',
    'default_vat_rate': '19.0'
}

CONFIG_DISPLAY_NAMES = {
    'company_name': 'Firmenname',
    'company_contact_person': 'Kontaktperson',
    'company_street': 'Straße',
    'company_housenumber': 'Hausnummer',
    'company_postal_code': 'Postleitzahl',
    'company_city': 'Stadt',
    'company_country_id': 'Länderkennzeichen (ID)',
    'company_phone': 'Telefon',
    'company_email': 'E-Mail-Adresse',
    'company_tax_id': 'Umsatzsteuer-IdNr.',
    'company_fiscal_number': 'Steuernummer',
    'company_bank_details_iban': 'IBAN',
    'company_bank_details_bic': 'BIC',
    'default_vat_rate': 'Standard MwSt.-Satz (%)'
}

# --- HILFSFUNKTIONEN FÜR DATENSCHLOSS UND LIZENZ (aus Mahnwesen übernommen) ---


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
                 logging.warning(f"pythonw.exe nicht gefunden ({pythonw_interpreter}), verwende {sys.executable} für .pyw")
        logging.info(f"DatenSchloss Tool gefunden (PYW): {tool_pyw_path} (Interpreter: {interpreter})")
        return [interpreter, tool_pyw_path]
    logging.warning(f"DatenSchloss Tool '{tool_name_base}' nicht gefunden (gesucht: .exe, .pyw im Skript-Verzeichnis).")
    return None

def _run_daten_schloss_startup():
    logging.info("Prüfe und starte DatenSchloss Tool (Startup)...")
    tool_command = _find_daten_schloss_tool()
    if tool_command:
        try:
            logging.info(f"Starte DatenSchloss Tool: {' '.join(tool_command)}")
            startupinfo = None
            creationflags = 0
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NO_WINDOW

            process = subprocess.run(tool_command, check=True, cwd=os.path.dirname(os.path.abspath(__file__)),
                                     text=True, capture_output=True, startupinfo=startupinfo, creationflags=creationflags)
            logging.info(f"DatenSchloss Tool (Startup) erfolgreich beendet. Exit Code: {process.returncode}")
            return True
        except FileNotFoundError:
             logging.error(f"DatenSchloss Tool oder Interpreter nicht gefunden. Command: {' '.join(tool_command)}")
             messagebox.showerror("Fehler", "Das benötigte Tool 'DatenSchloss' wurde nicht gefunden oder kann nicht gestartet werden.\n\nBitte stellen Sie sicher, dass 'DatenSchloss.exe' oder 'DatenSchloss.pyw' im selben Verzeichnis wie die Anwendung liegt.")
             return False
        except subprocess.CalledProcessError as e:
            logging.error(f"DatenSchloss Tool (Startup) beendet mit Fehler (Exit Code: {e.returncode}). Stderr:\n{e.stderr}\nStdout:\n{e.stdout}")
            messagebox.showerror("Fehler", f"Das Tool 'DatenSchloss' ist beim Start unerwartet beendet (Exit Code {e.returncode}).\n\nDie Anwendung wird beendet.\nDetails: {e.stdout or e.stderr}")
            return False
        except Exception as e:
            logging.exception("Unerwarteter Fehler beim Starten des DatenSchloss Tools (Startup):")
            messagebox.showerror("Fehler", f"Ein unerwarteter Fehler ist beim Starten des Tools 'DatenSchloss' aufgetreten:\n{e}\n\nDie Anwendung wird beendet.")
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
            logging.info(f"Starte DatenSchloss Tool (Shutdown): {' '.join(tool_command)}")
            startupinfo = None
            creationflags = 0
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NO_WINDOW

            process = subprocess.run(tool_command, cwd=os.path.dirname(os.path.abspath(__file__)),
                                     text=True, capture_output=True, startupinfo=startupinfo, creationflags=creationflags)
            logging.info(f"DatenSchloss Tool (Shutdown) beendet. Exit Code: {process.returncode}")
            if process.returncode != 0:
                 logging.warning(f"DatenSchloss Tool (Shutdown) beendet mit Non-Zero Exit Code: {process.returncode}. Stderr:\n{process.stderr}\nStdout:\n{process.stdout}")
        except FileNotFoundError:
             logging.error(f"DatenSchloss Tool (Shutdown) nicht gefunden (oder Interpreter für .pyw): {' '.join(tool_command)}")
        except Exception as e:
            logging.exception("Unerwarteter Fehler beim Starten des DatenSchloss Tools (Shutdown):")
    else:
        logging.warning("DatenSchloss Tool nicht gefunden, kann nicht beim Beenden gestartet werden.")

# --- ENDE HILFSFUNKTIONEN FÜR DATENSCHLOSS UND LIZENZ ---


# --- CONFIG MANAGEMENT ---
def get_config_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), CONFIG_FILE_NAME)

def load_config_flat():
    config_path = get_config_path()
    config_data = DEFAULT_CONFIG_FLAT.copy()
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'): continue
                    if '=' in line: key, value = line.split('=', 1); config_data[key.strip()] = value.strip()
        except Exception as e:
            messagebox.showerror("Config Fehler", f"Fehler beim Lesen von {CONFIG_FILE_NAME}: {e}")
            return DEFAULT_CONFIG_FLAT.copy()
    else:
        save_config_flat(config_data)
        messagebox.showinfo("Konfiguration", f"{CONFIG_FILE_NAME} wurde mit Standardwerten erstellt.")
    return config_data

def save_config_flat(config_data):
    config_path = get_config_path()
    try:
        with open(config_path, 'w', encoding='utf-8') as f:
            all_keys_to_save = list(DEFAULT_CONFIG_FLAT.keys())
            for key_in_data in config_data:
                if key_in_data not in all_keys_to_save: all_keys_to_save.append(key_in_data)
            final_keys_to_write = [k for k in all_keys_to_save if k in config_data or k in DEFAULT_CONFIG_FLAT]
            for key in final_keys_to_write:
                value = config_data.get(key, DEFAULT_CONFIG_FLAT.get(key, '')); f.write(f"{key}={value}\n")
        return True
    except Exception as e:
        messagebox.showerror("Fehler", f"Konfiguration konnte nicht gespeichert werden: {e}"); return False

# --- DATENBANKFUNKTIONEN ---
def get_db_connection(config_data):
    db_path_val = config_data.get('db_path', DEFAULT_CONFIG_FLAT['db_path'])
    if not os.path.isabs(db_path_val):
        script_dir = os.path.dirname(os.path.abspath(__file__)); db_path_val = os.path.join(script_dir, db_path_val)
    if not os.path.exists(db_path_val):
        messagebox.showerror("Datenbankfehler", f"Datenbankdatei nicht gefunden: {db_path_val}\nPfad prüfen."); return None
    try:
        conn = sqlite3.connect(db_path_val); conn.row_factory = sqlite3.Row; return conn
    except sqlite3.Error as e:
        messagebox.showerror("Datenbankfehler", f"Fehler Verbinden Datenbank: {e}"); return None

def fetch_invoice_data_from_db(conn, rechnungsnummer_input):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT r.*, k.id as k_id, k.name as k_name, k.vorname as k_vorname, k.titel_firma,
               k.strasse as k_strasse, k.hausnummer as k_hausnummer, k.plz as k_plz, k.ort as k_ort,
               k.telefon as k_telefon, k.email as k_email, k.zifferncode as k_zifferncode
        FROM rechnungen r JOIN kunden k ON r.kunde_id = k.id 
        WHERE r.rechnungsnummer = ? AND r.is_finalized = 1
    """, (rechnungsnummer_input,))
    invoice_header = cursor.fetchone()

    if not invoice_header:
        cursor.execute("SELECT status FROM rechnungen WHERE rechnungsnummer = ?", (rechnungsnummer_input,))
        status_row = cursor.fetchone()
        if status_row:
            return f"STATUS:{status_row['status']}", None
        return None, None

    cursor.execute("SELECT * FROM rechnungsposten WHERE rechnung_id = ? ORDER BY position", (invoice_header["id"],))
    invoice_lines = cursor.fetchall()
    return invoice_header, invoice_lines

def save_document_to_db(conn, kunde_id, document_path, filename):
    try:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO kunden_dokumente (kunde_id, dokument_pfad, dateiname) VALUES (?, ?, ?)",
                       (kunde_id, document_path, filename))
        conn.commit(); return True
    except sqlite3.Error as e:
        messagebox.showerror("Datenbankfehler", f"Fehler Speichern Dokument in DB: {e}"); return False

# --- HILFSFUNKTIONEN ---
def format_date_for_xml(date_str_db):
    if not date_str_db: return datetime.now().strftime("%Y%m%d")
    try: return datetime.strptime(date_str_db, "%d.%m.%Y").strftime("%Y%m%d")
    except ValueError:
        try: return datetime.strptime(date_str_db, "%Y-%m-%d").strftime("%Y%m%d")
        except ValueError: return datetime.now().strftime("%Y%m%d")

def format_decimal(value, digits=2):
    if value is None: return f"0.{'0'*digits}"
    try: return f"{float(value):.{digits}f}"
    except (ValueError, TypeError): return f"0.{'0'*digits}"

def get_unit_code(db_unit_name):
    return UNIT_CODE_MAP.get(str(db_unit_name).lower() if db_unit_name else "", "C62")

# --- XRECHNUNG ERSTELLUNGSFUNKTION ---
def create_xrechnung_xml_from_gui(gui_data):
    root = etree.Element(etree.QName(NSMAP["rsm"], "CrossIndustryInvoice"), nsmap=NSMAP)
    edc = etree.SubElement(root, etree.QName(NSMAP["rsm"], "ExchangedDocumentContext"))
    bpdcp = etree.SubElement(edc, etree.QName(NSMAP["ram"], "BusinessProcessSpecifiedDocumentContextParameter"))
    etree.SubElement(bpdcp, etree.QName(NSMAP["ram"], "ID")).text = "urn:fdc:peppol.eu:2017:poacc:billing:01:1.0"
    gsp = etree.SubElement(edc, etree.QName(NSMAP["ram"], "GuidelineSpecifiedDocumentContextParameter"))
    etree.SubElement(gsp, etree.QName(NSMAP["ram"], "ID")).text = "urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0"
    ed = etree.SubElement(root, etree.QName(NSMAP["rsm"], "ExchangedDocument"))
    etree.SubElement(ed, etree.QName(NSMAP["ram"], "ID")).text = gui_data['invoice_number']
    etree.SubElement(ed, etree.QName(NSMAP["ram"], "TypeCode")).text = "380"
    issue_date_xml = format_date_for_xml(gui_data['invoice_date'])
    id_dt = etree.SubElement(ed, etree.QName(NSMAP["ram"], "IssueDateTime"))
    dt_str_el = etree.SubElement(id_dt, etree.QName(NSMAP["udt"], "DateTimeString"), format="102"); dt_str_el.text = issue_date_xml
    if gui_data.get('invoice_note'):
         note = etree.SubElement(ed, etree.QName(NSMAP["ram"], "IncludedNote"))
         etree.SubElement(note, etree.QName(NSMAP["ram"], "Content")).text = gui_data['invoice_note']
    sctt = etree.SubElement(root, etree.QName(NSMAP["rsm"], "SupplyChainTradeTransaction"))
    for item in gui_data['invoice_lines']:
        li = etree.SubElement(sctt, etree.QName(NSMAP["ram"], "IncludedSupplyChainTradeLineItem"))
        doc_line_doc = etree.SubElement(li, etree.QName(NSMAP["ram"], "AssociatedDocumentLineDocument"))
        etree.SubElement(doc_line_doc, etree.QName(NSMAP["ram"], "LineID")).text = str(item["position"])
        trade_product = etree.SubElement(li, etree.QName(NSMAP["ram"], "SpecifiedTradeProduct"))
        if "artikelnummer" in item.keys() and item["artikelnummer"] is not None:
            etree.SubElement(trade_product, etree.QName(NSMAP["ram"], "SellerAssignedID")).text = str(item["artikelnummer"])
        etree.SubElement(trade_product, etree.QName(NSMAP["ram"], "Name")).text = item["beschreibung"]
        trade_agreement_line = etree.SubElement(li, etree.QName(NSMAP["ram"], "SpecifiedLineTradeAgreement"))
        net_price_el = etree.SubElement(trade_agreement_line, etree.QName(NSMAP["ram"], "NetPriceProductTradePrice"))
        etree.SubElement(net_price_el, etree.QName(NSMAP["ram"], "ChargeAmount")).text = format_decimal(item["einzelpreis_netto"])
        trade_delivery_line = etree.SubElement(li, etree.QName(NSMAP["ram"], "SpecifiedLineTradeDelivery"))
        unit_val = item["einheit"] if "einheit" in item.keys() else None
        billed_qty_el = etree.SubElement(trade_delivery_line, etree.QName(NSMAP["ram"], "BilledQuantity"), unitCode=get_unit_code(unit_val))
        billed_qty_el.text = format_decimal(item["menge"], 3)
        trade_settlement_line = etree.SubElement(li, etree.QName(NSMAP["ram"], "SpecifiedLineTradeSettlement"))
        vat_line = etree.SubElement(trade_settlement_line, etree.QName(NSMAP["ram"], "ApplicableTradeTax"))
        etree.SubElement(vat_line, etree.QName(NSMAP["ram"], "TypeCode")).text = "VAT"
        etree.SubElement(vat_line, etree.QName(NSMAP["ram"], "CategoryCode")).text = "S"
        etree.SubElement(vat_line, etree.QName(NSMAP["ram"], "RateApplicablePercent")).text = format_decimal(gui_data['vat_rate'])
        mon_sum_line = etree.SubElement(trade_settlement_line, etree.QName(NSMAP["ram"], "SpecifiedTradeSettlementLineMonetarySummation"))
        etree.SubElement(mon_sum_line, etree.QName(NSMAP["ram"], "LineTotalAmount")).text = format_decimal(item["gesamtpreis_netto"])
    ah_trade_agreement = etree.SubElement(sctt, etree.QName(NSMAP["ram"], "ApplicableHeaderTradeAgreement"))
    if gui_data.get('buyer_reference'):
        etree.SubElement(ah_trade_agreement, etree.QName(NSMAP["ram"], "BuyerReference")).text = gui_data['buyer_reference']
    seller_party = etree.SubElement(ah_trade_agreement, etree.QName(NSMAP["ram"], "SellerTradeParty"))
    etree.SubElement(seller_party, etree.QName(NSMAP["ram"], "Name")).text = gui_data.get('seller_name', gui_data.get('company_name'))
    seller_contact = etree.SubElement(seller_party, etree.QName(NSMAP["ram"], "DefinedTradeContact"))
    etree.SubElement(seller_contact, etree.QName(NSMAP["ram"], "PersonName")).text = gui_data.get('seller_contact_person', gui_data.get('company_contact_person'))
    seller_contact_phone = etree.SubElement(seller_contact, etree.QName(NSMAP["ram"], "TelephoneUniversalCommunication"))
    etree.SubElement(seller_contact_phone, etree.QName(NSMAP["ram"], "CompleteNumber")).text = gui_data.get('seller_phone', gui_data.get('company_phone'))
    seller_contact_email = etree.SubElement(seller_contact, etree.QName(NSMAP["ram"], "EmailURIUniversalCommunication"))
    etree.SubElement(seller_contact_email, etree.QName(NSMAP["ram"], "URIID")).text = gui_data.get('seller_email', gui_data.get('company_email'))
    seller_address = etree.SubElement(seller_party, etree.QName(NSMAP["ram"], "PostalTradeAddress"))
    etree.SubElement(seller_address, etree.QName(NSMAP["ram"], "PostcodeCode")).text = gui_data.get('seller_postal_code', gui_data.get('company_postal_code'))
    seller_street_val = gui_data.get('seller_street', gui_data.get('company_street','')); seller_hnr_val = gui_data.get('seller_housenumber', gui_data.get('company_housenumber',''))
    etree.SubElement(seller_address, etree.QName(NSMAP["ram"], "LineOne")).text = f"{seller_street_val} {seller_hnr_val}".strip()
    etree.SubElement(seller_address, etree.QName(NSMAP["ram"], "CityName")).text = gui_data.get('seller_city', gui_data.get('company_city'))
    etree.SubElement(seller_address, etree.QName(NSMAP["ram"], "CountryID")).text = gui_data.get('seller_country_id', gui_data.get('company_country_id'))
    
    # KORREKTUR 2: Hinzufügen der Verkäufer-E-Mail auf der Hauptebene, um R020 zu erfüllen.
    seller_email_val = gui_data.get('seller_email', gui_data.get('company_email'))
    if seller_email_val:
        seller_email_main = etree.SubElement(seller_party, etree.QName(NSMAP["ram"], "URIUniversalCommunication"))
        etree.SubElement(seller_email_main, etree.QName(NSMAP["ram"], "URIID"), schemeID="EM").text = seller_email_val

    seller_tax_reg_vat = etree.SubElement(seller_party, etree.QName(NSMAP["ram"], "SpecifiedTaxRegistration"))
    etree.SubElement(seller_tax_reg_vat, etree.QName(NSMAP["ram"], "ID"), schemeID="VA").text = gui_data.get('seller_vat_id', gui_data.get('company_tax_id'))
    seller_tax_reg_fc = etree.SubElement(seller_party, etree.QName(NSMAP["ram"], "SpecifiedTaxRegistration"))
    etree.SubElement(seller_tax_reg_fc, etree.QName(NSMAP["ram"], "ID"), schemeID="FC").text = gui_data.get('seller_fiscal_number', gui_data.get('company_fiscal_number'))
    buyer_party = etree.SubElement(ah_trade_agreement, etree.QName(NSMAP["ram"], "BuyerTradeParty"))
    etree.SubElement(buyer_party, etree.QName(NSMAP["ram"], "Name")).text = gui_data['buyer_name']
    buyer_address = etree.SubElement(buyer_party, etree.QName(NSMAP["ram"], "PostalTradeAddress"))
    etree.SubElement(buyer_address, etree.QName(NSMAP["ram"], "PostcodeCode")).text = gui_data['buyer_postal_code']
    etree.SubElement(buyer_address, etree.QName(NSMAP["ram"], "LineOne")).text = gui_data['buyer_street_line']
    etree.SubElement(buyer_address, etree.QName(NSMAP["ram"], "CityName")).text = gui_data['buyer_city']
    etree.SubElement(buyer_address, etree.QName(NSMAP["ram"], "CountryID")).text = "DE"
    if gui_data.get('buyer_email'):
        buyer_email_main = etree.SubElement(buyer_party, etree.QName(NSMAP["ram"], "URIUniversalCommunication"))
        etree.SubElement(buyer_email_main, etree.QName(NSMAP["ram"], "URIID"), schemeID="EM").text = gui_data['buyer_email']
    
    # KORREKTUR 1: ApplicableHeaderTradeDelivery wieder einfügen (an der korrekten Position) und mit minimalem Inhalt füllen, um den XSD-Fehler zu beheben.
    ah_trade_delivery = etree.SubElement(sctt, etree.QName(NSMAP["ram"], "ApplicableHeaderTradeDelivery"))
    delivery_event = etree.SubElement(ah_trade_delivery, etree.QName(NSMAP["ram"], "ActualDeliverySupplyChainEvent"))
    occurrence_date = etree.SubElement(delivery_event, etree.QName(NSMAP["ram"], "OccurrenceDateTime"))
    dt_str_el_delivery = etree.SubElement(occurrence_date, etree.QName(NSMAP["udt"], "DateTimeString"), format="102")
    dt_str_el_delivery.text = format_date_for_xml(gui_data.get('invoice_date')) # Rechnungsdatum als Standard-Lieferdatum verwenden
    
    ah_trade_settlement = etree.SubElement(sctt, etree.QName(NSMAP["ram"], "ApplicableHeaderTradeSettlement"))
    etree.SubElement(ah_trade_settlement, etree.QName(NSMAP["ram"], "InvoiceCurrencyCode")).text = "EUR"
    payment_means = etree.SubElement(ah_trade_settlement, etree.QName(NSMAP["ram"], "SpecifiedTradeSettlementPaymentMeans"))
    etree.SubElement(payment_means, etree.QName(NSMAP["ram"], "TypeCode")).text = "30"
    payee_account = etree.SubElement(payment_means, etree.QName(NSMAP["ram"], "PayeePartyCreditorFinancialAccount"))
    etree.SubElement(payee_account, etree.QName(NSMAP["ram"], "IBANID")).text = gui_data.get('seller_iban', gui_data.get('company_bank_details_iban'))
    if gui_data.get('seller_bic', gui_data.get('company_bank_details_bic')):
         etree.SubElement(payee_account, etree.QName(NSMAP["ram"], "ProprietaryID")).text = gui_data.get('seller_bic', gui_data.get('company_bank_details_bic'))
    vat_breakdown = etree.SubElement(ah_trade_settlement, etree.QName(NSMAP["ram"], "ApplicableTradeTax"))
    etree.SubElement(vat_breakdown, etree.QName(NSMAP["ram"], "CalculatedAmount")).text = format_decimal(gui_data['total_vat_amount'])
    etree.SubElement(vat_breakdown, etree.QName(NSMAP["ram"], "TypeCode")).text = "VAT"
    etree.SubElement(vat_breakdown, etree.QName(NSMAP["ram"], "BasisAmount")).text = format_decimal(gui_data['total_net_amount'])
    etree.SubElement(vat_breakdown, etree.QName(NSMAP["ram"], "CategoryCode")).text = "S"
    etree.SubElement(vat_breakdown, etree.QName(NSMAP["ram"], "RateApplicablePercent")).text = format_decimal(gui_data['vat_rate'])
    payment_terms_node = etree.SubElement(ah_trade_settlement, etree.QName(NSMAP["ram"], "SpecifiedTradePaymentTerms"))
    payment_description = (gui_data.get('payment_terms_note') or 
                           gui_data.get('invoice_note') or 
                           f"Zahlbar bis {gui_data.get('due_date', 'N/A')}.")
    etree.SubElement(payment_terms_node, etree.QName(NSMAP["ram"], "Description")).text = payment_description
    if gui_data.get('due_date'):
        due_date_dt = etree.SubElement(payment_terms_node, etree.QName(NSMAP["ram"], "DueDateDateTime"))
        dt_str_el_due = etree.SubElement(due_date_dt, etree.QName(NSMAP["udt"], "DateTimeString"), format="102"); dt_str_el_due.text = format_date_for_xml(gui_data['due_date'])
    mon_sum_header = etree.SubElement(ah_trade_settlement, etree.QName(NSMAP["ram"], "SpecifiedTradeSettlementHeaderMonetarySummation"))
    etree.SubElement(mon_sum_header, etree.QName(NSMAP["ram"], "LineTotalAmount")).text = format_decimal(gui_data['total_net_amount'])
    etree.SubElement(mon_sum_header, etree.QName(NSMAP["ram"], "TaxBasisTotalAmount")).text = format_decimal(gui_data['total_net_amount'])
    etree.SubElement(mon_sum_header, etree.QName(NSMAP["ram"], "TaxTotalAmount"), currencyID="EUR").text = format_decimal(gui_data['total_vat_amount'])
    etree.SubElement(mon_sum_header, etree.QName(NSMAP["ram"], "GrandTotalAmount")).text = format_decimal(gui_data['total_gross_amount'])
    etree.SubElement(mon_sum_header, etree.QName(NSMAP["ram"], "DuePayableAmount")).text = format_decimal(gui_data['total_gross_amount'])
    xml_bytes = etree.tostring(root, pretty_print=True, xml_declaration=True, encoding='UTF-8')
    return xml_bytes

# --- TKINTER GUI ---
class XRechnungApp:
    def __init__(self, root_tk):
        self.root = root_tk
        self.root.title(APP_NAME)
        self.root.geometry("850x700")
        self.config_data = load_config_flat()
        self.current_invoice_header = None
        self.current_invoice_lines = []
        self.entries = {}
        self.setup_menu()
        self.setup_gui()
        self.load_seller_info_from_config()
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)


    def on_closing(self):
        logging.info(f"{APP_NAME} wird beendet...")
        _run_daten_schloss_shutdown()
        if hasattr(self, 'conn') and self.conn:
            try:
                self.conn.close()
                logging.info("Datenbankverbindung geschlossen.")
            except Exception as e:
                logging.error(f"Fehler beim Schließen der Datenbankverbindung: {e}")
        self.root.destroy()
        logging.info("Anwendungsfenster zerstört. Programmende.")

    def setup_menu(self):
        menubar = tk.Menu(self.root)
        filemenu = tk.Menu(menubar, tearoff=0)
        filemenu.add_command(label="Einstellungen", command=self.open_settings_dialog)
        filemenu.add_separator()
        filemenu.add_command(label="Beenden", command=self.on_closing)
        menubar.add_cascade(label="Datei", menu=filemenu)
        self.root.config(menu=menubar)

    def create_labeled_entry(self, parent, label_text, row, col, var_name, **kwargs):
        label = ttk.Label(parent, text=label_text)
        label.grid(row=row, column=col, padx=5, pady=2, sticky="w")
        entry_var = tk.StringVar()
        entry = ttk.Entry(parent, textvariable=entry_var, **kwargs)
        entry.grid(row=row, column=col + 1, padx=5, pady=2, sticky="ew")
        self.entries[var_name] = entry_var
        return entry_var, entry

    def setup_gui(self):
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(expand=True, fill="both")
        main_frame.columnconfigure(1, weight=1)
        invoice_input_frame = ttk.LabelFrame(main_frame, text="Rechnungsdaten laden")
        invoice_input_frame.grid(row=0, column=0, columnspan=2, padx=5, pady=5, sticky="ew")
        invoice_input_frame.columnconfigure(1, weight=1)
        self.create_labeled_entry(invoice_input_frame, "Rechnungsnummer:", 0, 0, "invoice_number_input", width=25)
        load_button = ttk.Button(invoice_input_frame, text="Laden", command=self.load_invoice_data)
        load_button.grid(row=0, column=2, padx=5, pady=5)
        paste_button = ttk.Button(invoice_input_frame, text="Einfügen", command=self.paste_invoice_number)
        paste_button.grid(row=0, column=3, padx=5, pady=5)
        details_frame = ttk.LabelFrame(main_frame, text="Rechnungsdetails (editierbar)")
        details_frame.grid(row=1, column=0, padx=5, pady=5, sticky="nsew")
        details_frame.columnconfigure(1, weight=1)
        entry_width_short = 20
        entry_width_medium = 30
        self.create_labeled_entry(details_frame, "Rechnungs-Nr.:", 0, 0, "invoice_number", width=entry_width_short)
        self.create_labeled_entry(details_frame, "Rechnungsdatum (TT.MM.JJJJ):", 1, 0, "invoice_date", width=entry_width_short)
        self.create_labeled_entry(details_frame, "Fälligkeitsdatum (TT.MM.JJJJ):", 2, 0, "due_date", width=entry_width_short)
        self.create_labeled_entry(details_frame, "MwSt.-Satz (%):", 3, 0, "vat_rate", width=entry_width_short)
        self.create_labeled_entry(details_frame, "Bemerkung/Zahlungsbedingung:", 4, 0, "invoice_note", width=entry_width_medium)
        self.create_labeled_entry(details_frame, "Gesamt Netto:", 5, 0, "total_net_amount", state='readonly', width=entry_width_short)
        self.create_labeled_entry(details_frame, "Gesamt MwSt.:", 6, 0, "total_vat_amount", state='readonly', width=entry_width_short)
        self.create_labeled_entry(details_frame, "Gesamt Brutto:", 7, 0, "total_gross_amount", state='readonly', width=entry_width_short)
        buyer_frame = ttk.LabelFrame(main_frame, text="Käuferdetails (editierbar)")
        buyer_frame.grid(row=1, column=1, padx=5, pady=5, sticky="nsew")
        buyer_frame.columnconfigure(1, weight=1)
        self.create_labeled_entry(buyer_frame, "Käufername:", 0, 0, "buyer_name", width=entry_width_medium)
        self.create_labeled_entry(buyer_frame, "Käufer Referenz/Kdnr.:", 1, 0, "buyer_reference", width=entry_width_short)
        self.create_labeled_entry(buyer_frame, "Straße Hnr.:", 2, 0, "buyer_street_line", width=entry_width_medium)
        self.create_labeled_entry(buyer_frame, "PLZ:", 3, 0, "buyer_postal_code", width=entry_width_short)
        self.create_labeled_entry(buyer_frame, "Stadt:", 4, 0, "buyer_city", width=entry_width_medium)
        self.create_labeled_entry(buyer_frame, "E-Mail:", 5, 0, "buyer_email", width=entry_width_medium)
        seller_frame = ttk.LabelFrame(main_frame, text="Verkäuferdetails (aus config.txt, editierbar)")
        seller_frame.grid(row=2, column=0, columnspan=2, padx=5, pady=5, sticky="ew")
        seller_frame.columnconfigure(1, weight=1); seller_frame.columnconfigure(3, weight=1)
        seller_entry_width = 35
        self.create_labeled_entry(seller_frame, "Firmenname:", 0, 0, "seller_name", width=seller_entry_width)
        self.create_labeled_entry(seller_frame, "Kontaktperson:", 0, 2, "seller_contact_person", width=seller_entry_width)
        self.create_labeled_entry(seller_frame, "Straße:", 1, 0, "seller_street", width=seller_entry_width)
        self.create_labeled_entry(seller_frame, "Hausnummer:", 1, 2, "seller_housenumber", width=seller_entry_width-20)
        self.create_labeled_entry(seller_frame, "PLZ:", 2, 0, "seller_postal_code", width=seller_entry_width-20)
        self.create_labeled_entry(seller_frame, "Stadt:", 2, 2, "seller_city", width=seller_entry_width)
        self.create_labeled_entry(seller_frame, "Land (ID):", 3, 0, "seller_country_id", width=seller_entry_width-20)
        self.create_labeled_entry(seller_frame, "Telefon:", 3, 2, "seller_phone", width=seller_entry_width)
        self.create_labeled_entry(seller_frame, "E-Mail:", 4, 0, "seller_email", width=seller_entry_width)
        self.create_labeled_entry(seller_frame, "USt-IdNr.:", 4, 2, "seller_vat_id", width=seller_entry_width)
        self.create_labeled_entry(seller_frame, "Steuernummer:", 5, 0, "seller_fiscal_number", width=seller_entry_width)
        self.create_labeled_entry(seller_frame, "IBAN:", 5, 2, "seller_iban", width=seller_entry_width)
        self.create_labeled_entry(seller_frame, "BIC:", 6, 0, "seller_bic", width=seller_entry_width)
        action_frame = ttk.Frame(main_frame)
        action_frame.grid(row=3, column=0, columnspan=2, pady=10)
        create_button = ttk.Button(action_frame, text="XRechnung erstellen und speichern", command=self.create_and_save_xrechnung)
        create_button.pack(side="left", padx=5)
        self.status_var = tk.StringVar(); self.status_var.set("Bereit.")
        status_bar = ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor="w")
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    def paste_invoice_number(self):
        temp_file = "temporärspeicher.tmp"
        try:
            if not os.path.exists(temp_file):
                messagebox.showwarning("Keine Daten", "Es wurde keine Rechnungsnummer vorbereitet.", parent=self.root)
                return

            with open(temp_file, "r", encoding="utf-8") as f:
                rechnungs_nr = f.read().strip()
            
            self.entries["invoice_number_input"].set(rechnungs_nr)
            logging.info(f"Rechnungsnummer '{rechnungs_nr}' aus '{temp_file}' eingefügt.")

        except Exception as e:
            messagebox.showerror("Fehler", f"Vorbereitete Rechnungsnummer konnte nicht gelesen werden:\n{e}", parent=self.root)
            logging.error(f"Fehler beim Lesen der temporären Datei: {e}")

    def load_seller_info_from_config(self):
        self.config_data = load_config_flat()
        seller_gui_map = {
            'company_name': 'seller_name', 'company_contact_person': 'seller_contact_person',
            'company_street': 'seller_street', 'company_housenumber': 'seller_housenumber',
            'company_postal_code': 'seller_postal_code', 'company_city': 'seller_city',
            'company_country_id': 'seller_country_id', 'company_phone': 'seller_phone',
            'company_email': 'seller_email', 'company_tax_id': 'seller_vat_id',
            'company_fiscal_number': 'seller_fiscal_number',
            'company_bank_details_iban': 'seller_iban', 'company_bank_details_bic': 'seller_bic'
        }
        for config_key, entry_key in seller_gui_map.items():
            if self.entries.get(entry_key):
                value = self.config_data.get(config_key, DEFAULT_CONFIG_FLAT.get(config_key, ''))
                self.entries[entry_key].set(value)
        vat_rate_conf = self.config_data.get('default_vat_rate', DEFAULT_CONFIG_FLAT['default_vat_rate'])
        if self.entries.get('vat_rate') and not self.entries['vat_rate'].get():
            self.entries['vat_rate'].set(vat_rate_conf)

    def load_invoice_data(self):
        rechnungsnummer = self.entries["invoice_number_input"].get()
        if not rechnungsnummer:
            messagebox.showwarning("Eingabe fehlt", "Bitte geben Sie eine Rechnungsnummer ein.")
            return

        conn = get_db_connection(self.config_data)
        if not conn:
            return

        try:
            header, lines = fetch_invoice_data_from_db(conn, rechnungsnummer)

            if isinstance(header, str) and header.startswith("STATUS:"):
                status = header.split(":")[1]
                messagebox.showwarning("Falscher Status",
                                       f"Rechnung '{rechnungsnummer}' wurde gefunden, hat aber den Status '{status}'.\n\n"
                                       "Eine XRechnung kann nur für finalisierte und offene Rechnungen erstellt werden.")
                self.status_var.set(f"Rechnung {rechnungsnummer} hat den Status '{status}'. Laden nicht möglich.")
                self.clear_invoice_fields()
            elif header:
                self.current_invoice_header = header
                self.current_invoice_lines = lines
                self.status_var.set(f"Daten für finalisierte Rechnung {rechnungsnummer} geladen.")
                self.populate_gui_from_data()
            else:
                messagebox.showinfo("Nicht gefunden",
                                    f"Es wurde keine finalisierte Rechnung mit der Nummer '{rechnungsnummer}' gefunden.")
                self.status_var.set(f"Keine finalisierte Rechnung für {rechnungsnummer} gefunden.")
                self.clear_invoice_fields()

        except Exception as e:
            messagebox.showerror("Fehler", f"Ein Fehler ist beim Laden der Rechnungsdaten aufgetreten: {e}")
            self.status_var.set("Fehler beim Laden der Daten.")
            traceback.print_exc()
        finally:
            if conn:
                conn.close()

    def populate_gui_from_data(self):
        if not self.current_invoice_header: return
        h = self.current_invoice_header
        self.entries['invoice_number'].set(h['rechnungsnummer']); self.entries['invoice_date'].set(h['rechnungsdatum'])
        self.entries['due_date'].set(h['faelligkeitsdatum'] or ''); self.entries['vat_rate'].set(format_decimal(h['mwst_prozent']))
        self.entries['invoice_note'].set(h['bemerkung'] or ''); self.entries['total_net_amount'].set(format_decimal(h['summe_netto']))
        self.entries['total_vat_amount'].set(format_decimal(h['summe_mwst'])); self.entries['total_gross_amount'].set(format_decimal(h['summe_brutto']))
        buyer_name = h['titel_firma'] if h['titel_firma'] else f"{h['k_vorname'] or ''} {h['k_name'] or ''}".strip()
        self.entries['buyer_name'].set(buyer_name); self.entries['buyer_reference'].set(h['k_zifferncode'] or '')
        self.entries['buyer_street_line'].set(f"{h['k_strasse'] or ''} {h['k_hausnummer'] or ''}".strip())
        self.entries['buyer_postal_code'].set(h['k_plz'] or ''); self.entries['buyer_city'].set(h['k_ort'] or '')
        self.entries['buyer_email'].set(h['k_email'] or '')

    def clear_invoice_fields(self):
        fields_to_clear = ['invoice_number', 'invoice_date', 'due_date', 'vat_rate', 'invoice_note', 'total_net_amount', 'total_vat_amount', 'total_gross_amount', 'buyer_name', 'buyer_reference', 'buyer_street_line', 'buyer_postal_code', 'buyer_city', 'buyer_email']
        for key in fields_to_clear:
            if self.entries.get(key): self.entries[key].set("")
        self.current_invoice_header = None; self.current_invoice_lines = []

    def collect_gui_data_for_xml(self):
        gui_data = {key: var.get() for key, var in self.entries.items()}
        gui_data['invoice_lines'] = self.current_invoice_lines
        try: float(gui_data.get('vat_rate', 0))
        except ValueError: messagebox.showerror("Fehler", "Ungültiger MwSt.-Satz."); return None
        return gui_data

    def create_and_save_xrechnung(self):
        if not self.current_invoice_header: messagebox.showwarning("Keine Daten", "Bitte laden Sie zuerst die Daten einer finalisierten Rechnung."); return
        gui_data = self.collect_gui_data_for_xml()
        if not gui_data: return
        try: xml_bytes = create_xrechnung_xml_from_gui(gui_data)
        except Exception as e:
            messagebox.showerror("XML Erstellungsfehler", f"Fehler bei XML-Erstellung: {e}"); self.status_var.set(f"Fehler XML: {type(e).__name__} - {e}")
            print(f"DEBUG: XML Fehler: {type(e).__name__} - {e}"); traceback.print_exc(); return
        rechnungsnummer = gui_data['invoice_number']; safe_rechnungsnummer = "".join(c if c.isalnum() or c in ['-', '_'] else '_' for c in rechnungsnummer)
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S"); xml_filename = f"XRechnung_{safe_rechnungsnummer}_{timestamp}.xml"
        document_base_path_val = self.config_data.get('document_base_path', DEFAULT_CONFIG_FLAT['document_base_path'])
        if not os.path.isabs(document_base_path_val):
            script_dir = os.path.dirname(os.path.abspath(__file__)); document_base_path_val = os.path.join(script_dir, document_base_path_val)
        header_keys = self.current_invoice_header.keys(); k_zifferncode_val = None; k_id_val = None
        if 'k_zifferncode' in header_keys and self.current_invoice_header['k_zifferncode'] is not None: k_zifferncode_val = str(self.current_invoice_header['k_zifferncode'])
        if 'k_id' in header_keys and self.current_invoice_header['k_id'] is not None: k_id_val = str(self.current_invoice_header['k_id'])
        customer_identifier = k_zifferncode_val or k_id_val or "Unbekannt"
        customer_folder_path = os.path.join(document_base_path_val, customer_identifier); os.makedirs(customer_folder_path, exist_ok=True)
        full_xml_path = os.path.join(customer_folder_path, xml_filename)
        try:
            with open(full_xml_path, "wb") as f: f.write(xml_bytes)
            self.status_var.set(f"XRechnung gespeichert: {xml_filename}"); messagebox.showinfo("Erfolg", f"XRechnung gespeichert:\n'{full_xml_path}'.")
            conn = get_db_connection(self.config_data)
            if conn:
                try:
                    kunde_id_db = int(self.current_invoice_header['k_id']) if 'k_id' in self.current_invoice_header.keys() else None
                    if kunde_id_db is not None: save_document_to_db(conn, kunde_id_db, full_xml_path, xml_filename); self.status_var.set(f"XRechnung gespeichert & DB vermerkt: {xml_filename}")
                    else: self.status_var.set(f"XRechnung gespeichert, k_id für DB fehlt.")
                finally: conn.close()
        except Exception as e: messagebox.showerror("Speicherfehler", f"Fehler Speichern XML: {e}"); self.status_var.set("Fehler Speichern XML."); traceback.print_exc()

    def open_settings_dialog(self):
        settings_dialog = tk.Toplevel(self.root); settings_dialog.title("Einstellungen"); settings_dialog.transient(self.root); settings_dialog.grab_set()
        frame = ttk.Frame(settings_dialog, padding="10"); frame.pack(expand=True, fill="both"); frame.columnconfigure(1, weight=1)
        settings_vars = {}
        ttk.Label(frame, text="Datenbankpfad:").grid(row=0, column=0, sticky="w", pady=2)
        db_path_var = tk.StringVar(value=self.config_data.get('db_path', DEFAULT_CONFIG_FLAT['db_path'])); settings_vars['db_path'] = db_path_var
        db_path_entry = ttk.Entry(frame, textvariable=db_path_var, width=50); db_path_entry.grid(row=0, column=1, sticky="ew", pady=2, padx=5)
        ttk.Button(frame, text="...", command=lambda: self.browse_db_path(db_path_var)).grid(row=0, column=2, pady=2)
        ttk.Label(frame, text="Basis-Dokumentenpfad:").grid(row=1, column=0, sticky="w", pady=2)
        doc_base_path_var = tk.StringVar(value=self.config_data.get('document_base_path', DEFAULT_CONFIG_FLAT['document_base_path'])); settings_vars['document_base_path'] = doc_base_path_var
        doc_base_path_entry = ttk.Entry(frame, textvariable=doc_base_path_var, width=50); doc_base_path_entry.grid(row=1, column=1, sticky="ew", pady=2, padx=5)
        ttk.Button(frame, text="...", command=lambda: self.browse_folder_path(doc_base_path_var)).grid(row=1, column=2, pady=2)
        row_idx = 2; ttk.Label(frame, text="Verkäufer-/Firmendaten:", font="-weight bold").grid(row=row_idx, column=0, columnspan=3, sticky="w", pady=(10,2)); row_idx += 1
        editable_config_keys = ['company_name', 'company_contact_person', 'company_street', 'company_housenumber', 'company_postal_code', 'company_city', 'company_country_id', 'company_phone', 'company_email', 'company_tax_id', 'company_fiscal_number', 'company_bank_details_iban', 'company_bank_details_bic', 'default_vat_rate']
        for key in editable_config_keys:
            default_value = DEFAULT_CONFIG_FLAT.get(key, ''); display_name = CONFIG_DISPLAY_NAMES.get(key, key.replace('_', ' ').title())
            ttk.Label(frame, text=f"{display_name}:").grid(row=row_idx, column=0, sticky="w", pady=2)
            var = tk.StringVar(value=self.config_data.get(key, default_value)); entry = ttk.Entry(frame, textvariable=var, width=50)
            entry.grid(row=row_idx, column=1, columnspan=2, sticky="ew", pady=2, padx=5); settings_vars[key] = var; row_idx += 1
        ttk.Button(frame, text="Speichern und Schließen", command=lambda: self.save_settings(settings_dialog, settings_vars)).grid(row=row_idx, column=0, columnspan=3, pady=10)

    def browse_db_path(self, path_var):
        filename = filedialog.askopenfilename(title="Datenbankdatei", filetypes=(("SQLite DB", "*.db"), ("Alle Dateien", "*.*")))
        if filename: path_var.set(filename)

    def browse_folder_path(self, path_var):
        foldername = filedialog.askdirectory(title="Ordner auswählen")
        if foldername: path_var.set(foldername)

    def save_settings(self, dialog, settings_vars_dict):
        for key, var in settings_vars_dict.items(): self.config_data[key] = var.get()
        if save_config_flat(self.config_data):
            messagebox.showinfo("Gespeichert", "Einstellungen gespeichert.", parent=dialog)
            self.load_seller_info_from_config(); dialog.destroy()
        else: messagebox.showerror("Fehler", "Einstellungen nicht gespeichert.", parent=dialog)

if __name__ == "__main__":
    logging.info(f"=======================================\nStarte {APP_NAME}...")
    if not _run_daten_schloss_startup():
        logging.critical("DatenSchloss-Startup fehlgeschlagen. Anwendung wird beendet.")
        sys.exit(1)

    root = None
    try:
        root = tk.Tk()
        app = XRechnungApp(root)

        logging.info("Standard Tkinter-Widgets werden verwendet.")

        if hasattr(app, 'config_data'):
            root.mainloop()
        else:
            logging.critical("Anwendung konnte nicht korrekt initialisiert werden. Beende.")
            if root and root.winfo_exists(): root.destroy()
            _run_daten_schloss_shutdown()
            sys.exit(1)

    except Exception as main_e:
        logging.exception("Kritischer Fehler im Hauptprogrammablauf:")
        try:
            messagebox.showerror("Kritischer Fehler", f"Ein unerwarteter kritischer Fehler ist aufgetreten:\n{main_e}\n\nDie Anwendung wird beendet. Bitte prüfen Sie die Logdatei 'xrechnung_generator.log'.")
        except Exception as msg_e:
            print(f"FATAL APPLICATION ERROR: {main_e}\n(Messagebox display error: {msg_e})", file=sys.stderr)
        if root and root.winfo_exists():
            try: root.destroy()
            except: pass
        _run_daten_schloss_shutdown()
        sys.exit(1)


    finally:
        if 'app' in locals() and app is not None and not app.root.winfo_exists():
            pass
        else:
            logging.info("Anwendungsprozess endet via finally-Block (möglicherweise unerwartet).")
            _run_daten_schloss_shutdown()