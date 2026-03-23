"""
ui/modules/rechnungskorrektur/panel.py – Rechnungskorrektur-Modul
=================================================================
Bietet:
  • Übersicht aller Gutschriften & Stornos
  • Teilzahlungen erfassen & verbuchen
  • Skonto / Rabatt nachträglich gewähren
  • Teilkorrekturen (einzelne Positionen)

Alle Operationen sind GoBD-konform: Es wird nie eine
finalisierte Rechnung direkt geändert – stattdessen werden
Buchungsvermerke in der Bemerkung und Statusänderungen genutzt.
"""

import logging
from decimal import Decimal, InvalidOperation
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QTabWidget, QMenu, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QLineEdit, QTextEdit, QFormLayout,
    QComboBox, QSizePolicy, QMessageBox,
)

from core.db.engine import db
from core.services.rechnungen_service import (
    rechnungen_service, RechnungStatus, RechnungDTO,
)
from core.services.kunden_service import kunden_service
from ui.components.widgets import DataTable, NotificationBanner, ConfirmDialog
from ui.theme.theme import Colors, Fonts, Spacing, Radius, on_theme_changed

logger = logging.getLogger(__name__)


def _fmt(v) -> str:
    r = Decimal(str(v or "0")).quantize(Decimal("0.01"))
    s = f"{r:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s} €"


# ───────────────────────────────────────────────────────────────────────────────
# Dialoge
# ───────────────────────────────────────────────────────────────────────────────

class _TeilzahlungDialog(QDialog):
    """Dialog für eine neue Teilzahlung."""

    def __init__(self, dto: RechnungDTO, parent=None):
        super().__init__(parent)
        # WA_DeleteOnClose entfernt: Dialog muss nach exec() noch lesbar sein
        self._dto = dto
        self.setWindowTitle("Teilzahlung erfassen")
        self.setMinimumWidth(420)
        self.setModal(True)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.XL, Spacing.XL, Spacing.XL, Spacing.LG)
        layout.setSpacing(Spacing.MD)

        # Info-Box
        info = QFrame()
        info.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.BG_ELEVATED};
                border-radius: {Radius.MD}px;
                border: 1px solid {Colors.BORDER};
            }}
        """)
        info_layout = QFormLayout(info)
        info_layout.setContentsMargins(Spacing.LG, Spacing.MD, Spacing.LG, Spacing.MD)
        info_layout.setSpacing(Spacing.SM)
        for label, val in [
            ("Rechnung:", self._dto.rechnungsnummer),
            ("Brutto:", _fmt(self._dto.summe_brutto)),
            ("Noch offen:", _fmt(self._dto.offener_betrag)),
        ]:
            lbl = QLabel(label)
            lbl.setFont(Fonts.get(Fonts.SIZE_SM, bold=True))
            lbl.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; background: transparent;")
            val_lbl = QLabel(val)
            val_lbl.setFont(Fonts.get(Fonts.SIZE_SM))
            val_lbl.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; background: transparent;")
            info_layout.addRow(lbl, val_lbl)
        layout.addWidget(info)

        # Formular
        form = QFormLayout()
        form.setSpacing(Spacing.SM)

        self._betrag_spin = QDoubleSpinBox()
        self._betrag_spin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        self._betrag_spin.setRange(0.01, float(self._dto.offener_betrag))
        self._betrag_spin.setDecimals(2)
        self._betrag_spin.setSuffix(" €")
        self._betrag_spin.setValue(float(self._dto.offener_betrag))
        self._betrag_spin.setFixedHeight(36)

        self._datum_edit = QLineEdit()
        from datetime import date
        self._datum_edit.setText(date.today().strftime("%d.%m.%Y"))
        self._datum_edit.setPlaceholderText("TT.MM.JJJJ")
        self._datum_edit.setFixedHeight(36)
        self._datum_edit.setStyleSheet(f"""
            QLineEdit {{
                background: {Colors.BG_ELEVATED};
                border: 1px solid {Colors.BORDER};
                border-radius: {Radius.SM}px;
                color: {Colors.TEXT_PRIMARY};
                padding: 4px 8px;
            }}
        """)

        self._bemerkung_edit = QLineEdit()
        self._bemerkung_edit.setPlaceholderText("z.B. Überweisung, Barzahlung …")
        self._bemerkung_edit.setFixedHeight(36)
        self._bemerkung_edit.setStyleSheet(self._datum_edit.styleSheet())

        form.addRow("Betrag:", self._betrag_spin)
        form.addRow("Datum:", self._datum_edit)
        form.addRow("Bemerkung:", self._bemerkung_edit)
        layout.addLayout(form)

        # Buttons
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("Zahlung buchen")
        btns.button(QDialogButtonBox.StandardButton.Ok).setProperty("role", "primary")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def get_daten(self) -> dict:
        return {
            "betrag": Decimal(str(self._betrag_spin.value())),
            "datum": self._datum_edit.text().strip(),
            "bemerkung": self._bemerkung_edit.text().strip(),
        }


class _SkontoDialog(QDialog):
    """Dialog für Skonto / nachträglichen Rabatt."""

    def __init__(self, dto: RechnungDTO, parent=None):
        super().__init__(parent)
        # WA_DeleteOnClose entfernt: Dialog muss nach exec() noch lesbar sein
        self._dto = dto
        self.setWindowTitle("Skonto / Rabatt gewähren")
        self.setMinimumWidth(440)
        self.setModal(True)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.XL, Spacing.XL, Spacing.XL, Spacing.LG)
        layout.setSpacing(Spacing.MD)

        # Info-Box
        info = QFrame()
        info.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.BG_ELEVATED};
                border-radius: {Radius.MD}px;
                border: 1px solid {Colors.BORDER};
            }}
        """)
        info_l = QFormLayout(info)
        info_l.setContentsMargins(Spacing.LG, Spacing.MD, Spacing.LG, Spacing.MD)
        for lbl_t, val_t in [
            ("Rechnung:", self._dto.rechnungsnummer),
            ("Brutto:", _fmt(self._dto.summe_brutto)),
            ("Noch offen:", _fmt(self._dto.offener_betrag)),
        ]:
            lbl = QLabel(lbl_t)
            lbl.setFont(Fonts.get(Fonts.SIZE_SM, bold=True))
            lbl.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; background: transparent;")
            val = QLabel(val_t)
            val.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; background: transparent;")
            info_l.addRow(lbl, val)
        layout.addWidget(info)

        # Formular
        form = QFormLayout()
        form.setSpacing(Spacing.SM)

        self._art_combo = QComboBox()
        self._art_combo.addItems(["Prozentualer Skonto", "Fester Betrag"])
        self._art_combo.setFixedHeight(36)

        self._syncing = False  # Verhindert Endlos-Loop bei gegenseitiger Aktualisierung

        self._prozent_spin = QDoubleSpinBox()
        self._prozent_spin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        self._prozent_spin.setRange(0.00, 100.0)
        self._prozent_spin.setDecimals(2)
        self._prozent_spin.setValue(2.0)
        self._prozent_spin.setSuffix(" %")
        self._prozent_spin.setFixedHeight(36)
        self._prozent_spin.valueChanged.connect(self._on_prozent_changed)

        self._betrag_spin = QDoubleSpinBox()
        self._betrag_spin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        self._betrag_spin.setRange(0.00, float(self._dto.offener_betrag))
        self._betrag_spin.setDecimals(2)
        self._betrag_spin.setSuffix(" €")
        self._betrag_spin.setFixedHeight(36)
        self._betrag_spin.valueChanged.connect(self._on_betrag_changed)

        self._preview_lbl = QLabel("")
        self._preview_lbl.setFont(Fonts.get(Fonts.SIZE_MD, bold=True))

        self._bemerkung_edit = QLineEdit()
        self._bemerkung_edit.setPlaceholderText("Optionaler Hinweis …")
        self._bemerkung_edit.setFixedHeight(36)

        self._art_combo.currentIndexChanged.connect(self._on_art_changed)

        form.addRow("Art:", self._art_combo)
        form.addRow("Prozent:", self._prozent_spin)
        form.addRow("Betrag:", self._betrag_spin)
        form.addRow("Bemerkung:", self._bemerkung_edit)
        layout.addLayout(form)

        # Vorschau-Box
        self._preview_box = QFrame()
        self._preview_box.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.SUCCESS_BG};
                border: 1px solid {Colors.SUCCESS};
                border-radius: {Radius.MD}px;
            }}
        """)
        pbox_l = QVBoxLayout(self._preview_box)
        pbox_l.setContentsMargins(Spacing.LG, Spacing.SM, Spacing.LG, Spacing.SM)
        self._preview_lbl.setStyleSheet(f"color: {Colors.SUCCESS}; background: transparent;")
        pbox_l.addWidget(self._preview_lbl)
        self._preview_neu_lbl = QLabel("")
        self._preview_neu_lbl.setFont(Fonts.get(Fonts.SIZE_SM))
        self._preview_neu_lbl.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; background: transparent;")
        pbox_l.addWidget(self._preview_neu_lbl)
        layout.addWidget(self._preview_box)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("Skonto gewähren")
        btns.button(QDialogButtonBox.StandardButton.Ok).setProperty("role", "primary")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        # Initialer Sync: Betrag aus Prozent berechnen
        self._on_prozent_changed(self._prozent_spin.value())

    def _on_art_changed(self, index: int) -> None:
        """Art gewechselt → das jeweils andere Feld neu berechnen."""
        if index == 0:
            # Prozentualer Skonto → Betrag aus Prozent berechnen
            self._on_prozent_changed(self._prozent_spin.value())
        else:
            # Fester Betrag → Prozent aus Betrag berechnen
            self._on_betrag_changed(self._betrag_spin.value())

    def _on_prozent_changed(self, val: float) -> None:
        """Prozent geändert → Betrag automatisch berechnen (Basis: offener Betrag)."""
        if self._syncing:
            return
        self._syncing = True
        try:
            offen = Decimal(str(self._dto.offener_betrag))
            p = Decimal(str(val))
            skonto = (offen * p / Decimal("100")).quantize(Decimal("0.01"))
            self._betrag_spin.setValue(float(skonto))
        except Exception:
            pass
        self._syncing = False
        self._update_preview()

    def _on_betrag_changed(self, val: float) -> None:
        """Betrag geändert → Prozent automatisch berechnen (Basis: offener Betrag)."""
        if self._syncing:
            return
        self._syncing = True
        try:
            offen = Decimal(str(self._dto.offener_betrag))
            betrag = Decimal(str(val))
            if offen > 0:
                prozent = (betrag / offen * Decimal("100")).quantize(Decimal("0.01"))
                self._prozent_spin.setValue(float(prozent))
        except Exception:
            pass
        self._syncing = False
        self._update_preview()

    def _update_preview(self) -> None:
        try:
            offen = Decimal(str(self._dto.offener_betrag))
            skonto = Decimal(str(self._betrag_spin.value()))
            neu_offen = max(offen - skonto, Decimal("0"))
            self._preview_lbl.setText(f"Abzug: –{_fmt(skonto)}")
            self._preview_neu_lbl.setText(
                f"Offener Betrag: {_fmt(offen)} → {_fmt(neu_offen)}"
            )
        except Exception:
            self._preview_lbl.setText("–")
            self._preview_neu_lbl.setText("")

    def get_daten(self) -> dict:
        if self._art_combo.currentIndex() == 0:
            return {"prozent": Decimal(str(self._prozent_spin.value())), "betrag": None,
                    "bemerkung": self._bemerkung_edit.text().strip()}
        else:
            return {"prozent": None, "betrag": Decimal(str(self._betrag_spin.value())),
                    "bemerkung": self._bemerkung_edit.text().strip()}


class _TeilkorrekturDialog(QDialog):
    """
    Dialog für eine Teilkorrektur: Erstellt eine manuelle Teil-Gutschrift.
    Da finalisierte Rechnungen GoBD-konform nicht editiert werden können,
    wird eine neue Gutschrift für den Korrekturbetrag angelegt.
    """

    def __init__(self, dto: RechnungDTO, parent=None):
        super().__init__(parent)
        # WA_DeleteOnClose entfernt: Dialog muss nach exec() noch lesbar sein
        self._dto = dto
        self.setWindowTitle("Teilkorrektur / Teil-Gutschrift")
        self.setMinimumWidth(480)
        self.setModal(True)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.XL, Spacing.XL, Spacing.XL, Spacing.LG)
        layout.setSpacing(Spacing.MD)

        # Hinweis
        hinweis = QLabel(
            "ℹ  Eine Teil-Gutschrift korrigiert einzelne Positionen GoBD-konform: "
            "Die Originalrechnung bleibt unverändert; es wird eine neue Gutschrift "
            "über den Korrekturbetrag angelegt."
        )
        hinweis.setWordWrap(True)
        hinweis.setFont(Fonts.get(Fonts.SIZE_SM))
        hinweis.setStyleSheet(f"""
            background-color: {Colors.BG_ELEVATED};
            border-left: 3px solid {Colors.INFO};
            border-radius: {Radius.SM}px;
            color: {Colors.TEXT_SECONDARY};
            padding: 8px 12px;
        """)
        layout.addWidget(hinweis)

        # Info
        info_row = QHBoxLayout()
        for label, val in [
            ("Rechnung:", self._dto.rechnungsnummer),
            ("Brutto:", _fmt(self._dto.summe_brutto)),
            ("Noch offen:", _fmt(self._dto.offener_betrag)),
        ]:
            lbl = QLabel(f"<b>{label}</b> {val}")
            lbl.setFont(Fonts.get(Fonts.SIZE_SM))
            lbl.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
            info_row.addWidget(lbl)
        info_row.addStretch()
        layout.addLayout(info_row)

        # Formular
        form = QFormLayout()
        form.setSpacing(Spacing.SM)

        self._beschreibung_edit = QLineEdit()
        self._beschreibung_edit.setPlaceholderText("z.B. Rückgabe Pos. 2 – Artikel defekt")
        self._beschreibung_edit.setFixedHeight(36)

        self._netto_spin = QDoubleSpinBox()
        self._netto_spin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        # Maximal den offenen Netto-Betrag erlauben (Brutto→Netto rückrechnen)
        offen = Decimal(str(self._dto.offener_betrag))
        mwst_faktor = Decimal("1") + self._dto.mwst_prozent / Decimal("100")
        max_netto = (offen / mwst_faktor).quantize(Decimal("0.01"))
        self._netto_spin.setRange(0.01, float(max_netto))
        self._netto_spin.setDecimals(2)
        self._netto_spin.setSuffix(" €  (netto)")
        self._netto_spin.setFixedHeight(36)

        self._grund_edit = QLineEdit()
        self._grund_edit.setPlaceholderText("Begründung der Korrektur …")
        self._grund_edit.setFixedHeight(36)

        form.addRow("Beschreibung:", self._beschreibung_edit)
        form.addRow("Netto-Betrag:", self._netto_spin)
        form.addRow("Begründung:", self._grund_edit)
        layout.addLayout(form)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("Teil-Gutschrift erstellen")
        btns.button(QDialogButtonBox.StandardButton.Ok).setProperty("role", "primary")
        btns.accepted.connect(self._validate_and_accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _validate_and_accept(self) -> None:
        if not self._beschreibung_edit.text().strip():
            self._beschreibung_edit.setFocus()
            return
        self.accept()

    def get_daten(self) -> dict:
        return {
            "beschreibung": self._beschreibung_edit.text().strip(),
            "netto": Decimal(str(self._netto_spin.value())),
            "grund": self._grund_edit.text().strip(),
        }


# ───────────────────────────────────────────────────────────────────────────────
# Hauptpanel
# ───────────────────────────────────────────────────────────────────────────────

class RechnungskorrekturPanel(QWidget):
    """
    Rechnungskorrektur-Modul.
    Tabs: Gutschriften/Stornos · Zahlungseingänge · Skonto/Rabatt
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._alle_korrekturen: list[RechnungDTO] = []
        self._korrigierbar: list[RechnungDTO] = []
        self._gefilterte_korrekturen: list[RechnungDTO] = []
        self._gefilterte_korrigierbar: list[RechnungDTO] = []
        self._root_layout = None
        self._build_ui()
        self._search_text = ""
        QTimer.singleShot(100, self._load_data)
        on_theme_changed(self._on_theme_changed)

    def _on_theme_changed(self, _mode: str) -> None:
        if self._root_layout is not None:
            while self._root_layout.count():
                item = self._root_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            QWidget().setLayout(self._root_layout)
        self._build_ui()
        self._load_data()

    def showEvent(self, event):
        super().showEvent(event)
        self._load_data()

    # ------------------------------------------------------------------
    # UI-Aufbau
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        self._root_layout = root
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())

        banner_wrap = QWidget()
        bw_l = QVBoxLayout(banner_wrap)
        bw_l.setContentsMargins(Spacing.XL, Spacing.SM, Spacing.XL, 0)
        self._banner = NotificationBanner()
        bw_l.addWidget(self._banner)
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
        self._tabs.addTab(self._build_gutschriften_tab(), "📋  Gutschriften & Stornos")
        self._tabs.addTab(self._build_zahlungen_tab(), "💶  Zahlungseingänge")
        self._tabs.addTab(self._build_skonto_tab(), "🏷  Skonto & Rabatt")
        root.addWidget(self._tabs, 1)

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("korrekturPanelHeader")
        header.setFixedHeight(64)
        header.setStyleSheet(f"""
            #korrekturPanelHeader {{
                background-color: {Colors.BG_SURFACE};
                border-bottom: 1px solid {Colors.BORDER};
            }}
        """)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(Spacing.XL, 0, Spacing.XL, 0)

        icon = QLabel("✏️")
        icon.setStyleSheet("font-size: 22px; background: transparent;")
        title = QLabel("Rechnungskorrektur")
        title.setFont(Fonts.heading2())
        title.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; background: transparent;")
        layout.addWidget(icon)
        layout.addSpacing(Spacing.SM)
        layout.addWidget(title)
        layout.addStretch()

        btn_refresh = QPushButton("↻  Aktualisieren")
        btn_refresh.setProperty("role", "secondary")
        btn_refresh.clicked.connect(self._load_data)
        layout.addWidget(btn_refresh)
        return header

    def _build_gutschriften_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(Spacing.XL, Spacing.MD, Spacing.XL, Spacing.MD)

        # Zusammenfassung
        self._gs_summary = QLabel("")
        self._gs_summary.setFont(Fonts.caption())
        self._gs_summary.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        layout.addWidget(self._gs_summary)

        # Suchfeld
        from PySide6.QtWidgets import QLineEdit
        self._gs_search = QLineEdit()
        self._gs_search.setPlaceholderText(
            "Suchen nach Rechnungsnr., Kunde, Kundennr. ..."
        )
        self._gs_search.setFixedHeight(36)
        self._gs_search.textChanged.connect(self._on_search_changed)
        layout.addWidget(self._gs_search)

        self._gs_table = DataTable(
            columns=["ID", "Nummer", "Datum", "Kunde", "Typ",
                     "Brutto", "Gutschrift zu", "Status"],
            column_widths=[0, 130, 100, 220, 130, 110, 130, 160],
            stretch_column=3,
                    table_id="korrektur_gutschriften",
        )
        self._gs_table.setColumnHidden(0, True)
        self._gs_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._gs_table.customContextMenuRequested.connect(self._gs_context_menu)
        layout.addWidget(self._gs_table)
        return tab

    def _build_zahlungen_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(Spacing.XL, Spacing.MD, Spacing.XL, Spacing.MD)

        info = QLabel(
            "Hier können Sie Teilzahlungen auf offene, finalisierte Rechnungen buchen. "
            "Bei vollständiger Zahlung wird die Rechnung automatisch als 'Bezahlt' markiert."
        )
        info.setWordWrap(True)
        info.setFont(Fonts.caption())
        info.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; padding-bottom: 4px;")
        layout.addWidget(info)

        # Suchfeld
        from PySide6.QtWidgets import QLineEdit
        self._zahl_search = QLineEdit()
        self._zahl_search.setPlaceholderText(
            "Suchen nach Rechnungsnr., Kunde, Kundennr. ..."
        )
        self._zahl_search.setFixedHeight(36)
        self._zahl_search.textChanged.connect(self._on_search_changed)
        layout.addWidget(self._zahl_search)

        self._zahl_table = DataTable(
            columns=["ID", "Nummer", "Datum", "Kunde", "Fällig am",
                     "Brutto", "Offen", "Status"],
            column_widths=[0, 130, 100, 220, 100, 110, 110, 160],
            stretch_column=3,
                    table_id="korrektur_zahlungen",
        )
        self._zahl_table.setColumnHidden(0, True)
        self._zahl_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._zahl_table.customContextMenuRequested.connect(self._zahl_context_menu)
        layout.addWidget(self._zahl_table)
        return tab

    def _build_skonto_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(Spacing.XL, Spacing.MD, Spacing.XL, Spacing.MD)

        info = QLabel(
            "Gewähren Sie Skonto oder Rabatt auf offene Rechnungen. "
            "Hier können Sie auch Teil-Gutschriften für einzelne Korrekturen erstellen."
        )
        info.setWordWrap(True)
        info.setFont(Fonts.caption())
        info.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; padding-bottom: 4px;")
        layout.addWidget(info)

        # Suchfeld (geteilt mit Zahlungen-Tab über dasselbe Signal)
        from PySide6.QtWidgets import QLineEdit
        self._skonto_search = QLineEdit()
        self._skonto_search.setPlaceholderText(
            "Suchen nach Rechnungsnr., Kunde, Kundennr. ..."
        )
        self._skonto_search.setFixedHeight(36)
        self._skonto_search.textChanged.connect(self._on_search_changed)
        layout.addWidget(self._skonto_search)

        self._skonto_table = DataTable(
            columns=["ID", "Nummer", "Datum", "Kunde", "Fällig am",
                     "Brutto", "Offen", "Status"],
            column_widths=[0, 130, 100, 220, 100, 110, 110, 160],
            stretch_column=3,
                    table_id="korrektur_skonto",
        )
        self._skonto_table.setColumnHidden(0, True)
        self._skonto_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._skonto_table.customContextMenuRequested.connect(self._skonto_context_menu)
        layout.addWidget(self._skonto_table)
        return tab

    # ------------------------------------------------------------------
    # Daten laden
    # ------------------------------------------------------------------

    def _load_data(self) -> None:
        try:
            with db.session() as session:
                # Gutschriften & Stornos
                self._alle_korrekturen = rechnungen_service.alle(
                    session,
                    nur_finalisiert=True,
                    status_filter=[RechnungStatus.STORNIERT, RechnungStatus.GUTSCHRIFT],
                )
                # Korrigierbare (offene) Rechnungen
                self._korrigierbar = rechnungen_service.alle(
                    session,
                    nur_offene=True,
                )
        except Exception as e:
            self._banner.show_error(f"Fehler beim Laden: {e}")
            logger.exception("Rechnungskorrektur: Fehler beim Laden")
            return

        self._refresh_ui()

    def _on_search_changed(self, text: str) -> None:
        """Filtert alle Tabellen nach Suchtext."""
        self._search_text = text.strip().lower()
        # Suchfelder synchron halten
        for field in [self._gs_search, self._zahl_search, self._skonto_search]:
            if field.text().strip().lower() != self._search_text:
                field.blockSignals(True)
                field.setText(text)
                field.blockSignals(False)
        self._refresh_ui()

    def _matches_search(self, dto: RechnungDTO, q: str) -> bool:
        """Prüft ob ein DTO zum Suchtext passt (inkl. Kundennummer)."""
        if not q:
            return True
        if q in dto.rechnungsnummer.lower():
            return True
        if q in dto.kunde_display.lower():
            return True
        if dto.kunde_zifferncode is not None and q in str(dto.kunde_zifferncode):
            return True
        return False

    def _refresh_ui(self) -> None:
        # Tab 1: Gutschriften
        q = self._search_text
        self._gefilterte_korrekturen = [
            dto for dto in self._alle_korrekturen
            if self._matches_search(dto, q)
        ]
        gs_rows = []
        for dto in self._gefilterte_korrekturen:
            typ = "Storniert" if dto.status == RechnungStatus.STORNIERT else "Gutschrift"
            gs_rows.append([
                dto.id,
                dto.rechnungsnummer,
                dto.rechnungsdatum,
                dto.kunde_display,
                typ,
                _fmt(dto.summe_brutto),
                dto.storno_zu_nr or "–",
                dto.status,
            ])
        self._gs_table.set_data(gs_rows)
        n = len(gs_rows)
        stornos   = sum(1 for d in self._alle_korrekturen if d.status == RechnungStatus.STORNIERT)
        gutschr   = sum(1 for d in self._alle_korrekturen if d.status == RechnungStatus.GUTSCHRIFT)
        self._gs_summary.setText(
            f"{n} Einträge  ·  {stornos} Storno(s)  ·  {gutschr} Gutschrift(en)"
        )

        # Tab 2 & 3: Offene Rechnungen
        self._gefilterte_korrigierbar = [
            dto for dto in self._korrigierbar
            if self._matches_search(dto, q)
        ]
        rows = []
        for dto in self._gefilterte_korrigierbar:
            rows.append([
                dto.id,
                dto.rechnungsnummer,
                dto.rechnungsdatum,
                dto.kunde_display,
                dto.faelligkeitsdatum or "–",
                _fmt(dto.summe_brutto),
                _fmt(dto.offener_betrag),
                dto.status,
            ])
        self._zahl_table.set_data(rows)
        self._skonto_table.set_data(rows)

    # ------------------------------------------------------------------
    # Kontextmenüs
    # ------------------------------------------------------------------

    def _gs_context_menu(self, pos) -> None:
        row = self._gs_table.current_source_row()
        if row < 0 or row >= len(self._gefilterte_korrekturen):
            return
        dto = self._gefilterte_korrekturen[row]

        menu = self._make_menu()
        menu.addAction("📖  Rechnung öffnen").triggered.connect(
            lambda: self._rechnung_oeffnen(dto)
        )
        menu.addAction("🖨  PDF erstellen").triggered.connect(
            lambda: self._pdf_export(dto)
        )
        menu.addSeparator()
        menu.addAction("📂  Kundendokumente").triggered.connect(
            lambda: self._show_kunde_documents(dto)
        )
        menu.addAction("📧  E-Mail senden").triggered.connect(
            lambda: self._send_email(dto)
        )
        menu.exec(self._gs_table.viewport().mapToGlobal(pos))

    def _zahl_context_menu(self, pos) -> None:
        row = self._zahl_table.current_source_row()
        if row < 0 or row >= len(self._gefilterte_korrigierbar):
            return
        dto = self._gefilterte_korrigierbar[row]

        menu = self._make_menu()
        menu.addAction("💶  Teilzahlung erfassen").triggered.connect(
            lambda: self._teilzahlung(dto)
        )
        menu.addSeparator()
        menu.addAction("📖  Rechnung öffnen").triggered.connect(
            lambda: self._rechnung_oeffnen(dto)
        )
        menu.addSeparator()
        menu.addAction("📂  Kundendokumente").triggered.connect(
            lambda: self._show_kunde_documents(dto)
        )
        menu.addAction("📧  E-Mail senden").triggered.connect(
            lambda: self._send_email(dto)
        )
        menu.exec(self._zahl_table.viewport().mapToGlobal(pos))

    def _skonto_context_menu(self, pos) -> None:
        row = self._skonto_table.current_source_row()
        if row < 0 or row >= len(self._gefilterte_korrigierbar):
            return
        dto = self._gefilterte_korrigierbar[row]

        menu = self._make_menu()
        menu.addAction("🏷  Skonto / Rabatt gewähren").triggered.connect(
            lambda: self._skonto(dto)
        )
        menu.addAction("📝  Teilkorrektur / Teil-Gutschrift").triggered.connect(
            lambda: self._teilkorrektur(dto)
        )
        menu.addSeparator()
        menu.addAction("📖  Rechnung öffnen").triggered.connect(
            lambda: self._rechnung_oeffnen(dto)
        )
        menu.addSeparator()
        menu.addAction("📂  Kundendokumente").triggered.connect(
            lambda: self._show_kunde_documents(dto)
        )
        menu.addAction("📧  E-Mail senden").triggered.connect(
            lambda: self._send_email(dto)
        )
        menu.exec(self._skonto_table.viewport().mapToGlobal(pos))

    def _make_menu(self) -> QMenu:
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
        return menu

    # ------------------------------------------------------------------
    # Kundendokumente & E-Mail
    # ------------------------------------------------------------------

    def _show_kunde_documents(self, dto: RechnungDTO) -> None:
        """Öffnet den Dokumenten-Dialog für den Kunden der Rechnung."""
        try:
            from core.services.kunden_service import kunden_service
            from ui.modules.kunden.dokumente_dialog import DokumenteDialog
            with db.session() as session:
                kunde_dto = kunden_service.nach_id(session, dto.kunde_id)
            if not kunde_dto:
                self._banner.show_error("Kunde nicht gefunden.")
                return
            dlg = DokumenteDialog(kunde_dto, parent=self)
            dlg.exec()
        except Exception as e:
            self._banner.show_error(f"Fehler beim Öffnen der Dokumente: {e}")

    def _send_email(self, dto: RechnungDTO) -> None:
        """Öffnet das System-Mailprogramm mit der Kundenadresse."""
        import urllib.parse
        try:
            from core.services.kunden_service import kunden_service
            with db.session() as session:
                kunde_dto = kunden_service.nach_id(session, dto.kunde_id)
            if not kunde_dto:
                self._banner.show_error("Kunde nicht gefunden.")
                return
            empfaenger = kunde_dto.email or ""
            betreff = urllib.parse.quote(f"Rechnung {dto.rechnungsnummer}")
            empf_enc = urllib.parse.quote(empfaenger)
            mailto = f"mailto:{empf_enc}?subject={betreff}"
            import os, sys
            if sys.platform == "win32":
                os.startfile(mailto)
            elif sys.platform == "darwin":
                import subprocess
                subprocess.run(["open", mailto])
            else:
                import subprocess
                subprocess.run(["xdg-open", mailto])
        except Exception as e:
            self._banner.show_error(f"E-Mail konnte nicht geöffnet werden: {e}")

    # ------------------------------------------------------------------
    # Aktionen
    # ------------------------------------------------------------------

    def _rechnung_oeffnen(self, dto: RechnungDTO) -> None:
        from ui.modules.rechnungen.dialog import RechnungDialog
        with db.session() as session:
            full_dto = rechnungen_service.nach_id(session, dto.id)
        if not full_dto:
            self._banner.show_error("Rechnung nicht gefunden.")
            return
        dlg = RechnungDialog(
            parent=self,
            dto=full_dto,
            kunde_name=dto.kunde_display,
            title=f"Rechnung {full_dto.rechnungsnummer}",
        )
        dlg.exec()
        self._load_data()

    def _pdf_export(self, dto: RechnungDTO) -> None:
        from core.services.pdf_service import pdf_service
        with db.session() as session:
            full_dto = rechnungen_service.nach_id(session, dto.id)
            if not full_dto:
                self._banner.show_error("Rechnung nicht gefunden.")
                return
            ok, ergebnis = pdf_service.rechnung_als_datei(full_dto, session=session)
            if ok:
                try:
                    kunden_service.dokument_in_kundenordner_erstellen(
                        session, dto.kunde_id, ergebnis
                    )
                except Exception:
                    pass
        if ok:
            import os
            self._banner.show_success(f"PDF erstellt: {os.path.basename(ergebnis)}")
        else:
            self._banner.show_error(f"PDF-Fehler: {ergebnis}")

    def _teilzahlung(self, dto: RechnungDTO) -> None:
        with db.session() as session:
            full_dto = rechnungen_service.nach_id(session, dto.id)
        if not full_dto:
            self._banner.show_error("Rechnung nicht gefunden.")
            return

        dlg = _TeilzahlungDialog(full_dto, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            dlg.deleteLater()
            return

        daten = dlg.get_daten()
        dlg.deleteLater()
        with db.session() as session:
            result = rechnungen_service.teilzahlung_buchen(
                session,
                full_dto.id,
                betrag=daten["betrag"],
                datum=daten["datum"],
                bemerkung_zusatz=daten["bemerkung"],
            )
        if result.success:
            self._banner.show_success(result.message)
            self._load_data()
        else:
            self._banner.show_error(result.message)

    def _skonto(self, dto: RechnungDTO) -> None:
        with db.session() as session:
            full_dto = rechnungen_service.nach_id(session, dto.id)
        if not full_dto:
            self._banner.show_error("Rechnung nicht gefunden.")
            return

        dlg = _SkontoDialog(full_dto, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            dlg.deleteLater()
            return

        daten = dlg.get_daten()
        dlg.deleteLater()
        try:
            with db.session() as session:
                result = rechnungen_service.skonto_gewaehren(
                    session,
                    full_dto.id,
                    prozent=daten["prozent"],
                    betrag=daten["betrag"],
                    bemerkung_zusatz=daten["bemerkung"],
                )
        except Exception as e:
            logger.exception("Skonto-Fehler")
            QMessageBox.critical(self, "Fehler", f"Datenbankfehler:\n{e}")
            return

        if result.success:
            self._banner.show_success(result.message)
            self._load_data()
            QMessageBox.information(
                self, "Skonto gewährt",
                f"✅ {result.message}\n\n"
                f"Rechnung: {full_dto.rechnungsnummer}\n"
                f"Neuer offener Betrag: {_fmt(result.data.get('offener_betrag', 0))}",
            )
        else:
            self._banner.show_error(result.message)
            QMessageBox.warning(self, "Skonto fehlgeschlagen", result.message)

    def _teilkorrektur(self, dto: RechnungDTO) -> None:
        with db.session() as session:
            full_dto = rechnungen_service.nach_id(session, dto.id)
        if not full_dto:
            self._banner.show_error("Rechnung nicht gefunden.")
            return

        dlg = _TeilkorrekturDialog(full_dto, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            dlg.deleteLater()
            return

        daten = dlg.get_daten()
        dlg.deleteLater()
        mwst = full_dto.mwst_prozent / Decimal("100")
        netto = daten["netto"]
        mwst_betrag = (netto * mwst).quantize(Decimal("0.01"))
        brutto = netto + mwst_betrag

        if not ConfirmDialog.ask(
            title="Teil-Gutschrift erstellen",
            message=f"Teil-Gutschrift über {_fmt(brutto)} erstellen?",
            detail=(
                f"Zu: {full_dto.rechnungsnummer}\n"
                f"Beschreibung: {daten['beschreibung']}\n"
                f"Netto: {_fmt(netto)}  MwSt: {_fmt(mwst_betrag)}  Brutto: {_fmt(brutto)}"
            ),
            confirm_text="Teil-Gutschrift erstellen",
            parent=self,
        ):
            return

        try:
            with db.session() as session:
                result = rechnungen_service.teilgutschrift_erstellen(
                    session,
                    rechnung_id=full_dto.id,
                    beschreibung=daten["beschreibung"],
                    netto=netto,
                    mwst_prozent=full_dto.mwst_prozent,
                    grund=daten["grund"],
                )
        except Exception as e:
            logger.exception("Teilgutschrift-Fehler")
            QMessageBox.critical(self, "Fehler", f"Datenbankfehler:\n{e}")
            return

        if result.success:
            self._banner.show_success(result.message)
            self._load_data()
            QMessageBox.information(
                self, "Teil-Gutschrift erstellt",
                f"✅ {result.message}\n\n"
                f"Originalrechnung: {full_dto.rechnungsnummer}\n"
                f"Gutschrift-Nr: {result.data.get('gutschrift_nummer', '–')}",
            )
        else:
            self._banner.show_error(result.message)
            QMessageBox.warning(self, "Fehler", result.message)
