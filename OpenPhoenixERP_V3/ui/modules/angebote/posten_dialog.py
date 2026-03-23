"""
ui/modules/angebote/posten_dialog.py – Dialog für Angebotsposten
=================================================================
Zum Hinzufügen und Bearbeiten einzelner Angebotsposten.
Unterstützt Artikelauswahl aus dem Stamm UND freie Positionen
(z.B. Stunden, Service, Dienstleistung).
"""

from decimal import Decimal, InvalidOperation

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFrame, QComboBox, QWidget,
)

from core.services.angebote_service import AngebotsPostenDTO, berechne_gesamtpreis
from ui.components.widgets import FormField, NotificationBanner, SectionTitle
from ui.theme.theme import Colors, Fonts, Spacing, Radius


class AngebotsPostenDialog(QDialog):
    """
    Dialog zum Anlegen / Bearbeiten eines Angebotspostens.

    Unterstützt:
    - Artikelauswahl aus dem Lagerbestand (Dropdown)
    - Freie Positionen (Stunden, Service, Dienstleistung etc.)

    Signals:
        saved(AngebotsPostenDTO): Wird ausgelöst wenn der Nutzer speichert.
    """

    saved = Signal(object)  # AngebotsPostenDTO

    def __init__(
        self,
        parent=None,
        dto: AngebotsPostenDTO = None,
        position: int = 1,
        artikel_liste: list = None,
    ):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._edit_mode = dto is not None
        self._original_dto = dto
        self._position = dto.position if dto else position
        self._artikel_liste = artikel_liste or []
        self.setWindowTitle("Posten bearbeiten" if self._edit_mode else "Posten hinzufügen")
        self.setModal(True)
        self.setMinimumWidth(560)
        self._build_ui()
        if dto:
            self._populate(dto)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        header = QFrame()
        header.setObjectName("postenDialogHeader")
        header.setFixedHeight(56)
        header.setStyleSheet(f"""
            #postenDialogHeader {{
                background-color: {Colors.BG_SURFACE};
                border-bottom: 1px solid {Colors.BORDER};
            }}
        """)
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(Spacing.XL, 0, Spacing.XL, 0)
        icon = QLabel("📋")
        icon.setStyleSheet("font-size: 18px; background: transparent;")
        title = QLabel(self.windowTitle())
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
        c_layout.setContentsMargins(Spacing.XL, Spacing.LG, Spacing.XL, Spacing.LG)
        c_layout.setSpacing(Spacing.SM)

        self._banner = NotificationBanner()
        c_layout.addWidget(self._banner)

        # Artikelauswahl (wenn Artikel vorhanden)
        if self._artikel_liste:
            c_layout.addWidget(SectionTitle("Aus Artikelstamm laden (optional)"))
            combo_row = QHBoxLayout()
            self._artikel_combo = QComboBox()
            self._artikel_combo.addItem("– Artikel auswählen –", None)
            for art in self._artikel_liste:
                label = f"{art['artikelnummer']} – {art['beschreibung']}"
                self._artikel_combo.addItem(label, art)
            self._artikel_combo.currentIndexChanged.connect(self._on_artikel_selected)
            combo_row.addWidget(self._artikel_combo)
            c_layout.addLayout(combo_row)

        # Hinweis für freie Positionen
        hint = QLabel(
            "💡 Tipp: Für freie Positionen (Stunden, Service, Dienstleistung) "
            "lassen Sie die Artikelnummer leer und tragen Sie eine Beschreibung ein."
        )
        hint.setWordWrap(True)
        hint.setFont(Fonts.get(Fonts.SIZE_XS))
        hint.setStyleSheet(f"color: {Colors.TEXT_DISABLED}; background: transparent; padding: 4px 0;")
        c_layout.addWidget(hint)

        # Felder
        c_layout.addWidget(SectionTitle("Postendaten"))

        # Beschreibung
        self.f_beschreibung = FormField(
            "Beschreibung *", required=True,
            placeholder="z.B. Beratungsleistung, Montage, Artikel-Bezeichnung..."
        )
        c_layout.addWidget(self.f_beschreibung)

        # ArtNr + Einheit
        row1 = QHBoxLayout()
        row1.setSpacing(Spacing.MD)
        self.f_artikelnummer = FormField("Artikelnummer", placeholder="z.B. ART-001 (leer = freie Position)")
        self.f_einheit = FormField("Einheit", placeholder="z.B. Stück, h, kg, pauschal")
        self.f_einheit.setFixedWidth(160)
        row1.addWidget(self.f_artikelnummer, 2)
        row1.addWidget(self.f_einheit, 1)
        c_layout.addLayout(row1)

        # Menge + Einzelpreis + Gesamtpreis
        row2 = QHBoxLayout()
        row2.setSpacing(Spacing.MD)
        self.f_menge = FormField("Menge *", required=True, placeholder="1")
        self.f_menge.setFixedWidth(120)
        self.f_einzelpreis = FormField(
            "Einzelpreis netto (€) *", required=True, placeholder="0,00"
        )
        self.f_einzelpreis.setFixedWidth(180)

        # Gesamtpreis (schreibgeschützt, wird berechnet)
        gesamtpreis_widget = QWidget()
        gp_layout = QVBoxLayout(gesamtpreis_widget)
        gp_layout.setContentsMargins(0, 0, 0, 0)
        gp_layout.setSpacing(4)
        gp_lbl = QLabel("Gesamtpreis netto")
        gp_lbl.setFont(Fonts.get(Fonts.SIZE_SM))
        gp_lbl.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        self._gesamtpreis_label = QLabel("0,00 €")
        self._gesamtpreis_label.setFont(Fonts.get(Fonts.SIZE_LG, bold=True))
        self._gesamtpreis_label.setStyleSheet(
            f"color: {Colors.PRIMARY}; background: transparent;"
        )
        gp_layout.addWidget(gp_lbl)
        gp_layout.addWidget(self._gesamtpreis_label)

        row2.addWidget(self.f_menge)
        row2.addWidget(self.f_einzelpreis)
        row2.addWidget(gesamtpreis_widget)
        row2.addStretch()
        c_layout.addLayout(row2)

        # Live-Berechnung
        self.f_menge.value_changed.connect(self._update_gesamtpreis)
        self.f_einzelpreis.value_changed.connect(self._update_gesamtpreis)

        root.addWidget(content, 1)

        # Footer
        footer = QFrame()
        footer.setObjectName("postenDialogFooter")
        footer.setFixedHeight(64)
        footer.setStyleSheet(f"""
            #postenDialogFooter {{
                background-color: {Colors.BG_SURFACE};
                border-top: 1px solid {Colors.BORDER};
            }}
        """)
        f_layout = QHBoxLayout(footer)
        f_layout.setContentsMargins(Spacing.XL, 0, Spacing.XL, 0)
        f_layout.addStretch()

        cancel_btn = QPushButton("Abbrechen")
        cancel_btn.setProperty("role", "secondary")
        cancel_btn.clicked.connect(self.reject)
        f_layout.addWidget(cancel_btn)

        save_btn = QPushButton("💾  Übernehmen")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._on_save)
        f_layout.addWidget(save_btn)

        root.addWidget(footer)

    # ------------------------------------------------------------------
    # Daten
    # ------------------------------------------------------------------

    def _populate(self, dto: AngebotsPostenDTO) -> None:
        self.f_beschreibung.set_value(dto.beschreibung)
        self.f_artikelnummer.set_value(dto.artikelnummer)
        self.f_einheit.set_value(dto.einheit)
        self.f_menge.set_value(str(dto.menge).replace(".", ","))
        self.f_einzelpreis.set_value(str(dto.einzelpreis_netto).replace(".", ","))
        self._update_gesamtpreis()

    def _on_artikel_selected(self, index: int) -> None:
        art = self._artikel_combo.currentData()
        if not art:
            return
        self.f_beschreibung.set_value(art.get("beschreibung", ""))
        self.f_artikelnummer.set_value(art.get("artikelnummer", ""))
        self.f_einheit.set_value(art.get("einheit", ""))
        preis = art.get("einzelpreis_netto", Decimal("0"))
        self.f_einzelpreis.set_value(str(preis).replace(".", ","))
        self._update_gesamtpreis()

    def _parse_decimal(self, text: str) -> Decimal:
        try:
            # Tausenderpunkte entfernen, dann deutsches Komma → Dezimalpunkt
            clean = text.replace(".", "").replace(",", ".").strip()
            return Decimal(clean)
        except InvalidOperation:
            return Decimal("0")

    def _update_gesamtpreis(self, *_) -> None:
        menge = self._parse_decimal(self.f_menge.value())
        preis = self._parse_decimal(self.f_einzelpreis.value())
        gesamt = berechne_gesamtpreis(menge, preis)
        self._gesamtpreis_label.setText(
            f"{gesamt:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
        )

    def _collect(self) -> AngebotsPostenDTO:
        menge = self._parse_decimal(self.f_menge.value())
        preis = self._parse_decimal(self.f_einzelpreis.value())
        return AngebotsPostenDTO(
            id=self._original_dto.id if self._original_dto else None,
            angebot_id=self._original_dto.angebot_id if self._original_dto else None,
            position=self._position,
            artikelnummer=self.f_artikelnummer.value(),
            beschreibung=self.f_beschreibung.value(),
            menge=menge,
            einheit=self.f_einheit.value(),
            einzelpreis_netto=preis,
            gesamtpreis_netto=berechne_gesamtpreis(menge, preis),
        )

    def _validate(self) -> bool:
        valid = True
        if not self.f_beschreibung.value():
            self.f_beschreibung.set_error("Beschreibung ist ein Pflichtfeld.")
            valid = False
        try:
            m = Decimal(self.f_menge.value().replace(",", "."))
            if m == 0:
                self.f_menge.set_error("Menge darf nicht 0 sein.")
                valid = False
        except InvalidOperation:
            self.f_menge.set_error("Ungültige Zahl.")
            valid = False
        try:
            Decimal(self.f_einzelpreis.value().replace(",", "."))
        except InvalidOperation:
            self.f_einzelpreis.set_error("Ungültiger Preis.")
            valid = False
        return valid

    def _on_save(self) -> None:
        if not self._validate():
            return
        self.saved.emit(self._collect())
        self.accept()
