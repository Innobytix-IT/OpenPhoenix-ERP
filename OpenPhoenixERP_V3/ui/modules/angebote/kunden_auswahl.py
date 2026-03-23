"""
ui/modules/angebote/kunden_auswahl.py – Kundenauswahl für neue Angebote
========================================================================
Schneller Dialog zum Auswählen eines aktiven Kunden bevor ein Angebot
angelegt wird.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QFrame, QWidget,
)

from core.db.engine import db
from core.services.kunden_service import kunden_service
from ui.components.widgets import SearchBar, DataTable, NotificationBanner
from ui.theme.theme import Colors, Fonts, Spacing, Radius


class KundenAuswahlDialog(QDialog):
    """
    Modaler Dialog zur Kundenauswahl für Angebote.

    Signals:
        selected(int, str): Kunden-ID und Anzeigename des gewählten Kunden
    """

    selected = Signal(int, str)  # (kunde_id, display_name)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("Kunde für Angebot auswählen")
        self.setModal(True)
        self.setMinimumSize(620, 480)
        self._dtos = []
        self._build_ui()
        self._load()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        header = QFrame()
        header.setFixedHeight(56)
        header.setStyleSheet(f"""
            background-color: {Colors.BG_SURFACE};
            border-bottom: 1px solid {Colors.BORDER};
        """)
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(Spacing.XL, 0, Spacing.XL, 0)
        icon = QLabel("👥")
        icon.setStyleSheet("font-size: 18px; background: transparent;")
        title = QLabel("Kunden auswählen")
        title.setFont(Fonts.heading3())
        title.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; background: transparent;")
        h_layout.addWidget(icon)
        h_layout.addSpacing(Spacing.SM)
        h_layout.addWidget(title)
        h_layout.addStretch()
        root.addWidget(header)

        # Content
        content = QWidget()
        c_layout = QVBoxLayout(content)
        c_layout.setContentsMargins(Spacing.XL, Spacing.MD, Spacing.XL, Spacing.MD)
        c_layout.setSpacing(Spacing.SM)

        self._banner = NotificationBanner()
        c_layout.addWidget(self._banner)

        self._search = SearchBar("Kunden suchen…")
        self._search.search_changed.connect(self._load)
        self._search.cleared.connect(self._load)
        c_layout.addWidget(self._search)

        self._table = DataTable(
            columns=["ID", "Kundennr.", "Name", "Vorname", "Ort", "E-Mail"],
            column_widths=[0, 90, 150, 130, 120, 180],
            stretch_column=5,
        )
        self._table.setColumnHidden(0, True)
        self._table.row_double_clicked.connect(self._on_double_click)
        c_layout.addWidget(self._table)

        root.addWidget(content, 1)

        # Footer
        footer = QFrame()
        footer.setFixedHeight(64)
        footer.setStyleSheet(f"""
            background-color: {Colors.BG_SURFACE};
            border-top: 1px solid {Colors.BORDER};
        """)
        f_layout = QHBoxLayout(footer)
        f_layout.setContentsMargins(Spacing.XL, 0, Spacing.XL, 0)
        f_layout.addStretch()

        cancel_btn = QPushButton("Abbrechen")
        cancel_btn.setProperty("role", "secondary")
        cancel_btn.clicked.connect(self.reject)
        f_layout.addWidget(cancel_btn)

        self._select_btn = QPushButton("✅  Kunden wählen")
        self._select_btn.setMinimumWidth(160)
        self._select_btn.setEnabled(False)
        self._select_btn.clicked.connect(self._on_select)
        f_layout.addWidget(self._select_btn)

        root.addWidget(footer)

        self._table.row_selected.connect(lambda _: self._select_btn.setEnabled(True))

    def _load(self, suchtext: str = "") -> None:
        try:
            with db.session() as session:
                self._dtos = kunden_service.alle(session, nur_aktive=True, suchtext=suchtext)
        except Exception as e:
            self._banner.show_error(f"Fehler: {e}")
            return

        rows = [[
            dto.id, dto.zifferncode, dto.name,
            dto.vorname, dto.ort, dto.email,
        ] for dto in self._dtos]
        self._table.set_data(rows)

    def _on_select(self) -> None:
        row = self._table.current_source_row()
        if 0 <= row < len(self._dtos):
            dto = self._dtos[row]
            self.selected.emit(dto.id, dto.display_name)
            self.accept()

    def _on_double_click(self, row: int) -> None:
        if 0 <= row < len(self._dtos):
            dto = self._dtos[row]
            self.selected.emit(dto.id, dto.display_name)
            self.accept()
