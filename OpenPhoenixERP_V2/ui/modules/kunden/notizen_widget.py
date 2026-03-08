"""
ui/modules/kunden/notizen_widget.py – CRM-Notizen pro Kunde
============================================================
Zeigt den Notizverlauf eines Kunden und ermöglicht das Hinzufügen
neuer Notizen mit automatischem Zeitstempel.
Notizen sind rein intern und erscheinen nicht auf Dokumenten.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTextEdit, QScrollArea, QFrame, QSizePolicy,
)

from core.db.engine import db
from core.config import config
from core.services.kunden_service import kunden_service
from ui.theme.theme import Colors, Fonts, Spacing, Radius


class _NotizEintrag(QFrame):
    """Ein einzelner Notizeintrag in der Listenansicht."""

    def __init__(self, dto, on_delete, parent=None):
        super().__init__(parent)
        self._dto = dto
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.BG_ELEVATED};
                border-radius: {Radius.MD}px;
                border: 1px solid {Colors.BORDER};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.MD, Spacing.SM, Spacing.MD, Spacing.SM)
        layout.setSpacing(4)

        # Header: Autor + Datum + Löschen-Button
        header = QHBoxLayout()
        meta = f"{dto.erstellt_am}"
        if dto.autor:
            meta = f"{dto.autor}  ·  {dto.erstellt_am}"
        meta_lbl = QLabel(meta)
        meta_lbl.setFont(Fonts.get(Fonts.SIZE_SM))
        meta_lbl.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; border: none;")
        header.addWidget(meta_lbl, 1)

        del_btn = QPushButton("✕")
        del_btn.setFixedSize(22, 22)
        del_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {Colors.TEXT_SECONDARY};
                border: none;
                font-size: 11px;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: rgba(239,68,68,0.15);
                color: #EF4444;
            }}
        """)
        del_btn.setToolTip("Notiz löschen")
        del_btn.clicked.connect(lambda: on_delete(dto.id))
        header.addWidget(del_btn)
        layout.addLayout(header)

        # Notiztext
        text_lbl = QLabel(dto.text)
        text_lbl.setWordWrap(True)
        text_lbl.setFont(Fonts.get(Fonts.SIZE_SM))
        text_lbl.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; border: none;")
        text_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(text_lbl)


class NotizenWidget(QWidget):
    """
    CRM-Notiz-Widget für das Kunden-Detail-Panel.
    Zeigt Notizverlauf (neueste oben) + Eingabefeld zum Hinzufügen.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._kunde_id: int | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Spacing.SM)

        # Abschnittstitel
        title = QLabel("📝  Notizen")
        title.setFont(Fonts.get(Fonts.SIZE_SM, bold=True))
        title.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        layout.addWidget(title)

        # Scroll-Bereich für Notizverlauf
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("background: transparent;")
        self._scroll.setMinimumHeight(140)
        self._scroll.setMaximumHeight(220)

        self._list_widget = QWidget()
        self._list_widget.setStyleSheet("background: transparent;")
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(Spacing.XS if hasattr(Spacing, "XS") else 4)
        self._list_layout.addStretch()
        self._scroll.setWidget(self._list_widget)
        layout.addWidget(self._scroll)

        # Eingabefeld
        self._input = QTextEdit()
        self._input.setPlaceholderText("Neue Notiz eingeben…")
        self._input.setFixedHeight(72)
        self._input.setFont(Fonts.get(Fonts.SIZE_SM))
        self._input.setStyleSheet(f"""
            QTextEdit {{
                background-color: {Colors.BG_ELEVATED};
                border: 1px solid {Colors.BORDER};
                border-radius: {Radius.MD}px;
                color: {Colors.TEXT_PRIMARY};
                padding: 6px 8px;
            }}
            QTextEdit:focus {{
                border-color: {Colors.PRIMARY};
            }}
        """)
        layout.addWidget(self._input)

        # Speichern-Button
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._save_btn = QPushButton("Notiz speichern")
        self._save_btn.setProperty("role", "primary")
        self._save_btn.setFixedHeight(32)
        self._save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(self._save_btn)
        layout.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self, kunde_id: int) -> None:
        """Lädt den Notizverlauf für den angegebenen Kunden."""
        self._kunde_id = kunde_id
        self._refresh()
        self._input.clear()
        self.setEnabled(True)

    def clear(self) -> None:
        """Leert das Widget (kein Kunde ausgewählt)."""
        self._kunde_id = None
        self._clear_list()
        self._input.clear()
        self.setEnabled(False)

    # ------------------------------------------------------------------
    # Intern
    # ------------------------------------------------------------------

    def _refresh(self) -> None:
        self._clear_list()
        if not self._kunde_id:
            return
        with db.session() as session:
            notizen = kunden_service.notizen(session, self._kunde_id)
        if not notizen:
            leer = QLabel("Noch keine Notizen vorhanden.")
            leer.setFont(Fonts.get(Fonts.SIZE_SM))
            leer.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
            leer.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._list_layout.insertWidget(0, leer)
        else:
            for dto in notizen:
                entry = _NotizEintrag(dto, self._on_delete)
                self._list_layout.insertWidget(self._list_layout.count() - 1, entry)

    def _clear_list(self) -> None:
        while self._list_layout.count() > 1:  # letztes Item = Stretch
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _on_save(self) -> None:
        text = self._input.toPlainText().strip()
        if not text or not self._kunde_id:
            return
        autor = config.get("company", "name", "")
        with db.session() as session:
            result = kunden_service.notiz_hinzufuegen(
                session, self._kunde_id, text, autor
            )
        if result.success:
            self._input.clear()
            self._refresh()
            # Zum Anfang scrollen (neueste Notiz)
            self._scroll.verticalScrollBar().setValue(0)

    def _on_delete(self, notiz_id: int) -> None:
        with db.session() as session:
            kunden_service.notiz_loeschen(session, notiz_id)
        self._refresh()
