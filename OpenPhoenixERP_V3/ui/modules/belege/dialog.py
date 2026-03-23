"""
ui/modules/belege/dialog.py – Dialog zum Erfassen und Bearbeiten von Belegen
=============================================================================
Formular für Eingangsrechnungen / Belege inkl. Datei-Upload.
"""

import logging
from decimal import Decimal, InvalidOperation
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFrame,
    QLabel, QPushButton, QWidget, QScrollArea,
    QComboBox, QTextEdit, QFileDialog,
)

from core.db.engine import db
from core.services.belege_service import (
    belege_service, EingangsRechnungDTO, BelegKategorie, Zahlungsstatus,
)
from ui.components.widgets import FormField, SectionTitle, NotificationBanner
from ui.theme.theme import Colors, Fonts, Spacing, Radius

logger = logging.getLogger(__name__)


class BelegDialog(QDialog):
    """
    Dialog zum Anlegen und Bearbeiten von Eingangsrechnungen / Belegen.

    Signals:
        saved(EingangsRechnungDTO): Enthält den gespeicherten Beleg.
    """

    saved = Signal(object)

    def __init__(self, parent=None, dto: EingangsRechnungDTO = None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._edit_mode = dto is not None
        self._original = dto
        self._datei_bytes: bytes | None = None
        self._datei_name: str | None = None
        self.setWindowTitle(
            "Beleg bearbeiten" if dto else "Neuer Beleg"
        )
        self.setModal(True)
        self.setMinimumSize(600, 620)
        self.resize(650, 700)
        self._build_ui()
        if dto:
            self._populate(dto)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())

        self._banner = NotificationBanner()
        wrapper = QWidget()
        wl = QVBoxLayout(wrapper)
        wl.setContentsMargins(Spacing.XL, Spacing.SM, Spacing.XL, 0)
        wl.addWidget(self._banner)
        root.addWidget(wrapper)

        scroll = QScrollArea()
        scroll.setObjectName("belegDialogScroll")
        scroll.setStyleSheet(f"#belegDialogScroll {{ background-color: {Colors.BG_APP}; border: none; }}")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self._build_form())
        root.addWidget(scroll, 1)

        root.addWidget(self._build_footer())

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setFixedHeight(56)
        header.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.BG_SURFACE};
                border-bottom: 1px solid {Colors.BORDER};
            }}
        """)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(Spacing.XL, 0, Spacing.XL, 0)

        icon = QLabel("📥")
        icon.setStyleSheet("font-size: 20px; background: transparent;")
        layout.addWidget(icon)
        layout.addSpacing(Spacing.SM)

        title = QLabel(self.windowTitle())
        title.setFont(Fonts.heading3())
        title.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; background: transparent;")
        layout.addWidget(title)
        layout.addStretch()

        return header

    def _build_form(self) -> QWidget:
        form = QWidget()
        form.setObjectName("belegDialogForm")
        form.setStyleSheet(f"#belegDialogForm {{ background-color: {Colors.BG_APP}; }}")
        layout = QVBoxLayout(form)
        layout.setContentsMargins(Spacing.XL, Spacing.MD, Spacing.XL, Spacing.XL)
        layout.setSpacing(Spacing.MD)

        # --- Belegdaten ---
        layout.addWidget(SectionTitle("Belegdaten"))

        row1 = QHBoxLayout()
        row1.setSpacing(Spacing.MD)
        self._f_datum = FormField("Datum *", placeholder="TT.MM.JJJJ")
        self._f_belegnummer = FormField("Belegnummer", placeholder="z.B. RE-2026-001")
        row1.addWidget(self._f_datum)
        row1.addWidget(self._f_belegnummer)
        layout.addLayout(row1)

        self._f_lieferant = FormField(
            "Lieferant / Absender *", placeholder="z.B. Bauhaus, Shell, Amazon"
        )
        layout.addWidget(self._f_lieferant)

        # --- Beträge ---
        layout.addWidget(SectionTitle("Beträge"))

        row2 = QHBoxLayout()
        row2.setSpacing(Spacing.MD)
        self._f_netto = FormField("Betrag netto (€) *", placeholder="0,00")
        row2.addWidget(self._f_netto)

        # MwSt-Satz Dropdown
        mwst_widget = QWidget()
        mwst_layout = QVBoxLayout(mwst_widget)
        mwst_layout.setContentsMargins(0, 0, 0, 0)
        mwst_layout.setSpacing(4)
        mwst_label = QLabel("MwSt-Satz")
        mwst_label.setFont(Fonts.caption())
        mwst_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        mwst_layout.addWidget(mwst_label)
        self._cb_mwst = QComboBox()
        self._cb_mwst.addItem("19 %", Decimal("19.00"))
        self._cb_mwst.addItem("7 %", Decimal("7.00"))
        self._cb_mwst.addItem("0 %", Decimal("0.00"))
        self._cb_mwst.setFixedHeight(38)
        mwst_layout.addWidget(self._cb_mwst)
        row2.addWidget(mwst_widget)

        # Brutto (berechnet)
        brutto_widget = QWidget()
        brutto_layout = QVBoxLayout(brutto_widget)
        brutto_layout.setContentsMargins(0, 0, 0, 0)
        brutto_layout.setSpacing(4)
        brutto_label = QLabel("Bruttobetrag")
        brutto_label.setFont(Fonts.caption())
        brutto_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        brutto_layout.addWidget(brutto_label)
        self._lbl_brutto = QLabel("0,00 €")
        self._lbl_brutto.setFont(Fonts.get(Fonts.SIZE_LG, bold=True))
        self._lbl_brutto.setStyleSheet(
            f"color: {Colors.SUCCESS}; padding: 8px 0;"
        )
        brutto_layout.addWidget(self._lbl_brutto)
        row2.addWidget(brutto_widget)

        layout.addLayout(row2)

        # Auto-Berechnung
        self._f_netto.value_changed.connect(self._update_brutto)
        self._cb_mwst.currentIndexChanged.connect(
            lambda _: self._update_brutto()
        )

        # --- Kategorisierung ---
        layout.addWidget(SectionTitle("Kategorisierung"))

        row3 = QHBoxLayout()
        row3.setSpacing(Spacing.MD)

        kat_widget = QWidget()
        kat_layout = QVBoxLayout(kat_widget)
        kat_layout.setContentsMargins(0, 0, 0, 0)
        kat_layout.setSpacing(4)
        kat_label = QLabel("Kategorie *")
        kat_label.setFont(Fonts.caption())
        kat_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        kat_layout.addWidget(kat_label)
        self._cb_kategorie = QComboBox()
        for kat in BelegKategorie.alle():
            self._cb_kategorie.addItem(kat, kat)
        self._cb_kategorie.setFixedHeight(38)
        kat_layout.addWidget(self._cb_kategorie)
        row3.addWidget(kat_widget)

        status_widget = QWidget()
        status_layout = QVBoxLayout(status_widget)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(4)
        status_label = QLabel("Zahlungsstatus")
        status_label.setFont(Fonts.caption())
        status_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        status_layout.addWidget(status_label)
        self._cb_status = QComboBox()
        for st in Zahlungsstatus.ALLE:
            self._cb_status.addItem(st, st)
        self._cb_status.setFixedHeight(38)
        status_layout.addWidget(self._cb_status)
        row3.addWidget(status_widget)

        layout.addLayout(row3)

        # --- Bemerkung ---
        layout.addWidget(SectionTitle("Bemerkung"))
        self._txt_bemerkung = QTextEdit()
        self._txt_bemerkung.setPlaceholderText("Optionale Notizen zum Beleg…")
        self._txt_bemerkung.setMaximumHeight(100)
        self._txt_bemerkung.setStyleSheet(f"""
            QTextEdit {{
                background-color: {Colors.BG_INPUT};
                color: {Colors.TEXT_PRIMARY};
                border: 1px solid {Colors.BORDER};
                border-radius: {Radius.SM}px;
                padding: 8px;
                font-size: {Fonts.SIZE_BASE}pt;
            }}
            QTextEdit:focus {{
                border: 1px solid {Colors.PRIMARY};
            }}
        """)
        layout.addWidget(self._txt_bemerkung)

        # --- Belegdatei ---
        layout.addWidget(SectionTitle("Belegdatei (PDF / Bild)"))

        file_row = QHBoxLayout()
        file_row.setSpacing(Spacing.SM)

        self._btn_datei = QPushButton("📂  Datei auswählen…")
        self._btn_datei.setProperty("role", "secondary")
        self._btn_datei.clicked.connect(self._datei_auswaehlen)
        file_row.addWidget(self._btn_datei)

        self._lbl_datei = QLabel("Keine Datei ausgewählt")
        self._lbl_datei.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        self._lbl_datei.setFont(Fonts.caption())
        file_row.addWidget(self._lbl_datei, 1)

        layout.addLayout(file_row)

        layout.addStretch()
        return form

    def _build_footer(self) -> QFrame:
        footer = QFrame()
        footer.setObjectName("belegDialogFooter")
        footer.setFixedHeight(60)
        footer.setStyleSheet(f"""
            #belegDialogFooter {{
                background-color: {Colors.BG_SURFACE};
                border-top: 1px solid {Colors.BORDER};
            }}
        """)
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(Spacing.XL, 0, Spacing.XL, 0)

        btn_cancel = QPushButton("Abbrechen")
        btn_cancel.setProperty("role", "secondary")
        btn_cancel.clicked.connect(self.reject)
        layout.addWidget(btn_cancel)

        layout.addStretch()

        btn_save = QPushButton(
            "💾  Übernehmen" if self._edit_mode else "💾  Anlegen"
        )
        btn_save.clicked.connect(self._save)
        layout.addWidget(btn_save)

        return footer

    # ------------------------------------------------------------------
    # Daten befüllen (Edit-Modus)
    # ------------------------------------------------------------------

    def _populate(self, dto: EingangsRechnungDTO) -> None:
        self._f_datum.set_value(dto.datum)
        self._f_belegnummer.set_value(dto.belegnummer)
        self._f_lieferant.set_value(dto.lieferant)
        self._f_netto.set_value(
            str(dto.betrag_netto).replace(".", ",")
        )

        # MwSt-Satz
        mwst_map = {Decimal("19.00"): 0, Decimal("7.00"): 1, Decimal("0.00"): 2}
        self._cb_mwst.setCurrentIndex(mwst_map.get(dto.mwst_satz, 0))

        # Kategorie
        idx = self._cb_kategorie.findData(dto.kategorie)
        if idx >= 0:
            self._cb_kategorie.setCurrentIndex(idx)

        # Status
        idx = self._cb_status.findData(dto.zahlungsstatus)
        if idx >= 0:
            self._cb_status.setCurrentIndex(idx)

        # Bemerkung
        if dto.bemerkung:
            self._txt_bemerkung.setPlainText(dto.bemerkung)

        # Datei-Anzeige
        if dto.beleg_dateiname:
            self._lbl_datei.setText(f"📄 {dto.beleg_dateiname}")
            self._lbl_datei.setStyleSheet(f"color: {Colors.TEXT_PRIMARY};")

        self._update_brutto()

    # ------------------------------------------------------------------
    # Auto-Berechnung
    # ------------------------------------------------------------------

    def _update_brutto(self, _text: str = "") -> None:
        try:
            netto_text = self._f_netto.value().replace(".", "").replace(",", ".").strip()
            netto = Decimal(netto_text) if netto_text else Decimal("0")
        except InvalidOperation:
            netto = Decimal("0")

        mwst_satz = self._cb_mwst.currentData() or Decimal("19.00")
        mwst = netto * mwst_satz / Decimal("100")
        brutto = netto + mwst

        brutto_str = f"{float(brutto):,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
        self._lbl_brutto.setText(brutto_str)

    # ------------------------------------------------------------------
    # Datei-Upload
    # ------------------------------------------------------------------

    def _datei_auswaehlen(self) -> None:
        pfad, _ = QFileDialog.getOpenFileName(
            self,
            "Belegdatei auswählen",
            "",
            "Alle Belege (*.pdf *.png *.jpg *.jpeg *.bmp *.tiff);;"
            "PDF-Dateien (*.pdf);;"
            "Bilder (*.png *.jpg *.jpeg *.bmp *.tiff);;"
            "Alle Dateien (*)",
        )
        if not pfad:
            return

        path_obj = Path(pfad)
        try:
            self._datei_bytes = path_obj.read_bytes()
            self._datei_name = path_obj.name
            self._lbl_datei.setText(f"📄 {path_obj.name}")
            self._lbl_datei.setStyleSheet(f"color: {Colors.SUCCESS};")
        except Exception as e:
            self._banner.show_error(f"Datei konnte nicht gelesen werden: {e}")

    # ------------------------------------------------------------------
    # Speichern
    # ------------------------------------------------------------------

    def _save(self) -> None:
        # Netto parsen
        try:
            netto_text = self._f_netto.value().replace(".", "").replace(",", ".").strip()
            betrag_netto = Decimal(netto_text) if netto_text else Decimal("0")
        except InvalidOperation:
            self._banner.show_error("Ungültiger Nettobetrag.")
            return

        mwst_satz = self._cb_mwst.currentData() or Decimal("19.00")

        dto = EingangsRechnungDTO(
            id=self._original.id if self._original else None,
            datum=self._f_datum.value().strip(),
            lieferant=self._f_lieferant.value().strip(),
            belegnummer=self._f_belegnummer.value().strip(),
            betrag_netto=betrag_netto,
            mwst_satz=mwst_satz,
            mwst_betrag=Decimal("0"),  # wird vom Service berechnet
            betrag_brutto=Decimal("0"),  # wird vom Service berechnet
            kategorie=self._cb_kategorie.currentData() or BelegKategorie.SONSTIGES,
            bemerkung=self._txt_bemerkung.toPlainText().strip(),
            zahlungsstatus=self._cb_status.currentData() or Zahlungsstatus.OFFEN,
            beleg_pfad=self._original.beleg_pfad if self._original else None,
            beleg_dateiname=self._original.beleg_dateiname if self._original else None,
        )

        try:
            with db.session() as session:
                if self._edit_mode and self._original:
                    result = belege_service.beleg_aktualisieren(
                        session,
                        self._original.id,
                        dto,
                        datei_bytes=self._datei_bytes,
                        datei_name=self._datei_name,
                    )
                else:
                    result = belege_service.beleg_erstellen(
                        session,
                        dto,
                        datei_bytes=self._datei_bytes,
                        datei_name=self._datei_name,
                    )
        except Exception as e:
            self._banner.show_error(f"Fehler beim Speichern: {e}")
            logger.exception("Beleg speichern fehlgeschlagen")
            return

        if result.success:
            self.saved.emit(result.data)
            self.accept()
        else:
            self._banner.show_error(result.message)
