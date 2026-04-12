"""
ui/components/widgets.py – Wiederverwendbare UI-Komponenten
===========================================================
Diese Komponenten werden von allen Modulen genutzt.
Einmal gebaut, überall konsistent.
"""

from typing import Optional, Callable

from PySide6.QtCore import (
    Qt, Signal, QTimer, QSortFilterProxyModel, QAbstractTableModel,
    QModelIndex, QPersistentModelIndex
)
from PySide6.QtGui import QFont, QColor, QIcon
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame, QTableView, QHeaderView, QAbstractItemView,
    QDialog, QDialogButtonBox, QSizePolicy, QMessageBox,
    QStyledItemDelegate, QStyleOptionViewItem,
)

from ui.theme.theme import Colors, Fonts, Spacing, Radius


# ---------------------------------------------------------------------------
# Suchleiste
# ---------------------------------------------------------------------------

class SearchBar(QFrame):
    """
    Suchleiste mit Debounce-Timer (sucht erst 300ms nach letzter Eingabe).

    Signals:
        search_changed(str): Wird mit dem Suchtext ausgelöst
        cleared():           Wird ausgelöst wenn Suche geleert wird
    """

    search_changed = Signal(str)
    cleared = Signal()

    def __init__(self, placeholder: str = "Suchen…", parent=None):
        super().__init__(parent)
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._emit_search)
        self._build_ui(placeholder)

    def _build_ui(self, placeholder: str) -> None:
        self.setObjectName("searchBar")
        self.setStyleSheet("#searchBar { background: transparent; border: none; }")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Spacing.SM)

        # Suchfeld
        self._input = QLineEdit()
        self._input.setPlaceholderText(placeholder)
        self._input.setMinimumHeight(36)
        self._input.setClearButtonEnabled(True)
        self._input.textChanged.connect(self._on_text_changed)
        layout.addWidget(self._input)

    def _on_text_changed(self, text: str) -> None:
        if not text:
            self._timer.stop()
            self.cleared.emit()
        else:
            self._timer.start(300)

    def _emit_search(self) -> None:
        self.search_changed.emit(self._input.text().strip())

    def text(self) -> str:
        return self._input.text().strip()

    def clear(self) -> None:
        self._input.clear()

    def set_focus(self) -> None:
        self._input.setFocus()


# ---------------------------------------------------------------------------
# Modernes Tabellenmodell
# ---------------------------------------------------------------------------

class TableModel(QAbstractTableModel):
    """
    Generisches Tabellenmodell für QTableView.

    Verwendung:
        model = TableModel(
            columns=["ID", "Name", "Vorname", "E-Mail"],
            data=[[1, "Müller", "Hans", "hans@test.de"], ...]
        )
        table_view.setModel(model)
    """

    def __init__(
        self,
        columns: list[str],
        data: list[list] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._columns = columns
        self._data: list[list] = data or []
        self._row_colors: dict[int, QColor] = {}

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._data)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self._columns)

    # Custom Role für Zeilenfarben – wird NICHT als ForegroundRole
    # zurückgegeben, damit Qt die Farbe nicht bei Selektion erzwingt.
    RowColorRole = Qt.ItemDataRole.UserRole + 100

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None

        row, col = index.row(), index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            try:
                val = self._data[row][col]
                return "" if val is None else str(val)
            except IndexError:
                return ""

        if role == self.RowColorRole:
            return self._row_colors.get(row)

        if role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft

        return None

    def headerData(
        self, section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                try:
                    return self._columns[section]
                except IndexError:
                    return ""
        return None

    def set_data(self, data: list[list]) -> None:
        """Ersetzt alle Daten und löst ein vollständiges Refresh aus."""
        self.beginResetModel()
        self._data = data
        self._row_colors = {}
        self.endResetModel()

    def set_row_color(self, row: int, color: QColor) -> None:
        """Setzt eine Farbe für eine bestimmte Zeile."""
        self._row_colors[row] = color

    def row_data(self, row: int) -> list:
        """Gibt die Rohdaten einer Zeile zurück."""
        if 0 <= row < len(self._data):
            return self._data[row]
        return []

    def id_for_row(self, row: int, id_column: int = 0) -> Optional[int]:
        """Gibt die ID (erste Spalte) einer Zeile zurück."""
        try:
            return int(self._data[row][id_column])
        except (IndexError, ValueError, TypeError):
            return None


class _SelectionAwareDelegate(QStyledItemDelegate):
    """Wendet Zeilenfarben aus TableModel.RowColorRole an, erzwingt aber
    weiße Schrift wenn die Zeile selektiert ist."""

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        if option.state & QStyleOptionViewItem.State_Selected:
            # Selektiert → weiße Schrift, egal welche Zeilenfarbe
            option.palette.setColor(option.palette.ColorRole.Text, QColor("#FFFFFF"))
            option.palette.setColor(option.palette.ColorRole.HighlightedText, QColor("#FFFFFF"))
        else:
            # Nicht selektiert → ggf. Zeilenfarbe anwenden
            color = index.data(TableModel.RowColorRole)
            if color:
                option.palette.setColor(option.palette.ColorRole.Text, color)


class DataTable(QTableView):
    """
    Vorkonfigurierter QTableView mit OpenPhoenix-Styling.

    Signals:
        row_selected(int):       Zeilenindex wenn Zeile ausgewählt
        row_double_clicked(int): Zeilenindex bei Doppelklick
    """

    row_selected = Signal(int)
    row_double_clicked = Signal(int)

    def __init__(
        self,
        columns: list[str],
        column_widths: list[int] = None,
        stretch_column: int = -1,
        table_id: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self._table_model = TableModel(columns)
        self._table_id = table_id

        # Proxy-Modell für clientseitiges Sortieren
        self._proxy = QSortFilterProxyModel()
        self._proxy.setSourceModel(self._table_model)
        self._proxy.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setModel(self._proxy)

        self.setItemDelegate(_SelectionAwareDelegate(self))
        self._configure(column_widths, stretch_column)
        self._connect_signals()

    def _configure(
        self, column_widths: Optional[list[int]], stretch_column: int
    ) -> None:
        # Verhalten
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.setSortingEnabled(True)
        self.setShowGrid(False)
        self.verticalHeader().setVisible(False)
        self.setWordWrap(False)

        # Zeilenhöhe
        self.verticalHeader().setDefaultSectionSize(40)
        self.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Fixed
        )

        # Spaltenbreiten
        header = self.horizontalHeader()
        header.setHighlightSections(False)
        header.setSectionsMovable(True)

        # Standard-Breiten setzen
        if column_widths:
            for i, w in enumerate(column_widths):
                if w > 0:
                    self.setColumnWidth(i, w)

        # Gespeicherte Benutzerbreiten überschreiben Standard-Breiten
        if self._table_id:
            from ui.components.column_store import laden
            gespeichert = laden(self._table_id)
            for col, breite in gespeichert.items():
                if col < len(column_widths or []) or col < self._table_model.columnCount():
                    self.setColumnWidth(col, breite)

        if stretch_column >= 0:
            header.setSectionResizeMode(
                stretch_column, QHeaderView.ResizeMode.Stretch
            )

    def _connect_signals(self) -> None:
        self.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self.doubleClicked.connect(self._on_double_clicked)
        # Spaltenbreiten-Änderungen persistieren
        if self._table_id:
            self.horizontalHeader().sectionResized.connect(self._on_section_resized)

    def _on_section_resized(self, col: int, _old: int, new: int) -> None:
        """Speichert neue Spaltenbreite nach Benutzeranpassung."""
        from ui.components.column_store import laden, speichern
        breiten = laden(self._table_id)
        breiten[col] = new
        speichern(self._table_id, breiten)

    def _on_selection_changed(self) -> None:
        row = self.current_source_row()
        if row >= 0:
            self.row_selected.emit(row)

    def _on_double_clicked(self, index: QModelIndex) -> None:
        source_row = self._proxy.mapToSource(index).row()
        if source_row >= 0:
            self.row_double_clicked.emit(source_row)

    def set_data(self, data: list[list]) -> None:
        self._table_model.set_data(data)

    def set_row_color(self, row: int, color: QColor) -> None:
        self._table_model.set_row_color(row, color)

    def current_source_row(self) -> int:
        """Gibt den aktuellen Zeilenindex im Quell-Modell zurück."""
        indexes = self.selectionModel().selectedRows()
        if not indexes:
            return -1
        return self._proxy.mapToSource(indexes[0]).row()

    def current_row_id(self, id_column: int = 0) -> Optional[int]:
        """Gibt die ID der aktuell ausgewählten Zeile zurück."""
        row = self.current_source_row()
        return self._table_model.id_for_row(row, id_column)

    def current_row_data(self) -> list:
        """Gibt die Rohdaten der aktuell ausgewählten Zeile zurück."""
        row = self.current_source_row()
        return self._table_model.row_data(row)

    def select_row_by_id(self, target_id: int, id_column: int = 0) -> bool:
        """Selektiert eine Zeile anhand der ID."""
        for row in range(self._table_model.rowCount()):
            if self._table_model.id_for_row(row, id_column) == target_id:
                proxy_index = self._proxy.mapFromSource(
                    self._table_model.index(row, 0)
                )
                self.selectRow(proxy_index.row())
                self.scrollTo(proxy_index)
                return True
        return False


# ---------------------------------------------------------------------------
# Formularfeld mit Label und Validierung
# ---------------------------------------------------------------------------

class FormField(QWidget):
    """
    Label + Eingabefeld mit optionaler Validierungsanzeige.

    Verwendung:
        field = FormField("Name*", required=True)
        field.set_value("Müller")
        value = field.value()
        field.set_error("Name darf nicht leer sein.")
    """

    value_changed = Signal(str)

    def __init__(
        self,
        label: str,
        required: bool = False,
        placeholder: str = "",
        max_length: int = 0,
        parent=None,
    ):
        super().__init__(parent)
        self._required = required
        self._build_ui(label, placeholder, max_length)

    def _build_ui(self, label: str, placeholder: str, max_length: int) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Label
        self._label = QLabel(label)
        self._label.setFont(Fonts.get(Fonts.SIZE_SM))
        self._label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        layout.addWidget(self._label)

        # Eingabefeld
        self._input = QLineEdit()
        self._input.setPlaceholderText(placeholder)
        self._input.setMinimumHeight(36)
        if max_length:
            self._input.setMaxLength(max_length)
        self._input.textChanged.connect(self._on_changed)
        layout.addWidget(self._input)

        # Fehlermeldung (zunächst versteckt)
        self._error_label = QLabel("")
        self._error_label.setFont(Fonts.get(Fonts.SIZE_XS))
        self._error_label.setStyleSheet(f"color: {Colors.ERROR};")
        self._error_label.setVisible(False)
        layout.addWidget(self._error_label)

    def _on_changed(self, text: str) -> None:
        self.clear_error()
        self.value_changed.emit(text)

    def value(self) -> str:
        return self._input.text().strip()

    def set_value(self, value: str) -> None:
        self._input.setText(value or "")

    def clear(self) -> None:
        self._input.clear()
        self.clear_error()

    def set_error(self, message: str) -> None:
        self._error_label.setText(message)
        self._error_label.setVisible(True)
        self._input.setProperty("valid", "false")
        self._input.style().unpolish(self._input)
        self._input.style().polish(self._input)

    def clear_error(self) -> None:
        self._error_label.setVisible(False)
        self._input.setProperty("valid", "")
        self._input.style().unpolish(self._input)
        self._input.style().polish(self._input)

    def set_read_only(self, read_only: bool) -> None:
        self._input.setReadOnly(read_only)

    def set_focus(self) -> None:
        self._input.setFocus()


# ---------------------------------------------------------------------------
# Status-Badge
# ---------------------------------------------------------------------------

class StatusBadge(QLabel):
    """Farbiges Kennzeichen für Status-Werte."""

    STATUS_COLORS = {
        "Aktiv":        (Colors.SUCCESS_BG, Colors.SUCCESS),
        "Inaktiv":      (Colors.BG_ELEVATED, Colors.TEXT_DISABLED),
        "Entwurf":      (Colors.BG_ELEVATED, Colors.TEXT_SECONDARY),
        "Offen":        (Colors.INFO_BG, Colors.INFO),
        "Bezahlt":      (Colors.SUCCESS_BG, Colors.SUCCESS),
        "Storniert":    (Colors.BG_ELEVATED, Colors.TEXT_DISABLED),
        "Gutschrift":   (Colors.INFO_BG, Colors.STATUS_GUTSCHRIFT),
        "Steht zur Erinnerung an":   (Colors.WARNING_BG, Colors.WARNING),
        "Steht zur Mahnung an":      (Colors.WARNING_BG, Colors.STATUS_MAHNUNG),
        "Steht zur Mahnung 2 an":    (Colors.ERROR_BG, Colors.ERROR),
        "Bitte an Inkasso weiterleiten": (Colors.ERROR_BG, Colors.STATUS_INKASSO),
    }

    def __init__(self, status: str = "", parent=None):
        super().__init__(parent)
        self.set_status(status)

    def set_status(self, status: str) -> None:
        bg, fg = self.STATUS_COLORS.get(status, (Colors.BG_ELEVATED, Colors.TEXT_SECONDARY))
        self.setText(status)
        self.setStyleSheet(f"""
            QLabel {{
                background-color: {bg};
                color: {fg};
                border-radius: {Radius.SM}px;
                padding: 3px 10px;
                font-size: {Fonts.SIZE_SM}pt;
                font-weight: bold;
            }}
        """)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)


# ---------------------------------------------------------------------------
# Bestätigungs-Dialog
# ---------------------------------------------------------------------------

class ConfirmDialog(QDialog):
    """
    Modaler Bestätigungs-Dialog.

    Verwendung:
        if ConfirmDialog.ask(
            parent=self,
            title="Kunde deaktivieren",
            message="Soll der Kunde wirklich deaktiviert werden?",
            detail="Der Kunde kann später reaktiviert werden.",
            confirm_text="Deaktivieren",
            danger=True,
        ):
            # Bestätigt
    """

    def __init__(
        self,
        title: str,
        message: str,
        detail: str = "",
        confirm_text: str = "Bestätigen",
        cancel_text: str = "Abbrechen",
        danger: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(400)
        self._build_ui(message, detail, confirm_text, cancel_text, danger)

    def _build_ui(
        self, message, detail, confirm_text, cancel_text, danger
    ) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.XL, Spacing.XL, Spacing.XL, Spacing.LG)
        layout.setSpacing(Spacing.MD)

        # Nachricht
        msg_label = QLabel(message)
        msg_label.setFont(Fonts.get(Fonts.SIZE_MD, bold=True))
        msg_label.setWordWrap(True)
        layout.addWidget(msg_label)

        # Detail
        if detail:
            detail_label = QLabel(detail)
            detail_label.setFont(Fonts.get(Fonts.SIZE_BASE))
            detail_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
            detail_label.setWordWrap(True)
            layout.addWidget(detail_label)

        layout.addSpacing(Spacing.SM)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton(cancel_text)
        cancel_btn.setProperty("role", "secondary")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        confirm_btn = QPushButton(confirm_text)
        if danger:
            confirm_btn.setProperty("role", "danger")
        confirm_btn.clicked.connect(self.accept)
        confirm_btn.setDefault(True)
        btn_layout.addWidget(confirm_btn)

        layout.addLayout(btn_layout)

    @staticmethod
    def ask(
        title: str,
        message: str,
        detail: str = "",
        confirm_text: str = "Bestätigen",
        cancel_text: str = "Abbrechen",
        danger: bool = False,
        parent=None,
    ) -> bool:
        """Zeigt den Dialog und gibt True zurück wenn bestätigt."""
        dlg = ConfirmDialog(
            title=title, message=message, detail=detail,
            confirm_text=confirm_text, cancel_text=cancel_text,
            danger=danger, parent=parent,
        )
        return dlg.exec() == QDialog.DialogCode.Accepted


# ---------------------------------------------------------------------------
# Benachrichtigungs-Banner
# ---------------------------------------------------------------------------

class NotificationBanner(QFrame):
    """
    Temporäres Benachrichtigungs-Banner (erscheint, verschwindet automatisch).

    Verwendung:
        banner = NotificationBanner(parent=self)
        banner.show_success("Kunde erfolgreich gespeichert.")
        banner.show_error("Name ist ein Pflichtfeld.")
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self._build_ui()
        self.hide()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(Spacing.LG, Spacing.MD, Spacing.LG, Spacing.MD)

        self._icon = QLabel()
        self._icon.setFixedWidth(20)
        layout.addWidget(self._icon)

        self._text = QLabel()
        self._text.setFont(Fonts.get(Fonts.SIZE_BASE))
        self._text.setWordWrap(True)
        layout.addWidget(self._text, 1)

        close_btn = QPushButton("✕")
        close_btn.setProperty("role", "ghost")
        close_btn.setFixedSize(24, 24)
        close_btn.clicked.connect(self.hide)
        layout.addWidget(close_btn)

    def _show(self, text: str, bg: str, fg: str, icon: str, timeout_ms: int) -> None:
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {bg};
                border-radius: {Radius.MD}px;
                border-left: 4px solid {fg};
            }}
        """)
        self._icon.setText(icon)
        self._text.setText(text)
        self._text.setStyleSheet(f"color: {fg};")
        self.show()
        if timeout_ms > 0:
            self._timer.start(timeout_ms)

    def show_success(self, text: str, timeout_ms: int = 4000) -> None:
        self._show(text, Colors.SUCCESS_BG, Colors.SUCCESS, "✓", timeout_ms)

    def show_error(self, text: str, timeout_ms: int = 0) -> None:
        self._show(text, Colors.ERROR_BG, Colors.ERROR, "✕", timeout_ms)

    def show_warning(self, text: str, timeout_ms: int = 6000) -> None:
        self._show(text, Colors.WARNING_BG, Colors.WARNING, "⚠", timeout_ms)

    def show_info(self, text: str, timeout_ms: int = 4000) -> None:
        self._show(text, Colors.INFO_BG, Colors.INFO, "ℹ", timeout_ms)


# ---------------------------------------------------------------------------
# Sektionstitel (für Formulare)
# ---------------------------------------------------------------------------

class SectionTitle(QWidget):
    """Visueller Trenner mit Titel für Formular-Abschnitte."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, Spacing.MD, 0, Spacing.XS)
        layout.setSpacing(Spacing.SM)

        label = QLabel(title)
        label.setFont(Fonts.get(Fonts.SIZE_SM, bold=True))
        label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        layout.addWidget(label)

        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background-color: {Colors.BORDER};")
        layout.addWidget(line, 1)


# ---------------------------------------------------------------------------
# Leerer Zustand (Empty State)
# ---------------------------------------------------------------------------

class EmptyState(QWidget):
    """Wird angezeigt wenn eine Liste leer ist."""

    def __init__(
        self,
        icon: str = "📭",
        title: str = "Keine Einträge",
        subtitle: str = "",
        parent=None,
    ):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(Spacing.MD)

        icon_label = QLabel(icon)
        icon_label.setFont(QFont("Segoe UI Emoji", 40))
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet("background: transparent;")
        layout.addWidget(icon_label)

        title_label = QLabel(title)
        title_label.setFont(Fonts.get(Fonts.SIZE_LG, bold=True))
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet(
            f"color: {Colors.TEXT_PRIMARY}; background: transparent;"
        )
        layout.addWidget(title_label)

        if subtitle:
            sub_label = QLabel(subtitle)
            sub_label.setFont(Fonts.get(Fonts.SIZE_BASE))
            sub_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sub_label.setStyleSheet(
                f"color: {Colors.TEXT_SECONDARY}; background: transparent;"
            )
            sub_label.setWordWrap(True)
            layout.addWidget(sub_label)
