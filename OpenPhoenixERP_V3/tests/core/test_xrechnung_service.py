"""
tests/core/test_xrechnung_service.py – Tests für den XRechnungService
======================================================================
Prüft die XML-Generierung nach EN 16931 / UBL 2.1.
"""

import pytest
from decimal import Decimal
from lxml import etree

from core.services.xrechnung_service import (
    XRechnungService, XRechnungDaten, XRechnungPosten,
    VerkäuferInfo, ExportResult,
    _datum_iso, _einheit_code, _mwst_kategorie,
    CAC, CBC,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def service():
    return XRechnungService()


@pytest.fixture
def verkäufer():
    return VerkäuferInfo(
        name="Muster GmbH",
        strasse="Musterstraße 1",
        plz="12345",
        ort="Berlin",
        steuernummer="",
        ust_id="DE123456789",
        email="info@muster.de",
        telefon="+49 30 123456",
        bank_iban="DE89370400440532013000",
        bank_bic="COBADEFFXXX",
    )


@pytest.fixture
def posten():
    return [
        XRechnungPosten(
            position=1,
            artikelnummer="ART-001",
            beschreibung="Beratungsleistung",
            menge=Decimal("10"),
            einheit="HUR",
            einzelpreis_netto=Decimal("95.00"),
            gesamtpreis_netto=Decimal("950.00"),
            mwst_prozent=Decimal("19"),
        ),
        XRechnungPosten(
            position=2,
            artikelnummer="ART-002",
            beschreibung="Softwarelizenz",
            menge=Decimal("1"),
            einheit="C62",
            einzelpreis_netto=Decimal("299.00"),
            gesamtpreis_netto=Decimal("299.00"),
            mwst_prozent=Decimal("19"),
        ),
    ]


@pytest.fixture
def xdaten(verkäufer, posten):
    return XRechnungDaten(
        rechnungsnummer="2025-0001",
        rechnungsdatum="15.01.2025",
        faelligkeitsdatum="29.01.2025",
        leitweg_id="info@kunde.de",
        verkäufer=verkäufer,
        käufer_name="Beispiel AG",
        käufer_strasse="Beispielweg 5",
        käufer_plz="54321",
        käufer_ort="Hamburg",
        käufer_email="info@kunde.de",
        mwst_prozent=Decimal("19"),
        summe_netto=Decimal("1249.00"),
        summe_mwst=Decimal("237.31"),
        summe_brutto=Decimal("1486.31"),
        posten=posten,
    )


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

class TestHilfsfunktionen:
    def test_datum_iso_korrekt(self):
        assert _datum_iso("15.01.2025") == "2025-01-15"
        assert _datum_iso("01.12.2024") == "2024-12-01"

    def test_datum_iso_ungueltig(self):
        # Gibt den Eingabewert zurück bei ungültigem Format
        result = _datum_iso("kein-datum")
        assert result == "kein-datum"

    def test_einheit_code_stueck(self):
        assert _einheit_code("Stück") == "C62"
        assert _einheit_code("stk") == "C62"
        assert _einheit_code("STK") == "C62"

    def test_einheit_code_stunde(self):
        assert _einheit_code("Stunde") == "HUR"
        assert _einheit_code("Std") == "HUR"
        assert _einheit_code("h") == "HUR"

    def test_einheit_code_kg(self):
        assert _einheit_code("kg") == "KGM"

    def test_einheit_code_fallback(self):
        # Unbekannte Einheit → C62 (Stück)
        assert _einheit_code("Schachtel") == "C62"

    def test_mwst_kategorie_standard(self):
        assert _mwst_kategorie(Decimal("19")) == "S"
        assert _mwst_kategorie(Decimal("7")) == "S"

    def test_mwst_kategorie_null(self):
        assert _mwst_kategorie(Decimal("0")) == "Z"


# ---------------------------------------------------------------------------
# XML-Erstellung
# ---------------------------------------------------------------------------

class TestXMLErstellung:
    def test_xml_ist_valid_xml(self, service, xdaten):
        xml_bytes = service._xml_erstellen(xdaten)
        # Darf keinen Parse-Fehler werfen
        root = etree.fromstring(xml_bytes)
        assert root is not None

    def test_spezifikations_id(self, service, xdaten):
        xml_bytes = service._xml_erstellen(xdaten)
        root = etree.fromstring(xml_bytes)
        spec = root.find(f"{CBC}CustomizationID")
        assert spec is not None
        assert "xrechnung_3.0" in spec.text

    def test_rechnungsnummer(self, service, xdaten):
        xml_bytes = service._xml_erstellen(xdaten)
        root = etree.fromstring(xml_bytes)
        invoice_id = root.find(f"{CBC}ID")
        assert invoice_id.text == "2025-0001"

    def test_rechnungsdatum_iso(self, service, xdaten):
        xml_bytes = service._xml_erstellen(xdaten)
        root = etree.fromstring(xml_bytes)
        datum = root.find(f"{CBC}IssueDate")
        assert datum.text == "2025-01-15"

    def test_faelligkeitsdatum_iso(self, service, xdaten):
        xml_bytes = service._xml_erstellen(xdaten)
        root = etree.fromstring(xml_bytes)
        due = root.find(f"{CBC}DueDate")
        assert due.text == "2025-01-29"

    def test_rechnungstyp_380(self, service, xdaten):
        xml_bytes = service._xml_erstellen(xdaten)
        root = etree.fromstring(xml_bytes)
        typ = root.find(f"{CBC}InvoiceTypeCode")
        assert typ.text == "380"

    def test_waehrung_eur(self, service, xdaten):
        xml_bytes = service._xml_erstellen(xdaten)
        root = etree.fromstring(xml_bytes)
        waehrung = root.find(f"{CBC}DocumentCurrencyCode")
        assert waehrung.text == "EUR"

    def test_leitweg_id(self, service, xdaten):
        xml_bytes = service._xml_erstellen(xdaten)
        root = etree.fromstring(xml_bytes)
        ref = root.find(f"{CBC}BuyerReference")
        assert ref.text == "info@kunde.de"

    def test_verkaeufer_name(self, service, xdaten):
        xml_bytes = service._xml_erstellen(xdaten)
        root = etree.fromstring(xml_bytes)
        supplier = root.find(f"{CAC}AccountingSupplierParty")
        party = supplier.find(f"{CAC}Party")
        pname = party.find(f"{CAC}PartyName/{CBC}Name")
        assert pname.text == "Muster GmbH"

    def test_verkaeufer_ustid(self, service, xdaten):
        xml_bytes = service._xml_erstellen(xdaten)
        root = etree.fromstring(xml_bytes)
        supplier = root.find(f"{CAC}AccountingSupplierParty")
        party = supplier.find(f"{CAC}Party")
        tax = party.find(f"{CAC}PartyTaxScheme/{CBC}CompanyID")
        assert tax.text == "DE123456789"

    def test_kaeufer_name(self, service, xdaten):
        xml_bytes = service._xml_erstellen(xdaten)
        root = etree.fromstring(xml_bytes)
        customer = root.find(f"{CAC}AccountingCustomerParty")
        party = customer.find(f"{CAC}Party")
        pname = party.find(f"{CAC}PartyName/{CBC}Name")
        assert pname.text == "Beispiel AG"

    def test_gesamtbetrag(self, service, xdaten):
        xml_bytes = service._xml_erstellen(xdaten)
        root = etree.fromstring(xml_bytes)
        total = root.find(f"{CAC}LegalMonetaryTotal/{CBC}PayableAmount")
        assert Decimal(total.text) == Decimal("1486.31")

    def test_steuergesamt(self, service, xdaten):
        xml_bytes = service._xml_erstellen(xdaten)
        root = etree.fromstring(xml_bytes)
        tax_amount = root.find(f"{CAC}TaxTotal/{CBC}TaxAmount")
        assert Decimal(tax_amount.text) == Decimal("237.31")

    def test_positionen_vorhanden(self, service, xdaten):
        xml_bytes = service._xml_erstellen(xdaten)
        root = etree.fromstring(xml_bytes)
        ns = {"cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"}
        lines = root.findall(f"{CAC}InvoiceLine")
        assert len(lines) == 2

    def test_position_beschreibung(self, service, xdaten):
        xml_bytes = service._xml_erstellen(xdaten)
        root = etree.fromstring(xml_bytes)
        lines = root.findall(f"{CAC}InvoiceLine")
        beschr = lines[0].find(f"{CAC}Item/{CBC}Description")
        assert beschr.text == "Beratungsleistung"

    def test_position_menge(self, service, xdaten):
        xml_bytes = service._xml_erstellen(xdaten)
        root = etree.fromstring(xml_bytes)
        lines = root.findall(f"{CAC}InvoiceLine")
        menge = lines[0].find(f"{CBC}InvoicedQuantity")
        assert Decimal(menge.text) == Decimal("10")
        assert menge.get("unitCode") == "HUR"

    def test_position_einzelpreis(self, service, xdaten):
        xml_bytes = service._xml_erstellen(xdaten)
        root = etree.fromstring(xml_bytes)
        lines = root.findall(f"{CAC}InvoiceLine")
        preis = lines[0].find(f"{CAC}Price/{CBC}PriceAmount")
        assert Decimal(preis.text) == Decimal("95.00")

    def test_encoding_utf8(self, service, xdaten):
        xml_bytes = service._xml_erstellen(xdaten)
        assert xml_bytes.startswith(b"<?xml")
        assert b"UTF-8" in xml_bytes[:50]

    def test_bankdaten_in_xml(self, service, xdaten):
        xml_bytes = service._xml_erstellen(xdaten)
        root = etree.fromstring(xml_bytes)
        iban = root.find(
            f"{CAC}PaymentMeans/{CAC}PayeeFinancialAccount/{CBC}ID"
        )
        assert iban is not None
        assert iban.text == "DE89370400440532013000"


# ---------------------------------------------------------------------------
# Validierung
# ---------------------------------------------------------------------------

class TestValidierung:
    def test_fehlende_rechnungsnummer(self, service, xdaten):
        xdaten.rechnungsnummer = ""
        fehler = service._validiere_pflichtfelder(xdaten)
        assert fehler != ""

    def test_fehlender_verkaeufer_name(self, service, xdaten):
        xdaten.verkäufer.name = ""
        fehler = service._validiere_pflichtfelder(xdaten)
        assert "Firmenname" in fehler

    def test_fehlende_steuer(self, service, xdaten):
        xdaten.verkäufer.ust_id = ""
        xdaten.verkäufer.steuernummer = ""
        fehler = service._validiere_pflichtfelder(xdaten)
        assert "Steuer" in fehler

    def test_keine_posten(self, service, xdaten):
        xdaten.posten = []
        fehler = service._validiere_pflichtfelder(xdaten)
        assert fehler != ""

    def test_betrag_null(self, service, xdaten):
        xdaten.summe_brutto = Decimal("0")
        fehler = service._validiere_pflichtfelder(xdaten)
        assert fehler != ""

    def test_valide_daten(self, service, xdaten):
        fehler = service._validiere_pflichtfelder(xdaten)
        assert fehler == ""


# ---------------------------------------------------------------------------
# xml_string()
# ---------------------------------------------------------------------------

class TestXMLString:
    def test_xml_string_korrekt(self, service, xdaten):
        xml = service.xml_string(xdaten)
        assert xml.startswith("<?xml")
        assert "2025-0001" in xml
        assert "Muster GmbH" in xml
        assert "Beispiel AG" in xml

    def test_xml_string_wirft_bei_fehler(self, service, xdaten):
        xdaten.rechnungsnummer = ""
        with pytest.raises(ValueError):
            service.xml_string(xdaten)


# ---------------------------------------------------------------------------
# Datums-Konvertierung (Grenzfälle)
# ---------------------------------------------------------------------------

class TestDatumKonvertierung:
    def test_schaltjahr(self):
        assert _datum_iso("29.02.2024") == "2024-02-29"

    def test_jahreswechsel(self):
        assert _datum_iso("31.12.2024") == "2024-12-31"
        assert _datum_iso("01.01.2025") == "2025-01-01"
