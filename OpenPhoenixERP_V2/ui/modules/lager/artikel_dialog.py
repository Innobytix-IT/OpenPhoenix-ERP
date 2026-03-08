"""
ui/modules/lager/artikel_dialog.py – Artikel anlegen und bearbeiten
====================================================================
Formular für Artikelstammdaten. Bestand wird nur beim Anlegen gesetzt —
spätere Bestandsänderungen laufen über Buchungsdialoge.
"""

from decimal import Decimal, InvalidOperation

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFrame,
    QLabel, QPushButton, QWidget, QScrollArea,
)

from core.services.lager_service import ArtikelDTO
from ui.components.widgets import FormField, SectionTitle, NotificationBanner
from ui.theme.theme import Colors, Fonts, Spacing, Radius


class ArtikelDialog(QDialog):
    """
    Dialog zum Anlegen und Bearbeiten eines Artikels.

    Signals:
        saved(ArtikelDTO): Enthält die ausgefüllten Stammdaten.
    """

    saved = Signal(object)  # ArtikelDTO

    def __init__(self, parent=None, dto: ArtikelDTO = None):
        super().__init__(parent)
        self._edit_mode = dto is not None
        self._original = dto
        self.setWindowTitle("Artikel bearbeiten" if dto else "Neuer Artikel")
        self.setModal(True)
        self.setMinimumSize(520, 480)
        self.resize(560, 500)
        self._build_ui()
        if dto:
            self._populate(dto)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())

        self._banner = NotificationBanner()
        wrapper = QWidget()
        wl = QVBoxLayout(wrapper)
        wl.setContentsMargins(Spacing.XL, Spacing.SM, Spacing.XL, 0)
        wl.addWidget(self._banner)
        root.addWidget(wrapper)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self._build_form())
        root.addWidget(scroll, 1)

        root.addWidget(self._build_footer())

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setFixedHeight(56)
        header.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.BG_SURFACE};
                border-bottom: 1px solid {Colors.BORDER};
            }}
        """)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(Spacing.XL, 0, Spacing.XL, 0)

        icon = QLabel("📦")
        icon.setStyleSheet("font-size: 20px; background: transparent;")
        layout.addWidget(icon)
        layout.addSpacing(Spacing.SM)

        title = QLabel(self.windowTitle())
        title.setFont(Fonts.heading3())
        title.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; background: transparent;")
        layout.addWidget(title)
        layout.addStretch()

        if self._edit_mode and self._original:
            nr_label = QLabel(self._original.artikelnummer)
            nr_label.setStyleSheet(f"""
                background-color: {Colors.BG_ELEVATED};
                color: {Colors.TEXT_SECONDARY};
                border-radius: {Radius.SM}px;
                padding: 4px 10px;
                font-size: {Fonts.SIZE_SM}pt;
            """)
            layout.addWidget(nr_label)

        return header

    def _build_form(self) -> QWidget:
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(Spacing.XL, Spacing.LG, Spacing.XL, Spacing.LG)
        layout.setSpacing(Spacing.SM)

        # Artikelidentifikation
        layout.addWidget(SectionTitle("Identifikation"))
        row1 = QHBoxLayout()
        row1.setSpacing(Spacing.MD)
        self.f_nummer = FormField(
            "Artikelnummer *", required=True,
            placeholder="z.B. ART-001, 10042",
            max_length=50,
        )
        if self._edit_mode and self._original and self._original.rechnungsposten if hasattr(self._original, 'rechnungsposten') else False:
            self.f_nummer.set_read_only(True)
        row1.addWidget(self.f_nummer, 1)
        layout.addLayout(row1)

        self.f_beschreibung = FormField(
            "Beschreibung *", required=True,
            placeholder="Produktbezeichnung",
            max_length=500,
        )
        layout.addWidget(self.f_beschreibung)

        # Preis & Einheit
        layout.addWidget(SectionTitle("Preis & Einheit"))
        row2 = QHBoxLayout()
        row2.setSpacing(Spacing.MD)
        self.f_preis = FormField(
            "Einzelpreis Netto (€) *",
            required=True,
            placeholder="0,00",
            max_length=15,
        )
        self.f_einheit = FormField(
            "Einheit",
            placeholder="Stück, kg, m, Std., …",
            max_length=20,
        )
        self.f_einheit.setFixedWidth(150)
        row2.addWidget(self.f_preis, 2)
        row2.addWidget(self.f_einheit, 1)
        layout.addLayout(row2)

        # Anfangsbestand (nur beim Anlegen)
        if not self._edit_mode:
            layout.addWidget(SectionTitle("Anfangsbestand"))
            bestand_info = QLabel(
                "Der Anfangsbestand wird als Eingangs-Buchung protokolliert. "
                "Spätere Änderungen über Ein-/Ausbuchen."
            )
            bestand_info.setFont(Fonts.caption())
            bestand_info.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
            bestand_info.setWordWrap(True)
            layout.addWidget(bestand_info)

            self.f_bestand = FormField(
                "Anfangsbestand",
                placeholder="0",
                max_length=15,
            )
            self.f_bestand.set_value("0")
            layout.addWidget(self.f_bestand)
        else:
            self.f_bestand = None

        layout.addStretch()
        return container

    def _build_footer(self) -> QFrame:
        footer = QFrame()
        footer.setFixedHeight(60)
        footer.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.BG_SURFACE};
                border-top: 1px solid {Colors.BORDER};
            }}
        """)
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(Spacing.XL, 0, Spacing.XL, 0)
        layout.setSpacing(Spacing.SM)
        layout.addStretch()

        cancel_btn = QPushButton("Abbrechen")
        cancel_btn.setProperty("role", "secondary")
        cancel_btn.setMinimumWidth(110)
        cancel_btn.clicked.connect(self.reject)
        layout.addWidget(cancel_btn)

        self._save_btn = QPushButton(
            "💾  Speichern" if self._edit_mode else "➕  Artikel anlegen"
        )
        self._save_btn.setMinimumWidth(150)
        self._save_btn.clicked.connect(self._on_save)
        self._save_btn.setDefault(True)
        layout.addWidget(self._save_btn)

        return footer

    def _populate(self, dto: ArtikelDTO) -> None:
        self.f_nummer.set_value(dto.artikelnummer)
        self.f_beschreibung.set_value(dto.beschreibung)
        self.f_preis.set_value(
            f"{dto.einzelpreis_netto:.2f}".replace(".", ",")
        )
        self.f_einheit.set_value(dto.einheit)

    def _collect(self) -> ArtikelDTO:
        preis_str = self.f_preis.value().replace(",", ".")
        try:
            preis = Decimal(preis_str)
        except InvalidOperation:
            preis = Decimal("0")

        if self.f_bestand:
            bestand_str = self.f_bestand.value().replace(",", ".")
            try:
                bestand = Decimal(bestand_str)
            except InvalidOperation:
                bestand = Decimal("0")
        else:
            bestand = self._original.verfuegbar if self._original else Decimal("0")

        return ArtikelDTO(
            id=self._original.id if self._original else None,
            artikelnummer=self.f_nummer.value(),
            beschreibung=self.f_beschreibung.value(),
            einheit=self.f_einheit.value(),
            einzelpreis_netto=preis,
            verfuegbar=bestand,
        )

    def _validate(self) -> bool:
        dto = self._collect()
        valid = True

        if not dto.artikelnummer:
            self.f_nummer.set_error("Artikelnummer ist ein Pflichtfeld.")
            valid = False
        if not dto.beschreibung:
            self.f_beschreibung.set_error("Beschreibung ist ein Pflichtfeld.")
            valid = False
        if dto.einzelpreis_netto < Decimal("0"):
            self.f_preis.set_error("Preis darf nicht negativ sein.")
            valid = False

        return valid

    def _on_save(self) -> None:
        if self._validate():
            self.saved.emit(self._collect())

    def show_error(self, message: str) -> None:
        self._banner.show_error(message)
