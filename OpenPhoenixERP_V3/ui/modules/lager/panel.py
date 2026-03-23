"""
ui/modules/lager/panel.py – Hauptpanel der Lagerverwaltung
===========================================================
Artikelstamm mit Bestandsübersicht und Buchungshistorie.
Zwei Tabs: Artikel | Bewegungshistorie.
"""

import logging
from decimal import Decimal
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QTabWidget, QCheckBox, QMenu,
)

from core.db.engine import db
from core.services.lager_service import (
    lager_service, ArtikelDTO, BewegungDTO, Buchungsart,
)
from ui.components.widgets import (
    SearchBar, DataTable, NotificationBanner,
    EmptyState, ConfirmDialog, SectionTitle,
)
from ui.theme.theme import Colors, Fonts, Spacing, Radius, on_theme_changed

logger = logging.getLogger(__name__)


# Farbcodierung je Buchungsart
BUCHUNGSART_FARBEN = {
    Buchungsart.EINGANG:         QColor(Colors.SUCCESS),
    Buchungsart.STORNOEINGANG:   QColor(Colors.SUCCESS),
    Buchungsart.AUSGANG:         QColor(Colors.ERROR),
    Buchungsart.RECHNUNGSABGANG: QColor(Colors.ERROR),
    Buchungsart.KORREKTUR:       QColor(Colors.WARNING),
}


class LagerPanel(QWidget):
    """
    Vollständiges Lagerverwaltungs-Modul.
    Tab 1: Artikelstamm  |  Tab 2: Bewegungshistorie
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._show_inactive = False
        self._artikel_dtos: list[ArtikelDTO] = []
        self._bewegung_dtos: list[BewegungDTO] = []
        self._styled_widgets: list = []
        self._build_ui()
        self._connect_signals()
        self._load_artikel()
        self._update_stats()
        on_theme_changed(self._on_theme_changed)

    def _on_theme_changed(self, _mode: str) -> None:
        for widget, style_fn in self._styled_widgets:
            widget.setStyleSheet(style_fn())

    # ------------------------------------------------------------------
    # UI aufbauen
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())

        # Banner
        banner_wrapper = QWidget()
        bw_layout = QVBoxLayout(banner_wrapper)
        bw_layout.setContentsMargins(Spacing.XL, Spacing.SM, Spacing.XL, 0)
        self._banner = NotificationBanner()
        bw_layout.addWidget(self._banner)
        root.addWidget(banner_wrapper)

        # Statistik-Karten
        root.addWidget(self._build_stats_row())

        # Tabs
        self._tabs = QTabWidget()
        _tabs_style = lambda: f"""
            QTabWidget::pane {{
                background-color: {Colors.BG_APP};
                border: none;
            }}
            QTabBar::tab {{
                background: transparent;
                color: {Colors.TEXT_SECONDARY};
                padding: 10px 20px;
                border-bottom: 2px solid transparent;
                font-size: {Fonts.SIZE_BASE}pt;
            }}
            QTabBar::tab:selected {{
                color: {Colors.PRIMARY};
                border-bottom: 2px solid {Colors.PRIMARY};
            }}
            QTabBar::tab:hover {{
                color: {Colors.TEXT_PRIMARY};
            }}
        """
        self._tabs.setStyleSheet(_tabs_style())
        self._styled_widgets.append((self._tabs, _tabs_style))

        # Tab 1: Artikelstamm
        artikel_tab = QWidget()
        at_layout = QVBoxLayout(artikel_tab)
        at_layout.setContentsMargins(Spacing.XL, Spacing.MD, Spacing.XL, Spacing.MD)
        at_layout.setSpacing(Spacing.SM)
        at_layout.addWidget(self._build_artikel_toolbar())
        at_layout.addWidget(self._build_artikel_table())
        self._tabs.addTab(artikel_tab, "📦  Artikelstamm")

        # Tab 2: Bewegungshistorie
        bewegung_tab = QWidget()
        bv_layout = QVBoxLayout(bewegung_tab)
        bv_layout.setContentsMargins(Spacing.XL, Spacing.MD, Spacing.XL, Spacing.MD)
        bv_layout.setSpacing(Spacing.SM)
        bv_layout.addWidget(self._build_bewegung_toolbar())
        bv_layout.addWidget(self._build_bewegung_table())
        self._tabs.addTab(bewegung_tab, "📋  Bewegungshistorie")

        root.addWidget(self._tabs, 1)

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("lagerPanelHeader")
        header.setFixedHeight(64)
        _hdr_style = lambda: f"""
            #lagerPanelHeader {{
                background-color: {Colors.BG_SURFACE};
                border-bottom: 1px solid {Colors.BORDER};
            }}
        """
        header.setStyleSheet(_hdr_style())
        self._styled_widgets.append((header, _hdr_style))
        layout = QHBoxLayout(header)
        layout.setContentsMargins(Spacing.XL, 0, Spacing.XL, 0)

        icon = QLabel("📦")
        icon.setStyleSheet("font-size: 22px; background: transparent;")
        title = QLabel("Lagerverwaltung")
        title.setFont(Fonts.heading2())
        _title_style = lambda: f"color: {Colors.TEXT_PRIMARY}; background: transparent;"
        title.setStyleSheet(_title_style())
        self._styled_widgets.append((title, _title_style))

        layout.addWidget(icon)
        layout.addSpacing(Spacing.SM)
        layout.addWidget(title)
        layout.addStretch()

        self._btn_einbuchen = QPushButton("⬆  Einbuchen")
        self._btn_einbuchen.setProperty("role", "success")
        self._btn_einbuchen.clicked.connect(self._schnell_einbuchen)
        layout.addWidget(self._btn_einbuchen)

        self._btn_ausbuchen = QPushButton("⬇  Ausbuchen")
        self._btn_ausbuchen.setProperty("role", "danger")
        self._btn_ausbuchen.clicked.connect(self._schnell_ausbuchen)
        layout.addWidget(self._btn_ausbuchen)

        btn_new = QPushButton("➕  Neuer Artikel")
        btn_new.clicked.connect(self._neuer_artikel)
        layout.addWidget(btn_new)

        return header

    def _build_stats_row(self) -> QWidget:
        """Statistik-Leiste mit 4 Kennzahlen."""
        row = QWidget()
        row.setObjectName("lagerStatsRow")
        _stats_row_style = lambda: f"#lagerStatsRow {{ background-color: {Colors.BG_SURFACE}; border-bottom: 1px solid {Colors.BORDER}; }}"
        row.setStyleSheet(_stats_row_style())
        self._styled_widgets.append((row, _stats_row_style))
        layout = QHBoxLayout(row)
        layout.setContentsMargins(Spacing.XL, Spacing.MD, Spacing.XL, Spacing.MD)
        layout.setSpacing(Spacing.LG)

        self._stat_labels = {}
        stats = [
            ("aktiv",    "Aktive Artikel",  "TEXT_PRIMARY"),
            ("kritisch", "Kritischer Bestand", "WARNING"),
            ("negativ",  "Negativbestand",  "ERROR"),
            ("lagerwert","Lagerwert (Netto)", "INFO"),
        ]
        for key, label, color_attr in stats:
            card = QWidget()
            card_name = f"lagerStatCard_{key}"
            card.setObjectName(card_name)
            card.setStyleSheet(f"#{card_name} {{ background: transparent; }}")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(0, 0, 0, 0)
            cl.setSpacing(2)

            val_label = QLabel("–")
            val_label.setFont(Fonts.get(Fonts.SIZE_XL, bold=True))
            _val_style = lambda a=color_attr: f"color: {getattr(Colors, a)};"
            val_label.setStyleSheet(_val_style())
            self._styled_widgets.append((val_label, _val_style))
            self._stat_labels[key] = val_label

            desc_label = QLabel(label)
            desc_label.setFont(Fonts.caption())
            _desc_style = lambda: f"color: {Colors.TEXT_SECONDARY};"
            desc_label.setStyleSheet(_desc_style())
            self._styled_widgets.append((desc_label, _desc_style))

            cl.addWidget(val_label)
            cl.addWidget(desc_label)
            layout.addWidget(card)

        layout.addStretch()
        return row

    def _build_artikel_toolbar(self) -> QWidget:
        toolbar = QWidget()
        toolbar.setObjectName("lagerArtikelToolbar")
        toolbar.setStyleSheet("#lagerArtikelToolbar { background: transparent; }")
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Spacing.SM)

        self._search_artikel = SearchBar("Artikel suchen…")
        layout.addWidget(self._search_artikel, 1)

        self._inactive_check = QCheckBox("Inaktive anzeigen")
        _chk_style = lambda: f"color: {Colors.TEXT_SECONDARY};"
        self._inactive_check.setStyleSheet(_chk_style())
        self._styled_widgets.append((self._inactive_check, _chk_style))
        self._inactive_check.toggled.connect(self._on_inactive_toggled)
        layout.addWidget(self._inactive_check)

        return toolbar

    def _build_artikel_table(self) -> DataTable:
        self._artikel_table = DataTable(
            columns=[
                "ID", "Artikelnummer", "Beschreibung", "Einheit",
                "Preis (Netto)", "Bestand", "Status"
            ],
            column_widths=[0, 120, 300, 80, 110, 100, 80],
            stretch_column=2,
                    table_id="lager_artikel",
        )
        self._artikel_table.setColumnHidden(0, True)
        self._artikel_table.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._artikel_table.customContextMenuRequested.connect(
            self._context_menu_artikel
        )
        return self._artikel_table

    def _build_bewegung_toolbar(self) -> QWidget:
        toolbar = QWidget()
        toolbar.setObjectName("lagerBewegungToolbar")
        toolbar.setStyleSheet("#lagerBewegungToolbar { background: transparent; }")
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Spacing.SM)

        layout.addWidget(QLabel("Artikel-Nr.:"))
        self._search_bewegung = SearchBar("Filter nach Artikelnummer…")
        layout.addWidget(self._search_bewegung, 1)

        btn_refresh = QPushButton("↻  Aktualisieren")
        btn_refresh.setProperty("role", "secondary")
        btn_refresh.clicked.connect(lambda _=None: self._load_bewegungen())
        layout.addWidget(btn_refresh)

        return toolbar

    def _build_bewegung_table(self) -> DataTable:
        self._bewegung_table = DataTable(
            columns=[
                "ID", "Datum", "Artikelnummer", "Buchungsart",
                "Menge", "Bestand vorher", "Bestand nachher", "Referenz", "Benutzer"
            ],
            column_widths=[0, 130, 120, 140, 80, 120, 120, 160, 100],
            stretch_column=7,
                    table_id="lager_bewegung",
        )
        self._bewegung_table.setColumnHidden(0, True)
        return self._bewegung_table

    # ------------------------------------------------------------------
    # Signale
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        self._search_artikel.search_changed.connect(self._on_search_artikel)
        self._search_artikel.cleared.connect(self._load_artikel)
        self._artikel_table.row_double_clicked.connect(self._on_artikel_double_click)
        self._search_bewegung.search_changed.connect(self._load_bewegungen)
        self._search_bewegung.cleared.connect(self._load_bewegungen)
        self._tabs.currentChanged.connect(self._on_tab_changed)

    # ------------------------------------------------------------------
    # Daten laden
    # ------------------------------------------------------------------

    def _load_artikel(self, suchtext: str = "") -> None:
        try:
            with db.session() as session:
                self._artikel_dtos = lager_service.alle_artikel(
                    session,
                    nur_aktive=not self._show_inactive,
                    suchtext=suchtext,
                )
        except Exception as e:
            self._banner.show_error(f"Fehler beim Laden: {e}")
            return

        def fmt_preis(v: Decimal) -> str:
            return f"{v:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")

        rows = []
        colors = {}
        for i, dto in enumerate(self._artikel_dtos):
            rows.append([
                dto.id,
                dto.artikelnummer,
                dto.beschreibung,
                dto.einheit or "–",
                fmt_preis(dto.einzelpreis_netto),
                dto.bestand_anzeige,
                "Aktiv" if dto.is_active else "Inaktiv",
            ])
            if dto.bestand_negativ:
                colors[i] = QColor(Colors.ERROR)
            elif dto.bestand_kritisch:
                colors[i] = QColor(Colors.WARNING)
            elif not dto.is_active:
                colors[i] = QColor(Colors.TEXT_DISABLED)

        self._artikel_table.set_data(rows)
        for row, color in colors.items():
            self._artikel_table.set_row_color(row, color)

    def _load_bewegungen(self, filter_nr: str = "") -> None:
        try:
            with db.session() as session:
                self._bewegung_dtos = lager_service.bewegungen(
                    session,
                    artikelnummer=filter_nr.strip() or None,
                    limit=500,
                )
        except Exception as e:
            self._banner.show_error(f"Fehler beim Laden: {e}")
            return

        def fmt_bestand(v: Decimal) -> str:
            return f"{float(v):g}"

        rows = []
        colors = {}
        for i, dto in enumerate(self._bewegung_dtos):
            rows.append([
                dto.id,
                dto.erstellt_am,
                dto.artikelnummer,
                dto.buchungsart,
                dto.menge_anzeige,
                fmt_bestand(dto.bestand_vor),
                fmt_bestand(dto.bestand_nach),
                dto.referenz or "–",
                dto.user,
            ])
            farbe = BUCHUNGSART_FARBEN.get(dto.buchungsart)
            if farbe:
                colors[i] = farbe

        self._bewegung_table.set_data(rows)
        for row, color in colors.items():
            self._bewegung_table.set_row_color(row, color)

    def _update_stats(self) -> None:
        """Aktualisiert die Statistik-Leiste."""
        try:
            with db.session() as session:
                stats = lager_service.artikel_statistik(session)
        except Exception:
            return

        def fmt(v: Decimal) -> str:
            return f"{v:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")

        self._stat_labels["aktiv"].setText(str(stats["aktiv"]))
        self._stat_labels["kritisch"].setText(str(stats["kritisch"]))
        self._stat_labels["negativ"].setText(str(stats["negativ"]))
        self._stat_labels["lagerwert"].setText(fmt(stats["lagerwert"]))

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def _on_search_artikel(self, text: str) -> None:
        self._load_artikel(suchtext=text)

    def _on_inactive_toggled(self, checked: bool) -> None:
        self._show_inactive = checked
        self._load_artikel(self._search_artikel.text())

    def _on_artikel_double_click(self, source_row: int) -> None:
        try:
            dto = self._artikel_dtos[source_row]
            self._edit_artikel(dto)
        except IndexError:
            pass

    def showEvent(self, event) -> None:
        """Aktualisiert Daten automatisch wenn das Modul angezeigt wird."""
        super().showEvent(event)
        self._load_artikel(self._search_artikel.text())
        self._update_stats()

    def _on_tab_changed(self, index: int) -> None:
        if index == 1:
            self._load_bewegungen(self._search_bewegung.text())

    def _context_menu_artikel(self, pos) -> None:
        row = self._artikel_table.current_source_row()
        if row < 0 or row >= len(self._artikel_dtos):
            return
        dto = self._artikel_dtos[row]

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

        menu.addAction("✏️  Bearbeiten").triggered.connect(
            lambda: self._edit_artikel(dto)
        )
        menu.addSeparator()
        menu.addAction("⬆  Einbuchen").triggered.connect(
            lambda: self._buchung_dialog(dto, "eingang")
        )
        menu.addAction("⬇  Ausbuchen").triggered.connect(
            lambda: self._buchung_dialog(dto, "ausgang")
        )
        menu.addAction("🔧  Bestand korrigieren").triggered.connect(
            lambda: self._buchung_dialog(dto, "korrektur")
        )
        menu.addSeparator()

        if dto.is_active:
            menu.addAction("🔴  Deaktivieren").triggered.connect(
                lambda: self._deaktivieren(dto)
            )
        else:
            menu.addAction("🟢  Reaktivieren").triggered.connect(
                lambda: self._reaktivieren(dto)
            )

        menu.exec(self._artikel_table.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------------
    # Aktionen
    # ------------------------------------------------------------------

    def _neuer_artikel(self) -> None:
        from ui.modules.lager.artikel_dialog import ArtikelDialog
        dlg = ArtikelDialog(parent=self)
        dlg.saved.connect(self._on_artikel_saved_new)
        dlg.exec()

    def _edit_artikel(self, dto: ArtikelDTO) -> None:
        from ui.modules.lager.artikel_dialog import ArtikelDialog
        dlg = ArtikelDialog(parent=self, dto=dto)
        dlg.saved.connect(lambda d: self._on_artikel_saved_edit(dto.id, d, dlg))
        dlg.exec()

    def _on_artikel_saved_new(self, dto: ArtikelDTO) -> None:
        with db.session() as session:
            result = lager_service.artikel_erstellen(session, dto)
        if result.success:
            self._banner.show_success(result.message)
            self._load_artikel(self._search_artikel.text())
            self._update_stats()
            # Dialog schließen
            for dlg in self.findChildren(type(self.sender())):
                dlg.accept()
        else:
            self._banner.show_error(result.message)

    def _on_artikel_saved_edit(self, artikel_id: int, dto: ArtikelDTO, dlg) -> None:
        with db.session() as session:
            result = lager_service.artikel_aktualisieren(session, artikel_id, dto)
        if result.success:
            dlg.accept()
            self._banner.show_success(result.message)
            self._load_artikel(self._search_artikel.text())
        else:
            dlg.show_error(result.message)

    def _schnell_einbuchen(self) -> None:
        """Einbuchen für ausgewählten Artikel oder Artikelauswahl."""
        row = self._artikel_table.current_source_row()
        if 0 <= row < len(self._artikel_dtos):
            self._buchung_dialog(self._artikel_dtos[row], "eingang")
        else:
            from ui.modules.lager.buchung_dialog import BuchungDialog
            dlg = BuchungDialog("eingang", parent=self)
            dlg.gebucht.connect(self._on_buchung_done)
            dlg.exec()

    def _schnell_ausbuchen(self) -> None:
        row = self._artikel_table.current_source_row()
        if 0 <= row < len(self._artikel_dtos):
            self._buchung_dialog(self._artikel_dtos[row], "ausgang")
        else:
            from ui.modules.lager.buchung_dialog import BuchungDialog
            dlg = BuchungDialog("ausgang", parent=self)
            dlg.gebucht.connect(self._on_buchung_done)
            dlg.exec()

    def _buchung_dialog(self, dto: ArtikelDTO, modus: str) -> None:
        from ui.modules.lager.buchung_dialog import BuchungDialog
        dlg = BuchungDialog(modus, artikel_dto=dto, parent=self)
        dlg.gebucht.connect(self._on_buchung_done)
        dlg.exec()

    def _on_buchung_done(self, message: str) -> None:
        self._banner.show_success(message)
        self._load_artikel(self._search_artikel.text())
        self._update_stats()
        if self._tabs.currentIndex() == 1:
            self._load_bewegungen(self._search_bewegung.text())

    def _deaktivieren(self, dto: ArtikelDTO) -> None:
        if not ConfirmDialog.ask(
            title="Artikel deaktivieren",
            message=f"'{dto.beschreibung}' deaktivieren?",
            detail="Der Artikel kann später reaktiviert werden.",
            confirm_text="Deaktivieren",
            danger=True,
            parent=self,
        ):
            return
        with db.session() as session:
            result = lager_service.artikel_deaktivieren(session, dto.id)
        if result.success:
            self._banner.show_success(result.message)
            self._load_artikel(self._search_artikel.text())
            self._update_stats()
        else:
            self._banner.show_error(result.message)

    def _reaktivieren(self, dto: ArtikelDTO) -> None:
        with db.session() as session:
            result = lager_service.artikel_reaktivieren(session, dto.id)
        if result.success:
            self._banner.show_success(result.message)
            self._load_artikel(self._search_artikel.text())
            self._update_stats()
        else:
            self._banner.show_error(result.message)
