"""
ui/modules/xrechnung/panel.py – XRechnung & PDF-Export
=======================================================
Zentrale Exportzentrale für elektronische Rechnungen:
  - XRechnung-XML generieren (EN 16931 / UBL 2.1)
  - PDF-Rechnung generieren (reportlab)
  - XML-Vorschau
  - Massen-Export mehrerer Rechnungen
"""

import logging
import os
import subprocess
import sys
from decimal import Decimal
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QTabWidget, QTextEdit, QMenu, QCheckBox, QFileDialog,
    QDialog, QScrollArea,
)

from core.db.engine import db
from core.services.rechnungen_service import (
    rechnungen_service, RechnungDTO, RechnungStatus,
)
from core.services.xrechnung_service import xrechnung_service, XRechnungDaten
from core.services.pdf_service import pdf_service
from core.config import config
from ui.components.widgets import (
    SearchBar, DataTable, NotificationBanner,
    ConfirmDialog, FormField,
)
from ui.theme.theme import Colors, Fonts, Spacing, Radius

logger = logging.getLogger(__name__)


def _fmt(v: Decimal) -> str:
    return f"{v:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


class XRechnungPanel(QWidget):
    """
    Exportzentrale für XRechnung (XML) und PDF.
    Tab 1: Rechnungsauswahl + Exportaktionen
    Tab 2: XML-Vorschau
    Tab 3: Export-Protokoll
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rechnungen: list[RechnungDTO] = []
        self._vorschau_xml: str = ""
        self._build_ui()
        self._connect_signals()
        QTimer.singleShot(200, self._laden)

    def showEvent(self, event):
        super().showEvent(event)
        self._laden()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())

        banner_wrap = QWidget()
        bw = QVBoxLayout(banner_wrap)
        bw.setContentsMargins(Spacing.XL, Spacing.SM, Spacing.XL, 0)
        self._banner = NotificationBanner()
        bw.addWidget(self._banner)
        root.addWidget(banner_wrap)

        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                background-color: {Colors.BG_APP};
                border: none;
            }}
            QTabBar::tab {{
                background: transparent;
                color: {Colors.TEXT_SECONDARY};
                padding: 10px 20px;
                border-bottom: 2px solid transparent;
            }}
            QTabBar::tab:selected {{
                color: {Colors.PRIMARY};
                border-bottom: 2px solid {Colors.PRIMARY};
            }}
            QTabBar::tab:hover {{ color: {Colors.TEXT_PRIMARY}; }}
        """)

        self._tabs.addTab(self._build_auswahl_tab(),  "🧾  Rechnungen")
        self._tabs.addTab(self._build_vorschau_tab(), "📄  XML-Vorschau")
        self._tabs.addTab(self._build_log_tab(),      "📋  Export-Protokoll")

        root.addWidget(self._tabs, 1)

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setFixedHeight(64)
        header.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.BG_SURFACE};
                border-bottom: 1px solid {Colors.BORDER};
            }}
        """)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(Spacing.XL, 0, Spacing.XL, 0)

        icon = QLabel("🖹")
        icon.setStyleSheet("font-size: 22px; background: transparent;")
        title = QLabel("XRechnung & PDF-Export")
        title.setFont(Fonts.heading2())
        title.setStyleSheet(
            f"color: {Colors.TEXT_PRIMARY}; background: transparent;"
        )
        layout.addWidget(icon)
        layout.addSpacing(Spacing.SM)
        layout.addWidget(title)
        layout.addStretch()

        # Aktions-Buttons in der Headerleiste
        self._btn_xml = QPushButton("⬇  XRechnung (XML)")
        self._btn_xml.setEnabled(False)
        self._btn_xml.clicked.connect(self._export_xml_selected)
        layout.addWidget(self._btn_xml)

        self._btn_pdf = QPushButton("📄  PDF generieren")
        self._btn_pdf.setEnabled(False)
        self._btn_pdf.clicked.connect(self._export_pdf_selected)
        layout.addWidget(self._btn_pdf)

        self._btn_beide = QPushButton("✨  Beide exportieren")
        self._btn_beide.setEnabled(False)
        self._btn_beide.clicked.connect(self._export_beide_selected)
        layout.addWidget(self._btn_beide)

        return header

    def _build_auswahl_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(Spacing.XL, Spacing.MD, Spacing.XL, Spacing.MD)
        layout.setSpacing(Spacing.SM)

        # Toolbar
        toolbar = QWidget()
        toolbar.setStyleSheet("background: transparent;")
        tl = QHBoxLayout(toolbar)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(Spacing.SM)

        self._search = SearchBar("Rechnung suchen…")
        tl.addWidget(self._search, 1)

        self._nur_finalisiert_check = QCheckBox("Nur finalisierte")
        self._nur_finalisiert_check.setChecked(True)
        self._nur_finalisiert_check.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        self._nur_finalisiert_check.toggled.connect(self._laden)
        tl.addWidget(self._nur_finalisiert_check)

        layout.addWidget(toolbar)

        # Infotext
        info = QLabel(
            "ℹ  Wählen Sie eine Rechnung aus und exportieren Sie sie als "
            "XRechnung-XML (EN 16931) oder als PDF. "
            "Für B2G-Rechnungen (öffentlicher Auftraggeber) die Leitweg-ID "
            "vor dem Export eingeben."
        )
        info.setFont(Fonts.caption())
        info.setStyleSheet(
            f"color: {Colors.TEXT_SECONDARY}; "
            f"background-color: {Colors.BG_ELEVATED}; "
            f"border-radius: {Radius.SM}px; "
            f"padding: {Spacing.SM}px {Spacing.MD}px;"
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        # Leitweg-ID
        leitweg_row = QHBoxLayout()
        leitweg_row.setSpacing(Spacing.SM)
        self.f_leitweg = FormField(
            "Leitweg-ID (B2G) / Käufer-Referenz",
            placeholder='z.B. 991-12345678-06 oder E-Mail des Käufers',
            max_length=100,
        )
        leitweg_row.addWidget(self.f_leitweg)
        leitweg_info = QLabel(
            "Pflicht für Behörden.\nFür private Kunden leer lassen."
        )
        leitweg_info.setFont(Fonts.caption())
        leitweg_info.setStyleSheet(f"color: {Colors.TEXT_DISABLED};")
        leitweg_row.addWidget(leitweg_info)
        layout.addLayout(leitweg_row)

        # Hinweis: Speicherort = Kundenordner aus Einstellungen → Pfade → Dokumentenordner
        pfad_info = QLabel(
            "📁  Dateien werden automatisch im Kundenordner gespeichert "
            "(Einstellungen → Pfade → Dokumentenordner)."
        )
        pfad_info.setFont(Fonts.caption())
        pfad_info.setStyleSheet(
            f"color: {Colors.TEXT_SECONDARY}; "
            f"background-color: {Colors.BG_ELEVATED}; "
            f"border-radius: {Radius.SM}px; "
            f"padding: {Spacing.SM}px {Spacing.MD}px;"
        )
        pfad_info.setWordWrap(True)
        layout.addWidget(pfad_info)

        # Tabelle
        self._table = DataTable(
            columns=[
                "ID", "Rechnungsnr.", "Datum", "Fällig am",
                "Kunde", "Netto", "Brutto", "Status",
            ],
            column_widths=[0, 130, 100, 100, 220, 100, 110, 140],
            stretch_column=4,
                    table_id="xrechnung_liste",
        )
        self._table.setColumnHidden(0, True)
        self._table.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._table.customContextMenuRequested.connect(self._context_menu)
        layout.addWidget(self._table, 1)

        return tab

    def _build_vorschau_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(Spacing.XL, Spacing.MD, Spacing.XL, Spacing.MD)
        layout.setSpacing(Spacing.SM)

        toolbar = QHBoxLayout()
        lbl = QLabel("XML-Vorschau der zuletzt exportierten Rechnung:")
        lbl.setFont(Fonts.caption())
        lbl.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        toolbar.addWidget(lbl)
        toolbar.addStretch()
        self._btn_kopieren = QPushButton("📋  Kopieren")
        self._btn_kopieren.setProperty("role", "secondary")
        self._btn_kopieren.clicked.connect(self._xml_kopieren)
        toolbar.addWidget(self._btn_kopieren)
        layout.addLayout(toolbar)

        self._xml_vorschau = QTextEdit()
        self._xml_vorschau.setReadOnly(True)
        self._xml_vorschau.setFont(
            __import__("PySide6.QtGui", fromlist=["QFont"]).QFont("Consolas", 9)
        )
        self._xml_vorschau.setStyleSheet(f"""
            QTextEdit {{
                background-color: {Colors.BG_SURFACE};
                color: {Colors.TEXT_PRIMARY};
                border: 1px solid {Colors.BORDER};
                border-radius: {Radius.MD}px;
                padding: {Spacing.SM}px;
            }}
        """)
        self._xml_vorschau.setPlaceholderText(
            "Hier erscheint das XML nach dem ersten XRechnung-Export…"
        )
        layout.addWidget(self._xml_vorschau, 1)
        return tab

    def _build_log_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(Spacing.XL, Spacing.MD, Spacing.XL, Spacing.MD)
        layout.setSpacing(Spacing.SM)

        toolbar = QHBoxLayout()
        lbl = QLabel("Export-Protokoll dieser Sitzung:")
        lbl.setFont(Fonts.caption())
        lbl.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        toolbar.addWidget(lbl)
        toolbar.addStretch()
        btn_clear = QPushButton("🗑  Leeren")
        btn_clear.setProperty("role", "secondary")
        btn_clear.clicked.connect(lambda: self._log_edit.clear())
        toolbar.addWidget(btn_clear)
        layout.addLayout(toolbar)

        self._log_edit = QTextEdit()
        self._log_edit.setReadOnly(True)
        self._log_edit.setFont(
            __import__("PySide6.QtGui", fromlist=["QFont"]).QFont("Consolas", 9)
        )
        self._log_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {Colors.BG_SURFACE};
                color: {Colors.TEXT_PRIMARY};
                border: 1px solid {Colors.BORDER};
                border-radius: {Radius.MD}px;
                padding: {Spacing.SM}px;
            }}
        """)
        layout.addWidget(self._log_edit, 1)
        return tab

    # ------------------------------------------------------------------
    # Signale
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        self._search.search_changed.connect(self._on_suche)
        self._search.cleared.connect(self._laden)
        self._table.row_selected.connect(self._on_zeile_ausgewaehlt)
        self._table.row_double_clicked.connect(self._on_doppelklick)

    # ------------------------------------------------------------------
    # Daten laden
    # ------------------------------------------------------------------

    def _laden(self, suchtext: str = "") -> None:
        nur_finalisiert = self._nur_finalisiert_check.isChecked()
        try:
            with db.session() as session:
                self._rechnungen = rechnungen_service.alle(
                    session,
                    nur_finalisiert=nur_finalisiert,
                    suchtext=suchtext,
                )
        except Exception as e:
            self._banner.show_error(f"Fehler beim Laden: {e}")
            return

        STATUS_FARBEN = {
            RechnungStatus.ENTWURF:    Colors.TEXT_DISABLED,
            RechnungStatus.OFFEN:      Colors.INFO,
            RechnungStatus.BEZAHLT:    Colors.SUCCESS,
            RechnungStatus.ERINNERUNG: Colors.WARNING,
            RechnungStatus.MAHNUNG1:   "#F97316",
            RechnungStatus.MAHNUNG2:   Colors.ERROR,
            RechnungStatus.INKASSO:    "#DC2626",
            RechnungStatus.STORNIERT:  Colors.TEXT_DISABLED,
        }

        rows, colors = [], {}
        for i, dto in enumerate(self._rechnungen):
            rows.append([
                dto.id,
                dto.rechnungsnummer,
                dto.rechnungsdatum,
                dto.faelligkeitsdatum or "–",
                dto.kunde_display,
                _fmt(dto.summe_netto),
                _fmt(dto.summe_brutto),
                dto.status,
            ])
            farbe = STATUS_FARBEN.get(dto.status)
            if farbe:
                colors[i] = QColor(farbe)

        self._table.set_data(rows)
        for row, color in colors.items():
            self._table.set_row_color(row, color)

        self._btn_xml.setEnabled(False)
        self._btn_pdf.setEnabled(False)
        self._btn_beide.setEnabled(False)

    def _on_suche(self, text: str) -> None:
        self._laden(text)

    def _on_zeile_ausgewaehlt(self, row: int) -> None:
        aktiv = 0 <= row < len(self._rechnungen)
        self._btn_xml.setEnabled(aktiv)
        self._btn_pdf.setEnabled(aktiv)
        self._btn_beide.setEnabled(aktiv)

    def _on_doppelklick(self, row: int) -> None:
        if 0 <= row < len(self._rechnungen):
            self._export_beide(self._rechnungen[row])

    # ------------------------------------------------------------------
    # Kontext-Menü
    # ------------------------------------------------------------------

    def _context_menu(self, pos) -> None:
        row = self._table.current_source_row()
        if row < 0 or row >= len(self._rechnungen):
            return
        dto = self._rechnungen[row]

        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {Colors.BG_ELEVATED};
                border: 1px solid {Colors.BORDER};
                border-radius: {Radius.MD}px;
                padding: 4px;
            }}
            QMenu::item {{ padding: 8px 20px; border-radius: {Radius.SM}px; }}
            QMenu::item:selected {{ background-color: {Colors.PRIMARY}; }}
        """)

        menu.addAction("⬇  XRechnung (XML)").triggered.connect(
            lambda: self._export_xml(dto)
        )
        menu.addAction("📄  PDF generieren").triggered.connect(
            lambda: self._export_pdf(dto)
        )
        menu.addAction("✨  Beide exportieren").triggered.connect(
            lambda: self._export_beide(dto)
        )
        menu.addSeparator()
        menu.addAction("👁  XML-Vorschau").triggered.connect(
            lambda: self._vorschau(dto)
        )

        menu.exec(self._table.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------------
    # Aktionen
    # ------------------------------------------------------------------

    def _export_xml_selected(self) -> None:
        row = self._table.current_source_row()
        if 0 <= row < len(self._rechnungen):
            self._export_xml(self._rechnungen[row])

    def _export_pdf_selected(self) -> None:
        row = self._table.current_source_row()
        if 0 <= row < len(self._rechnungen):
            self._export_pdf(self._rechnungen[row])

    def _export_beide_selected(self) -> None:
        row = self._table.current_source_row()
        if 0 <= row < len(self._rechnungen):
            self._export_beide(self._rechnungen[row])

    def _export_xml(self, dto: RechnungDTO) -> None:
        """Exportiert XRechnung-XML in den Kundenordner und registriert im DMS."""
        try:
            from core.services.kunden_service import kunden_service
            with db.session() as session:
                full_dto = rechnungen_service.nach_id(session, dto.id)
                if not full_dto:
                    self._banner.show_error("Rechnung nicht gefunden.")
                    return
                ordner = kunden_service.kunden_ordner_pfad(session, dto.kunde_id)
                if not ordner:
                    self._banner.show_error(
                        "Kein Dokumentenordner konfiguriert. "
                        "Bitte unter Einstellungen → Pfade → Dokumentenordner festlegen."
                    )
                    return
                xdaten = xrechnung_service.xrechnung_daten_aus_dto(
                    full_dto, session,
                    leitweg_id=self.f_leitweg.value().strip(),
                )
                xml_bytes = xrechnung_service._xml_erstellen(xdaten)
                # XML-Vorschau aktualisieren
                xml_str = xml_bytes.decode("utf-8")
                self._xml_vorschau.setPlainText(xml_str)
                safe_nr = full_dto.rechnungsnummer.replace("/", "-").replace("\\", "-")
                dateiname = f"XRechnung_{safe_nr}.xml"
                ziel = kunden_service.dokument_in_kundenordner_erstellen(
                    session, dto.kunde_id, dateiname, xml_bytes
                )
            if ziel:
                self._tabs.setCurrentIndex(1)
                self._log(f"✓ XML → {ziel}")
                self._banner.show_success(f"XRechnung gespeichert: {ziel.name}")
                self._oeffne_ordner(str(ordner))
            else:
                self._banner.show_error("XRechnung konnte nicht gespeichert werden.")
        except Exception as e:
            self._log(f"✗ XML-Fehler: {e}")
            self._banner.show_error(f"Fehler: {e}")

    def _export_pdf(self, dto: RechnungDTO) -> None:
        """Exportiert PDF in den Kundenordner und registriert im DMS."""
        try:
            from core.services.kunden_service import kunden_service
            with db.session() as session:
                full_dto = rechnungen_service.nach_id(session, dto.id)
                if not full_dto:
                    self._banner.show_error("Rechnung nicht gefunden.")
                    return
                ordner = kunden_service.kunden_ordner_pfad(session, dto.kunde_id)
                if not ordner:
                    self._banner.show_error(
                        "Kein Dokumentenordner konfiguriert. "
                        "Bitte unter Einstellungen → Pfade → Dokumentenordner festlegen."
                    )
                    return
                pdf_bytes = pdf_service.rechnung_als_pdf_bytes(full_dto, session)
                safe_nr = full_dto.rechnungsnummer.replace("/", "-").replace("\\", "-")
                dateiname = f"Rechnung_{safe_nr}.pdf"
                ziel = kunden_service.dokument_in_kundenordner_erstellen(
                    session, dto.kunde_id, dateiname, pdf_bytes
                )
            if ziel:
                self._log(f"✓ PDF → {ziel}")
                self._banner.show_success(f"PDF gespeichert: {ziel.name}")
                self._oeffne_datei(str(ziel))
            else:
                self._banner.show_error("PDF konnte nicht gespeichert werden.")
        except Exception as e:
            self._log(f"✗ PDF-Fehler: {e}")
            self._banner.show_error(f"Fehler: {e}")

    def _export_beide(self, dto: RechnungDTO) -> None:
        """Exportiert XML und PDF in einem Schritt."""
        self._export_xml(dto)
        self._export_pdf(dto)

    def _vorschau(self, dto: RechnungDTO) -> None:
        """Zeigt die XML-Vorschau ohne Datei zu schreiben."""
        try:
            with db.session() as session:
                full_dto = rechnungen_service.nach_id(session, dto.id)
                if not full_dto:
                    self._banner.show_error("Rechnung nicht gefunden.")
                    return
                xdaten = xrechnung_service.xrechnung_daten_aus_dto(
                    full_dto, session,
                    leitweg_id=self.f_leitweg.value().strip(),
                )
            xml = xrechnung_service.xml_string(xdaten)
            self._xml_vorschau.setPlainText(xml)
            self._tabs.setCurrentIndex(1)
        except Exception as e:
            self._banner.show_error(f"Vorschau-Fehler: {e}")

    def _xml_kopieren(self) -> None:
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self._xml_vorschau.toPlainText())
        self._banner.show_success("XML in Zwischenablage kopiert.")

    # ------------------------------------------------------------------
    # Hilfsmethoden
    # ------------------------------------------------------------------

    def _log(self, text: str) -> None:
        ts = __import__("datetime").datetime.now().strftime("%H:%M:%S")
        self._log_edit.append(f"[{ts}]  {text}")

    def _oeffne_datei(self, pfad: str) -> None:
        """Öffnet eine Datei mit dem Standardprogramm des OS."""
        try:
            if sys.platform == "win32":
                os.startfile(pfad)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", pfad])
            else:
                subprocess.Popen(["xdg-open", pfad])
        except Exception:
            pass  # Nicht kritisch

    def _oeffne_ordner(self, dateipfad: str) -> None:
        """Öffnet den Ordner der Datei im Explorer/Finder."""
        try:
            ordner = str(__import__("pathlib").Path(dateipfad).parent)
            if sys.platform == "win32":
                subprocess.Popen(["explorer", ordner])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", ordner])
            else:
                subprocess.Popen(["xdg-open", ordner])
        except Exception:
            pass
