"""
ui/modules/belege/panel.py – Hauptpanel für Eingangsrechnungen / Belege
========================================================================
Liste aller Belege mit Filtern, Statistik und CRUD-Operationen.
"""

import logging
import os
import subprocess
import sys
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QComboBox, QMenu, QDateEdit,
)

from core.db.engine import db
from core.services.belege_service import (
    belege_service, EingangsRechnungDTO, BelegKategorie, Zahlungsstatus,
)
from ui.components.widgets import (
    SearchBar, DataTable, NotificationBanner,
    EmptyState, ConfirmDialog,
)
from ui.theme.theme import Colors, Fonts, Spacing, Radius, on_theme_changed

logger = logging.getLogger(__name__)


class BelegePanel(QWidget):
    """
    Vollständiges Modul für Eingangsrechnungen / Belege.
    Listenansicht mit Filtern, Statistik-Karten und Dialog für CRUD.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._belege_dtos: list[EingangsRechnungDTO] = []
        self._root_layout = None
        self._build_ui()
        self._connect_signals()
        self._load_belege()
        self._update_stats()
        on_theme_changed(self._on_theme_changed)

    def _on_theme_changed(self, _mode: str) -> None:
        if self._root_layout is not None:
            while self._root_layout.count():
                item = self._root_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            QWidget().setLayout(self._root_layout)
        self._build_ui()
        self._connect_signals()
        self._load_belege()
        self._update_stats()

    # ------------------------------------------------------------------
    # UI aufbauen
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        self._root_layout = root
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

        # Statistik
        root.addWidget(self._build_stats_row())

        # Toolbar + Tabelle
        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(Spacing.XL, Spacing.MD, Spacing.XL, Spacing.MD)
        cl.setSpacing(Spacing.SM)
        cl.addWidget(self._build_toolbar())
        cl.addWidget(self._build_table())

        # Summen-Zeile
        cl.addWidget(self._build_summen_zeile())

        root.addWidget(content, 1)

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("belegePanelHeader")
        header.setFixedHeight(64)
        header.setStyleSheet(f"""
            #belegePanelHeader {{
                background-color: {Colors.BG_SURFACE};
                border-bottom: 1px solid {Colors.BORDER};
            }}
        """)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(Spacing.XL, 0, Spacing.XL, 0)

        icon = QLabel("📥")
        icon.setStyleSheet("font-size: 22px; background: transparent;")
        title = QLabel("Eingangsrechnungen / Belege")
        title.setFont(Fonts.heading2())
        title.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; background: transparent;")

        layout.addWidget(icon)
        layout.addSpacing(Spacing.SM)
        layout.addWidget(title)
        layout.addStretch()

        # Zähler
        self._count_label = QLabel("0 Belege")
        self._count_label.setFont(Fonts.caption())
        self._count_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; background: transparent;")
        layout.addWidget(self._count_label)
        layout.addSpacing(Spacing.LG)

        btn_new = QPushButton("➕  Neuer Beleg")
        btn_new.clicked.connect(self._neuer_beleg)
        layout.addWidget(btn_new)

        return header

    def _build_stats_row(self) -> QWidget:
        row = QWidget()
        row.setObjectName("belegeStatsRow")
        row.setStyleSheet(
            f"#belegeStatsRow {{ background-color: {Colors.BG_SURFACE}; "
            f"border-bottom: 1px solid {Colors.BORDER}; }}"
        )
        layout = QHBoxLayout(row)
        layout.setContentsMargins(Spacing.XL, Spacing.MD, Spacing.XL, Spacing.MD)
        layout.setSpacing(Spacing.LG)

        self._stat_labels = {}
        stats = [
            ("gesamt",   "Gesamt",          Colors.TEXT_PRIMARY),
            ("offen",    "Offen",           Colors.WARNING),
            ("bezahlt",  "Bezahlt",         Colors.SUCCESS),
            ("summe",    "Summe Brutto",    Colors.INFO),
        ]
        for key, label, color in stats:
            card = QWidget()
            card_name = f"belegeStatCard_{key}"
            card.setObjectName(card_name)
            card.setStyleSheet(f"#{card_name} {{ background: transparent; }}")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(0, 0, 0, 0)
            cl.setSpacing(2)

            val_label = QLabel("–")
            val_label.setFont(Fonts.get(Fonts.SIZE_XL, bold=True))
            val_label.setStyleSheet(f"color: {color};")
            self._stat_labels[key] = val_label

            desc_label = QLabel(label)
            desc_label.setFont(Fonts.caption())
            desc_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")

            cl.addWidget(val_label)
            cl.addWidget(desc_label)
            layout.addWidget(card)

        layout.addStretch()
        return row

    def _build_toolbar(self) -> QWidget:
        toolbar = QWidget()
        toolbar.setObjectName("belegeToolbar")
        toolbar.setStyleSheet("#belegeToolbar { background: transparent; }")
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Spacing.SM)

        self._search = SearchBar("Belege suchen (Lieferant, Belegnr.)…")
        layout.addWidget(self._search, 1)

        # Kategorie-Filter
        self._filter_kategorie = QComboBox()
        self._filter_kategorie.addItem("Alle Kategorien", "")
        for kat in BelegKategorie.alle():
            self._filter_kategorie.addItem(kat, kat)
        self._filter_kategorie.setFixedWidth(160)
        layout.addWidget(self._filter_kategorie)

        # Status-Filter
        self._filter_status = QComboBox()
        self._filter_status.addItem("Alle Status", "")
        for st in Zahlungsstatus.ALLE:
            self._filter_status.addItem(st, st)
        self._filter_status.setFixedWidth(130)
        layout.addWidget(self._filter_status)

        # Refresh
        btn_refresh = QPushButton("↻")
        btn_refresh.setProperty("role", "secondary")
        btn_refresh.setFixedWidth(40)
        btn_refresh.clicked.connect(lambda: self._load_belege())
        layout.addWidget(btn_refresh)

        return toolbar

    def _build_table(self) -> DataTable:
        self._table = DataTable(
            columns=[
                "ID", "Datum", "Lieferant", "Belegnr.", "Netto",
                "MwSt", "Brutto", "Kategorie", "Status", "Beleg",
            ],
            column_widths=[0, 90, 200, 100, 100, 80, 100, 110, 80, 50],
            stretch_column=2,
            table_id="belege_liste",
        )
        self._table.setColumnHidden(0, True)  # ID verstecken
        self._table.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._table.customContextMenuRequested.connect(self._context_menu)
        return self._table

    def _build_summen_zeile(self) -> QFrame:
        """Summenzeile unter der Tabelle."""
        frame = QFrame()
        frame.setObjectName("belegeSummenZeile")
        frame.setStyleSheet(f"""
            #belegeSummenZeile {{
                background-color: {Colors.BG_SURFACE};
                border: 1px solid {Colors.BORDER};
                border-radius: {Radius.SM}px;
                padding: 6px 12px;
            }}
        """)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(12, 6, 12, 6)

        self._lbl_summe_netto = QLabel("Netto: 0,00 EUR")
        self._lbl_summe_netto.setFont(Fonts.get(Fonts.SIZE_BASE, bold=True))
        self._lbl_summe_netto.setStyleSheet(f"color: {Colors.TEXT_PRIMARY};")

        self._lbl_summe_mwst = QLabel("MwSt: 0,00 EUR")
        self._lbl_summe_mwst.setFont(Fonts.get(Fonts.SIZE_BASE))
        self._lbl_summe_mwst.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")

        self._lbl_summe_brutto = QLabel("Brutto: 0,00 EUR")
        self._lbl_summe_brutto.setFont(Fonts.get(Fonts.SIZE_BASE, bold=True))
        self._lbl_summe_brutto.setStyleSheet(f"color: {Colors.SUCCESS};")

        layout.addWidget(self._lbl_summe_netto)
        layout.addSpacing(Spacing.XL)
        layout.addWidget(self._lbl_summe_mwst)
        layout.addSpacing(Spacing.XL)
        layout.addWidget(self._lbl_summe_brutto)
        layout.addStretch()

        return frame

    # ------------------------------------------------------------------
    # Signale
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        self._search.search_changed.connect(self._on_search)
        self._search.cleared.connect(lambda: self._load_belege())
        self._filter_kategorie.currentIndexChanged.connect(
            lambda _: self._load_belege()
        )
        self._filter_status.currentIndexChanged.connect(
            lambda _: self._load_belege()
        )
        self._table.row_double_clicked.connect(self._on_double_click)

    # ------------------------------------------------------------------
    # Daten laden
    # ------------------------------------------------------------------

    def _load_belege(self, suchtext: str = "") -> None:
        try:
            kat = self._filter_kategorie.currentData() or ""
            status = self._filter_status.currentData() or ""

            with db.session() as session:
                self._belege_dtos = belege_service.alle_belege(
                    session,
                    suchtext=suchtext,
                    kategorie=kat,
                    zahlungsstatus=status,
                )
        except Exception as e:
            self._banner.show_error(f"Fehler beim Laden: {e}")
            logger.exception("Belege laden fehlgeschlagen")
            return

        self._fill_table()
        self._update_stats()
        self._update_summen()
        self._count_label.setText(f"{len(self._belege_dtos)} Belege")

    def _fill_table(self) -> None:
        rows = []
        for dto in self._belege_dtos:
            netto = f"{float(dto.betrag_netto):,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
            mwst = f"{float(dto.mwst_betrag):,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
            brutto = f"{float(dto.betrag_brutto):,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
            beleg_icon = "📄" if dto.beleg_pfad else ""

            rows.append([
                str(dto.id),
                dto.datum,
                dto.lieferant,
                dto.belegnummer,
                netto,
                mwst,
                brutto,
                dto.kategorie,
                dto.zahlungsstatus,
                beleg_icon,
            ])

        self._table.set_data(rows)

    def _update_stats(self) -> None:
        try:
            with db.session() as session:
                stats = belege_service.statistik(session)
        except Exception:
            return

        self._stat_labels["gesamt"].setText(str(stats["gesamt"]))
        self._stat_labels["offen"].setText(str(stats["offen"]))
        self._stat_labels["bezahlt"].setText(str(stats["bezahlt"]))
        brutto_str = f"{float(stats['summe_brutto']):,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
        self._stat_labels["summe"].setText(brutto_str)

    def _update_summen(self) -> None:
        """Aktualisiert die Summenzeile basierend auf den aktuell angezeigten Belegen."""
        summe_netto = sum(dto.betrag_netto for dto in self._belege_dtos)
        summe_mwst = sum(dto.mwst_betrag for dto in self._belege_dtos)
        summe_brutto = sum(dto.betrag_brutto for dto in self._belege_dtos)

        def fmt(val):
            return f"{float(val):,.2f} EUR".replace(",", "X").replace(".", ",").replace("X", ".")

        self._lbl_summe_netto.setText(f"Netto: {fmt(summe_netto)}")
        self._lbl_summe_mwst.setText(f"MwSt: {fmt(summe_mwst)}")
        self._lbl_summe_brutto.setText(f"Brutto: {fmt(summe_brutto)}")

    # ------------------------------------------------------------------
    # Aktionen
    # ------------------------------------------------------------------

    def _on_search(self, text: str) -> None:
        self._load_belege(suchtext=text)

    def _on_double_click(self, row_index: int) -> None:
        if 0 <= row_index < len(self._belege_dtos):
            self._beleg_bearbeiten(self._belege_dtos[row_index])

    def _neuer_beleg(self) -> None:
        from ui.modules.belege.dialog import BelegDialog
        dlg = BelegDialog(parent=self)
        dlg.saved.connect(self._on_saved)
        dlg.exec()

    def _beleg_bearbeiten(self, dto: EingangsRechnungDTO) -> None:
        from ui.modules.belege.dialog import BelegDialog
        dlg = BelegDialog(parent=self, dto=dto)
        dlg.saved.connect(self._on_saved)
        dlg.exec()

    def _on_saved(self, _dto) -> None:
        self._load_belege()
        self._banner.show_success("Beleg erfolgreich gespeichert.")

    def _context_menu(self, pos) -> None:
        index = self._table.indexAt(pos)
        if not index.isValid():
            return

        # Proxy → Source-Zeile mapppen
        source_index = self._table._proxy.mapToSource(index)
        row = source_index.row()
        if row < 0 or row >= len(self._belege_dtos):
            return

        dto = self._belege_dtos[row]

        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {Colors.BG_ELEVATED};
                color: {Colors.TEXT_PRIMARY};
                border: 1px solid {Colors.BORDER};
                padding: 4px;
            }}
            QMenu::item:selected {{
                background-color: {Colors.PRIMARY};
                color: white;
            }}
        """)

        act_edit = menu.addAction("✏  Bearbeiten")
        act_edit.triggered.connect(lambda: self._beleg_bearbeiten(dto))

        # Status umschalten
        if dto.zahlungsstatus == Zahlungsstatus.OFFEN:
            act_status = menu.addAction("✅  Als bezahlt markieren")
            act_status.triggered.connect(
                lambda: self._status_umschalten(dto.id, Zahlungsstatus.BEZAHLT)
            )
        else:
            act_status = menu.addAction("↩  Auf offen setzen")
            act_status.triggered.connect(
                lambda: self._status_umschalten(dto.id, Zahlungsstatus.OFFEN)
            )

        # Beleg anzeigen
        if dto.beleg_pfad:
            menu.addSeparator()
            act_show = menu.addAction("📄  Beleg öffnen")
            act_show.triggered.connect(lambda: self._beleg_oeffnen(dto))

        menu.addSeparator()
        act_delete = menu.addAction("🗑  Deaktivieren")
        act_delete.triggered.connect(lambda: self._beleg_deaktivieren(dto))

        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _status_umschalten(self, beleg_id: int, neuer_status: str) -> None:
        try:
            with db.session() as session:
                result = belege_service.zahlungsstatus_setzen(
                    session, beleg_id, neuer_status
                )
            if result.success:
                self._banner.show_success(result.message)
            else:
                self._banner.show_error(result.message)
        except Exception as e:
            self._banner.show_error(f"Fehler: {e}")
        self._load_belege()

    def _beleg_oeffnen(self, dto: EingangsRechnungDTO) -> None:
        """Öffnet die Belegdatei im Standard-Viewer des Betriebssystems."""
        if not dto.beleg_pfad:
            return
        abs_pfad = belege_service.beleg_dateipfad_absolut(dto.beleg_pfad)
        if not abs_pfad.exists():
            self._banner.show_error(f"Datei nicht gefunden: {abs_pfad}")
            return
        try:
            if sys.platform == "win32":
                os.startfile(str(abs_pfad))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(abs_pfad)])
            else:
                subprocess.Popen(["xdg-open", str(abs_pfad)])
        except Exception as e:
            self._banner.show_error(f"Datei konnte nicht geöffnet werden: {e}")

    def _beleg_deaktivieren(self, dto: EingangsRechnungDTO) -> None:
        ok = ConfirmDialog.ask(
            self,
            "Beleg deaktivieren",
            f"Beleg von '{dto.lieferant}' wirklich deaktivieren?\n"
            f"(Der Beleg wird nur ausgeblendet, nicht gelöscht.)",
        )
        if not ok:
            return
        try:
            with db.session() as session:
                result = belege_service.beleg_deaktivieren(session, dto.id)
            if result.success:
                self._banner.show_success(result.message)
            else:
                self._banner.show_error(result.message)
        except Exception as e:
            self._banner.show_error(f"Fehler: {e}")
        self._load_belege()

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._refresh_kategorien()
        self._load_belege()

    def _refresh_kategorien(self) -> None:
        """Aktualisiert das Kategorie-Dropdown mit neuen Ordnern."""
        aktuelle = self._filter_kategorie.currentData() or ""
        self._filter_kategorie.blockSignals(True)
        self._filter_kategorie.clear()
        self._filter_kategorie.addItem("Alle Kategorien", "")
        for kat in BelegKategorie.alle():
            self._filter_kategorie.addItem(kat, kat)
        # Vorherige Auswahl wiederherstellen
        if aktuelle:
            idx = self._filter_kategorie.findData(aktuelle)
            if idx >= 0:
                self._filter_kategorie.setCurrentIndex(idx)
        self._filter_kategorie.blockSignals(False)
