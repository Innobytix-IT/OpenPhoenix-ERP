"""
ui/modules/datev/panel.py – DATEV-Export-Panel
===============================================
Ermöglicht den Export von Buchungsdaten im DATEV-Format (CSV)
für den Steuerberater.

Features:
- Zeitraum wählen (Monat / Quartal / Jahr / Benutzerdefiniert)
- Ausgangsrechnungen + Eingangsbelege exportieren
- Vorschau der enthaltenen Buchungen
- Direkter Datei-Export mit DATEV-konformem Encoding (CP1252)
"""

import logging
import os
import subprocess
import sys
from datetime import datetime, date, timedelta
from decimal import Decimal

from PySide6.QtCore import Qt, QDate
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QComboBox, QScrollArea, QDateEdit, QCheckBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QFileDialog,
)

from core.db.engine import db
from core.services.datev_service import datev_service, DatevExportResult
from ui.components.widgets import SectionTitle, NotificationBanner
from ui.theme.theme import Colors, Fonts, Spacing, Radius, on_theme_changed

logger = logging.getLogger(__name__)


class DatevPanel(QWidget):
    """DATEV-Export Panel — exportiert Buchungsdaten für den Steuerberater."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._last_result: DatevExportResult | None = None
        self._root_layout = None
        self._build_ui()
        on_theme_changed(self._on_theme_changed)

    def _on_theme_changed(self, _mode: str) -> None:
        if self._root_layout is not None:
            while self._root_layout.count():
                item = self._root_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            QWidget().setLayout(self._root_layout)
        self._build_ui()

    # ------------------------------------------------------------------
    # UI aufbauen
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        self._root_layout = root
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        root.addWidget(self._build_header())

        # Banner
        banner_wrap = QWidget()
        bw = QVBoxLayout(banner_wrap)
        bw.setContentsMargins(Spacing.XL, Spacing.SM, Spacing.XL, 0)
        bw.setSpacing(0)
        self._banner = NotificationBanner()
        bw.addWidget(self._banner)
        root.addWidget(banner_wrap)

        # Scroll-Bereich
        scroll = QScrollArea()
        scroll.setObjectName("datevScroll")
        scroll.setStyleSheet(f"#datevScroll {{ background-color: {Colors.BG_APP}; border: none; }}")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        content.setObjectName("datevContent")
        content.setStyleSheet(f"#datevContent {{ background-color: {Colors.BG_APP}; }}")
        self._layout = QVBoxLayout(content)
        self._layout.setContentsMargins(Spacing.XL, Spacing.LG, Spacing.XL, Spacing.XL)
        self._layout.setSpacing(Spacing.LG)

        # Zeitraum-Auswahl
        self._build_zeitraum_section()

        # Optionen
        self._build_optionen_section()

        # Export-Button
        self._build_export_section()

        # Vorschau/Ergebnis
        self._build_vorschau_section()

        self._layout.addStretch()
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setFixedHeight(64)
        header.setStyleSheet(
            f"background-color: {Colors.BG_SURFACE}; "
            f"border-bottom: 1px solid {Colors.BORDER};"
        )
        hl = QHBoxLayout(header)
        hl.setContentsMargins(Spacing.XL, 0, Spacing.XL, 0)

        icon = QLabel("📊")
        icon.setStyleSheet(f"font-size: 22px; background: transparent; border: none;")
        hl.addWidget(icon)

        title = QLabel("DATEV-Export")
        title.setStyleSheet(
            f"font-size: {Fonts.SIZE_XL}pt; font-weight: bold; "
            f"color: {Colors.TEXT_PRIMARY}; background: transparent; border: none;"
        )
        hl.addWidget(title)
        hl.addStretch()

        return header

    def _build_zeitraum_section(self) -> None:
        self._layout.addWidget(SectionTitle("Exportzeitraum"))

        # Schnellauswahl
        row1 = QHBoxLayout()
        row1.setSpacing(Spacing.SM)

        lbl = QLabel("Schnellauswahl:")
        lbl.setStyleSheet(
            f"color: {Colors.TEXT_SECONDARY}; font-weight: bold; "
            f"background: transparent; border: none;"
        )
        row1.addWidget(lbl)

        self._zeitraum_combo = QComboBox()
        self._zeitraum_combo.addItems([
            "Aktueller Monat",
            "Letzter Monat",
            "Aktuelles Quartal",
            "Letztes Quartal",
            "Aktuelles Jahr",
            "Letztes Jahr",
            "Benutzerdefiniert",
        ])
        self._zeitraum_combo.setFixedWidth(220)
        self._zeitraum_combo.currentIndexChanged.connect(self._on_zeitraum_changed)
        row1.addWidget(self._zeitraum_combo)
        row1.addStretch()
        self._layout.addLayout(row1)

        # Datum-Felder
        row2 = QHBoxLayout()
        row2.setSpacing(Spacing.LG)

        # Von
        von_lbl = QLabel("Von:")
        von_lbl.setStyleSheet(
            f"color: {Colors.TEXT_SECONDARY}; background: transparent; border: none;"
        )
        row2.addWidget(von_lbl)

        self._date_von = QDateEdit()
        self._date_von.setCalendarPopup(True)
        self._date_von.setDisplayFormat("dd.MM.yyyy")
        self._date_von.setFixedWidth(150)
        row2.addWidget(self._date_von)

        # Bis
        bis_lbl = QLabel("Bis:")
        bis_lbl.setStyleSheet(
            f"color: {Colors.TEXT_SECONDARY}; background: transparent; border: none;"
        )
        row2.addWidget(bis_lbl)

        self._date_bis = QDateEdit()
        self._date_bis.setCalendarPopup(True)
        self._date_bis.setDisplayFormat("dd.MM.yyyy")
        self._date_bis.setFixedWidth(150)
        row2.addWidget(self._date_bis)

        row2.addStretch()
        self._layout.addLayout(row2)

        # Initial: Aktueller Monat
        self._on_zeitraum_changed(0)

    def _build_optionen_section(self) -> None:
        self._layout.addWidget(SectionTitle("Exportumfang"))

        row = QHBoxLayout()
        row.setSpacing(Spacing.XL)

        self._chk_ar = QCheckBox("Ausgangsrechnungen (Erlöse)")
        self._chk_ar.setChecked(True)
        self._chk_ar.setStyleSheet(
            f"color: {Colors.TEXT_PRIMARY}; background: transparent; border: none; "
            f"spacing: 8px;"
        )
        row.addWidget(self._chk_ar)

        self._chk_er = QCheckBox("Eingangsrechnungen / Belege (Aufwand)")
        self._chk_er.setChecked(True)
        self._chk_er.setStyleSheet(
            f"color: {Colors.TEXT_PRIMARY}; background: transparent; border: none; "
            f"spacing: 8px;"
        )
        row.addWidget(self._chk_er)

        row.addStretch()
        self._layout.addLayout(row)

        # Kontenrahmen-Info
        info = QLabel(
            "Kontenrahmen: SKR03 (Standard) — "
            "Debitoren ab 10000, Sachkonten 4-stellig"
        )
        info.setStyleSheet(
            f"color: {Colors.TEXT_DISABLED}; font-size: {Fonts.SIZE_SM}pt; "
            f"background: transparent; border: none;"
        )
        info.setWordWrap(True)
        self._layout.addWidget(info)

    def _build_export_section(self) -> None:
        row = QHBoxLayout()
        row.setSpacing(Spacing.MD)

        # Vorschau generieren
        btn_vorschau = QPushButton("🔍  Vorschau generieren")
        btn_vorschau.setProperty("role", "secondary")
        btn_vorschau.clicked.connect(self._vorschau_generieren)
        row.addWidget(btn_vorschau)

        # Export starten
        btn_export = QPushButton("📊  DATEV-Export speichern")
        btn_export.clicked.connect(self._export_speichern)
        row.addWidget(btn_export)

        row.addStretch()
        self._layout.addLayout(row)

    def _build_vorschau_section(self) -> None:
        self._layout.addWidget(SectionTitle("Vorschau / Ergebnis"))

        # Zusammenfassung
        self._summary_frame = QFrame()
        self._summary_frame.setObjectName("datevSummary")
        self._summary_frame.setStyleSheet(
            f"#datevSummary {{ "
            f"  background-color: {Colors.BG_SURFACE}; "
            f"  border: 1px solid {Colors.BORDER}; "
            f"  border-radius: {Radius.MD}px; "
            f"  padding: {Spacing.MD}px; "
            f"}}"
        )
        summary_layout = QVBoxLayout(self._summary_frame)
        summary_layout.setSpacing(Spacing.SM)

        self._lbl_status = QLabel("Noch kein Export erstellt. Klicken Sie auf 'Vorschau generieren'.")
        self._lbl_status.setStyleSheet(
            f"color: {Colors.TEXT_SECONDARY}; font-size: {Fonts.SIZE_BASE}pt; "
            f"background: transparent; border: none;"
        )
        self._lbl_status.setWordWrap(True)
        summary_layout.addWidget(self._lbl_status)

        # Detail-Labels (initial versteckt)
        self._detail_labels: list[QLabel] = []
        for _ in range(5):
            lbl = QLabel("")
            lbl.setStyleSheet(
                f"color: {Colors.TEXT_PRIMARY}; font-size: {Fonts.SIZE_BASE}pt; "
                f"background: transparent; border: none;"
            )
            lbl.setVisible(False)
            summary_layout.addWidget(lbl)
            self._detail_labels.append(lbl)

        self._layout.addWidget(self._summary_frame)

        # Buchungs-Tabelle
        self._table = QTableWidget()
        self._table.setColumnCount(7)
        self._table.setHorizontalHeaderLabels([
            "Datum", "Beleg-Nr.", "Buchungstext", "Konto",
            "Gegenkonto", "S/H", "Betrag",
        ])
        self._table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setMinimumHeight(200)
        self._table.setVisible(False)
        self._layout.addWidget(self._table)

    # ------------------------------------------------------------------
    # Zeitraum-Logik
    # ------------------------------------------------------------------

    def _on_zeitraum_changed(self, index: int) -> None:
        """Setzt Von/Bis-Datum basierend auf der Schnellauswahl."""
        heute = date.today()
        jahr = heute.year
        monat = heute.month

        if index == 0:  # Aktueller Monat
            von = date(jahr, monat, 1)
            # Letzter Tag des Monats
            if monat == 12:
                bis = date(jahr, 12, 31)
            else:
                bis = date(jahr, monat + 1, 1).replace(day=1)
                bis = bis.replace(day=1) - timedelta(days=1)

        elif index == 1:  # Letzter Monat
            if monat == 1:
                von = date(jahr - 1, 12, 1)
                bis = date(jahr - 1, 12, 31)
            else:
                von = date(jahr, monat - 1, 1)
                bis = date(jahr, monat, 1) - timedelta(days=1)

        elif index == 2:  # Aktuelles Quartal
            q_start = ((monat - 1) // 3) * 3 + 1
            von = date(jahr, q_start, 1)
            q_end_month = q_start + 2
            if q_end_month == 12:
                bis = date(jahr, 12, 31)
            else:
                bis = date(jahr, q_end_month + 1, 1) - timedelta(days=1)

        elif index == 3:  # Letztes Quartal
            q_start = ((monat - 1) // 3) * 3 + 1
            if q_start == 1:
                von = date(jahr - 1, 10, 1)
                bis = date(jahr - 1, 12, 31)
            else:
                q_prev = q_start - 3
                von = date(jahr, q_prev, 1)
                bis = date(jahr, q_start, 1) - timedelta(days=1)

        elif index == 4:  # Aktuelles Jahr
            von = date(jahr, 1, 1)
            bis = date(jahr, 12, 31)

        elif index == 5:  # Letztes Jahr
            von = date(jahr - 1, 1, 1)
            bis = date(jahr - 1, 12, 31)

        else:  # Benutzerdefiniert → nichts ändern
            return

        self._date_von.setDate(QDate(von.year, von.month, von.day))
        self._date_bis.setDate(QDate(bis.year, bis.month, bis.day))

    # ------------------------------------------------------------------
    # Export-Logik
    # ------------------------------------------------------------------

    def _get_zeitraum(self) -> tuple[str, str]:
        """Gibt Von/Bis als TT.MM.JJJJ-Strings zurück."""
        von = self._date_von.date().toString("dd.MM.yyyy")
        bis = self._date_bis.date().toString("dd.MM.yyyy")
        return von, bis

    def _vorschau_generieren(self) -> None:
        """Erstellt eine Vorschau des Exports."""
        von, bis = self._get_zeitraum()
        include_ar = self._chk_ar.isChecked()
        include_er = self._chk_er.isChecked()

        if not include_ar and not include_er:
            self._banner.show_error(
                "Bitte mindestens Ausgangs- oder Eingangsrechnungen auswählen."
            )
            return

        try:
            with db.session() as session:
                result = datev_service.exportieren(
                    session, von, bis,
                    include_ar=include_ar,
                    include_er=include_er,
                )
            self._last_result = result
            self._zeige_ergebnis(result)

            if result.anzahl_buchungen == 0:
                self._banner.show_warning(
                    f"Keine Buchungen im Zeitraum {von} – {bis} gefunden."
                )
            else:
                self._banner.show_success(
                    f"Vorschau erstellt: {result.anzahl_buchungen} Buchungen gefunden."
                )
        except Exception as e:
            logger.exception(f"DATEV-Vorschau fehlgeschlagen: {e}")
            self._banner.show_error(f"Fehler bei der Vorschau: {e}")

    def _export_speichern(self) -> None:
        """Speichert den DATEV-Export als CSV-Datei."""
        von, bis = self._get_zeitraum()
        include_ar = self._chk_ar.isChecked()
        include_er = self._chk_er.isChecked()

        if not include_ar and not include_er:
            self._banner.show_error(
                "Bitte mindestens Ausgangs- oder Eingangsrechnungen auswählen."
            )
            return

        try:
            with db.session() as session:
                result = datev_service.exportieren(
                    session, von, bis,
                    include_ar=include_ar,
                    include_er=include_er,
                )

            if result.anzahl_buchungen == 0:
                self._banner.show_warning(
                    f"Keine Buchungen im Zeitraum {von} – {bis}. "
                    f"Nichts zu exportieren."
                )
                return

            # Datei-Dialog
            pfad, _ = QFileDialog.getSaveFileName(
                self,
                "DATEV-Export speichern",
                result.dateiname,
                "CSV-Dateien (*.csv);;Alle Dateien (*)",
            )

            if not pfad:
                return

            # Datei schreiben
            with open(pfad, "wb") as f:
                f.write(result.csv_bytes)

            self._last_result = result
            self._zeige_ergebnis(result)
            self._banner.show_success(
                f"DATEV-Export gespeichert: {os.path.basename(pfad)} "
                f"({result.anzahl_buchungen} Buchungen)"
            )

            # Ordner öffnen
            self._oeffne_ordner(os.path.dirname(pfad))

        except Exception as e:
            logger.exception(f"DATEV-Export fehlgeschlagen: {e}")
            self._banner.show_error(f"Fehler beim Export: {e}")

    # ------------------------------------------------------------------
    # Ergebnis-Anzeige
    # ------------------------------------------------------------------

    def _zeige_ergebnis(self, result: DatevExportResult) -> None:
        """Zeigt die Export-Zusammenfassung und Buchungsvorschau."""
        # Status-Text
        self._lbl_status.setText(
            f"Export: {result.zeitraum_von} – {result.zeitraum_bis}"
        )

        # Detail-Labels
        details = [
            f"Anzahl Buchungen: {result.anzahl_buchungen}",
            f"Ausgangsrechnungen (Erlöse): {self._fmt_eur(result.summe_ar)}",
            f"Eingangsrechnungen (Aufwand): {self._fmt_eur(result.summe_er)}",
            f"Dateiname: {result.dateiname}",
            f"Format: DATEV Buchungsstapel (EXTF), Encoding CP1252, SKR03",
        ]
        for i, text in enumerate(details):
            self._detail_labels[i].setText(text)
            self._detail_labels[i].setVisible(True)

        # Tabelle mit Buchungsvorschau
        self._table.setVisible(True)
        self._table.setRowCount(0)

        # CSV nochmal parsen um die Buchungen zu zeigen
        try:
            csv_text = result.csv_bytes.decode("cp1252")
            lines = csv_text.split("\n")
            # Zeile 0 = Header, Zeile 1 = Spaltenüberschriften, ab Zeile 2 = Daten
            for row_idx, line in enumerate(lines[2:]):
                if not line.strip():
                    continue
                parts = line.split(";")
                if len(parts) < 14:
                    continue

                self._table.insertRow(row_idx)

                # Datum (TTMM → TT.MM)
                datum_raw = parts[9].strip().strip('"')
                if len(datum_raw) == 4:
                    datum_fmt = f"{datum_raw[:2]}.{datum_raw[2:]}"
                else:
                    datum_fmt = datum_raw

                zellen = [
                    datum_fmt,               # Datum
                    parts[10].strip('"'),     # Beleg-Nr
                    parts[13].strip('"'),     # Buchungstext
                    parts[6].strip('"'),      # Konto
                    parts[7].strip('"'),      # Gegenkonto
                    parts[1].strip('"'),      # S/H
                    parts[0].strip('"'),      # Betrag
                ]

                for col, text in enumerate(zellen):
                    item = QTableWidgetItem(text)
                    if col == 6:  # Betrag rechtsbündig
                        item.setTextAlignment(
                            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                        )
                    self._table.setItem(row_idx, col, item)

        except Exception as e:
            logger.warning(f"Vorschau-Tabelle konnte nicht gefüllt werden: {e}")

    # ------------------------------------------------------------------
    # Hilfsfunktionen
    # ------------------------------------------------------------------

    @staticmethod
    def _fmt_eur(betrag: Decimal) -> str:
        """Formatiert einen Betrag als Euro-String."""
        return f"{betrag:,.2f} EUR".replace(",", "X").replace(".", ",").replace("X", ".")

    @staticmethod
    def _oeffne_ordner(pfad: str) -> None:
        """Öffnet einen Ordner im Datei-Explorer."""
        try:
            if sys.platform == "win32":
                os.startfile(pfad)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", pfad])
            else:
                subprocess.Popen(["xdg-open", pfad])
        except Exception:
            pass
