"""
ui/modules/kunden/panel.py – Hauptpanel der Kundenverwaltung
=============================================================
Vollständige Kundenverwaltung als PySide6-Panel.
Wird vom Hauptfenster in den StackedWidget eingebettet.
"""

import logging
from typing import Optional

from PySide6.QtCore import Qt, Signal, QThread, QObject
from PySide6.QtGui import QColor, QAction
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QCheckBox, QMenu,
    QSplitter, QStackedWidget, QScrollArea,
)

from core.db.engine import db
from core.services.kunden_service import kunden_service, KundeDTO
from ui.components.widgets import (
    SearchBar, DataTable, NotificationBanner,
    EmptyState, StatusBadge, ConfirmDialog, SectionTitle,
)
from ui.theme.theme import Colors, Fonts, Spacing, Radius
from ui.modules.kunden.notizen_widget import NotizenWidget

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Kunden-Detailansicht (rechte Seite)
# ---------------------------------------------------------------------------

class KundenDetailPanel(QScrollArea):
    """
    Zeigt die Details eines ausgewählten Kunden an.
    Rechte Spalte des Splitters.
    """

    edit_requested = Signal(object)       # KundeDTO
    deactivate_requested = Signal(object) # KundeDTO
    reactivate_requested = Signal(object) # KundeDTO
    documents_requested = Signal(object)  # KundeDTO
    new_invoice_requested = Signal(object)# KundeDTO

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMinimumWidth(320)
        self._dto: Optional[KundeDTO] = None
        self._build_ui()

    def _build_ui(self) -> None:
        container = QWidget()
        container.setStyleSheet(f"background-color: {Colors.BG_APP};")
        self.setWidget(container)

        self._main_layout = QVBoxLayout(container)
        self._main_layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        self._main_layout.setSpacing(Spacing.MD)

        # Leer-Zustand
        self._empty = EmptyState(
            "👤", "Kein Kunde ausgewählt",
            "Wählen Sie einen Kunden aus der Liste aus."
        )
        self._main_layout.addWidget(self._empty)

        # Detail-Inhalt (zunächst versteckt)
        self._detail_widget = QWidget()
        self._detail_widget.setVisible(False)
        detail_layout = QVBoxLayout(self._detail_widget)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(Spacing.MD)

        # Kopfzeile mit Name + Status
        name_row = QHBoxLayout()
        self._name_label = QLabel()
        self._name_label.setFont(Fonts.heading2())
        self._name_label.setWordWrap(True)
        self._status_badge = StatusBadge()
        name_row.addWidget(self._name_label, 1)
        name_row.addWidget(self._status_badge)
        detail_layout.addLayout(name_row)

        self._kundennr_label = QLabel()
        self._kundennr_label.setFont(Fonts.get(Fonts.SIZE_SM))
        self._kundennr_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        detail_layout.addWidget(self._kundennr_label)

        # Trennlinie
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background-color: {Colors.BORDER};")
        detail_layout.addWidget(line)

        # Aktions-Buttons
        btn_layout = QVBoxLayout()
        btn_layout.setSpacing(Spacing.SM)

        self._btn_edit = QPushButton("✏️  Bearbeiten")
        self._btn_edit.clicked.connect(
            lambda: self.edit_requested.emit(self._dto)
        )
        btn_layout.addWidget(self._btn_edit)

        self._btn_invoice = QPushButton("🧾  Neue Rechnung")
        self._btn_invoice.clicked.connect(
            lambda: self.new_invoice_requested.emit(self._dto)
        )
        btn_layout.addWidget(self._btn_invoice)

        self._btn_docs = QPushButton("📂  Dokumente")
        self._btn_docs.setProperty("role", "secondary")
        self._btn_docs.clicked.connect(
            lambda: self.documents_requested.emit(self._dto)
        )
        btn_layout.addWidget(self._btn_docs)

        self._btn_toggle = QPushButton()
        self._btn_toggle.clicked.connect(self._on_toggle_status)
        btn_layout.addWidget(self._btn_toggle)

        detail_layout.addLayout(btn_layout)

        # Informationsfelder
        self._info_frame = QFrame()
        self._info_frame.setProperty("frameRole", "surface")
        self._info_frame.setStyleSheet(f"""
            QFrame[frameRole="surface"] {{
                background-color: {Colors.BG_SURFACE};
                border-radius: {Radius.LG}px;
                border: 1px solid {Colors.BORDER};
            }}
        """)
        info_layout = QVBoxLayout(self._info_frame)
        info_layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        info_layout.setSpacing(Spacing.SM)

        self._info_fields: dict[str, QLabel] = {}
        fields = [
            ("Adresse",   "adresse"),
            ("Telefon",   "telefon"),
            ("E-Mail",    "email"),
            ("Geburtsdatum", "geburtsdatum"),
        ]
        for label_text, key in fields:
            row = QHBoxLayout()
            lbl = QLabel(label_text)
            lbl.setFont(Fonts.get(Fonts.SIZE_SM))
            lbl.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
            lbl.setFixedWidth(100)
            val = QLabel("–")
            val.setFont(Fonts.get(Fonts.SIZE_SM))
            val.setWordWrap(True)
            val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self._info_fields[key] = val
            row.addWidget(lbl)
            row.addWidget(val, 1)
            info_layout.addLayout(row)

        detail_layout.addWidget(self._info_frame)
        detail_layout.addStretch()

        # CRM-Notizen
        self._notizen = NotizenWidget()
        self._notizen.clear()
        detail_layout.addWidget(self._notizen)

        self._main_layout.addWidget(self._detail_widget)

    # ------------------------------------------------------------------
    # Daten
    # ------------------------------------------------------------------

    def show_customer(self, dto: KundeDTO) -> None:
        self._dto = dto
        self._empty.setVisible(False)
        self._detail_widget.setVisible(True)

        # Name + Status
        self._name_label.setText(dto.display_name)
        status = "Aktiv" if dto.is_active else "Inaktiv"
        self._status_badge.set_status(status)
        self._kundennr_label.setText(f"Kundennummer: {dto.zifferncode}")

        # Adresse zusammenbauen
        adresse_parts = []
        if dto.strasse or dto.hausnummer:
            adresse_parts.append(f"{dto.strasse} {dto.hausnummer}".strip())
        if dto.plz or dto.ort:
            adresse_parts.append(f"{dto.plz} {dto.ort}".strip())
        adresse = "\n".join(adresse_parts) if adresse_parts else "–"

        self._info_fields["adresse"].setText(adresse)
        self._info_fields["telefon"].setText(dto.telefon or "–")
        self._info_fields["email"].setText(dto.email or "–")
        self._info_fields["geburtsdatum"].setText(dto.geburtsdatum or "–")

        # Buttons anpassen
        self._btn_invoice.setEnabled(dto.is_active)
        self._btn_toggle.setText(
            "🔴  Deaktivieren" if dto.is_active else "🟢  Reaktivieren"
        )
        if dto.is_active:
            self._btn_toggle.setProperty("role", "")
        else:
            self._btn_toggle.setProperty("role", "success")
        self._btn_toggle.style().unpolish(self._btn_toggle)
        self._btn_toggle.style().polish(self._btn_toggle)
        self._notizen.load(dto.id)

    def clear(self) -> None:
        self._dto = None
        self._empty.setVisible(True)
        self._detail_widget.setVisible(False)
        if hasattr(self, '_notizen'):
            self._notizen.clear()

    def _on_toggle_status(self) -> None:
        if not self._dto:
            return
        if self._dto.is_active:
            self.deactivate_requested.emit(self._dto)
        else:
            self.reactivate_requested.emit(self._dto)


# ---------------------------------------------------------------------------
# Haupt-Panel
# ---------------------------------------------------------------------------

class KundenPanel(QWidget):
    """
    Vollständiges Kundenverwaltungs-Modul.
    Wird vom MainWindow in den StackedWidget eingebettet.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._show_inactive = False
        self._build_ui()
        self._connect_signals()
        self._load_customers()

    # ------------------------------------------------------------------
    # UI aufbauen
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Kopfzeile ─────────────────────────────────────────────────
        root.addWidget(self._build_header())

        # ── Benachrichtigungs-Banner ──────────────────────────────────
        banner_wrapper = QWidget()
        banner_layout = QVBoxLayout(banner_wrapper)
        banner_layout.setContentsMargins(Spacing.XL, Spacing.SM, Spacing.XL, 0)
        self._banner = NotificationBanner()
        banner_layout.addWidget(self._banner)
        root.addWidget(banner_wrapper)

        # ── Hauptbereich: Splitter links (Liste) + rechts (Detail) ────
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)
        splitter.setStyleSheet(f"""
            QSplitter::handle {{ background-color: {Colors.BORDER}; }}
        """)

        # Linke Seite: Toolbar + Tabelle
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(Spacing.XL, Spacing.MD, Spacing.MD, Spacing.MD)
        left_layout.setSpacing(Spacing.SM)

        left_layout.addWidget(self._build_toolbar())
        left_layout.addWidget(self._build_table())

        # Rechte Seite: Detailansicht
        self._detail_panel = KundenDetailPanel()

        splitter.addWidget(left_panel)
        splitter.addWidget(self._detail_panel)
        splitter.setSizes([720, 360])
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)

        root.addWidget(splitter, 1)

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

        icon = QLabel("👥")
        icon.setStyleSheet("font-size: 22px; background: transparent;")
        title = QLabel("Kundenverwaltung")
        title.setFont(Fonts.heading2())
        title.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; background: transparent;")

        self._count_badge = QLabel("0 Kunden")
        self._count_badge.setFont(Fonts.get(Fonts.SIZE_SM))
        self._count_badge.setStyleSheet(f"""
            background-color: {Colors.BG_ELEVATED};
            color: {Colors.TEXT_SECONDARY};
            border-radius: {Radius.SM}px;
            padding: 4px 10px;
        """)

        layout.addWidget(icon)
        layout.addSpacing(Spacing.SM)
        layout.addWidget(title)
        layout.addSpacing(Spacing.SM)
        layout.addWidget(self._count_badge)
        layout.addStretch()

        new_btn = QPushButton("➕  Neuer Kunde")
        new_btn.clicked.connect(self._new_customer)
        layout.addWidget(new_btn)

        return header

    def _build_toolbar(self) -> QWidget:
        toolbar = QWidget()
        toolbar.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Spacing.SM)

        self._search = SearchBar("Kunden suchen…")
        layout.addWidget(self._search, 1)

        self._inactive_check = QCheckBox("Inaktive anzeigen")
        self._inactive_check.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        self._inactive_check.toggled.connect(self._on_inactive_toggled)
        layout.addWidget(self._inactive_check)

        return toolbar

    def _build_table(self) -> DataTable:
        self._table = DataTable(
            columns=[
                "ID", "Kundennr.", "Nachname", "Vorname",
                "Titel / Firma", "PLZ", "Ort", "E-Mail", "Status"
            ],
            column_widths=[0, 90, 150, 130, 160, 70, 120, 200, 80],
            stretch_column=7,  # E-Mail streckt sich
            table_id="kunden_liste",
        )
        # ID-Spalte ausblenden
        self._table.setColumnHidden(0, True)
        # Kontextmenü
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_context_menu)
        return self._table

    # ------------------------------------------------------------------
    # Signale verbinden
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        self._search.search_changed.connect(self._on_search)
        self._search.cleared.connect(self._load_customers)
        self._table.row_selected.connect(self._on_row_selected)
        self._table.row_double_clicked.connect(self._on_row_double_clicked)

        self._detail_panel.edit_requested.connect(self._edit_customer)
        self._detail_panel.deactivate_requested.connect(self._deactivate_customer)
        self._detail_panel.reactivate_requested.connect(self._reactivate_customer)
        self._detail_panel.documents_requested.connect(self._show_documents)
        self._detail_panel.new_invoice_requested.connect(self._new_invoice)

    # ------------------------------------------------------------------
    # Daten laden
    # ------------------------------------------------------------------

    def _load_customers(self, search: str = "") -> None:
        try:
            with db.session() as session:
                dtos = kunden_service.alle(
                    session,
                    nur_aktive=not self._show_inactive,
                    suchtext=search,
                )
        except Exception as e:
            self._banner.show_error(f"Fehler beim Laden der Kunden: {e}")
            logger.exception("Kunden laden fehlgeschlagen:")
            return

        # Tabellendaten aufbauen
        rows = []
        colors = {}
        for i, dto in enumerate(dtos):
            rows.append([
                dto.id,
                dto.zifferncode,
                dto.name,
                dto.vorname,
                dto.titel_firma,
                dto.plz,
                dto.ort,
                dto.email,
                "Aktiv" if dto.is_active else "Inaktiv",
            ])
            if not dto.is_active:
                colors[i] = QColor(Colors.TEXT_DISABLED)

        self._table.set_data(rows)
        for row, color in colors.items():
            self._table.set_row_color(row, color)

        # Zähler
        total = len(dtos)
        self._count_badge.setText(
            f"{total} Kunde{'n' if total != 1 else ''}"
        )

        # Detail leeren wenn nichts mehr ausgewählt
        if total == 0:
            self._detail_panel.clear()

        # DTOs für spätere Zugriffe merken
        self._current_dtos = dtos

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def _on_search(self, text: str) -> None:
        self._load_customers(search=text)

    def _on_inactive_toggled(self, checked: bool) -> None:
        self._show_inactive = checked
        self._load_customers(self._search.text())

    def _on_row_selected(self, source_row: int) -> None:
        try:
            dto = self._current_dtos[source_row]
            self._detail_panel.show_customer(dto)
        except IndexError:
            self._detail_panel.clear()

    def _on_row_double_clicked(self, source_row: int) -> None:
        try:
            dto = self._current_dtos[source_row]
            self._edit_customer(dto)
        except IndexError:
            pass

    def _show_context_menu(self, pos) -> None:
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

        action_edit = menu.addAction("✏️  Bearbeiten")
        action_docs = menu.addAction("📂  Dokumente")
        menu.addSeparator()

        if dto.is_active:
            action_invoice = menu.addAction("🧾  Neue Rechnung")
            action_invoice.triggered.connect(lambda: self._new_invoice(dto))
            action_toggle = menu.addAction("🔴  Deaktivieren")
            action_toggle.triggered.connect(lambda: self._deactivate_customer(dto))
        else:
            action_toggle = menu.addAction("🟢  Reaktivieren")
            action_toggle.triggered.connect(lambda: self._reactivate_customer(dto))

        action_edit.triggered.connect(lambda: self._edit_customer(dto))
        action_docs.triggered.connect(lambda: self._show_documents(dto))

        menu.exec(self._table.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------------
    # Aktionen
    # ------------------------------------------------------------------

    def _new_customer(self) -> None:
        from ui.modules.kunden.dialog import KundenDialog
        dlg = KundenDialog(parent=self)
        dlg.saved.connect(lambda dto: self._on_customer_save_new(dto, dlg))
        dlg.exec()

    def _edit_customer(self, dto: KundeDTO) -> None:
        from ui.modules.kunden.dialog import KundenDialog
        dlg = KundenDialog(
            parent=self, dto=dto,
            title=f"Kunde bearbeiten – {dto.display_name}",
        )
        dlg.saved.connect(lambda new_dto: self._on_customer_save_edit(dto.id, new_dto, dlg))
        dlg.exec()

    def _on_customer_save_new(self, dto: KundeDTO, dlg) -> None:
        with db.session() as session:
            result = kunden_service.erstellen(session, dto)

        if result.success:
            dlg.close_dialog()
            self._banner.show_success(result.message)
            self._load_customers(self._search.text())
            if result.data:
                self._table.select_row_by_id(result.data.id)
        else:
            dlg.show_error(result.message)

    def _on_customer_save_edit(self, kunde_id: int, dto: KundeDTO, dlg) -> None:
        with db.session() as session:
            result = kunden_service.aktualisieren(session, kunde_id, dto)

        if result.success:
            dlg.close_dialog()
            self._banner.show_success(result.message)
            self._load_customers(self._search.text())
            self._table.select_row_by_id(kunde_id)
        else:
            dlg.show_error(result.message)

    def _deactivate_customer(self, dto: KundeDTO) -> None:
        if not ConfirmDialog.ask(
            title="Kunde deaktivieren",
            message=f"{dto.display_name} deaktivieren?",
            detail=(
                "Der Kunde wird als inaktiv markiert. "
                "Bestehende Rechnungen bleiben erhalten. "
                "Eine Reaktivierung ist jederzeit möglich."
            ),
            confirm_text="Deaktivieren",
            danger=True,
            parent=self,
        ):
            return

        with db.session() as session:
            result = kunden_service.deaktivieren(session, dto.id)

        if result.success:
            self._banner.show_success(result.message)
            self._load_customers(self._search.text())
            self._detail_panel.clear()
        else:
            self._banner.show_error(result.message)

    def _reactivate_customer(self, dto: KundeDTO) -> None:
        with db.session() as session:
            result = kunden_service.reaktivieren(session, dto.id)

        if result.success:
            self._banner.show_success(result.message)
            self._load_customers(self._search.text())
            self._table.select_row_by_id(dto.id)
        else:
            self._banner.show_error(result.message)

    def _show_documents(self, dto: KundeDTO) -> None:
        if dto is None:
            self._banner.show_error("Kein Kunde ausgewählt.")
            return
        try:
            from ui.modules.kunden.dokumente_dialog import DokumenteDialog
            dlg = DokumenteDialog(dto, parent=self)
            dlg.exec()
        except Exception as e:
            import traceback
            self._banner.show_error(f"Fehler beim Öffnen der Dokumente: {e}")
            import logging
            logging.getLogger(__name__).exception("DokumenteDialog Fehler:")

    def _new_invoice(self, dto: KundeDTO) -> None:
        """Öffnet den Rechnungsdialog für den gewählten Kunden."""
        try:
            from ui.modules.rechnungen.dialog import RechnungDialog
            from core.db.engine import db
            from core.services.rechnungen_service import rechnungen_service

            dlg = RechnungDialog(
                parent=self,
                kunde_id=dto.id,
                kunde_name=dto.display_name,
                title=f"Neue Rechnung – {dto.display_name}",
            )

            def _on_saved(rdto):
                with db.session() as session:
                    result = rechnungen_service.entwurf_erstellen(
                        session, rdto.kunde_id, rdto
                    )
                if result.success:
                    new_id = result.data.id
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
                else:
                    dlg.show_error(result.message)

            dlg.saved.connect(_on_saved)
            dlg.exec()
        except Exception as e:
            self._banner.show_error(f"Fehler beim Öffnen des Rechnungsdialogs: {e}")
