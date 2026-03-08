"""
ui/modules/lager/buchung_dialog.py – Buchungsdialog für Lager
=============================================================
Ein Dialog für alle drei manuellen Buchungsarten:
  - Einbuchen  (Wareneingang)
  - Ausbuchen  (Verbrauch / Verlust)
  - Korrektur  (Inventur-Abgleich)
"""

from decimal import Decimal, InvalidOperation

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFrame,
    QLabel, QPushButton, QWidget, QComboBox, QTextEdit,
)

from core.db.engine import db
from core.services.lager_service import lager_service, ArtikelDTO, Buchungsart
from ui.components.widgets import FormField, NotificationBanner
from ui.theme.theme import Colors, Fonts, Spacing, Radius


class BuchungDialog(QDialog):
    """
    Dialog für manuelle Lagerbuchungen.

    Args:
        modus:       "eingang" | "ausgang" | "korrektur"
        artikel_dto: Vorausgewählter Artikel (optional)

    Signals:
        gebucht(str): Wird mit der Erfolgsmeldung ausgelöst.
    """

    gebucht = Signal(str)

    TITEL = {
        "eingang":   ("Einbuchen",         Colors.SUCCESS),
        "ausgang":   ("Ausbuchen",          "#EF4444"),
        "korrektur": ("Bestand korrigieren", Colors.WARNING),
    }

    def __init__(self, modus: str, artikel_dto: ArtikelDTO = None, parent=None):
        super().__init__(parent)
        self._modus = modus
        self._artikel_dto = artikel_dto
        titel, _ = self.TITEL.get(modus, ("Buchung", Colors.PRIMARY))
        self.setWindowTitle(titel)
        self.setModal(True)
        self.setMinimumSize(500, 520)
        self.resize(520, 540)
        self._build_ui()
        if artikel_dto:
            self._set_artikel(artikel_dto)

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

        root.addWidget(self._build_form(), 1)
        root.addWidget(self._build_footer())

    def _build_header(self) -> QFrame:
        titel_text, titel_farbe = self.TITEL.get(
            self._modus, ("Buchung", Colors.PRIMARY)
        )
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

        title = QLabel(titel_text)
        title.setFont(Fonts.heading3())
        title.setStyleSheet(
            f"color: {titel_farbe}; background: transparent;"
        )
        layout.addWidget(title)
        layout.addStretch()
        return header

    def _build_form(self) -> QWidget:
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(Spacing.XL, Spacing.LG, Spacing.XL, Spacing.LG)
        layout.setSpacing(Spacing.MD)

        # Artikelauswahl (nur wenn kein Artikel vorausgewählt)
        if not self._artikel_dto:
            lbl_art = QLabel("Artikel *")
            lbl_art.setFont(Fonts.caption())
            lbl_art.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
            layout.addWidget(lbl_art)

            self._artikel_combo = QComboBox()
            self._artikel_combo.setMinimumHeight(36)
            self._artikel_combo.setPlaceholderText("Artikel auswählen…")
            self._lade_artikel_combo()
            self._artikel_combo.currentIndexChanged.connect(
                self._on_artikel_ausgewaehlt
            )
            layout.addWidget(self._artikel_combo)
        else:
            self._artikel_combo = None

        # Aktueller Bestand (Anzeige)
        self._bestand_frame = QFrame()
        self._bestand_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.BG_SURFACE};
                border-radius: {Radius.MD}px;
                border: 1px solid {Colors.BORDER};
            }}
        """)
        bf_layout = QHBoxLayout(self._bestand_frame)
        bf_layout.setContentsMargins(Spacing.LG, Spacing.MD, Spacing.LG, Spacing.MD)
        lbl_b = QLabel("Aktueller Bestand:")
        lbl_b.setFont(Fonts.get(Fonts.SIZE_SM))
        lbl_b.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        self._bestand_label = QLabel("–")
        self._bestand_label.setFont(Fonts.get(Fonts.SIZE_LG, bold=True))
        self._bestand_label.setStyleSheet(f"color: {Colors.TEXT_PRIMARY};")
        bf_layout.addWidget(lbl_b)
        bf_layout.addStretch()
        bf_layout.addWidget(self._bestand_label)
        layout.addWidget(self._bestand_frame)

        # Mengenfeld oder Zielbestand
        if self._modus == "korrektur":
            self.f_menge = FormField(
                "Neuer Zielbestand *",
                placeholder="z.B. 50",
                max_length=15,
            )
        else:
            label = "Eingehende Menge *" if self._modus == "eingang" else "Ausbuchende Menge *"
            self.f_menge = FormField(label, placeholder="z.B. 10", max_length=15)
        layout.addWidget(self.f_menge)

        # Referenz
        self.f_referenz = FormField(
            "Referenz (optional)",
            placeholder="z.B. Lieferschein 2025-042, Inventur Jan 2025",
            max_length=100,
        )
        layout.addWidget(self.f_referenz)

        # Notiz
        notiz_label = QLabel("Notiz (optional)")
        notiz_label.setFont(Fonts.caption())
        notiz_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        layout.addWidget(notiz_label)

        self._notiz_edit = QTextEdit()
        self._notiz_edit.setFixedHeight(70)
        self._notiz_edit.setPlaceholderText("Zusätzliche Informationen zur Buchung…")
        layout.addWidget(self._notiz_edit)

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

        titel_text, farbe = self.TITEL.get(self._modus, ("Buchen", Colors.PRIMARY))
        self._buch_btn = QPushButton(titel_text)
        self._buch_btn.setMinimumWidth(140)
        self._buch_btn.clicked.connect(self._on_buchen)
        self._buch_btn.setDefault(True)
        if self._modus == "ausgang":
            self._buch_btn.setProperty("role", "danger")
        elif self._modus == "eingang":
            self._buch_btn.setProperty("role", "success")
        layout.addWidget(self._buch_btn)

        return footer

    # ------------------------------------------------------------------
    # Hilfsmethoden
    # ------------------------------------------------------------------

    def _lade_artikel_combo(self) -> None:
        """Füllt die Artikelauswahl."""
        try:
            with db.session() as session:
                self._alle_artikel = lager_service.alle_artikel(session)
            self._artikel_combo.clear()
            self._artikel_combo.addItem("– Artikel auswählen –", None)
            for a in self._alle_artikel:
                self._artikel_combo.addItem(
                    f"{a.artikelnummer}  –  {a.beschreibung}", a
                )
        except Exception:
            self._alle_artikel = []

    def _on_artikel_ausgewaehlt(self, index: int) -> None:
        if self._artikel_combo:
            dto = self._artikel_combo.itemData(index)
            if dto:
                self._set_artikel(dto)

    def _set_artikel(self, dto: ArtikelDTO) -> None:
        """Zeigt den aktuellen Bestand des Artikels an."""
        self._artikel_dto = dto
        einheit = f" {dto.einheit}" if dto.einheit else ""
        self._bestand_label.setText(f"{float(dto.verfuegbar):g}{einheit}")

        farbe = Colors.ERROR if dto.bestand_negativ else (
            Colors.WARNING if dto.bestand_kritisch else Colors.SUCCESS
        )
        self._bestand_label.setStyleSheet(f"color: {farbe};")

    def _on_buchen(self) -> None:
        menge_str = self.f_menge.value().replace(",", ".")
        try:
            menge = Decimal(menge_str)
        except InvalidOperation:
            self.f_menge.set_error("Bitte eine gültige Zahl eingeben.")
            return

        if self._modus != "korrektur" and menge <= 0:
            self.f_menge.set_error("Menge muss größer als 0 sein.")
            return

        # Artikel bestimmen
        if self._artikel_combo:
            dto = self._artikel_combo.currentData()
        else:
            dto = self._artikel_dto

        if not dto:
            self._banner.show_error("Bitte einen Artikel auswählen.")
            return

        referenz = self.f_referenz.value()
        notiz = self._notiz_edit.toPlainText().strip()

        try:
            with db.session() as session:
                if self._modus == "eingang":
                    result = lager_service.einbuchen(
                        session, dto.artikelnummer, menge, referenz, notiz
                    )
                elif self._modus == "ausgang":
                    result = lager_service.ausbuchen(
                        session, dto.artikelnummer, menge, referenz, notiz
                    )
                else:  # korrektur
                    result = lager_service.korrektur(
                        session, dto.artikelnummer, menge, notiz
                    )
        except Exception as e:
            self._banner.show_error(f"Fehler: {e}")
            return

        if result.success:
            self.gebucht.emit(result.message)
            self.accept()
        else:
            self._banner.show_error(result.message)
