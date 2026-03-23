"""
ui/modules/angebote/dialog.py – Angebot erstellen und bearbeiten
=================================================================
Vollständiger Angebotsdialog mit Postenverwaltung (Artikel + freie Positionen),
Summenberechnung und Statusverwaltung.
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
from core.services.angebote_service import (
    AngebotDTO, AngebotsPostenDTO, AngebotStatus,
    angebote_service, berechne_summen,
)
from core.models import Artikel
from ui.components.widgets import (
    FormField, SectionTitle, NotificationBanner, ConfirmDialog,
)
from ui.theme.theme import Colors, Fonts, Spacing, Radius


class AngebotDialog(QDialog):
    """
    Dialog zum Erstellen und Bearbeiten von Angeboten.

    Signals:
        saved(AngebotDTO):        Beim Speichern
        status_changed(int, str): Beim Statuswechsel (ID, neuer Status)
    """

    saved = Signal(object)       # AngebotDTO
    status_changed = Signal(int, str)

    def __init__(
        self,
        parent=None,
        dto: AngebotDTO = None,
        kunde_id: int = None,
        kunde_name: str = "",
        title: str = "Neues Angebot",
    ):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._dto = dto
        self._kunde_id = kunde_id or (dto.kunde_id if dto else None)
        self._kunde_name = kunde_name or (dto.kunde_display if dto else "")
        self._edit_mode = dto is not None
        self._posten: list[AngebotsPostenDTO] = list(dto.posten) if (dto and dto.posten) else []
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

        self._banner = NotificationBanner()
        banner_wrap = QWidget()
        bw_layout = QVBoxLayout(banner_wrap)
        bw_layout.setContentsMargins(Spacing.XL, Spacing.SM, Spacing.XL, 0)
        bw_layout.addWidget(self._banner)
        root.addWidget(banner_wrap)

        # Scrollbereich mit Hauptinhalt
        scroll = QScrollArea()
        scroll.setObjectName("angebotDialogScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("#angebotDialogScroll { background: transparent; }")
        scroll.setWidget(self._build_content())
        root.addWidget(scroll, 1)

        root.addWidget(self._build_footer())

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("angebotDialogHeader")
        header.setFixedHeight(64)
        header.setStyleSheet(f"""
            #angebotDialogHeader {{
                background-color: {Colors.BG_SURFACE};
                border-bottom: 1px solid {Colors.BORDER};
            }}
        """)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(Spacing.XL, 0, Spacing.XL, 0)

        icon = QLabel("📝")
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
        content.setObjectName("angebotDialogContent")
        content.setStyleSheet("#angebotDialogContent { background: transparent; }")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(Spacing.XL, Spacing.LG, Spacing.XL, Spacing.LG)
        layout.setSpacing(Spacing.SM)

        # ── Angebotskopf ─────────────────────────────────────────
        layout.addWidget(SectionTitle("Angebotsdaten"))
        row1 = QHBoxLayout()
        row1.setSpacing(Spacing.MD)

        self.f_nummer = FormField(
            "Angebotsnummer *", required=True, placeholder="z.B. AG-2026-0001"
        )

        self.f_datum = FormField("Angebotsdatum *", required=True, placeholder="TT.MM.JJJJ")
        self.f_datum.setFixedWidth(160)

        self.f_gueltig = FormField("Gültig bis", placeholder="TT.MM.JJJJ")
        self.f_gueltig.setFixedWidth(160)

        row1.addWidget(self.f_nummer, 2)
        row1.addWidget(self.f_datum)
        row1.addWidget(self.f_gueltig)
        layout.addLayout(row1)

        # MwSt + Status
        row2 = QHBoxLayout()
        mwst_widget = QWidget()
        mwst_layout = QVBoxLayout(mwst_widget)
        mwst_layout.setContentsMargins(0, 0, 0, 0)
        mwst_layout.setSpacing(4)
        mwst_lbl = QLabel("MwSt-Satz")
        mwst_lbl.setFont(Fonts.get(Fonts.SIZE_SM))
        mwst_lbl.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        self._mwst_combo = QComboBox()
        # MwSt-Sätze aus Einstellungen laden (Regel + Ermäßigt + Steuerfrei)
        from core.config import config
        regel_mwst = config.get("invoice", "default_vat", 19.0)
        ermaessigt_mwst = config.get("invoice", "reduced_vat", 7.0)
        self._mwst_combo.addItem(f"{regel_mwst:,.2f} %".replace(".", ","))
        self._mwst_combo.addItem(f"{ermaessigt_mwst:,.2f} %".replace(".", ","))
        self._mwst_combo.addItem("0,00 %")
        self._mwst_combo.setCurrentIndex(0)  # Regelsteuersatz als Vorauswahl
        self._mwst_combo.setFixedWidth(120)
        self._mwst_combo.currentTextChanged.connect(self._update_summen)
        mwst_layout.addWidget(mwst_lbl)
        mwst_layout.addWidget(self._mwst_combo)
        row2.addWidget(mwst_widget)

        # Status-Auswahl
        status_widget = QWidget()
        status_layout = QVBoxLayout(status_widget)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(4)
        status_lbl = QLabel("Status")
        status_lbl.setFont(Fonts.get(Fonts.SIZE_SM))
        status_lbl.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        self._status_combo = QComboBox()
        self._status_combo.addItems(AngebotStatus.ALLE)
        self._status_combo.setCurrentText(AngebotStatus.ENTWURF)
        self._status_combo.setFixedWidth(180)
        status_layout.addWidget(status_lbl)
        status_layout.addWidget(self._status_combo)
        row2.addWidget(status_widget)

        row2.addStretch()
        layout.addLayout(row2)

        # ── Posten ────────────────────────────────────────────────
        layout.addWidget(SectionTitle("Angebotspositionen"))

        posten_toolbar = QHBoxLayout()
        add_posten_btn = QPushButton("➕  Position hinzufügen")
        add_posten_btn.clicked.connect(self._add_posten)
        posten_toolbar.addWidget(add_posten_btn)

        add_free_btn = QPushButton("✍  Freie Position (Service/Stunden)")
        add_free_btn.setProperty("role", "secondary")
        add_free_btn.clicked.connect(self._add_free_posten)
        posten_toolbar.addWidget(add_free_btn)

        posten_toolbar.addStretch()
        layout.addLayout(posten_toolbar)

        self._posten_table = self._build_posten_table()
        layout.addWidget(self._posten_table)

        # ── Summen ────────────────────────────────────────────────
        layout.addWidget(self._build_summen_widget())

        # ── Bemerkung ─────────────────────────────────────────────
        layout.addWidget(SectionTitle("Bemerkung / Angebotsbedingungen"))
        bemerkung_lbl = QLabel("Optionale Hinweise, Zahlungsbedingungen, Lieferkonditionen:")
        bemerkung_lbl.setFont(Fonts.get(Fonts.SIZE_SM))
        bemerkung_lbl.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        layout.addWidget(bemerkung_lbl)

        self._bemerkung_edit = QTextEdit()
        self._bemerkung_edit.setFixedHeight(100)
        self._bemerkung_edit.setPlaceholderText(
            "z.B. Zahlungsziel 30 Tage, Lieferzeit 2 Wochen, Preise gültig bis..."
        )
        layout.addWidget(self._bemerkung_edit)

        return content

    def _build_posten_table(self) -> QTableWidget:
        columns = ["Pos.", "ArtNr.", "Beschreibung", "Menge", "Einheit", "Einzelpreis", "Gesamt", "Aktionen"]

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
        table.setColumnWidth(7, 120)  # Aktionen

        table.verticalHeader().setDefaultSectionSize(44)
        table.doubleClicked.connect(self._edit_posten_by_click)

        return table

    def _build_summen_widget(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("angebotSummen")
        frame.setStyleSheet(f"""
            #angebotSummen {{
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
        footer.setObjectName("angebotDialogFooter")
        footer.setFixedHeight(72)
        footer.setStyleSheet(f"""
            #angebotDialogFooter {{
                background-color: {Colors.BG_SURFACE};
                border-top: 1px solid {Colors.BORDER};
            }}
        """)
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(Spacing.XL, 0, Spacing.XL, 0)
        layout.setSpacing(Spacing.SM)

        cancel_btn = QPushButton("Abbrechen")
        cancel_btn.setProperty("role", "secondary")
        cancel_btn.clicked.connect(self.reject)
        layout.addWidget(cancel_btn)

        layout.addStretch()

        if self._edit_mode:
            delete_btn = QPushButton("🗑  Angebot löschen")
            delete_btn.setProperty("role", "danger")
            delete_btn.clicked.connect(self._delete_angebot)
            layout.addWidget(delete_btn)

        save_btn = QPushButton("💾  Angebot speichern")
        save_btn.setMinimumWidth(200)
        save_btn.clicked.connect(self._save)
        layout.addWidget(save_btn)

        return footer

    # ------------------------------------------------------------------
    # Daten
    # ------------------------------------------------------------------

    def _populate(self, dto: AngebotDTO) -> None:
        self.f_nummer.set_value(dto.angebotsnummer)
        self.f_datum.set_value(dto.angebotsdatum)
        self.f_gueltig.set_value(dto.gueltig_bis)

        # MwSt – historische Sätze ggf. dynamisch ergänzen
        mwst_text = f"{dto.mwst_prozent:,.2f} %".replace(".", ",")
        idx = self._mwst_combo.findText(mwst_text)
        if idx >= 0:
            self._mwst_combo.setCurrentIndex(idx)
        else:
            self._mwst_combo.addItem(mwst_text)
            self._mwst_combo.setCurrentText(mwst_text)

        # Status
        idx = self._status_combo.findText(dto.status)
        if idx >= 0:
            self._status_combo.setCurrentIndex(idx)

        self._bemerkung_edit.setPlainText(dto.bemerkung)
        self._refresh_posten_table()
        self._update_summen()

    def _set_default_dates(self) -> None:
        """Setzt Standarddaten für neue Angebote."""
        heute = datetime.now()
        self.f_datum.set_value(heute.strftime("%d.%m.%Y"))

        # Standardmäßig 30 Tage gültig
        gueltig = heute + timedelta(days=30)
        self.f_gueltig.set_value(gueltig.strftime("%d.%m.%Y"))

        # Nächste Angebotsnummer vorschlagen
        with db.session() as session:
            nr = angebote_service.naechste_angebotsnummer(session)
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
        table.setRowCount(0)

        for p in self._posten:
            row = table.rowCount()
            table.insertRow(row)

            def make_item(text: str, align=Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft) -> QTableWidgetItem:
                item = QTableWidgetItem(str(text))
                item.setTextAlignment(align)
                return item

            right = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight

            # Freie Positionen (ohne ArtNr) farblich hervorheben
            art_nr_text = p.artikelnummer if p.artikelnummer else "– frei –"

            table.setItem(row, 0, make_item(p.position))
            table.setItem(row, 1, make_item(art_nr_text))
            table.setItem(row, 2, make_item(p.beschreibung))
            table.setItem(row, 3, make_item(f"{float(p.menge):g}", right))
            table.setItem(row, 4, make_item(p.einheit))
            table.setItem(row, 5, make_item(f"{p.einzelpreis_netto:,.2f} €".replace(",", "X").replace(".", ",").replace("X", "."), right))
            table.setItem(row, 6, make_item(f"{p.gesamtpreis_netto:,.2f} €".replace(",", "X").replace(".", ",").replace("X", "."), right))

            # Freie Position farblich kennzeichnen
            if not p.artikelnummer:
                for col in range(7):
                    item = table.item(row, col)
                    if item:
                        item.setForeground(QColor(Colors.INFO))

            btn_widget = QWidget()
            btn_widget.setObjectName("postenActions")
            btn_widget.setStyleSheet("#postenActions { background: transparent; }")
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
        from ui.modules.angebote.posten_dialog import AngebotsPostenDialog
        dlg = AngebotsPostenDialog(
            parent=self,
            position=len(self._posten) + 1,
            artikel_liste=self._artikel_cache,
        )
        dlg.saved.connect(self._on_posten_saved)
        dlg.exec()

    def _add_free_posten(self) -> None:
        """Öffnet den Postendialog ohne Artikelvorauswahl für freie Positionen."""
        from ui.modules.angebote.posten_dialog import AngebotsPostenDialog
        dlg = AngebotsPostenDialog(
            parent=self,
            position=len(self._posten) + 1,
            artikel_liste=[],  # Keine Artikelliste → reiner Freitextmodus
        )
        dlg.saved.connect(self._on_posten_saved)
        dlg.exec()

    def _edit_posten(self, position: int) -> None:
        posten = next((p for p in self._posten if p.position == position), None)
        if not posten:
            return
        from ui.modules.angebote.posten_dialog import AngebotsPostenDialog
        dlg = AngebotsPostenDialog(parent=self, dto=posten, artikel_liste=self._artikel_cache)
        dlg.saved.connect(lambda dto: self._on_posten_updated(dto))
        dlg.exec()

    def _edit_posten_by_click(self, index) -> None:
        row = index.row()
        if 0 <= row < len(self._posten):
            self._edit_posten(self._posten[row].position)

    def _on_posten_saved(self, dto: AngebotsPostenDTO) -> None:
        self._posten.append(dto)
        self._renumber_posten()
        self._refresh_posten_table()

    def _on_posten_updated(self, dto: AngebotsPostenDTO) -> None:
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

    def _collect(self) -> AngebotDTO:
        return AngebotDTO(
            id=self._dto.id if self._dto else None,
            kunde_id=self._kunde_id,
            angebotsnummer=self.f_nummer.value(),
            angebotsdatum=self.f_datum.value(),
            gueltig_bis=self.f_gueltig.value(),
            mwst_prozent=self._get_mwst(),
            summe_netto=Decimal("0"),
            summe_mwst=Decimal("0"),
            summe_brutto=Decimal("0"),
            status=self._status_combo.currentText(),
            bemerkung=self._bemerkung_edit.toPlainText(),
            posten=self._posten,
        )

    # ------------------------------------------------------------------
    # Aktionen
    # ------------------------------------------------------------------

    def _save(self) -> None:
        dto = self._collect()
        self.saved.emit(dto)

    def _delete_angebot(self) -> None:
        if not self._dto or not self._dto.id:
            self.reject()
            return
        if not ConfirmDialog.ask(
            title="Angebot löschen",
            message="Dieses Angebot wirklich löschen?",
            detail="Das Angebot und alle zugehörigen Positionen werden endgültig gelöscht.",
            confirm_text="Löschen",
            danger=True,
            parent=self,
        ):
            return
        with db.session() as session:
            result = angebote_service.loeschen(session, self._dto.id)
        if result.success:
            self.done(2)  # Spezieller Exit-Code für "gelöscht"
        else:
            self._banner.show_error(result.message)

    def show_error(self, message: str) -> None:
        self._banner.show_error(message)
