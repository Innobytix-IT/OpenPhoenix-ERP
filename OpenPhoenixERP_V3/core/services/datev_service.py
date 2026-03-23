"""
core/services/datev_service.py – DATEV-Export-Service
======================================================
Exportiert Ausgangsrechnungen und Eingangsbelege im DATEV-Buchungsstapel-
Format (CSV). Kompatibel mit DATEV Unternehmen Online und den meisten
Steuerberater-Programmen.

DATEV-Format-Spezifikation:
- Encoding: CP1252 (Windows-1252)
- Trennzeichen: Semikolon (;)
- Dezimaltrennzeichen: Komma (,)
- Header: 2 Zeilen (Kopf-Zeile + Spaltenüberschriften)
- Datumsformat: TTMM (4-stellig, ohne Trennzeichen)
- Beträge: immer positiv, Soll/Haben bestimmt die Buchungsrichtung
"""

import csv
import io
import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from core.config import config
from core.models import Rechnung, EingangsRechnung

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Konstanten — DATEV-Kontenrahmen SKR03 (Standard für Kleinbetriebe)
# ---------------------------------------------------------------------------

# Erlöskonten (Ausgangsrechnungen)
ERLOES_19 = "8400"       # Erlöse 19% USt
ERLOES_7  = "8300"       # Erlöse 7% USt
ERLOES_0  = "8100"       # Steuerfreie Erlöse

# Aufwandskonten (Eingangsrechnungen — Kategorie-Mapping)
AUFWAND_KONTEN = {
    "Material":      "3400",   # Wareneingang 19% Vorsteuer
    "Kraftstoff":    "6530",   # Laufende Kfz-Betriebskosten
    "Bürobedarf":    "6815",   # Bürobedarf
    "Werkzeug":      "6845",   # Werkzeuge und Kleingeräte
    "Versicherung":  "6400",   # Versicherungen
    "Miete":         "6310",   # Miete (Grundstücke / Gebäude)
    "Sonstiges":     "6300",   # Sonstige betriebliche Aufwendungen
}
AUFWAND_DEFAULT = "6300"

# Debitoren/Kreditoren-Bereiche
DEBITOREN_START = 10000   # Debitor-Kontonummern ab 10000
KREDITOREN_KONTO = "70000"  # Sammel-Kreditorkonto für Eingangsrechnungen


# ---------------------------------------------------------------------------
# Datenklassen
# ---------------------------------------------------------------------------

@dataclass
class DatevBuchung:
    """Eine einzelne Buchungszeile im DATEV-Format."""
    umsatz: Decimal         # Betrag (immer positiv)
    soll_haben: str         # "S" oder "H"
    konto: str              # Konto (Debitor/Kreditor oder Sachkonto)
    gegenkonto: str         # Gegenkonto
    belegdatum: str         # TTMM (4-stellig)
    belegnummer: str        # Rechnungs-/Belegnummer
    buchungstext: str       # Beschreibung
    steuerschluessel: str   # DATEV-Steuerschlüssel
    kostenstelle1: str = "" # Optional: Kostenstelle 1
    kostenstelle2: str = "" # Optional: Kostenstelle 2


@dataclass
class DatevExportResult:
    """Ergebnis eines DATEV-Exports."""
    csv_bytes: bytes
    dateiname: str
    anzahl_buchungen: int
    zeitraum_von: str
    zeitraum_bis: str
    summe_ar: Decimal       # Ausgangsrechnungen
    summe_er: Decimal       # Eingangsrechnungen/Belege


# ---------------------------------------------------------------------------
# DATEV-Steuerschlüssel
# ---------------------------------------------------------------------------

def _steuerschluessel_ar(mwst_prozent: Decimal) -> str:
    """Steuerschlüssel für Ausgangsrechnungen (Erlöse)."""
    if mwst_prozent == Decimal("19.00") or mwst_prozent == Decimal("19"):
        return "3"    # USt 19%
    elif mwst_prozent == Decimal("7.00") or mwst_prozent == Decimal("7"):
        return "2"    # USt 7%
    elif mwst_prozent == Decimal("0") or mwst_prozent == Decimal("0.00"):
        return "0"    # Steuerfrei
    else:
        return "3"    # Fallback: 19%


def _steuerschluessel_er(mwst_satz: Decimal) -> str:
    """Steuerschlüssel für Eingangsrechnungen (Vorsteuer)."""
    if mwst_satz == Decimal("19.00") or mwst_satz == Decimal("19"):
        return "9"    # VSt 19%
    elif mwst_satz == Decimal("7.00") or mwst_satz == Decimal("7"):
        return "8"    # VSt 7%
    elif mwst_satz == Decimal("0") or mwst_satz == Decimal("0.00"):
        return "0"    # Steuerfrei
    else:
        return "9"    # Fallback: 19%


def _erloeskonto(mwst_prozent: Decimal) -> str:
    """Ordnet den MwSt-Satz dem richtigen Erlöskonto zu."""
    if mwst_prozent == Decimal("19.00") or mwst_prozent == Decimal("19"):
        return ERLOES_19
    elif mwst_prozent == Decimal("7.00") or mwst_prozent == Decimal("7"):
        return ERLOES_7
    elif mwst_prozent == Decimal("0") or mwst_prozent == Decimal("0.00"):
        return ERLOES_0
    return ERLOES_19


def _aufwandskonto(kategorie: str) -> str:
    """Ordnet die Belegkategorie dem richtigen Aufwandskonto zu."""
    return AUFWAND_KONTEN.get(kategorie, AUFWAND_DEFAULT)


def _debitor_konto(kunde_id: int) -> str:
    """Generiert eine Debitor-Kontonummer aus der Kunden-ID.

    Begrenzt auf den 5-stelligen DATEV-Bereich (10000–99999).
    Bei Überlauf wird die Kunden-ID modular gemappt.
    """
    konto = DEBITOREN_START + kunde_id
    if konto > 99999:
        konto = DEBITOREN_START + (kunde_id % 90000)
        logger.warning(
            f"Debitor-Konto für Kunde {kunde_id} würde 5-stelligen Bereich "
            f"überschreiten. Modular-Mapping auf Konto {konto}."
        )
    return str(konto)


def _datum_ttmm(datum_str: str) -> str:
    """Konvertiert TT.MM.JJJJ zu TTMM (DATEV-Format)."""
    try:
        parts = datum_str.strip().split(".")
        return f"{int(parts[0]):02d}{int(parts[1]):02d}"
    except (ValueError, IndexError):
        return "0101"


def _format_betrag(betrag: Decimal) -> str:
    """Formatiert einen Betrag für DATEV: immer positiv, Komma als Dezimaltrennzeichen."""
    wert = abs(betrag).quantize(Decimal("0.01"))
    return str(wert).replace(".", ",")


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class DatevService:
    """
    Erstellt DATEV-konforme CSV-Exporte (Buchungsstapel).

    Unterstützte Buchungstypen:
    - Ausgangsrechnungen (finalisiert, im Zeitraum)
    - Eingangsrechnungen / Belege (im Zeitraum)
    - Stornos / Gutschriften
    """

    def exportieren(
        self,
        session: Session,
        von: str,
        bis: str,
        include_ar: bool = True,
        include_er: bool = True,
    ) -> DatevExportResult:
        """
        Erstellt einen DATEV-Export für den angegebenen Zeitraum.

        Args:
            session:    SQLAlchemy-Session
            von:        Startdatum (TT.MM.JJJJ)
            bis:        Enddatum (TT.MM.JJJJ)
            include_ar: Ausgangsrechnungen einbeziehen
            include_er: Eingangsrechnungen/Belege einbeziehen

        Returns:
            DatevExportResult mit CSV-Bytes und Metadaten
        """
        buchungen: list[DatevBuchung] = []
        summe_ar = Decimal("0")
        summe_er = Decimal("0")

        if include_ar:
            ar_buchungen, summe_ar = self._ausgangsrechnungen(session, von, bis)
            buchungen.extend(ar_buchungen)

        if include_er:
            er_buchungen, summe_er = self._eingangsrechnungen(session, von, bis)
            buchungen.extend(er_buchungen)

        # Sortierung nach Belegdatum
        buchungen.sort(key=lambda b: b.belegdatum)

        # CSV generieren
        csv_bytes = self._csv_erstellen(buchungen, von, bis)

        # Dateiname
        von_fmt = von.replace(".", "")
        bis_fmt = bis.replace(".", "")
        dateiname = f"DATEV_Export_{von_fmt}_{bis_fmt}.csv"

        logger.info(
            f"DATEV-Export erstellt: {len(buchungen)} Buchungen, "
            f"AR={summe_ar}, ER={summe_er}, Zeitraum {von}–{bis}"
        )

        return DatevExportResult(
            csv_bytes=csv_bytes,
            dateiname=dateiname,
            anzahl_buchungen=len(buchungen),
            zeitraum_von=von,
            zeitraum_bis=bis,
            summe_ar=summe_ar,
            summe_er=summe_er,
        )

    # ------------------------------------------------------------------
    # Ausgangsrechnungen
    # ------------------------------------------------------------------

    def _ausgangsrechnungen(
        self, session: Session, von: str, bis: str
    ) -> tuple[list[DatevBuchung], Decimal]:
        """Liest finalisierte Ausgangsrechnungen im Zeitraum."""
        buchungen: list[DatevBuchung] = []
        summe = Decimal("0")

        # Datum-Parsing für Vergleich
        try:
            von_dt = datetime.strptime(von, "%d.%m.%Y")
            bis_dt = datetime.strptime(bis, "%d.%m.%Y")
        except (ValueError, TypeError):
            logger.error(f"Ungültiges Datum: von={von}, bis={bis}")
            return buchungen, summe

        # Alle finalisierten Rechnungen laden
        rechnungen = (
            session.query(Rechnung)
            .filter(Rechnung.is_finalized.is_(True))
            .all()
        )

        for r in rechnungen:
            # Datum prüfen (Format: TT.MM.JJJJ)
            try:
                r_dt = datetime.strptime(r.rechnungsdatum, "%d.%m.%Y")
            except (ValueError, TypeError):
                logger.warning(
                    f"Rechnung {r.rechnungsnummer}: ungültiges Datum '{r.rechnungsdatum}'"
                )
                continue

            if not (von_dt <= r_dt <= bis_dt):
                continue

            # Kundendaten für Buchungstext
            kunde = r.kunde
            kundenname = kunde.display_name if kunde else "Unbekannt"
            debitor = _debitor_konto(r.kunde_id) if kunde else "10000"

            brutto = r.summe_brutto or Decimal("0")
            if brutto == 0:
                continue

            # Storno / Gutschrift?
            ist_storno = r.rechnungsnummer.startswith("S-")

            if ist_storno:
                # Gutschrift: Haben an Debitor
                buchungen.append(DatevBuchung(
                    umsatz=abs(brutto),
                    soll_haben="H",
                    konto=debitor,
                    gegenkonto=_erloeskonto(r.mwst_prozent),
                    belegdatum=_datum_ttmm(r.rechnungsdatum),
                    belegnummer=r.rechnungsnummer,
                    buchungstext=f"Gutschrift {r.rechnungsnummer} {kundenname}",
                    steuerschluessel=_steuerschluessel_ar(r.mwst_prozent),
                ))
            else:
                # Normale Rechnung: Soll an Debitor
                buchungen.append(DatevBuchung(
                    umsatz=brutto,
                    soll_haben="S",
                    konto=debitor,
                    gegenkonto=_erloeskonto(r.mwst_prozent),
                    belegdatum=_datum_ttmm(r.rechnungsdatum),
                    belegnummer=r.rechnungsnummer,
                    buchungstext=f"RE {r.rechnungsnummer} {kundenname}",
                    steuerschluessel=_steuerschluessel_ar(r.mwst_prozent),
                ))

            summe += brutto

        return buchungen, summe

    # ------------------------------------------------------------------
    # Eingangsrechnungen / Belege
    # ------------------------------------------------------------------

    def _eingangsrechnungen(
        self, session: Session, von: str, bis: str
    ) -> tuple[list[DatevBuchung], Decimal]:
        """Liest Eingangsrechnungen/Belege im Zeitraum."""
        buchungen: list[DatevBuchung] = []
        summe = Decimal("0")

        try:
            von_dt = datetime.strptime(von, "%d.%m.%Y")
            bis_dt = datetime.strptime(bis, "%d.%m.%Y")
        except (ValueError, TypeError):
            logger.error(f"Ungültiges Datum: von={von}, bis={bis}")
            return buchungen, summe

        belege = (
            session.query(EingangsRechnung)
            .filter(EingangsRechnung.is_active.is_(True))
            .all()
        )

        for b in belege:
            try:
                b_dt = datetime.strptime(b.datum, "%d.%m.%Y")
            except (ValueError, TypeError):
                logger.warning(
                    f"Beleg {b.belegnummer or b.id}: ungültiges Datum '{b.datum}'"
                )
                continue

            if not (von_dt <= b_dt <= bis_dt):
                continue

            brutto = b.betrag_brutto or Decimal("0")
            if brutto == 0:
                continue

            aufwandskonto = _aufwandskonto(b.kategorie)
            beleg_nr = b.belegnummer or f"ER-{b.id}"

            buchungen.append(DatevBuchung(
                umsatz=brutto,
                soll_haben="S",
                konto=aufwandskonto,
                gegenkonto=KREDITOREN_KONTO,
                belegdatum=_datum_ttmm(b.datum),
                belegnummer=beleg_nr,
                buchungstext=f"ER {beleg_nr} {b.lieferant}",
                steuerschluessel=_steuerschluessel_er(b.mwst_satz),
            ))

            summe += brutto

        return buchungen, summe

    # ------------------------------------------------------------------
    # CSV-Generierung (DATEV-Buchungsstapel-Format)
    # ------------------------------------------------------------------

    def _csv_erstellen(
        self,
        buchungen: list[DatevBuchung],
        von: str,
        bis: str,
    ) -> bytes:
        """
        Erstellt eine DATEV-konforme CSV-Datei (Buchungsstapel).

        Zeile 1: Header mit Metadaten
        Zeile 2: Spaltenüberschriften
        Zeile 3+: Buchungsdaten
        """
        firma = config.get("company", "name", "OpenPhoenix")
        berater_nr = "1001"      # Standard-Beraternummer
        mandanten_nr = "1"       # Standard-Mandantennummer

        # Geschäftsjahr aus Zeitraum ableiten
        try:
            gj_beginn = datetime.strptime(von, "%d.%m.%Y")
            gj_ende = datetime.strptime(bis, "%d.%m.%Y")
        except (ValueError, TypeError):
            gj_beginn = datetime(datetime.now().year, 1, 1)
            gj_ende = datetime(datetime.now().year, 12, 31)

        wj_beginn = f"{gj_beginn.year}0101"
        sachkonten_laenge = 4    # SKR03/04: 4-stellige Sachkonten

        buf = io.StringIO()
        writer = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_MINIMAL)

        # ----- Zeile 1: DATEV-Header -----
        # Format: EXTF; Versionsnummer; Kategorie; Formatname; Formatversion;
        #         Erzeugt; Importiert; Herkunft; Exportiert_von; Importiert_von;
        #         Berater; Mandant; WJ-Beginn; Sachkontenlänge; Datum_von; Datum_bis;
        #         Bezeichnung; Diktatzeichen; Buchungstyp; Rechnungslegungszweck;
        #         Festschreibung; WKZ
        header = [
            "EXTF",        # Kennung: externes Format
            700,           # Versionsnummer
            21,            # Kategorie: Buchungsstapel
            "Buchungsstapel",
            12,            # Formatversion
            datetime.now().strftime("%Y%m%d%H%M%S") + "000",
            "",            # Importiert (leer)
            "RE",          # Herkunft
            f"OpenPhoenix ERP",
            "",            # Importiert von
            berater_nr,
            mandanten_nr,
            wj_beginn,
            sachkonten_laenge,
            gj_beginn.strftime("%Y%m%d"),
            gj_ende.strftime("%Y%m%d"),
            f"Export {von} - {bis}",
            "",            # Diktatzeichen
            1,             # Buchungstyp: 1 = Finanzbuchhaltung
            0,             # Rechnungslegungszweck
            0,             # Festschreibung: 0 = nicht festgeschrieben
            "EUR",         # Währungskürzel
            "",            # Reserviert
            "",            # Derivatskennzeichen
            "",            # Reserviert
            "",            # Reserviert
            "",            # SKR
            "",            # Branchen-Lsg-ID
            "",            # Reserviert
            "",            # Reserviert
            "",            # Anwendungsinformation
        ]
        writer.writerow(header)

        # ----- Zeile 2: Spaltenüberschriften -----
        spalten = [
            "Umsatz (ohne Soll/Haben-Kz)",
            "Soll/Haben-Kennzeichen",
            "WKZ Umsatz",
            "Kurs",
            "Basis-Umsatz",
            "WKZ Basis-Umsatz",
            "Konto",
            "Gegenkonto (ohne BU-Schlüssel)",
            "BU-Schlüssel",
            "Belegdatum",
            "Belegfeld 1",
            "Belegfeld 2",
            "Skonto",
            "Buchungstext",
            "Postensperre",
            "Diverse Adressnummer",
            "Geschäftspartnerbank",
            "Sachverhalt",
            "Zinssperre",
            "Beleglink",
            "Beleginfo - Art 1",
            "Beleginfo - Inhalt 1",
            "Beleginfo - Art 2",
            "Beleginfo - Inhalt 2",
            "Beleginfo - Art 3",
            "Beleginfo - Inhalt 3",
            "Beleginfo - Art 4",
            "Beleginfo - Inhalt 4",
            "Beleginfo - Art 5",
            "Beleginfo - Inhalt 5",
            "Beleginfo - Art 6",
            "Beleginfo - Inhalt 6",
            "Beleginfo - Art 7",
            "Beleginfo - Inhalt 7",
            "Beleginfo - Art 8",
            "Beleginfo - Inhalt 8",
            "KOST1 - Kostenstelle",
            "KOST2 - Kostenstelle",
            "Kost-Menge",
            "EU-Land u. UStID",
            "EU-Steuersatz",
            "Abw. Versteuerungsart",
            "Sachverhalt L+L",
            "Funktionsergänzung L+L",
            "BU 49 Hauptfunktionstyp",
            "BU 49 Hauptfunktionsnummer",
            "BU 49 Funktionsergänzung",
            "Zusatzinformation - Art 1",
            "Zusatzinformation - Inhalt 1",
            "Zusatzinformation - Art 2",
            "Zusatzinformation - Inhalt 2",
            "Zusatzinformation - Art 3",
            "Zusatzinformation - Inhalt 3",
            "Zusatzinformation - Art 4",
            "Zusatzinformation - Inhalt 4",
            "Zusatzinformation - Art 5",
            "Zusatzinformation - Inhalt 5",
            "Zusatzinformation - Art 6",
            "Zusatzinformation - Inhalt 6",
            "Zusatzinformation - Art 7",
            "Zusatzinformation - Inhalt 7",
            "Zusatzinformation - Art 8",
            "Zusatzinformation - Inhalt 8",
            "Zusatzinformation - Art 9",
            "Zusatzinformation - Inhalt 9",
            "Zusatzinformation - Art 10",
            "Zusatzinformation - Inhalt 10",
            "Zusatzinformation - Art 11",
            "Zusatzinformation - Inhalt 11",
            "Zusatzinformation - Art 12",
            "Zusatzinformation - Inhalt 12",
            "Zusatzinformation - Art 13",
            "Zusatzinformation - Inhalt 13",
            "Zusatzinformation - Art 14",
            "Zusatzinformation - Inhalt 14",
            "Zusatzinformation - Art 15",
            "Zusatzinformation - Inhalt 15",
            "Zusatzinformation - Art 16",
            "Zusatzinformation - Inhalt 16",
            "Zusatzinformation - Art 17",
            "Zusatzinformation - Inhalt 17",
            "Zusatzinformation - Art 18",
            "Zusatzinformation - Inhalt 18",
            "Zusatzinformation - Art 19",
            "Zusatzinformation - Inhalt 19",
            "Zusatzinformation - Art 20",
            "Zusatzinformation - Inhalt 20",
            "Stück",
            "Gewicht",
            "Zahlweise",
            "Forderungsart",
            "Veranlagungsjahr",
            "Zugeordnete Fälligkeit",
            "Skontotyp",
            "Auftragsnummer",
            "Buchungstyp",
            "USt-Schlüssel (Anzahlungen)",
            "EU-Land (Anzahlungen)",
            "Sachverhalt L+L (Anzahlungen)",
            "EU-Steuersatz (Anzahlungen)",
            "Erlöskonto (Anzahlungen)",
            "Herkunft-Kz",
            "Buchungs GUID",
            "KOST-Datum",
            "SEPA-Mandatsreferenz",
            "Skontosperre",
            "Gesellschaftername",
            "Beteiligtennummer",
            "Identifikationsnummer",
            "Zeichnernummer",
            "Postensperre bis",
            "Bezeichnung SoBil-Sachverhalt",
            "Kennzeichen SoBil-Buchung",
            "Festschreibung",
            "Leistungsdatum",
            "Datum Zuord. Steuerperiode",
            "Fälligkeit",
            "Generalumkehr (GU)",
            "Steuersatz",
            "Land",
        ]
        writer.writerow(spalten)

        # ----- Zeile 3+: Buchungsdaten -----
        for b in buchungen:
            # DATEV erwartet 116 Spalten — wir füllen die relevanten
            zeile = [""] * 116
            zeile[0] = _format_betrag(b.umsatz)      # Umsatz
            zeile[1] = b.soll_haben                    # S/H
            zeile[2] = "EUR"                           # WKZ
            zeile[3] = ""                              # Kurs
            zeile[4] = ""                              # Basis-Umsatz
            zeile[5] = ""                              # WKZ Basis
            zeile[6] = b.konto                         # Konto
            zeile[7] = b.gegenkonto                    # Gegenkonto
            zeile[8] = b.steuerschluessel              # BU-Schlüssel
            zeile[9] = b.belegdatum                    # Belegdatum (TTMM)
            zeile[10] = b.belegnummer[:36]             # Belegfeld 1 (max 36 Zeichen)
            zeile[11] = ""                             # Belegfeld 2
            zeile[12] = ""                             # Skonto
            zeile[13] = b.buchungstext[:60]            # Buchungstext (max 60 Zeichen)
            zeile[14] = ""                             # Postensperre
            zeile[15] = ""                             # Diverse Adressnummer
            # Kostenstellen (Spalte 36+37)
            zeile[36] = b.kostenstelle1
            zeile[37] = b.kostenstelle2

            writer.writerow(zeile)

        # DATEV erwartet CP1252 (Windows-1252) Encoding
        csv_text = buf.getvalue()
        try:
            return csv_text.encode("cp1252")
        except UnicodeEncodeError:
            # Unicode-Normalisierung: z.B. Kombi-Zeichen in vorkombinierte Form
            import unicodedata
            normalized = unicodedata.normalize("NFC", csv_text)
            try:
                return normalized.encode("cp1252")
            except UnicodeEncodeError:
                # Letzte Möglichkeit: nicht darstellbare Zeichen ersetzen und warnen
                logger.warning(
                    "Einige Zeichen konnten nicht in CP1252 kodiert werden "
                    "und wurden durch '?' ersetzt. Bitte Kundendaten prüfen."
                )
                return normalized.encode("cp1252", errors="replace")


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
datev_service = DatevService()
