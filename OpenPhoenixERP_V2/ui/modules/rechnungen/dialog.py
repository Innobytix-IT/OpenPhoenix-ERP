"""
ui/modules/rechnungen/dialog.py – Rechnung erstellen und bearbeiten
====================================================================
Vollständiger Rechnungsdialog mit Postenverwaltung,
Summenberechnung und Finalisierungs-Schutz.
"""

from decimal import Decimal
from datetime import datetime, timedelta

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFrame, QScrollArea,
    QWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QComboBox,
    QTextEdit,
)

from core.db.engine import db
from core.services.rechnungen_service import (
    RechnungDTO, PostenDTO, RechnungStatus,
    rechnungen_service, berechne_summen,
)
from core.models import Artikel
from ui.components.widgets import (
    FormField, SectionTitle, NotificationBanner, ConfirmDialog,
)
from ui.theme.theme import Colors, Fonts, Spacing, Radius


class RechnungDialog(QDialog):
    """
    Dialog zum Erstellen und Bearbeiten von Rechnungen.

    Im Entwurfsmodus: alle Felder editierbar.
    Im finalisierten Modus: nur Status und Bemerkung änderbar.

    Signals:
        saved(RechnungDTO):       Beim Speichern (Entwurf)
        finalized(int):           Beim Finalisieren (Rechnung-ID)
        status_changed(int, str): Beim Statuswechsel (ID, neuer Status)
    """

    saved = Signal(object)       # RechnungDTO
    finalized = Signal(int)      # rechnung_id
    status_changed = Signal(int, str)

    def __init__(
        self,
        parent=None,
        dto: RechnungDTO = None,
        kunde_id: int = None,
        kunde_name: str = "",
        title: str = "Neue Rechnung",
    ):
        super().__init__(parent)
        self._dto = dto
        self._kunde_id = kunde_id or (dto.kunde_id if dto else None)
        self._kunde_name = kunde_name or (dto.kunde_display if dto else "")
        self._edit_mode = dto is not None
        self._is_finalized = dto.is_finalized if dto else False
        self._posten: list[PostenDTO] = list(dto.posten) if (dto and dto.posten) else []
        self._artikel_cache: list = []

        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumSize(900, 700)
        self.resize(1000, 780)

        self._load_artikel_cache()
        self._build_ui()
        if dto:
            self._populate(dto)
        self._update_summen()

    # ------------------------------------------------------------------
    # Artikelstamm laden (für Dropdown in Postendialog)
    # ------------------------------------------------------------------

    def _load_artikel_cache(self) -> None:
        try:
            with db.session() as session:
                artikel = (
                    session.query(Artikel)
                    .filter_by(is_active=True)
                    .order_by(Artikel.beschreibung)
                    .all()
                )
                self._artikel_cache = [
                    {
                        "artikelnummer": a.artikelnummer,
                        "beschreibung": a.beschreibung,
                        "einheit": a.einheit or "",
                        "einzelpreis_netto": Decimal(str(a.einzelpreis_netto or "0")),
                    }
                    for a in artikel
                ]
        except Exception:
            self._artikel_cache = []

    # ------------------------------------------------------------------
    # UI aufbauen
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())

        # Finalisierungs-Warnung
        if self._is_finalized:
            warning = QFrame()
            warning.setStyleSheet(f"""
                background-color: {Colors.WARNING_BG};
                border-bottom: 1px solid {Colors.WARNING};
                padding: 8px;
            """)
            w_layout = QHBoxLayout(warning)
            w_layout.setContentsMargins(Spacing.XL, Spacing.SM, Spacing.XL, Spacing.SM)
            w_lbl = QLabel(
                "⚠  Diese Rechnung ist finalisiert und GoBD-geschützt. "
                "Nur Status und Bemerkung können geändert werden."
            )
            w_lbl.setFont(Fonts.get(Fonts.SIZE_SM, bold=True))
            w_lbl.setStyleSheet(f"color: {Colors.WARNING}; background: transparent;")
            w_layout.addWidget(w_lbl)
            root.addWidget(warning)

        self._banner = NotificationBanner()
        banner_wrap = QWidget()
        bw_layout = QVBoxLayout(banner_wrap)
        bw_layout.setContentsMargins(Spacing.XL, Spacing.SM, Spacing.XL, 0)
        bw_layout.addWidget(self._banner)
        root.addWidget(banner_wrap)

        # Scrollbereich mit Hauptinhalt
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")
        scroll.setWidget(self._build_content())
        root.addWidget(scroll, 1)

        root.addWidget(self._build_footer())

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setFixedHeight(64)
        header.setStyleSheet(f"""
            background-color: {Colors.BG_SURFACE};
            border-bottom: 1px solid {Colors.BORDER};
        """)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(Spacing.XL, 0, Spacing.XL, 0)

        icon = QLabel("🧾")
        icon.setStyleSheet("font-size: 22px; background: transparent;")
        title_lbl = QLabel(self.windowTitle())
        title_lbl.setFont(Fonts.heading3())
        title_lbl.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; background: transparent;")

        layout.addWidget(icon)
        layout.addSpacing(Spacing.SM)
        layout.addWidget(title_lbl)
        layout.addStretch()

        if self._kunde_name:
            kunde_lbl = QLabel(f"👤 {self._kunde_name}")
            kunde_lbl.setFont(Fonts.get(Fonts.SIZE_SM))
            kunde_lbl.setStyleSheet(f"""
                background-color: {Colors.BG_ELEVATED};
                color: {Colors.TEXT_SECONDARY};
                border-radius: {Radius.SM}px;
                padding: 4px 12px;
            """)
            layout.addWidget(kunde_lbl)

        return header

    def _build_content(self) -> QWidget:
        content = QWidget()
        content.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(Spacing.XL, Spacing.LG, Spacing.XL, Spacing.LG)
        layout.setSpacing(Spacing.SM)

        readonly = self._is_finalized

        # ── Rechnungskopf ─────────────────────────────────────────
        layout.addWidget(SectionTitle("Rechnungsdaten"))
        row1 = QHBoxLayout()
        row1.setSpacing(Spacing.MD)

        self.f_nummer = FormField(
            "Rechnungsnummer *", required=True, placeholder="z.B. 2025-0001"
        )
        if readonly:
            self.f_nummer.set_read_only(True)

        self.f_datum = FormField("Rechnungsdatum *", required=True, placeholder="TT.MM.JJJJ")
        self.f_datum.setFixedWidth(160)
        if readonly:
            self.f_datum.set_read_only(True)

        self.f_faellig = FormField("Fälligkeitsdatum", placeholder="TT.MM.JJJJ")
        self.f_faellig.setFixedWidth(160)
        if readonly:
            self.f_faellig.set_read_only(True)

        row1.addWidget(self.f_nummer, 2)
        row1.addWidget(self.f_datum)
        row1.addWidget(self.f_faellig)
        layout.addLayout(row1)

        # MwSt
        row2 = QHBoxLayout()
        mwst_widget = QWidget()
        mwst_layout = QVBoxLayout(mwst_widget)
        mwst_layout.setContentsMargins(0, 0, 0, 0)
        mwst_layout.setSpacing(4)
        mwst_lbl = QLabel("MwSt-Satz")
        mwst_lbl.setFont(Fonts.get(Fonts.SIZE_SM))
        mwst_lbl.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        self._mwst_combo = QComboBox()
        self._mwst_combo.addItems(["7,00 %", "19,00 %", "0,00 %"])
        self._mwst_combo.setCurrentText("19,00 %")
        self._mwst_combo.setFixedWidth(120)
        self._mwst_combo.setEnabled(not readonly)
        self._mwst_combo.currentTextChanged.connect(self._update_summen)
        mwst_layout.addWidget(mwst_lbl)
        mwst_layout.addWidget(self._mwst_combo)
        row2.addWidget(mwst_widget)
        row2.addStretch()
        layout.addLayout(row2)

        # Status (nur finalisiert)
        if self._is_finalized:
            layout.addWidget(SectionTitle("Status"))
            status_row = QHBoxLayout()
            status_lbl = QLabel("Status:")
            status_lbl.setFont(Fonts.get(Fonts.SIZE_SM))
            status_lbl.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
            self._status_combo = QComboBox()
            self._status_combo.addItems(RechnungStatus.MANUELL_SETZBAR)
            if self._dto:
                idx = self._status_combo.findText(self._dto.status)
                if idx >= 0:
                    self._status_combo.setCurrentIndex(idx)
            self._status_combo.setFixedWidth(260)
            status_row.addWidget(status_lbl)
            status_row.addWidget(self._status_combo)
            status_row.addStretch()
            layout.addLayout(status_row)

        # ── Posten ────────────────────────────────────────────────
        layout.addWidget(SectionTitle("Rechnungsposten"))

        # Toolbar über der Postentabelle
        if not readonly:
            posten_toolbar = QHBoxLayout()
            add_posten_btn = QPushButton("➕  Posten hinzufügen")
            add_posten_btn.clicked.connect(self._add_posten)
            posten_toolbar.addWidget(add_posten_btn)
            posten_toolbar.addStretch()
            layout.addLayout(posten_toolbar)

        self._posten_table = self._build_posten_table(readonly)
        layout.addWidget(self._posten_table)

        # ── Summen ────────────────────────────────────────────────
        layout.addWidget(self._build_summen_widget())

        # ── Bemerkung ─────────────────────────────────────────────
        layout.addWidget(SectionTitle("Bemerkung"))
        bemerkung_lbl = QLabel("Interne Notizen / Zahlungshinweise:")
        bemerkung_lbl.setFont(Fonts.get(Fonts.SIZE_SM))
        bemerkung_lbl.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        layout.addWidget(bemerkung_lbl)

        self._bemerkung_edit = QTextEdit()
        self._bemerkung_edit.setFixedHeight(100)
        self._bemerkung_edit.setPlaceholderText(
            "Optionale Bemerkungen, Zahlungsbedingungen, Hinweise..."
        )
        layout.addWidget(self._bemerkung_edit)

        return content

    def _build_posten_table(self, readonly: bool) -> QTableWidget:
        columns = ["Pos.", "ArtNr.", "Beschreibung", "Menge", "Einheit", "Einzelpreis", "Gesamt"]
        if not readonly:
            columns.append("Aktionen")

        table = QTableWidget(0, len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.verticalHeader().setVisible(False)
        table.setShowGrid(False)
        table.setMinimumHeight(180)

        header = table.horizontalHeader()
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)  # Beschreibung
        table.setColumnWidth(0, 50)   # Pos
        table.setColumnWidth(1, 90)   # ArtNr
        table.setColumnWidth(3, 80)   # Menge
        table.setColumnWidth(4, 80)   # Einheit
        table.setColumnWidth(5, 110)  # Einzelpreis
        table.setColumnWidth(6, 110)  # Gesamt
        if not readonly:
            table.setColumnWidth(7, 120)  # Aktionen

        table.verticalHeader().setDefaultSectionSize(44)

        if not readonly:
            table.doubleClicked.connect(self._edit_posten_by_click)

        return table

    def _build_summen_widget(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.BG_SURFACE};
                border-radius: {Radius.LG}px;
                border: 1px solid {Colors.BORDER};
            }}
        """)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(Spacing.XL, Spacing.LG, Spacing.XL, Spacing.LG)

        def summen_row(label: str, value_attr: str, bold: bool = False, big: bool = False):
            row = QHBoxLayout()
            lbl = QLabel(label)
            font_size = Fonts.SIZE_LG if big else Fonts.SIZE_BASE
            lbl.setFont(Fonts.get(font_size, bold=bold))
            lbl.setStyleSheet(f"color: {Colors.TEXT_SECONDARY if not big else Colors.TEXT_PRIMARY}; background: transparent;")
            val = QLabel("0,00 €")
            val.setFont(Fonts.get(font_size, bold=bold))
            val.setStyleSheet(f"color: {Colors.PRIMARY if big else Colors.TEXT_PRIMARY}; background: transparent;")
            val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(lbl)
            row.addStretch()
            row.addWidget(val)
            setattr(self, value_attr, val)
            layout.addLayout(row)

        summen_row("Nettobetrag:", "_lbl_netto")

        # MwSt-Zeile
        mwst_row = QHBoxLayout()
        self._lbl_mwst_titel = QLabel("MwSt (19,00 %):")
        self._lbl_mwst_titel.setFont(Fonts.get(Fonts.SIZE_BASE))
        self._lbl_mwst_titel.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; background: transparent;")
        self._lbl_mwst = QLabel("0,00 €")
        self._lbl_mwst.setFont(Fonts.get(Fonts.SIZE_BASE))
        self._lbl_mwst.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; background: transparent;")
        self._lbl_mwst.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        mwst_row.addWidget(self._lbl_mwst_titel)
        mwst_row.addStretch()
        mwst_row.addWidget(self._lbl_mwst)
        layout.addLayout(mwst_row)

        # Trennlinie
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background-color: {Colors.BORDER};")
        layout.addWidget(line)

        summen_row("Gesamtbetrag (brutto):", "_lbl_brutto", bold=True, big=True)

        return frame

    def _build_footer(self) -> QFrame:
        footer = QFrame()
        footer.setFixedHeight(72)
        footer.setStyleSheet(f"""
            background-color: {Colors.BG_SURFACE};
            border-top: 1px solid {Colors.BORDER};
        """)
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(Spacing.XL, 0, Spacing.XL, 0)
        layout.setSpacing(Spacing.SM)

        cancel_btn = QPushButton("Schließen" if self._is_finalized else "Abbrechen")
        cancel_btn.setProperty("role", "secondary")
        cancel_btn.clicked.connect(self.reject)
        layout.addWidget(cancel_btn)

        layout.addStretch()

        if not self._is_finalized:
            if self._edit_mode:
                delete_btn = QPushButton("🗑  Entwurf löschen")
                delete_btn.setProperty("role", "danger")
                delete_btn.clicked.connect(self._delete_draft)
                layout.addWidget(delete_btn)

            save_btn = QPushButton("💾  Entwurf speichern")
            save_btn.setProperty("role", "secondary")
            save_btn.setMinimumWidth(180)
            save_btn.clicked.connect(self._save_draft)
            layout.addWidget(save_btn)

            finalize_btn = QPushButton("✅  Finalisieren & Buchen")
            finalize_btn.setMinimumWidth(200)
            finalize_btn.clicked.connect(self._do_finalize)
            layout.addWidget(finalize_btn)

        else:
            save_status_btn = QPushButton("💾  Status / Bemerkung speichern")
            save_status_btn.setMinimumWidth(240)
            save_status_btn.clicked.connect(self._save_status)
            layout.addWidget(save_status_btn)

            storno_btn = QPushButton("↩  Stornieren")
            storno_btn.setProperty("role", "danger")
            storno_btn.clicked.connect(self._do_storno)
            layout.addWidget(storno_btn)

        return footer

    # ------------------------------------------------------------------
    # Daten
    # ------------------------------------------------------------------

    def _populate(self, dto: RechnungDTO) -> None:
        self.f_nummer.set_value(dto.rechnungsnummer)
        self.f_datum.set_value(dto.rechnungsdatum)
        self.f_faellig.set_value(dto.faelligkeitsdatum)

        # MwSt
        mwst_text = f"{dto.mwst_prozent:,.2f} %".replace(".", ",")
        idx = self._mwst_combo.findText(mwst_text)
        if idx >= 0:
            self._mwst_combo.setCurrentIndex(idx)

        self._bemerkung_edit.setPlainText(dto.bemerkung)
        self._refresh_posten_table()
        self._update_summen()

    def _set_default_dates(self) -> None:
        """Setzt Standarddaten für neue Rechnungen."""
        heute = datetime.now()
        self.f_datum.set_value(heute.strftime("%d.%m.%Y"))

        with db.session() as session:
            try:
                from core.config import config
                tage = int(config.get("invoice", "payment_days", 14))
            except Exception:
                tage = 14
        faellig = heute + timedelta(days=tage)
        self.f_faellig.set_value(faellig.strftime("%d.%m.%Y"))

        # Nächste Rechnungsnummer vorschlagen
        with db.session() as session:
            nr = rechnungen_service.naechste_rechnungsnummer(session)
        self.f_nummer.set_value(nr)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._edit_mode:
            self._set_default_dates()

    # ------------------------------------------------------------------
    # Posten-Verwaltung
    # ------------------------------------------------------------------

    def _refresh_posten_table(self) -> None:
        table = self._posten_table
        readonly = self._is_finalized
        table.setRowCount(0)

        for p in self._posten:
            row = table.rowCount()
            table.insertRow(row)

            def make_item(text: str, align=Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft) -> QTableWidgetItem:
                item = QTableWidgetItem(str(text))
                item.setTextAlignment(align)
                return item

            right = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight

            table.setItem(row, 0, make_item(p.position))
            table.setItem(row, 1, make_item(p.artikelnummer))
            table.setItem(row, 2, make_item(p.beschreibung))
            table.setItem(row, 3, make_item(f"{float(p.menge):g}", right))
            table.setItem(row, 4, make_item(p.einheit))
            table.setItem(row, 5, make_item(f"{p.einzelpreis_netto:,.2f} €".replace(",", "X").replace(".", ",").replace("X", "."), right))
            table.setItem(row, 6, make_item(f"{p.gesamtpreis_netto:,.2f} €".replace(",", "X").replace(".", ",").replace("X", "."), right))

            if not readonly:
                btn_widget = QWidget()
                btn_layout = QHBoxLayout(btn_widget)
                btn_layout.setContentsMargins(4, 2, 4, 2)
                btn_layout.setSpacing(4)

                edit_btn = QPushButton("✏")
                edit_btn.setFixedSize(28, 28)
                edit_btn.setProperty("role", "ghost")
                edit_btn.setToolTip("Bearbeiten")
                edit_btn.clicked.connect(lambda _, pos=p.position: self._edit_posten(pos))

                del_btn = QPushButton("🗑")
                del_btn.setFixedSize(28, 28)
                del_btn.setProperty("role", "ghost")
                del_btn.setToolTip("Löschen")
                del_btn.clicked.connect(lambda _, pos=p.position: self._delete_posten(pos))

                up_btn = QPushButton("↑")
                up_btn.setFixedSize(24, 28)
                up_btn.setProperty("role", "ghost")
                up_btn.setToolTip("Nach oben")
                up_btn.clicked.connect(lambda _, pos=p.position: self._move_posten(pos, -1))

                down_btn = QPushButton("↓")
                down_btn.setFixedSize(24, 28)
                down_btn.setProperty("role", "ghost")
                down_btn.setToolTip("Nach unten")
                down_btn.clicked.connect(lambda _, pos=p.position: self._move_posten(pos, 1))

                btn_layout.addWidget(up_btn)
                btn_layout.addWidget(down_btn)
                btn_layout.addWidget(edit_btn)
                btn_layout.addWidget(del_btn)
                table.setCellWidget(row, 7, btn_widget)

        self._update_summen()

    def _add_posten(self) -> None:
        from ui.modules.rechnungen.posten_dialog import PostenDialog
        dlg = PostenDialog(
            parent=self,
            position=len(self._posten) + 1,
            artikel_liste=self._artikel_cache,
        )
        dlg.saved.connect(self._on_posten_saved)
        dlg.exec()

    def _edit_posten(self, position: int) -> None:
        posten = next((p for p in self._posten if p.position == position), None)
        if not posten:
            return
        from ui.modules.rechnungen.posten_dialog import PostenDialog
        dlg = PostenDialog(parent=self, dto=posten, artikel_liste=self._artikel_cache)
        dlg.saved.connect(lambda dto: self._on_posten_updated(dto))
        dlg.exec()

    def _edit_posten_by_click(self, index) -> None:
        row = index.row()
        if 0 <= row < len(self._posten):
            self._edit_posten(self._posten[row].position)

    def _on_posten_saved(self, dto: PostenDTO) -> None:
        self._posten.append(dto)
        self._renumber_posten()
        self._refresh_posten_table()

    def _on_posten_updated(self, dto: PostenDTO) -> None:
        for i, p in enumerate(self._posten):
            if p.position == dto.position:
                self._posten[i] = dto
                break
        self._refresh_posten_table()

    def _delete_posten(self, position: int) -> None:
        self._posten = [p for p in self._posten if p.position != position]
        self._renumber_posten()
        self._refresh_posten_table()

    def _move_posten(self, position: int, direction: int) -> None:
        idx = next((i for i, p in enumerate(self._posten) if p.position == position), -1)
        if idx < 0:
            return
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(self._posten):
            return
        self._posten[idx], self._posten[new_idx] = self._posten[new_idx], self._posten[idx]
        self._renumber_posten()
        self._refresh_posten_table()

    def _renumber_posten(self) -> None:
        for i, p in enumerate(self._posten, start=1):
            p.position = i

    # ------------------------------------------------------------------
    # Summen
    # ------------------------------------------------------------------

    def _get_mwst(self) -> Decimal:
        text = self._mwst_combo.currentText().replace(",", ".").replace(" %", "")
        try:
            return Decimal(text)
        except Exception:
            return Decimal("19.00")

    def _update_summen(self, *_) -> None:
        mwst = self._get_mwst()
        netto, mwst_betrag, brutto = berechne_summen(self._posten, mwst)

        def fmt(v: Decimal) -> str:
            return f"{v:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")

        self._lbl_netto.setText(fmt(netto))
        self._lbl_mwst.setText(fmt(mwst_betrag))
        self._lbl_brutto.setText(fmt(brutto))
        self._lbl_mwst_titel.setText(f"MwSt ({mwst:,.2f} %):".replace(".", ","))

    # ------------------------------------------------------------------
    # Formulardaten sammeln
    # ------------------------------------------------------------------

    def _collect(self) -> RechnungDTO:
        return RechnungDTO(
            id=self._dto.id if self._dto else None,
            kunde_id=self._kunde_id,
            rechnungsnummer=self.f_nummer.value(),
            rechnungsdatum=self.f_datum.value(),
            faelligkeitsdatum=self.f_faellig.value(),
            mwst_prozent=self._get_mwst(),
            summe_netto=Decimal("0"),
            summe_mwst=Decimal("0"),
            summe_brutto=Decimal("0"),
            mahngebuehren=Decimal("0"),
            offener_betrag=Decimal("0"),
            status=RechnungStatus.ENTWURF,
            bemerkung=self._bemerkung_edit.toPlainText(),
            is_finalized=False,
            posten=self._posten,
        )

    # ------------------------------------------------------------------
    # Aktionen
    # ------------------------------------------------------------------

    def _save_draft(self) -> None:
        dto = self._collect()
        self.saved.emit(dto)

    def _do_finalize(self) -> None:
        if not self._posten:
            self._banner.show_error("Bitte mindestens einen Posten hinzufügen.")
            return
        if not ConfirmDialog.ask(
            title="Rechnung finalisieren",
            message=f"Rechnung '{self.f_nummer.value()}' jetzt finalisieren?",
            detail=(
                "Nach dem Finalisieren kann die Rechnung nicht mehr bearbeitet werden. "
                "Lagerbestände werden abgebucht. "
                "Dieser Schritt kann nicht rückgängig gemacht werden."
            ),
            confirm_text="Finalisieren & Buchen",
            parent=self,
        ):
            return

        # Flag setzen damit das Panel weiß: nach dem Speichern finalisieren
        self._finalize_requested = True
        self._save_draft()

    def _delete_draft(self) -> None:
        if not self._dto or not self._dto.id:
            self.reject()
            return
        if not ConfirmDialog.ask(
            title="Entwurf löschen",
            message="Diesen Rechnungsentwurf wirklich löschen?",
            detail="Der Entwurf und alle zugehörigen Posten werden endgültig gelöscht.",
            confirm_text="Löschen",
            danger=True,
            parent=self,
        ):
            return
        with db.session() as session:
            result = rechnungen_service.entwurf_loeschen(session, self._dto.id)
        if result.success:
            self.done(2)  # Spezieller Exit-Code für "gelöscht"
        else:
            self._banner.show_error(result.message)

    def _save_status(self) -> None:
        """Speichert Status und Bemerkung an einer finalisierten Rechnung."""
        if not self._dto or not self._dto.id:
            return
        neuer_status = self._status_combo.currentText()
        neue_bemerkung = self._bemerkung_edit.toPlainText()

        with db.session() as session:
            if neuer_status != self._dto.status:
                result = rechnungen_service.status_aendern(
                    session, self._dto.id, neuer_status
                )
                if not result.success:
                    self._banner.show_error(result.message)
                    return
            result2 = rechnungen_service.bemerkung_aktualisieren(
                session, self._dto.id, neue_bemerkung
            )
        if result2.success:
            self._banner.show_success("Gespeichert.")
            self.status_changed.emit(self._dto.id, neuer_status)
        else:
            self._banner.show_error(result2.message)

    def _do_storno(self) -> None:
        if not self._dto or not self._dto.id:
            return
        if not ConfirmDialog.ask(
            title="Rechnung stornieren",
            message=f"Rechnung '{self._dto.rechnungsnummer}' stornieren?",
            detail=(
                "Es wird automatisch eine Gegenbuchungs-Gutschrift erstellt. "
                "Lagerbestände werden zurückgebucht. "
                "Dieser Schritt ist endgültig."
            ),
            confirm_text="Stornieren",
            danger=True,
            parent=self,
        ):
            return

        with db.session() as session:
            result = rechnungen_service.stornieren(session, self._dto.id)

        if result.success:
            self._banner.show_success(result.message)
            self.done(3)  # Exit-Code für "storniert"
        else:
            self._banner.show_error(result.message)

    def show_error(self, message: str) -> None:
        self._banner.show_error(message)
