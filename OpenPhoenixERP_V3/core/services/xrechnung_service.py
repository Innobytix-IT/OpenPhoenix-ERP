"""
core/services/xrechnung_service.py – XRechnung-Export (EN 16931 / UBL 2.1)
===========================================================================
Erstellt normkonforme XRechnung-XML-Dateien nach dem deutschen Standard
für elektronische Rechnungen (ZRE / OZG-RE).

Norm:       EN 16931-1:2017 + CIUS DE (XRechnung 3.0)
Format:     UBL 2.1 (Universal Business Language)
Zeichensatz: UTF-8

Pflichtfelder (BT = Business Term):
  BT-1   Rechnungsnummer
  BT-2   Rechnungsdatum
  BT-9   Fälligkeitsdatum
  BT-10  Leitweg-ID (Käufer-Referenz, Pflicht für B2G)
  BT-23  Geschäftsprozesskennung (urn:fdc:peppol.eu:2017:poacc:billing:01:1.0)
  BT-24  Spezifikationskennung (urn:cen.eu:en16931:2017#compliant#urn:xoev-de:kosit:standard:xrechnung_3.0)
  BT-27  Verkäufer-Name
  BT-31  Verkäufer-Steuernummer
  BT-44  Käufer-Name
  BT-112 Steuerpflichtiger Betrag (Netto)
  BT-117 MwSt.-Betrag
  BT-109 Gesamtbetrag Netto
  BT-112 Steuerpflichtiger Betrag
  BT-115 Fälliger Betrag
"""

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Optional

from lxml import etree

from core.config import config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# UBL-Namensräume
# ---------------------------------------------------------------------------

NS = {
    None:      "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
    "cac":     "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "cbc":     "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "xsi":     "http://www.w3.org/2001/XMLSchema-instance",
}

# Qualifizierte Tag-Namen
CAC  = "{urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2}"
CBC  = "{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}"
ROOT = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"

SPEC_ID   = "urn:cen.eu:en16931:2017#compliant#urn:xoev-de:kosit:standard:xrechnung_3.0"
PROCESS_ID = "urn:fdc:peppol.eu:2017:poacc:billing:01:1.0"


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------

@dataclass
class VerkäuferInfo:
    """Rechnungssteller (aus config.toml)."""
    name: str
    strasse: str = ""
    plz: str = ""
    ort: str = ""
    land: str = "DE"
    steuernummer: str = ""        # BT-31 (USt-ID bevorzugt)
    ust_id: str = ""              # BT-31 alternativ
    email: str = ""
    telefon: str = ""
    bank_iban: str = ""
    bank_bic: str = ""
    bank_name: str = ""
    leitweg_id: str = ""          # Leitweg-ID für Behördenrechnungen (B2G)

    @classmethod
    def aus_config(cls) -> "VerkäuferInfo":
        c = config
        name = c.get("company", "name", "")
        adresse = c.get("company", "address", "")
        # PLZ + Ort: erst neue Einzelfelder, dann Fallback auf zip_city
        plz = c.get("company", "zip", "")
        ort = c.get("company", "city", "")
        if not plz and not ort:
            plz_ort = c.get("company", "zip_city", "")
            if plz_ort:
                teile = plz_ort.split(" ", 1)
                if len(teile) == 2:
                    plz, ort = teile
        bank = c.get("company", "bank_details", "") or ""
        tax_id = c.get("company", "tax_id", "") or ""

        # Bank-IBAN aus Freitext extrahieren
        # Erkennt IBAN mit oder ohne "IBAN"-Präfix (z.B. "DE64..." oder "IBAN DE64...")
        import re as _re
        iban, bic, bname = "", "", ""
        bank_clean = bank.replace(" ", "").upper()
        # Direkte IBAN: 2 Buchstaben + 2 Prüfziffern + bis 30 alphanumerische Zeichen
        iban_match = _re.search(r'[A-Z]{2}[0-9]{2}[A-Z0-9]{10,30}', bank.replace(" ", "").upper())
        if iban_match:
            iban = iban_match.group(0)
        # BIC aus Freitext (8 oder 11 Zeichen, nur Buchstaben/Ziffern)
        for part in bank.split():
            if len(part) in (8, 11) and part.isalnum() and not part.startswith("DE"):
                bic = part

        # USt-ID vs. Steuernummer unterscheiden
        ust_id, steuernr = "", ""
        if tax_id.upper().startswith("DE"):
            ust_id = tax_id
        else:
            steuernr = tax_id

        return cls(
            name=name,
            strasse=adresse,
            plz=plz,
            ort=ort,
            steuernummer=steuernr,
            ust_id=ust_id,
            email=c.get("company", "email", ""),
            telefon=c.get("company", "phone", ""),
            bank_iban=iban,
            bank_bic=bic,
            bank_name=bname,
            leitweg_id=c.get("company", "leitweg_id", ""),
        )


@dataclass
class XRechnungPosten:
    """Ein Rechnungsposten für die XRechnung."""
    position: int
    artikelnummer: str
    beschreibung: str
    menge: Decimal
    einheit: str            # UNECE Unit Code z.B. "C62" = Stück, "HUR" = Stunde
    einzelpreis_netto: Decimal
    gesamtpreis_netto: Decimal
    mwst_prozent: Decimal   # Wird normalerweise auf Rechnungsebene gesetzt


@dataclass
class XRechnungDaten:
    """Alle Daten die für eine XRechnung benötigt werden."""
    rechnungsnummer: str
    rechnungsdatum: str           # TT.MM.JJJJ
    faelligkeitsdatum: str        # TT.MM.JJJJ
    leitweg_id: str               # BT-10, z.B. "991-12345678-06" oder Kunden-E-Mail
    verkäufer: VerkäuferInfo
    käufer_name: str
    käufer_strasse: str = ""
    käufer_plz: str = ""
    käufer_ort: str = ""
    käufer_land: str = "DE"
    käufer_email: str = ""
    käufer_ustid: str = ""
    mwst_prozent: Decimal = Decimal("19.00")
    summe_netto: Decimal = Decimal("0")
    summe_mwst: Decimal = Decimal("0")
    summe_brutto: Decimal = Decimal("0")
    offener_betrag: Optional[Decimal] = None    # BT-115 PayableAmount / BT-113 PrepaidAmount
    bemerkung: str = ""
    posten: list[XRechnungPosten] = field(default_factory=list)


@dataclass
class ExportResult:
    success: bool
    message: str = ""
    dateipfad: str = ""
    xml_string: str = ""

    @classmethod
    def ok(cls, dateipfad: str, xml_string: str) -> "ExportResult":
        return cls(
            success=True,
            message=f"XRechnung erstellt: {Path(dateipfad).name}",
            dateipfad=dateipfad,
            xml_string=xml_string,
        )

    @classmethod
    def fail(cls, message: str) -> "ExportResult":
        return cls(success=False, message=message)


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _datum_iso(datum_dd_mm_yyyy: str) -> str:
    """Konvertiert TT.MM.JJJJ → JJJJ-MM-TT (ISO 8601)."""
    try:
        return datetime.strptime(datum_dd_mm_yyyy.strip(), "%d.%m.%Y").strftime("%Y-%m-%d")
    except (ValueError, AttributeError):
        return datum_dd_mm_yyyy

def _mwst_kategorie(prozent: Decimal) -> str:
    """Gibt den MwSt.-Kategoriecode zurück."""
    if prozent == Decimal("0"):
        return "Z"   # Zero rated
    return "S"       # Standard rate

def _einheit_code(einheit: str) -> str:
    """Mappt deutsche Einheiten auf UNECE-Codes."""
    mapping = {
        "stück":    "C62",
        "stk":      "C62",
        "stk.":     "C62",
        "st":       "C62",
        "st.":      "C62",
        "stunde":   "HUR",
        "std":      "HUR",
        "std.":     "HUR",
        "h":        "HUR",
        "kg":       "KGM",
        "gramm":    "GRM",
        "g":        "GRM",
        "liter":    "LTR",
        "l":        "LTR",
        "meter":    "MTR",
        "m":        "MTR",
        "km":       "KMT",
        "tag":      "DAY",
        "tage":     "DAY",
        "monat":    "MON",
        "jahr":     "ANN",
        "pauschal": "LS",
        "pauschal.":"LS",
        "psch":     "LS",
    }
    return mapping.get(einheit.lower(), "C62")  # Default: Stück


def _sub(parent, tag: str, text: str = "", **attribs) -> etree._Element:
    """Erstellt ein Kind-Element mit optionalem Text und Attributen."""
    el = etree.SubElement(parent, tag, **attribs)
    if text:
        el.text = text
    return el


# ---------------------------------------------------------------------------
# XRechnungService
# ---------------------------------------------------------------------------

class XRechnungService:
    """
    Erstellt XRechnung-XML nach EN 16931 / CIUS DE / UBL 2.1.

    Workflow:
    1. xrechnung_daten_aus_dto() - Konvertiert RechnungDTO → XRechnungDaten
    2. erstellen() - Generiert XML und schreibt Datei
    3. validieren() - Optionale Schemavalidierung
    """

    def xrechnung_daten_aus_dto(
        self,
        rechnung_dto,      # RechnungDTO aus rechnungen_service
        session,           # SQLAlchemy-Session für Kundendaten
        leitweg_id: str = "",
    ) -> XRechnungDaten:
        """
        Konvertiert ein RechnungDTO in XRechnungDaten.
        leitweg_id: Pflichtfeld für B2G-Rechnungen (z.B. "991-12345678-06").
                    Für B2B kann die E-Mail des Kunden verwendet werden.
        """
        from core.models import Kunde
        kunde = session.get(Kunde, rechnung_dto.kunde_id)

        # Käufer-Adresse aufbauen
        käufer_strasse = ""
        käufer_plz = ""
        käufer_ort = ""
        if kunde:
            teile = [kunde.strasse or "", kunde.hausnummer or ""]
            käufer_strasse = " ".join(t for t in teile if t).strip()
            käufer_plz = kunde.plz or ""
            käufer_ort = kunde.ort or ""

        # Posten konvertieren
        posten = []
        for p in rechnung_dto.posten:
            posten.append(XRechnungPosten(
                position=p.position,
                artikelnummer=p.artikelnummer or "",
                beschreibung=p.beschreibung or "",
                menge=p.menge,
                einheit=_einheit_code(p.einheit or ""),
                einzelpreis_netto=p.einzelpreis_netto,
                gesamtpreis_netto=p.gesamtpreis_netto,
                mwst_prozent=rechnung_dto.mwst_prozent,
            ))

        # Leitweg-ID: Fallback auf E-Mail oder Kundennummer
        if not leitweg_id:
            if kunde and kunde.email:
                leitweg_id = kunde.email
            elif kunde and kunde.zifferncode:
                leitweg_id = str(kunde.zifferncode)
            else:
                leitweg_id = rechnung_dto.rechnungsnummer

        return XRechnungDaten(
            rechnungsnummer=rechnung_dto.rechnungsnummer,
            rechnungsdatum=rechnung_dto.rechnungsdatum,
            faelligkeitsdatum=rechnung_dto.faelligkeitsdatum or "",
            leitweg_id=leitweg_id,
            verkäufer=VerkäuferInfo.aus_config(),
            käufer_name=rechnung_dto.kunde_display,
            käufer_strasse=käufer_strasse,
            käufer_plz=käufer_plz,
            käufer_ort=käufer_ort,
            käufer_email=(kunde.email or "") if kunde else "",
            mwst_prozent=rechnung_dto.mwst_prozent,
            summe_netto=rechnung_dto.summe_netto,
            summe_mwst=rechnung_dto.summe_mwst,
            summe_brutto=rechnung_dto.summe_brutto,
            offener_betrag=rechnung_dto.offener_betrag,
            bemerkung=rechnung_dto.bemerkung or "",
            posten=posten,
        )

    def erstellen(
        self,
        daten: XRechnungDaten,
        ausgabe_verzeichnis: Optional[str] = None,
    ) -> ExportResult:
        """
        Generiert das XRechnung-XML und schreibt es in eine Datei.

        Dateiname: <Rechnungsnummer>.xml (Sonderzeichen werden ersetzt)
        """
        # Validierung
        fehler = self._validiere_pflichtfelder(daten)
        if fehler:
            return ExportResult.fail(fehler)

        try:
            xml_bytes = self._xml_erstellen(daten)
            xml_string = xml_bytes.decode("utf-8")

            # Dateiname
            safe_nr = daten.rechnungsnummer.replace("/", "-").replace("\\", "-")
            dateiname = f"XRechnung_{safe_nr}.xml"

            if not ausgabe_verzeichnis:
                ausgabe_verzeichnis = config.get("paths", "xrechnung_output", "")
            if not ausgabe_verzeichnis:
                ausgabe_verzeichnis = str(Path.home() / "OpenPhoenix" / "XRechnungen")

            os.makedirs(ausgabe_verzeichnis, exist_ok=True)
            dateipfad = str(Path(ausgabe_verzeichnis) / dateiname)

            with open(dateipfad, "wb") as f:
                f.write(xml_bytes)

            logger.info(f"XRechnung erstellt: {dateipfad}")
            return ExportResult.ok(dateipfad, xml_string)

        except Exception as e:
            logger.exception("Fehler beim Erstellen der XRechnung:")
            return ExportResult.fail(f"Fehler beim Erstellen: {e}")

    def xml_string(self, daten: XRechnungDaten) -> str:
        """Gibt das XML als String zurück (ohne Datei zu schreiben)."""
        fehler = self._validiere_pflichtfelder(daten)
        if fehler:
            raise ValueError(fehler)
        return self._xml_erstellen(daten).decode("utf-8")

    # ------------------------------------------------------------------
    # XML-Erstellung
    # ------------------------------------------------------------------

    def _xml_erstellen(self, d: XRechnungDaten) -> bytes:
        """Baut den vollständigen UBL-2.1-Baum auf."""

        # Root-Element mit Namensräumen
        root = etree.Element(
            f"{{{ROOT}}}Invoice",
            nsmap={
                None:  ROOT,
                "cac": NS["cac"],
                "cbc": NS["cbc"],
            }
        )

        # ---- BT-24 / BT-23: Spezifikations- und Prozesskennung --------
        _sub(root, f"{CBC}CustomizationID", SPEC_ID)
        _sub(root, f"{CBC}ProfileID", PROCESS_ID)

        # ---- BT-1: Rechnungsnummer ------------------------------------
        _sub(root, f"{CBC}ID", d.rechnungsnummer)

        # ---- BT-2: Rechnungsdatum -------------------------------------
        _sub(root, f"{CBC}IssueDate", _datum_iso(d.rechnungsdatum))

        # ---- Fälligkeitsdatum (BT-9 via PaymentMeans) -----------------
        if d.faelligkeitsdatum:
            _sub(root, f"{CBC}DueDate", _datum_iso(d.faelligkeitsdatum))

        # ---- Rechnungstyp 380 = Handelsrechnung -----------------------
        _sub(root, f"{CBC}InvoiceTypeCode", "380")

        # ---- Sprache ---------------------------------------------------
        _sub(root, f"{CBC}DocumentCurrencyCode", "EUR")

        # ---- BT-10: Leitweg-ID (Käufer-Referenz) ----------------------
        _sub(root, f"{CBC}BuyerReference", d.leitweg_id)

        # ---- Bemerkung (BT-22) ----------------------------------------
        if d.bemerkung:
            note = _sub(root, f"{CBC}Note", d.bemerkung[:255])

        # ---- Verkäufer (BT-27 ff.) ------------------------------------
        acc_supplier = _sub(root, f"{CAC}AccountingSupplierParty")
        party_v = _sub(acc_supplier, f"{CAC}Party")

        # EndpointID (BT-34) ist PFLICHT
        # Priorität: Leitweg-ID (für Behörden) > E-Mail > Firmenname
        if d.verkäufer.leitweg_id:
            ep_v = _sub(party_v, f"{CBC}EndpointID", d.verkäufer.leitweg_id)
            ep_v.set("schemeID", "0204")   # Leitweg-ID
        else:
            seller_endpoint = d.verkäufer.email or d.verkäufer.name
            ep_v = _sub(party_v, f"{CBC}EndpointID", seller_endpoint)
            ep_v.set("schemeID", "EM")     # E-Mail

        pname_v = _sub(party_v, f"{CAC}PartyName")
        _sub(pname_v, f"{CBC}Name", d.verkäufer.name)

        # PostalAddress ist BR-08 Pflichtfeld – immer generieren
        addr_v = _sub(party_v, f"{CAC}PostalAddress")
        if d.verkäufer.strasse:
            _sub(addr_v, f"{CBC}StreetName", d.verkäufer.strasse)
        if d.verkäufer.ort:
            _sub(addr_v, f"{CBC}CityName", d.verkäufer.ort)
        if d.verkäufer.plz:
            _sub(addr_v, f"{CBC}PostalZone", d.verkäufer.plz)
        ctr_v = _sub(addr_v, f"{CAC}Country")
        _sub(ctr_v, f"{CBC}IdentificationCode", d.verkäufer.land)

        # Steuernummer des Verkäufers
        tax_scheme_v = _sub(party_v, f"{CAC}PartyTaxScheme")
        if d.verkäufer.ust_id:
            _sub(tax_scheme_v, f"{CBC}CompanyID", d.verkäufer.ust_id)
        elif d.verkäufer.steuernummer:
            _sub(tax_scheme_v, f"{CBC}CompanyID", d.verkäufer.steuernummer)
        else:
            _sub(tax_scheme_v, f"{CBC}CompanyID", "DE000000000")
        ts_v = _sub(tax_scheme_v, f"{CAC}TaxScheme")
        _sub(ts_v, f"{CBC}ID", "VAT")

        legal_v = _sub(party_v, f"{CAC}PartyLegalEntity")
        _sub(legal_v, f"{CBC}RegistrationName", d.verkäufer.name)

        # Contact ist BR-DE-2 Pflichtfeld – immer generieren
        contact_v = _sub(party_v, f"{CAC}Contact")
        _sub(contact_v, f"{CBC}Name", d.verkäufer.name)  # BT-41 Pflicht
        if d.verkäufer.telefon:
            _sub(contact_v, f"{CBC}Telephone", d.verkäufer.telefon)
        if d.verkäufer.email:
            _sub(contact_v, f"{CBC}ElectronicMail", d.verkäufer.email)

        # ---- Käufer (BT-44 ff.) ---------------------------------------
        acc_customer = _sub(root, f"{CAC}AccountingCustomerParty")
        party_k = _sub(acc_customer, f"{CAC}Party")

        # EndpointID des Käufers (BT-49) – Pflicht in EN 16931
        if d.käufer_email:
            ep_k = _sub(party_k, f"{CBC}EndpointID", d.käufer_email)
            ep_k.set("schemeID", "EM")
        else:
            # Fallback: Kundenname als Endpoint mit "no-endpoint" Schema
            ep_k = _sub(party_k, f"{CBC}EndpointID", d.käufer_name or "N/A")
            ep_k.set("schemeID", "EM")

        pname_k = _sub(party_k, f"{CAC}PartyName")
        _sub(pname_k, f"{CBC}Name", d.käufer_name)

        if d.käufer_strasse or d.käufer_ort:
            addr_k = _sub(party_k, f"{CAC}PostalAddress")
            if d.käufer_strasse:
                _sub(addr_k, f"{CBC}StreetName", d.käufer_strasse)
            if d.käufer_ort:
                _sub(addr_k, f"{CBC}CityName", d.käufer_ort)
            if d.käufer_plz:
                _sub(addr_k, f"{CBC}PostalZone", d.käufer_plz)
            ctr_k = _sub(_sub(addr_k, f"{CAC}Country"), f"{CBC}IdentificationCode", d.käufer_land)

        legal_k = _sub(party_k, f"{CAC}PartyLegalEntity")
        _sub(legal_k, f"{CBC}RegistrationName", d.käufer_name)

        # ---- Zahlungsart (BT-81) -------------------------------------
        payment = _sub(root, f"{CAC}PaymentMeans")
        if d.verkäufer.bank_iban:
            # SEPA-Überweisung nur wenn IBAN vorhanden (BR-DE-19)
            _sub(payment, f"{CBC}PaymentMeansCode", "58")
            payee_fin = _sub(payment, f"{CAC}PayeeFinancialAccount")
            _sub(payee_fin, f"{CBC}ID", d.verkäufer.bank_iban)
            if d.verkäufer.bank_bic or d.verkäufer.bank_name:
                fin_inst = _sub(payee_fin, f"{CAC}FinancialInstitutionBranch")
                _sub(fin_inst, f"{CBC}ID",
                     d.verkäufer.bank_bic or d.verkäufer.bank_name)
        else:
            # Keine IBAN → "Nicht spezifiziert" statt ungültige Dummy-IBAN
            _sub(payment, f"{CBC}PaymentMeansCode", "1")

        # ---- Steuergesamt (BT-110 ff.) --------------------------------
        tax_total = _sub(root, f"{CAC}TaxTotal")
        _sub(tax_total, f"{CBC}TaxAmount",
             self._fmt_decimal(d.summe_mwst),
             currencyID="EUR")

        tax_sub = _sub(tax_total, f"{CAC}TaxSubtotal")
        _sub(tax_sub, f"{CBC}TaxableAmount",
             self._fmt_decimal(d.summe_netto), currencyID="EUR")
        _sub(tax_sub, f"{CBC}TaxAmount",
             self._fmt_decimal(d.summe_mwst), currencyID="EUR")
        tc = _sub(tax_sub, f"{CAC}TaxCategory")
        _sub(tc, f"{CBC}ID", _mwst_kategorie(d.mwst_prozent))
        _sub(tc, f"{CBC}Percent", str(d.mwst_prozent))
        # BR-Z-10: Bei 0% MwSt. muss ein Befreiungsgrund (BT-120) angegeben werden.
        # TaxExemptionReasonCode (BT-121) wird NICHT gesetzt, da der korrekte
        # Code vom konkreten Befreiungsgrund abhängt (Kleinunternehmer, Reverse
        # Charge, innergemeinschaftlich etc.) und falsche Codes zu Steuerfehlern
        # beim Empfänger führen können.
        if d.mwst_prozent == Decimal("0"):
            _sub(tc, f"{CBC}TaxExemptionReason",
                 "Steuerbefreit gem. §19 UStG / Art. 196 MwStSystRL")
        ts = _sub(tc, f"{CAC}TaxScheme")
        _sub(ts, f"{CBC}ID", "VAT")

        # ---- Geldbeträge-Übersicht (BT-106 ff.) ----------------------
        mon = _sub(root, f"{CAC}LegalMonetaryTotal")
        _sub(mon, f"{CBC}LineExtensionAmount",
             self._fmt_decimal(d.summe_netto), currencyID="EUR")
        _sub(mon, f"{CBC}TaxExclusiveAmount",
             self._fmt_decimal(d.summe_netto), currencyID="EUR")
        _sub(mon, f"{CBC}TaxInclusiveAmount",
             self._fmt_decimal(d.summe_brutto), currencyID="EUR")
        # BT-113 PrepaidAmount + BT-115 PayableAmount:
        # Wenn Teilzahlungen verbucht wurden, muss PayableAmount den offenen
        # Restbetrag widerspiegeln, nicht den vollen Brutto-Betrag.
        payable = d.summe_brutto
        if d.offener_betrag is not None and d.offener_betrag < d.summe_brutto:
            bereits_gezahlt = d.summe_brutto - d.offener_betrag
            if bereits_gezahlt > Decimal("0"):
                _sub(mon, f"{CBC}PrepaidAmount",
                     self._fmt_decimal(bereits_gezahlt), currencyID="EUR")
            payable = max(d.offener_betrag, Decimal("0"))
        _sub(mon, f"{CBC}PayableAmount",
             self._fmt_decimal(payable), currencyID="EUR")

        # ---- Rechnungspositionen (BG-25) ------------------------------
        for pos in d.posten:
            self._posten_xml(root, pos, d.mwst_prozent)

        # Serialisieren
        return etree.tostring(
            root,
            pretty_print=True,
            xml_declaration=True,
            encoding="UTF-8",
        )

    def _posten_xml(
        self,
        root: etree._Element,
        pos: XRechnungPosten,
        rechnung_mwst: Decimal,
    ) -> None:
        """Fügt eine Rechnungsposition (BG-25) ein."""
        line = _sub(root, f"{CAC}InvoiceLine")
        _sub(line, f"{CBC}ID", str(pos.position))
        _sub(line, f"{CBC}InvoicedQuantity",
             self._fmt_decimal_4(pos.menge),
             unitCode=pos.einheit)
        _sub(line, f"{CBC}LineExtensionAmount",
             self._fmt_decimal(pos.gesamtpreis_netto),
             currencyID="EUR")

        # Artikel (BG-31)
        item = _sub(line, f"{CAC}Item")
        # BT-154 Description (optional)
        if pos.beschreibung:
            _sub(item, f"{CBC}Description", pos.beschreibung)
        # BT-153 Name PFLICHT (BR-25)
        _sub(item, f"{CBC}Name", pos.beschreibung or pos.artikelnummer or "Artikel")
        if pos.artikelnummer:
            sid = _sub(item, f"{CAC}SellersItemIdentification")
            _sub(sid, f"{CBC}ID", pos.artikelnummer)

        # MwSt. auf Positionsebene (muss angegeben werden)
        ctax = _sub(item, f"{CAC}ClassifiedTaxCategory")
        _sub(ctax, f"{CBC}ID", _mwst_kategorie(pos.mwst_prozent or rechnung_mwst))
        _sub(ctax, f"{CBC}Percent", str(pos.mwst_prozent or rechnung_mwst))
        ts = _sub(ctax, f"{CAC}TaxScheme")
        _sub(ts, f"{CBC}ID", "VAT")

        # Preis (BG-29)
        price = _sub(line, f"{CAC}Price")
        _sub(price, f"{CBC}PriceAmount",
             self._fmt_decimal_4(pos.einzelpreis_netto),
             currencyID="EUR")

    def _fmt_decimal(self, val: Decimal) -> str:
        """Formatiert Decimal mit 2 Nachkommastellen für Summen/Beträge."""
        return str(val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    def _fmt_decimal_4(self, val: Decimal) -> str:
        """Formatiert Decimal mit bis zu 4 Nachkommastellen für Preise/Mengen.

        EN 16931 erlaubt für PriceAmount und InvoicedQuantity bis zu 4 Stellen.
        normalize() entfernt überflüssige Nullen (z.B. 1.2500 → 1.25).
        """
        return str(val.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP).normalize())

    # ------------------------------------------------------------------
    # Validierung
    # ------------------------------------------------------------------

    @staticmethod
    def _iban_gueltig(iban: str) -> bool:
        """Prüft eine IBAN mit dem Mod-97-Verfahren (ISO 13616)."""
        iban_clean = iban.replace(" ", "").upper()
        if len(iban_clean) < 5:
            return False
        # Ersten 4 Zeichen ans Ende verschieben
        umgestellt = iban_clean[4:] + iban_clean[:4]
        # Buchstaben in Zahlen umwandeln (A=10, B=11, ..., Z=35)
        numerisch = ""
        for c in umgestellt:
            if c.isdigit():
                numerisch += c
            elif c.isalpha():
                numerisch += str(ord(c) - ord("A") + 10)
            else:
                return False
        try:
            return int(numerisch) % 97 == 1
        except ValueError:
            return False

    def _validiere_pflichtfelder(self, d: XRechnungDaten) -> str:
        """
        Prüft alle XRechnung-Pflichtfelder VOR der XML-Generierung.
        Gibt eine Fehlermeldung zurück oder '' wenn alles ok.

        Geprüft werden alle Felder, die der KoSIT-Validator als Fehler
        oder Warnung melden würde — so erfährt der Nutzer sofort was fehlt.
        """
        fehler: list[str] = []

        # --- Rechnungsdaten ---
        if not d.rechnungsnummer:
            fehler.append("Rechnungsnummer fehlt.")
        if not d.rechnungsdatum:
            fehler.append("Rechnungsdatum fehlt.")
        if not d.posten:
            fehler.append("Die Rechnung hat keine Positionen.")
        if d.summe_brutto <= Decimal("0"):
            fehler.append("Der Rechnungsbetrag muss größer als 0 sein.")

        # --- Verkäufer (Einstellungen → Firma) ---
        v = d.verkäufer
        if not v.name:
            fehler.append("Firmenname fehlt (Einstellungen → Firma).")
        if not v.strasse:
            fehler.append("Firmenadresse / Straße fehlt (Einstellungen → Firma).")
        if not v.plz or not v.ort:
            fehler.append("PLZ / Ort der Firma fehlt (Einstellungen → Firma).")
        if not v.email:
            fehler.append(
                "E-Mail-Adresse der Firma fehlt (Einstellungen → Firma). "
                "Wird als elektronische Adresse (BT-34) in der XRechnung benötigt."
            )
        if not v.telefon:
            fehler.append("Telefonnummer der Firma fehlt (Pflichtfeld BT-42).")
        if not (v.ust_id or v.steuernummer):
            fehler.append(
                "Steuernummer / USt-ID fehlt (Einstellungen → Firma). "
                "Pflichtfeld für jede XRechnung."
            )
        if not v.bank_iban:
            fehler.append(
                "IBAN fehlt (Einstellungen → Firma → Bankverbindung). "
                "Für SEPA-Überweisung zwingend erforderlich (BR-DE-19)."
            )
        elif not self._iban_gueltig(v.bank_iban):
            fehler.append(
                f"IBAN '{v.bank_iban}' ist ungültig (Prüfziffer fehlgeschlagen). "
                f"Bitte unter Einstellungen → Firma → Bankverbindung korrigieren."
            )

        # --- Käufer ---
        if not d.käufer_name:
            fehler.append("Kundenname fehlt.")

        # Ergebnis: alle Fehler zusammenfassen
        if fehler:
            return "XRechnung kann nicht erstellt werden:\n• " + "\n• ".join(fehler)
        return ""


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
xrechnung_service = XRechnungService()
