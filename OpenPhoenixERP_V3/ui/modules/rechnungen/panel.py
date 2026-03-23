"""
ui/modules/rechnungen/panel.py – Hauptpanel Rechnungsverwaltung
===============================================================
Übersicht aller Rechnungen mit Filter, Sortierung,
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
from core.services.rechnungen_service import (
    rechnungen_service, RechnungDTO, RechnungStatus,
)
from core.services.pdf_service import pdf_service
from ui.components.widgets import (
    SearchBar, DataTable, NotificationBanner,
    EmptyState, StatusBadge, ConfirmDialog, SectionTitle,
)
from ui.theme.theme import Colors, Fonts, Spacing, Radius, on_theme_changed

logger = logging.getLogger(__name__)

# Farbzuordnung für Rechnungsstatus
STATUS_COLORS = {
    RechnungStatus.ENTWURF:    QColor(Colors.TEXT_DISABLED),
    RechnungStatus.OFFEN:      QColor(Colors.INFO),
    RechnungStatus.BEZAHLT:    QColor(Colors.SUCCESS),
    RechnungStatus.ERINNERUNG: QColor(Colors.WARNING),
    RechnungStatus.MAHNUNG1:   QColor("#F97316"),
    RechnungStatus.MAHNUNG2:   QColor(Colors.ERROR),
    RechnungStatus.INKASSO:    QColor("#DC2626"),
    RechnungStatus.STORNIERT:  QColor(Colors.TEXT_DISABLED),
    RechnungStatus.GUTSCHRIFT: QColor("#8B5CF6"),
}


class RechnungDetailPanel(QFrame):
    """Zeigt Details der ausgewählten Rechnung (rechte Seite)."""

    edit_requested = Signal(object)      # RechnungDTO
    storno_requested = Signal(object)    # RechnungDTO

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(300)
        self._dto: Optional[RechnungDTO] = None
        self._styled_widgets: list = []
        self._build_ui()
        on_theme_changed(self._on_theme_changed)

    def _on_theme_changed(self, _mode: str) -> None:
        """Aktualisiert inline Styles nach Theme-Wechsel."""
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
        container.setObjectName("rechnungDetailContainer")
        _container_style = lambda: f"#rechnungDetailContainer {{ background-color: {Colors.BG_APP}; }}"
        container.setStyleSheet(_container_style())
        self._styled_widgets.append((container, _container_style))
        scroll.setWidget(container)

        self._main = QVBoxLayout(container)
        self._main.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        self._main.setSpacing(Spacing.MD)

        self._empty = EmptyState("🧾", "Keine Rechnung ausgewählt", "Wählen Sie eine Rechnung aus der Liste.")
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
            ("Fällig", "faellig"),
            ("Netto", "netto"),
            ("MwSt", "mwst"),
            ("Brutto", "brutto"),
            ("Offen", "offen"),
            ("Gutschrift zu", "storno_zu_nr"),
        ]:
            row = QHBoxLayout()
            l = QLabel(lbl)
            l.setFont(Fonts.get(Fonts.SIZE_SM))
            _l_style = lambda: f"color: {Colors.TEXT_SECONDARY};"
            l.setStyleSheet(_l_style())
            self._styled_widgets.append((l, _l_style))
            l.setFixedWidth(70)
            v = QLabel("–")
            v.setFont(Fonts.get(Fonts.SIZE_SM))
            v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            if key in ("brutto", "offen"):
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

    def show_rechnung(self, dto: RechnungDTO) -> None:
        self._dto = dto
        self._empty.setVisible(False)
        self._detail.setVisible(True)

        self._nr_label.setText(dto.rechnungsnummer)
        self._status_badge.set_status(dto.status)
        self._kunde_label.setText(f"👤 {dto.kunde_display}")

        def fmt(v) -> str:
            return f"{v:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")

        self._fields["datum"].setText(dto.rechnungsdatum)
        self._fields["faellig"].setText(dto.faelligkeitsdatum or "–")
        self._fields["netto"].setText(fmt(dto.summe_netto))
        self._fields["mwst"].setText(fmt(dto.summe_mwst))
        self._fields["brutto"].setText(fmt(dto.summe_brutto))
        self._fields["offen"].setText(fmt(dto.offener_betrag))
        if dto.storno_zu_nr:
            self._fields["storno_zu_nr"].setText(dto.storno_zu_nr)
            self._fields["storno_zu_nr"].parent().setVisible(True)
        else:
            self._fields["storno_zu_nr"].setText("")
            self._fields["storno_zu_nr"].parent().setVisible(False)

        label = "📖  Anzeigen" if dto.is_finalized else "✏️  Bearbeiten"
        self._btn_open.setText(label)

    def clear(self) -> None:
        self._dto = None
        self._empty.setVisible(True)
        self._detail.setVisible(False)


class RechnungenPanel(QWidget):
    """Vollständiges Rechnungsmodul."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_dtos: list[RechnungDTO] = []
        self._styled_widgets: list = []
        self._build_ui()
        self._connect_signals()
        self._load()
        on_theme_changed(self._on_theme_changed)

    def _on_theme_changed(self, _mode: str) -> None:
        """Aktualisiert inline Styles nach Theme-Wechsel."""
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

        self._detail_panel = RechnungDetailPanel()

        splitter.addWidget(left)
        splitter.addWidget(self._detail_panel)
        splitter.setSizes([780, 300])
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)

        root.addWidget(splitter, 1)

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("rechnungenPanelHeader")
        header.setFixedHeight(64)
        _hdr_style = lambda: f"""
            #rechnungenPanelHeader {{
                background-color: {Colors.BG_SURFACE};
                border-bottom: 1px solid {Colors.BORDER};
            }}
        """
        header.setStyleSheet(_hdr_style())
        self._styled_widgets.append((header, _hdr_style))
        layout = QHBoxLayout(header)
        layout.setContentsMargins(Spacing.XL, 0, Spacing.XL, 0)

        icon = QLabel("🧾")
        icon.setStyleSheet("font-size: 22px; background: transparent;")
        title = QLabel("Rechnungen")
        title.setFont(Fonts.heading2())
        _title_style = lambda: f"color: {Colors.TEXT_PRIMARY}; background: transparent;"
        title.setStyleSheet(_title_style())
        self._styled_widgets.append((title, _title_style))

        self._count_badge = QLabel("0 Rechnungen")
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

        new_btn = QPushButton("➕  Neue Rechnung")
        new_btn.clicked.connect(self._new_rechnung)
        layout.addWidget(new_btn)

        return header

    def _build_toolbar(self) -> QWidget:
        toolbar = QWidget()
        toolbar.setObjectName("rechnungenToolbar")
        toolbar.setStyleSheet("#rechnungenToolbar { background: transparent; }")
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
        self._status_filter.addItem("Nur Entwürfe", [RechnungStatus.ENTWURF])
        self._status_filter.addItem("Nur offene", [
            RechnungStatus.OFFEN, RechnungStatus.ERINNERUNG,
            RechnungStatus.MAHNUNG1, RechnungStatus.MAHNUNG2, RechnungStatus.INKASSO,
        ])
        self._status_filter.addItem("Bezahlt", [RechnungStatus.BEZAHLT])
        self._status_filter.addItem("Storniert/Gutschrift", [
            RechnungStatus.STORNIERT, RechnungStatus.GUTSCHRIFT,
        ])
        self._status_filter.setFixedWidth(180)
        self._status_filter.currentIndexChanged.connect(self._load)
        layout.addWidget(status_lbl)
        layout.addWidget(self._status_filter)

        return toolbar

    def _build_table(self) -> DataTable:
        self._table = DataTable(
            columns=[
                "ID", "Rechnungsnr.", "Datum", "Fällig",
                "Kunde", "Netto", "MwSt", "Brutto", "Status"
            ],
            column_widths=[0, 120, 100, 100, 180, 100, 90, 110, 200],
            stretch_column=4,
                    table_id="rechnungen_liste",
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
        self._detail_panel.edit_requested.connect(self._open_rechnung)

    # ------------------------------------------------------------------
    # Daten laden
    # ------------------------------------------------------------------

    def _load(self, *_) -> None:
        suchtext = self._search.text()
        status_data = self._status_filter.currentData()

        try:
            with db.session() as session:
                self._current_dtos = rechnungen_service.alle(
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
                dto.rechnungsnummer,
                dto.rechnungsdatum,
                dto.faelligkeitsdatum or "–",
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
        self._count_badge.setText(f"{n} Rechnung{'en' if n != 1 else ''}")

        if n == 0:
            self._detail_panel.clear()

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def _on_row_selected(self, source_row: int) -> None:
        try:
            dto = self._current_dtos[source_row]
            self._detail_panel.show_rechnung(dto)
        except IndexError:
            self._detail_panel.clear()

    def _on_row_double_clicked(self, source_row: int) -> None:
        try:
            self._open_rechnung(self._current_dtos[source_row])
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

        label = "📖  Anzeigen" if dto.is_finalized else "✏️  Bearbeiten"
        menu.addAction(label).triggered.connect(lambda: self._open_rechnung(dto))

        if not dto.is_finalized:
            menu.addSeparator()
            menu.addAction("🗑  Entwurf löschen").triggered.connect(lambda: self._delete_draft(dto))

        if dto.is_finalized and dto.status not in (RechnungStatus.STORNIERT, RechnungStatus.GUTSCHRIFT):
            menu.addSeparator()
            menu.addAction("✅  Als bezahlt markieren").triggered.connect(
                lambda: self._quick_status(dto, RechnungStatus.BEZAHLT)
            )
            menu.addAction("↩  Stornieren").triggered.connect(lambda: self._stornieren(dto))

        if dto.is_finalized:
            menu.addSeparator()
            menu.addAction("📄  PDF generieren").triggered.connect(
                lambda: self._export_pdf(dto)
            )
            menu.addAction("⬇  XRechnung (XML)").triggered.connect(
                lambda: self._export_xrechnung(dto)
            )
            menu.addAction("✨  Beide exportieren").triggered.connect(
                lambda: self._export_beide(dto)
            )

        menu.addSeparator()
        menu.addAction("📂  Kundendokumente").triggered.connect(
            lambda: self._show_kunde_documents(dto)
        )
        menu.addAction("📧  E-Mail senden").triggered.connect(
            lambda: self._send_email(dto)
        )

        menu.exec(self._table.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------------
    # Aktionen
    # ------------------------------------------------------------------

    def _new_rechnung(self) -> None:
        """Neue Rechnung – erst Kunden auswählen."""
        from ui.modules.rechnungen.kunden_auswahl import KundenAuswahlDialog
        dlg = KundenAuswahlDialog(parent=self)
        dlg.selected.connect(self._open_new_for_kunde)
        dlg.exec()

    def _open_new_for_kunde(self, kunde_id: int, kunde_name: str) -> None:
        from ui.modules.rechnungen.dialog import RechnungDialog
        dlg = RechnungDialog(
            parent=self,
            kunde_id=kunde_id,
            kunde_name=kunde_name,
            title=f"Neue Rechnung – {kunde_name}",
        )
        dlg.saved.connect(lambda dto: self._on_saved_new(dto, dlg))
        dlg.exec()

    def _open_rechnung(self, dto: RechnungDTO) -> None:
        # Vollständige Rechnung mit Posten laden
        with db.session() as session:
            full_dto = rechnungen_service.nach_id(session, dto.id)
        if not full_dto:
            self._banner.show_error("Rechnung nicht gefunden.")
            return

        from ui.modules.rechnungen.dialog import RechnungDialog
        title = (
            f"Rechnung {full_dto.rechnungsnummer} – {full_dto.kunde_display}"
        )
        dlg = RechnungDialog(
            parent=self, dto=full_dto,
            kunde_name=full_dto.kunde_display,
            title=title,
        )
        dlg.saved.connect(lambda d: self._on_saved_edit(d, dlg, full_dto.id))
        dlg.status_changed.connect(lambda rid, s: self._load())
        result = dlg.exec()

        if result == 2:  # Entwurf gelöscht
            self._banner.show_success("Entwurf gelöscht.")
            self._load()
            self._detail_panel.clear()
        elif result == 3:  # Storniert
            self._banner.show_success("Rechnung storniert.")
            self._load()

    def _on_saved_new(self, dto: RechnungDTO, dlg) -> None:
        with db.session() as session:
            result = rechnungen_service.entwurf_erstellen(session, dto.kunde_id, dto)

        if result.success:
            new_id = result.data.id
            # Finalisieren wenn der Dialog das angefordert hat (_finalize_requested)
            if getattr(dlg, "_finalize_requested", False):
                with db.session() as session:
                    fin = rechnungen_service.finalisieren(session, new_id)
                if fin.success:
                    self._banner.show_success(fin.message)
                else:
                    self._banner.show_error(fin.message)
                    return
            else:
                self._banner.show_success(result.message)
            dlg.accept()
            self._load()
        else:
            dlg.show_error(result.message)

    def _on_saved_edit(self, dto: RechnungDTO, dlg, rechnung_id: int) -> None:
        with db.session() as session:
            result = rechnungen_service.entwurf_aktualisieren(session, rechnung_id, dto)

        if result.success:
            # Prüfen ob Finalisierung angefordert
            from PySide6.QtWidgets import QDialog
            if hasattr(dlg, '_finalize_requested') and dlg._finalize_requested:
                with db.session() as session:
                    fin = rechnungen_service.finalisieren(session, rechnung_id)
                if fin.success:
                    self._banner.show_success(fin.message)
                else:
                    self._banner.show_error(fin.message)
                    return
            else:
                self._banner.show_success(result.message)
            dlg.accept()
            self._load()
        else:
            dlg.show_error(result.message)

    def _delete_draft(self, dto: RechnungDTO) -> None:
        if not ConfirmDialog.ask(
            title="Entwurf löschen",
            message=f"Entwurf '{dto.rechnungsnummer}' löschen?",
            detail="Alle Posten werden ebenfalls gelöscht.",
            confirm_text="Löschen",
            danger=True,
            parent=self,
        ):
            return
        with db.session() as session:
            result = rechnungen_service.entwurf_loeschen(session, dto.id)
        if result.success:
            self._banner.show_success(result.message)
            self._detail_panel.clear()
            self._load()
        else:
            self._banner.show_error(result.message)

    def _quick_status(self, dto: RechnungDTO, status: str) -> None:
        with db.session() as session:
            result = rechnungen_service.status_aendern(session, dto.id, status)
        if result.success:
            self._banner.show_success(result.message)
            self._load()
        else:
            self._banner.show_error(result.message)

    def _stornieren(self, dto: RechnungDTO) -> None:
        if not ConfirmDialog.ask(
            title="Rechnung stornieren",
            message=f"Rechnung '{dto.rechnungsnummer}' stornieren?",
            detail="Es wird eine Gegenbuchungs-Gutschrift erstellt. Lagerbestände werden zurückgebucht.",
            confirm_text="Stornieren",
            danger=True,
            parent=self,
        ):
            return
        with db.session() as session:
            result = rechnungen_service.stornieren(session, dto.id)
        if result.success:
            self._banner.show_success(result.message)
            self._load()
        else:
            self._banner.show_error(result.message)

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
    # Export: PDF & XRechnung – mit automatischer Kundenordner-Speicherung
    # ------------------------------------------------------------------

    def _export_pdf(self, dto: RechnungDTO) -> None:
        """Generiert PDF, speichert im Kundenordner und registriert im DMS."""
        try:
            from core.services.kunden_service import kunden_service
            with db.session() as session:
                full_dto = rechnungen_service.nach_id(session, dto.id)
                if not full_dto:
                    self._banner.show_error("Rechnung nicht gefunden.")
                    return
                # Prüfen ob Dokumentenordner konfiguriert
                ordner = kunden_service.kunden_ordner_pfad(session, dto.kunde_id)
                if not ordner:
                    self._banner.show_error(
                        "Kein Dokumentenordner konfiguriert. "
                        "Bitte unter Einstellungen → Pfade → Dokumentenordner festlegen."
                    )
                    return
                # PDF generieren
                pdf_bytes = pdf_service.rechnung_als_pdf_bytes(full_dto, session)
                safe_nr = full_dto.rechnungsnummer.replace("/", "-").replace("\\", "-")
                dateiname = f"Rechnung_{safe_nr}.pdf"
                # Im Kundenordner speichern + DMS-Eintrag
                ziel = kunden_service.dokument_in_kundenordner_erstellen(
                    session, dto.kunde_id, dateiname, pdf_bytes
                )
            if ziel:
                self._banner.show_success(f"PDF im Kundenordner gespeichert: {ziel.name}")
                self._oeffne_datei(str(ziel))
            else:
                self._banner.show_error("PDF konnte nicht gespeichert werden.")
        except Exception as e:
            self._banner.show_error(f"Fehler: {e}")

    def _export_xrechnung(self, dto: RechnungDTO) -> None:
        """Generiert XRechnung-XML, speichert im Kundenordner und registriert im DMS."""
        try:
            from core.services.kunden_service import kunden_service
            from core.services.xrechnung_service import xrechnung_service
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
                xdaten = xrechnung_service.xrechnung_daten_aus_dto(full_dto, session)
                # Pflichtfelder validieren BEVOR XML erzeugt wird
                validierung = xrechnung_service._validiere_pflichtfelder(xdaten)
                if validierung:
                    self._banner.show_error(validierung)
                    return
                xml_bytes = xrechnung_service._xml_erstellen(xdaten)
                safe_nr = full_dto.rechnungsnummer.replace("/", "-").replace("\\", "-")
                dateiname = f"XRechnung_{safe_nr}.xml"
                ziel = kunden_service.dokument_in_kundenordner_erstellen(
                    session, dto.kunde_id, dateiname, xml_bytes
                )
            if ziel:
                self._banner.show_success(f"XRechnung im Kundenordner gespeichert: {ziel.name}")
                self._oeffne_ordner(str(ordner))
            else:
                self._banner.show_error("XRechnung konnte nicht gespeichert werden.")
        except Exception as e:
            self._banner.show_error(f"Fehler: {e}")

    def _export_beide(self, dto: RechnungDTO) -> None:
        """Exportiert PDF + XRechnung in einem Schritt in den Kundenordner."""
        self._export_pdf(dto)
        self._export_xrechnung(dto)

    def _oeffne_datei(self, pfad: str) -> None:
        """Öffnet eine Datei mit dem Standard-Programm des OS."""
        import os, sys, subprocess
        try:
            if sys.platform == "win32":
                os.startfile(pfad)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", pfad])
            else:
                subprocess.Popen(["xdg-open", pfad])
        except Exception:
            pass

    def _oeffne_ordner(self, pfad: str) -> None:
        """Öffnet den Ordner im Explorer/Finder."""
        import os, sys, subprocess
        try:
            if sys.platform == "win32":
                os.startfile(pfad)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", pfad])
            else:
                subprocess.Popen(["xdg-open", pfad])
        except Exception:
            pass

    def load_for_kunde(self, kunde_id: int) -> None:
        """Filtert die Rechnungsliste auf einen bestimmten Kunden."""
        try:
            with db.session() as session:
                self._current_dtos = rechnungen_service.alle(session, kunde_id=kunde_id)
            self._refresh_table()
        except Exception as e:
            self._banner.show_error(f"Fehler: {e}")

    def _refresh_table(self) -> None:
        self._load()
