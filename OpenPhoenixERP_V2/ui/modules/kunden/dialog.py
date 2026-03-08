"""
ui/modules/kunden/dialog.py – Kunden anlegen und bearbeiten
============================================================
Modaler Dialog mit vollständigem Formular für Kundendaten.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QFrame, QScrollArea, QWidget, QComboBox,
)

from core.services.kunden_service import KundeDTO
from ui.components.widgets import (
    FormField, SectionTitle, NotificationBanner
)
from ui.theme.theme import Colors, Fonts, Spacing, Radius


class KundenDialog(QDialog):
    """
    Dialog zum Anlegen und Bearbeiten eines Kunden.

    Signals:
        saved(KundeDTO): Wird ausgelöst wenn der Nutzer speichert.
                         Enthält die ausgefüllten Daten als DTO.
    """

    saved = Signal(object)  # KundeDTO

    def __init__(
        self,
        parent=None,
        dto: KundeDTO = None,
        title: str = "Neuer Kunde",
    ):
        super().__init__(parent)
        self._edit_mode = dto is not None
        self._original_dto = dto
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumSize(600, 580)
        self.resize(640, 620)
        self._build_ui()
        if dto:
            self._populate(dto)

    # ------------------------------------------------------------------
    # UI aufbauen
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Titelleiste
        root.addWidget(self._build_header())

        # Benachrichtigungs-Banner
        self._banner = NotificationBanner(self)
        banner_wrapper = QWidget()
        banner_layout = QVBoxLayout(banner_wrapper)
        banner_layout.setContentsMargins(Spacing.XL, Spacing.SM, Spacing.XL, 0)
        banner_layout.addWidget(self._banner)
        root.addWidget(banner_wrapper)

        # Scrollbares Formular
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")
        content = self._build_form()
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        # Footer mit Buttons
        root.addWidget(self._build_footer())

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

        icon = QLabel("👤")
        icon.setStyleSheet("font-size: 22px; background: transparent;")
        layout.addWidget(icon)
        layout.addSpacing(Spacing.SM)

        title = QLabel(self.windowTitle())
        title.setFont(Fonts.heading3())
        title.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; background: transparent;")
        layout.addWidget(title)
        layout.addStretch()

        if self._edit_mode and self._original_dto:
            nr_label = QLabel(f"Kundennr. {self._original_dto.zifferncode}")
            nr_label.setFont(Fonts.get(Fonts.SIZE_SM))
            nr_label.setStyleSheet(f"""
                background-color: {Colors.BG_ELEVATED};
                color: {Colors.TEXT_SECONDARY};
                border-radius: {Radius.SM}px;
                padding: 4px 10px;
            """)
            layout.addWidget(nr_label)

        return header

    def _build_form(self) -> QWidget:
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(Spacing.XL, Spacing.LG, Spacing.XL, Spacing.LG)
        layout.setSpacing(Spacing.SM)

        # ── Anrede ────────────────────────────────────────────────
        layout.addWidget(SectionTitle("Anrede"))
        anrede_row = QHBoxLayout()
        anrede_row.setSpacing(Spacing.MD)
        anrede_lbl = QLabel("Anrede")
        anrede_lbl.setFont(Fonts.caption())
        anrede_lbl.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        self.f_anrede = QComboBox()
        self.f_anrede.addItems(["(keine Angabe)", "Herr", "Frau", "Divers"])
        self.f_anrede.setMinimumHeight(36)
        self.f_anrede.setFixedWidth(200)
        self.f_anrede.setStyleSheet(f"""
            QComboBox {{
                background: {Colors.BG_ELEVATED};
                color: {Colors.TEXT_PRIMARY};
                border: 1px solid {Colors.BORDER};
                border-radius: {Radius.SM}px;
                padding: 4px 10px;
            }}
            QComboBox::drop-down {{ border: none; }}
        """)
        anrede_row.addWidget(anrede_lbl)
        anrede_row.addWidget(self.f_anrede)
        anrede_row.addStretch()
        layout.addLayout(anrede_row)

        # ── Pflichtfelder ──────────────────────────────────────────
        layout.addWidget(SectionTitle("Pflichtfelder"))
        row1 = QHBoxLayout()
        row1.setSpacing(Spacing.MD)
        self.f_vorname = FormField("Vorname *", required=True, placeholder="Vorname")
        self.f_name = FormField("Nachname *", required=True, placeholder="Nachname")
        row1.addWidget(self.f_vorname)
        row1.addWidget(self.f_name)
        layout.addLayout(row1)

        # ── Persönliche Daten ──────────────────────────────────────
        layout.addWidget(SectionTitle("Persönliche Daten"))
        row2 = QHBoxLayout()
        row2.setSpacing(Spacing.MD)
        self.f_titel_firma = FormField(
            "Titel / Firma",
            placeholder="z.B. Dr., GmbH, AG",
            max_length=200,
        )
        self.f_geburtsdatum = FormField(
            "Geburtsdatum",
            placeholder="TT.MM.JJJJ",
            max_length=10,
        )
        self.f_geburtsdatum.setFixedWidth(180)
        row2.addWidget(self.f_titel_firma, 2)
        row2.addWidget(self.f_geburtsdatum, 1)
        layout.addLayout(row2)

        # ── Adresse ────────────────────────────────────────────────
        layout.addWidget(SectionTitle("Adresse"))
        row3 = QHBoxLayout()
        row3.setSpacing(Spacing.MD)
        self.f_strasse = FormField("Straße", placeholder="Straße", max_length=200)
        self.f_hausnummer = FormField("Nr.", placeholder="Nr.", max_length=20)
        self.f_hausnummer.setFixedWidth(80)
        row3.addWidget(self.f_strasse, 3)
        row3.addWidget(self.f_hausnummer, 1)
        layout.addLayout(row3)

        row4 = QHBoxLayout()
        row4.setSpacing(Spacing.MD)
        self.f_plz = FormField("PLZ", placeholder="PLZ", max_length=10)
        self.f_plz.setFixedWidth(120)
        self.f_ort = FormField("Ort", placeholder="Ort", max_length=100)
        row4.addWidget(self.f_plz)
        row4.addWidget(self.f_ort, 1)
        layout.addLayout(row4)

        # ── Kontakt ────────────────────────────────────────────────
        layout.addWidget(SectionTitle("Kontakt"))
        row5 = QHBoxLayout()
        row5.setSpacing(Spacing.MD)
        self.f_telefon = FormField("Telefon", placeholder="+49 ...", max_length=50)
        self.f_email = FormField("E-Mail", placeholder="name@beispiel.de", max_length=200)
        row5.addWidget(self.f_telefon)
        row5.addWidget(self.f_email)
        layout.addLayout(row5)

        layout.addStretch()
        return container

    def _build_footer(self) -> QFrame:
        footer = QFrame()
        footer.setFixedHeight(64)
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
        cancel_btn.setMinimumWidth(120)
        cancel_btn.clicked.connect(self.reject)
        layout.addWidget(cancel_btn)

        self._save_btn = QPushButton(
            "💾  Speichern" if self._edit_mode else "➕  Kunde anlegen"
        )
        self._save_btn.setMinimumWidth(160)
        self._save_btn.clicked.connect(self._on_save)
        self._save_btn.setDefault(True)
        layout.addWidget(self._save_btn)

        return footer

    # ------------------------------------------------------------------
    # Daten
    # ------------------------------------------------------------------

    def _populate(self, dto: KundeDTO) -> None:
        """Befüllt das Formular mit bestehenden Kundendaten."""
        anrede = dto.anrede or ""
        idx = self.f_anrede.findText(anrede)
        self.f_anrede.setCurrentIndex(idx if idx >= 0 else 0)
        self.f_name.set_value(dto.name)
        self.f_vorname.set_value(dto.vorname)
        self.f_titel_firma.set_value(dto.titel_firma)
        self.f_geburtsdatum.set_value(dto.geburtsdatum)
        self.f_strasse.set_value(dto.strasse)
        self.f_hausnummer.set_value(dto.hausnummer)
        self.f_plz.set_value(dto.plz)
        self.f_ort.set_value(dto.ort)
        self.f_telefon.set_value(dto.telefon)
        self.f_email.set_value(dto.email)

    def _collect(self) -> KundeDTO:
        """Liest alle Formularfelder aus und gibt ein DTO zurück."""
        anrede_txt = self.f_anrede.currentText()
        return KundeDTO(
            id=self._original_dto.id if self._original_dto else None,
            zifferncode=self._original_dto.zifferncode if self._original_dto else None,
            anrede="" if anrede_txt == "(keine Angabe)" else anrede_txt,
            name=self.f_name.value(),
            vorname=self.f_vorname.value(),
            titel_firma=self.f_titel_firma.value(),
            geburtsdatum=self.f_geburtsdatum.value(),
            strasse=self.f_strasse.value(),
            hausnummer=self.f_hausnummer.value(),
            plz=self.f_plz.value(),
            ort=self.f_ort.value(),
            telefon=self.f_telefon.value(),
            email=self.f_email.value(),
            is_active=True,
        )

    def _validate(self) -> bool:
        """Clientseitige Validierung — markiert Fehler direkt im Formular."""
        valid = True
        dto = self._collect()

        if not dto.name:
            self.f_name.set_error("Nachname ist ein Pflichtfeld.")
            valid = False
        if not dto.vorname:
            self.f_vorname.set_error("Vorname ist ein Pflichtfeld.")
            valid = False
        if dto.geburtsdatum:
            from datetime import datetime
            try:
                datetime.strptime(dto.geburtsdatum, "%d.%m.%Y")
            except ValueError:
                self.f_geburtsdatum.set_error("Format: TT.MM.JJJJ")
                valid = False
        if dto.email and "@" not in dto.email:
            self.f_email.set_error("Ungültige E-Mail-Adresse.")
            valid = False

        return valid

    def _on_save(self) -> None:
        if not self._validate():
            return
        dto = self._collect()
        self.saved.emit(dto)

    def show_error(self, message: str) -> None:
        self._banner.show_error(message)

    def close_dialog(self) -> None:
        self.accept()
