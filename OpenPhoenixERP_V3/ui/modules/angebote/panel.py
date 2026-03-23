"""
ui/modules/angebote/panel.py – Hauptpanel Angebotsverwaltung
=============================================================
Übersicht aller Angebote mit Filter, Sortierung,
Statusanzeige und Direktaktionen.
"""

import logging
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QAction
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QComboBox, QMenu, QSplitter,
)

from core.db.engine import db
from core.services.angebote_service import (
    angebote_service, AngebotDTO, AngebotStatus,
)
from ui.components.widgets import (
    SearchBar, DataTable, NotificationBanner,
    EmptyState, StatusBadge, ConfirmDialog, SectionTitle,
)
from ui.theme.theme import Colors, Fonts, Spacing, Radius, on_theme_changed

logger = logging.getLogger(__name__)

# Farbzuordnung für Angebotsstatus
STATUS_COLORS = {
    AngebotStatus.ENTWURF:    QColor(Colors.TEXT_DISABLED),
    AngebotStatus.OFFEN:      QColor(Colors.INFO),
    AngebotStatus.ANGENOMMEN: QColor(Colors.SUCCESS),
    AngebotStatus.ABGELEHNT:  QColor(Colors.ERROR),
    AngebotStatus.ABGELAUFEN: QColor(Colors.WARNING),
}


class AngebotDetailPanel(QFrame):
    """Zeigt Details des ausgewählten Angebots (rechte Seite)."""

    edit_requested = Signal(object)      # AngebotDTO

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(300)
        self._dto: Optional[AngebotDTO] = None
        self._styled_widgets: list = []
        self._build_ui()
        on_theme_changed(self._on_theme_changed)

    def _on_theme_changed(self, _mode: str) -> None:
        for widget, style_fn in self._styled_widgets:
            widget.setStyleSheet(style_fn())

    def _build_ui(self) -> None:
        from PySide6.QtWidgets import QScrollArea
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        container.setObjectName("angebotDetailContainer")
        _container_style = lambda: f"#angebotDetailContainer {{ background-color: {Colors.BG_APP}; }}"
        container.setStyleSheet(_container_style())
        self._styled_widgets.append((container, _container_style))
        scroll.setWidget(container)

        self._main = QVBoxLayout(container)
        self._main.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        self._main.setSpacing(Spacing.MD)

        self._empty = EmptyState("📝", "Kein Angebot ausgewählt", "Wählen Sie ein Angebot aus der Liste.")
        self._main.addWidget(self._empty)

        self._detail = QWidget()
        self._detail.setVisible(False)
        detail_layout = QVBoxLayout(self._detail)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(Spacing.MD)

        # Kopfzeile
        header_row = QHBoxLayout()
        self._nr_label = QLabel()
        self._nr_label.setFont(Fonts.heading3())
        self._status_badge = StatusBadge()
        header_row.addWidget(self._nr_label, 1)
        header_row.addWidget(self._status_badge)
        detail_layout.addLayout(header_row)

        self._kunde_label = QLabel()
        self._kunde_label.setFont(Fonts.get(Fonts.SIZE_SM))
        _kunde_style = lambda: f"color: {Colors.TEXT_SECONDARY};"
        self._kunde_label.setStyleSheet(_kunde_style())
        self._styled_widgets.append((self._kunde_label, _kunde_style))
        detail_layout.addWidget(self._kunde_label)

        # Trennlinie
        line = QFrame()
        line.setFixedHeight(1)
        _line_style = lambda: f"background-color: {Colors.BORDER};"
        line.setStyleSheet(_line_style())
        self._styled_widgets.append((line, _line_style))
        detail_layout.addWidget(line)

        # Aktionsbuttons
        self._btn_open = QPushButton("✏️  Öffnen / Bearbeiten")
        self._btn_open.clicked.connect(lambda: self.edit_requested.emit(self._dto))
        detail_layout.addWidget(self._btn_open)

        # Infofelder
        info = QFrame()
        _info_style = lambda: f"""
            QFrame {{
                background-color: {Colors.BG_SURFACE};
                border-radius: {Radius.LG}px;
                border: 1px solid {Colors.BORDER};
            }}
        """
        info.setStyleSheet(_info_style())
        self._styled_widgets.append((info, _info_style))
        info_layout = QVBoxLayout(info)
        info_layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        info_layout.setSpacing(Spacing.SM)

        self._fields: dict[str, QLabel] = {}
        for lbl, key in [
            ("Datum", "datum"),
            ("Gültig bis", "gueltig"),
            ("Netto", "netto"),
            ("MwSt", "mwst"),
            ("Brutto", "brutto"),
        ]:
            row = QHBoxLayout()
            l = QLabel(lbl)
            l.setFont(Fonts.get(Fonts.SIZE_SM))
            _l_style = lambda: f"color: {Colors.TEXT_SECONDARY};"
            l.setStyleSheet(_l_style())
            self._styled_widgets.append((l, _l_style))
            l.setFixedWidth(80)
            v = QLabel("–")
            v.setFont(Fonts.get(Fonts.SIZE_SM))
            v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            if key == "brutto":
                v.setFont(Fonts.get(Fonts.SIZE_BASE, bold=True))
                _v_style = lambda: f"color: {Colors.PRIMARY};"
                v.setStyleSheet(_v_style())
                self._styled_widgets.append((v, _v_style))
            self._fields[key] = v
            row.addWidget(l)
            row.addWidget(v, 1)
            info_layout.addLayout(row)

        detail_layout.addWidget(info)
        detail_layout.addStretch()

        self._main.addWidget(self._detail)
        layout.addWidget(scroll)

    def show_angebot(self, dto: AngebotDTO) -> None:
        self._dto = dto
        self._empty.setVisible(False)
        self._detail.setVisible(True)

        self._nr_label.setText(dto.angebotsnummer)
        self._status_badge.set_status(dto.status)
        self._kunde_label.setText(f"👤 {dto.kunde_display}")

        def fmt(v) -> str:
            return f"{v:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")

        self._fields["datum"].setText(dto.angebotsdatum)
        self._fields["gueltig"].setText(dto.gueltig_bis or "–")
        self._fields["netto"].setText(fmt(dto.summe_netto))
        self._fields["mwst"].setText(fmt(dto.summe_mwst))
        self._fields["brutto"].setText(fmt(dto.summe_brutto))

    def clear(self) -> None:
        self._dto = None
        self._empty.setVisible(True)
        self._detail.setVisible(False)


class AngebotePanel(QWidget):
    """Vollständiges Angebotsmodul."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_dtos: list[AngebotDTO] = []
        self._styled_widgets: list = []
        self._build_ui()
        self._connect_signals()
        self._load()
        on_theme_changed(self._on_theme_changed)

    def _on_theme_changed(self, _mode: str) -> None:
        for widget, style_fn in self._styled_widgets:
            widget.setStyleSheet(style_fn())

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def showEvent(self, event) -> None:
        """Daten bei jedem Modul-Wechsel neu laden."""
        super().showEvent(event)
        self._load()

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

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)
        _split_style = lambda: f"QSplitter::handle {{ background-color: {Colors.BORDER}; }}"
        splitter.setStyleSheet(_split_style())
        self._styled_widgets.append((splitter, _split_style))

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(Spacing.XL, Spacing.MD, Spacing.MD, Spacing.MD)
        ll.setSpacing(Spacing.SM)
        ll.addWidget(self._build_toolbar())
        ll.addWidget(self._build_table())

        self._detail_panel = AngebotDetailPanel()

        splitter.addWidget(left)
        splitter.addWidget(self._detail_panel)
        splitter.setSizes([780, 300])
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)

        root.addWidget(splitter, 1)

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("angebotePanelHeader")
        header.setFixedHeight(64)
        _hdr_style = lambda: f"""
            #angebotePanelHeader {{
                background-color: {Colors.BG_SURFACE};
                border-bottom: 1px solid {Colors.BORDER};
            }}
        """
        header.setStyleSheet(_hdr_style())
        self._styled_widgets.append((header, _hdr_style))
        layout = QHBoxLayout(header)
        layout.setContentsMargins(Spacing.XL, 0, Spacing.XL, 0)

        icon = QLabel("📝")
        icon.setStyleSheet("font-size: 22px; background: transparent;")
        title = QLabel("Angebote")
        title.setFont(Fonts.heading2())
        _title_style = lambda: f"color: {Colors.TEXT_PRIMARY}; background: transparent;"
        title.setStyleSheet(_title_style())
        self._styled_widgets.append((title, _title_style))

        self._count_badge = QLabel("0 Angebote")
        self._count_badge.setFont(Fonts.get(Fonts.SIZE_SM))
        _badge_style = lambda: f"""
            background-color: {Colors.BG_ELEVATED};
            color: {Colors.TEXT_SECONDARY};
            border-radius: {Radius.SM}px;
            padding: 4px 10px;
        """
        self._count_badge.setStyleSheet(_badge_style())
        self._styled_widgets.append((self._count_badge, _badge_style))

        layout.addWidget(icon)
        layout.addSpacing(Spacing.SM)
        layout.addWidget(title)
        layout.addSpacing(Spacing.SM)
        layout.addWidget(self._count_badge)
        layout.addStretch()

        new_btn = QPushButton("➕  Neues Angebot")
        new_btn.clicked.connect(self._new_angebot)
        layout.addWidget(new_btn)

        return header

    def _build_toolbar(self) -> QWidget:
        toolbar = QWidget()
        toolbar.setObjectName("angeboteToolbar")
        toolbar.setStyleSheet("#angeboteToolbar { background: transparent; }")
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Spacing.SM)

        self._search = SearchBar("Suchen nach Nr., Kunde, Status…")
        layout.addWidget(self._search, 1)

        status_lbl = QLabel("Status:")
        _status_lbl_style = lambda: f"color: {Colors.TEXT_SECONDARY};"
        status_lbl.setStyleSheet(_status_lbl_style())
        self._styled_widgets.append((status_lbl, _status_lbl_style))
        self._status_filter = QComboBox()
        self._status_filter.addItem("Alle", None)
        self._status_filter.addItem("Nur Entwürfe", [AngebotStatus.ENTWURF])
        self._status_filter.addItem("Offene", [AngebotStatus.OFFEN])
        self._status_filter.addItem("Angenommen", [AngebotStatus.ANGENOMMEN])
        self._status_filter.addItem("Abgelehnt", [AngebotStatus.ABGELEHNT])
        self._status_filter.addItem("Abgelaufen", [AngebotStatus.ABGELAUFEN])
        self._status_filter.setFixedWidth(180)
        self._status_filter.currentIndexChanged.connect(self._load)
        layout.addWidget(status_lbl)
        layout.addWidget(self._status_filter)

        return toolbar

    def _build_table(self) -> DataTable:
        self._table = DataTable(
            columns=[
                "ID", "Angebotsnr.", "Datum", "Gültig bis",
                "Kunde", "Netto", "MwSt", "Brutto", "Status"
            ],
            column_widths=[0, 130, 100, 100, 180, 100, 90, 110, 140],
            stretch_column=4,
            table_id="angebote_liste",
        )
        self._table.setColumnHidden(0, True)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._context_menu)
        return self._table

    # ------------------------------------------------------------------
    # Signale
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        self._search.search_changed.connect(self._load)
        self._search.cleared.connect(self._load)
        self._table.row_selected.connect(self._on_row_selected)
        self._table.row_double_clicked.connect(self._on_row_double_clicked)
        self._detail_panel.edit_requested.connect(self._open_angebot)

    # ------------------------------------------------------------------
    # Daten laden
    # ------------------------------------------------------------------

    def _load(self, *_) -> None:
        suchtext = self._search.text()
        status_data = self._status_filter.currentData()

        try:
            with db.session() as session:
                self._current_dtos = angebote_service.alle(
                    session,
                    suchtext=suchtext,
                    status_filter=status_data,
                )
        except Exception as e:
            self._banner.show_error(f"Fehler beim Laden: {e}")
            return

        def fmt(v) -> str:
            return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

        rows = []
        colors = {}
        for i, dto in enumerate(self._current_dtos):
            rows.append([
                dto.id,
                dto.angebotsnummer,
                dto.angebotsdatum,
                dto.gueltig_bis or "–",
                dto.kunde_display,
                fmt(dto.summe_netto),
                fmt(dto.summe_mwst),
                fmt(dto.summe_brutto),
                dto.status,
            ])
            color = STATUS_COLORS.get(dto.status)
            if color:
                colors[i] = color

        self._table.set_data(rows)
        for row, color in colors.items():
            self._table.set_row_color(row, color)

        n = len(self._current_dtos)
        self._count_badge.setText(f"{n} Angebot{'e' if n != 1 else ''}")

        if n == 0:
            self._detail_panel.clear()

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def _on_row_selected(self, source_row: int) -> None:
        try:
            dto = self._current_dtos[source_row]
            self._detail_panel.show_angebot(dto)
        except IndexError:
            self._detail_panel.clear()

    def _on_row_double_clicked(self, source_row: int) -> None:
        try:
            self._open_angebot(self._current_dtos[source_row])
        except IndexError:
            pass

    def _context_menu(self, pos) -> None:
        row = self._table.current_source_row()
        if row < 0 or row >= len(self._current_dtos):
            return
        dto = self._current_dtos[row]

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

        menu.addAction("✏️  Bearbeiten").triggered.connect(lambda: self._open_angebot(dto))

        menu.addSeparator()

        if dto.status != AngebotStatus.ANGENOMMEN:
            menu.addAction("✅  Als angenommen markieren").triggered.connect(
                lambda: self._quick_status(dto, AngebotStatus.ANGENOMMEN)
            )
        if dto.status != AngebotStatus.ABGELEHNT:
            menu.addAction("❌  Als abgelehnt markieren").triggered.connect(
                lambda: self._quick_status(dto, AngebotStatus.ABGELEHNT)
            )
        if dto.status == AngebotStatus.ENTWURF:
            menu.addAction("📤  Als offen markieren").triggered.connect(
                lambda: self._quick_status(dto, AngebotStatus.OFFEN)
            )

        menu.addSeparator()
        menu.addAction("🗑  Löschen").triggered.connect(lambda: self._delete_angebot(dto))

        menu.exec(self._table.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------------
    # Aktionen
    # ------------------------------------------------------------------

    def _new_angebot(self) -> None:
        """Neues Angebot – erst Kunden auswählen."""
        from ui.modules.angebote.kunden_auswahl import KundenAuswahlDialog
        dlg = KundenAuswahlDialog(parent=self)
        dlg.selected.connect(self._open_new_for_kunde)
        dlg.exec()

    def _open_new_for_kunde(self, kunde_id: int, kunde_name: str) -> None:
        from ui.modules.angebote.dialog import AngebotDialog
        dlg = AngebotDialog(
            parent=self,
            kunde_id=kunde_id,
            kunde_name=kunde_name,
            title=f"Neues Angebot – {kunde_name}",
        )
        dlg.saved.connect(lambda dto: self._on_saved_new(dto, dlg))
        dlg.exec()

    def _open_angebot(self, dto: AngebotDTO) -> None:
        # Vollständiges Angebot mit Posten laden
        with db.session() as session:
            full_dto = angebote_service.nach_id(session, dto.id)
        if not full_dto:
            self._banner.show_error("Angebot nicht gefunden.")
            return

        from ui.modules.angebote.dialog import AngebotDialog
        title = (
            f"Angebot {full_dto.angebotsnummer} – {full_dto.kunde_display}"
        )
        dlg = AngebotDialog(
            parent=self, dto=full_dto,
            kunde_name=full_dto.kunde_display,
            title=title,
        )
        dlg.saved.connect(lambda d: self._on_saved_edit(d, dlg, full_dto.id))
        dlg.status_changed.connect(lambda rid, s: self._load())
        result = dlg.exec()

        if result == 2:  # Angebot gelöscht
            self._banner.show_success("Angebot gelöscht.")
            self._load()
            self._detail_panel.clear()

    def _on_saved_new(self, dto: AngebotDTO, dlg) -> None:
        with db.session() as session:
            result = angebote_service.erstellen(session, dto.kunde_id, dto)

        if result.success:
            self._banner.show_success(result.message)
            dlg.accept()
            self._load()
        else:
            dlg.show_error(result.message)

    def _on_saved_edit(self, dto: AngebotDTO, dlg, angebot_id: int) -> None:
        with db.session() as session:
            result = angebote_service.aktualisieren(session, angebot_id, dto)

        if result.success:
            self._banner.show_success(result.message)
            dlg.accept()
            self._load()
        else:
            dlg.show_error(result.message)

    def _delete_angebot(self, dto: AngebotDTO) -> None:
        if not ConfirmDialog.ask(
            title="Angebot löschen",
            message=f"Angebot '{dto.angebotsnummer}' löschen?",
            detail="Alle Positionen werden ebenfalls gelöscht.",
            confirm_text="Löschen",
            danger=True,
            parent=self,
        ):
            return
        with db.session() as session:
            result = angebote_service.loeschen(session, dto.id)
        if result.success:
            self._banner.show_success(result.message)
            self._detail_panel.clear()
            self._load()
        else:
            self._banner.show_error(result.message)

    def _quick_status(self, dto: AngebotDTO, status: str) -> None:
        with db.session() as session:
            result = angebote_service.status_aendern(session, dto.id, status)
        if result.success:
            self._banner.show_success(result.message)
            self._load()
        else:
            self._banner.show_error(result.message)
