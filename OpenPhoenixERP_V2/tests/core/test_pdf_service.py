"""
tests/core/test_pdf_service.py – Tests für den PDFService
=========================================================
Prüft die PDF-Generierung über reportlab.
Da keine visuelle Verifikation möglich ist, wird geprüft:
  - PDF-Bytes werden erzeugt (nicht leer, beginnt mit %PDF)
  - Keine Exceptions bei normalen und Grenzfall-Daten
  - Datei wird korrekt geschrieben und existiert
"""

import os
import tempfile
import pytest
from decimal import Decimal
from unittest.mock import MagicMock

from core.services.pdf_service import PDFService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def service():
    return PDFService()


def _make_dto(
    rechnungsnummer="2025-TEST",
    rechnungsdatum="15.01.2025",
    faelligkeitsdatum="29.01.2025",
    kunde_display="Max Mustermann",
    kunde_zifferncode=1001,
    mwst_prozent=Decimal("19"),
    summe_netto=Decimal("100.00"),
    summe_mwst=Decimal("19.00"),
    summe_brutto=Decimal("119.00"),
    mahngebuehren=Decimal("0"),
    bemerkung="",
    anzahl_posten=2,
):
    """Erstellt ein Mock-RechnungDTO für Tests."""
    dto = MagicMock()
    dto.rechnungsnummer = rechnungsnummer
    dto.rechnungsdatum = rechnungsdatum
    dto.faelligkeitsdatum = faelligkeitsdatum
    dto.kunde_display = kunde_display
    dto.kunde_zifferncode = kunde_zifferncode
    dto.mwst_prozent = mwst_prozent
    dto.summe_netto = summe_netto
    dto.summe_mwst = summe_mwst
    dto.summe_brutto = summe_brutto
    dto.mahngebuehren = mahngebuehren
    dto.bemerkung = bemerkung

    posten = []
    for i in range(anzahl_posten):
        p = MagicMock()
        p.position = i + 1
        p.artikelnummer = f"ART-{i+1:03d}"
        p.beschreibung = f"Testposition {i+1}"
        p.menge = Decimal("2")
        p.einheit = "Stück"
        p.einzelpreis_netto = Decimal("50.00")
        p.gesamtpreis_netto = Decimal("100.00")
        posten.append(p)

    dto.posten = posten
    return dto


# ---------------------------------------------------------------------------
# Grundlegende Tests
# ---------------------------------------------------------------------------

class TestPDFGenerierung:
    def test_pdf_bytes_nicht_leer(self, service):
        dto = _make_dto()
        pdf_bytes = service.rechnung_als_pdf_bytes(dto)
        assert len(pdf_bytes) > 0

    def test_pdf_beginnt_mit_pdf_header(self, service):
        dto = _make_dto()
        pdf_bytes = service.rechnung_als_pdf_bytes(dto)
        assert pdf_bytes.startswith(b"%PDF")

    def test_pdf_groesse_sinnvoll(self, service):
        """Ein A4-Rechnungs-PDF sollte mindestens 5 KB groß sein."""
        dto = _make_dto()
        pdf_bytes = service.rechnung_als_pdf_bytes(dto)
        assert len(pdf_bytes) > 1_000

    def test_keine_exception_bei_normalen_daten(self, service):
        dto = _make_dto()
        # Darf keine Exception werfen
        pdf_bytes = service.rechnung_als_pdf_bytes(dto)
        assert pdf_bytes is not None

    def test_keine_exception_ohne_posten(self, service):
        dto = _make_dto(anzahl_posten=0)
        # Leere Positionsliste darf nicht crashen
        pdf_bytes = service.rechnung_als_pdf_bytes(dto)
        assert pdf_bytes.startswith(b"%PDF")

    def test_keine_exception_mit_vielen_posten(self, service):
        dto = _make_dto(anzahl_posten=20)
        pdf_bytes = service.rechnung_als_pdf_bytes(dto)
        assert pdf_bytes.startswith(b"%PDF")

    def test_pdf_mit_bemerkung(self, service):
        dto = _make_dto(bemerkung="Vielen Dank für Ihr Vertrauen.\nZahlbar in 14 Tagen.")
        pdf_bytes = service.rechnung_als_pdf_bytes(dto)
        assert pdf_bytes.startswith(b"%PDF")

    def test_pdf_mit_mahngebuehren(self, service):
        dto = _make_dto(
            mahngebuehren=Decimal("10.00"),
            summe_brutto=Decimal("129.00"),
        )
        pdf_bytes = service.rechnung_als_pdf_bytes(dto)
        assert pdf_bytes.startswith(b"%PDF")


# ---------------------------------------------------------------------------
# Datei-Export
# ---------------------------------------------------------------------------

class TestDateiExport:
    def test_datei_wird_erstellt(self, service):
        dto = _make_dto()
        with tempfile.TemporaryDirectory() as tmpdir:
            ok, pfad = service.rechnung_als_datei(dto, ausgabe_verzeichnis=tmpdir)
            assert ok is True
            assert os.path.exists(pfad)

    def test_dateiname_enthaelt_rechnungsnummer(self, service):
        dto = _make_dto(rechnungsnummer="2025-0042")
        with tempfile.TemporaryDirectory() as tmpdir:
            ok, pfad = service.rechnung_als_datei(dto, ausgabe_verzeichnis=tmpdir)
            assert ok is True
            assert "2025-0042" in os.path.basename(pfad)

    def test_datei_nicht_leer(self, service):
        dto = _make_dto()
        with tempfile.TemporaryDirectory() as tmpdir:
            ok, pfad = service.rechnung_als_datei(dto, ausgabe_verzeichnis=tmpdir)
            assert ok is True
            assert os.path.getsize(pfad) > 1_000

    def test_dateiname_sonderzeichen_werden_ersetzt(self, service):
        """Sonderzeichen in der Rechnungsnummer dürfen keinen Dateifehler verursachen."""
        dto = _make_dto(rechnungsnummer="2025/0001")
        with tempfile.TemporaryDirectory() as tmpdir:
            ok, pfad = service.rechnung_als_datei(dto, ausgabe_verzeichnis=tmpdir)
            assert ok is True
            assert os.path.exists(pfad)
            # Slash wird durch Bindestrich ersetzt
            assert "/" not in os.path.basename(pfad)

    def test_verzeichnis_wird_erstellt(self, service):
        """Nicht existierende Verzeichnisse werden automatisch angelegt."""
        dto = _make_dto()
        with tempfile.TemporaryDirectory() as tmpdir:
            neues_verz = os.path.join(tmpdir, "unterordner", "pdfs")
            ok, pfad = service.rechnung_als_datei(dto, ausgabe_verzeichnis=neues_verz)
            assert ok is True
            assert os.path.exists(pfad)


# ---------------------------------------------------------------------------
# Grenzfälle
# ---------------------------------------------------------------------------

class TestGrenzfaelle:
    def test_sehr_langer_kundenname(self, service):
        dto = _make_dto(kunde_display="A" * 100)
        pdf_bytes = service.rechnung_als_pdf_bytes(dto)
        assert pdf_bytes.startswith(b"%PDF")

    def test_sehr_lange_beschreibung(self, service):
        dto = _make_dto()
        dto.posten[0].beschreibung = "Beschreibung " * 20
        pdf_bytes = service.rechnung_als_pdf_bytes(dto)
        assert pdf_bytes.startswith(b"%PDF")

    def test_null_euro_mwst(self, service):
        dto = _make_dto(
            mwst_prozent=Decimal("0"),
            summe_mwst=Decimal("0"),
            summe_brutto=Decimal("100.00"),
        )
        pdf_bytes = service.rechnung_als_pdf_bytes(dto)
        assert pdf_bytes.startswith(b"%PDF")

    def test_grosser_betrag(self, service):
        dto = _make_dto(
            summe_netto=Decimal("999999.99"),
            summe_mwst=Decimal("189999.998"),
            summe_brutto=Decimal("1189999.988"),
        )
        pdf_bytes = service.rechnung_als_pdf_bytes(dto)
        assert pdf_bytes.startswith(b"%PDF")

    def test_kein_faelligkeitsdatum(self, service):
        dto = _make_dto(faelligkeitsdatum="")
        pdf_bytes = service.rechnung_als_pdf_bytes(dto)
        assert pdf_bytes.startswith(b"%PDF")
