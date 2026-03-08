"""
ui/modules/einstellungen/panel.py – Einstellungen
===================================================
Zentrale Konfiguration aller Programmparameter.
Tabs: Firma | Rechnungen | Mahnwesen | E-Mail | Pfade | Datenbank
Alle Werte werden in config.toml gespeichert.
"""

import logging
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QTabWidget, QScrollArea, QFileDialog, QComboBox,
    QCheckBox, QSizePolicy, QTextEdit, QListWidget, QListWidgetItem,
    QSplitter, QInputDialog, QLineEdit, QDialog, QDialogButtonBox,
)

from core.config import config
from core.services.platzhalter_service import (
    load_vorlagen, save_vorlagen, reset_vorlage,
    load_custom_placeholders, save_custom_placeholders,
    BUILTIN_PLACEHOLDERS, DEFAULT_VORLAGEN,
)
from ui.components.widgets import FormField, SectionTitle, NotificationBanner
from ui.theme.theme import Colors, Fonts, Spacing, Radius

logger = logging.getLogger(__name__)


class EinstellungenPanel(QWidget):
    """
    Einstellungs-Panel mit Tab-Struktur.
    Jede Änderung wird erst beim Klick auf „Speichern" übernommen.
    """

    settings_saved = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._vorlagen  = load_vorlagen()
        self._custom_ph = load_custom_placeholders()
        self._build_ui()
        self._laden()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

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

        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                background-color: {Colors.BG_APP};
                border: none;
            }}
            QTabBar::tab {{
                background: transparent;
                color: {Colors.TEXT_SECONDARY};
                padding: 10px 20px;
                border-bottom: 2px solid transparent;
            }}
            QTabBar::tab:selected {{
                color: {Colors.PRIMARY};
                border-bottom: 2px solid {Colors.PRIMARY};
            }}
            QTabBar::tab:hover {{ color: {Colors.TEXT_PRIMARY}; }}
        """)

        self._tabs.addTab(self._build_firma_tab(),      "🏢  Firma")
        self._tabs.addTab(self._build_rechnung_tab(),   "🧾  Rechnungen")
        self._tabs.addTab(self._build_mahnwesen_tab(),  "📨  Mahnwesen")
        self._tabs.addTab(self._build_email_tab(),      "📧  E-Mail")
        self._tabs.addTab(self._build_vorlagen_tab(),   "📝  Textvorlagen")
        self._tabs.addTab(self._build_pfade_tab(),      "📁  Pfade")
        self._tabs.addTab(self._build_datenbank_tab(),  "🗄  Datenbank")

        root.addWidget(self._tabs, 1)
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
        icon = QLabel("⚙️")
        icon.setStyleSheet("font-size: 22px; background: transparent;")
        title = QLabel("Einstellungen")
        title.setFont(Fonts.heading2())
        title.setStyleSheet(
            f"color: {Colors.TEXT_PRIMARY}; background: transparent;"
        )
        layout.addWidget(icon)
        layout.addSpacing(Spacing.SM)
        layout.addWidget(title)
        layout.addStretch()
        return header

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

        hint = QLabel('Änderungen werden erst beim Klick auf „Speichern“ übernommen.')
        hint.setFont(Fonts.caption())
        hint.setStyleSheet(f"color: {Colors.TEXT_DISABLED};")
        layout.addWidget(hint)
        layout.addStretch()

        reset_btn = QPushButton("↩  Zurücksetzen")
        reset_btn.setProperty("role", "secondary")
        reset_btn.clicked.connect(self._laden)
        layout.addWidget(reset_btn)

        save_btn = QPushButton("💾  Speichern")
        save_btn.setMinimumWidth(140)
        save_btn.clicked.connect(self._speichern)
        save_btn.setDefault(True)
        layout.addWidget(save_btn)

        return footer

    # ------------------------------------------------------------------
    # Tab: Firma
    # ------------------------------------------------------------------

    def _build_firma_tab(self) -> QWidget:
        tab, layout = self._scroll_tab()

        layout.addWidget(SectionTitle("Unternehmensangaben"))
        layout.addWidget(
            _info("Diese Daten erscheinen auf Rechnungen und Mahnschreiben.")
        )

        self.f_firma_name = FormField(
            "Firmenname *", placeholder="Muster GmbH", max_length=200
        )
        layout.addWidget(self.f_firma_name)

        row1 = QHBoxLayout()
        self.f_firma_strasse = FormField(
            "Straße & Hausnummer", placeholder="Musterstraße 1", max_length=200
        )
        row1.addWidget(self.f_firma_strasse)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(Spacing.MD)
        self.f_firma_plz = FormField(
            "PLZ", placeholder="12345", max_length=10
        )
        self.f_firma_plz.setFixedWidth(110)
        self.f_firma_ort = FormField(
            "Ort", placeholder="Musterstadt", max_length=100
        )
        row2.addWidget(self.f_firma_plz)
        row2.addWidget(self.f_firma_ort, 1)
        layout.addLayout(row2)

        row3 = QHBoxLayout()
        row3.setSpacing(Spacing.MD)
        self.f_firma_telefon = FormField(
            "Telefon", placeholder="+49 30 1234567", max_length=50
        )
        self.f_firma_email = FormField(
            "E-Mail", placeholder="info@beispiel.de", max_length=200
        )
        row3.addWidget(self.f_firma_telefon)
        row3.addWidget(self.f_firma_email)
        layout.addLayout(row3)

        layout.addWidget(SectionTitle("Steuer & Bank"))
        self.f_firma_steuernr = FormField(
            "Steuernummer / USt-ID",
            placeholder="DE123456789 oder 123/456/78901",
            max_length=50,
        )
        layout.addWidget(self.f_firma_steuernr)

        self.f_firma_bank = FormField(
            "Bankverbindung (erscheint auf Rechnung)",
            placeholder="IBAN: DE00 1234 … | BIC: XXXXDEXX | Bank AG",
            max_length=300,
        )
        layout.addWidget(self.f_firma_bank)

        layout.addStretch()
        return tab

    # ------------------------------------------------------------------
    # Tab: Rechnungen
    # ------------------------------------------------------------------

    def _build_rechnung_tab(self) -> QWidget:
        tab, layout = self._scroll_tab()

        layout.addWidget(SectionTitle("Standardwerte"))

        row1 = QHBoxLayout()
        row1.setSpacing(Spacing.MD)
        self.f_mwst = FormField(
            "Standard-MwSt. (%)", placeholder="19", max_length=5
        )
        self.f_mwst.setFixedWidth(160)
        self.f_zahlungsziel = FormField(
            "Zahlungsziel (Tage)", placeholder="14", max_length=4
        )
        self.f_zahlungsziel.setFixedWidth(180)
        row1.addWidget(self.f_mwst)
        row1.addWidget(self.f_zahlungsziel)
        row1.addStretch()
        layout.addLayout(row1)

        layout.addWidget(SectionTitle("Rechnungsnummer-Format"))
        layout.addWidget(
            _info(
                "Platzhalter: {year} = Jahr, {number:04d} = Nummer mit 4 Stellen\n"
                "Beispiel: {year}-{number:04d}  ergibt  2025-0001"
            )
        )
        self.f_nummer_format = FormField(
            "Nummernformat",
            placeholder="{year}-{number:04d}",
            max_length=100,
        )
        layout.addWidget(self.f_nummer_format)

        layout.addStretch()
        return tab

    # ------------------------------------------------------------------
    # Tab: Mahnwesen
    # ------------------------------------------------------------------

    def _build_mahnwesen_tab(self) -> QWidget:
        tab, layout = self._scroll_tab()

        layout.addWidget(SectionTitle("Mahnstufen-Fristen (Tage nach Fälligkeit)"))
        layout.addWidget(
            _info(
                "Der Status wird automatisch beim App-Start aktualisiert, "
                "sobald eine Rechnung die jeweilige Grenze überschreitet."
            )
        )

        grid = QHBoxLayout()
        grid.setSpacing(Spacing.MD)
        self.f_erinnerung_tage = FormField(
            "Erinnerung ab Tag", placeholder="7", max_length=4
        )
        self.f_mahnung1_tage = FormField(
            "Mahnung 1 ab Tag", placeholder="21", max_length=4
        )
        self.f_mahnung2_tage = FormField(
            "Mahnung 2 ab Tag", placeholder="35", max_length=4
        )
        self.f_inkasso_tage = FormField(
            "Inkasso ab Tag", placeholder="49", max_length=4
        )
        for f in [self.f_erinnerung_tage, self.f_mahnung1_tage,
                  self.f_mahnung2_tage, self.f_inkasso_tage]:
            grid.addWidget(f)
        layout.addLayout(grid)

        layout.addWidget(SectionTitle("Mahngebühren (€)"))
        layout.addWidget(
            _info("Mahngebühren werden automatisch beim Stufenwechsel auf den offenen Betrag aufgeschlagen.")
        )

        fees = QHBoxLayout()
        fees.setSpacing(Spacing.MD)
        self.f_cost_erinnerung = FormField(
            "Erinnerung", placeholder="0,00", max_length=8
        )
        self.f_cost_mahnung1 = FormField(
            "Mahnung 1", placeholder="5,00", max_length=8
        )
        self.f_cost_mahnung2 = FormField(
            "Mahnung 2", placeholder="10,00", max_length=8
        )
        self.f_cost_inkasso = FormField(
            "Inkasso", placeholder="25,00", max_length=8
        )
        for f in [self.f_cost_erinnerung, self.f_cost_mahnung1,
                  self.f_cost_mahnung2, self.f_cost_inkasso]:
            fees.addWidget(f)
        layout.addLayout(fees)

        layout.addStretch()
        return tab

    # ------------------------------------------------------------------
    # Tab: E-Mail
    # ------------------------------------------------------------------

    def _build_email_tab(self) -> QWidget:
        tab, layout = self._scroll_tab()

        layout.addWidget(SectionTitle("SMTP-Konfiguration"))
        layout.addWidget(
            _info(
                "Wird für den Versand von Rechnungen und Mahnschreiben benötigt. "
                "Leer lassen wenn kein E-Mail-Versand gewünscht."
            )
        )

        row1 = QHBoxLayout()
        row1.setSpacing(Spacing.MD)
        self.f_smtp_server = FormField(
            "SMTP-Server", placeholder="smtp.example.com", max_length=200
        )
        self.f_smtp_port = FormField(
            "Port", placeholder="587", max_length=6
        )
        self.f_smtp_port.setFixedWidth(120)
        row1.addWidget(self.f_smtp_server, 3)
        row1.addWidget(self.f_smtp_port, 1)
        layout.addLayout(row1)

        self.f_smtp_user = FormField(
            "Benutzername / E-Mail",
            placeholder="absender@beispiel.de",
            max_length=200,
        )
        layout.addWidget(self.f_smtp_user)

        self.f_smtp_password = FormField(
            "Passwort", placeholder="••••••••", max_length=200
        )
        # Passwortfeld: Eingabe verbergen
        self.f_smtp_password._input.setEchoMode(
            self.f_smtp_password._input.EchoMode.Password
        )
        layout.addWidget(self.f_smtp_password)
        # Sicherheits-Hinweis: zeigt ob keyring aktiv ist
        from core.services.credential_service import keyring_verfuegbar
        self._smtp_sicher_lbl = QLabel()
        self._smtp_sicher_lbl.setWordWrap(True)
        if keyring_verfuegbar():
            self._smtp_sicher_lbl.setText(
                "🔒  Passwort wird im OS-Schlüsselbund gespeichert – nicht in config.toml")
            self._smtp_sicher_lbl.setStyleSheet(
                f"color: {Colors.SUCCESS}; font-size: 11px; padding: 2px 0;")
        else:
            self._smtp_sicher_lbl.setText(
                "⚠  keyring nicht verfügbar – verschlüsselter Fallback aktiv")
            self._smtp_sicher_lbl.setStyleSheet(
                f"color: {Colors.WARNING}; font-size: 11px; padding: 2px 0;")
        layout.addWidget(self._smtp_sicher_lbl)

        layout.addWidget(SectionTitle("Verschlüsselung"))
        enc_row = QHBoxLayout()
        enc_lbl = QLabel("Verbindungstyp")
        enc_lbl.setFont(Fonts.caption())
        enc_lbl.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        self._smtp_enc_combo = QComboBox()
        self._smtp_enc_combo.addItems(["STARTTLS", "SSL/TLS", "Keine"])
        self._smtp_enc_combo.setMinimumHeight(36)
        enc_row.addWidget(enc_lbl)
        enc_row.addWidget(self._smtp_enc_combo)
        enc_row.addStretch()
        layout.addLayout(enc_row)

        # Hinweis Microsoft / App-Passwort
        layout.addWidget(SectionTitle("Hinweise"))
        hint_box = QFrame()
        hint_box.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.BG_ELEVATED};
                border: 1px solid {Colors.BORDER};
                border-radius: 6px;
                padding: 4px;
            }}
        """)
        hint_layout = QVBoxLayout(hint_box)
        hint_layout.setContentsMargins(12, 10, 12, 10)
        hint_layout.setSpacing(6)

        for text in [
            "📧  <b>Gmail:</b> STARTTLS, Port 587 — 2-Faktor + App-Passwort unter "
            "myaccount.google.com → Sicherheit → App-Passwörter erstellen.",

            "📧  <b>Outlook.com (privat):</b> ⚠ Microsoft hat SMTP Basic Auth für private "
            "Konten vollständig deaktiviert — <b>kein SMTP-Versand möglich</b>, auch nicht mit "
            "App-Passwort. Workaround: E-Mail-Weiterleitungsdienst (z.B. SendGrid, Brevo) oder "
            "ein anderes Absender-Konto verwenden.",

            "📧  <b>Microsoft 365 (Geschäftskonto):</b> SMTP AUTH muss vom IT-Administrator "
            "pro Postfach aktiviert werden (Exchange Admin Center → Postfächer → "
            "E-Mail-Apps → SMTP AUTH). Danach funktioniert SSL/TLS Port 465 mit "
            "normalem Passwort oder App-Passwort (bei aktivierter MFA).",

            "📧  <b>GMX / Web.de:</b> STARTTLS, Port 587 — normales Passwort funktioniert, "
            "SMTP-Zugang muss im Webmail-Konto unter Einstellungen aktiviert sein.",

            "📧  <b>Eigener Server:</b> Einstellungen je nach Server-Konfiguration.",
        ]:
            lbl = QLabel(text)
            lbl.setWordWrap(True)
            lbl.setFont(Fonts.caption())
            lbl.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; background: transparent;")
            lbl.setOpenExternalLinks(True)
            hint_layout.addWidget(lbl)

        layout.addWidget(hint_box)

        # Verbindung testen
        layout.addWidget(SectionTitle("Verbindungstest"))
        test_row = QHBoxLayout()
        self._smtp_test_btn = QPushButton("Verbindung testen")
        self._smtp_test_btn.setProperty("role", "secondary")
        self._smtp_test_btn.setMinimumWidth(180)
        self._smtp_test_btn.clicked.connect(self._test_smtp)
        self._smtp_test_lbl = QLabel("")
        self._smtp_test_lbl.setFont(Fonts.caption())
        self._smtp_test_lbl.setWordWrap(True)
        test_row.addWidget(self._smtp_test_btn)
        test_row.addWidget(self._smtp_test_lbl, 1)
        test_row.addStretch()
        layout.addLayout(test_row)

        layout.addStretch()
        return tab

    # ------------------------------------------------------------------
    # Tab: Pfade
    # ------------------------------------------------------------------

    def _build_pfade_tab(self) -> QWidget:
        tab, layout = self._scroll_tab()

        layout.addWidget(SectionTitle("Ordner und Dateipfade"))
        layout.addWidget(
            _info("Alle Pfade können leer gelassen werden — "
                  "die entsprechenden Funktionen sind dann deaktiviert.")
        )

        # Hilfsfunktion: Pfad-Zeile mit Browse-Button
        def pfad_zeile(label: str, placeholder: str) -> tuple:
            field = FormField(label, placeholder=placeholder, max_length=500)
            row = QHBoxLayout()
            row.setSpacing(Spacing.SM)
            row.addWidget(field, 1)
            btn = QPushButton("📁  Auswählen")
            btn.setProperty("role", "secondary")
            btn.setFixedHeight(36)

            def browse(f=field):
                pfad = QFileDialog.getExistingDirectory(
                    self, "Ordner auswählen", f.value() or ""
                )
                if pfad:
                    f.set_value(pfad)

            btn.clicked.connect(lambda _=False, f=field: browse(f))
            row.addWidget(btn)
            return field, row

        self.f_pfad_dokumente, row_dok = pfad_zeile(
            "Kundendokumente",
            "z.B. C:/Firma/Kundendokumente",
        )
        layout.addLayout(row_dok)

        layout.addWidget(SectionTitle("Rechnungs-PDF"))
        layout.addWidget(
            _info(
                "Optionales Hintergrundbild / Briefpapier für alle PDF-Rechnungen und Mahnschreiben. "
                "Unterstützte Formate: PDF, JPG, PNG. "
                "Das Bild wird auf die gesamte A4-Seite skaliert und hinter den Inhalt gelegt — "
                "ideal für vorgestaltetes Briefpapier mit Logo, Adressfeld und Firmendesign. "
                "Leer lassen für kein Hintergrundbild."
            )
        )

        bg_row = QHBoxLayout()
        bg_row.setSpacing(Spacing.SM)
        self.f_pdf_bg = FormField(
            "Hintergrundbild",
            placeholder="z.B. C:/Firma/Briefpapier.pdf  oder  Briefpapier.jpg",
            max_length=500,
        )
        bg_row.addWidget(self.f_pdf_bg, 1)
        bg_btn = QPushButton("📄  Auswählen")
        bg_btn.setProperty("role", "secondary")
        bg_btn.setFixedHeight(36)

        def browse_pdf():
            pfad, _ = QFileDialog.getOpenFileName(
                self, "Hintergrundbild auswählen", self.f_pdf_bg.value() or "",
                "Bilder & PDF (*.pdf *.jpg *.jpeg *.png *.bmp)"
            )
            if pfad:
                self.f_pdf_bg.set_value(pfad)

        bg_btn.clicked.connect(browse_pdf)
        bg_row.addWidget(bg_btn)
        layout.addLayout(bg_row)

        layout.addStretch()
        return tab

    # ------------------------------------------------------------------
    # Tab: Textvorlagen & Platzhalter
    # ------------------------------------------------------------------

    def _build_vorlagen_tab(self) -> QWidget:
        tab = QWidget()
        root_layout = QVBoxLayout(tab)
        root_layout.setContentsMargins(Spacing.XL, Spacing.LG, Spacing.XL, Spacing.LG)
        root_layout.setSpacing(Spacing.SM)

        root_layout.addWidget(SectionTitle("Textvorlagen bearbeiten"))
        root_layout.addWidget(_info(
            "Bearbeiten Sie Texte für Rechnungshinweis, Mahnschreiben und E-Mails. "
            "Platzhalter wie {{RECHNUNGSNUMMER}} werden beim Erstellen automatisch ersetzt. "
            "Wählen Sie eine Vorlage, bearbeiten Sie den Text und klicken Sie 'Speichern'."
        ))

        # Vorlage auswählen
        vorlage_keys = {
            "📄  Rechnung – Zahlungshinweis":        "rechnung_hinweis",
            "📧  E-Mail – Standard Betreff":         "email_standard_betreff",
            "📧  E-Mail – Standard Nachricht":       "email_standard_text",
            "📧  E-Mail – Rechnung Betreff":         "email_rechnung_betreff",
            "📧  E-Mail – Rechnung Nachricht":       "email_rechnung_text",
            "📧  E-Mail – Mahnung Betreff":          "email_mahnung_betreff",
            "📧  E-Mail – Mahnung Nachricht":        "email_mahnung_text",
            "🔔  Zahlungserinnerung – Titel":        "mahnung_erinnerung_titel",
            "🔔  Zahlungserinnerung – Text":         "mahnung_erinnerung_text",
            "🔔  Zahlungserinnerung – Schluss":      "mahnung_erinnerung_schluss",
            "⚠   1. Mahnung – Titel":               "mahnung_1_titel",
            "⚠   1. Mahnung – Text":                "mahnung_1_text",
            "⚠   1. Mahnung – Schluss":             "mahnung_1_schluss",
            "🔴  2. Mahnung – Titel":                "mahnung_2_titel",
            "🔴  2. Mahnung – Text":                 "mahnung_2_text",
            "🔴  2. Mahnung – Schluss":              "mahnung_2_schluss",
            "🚨  Inkasso-Ankündigung – Titel":       "mahnung_inkasso_titel",
            "🚨  Inkasso-Ankündigung – Text":        "mahnung_inkasso_text",
            "🚨  Inkasso-Ankündigung – Schluss":     "mahnung_inkasso_schluss",
        }
        self._vorlage_key_map = vorlage_keys
        self._current_vorlage_key = ""

        sel_row = QHBoxLayout()
        lbl_sel = QLabel("Vorlage:")
        lbl_sel.setFont(Fonts.caption())
        lbl_sel.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        lbl_sel.setFixedWidth(70)
        self._vorlage_combo = QComboBox()
        self._vorlage_combo.addItems(list(vorlage_keys.keys()))
        self._vorlage_combo.setMinimumHeight(36)
        sel_row.addWidget(lbl_sel)
        sel_row.addWidget(self._vorlage_combo, 1)
        root_layout.addLayout(sel_row)

        # Splitter: Texteditor links | Platzhalter-Auswahl rechts
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # ── Linke Seite: Editor ────────────────────────────────────────
        editor_widget = QWidget()
        editor_layout = QVBoxLayout(editor_widget)
        editor_layout.setContentsMargins(0, 0, Spacing.SM, 0)
        editor_layout.setSpacing(Spacing.XS if hasattr(Spacing, "XS") else 4)

        self._vorlage_editor = QTextEdit()
        self._vorlage_editor.setMinimumHeight(200)
        self._vorlage_editor.setPlaceholderText("Vorlage oben auswählen …")
        self._vorlage_editor.setStyleSheet(
            f"background: {Colors.BG_ELEVATED}; "
            f"color: {Colors.TEXT_PRIMARY}; "
            f"border: 1px solid {Colors.BORDER}; "
            f"border-radius: {Radius.SM}px; "
            f"padding: 8px; font-family: monospace;"
        )
        editor_layout.addWidget(self._vorlage_editor, 1)

        btn_editor_row = QHBoxLayout()
        btn_save_vorlage = QPushButton("💾  Speichern")
        btn_save_vorlage.setProperty("role", "primary")
        btn_save_vorlage.setFixedHeight(36)
        btn_reset_vorlage = QPushButton("↩  Standard")
        btn_reset_vorlage.setProperty("role", "secondary")
        btn_reset_vorlage.setFixedHeight(36)
        btn_editor_row.addWidget(btn_save_vorlage)
        btn_editor_row.addWidget(btn_reset_vorlage)
        btn_editor_row.addStretch()
        editor_layout.addLayout(btn_editor_row)
        splitter.addWidget(editor_widget)

        # ── Rechte Seite: Platzhalter-Liste ───────────────────────────
        ph_widget = QWidget()
        ph_layout = QVBoxLayout(ph_widget)
        ph_layout.setContentsMargins(Spacing.SM, 0, 0, 0)
        ph_layout.setSpacing(Spacing.XS if hasattr(Spacing, "XS") else 4)

        ph_lbl = QLabel("Verfügbare Platzhalter")
        ph_lbl.setFont(Fonts.caption())
        ph_lbl.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        ph_layout.addWidget(ph_lbl)

        self._ph_list = QListWidget()
        self._ph_list.setAlternatingRowColors(True)
        self._ph_list.setStyleSheet(
            f"QListWidget {{ background: {Colors.BG_ELEVATED}; "
            f"border: 1px solid {Colors.BORDER}; border-radius: {Radius.SM}px; }}"
            f"QListWidget::item {{ padding: 3px 6px; font-size: 11px; }}"
            f"QListWidget::item:selected {{ background: {Colors.PRIMARY}; color: white; }}"
        )
        ph_layout.addWidget(self._ph_list, 1)

        btn_insert = QPushButton("↙  In Text einfügen")
        btn_insert.setProperty("role", "secondary")
        btn_insert.setFixedHeight(34)
        ph_layout.addWidget(btn_insert)
        splitter.addWidget(ph_widget)
        splitter.setSizes([460, 220])
        root_layout.addWidget(splitter, 1)

        # ── Eigene Platzhalter ─────────────────────────────────────────
        root_layout.addWidget(SectionTitle("Eigene Platzhalter"))
        root_layout.addWidget(_info(
            "Definieren Sie eigene statische Platzhalter, z.B. {{SACHBEARBEITER}} = 'Max Muster'. "
            "Sie erscheinen in der Liste oben und können in allen Vorlagen verwendet werden."
        ))

        add_row = QHBoxLayout()
        self._new_ph_key   = FormField("Name (ohne {{}})", placeholder="MEIN_PLATZHALTER", max_length=50)
        self._new_ph_value = FormField("Wert", placeholder="Beliebiger Text", max_length=200)
        btn_add_ph = QPushButton("➕  Hinzufügen")
        btn_add_ph.setProperty("role", "secondary")
        btn_add_ph.setFixedHeight(36)
        add_row.addWidget(self._new_ph_key, 1)
        add_row.addWidget(self._new_ph_value, 2)
        add_row.addWidget(btn_add_ph)
        root_layout.addLayout(add_row)

        self._custom_ph_list = QListWidget()
        self._custom_ph_list.setMaximumHeight(100)
        self._custom_ph_list.setAlternatingRowColors(True)
        root_layout.addWidget(self._custom_ph_list)

        btn_del_ph = QPushButton("🗑  Ausgewählten löschen")
        btn_del_ph.setProperty("role", "danger")
        btn_del_ph.setMaximumWidth(220)
        root_layout.addWidget(btn_del_ph)

        # ── Signale verbinden ──────────────────────────────────────────
        self._vorlage_combo.currentIndexChanged.connect(self._on_vorlage_changed)
        btn_save_vorlage.clicked.connect(self._vorlage_speichern)
        btn_reset_vorlage.clicked.connect(self._vorlage_reset)
        btn_insert.clicked.connect(self._platzhalter_einfuegen)
        self._ph_list.itemDoubleClicked.connect(lambda _: self._platzhalter_einfuegen())
        btn_add_ph.clicked.connect(self._custom_ph_hinzufuegen)
        btn_del_ph.clicked.connect(self._custom_ph_loeschen)

        # Initial befüllen
        self._ph_liste_aktualisieren()
        self._custom_ph_liste_aktualisieren()
        self._on_vorlage_changed(0)

        return tab

    # ── Vorlagen-Hilfsmethoden ─────────────────────────────────────────

    def _on_vorlage_changed(self, _index: int = 0) -> None:
        """Lädt den Text der gewählten Vorlage in den Editor."""
        display = self._vorlage_combo.currentText()
        key = self._vorlage_key_map.get(display, "")
        self._current_vorlage_key = key
        text = self._vorlagen.get(key, DEFAULT_VORLAGEN.get(key, ""))
        self._vorlage_editor.setPlainText(text)

    def _vorlage_speichern(self) -> None:
        """Speichert die aktuell angezeigte Vorlage."""
        key = self._current_vorlage_key
        if not key:
            return
        self._vorlagen[key] = self._vorlage_editor.toPlainText()
        if save_vorlagen(self._vorlagen):
            self._banner.show_success("Vorlage gespeichert.")
        else:
            self._banner.show_error("Fehler beim Speichern der Vorlage.")

    def _vorlage_reset(self) -> None:
        """Setzt die aktuelle Vorlage auf den Standardtext zurück."""
        key = self._current_vorlage_key
        if not key:
            return
        default = reset_vorlage(key)
        self._vorlage_editor.setPlainText(default)
        self._vorlagen[key] = default
        save_vorlagen(self._vorlagen)
        self._banner.show_info("Vorlage auf Standard zurückgesetzt.")

    def _platzhalter_einfuegen(self) -> None:
        """Fügt den gewählten Platzhalter an die Cursor-Position ein."""
        item = self._ph_list.currentItem()
        if not item:
            return
        text = item.text()
        # Trennzeilen überspringen
        if text.startswith("──"):
            return
        # Platzhalter-Key extrahieren: "{{KEY}}  –  Beschreibung"
        ph = text.split("  ")[0].strip()
        if not ph.startswith("{{"):
            return
        self._vorlage_editor.insertPlainText(ph)
        self._vorlage_editor.setFocus()

    def _ph_liste_aktualisieren(self) -> None:
        """Aktualisiert die Platzhalter-Liste (eingebaut + benutzerdefiniert)."""
        self._ph_list.clear()

        # Eingebaute Platzhalter
        sep = QListWidgetItem("──  Eingebaut  ──")
        sep.setFlags(sep.flags() & ~Qt.ItemFlag.ItemIsSelectable & ~Qt.ItemFlag.ItemIsEnabled)
        sep.setForeground(self._ph_list.palette().color(
            self._ph_list.palette().ColorRole.PlaceholderText))
        self._ph_list.addItem(sep)
        for key, desc in BUILTIN_PLACEHOLDERS.items():
            self._ph_list.addItem(f"{{{{{key}}}}}  –  {desc}")

        # Benutzerdefinierte Platzhalter
        custom = load_custom_placeholders()
        if custom:
            sep2 = QListWidgetItem("──  Eigene  ──")
            sep2.setFlags(sep2.flags() & ~Qt.ItemFlag.ItemIsSelectable & ~Qt.ItemFlag.ItemIsEnabled)
            sep2.setForeground(self._ph_list.palette().color(
                self._ph_list.palette().ColorRole.PlaceholderText))
            self._ph_list.addItem(sep2)
            for key, val in sorted(custom.items()):
                preview = val[:35] + "…" if len(val) > 35 else val
                self._ph_list.addItem(f"{{{{{key}}}}}  =  {preview}")

    def _custom_ph_liste_aktualisieren(self) -> None:
        """Aktualisiert die kleine Verwaltungs-Liste der eigenen Platzhalter."""
        self._custom_ph_list.clear()
        for key, val in sorted(load_custom_placeholders().items()):
            self._custom_ph_list.addItem(f"{{{{{key}}}}}  =  {val}")

    def _custom_ph_hinzufuegen(self) -> None:
        """Fügt einen neuen benutzerdefinierten Platzhalter hinzu."""
        key = self._new_ph_key.value().strip().upper()
        val = self._new_ph_value.value().strip()
        if not key or not val:
            self._banner.show_warning("Bitte Name und Wert angeben.")
            return
        # {{}} entfernen falls User sie mitgeschrieben hat
        key = key.strip("{}").replace(" ", "_")
        ph = load_custom_placeholders()
        ph[key] = val
        if save_custom_placeholders(ph):
            self._custom_ph = ph
            self._new_ph_key.set_value("")
            self._new_ph_value.set_value("")
            self._ph_liste_aktualisieren()
            self._custom_ph_liste_aktualisieren()

    def _custom_ph_loeschen(self) -> None:
        """Löscht den in der Verwaltungs-Liste gewählten Platzhalter."""
        item = self._custom_ph_list.currentItem()
        if not item:
            self._banner.show_warning("Bitte einen Platzhalter zum Löschen auswählen.")
            return
        # Key aus "{{KEY}}  =  Wert" extrahieren
        raw = item.text().split("}}")[0].lstrip("{").strip()
        ph = load_custom_placeholders()
        if raw in ph:
            del ph[raw]
            save_custom_placeholders(ph)
            self._custom_ph = ph
            self._ph_liste_aktualisieren()
            self._custom_ph_liste_aktualisieren()


    # ------------------------------------------------------------------
    # Tab: Datenbank
    # ------------------------------------------------------------------

    def _build_datenbank_tab(self) -> QWidget:
        tab, layout = self._scroll_tab()

        layout.addWidget(SectionTitle("Aktueller Modus"))

        modus = "Lokale SQLite-Datenbank" if config.is_local_db() else "PostgreSQL-Server"
        modus_lbl = QLabel(f"{'🗂' if config.is_local_db() else '🖧'}  {modus}")
        modus_lbl.setFont(Fonts.get(Fonts.SIZE_BASE, bold=True))
        modus_lbl.setStyleSheet(
            f"color: {Colors.SUCCESS if config.is_local_db() else Colors.INFO};"
        )
        layout.addWidget(modus_lbl)

        if config.is_local_db():
            db_path = config.get("database", "path", "openphoenix.db")
            path_lbl = QLabel(f"Datei: {db_path}")
            path_lbl.setFont(Fonts.caption())
            path_lbl.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
            layout.addWidget(path_lbl)

        layout.addWidget(SectionTitle("Datenbank wechseln"))
        layout.addWidget(
            _info(
                "⚠  Beim Wechsel der Datenbank wird die Anwendung neu gestartet. "
                "Alle nicht gespeicherten Daten gehen verloren."
            )
        )

        btn_row = QHBoxLayout()
        btn_local = QPushButton("🗂  Lokale SQLite-Datei öffnen")
        btn_local.setProperty("role", "secondary")
        btn_local.clicked.connect(self._db_wechseln_lokal)
        btn_row.addWidget(btn_local)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        layout.addWidget(SectionTitle("Info"))
        infos = [
            ("Version",       "OpenPhoenix ERP v2.0.0"),
            ("Datenbank",     modus),
            ("Python",        __import__("sys").version.split()[0]),
            ("Lizenz",        "GPL v3"),
        ]
        for schluessel, wert in infos:
            row = QHBoxLayout()
            k_lbl = QLabel(schluessel)
            k_lbl.setFixedWidth(120)
            k_lbl.setFont(Fonts.caption())
            k_lbl.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
            v_lbl = QLabel(wert)
            v_lbl.setFont(Fonts.get(Fonts.SIZE_SM))
            v_lbl.setStyleSheet(f"color: {Colors.TEXT_PRIMARY};")
            row.addWidget(k_lbl)
            row.addWidget(v_lbl)
            row.addStretch()
            layout.addLayout(row)

        layout.addStretch()
        return tab

    # ------------------------------------------------------------------
    # Daten laden / speichern
    # ------------------------------------------------------------------

    def _laden(self) -> None:
        """Liest alle Werte aus der config und befüllt die Felder."""
        c = config

        # Firma
        self.f_firma_name.set_value(c.get("company", "name", ""))
        self.f_firma_strasse.set_value(c.get("company", "address", ""))
        self.f_firma_plz.set_value(c.get("company", "zip", ""))
        self.f_firma_ort.set_value(c.get("company", "city", ""))
        # Rückwärtskompatibilität: zip_city → zip + city beim ersten Start
        if not c.get("company", "zip", "") and not c.get("company", "city", ""):
            zip_city = c.get("company", "zip_city", "")
            if zip_city:
                teile = zip_city.split(" ", 1)
                if len(teile) == 2:
                    self.f_firma_plz.set_value(teile[0])
                    self.f_firma_ort.set_value(teile[1])
        self.f_firma_telefon.set_value(c.get("company", "phone", ""))
        self.f_firma_email.set_value(c.get("company", "email", ""))
        self.f_firma_steuernr.set_value(c.get("company", "tax_id", ""))
        self.f_firma_bank.set_value(c.get("company", "bank_details", ""))

        # Rechnungen
        self.f_mwst.set_value(str(c.get("invoice", "default_vat", 19)))
        self.f_zahlungsziel.set_value(str(c.get("invoice", "payment_days", 14)))
        self.f_nummer_format.set_value(
            c.get("invoice", "number_format", "{year}-{number:04d}")
        )

        # Mahnwesen
        self.f_erinnerung_tage.set_value(str(c.get("dunning", "reminder_days", 7)))
        self.f_mahnung1_tage.set_value(str(c.get("dunning", "mahnung1_days", 21)))
        self.f_mahnung2_tage.set_value(str(c.get("dunning", "mahnung2_days", 35)))
        self.f_inkasso_tage.set_value(str(c.get("dunning", "inkasso_days", 49)))
        self.f_cost_erinnerung.set_value(
            str(c.get("dunning", "cost_erinnerung", "0.00")).replace(".", ",")
        )
        self.f_cost_mahnung1.set_value(
            str(c.get("dunning", "cost_mahnung1", "5.00")).replace(".", ",")
        )
        self.f_cost_mahnung2.set_value(
            str(c.get("dunning", "cost_mahnung2", "10.00")).replace(".", ",")
        )
        self.f_cost_inkasso.set_value(
            str(c.get("dunning", "cost_inkasso", "25.00")).replace(".", ",")
        )

        # SMTP
        self.f_smtp_server.set_value(c.get("smtp", "server", ""))
        self.f_smtp_port.set_value(str(c.get("smtp", "port", 587)))
        self.f_smtp_user.set_value(c.get("smtp", "user", ""))
        # Passwort aus sicherem OS-Schlüsselbund laden
        from core.services.credential_service import passwort_laden, keyring_verfuegbar
        _pw = passwort_laden()
        self.f_smtp_password.set_value(_pw)
        # Hinweis ob keyring aktiv ist
        if hasattr(self, "_smtp_sicher_lbl"):
            if keyring_verfuegbar():
                self._smtp_sicher_lbl.setText("🔒  Passwort wird im OS-Schlüsselbund gespeichert")
                self._smtp_sicher_lbl.setStyleSheet(f"color: {Colors.SUCCESS}; font-size: 11px;")
            else:
                self._smtp_sicher_lbl.setText("⚠  keyring nicht verfügbar – verschlüsselter Fallback aktiv")
                self._smtp_sicher_lbl.setStyleSheet(f"color: {Colors.WARNING}; font-size: 11px;")
        enc = c.get("smtp", "encryption", "STARTTLS")
        idx = self._smtp_enc_combo.findText(enc)
        if idx >= 0:
            self._smtp_enc_combo.setCurrentIndex(idx)

        # Pfade
        self.f_pfad_dokumente.set_value(c.get("paths", "documents", ""))
        self.f_pdf_bg.set_value(c.get("paths", "pdf_background", ""))

        # Textvorlagen: erste Vorlage anzeigen
        if hasattr(self, "_vorlage_combo"):
            self._on_vorlage_changed(0)

    def _speichern(self) -> None:
        """Validiert alle Felder und schreibt in config.toml."""
        fehler = self._validiere()
        if fehler:
            self._banner.show_error(fehler)
            return

        c = config

        # Firma
        c.set("company", "name",         self.f_firma_name.value())
        c.set("company", "address",      self.f_firma_strasse.value())
        c.set("company", "zip",         self.f_firma_plz.value())
        c.set("company", "city",        self.f_firma_ort.value())
        # zip_city für Abwärtskompatibilität (PDF-Service)
        c.set("company", "zip_city",    f"{self.f_firma_plz.value()} {self.f_firma_ort.value()}".strip())
        c.set("company", "phone",        self.f_firma_telefon.value())
        c.set("company", "email",        self.f_firma_email.value())
        c.set("company", "tax_id",       self.f_firma_steuernr.value())
        c.set("company", "bank_details", self.f_firma_bank.value())

        # Rechnungen
        c.set("invoice", "default_vat",    float(self.f_mwst.value().replace(",", ".")))
        c.set("invoice", "payment_days",   int(self.f_zahlungsziel.value()))
        c.set("invoice", "number_format",  self.f_nummer_format.value())

        # Mahnwesen
        c.set("dunning", "reminder_days",   int(self.f_erinnerung_tage.value()))
        c.set("dunning", "mahnung1_days",   int(self.f_mahnung1_tage.value()))
        c.set("dunning", "mahnung2_days",   int(self.f_mahnung2_tage.value()))
        c.set("dunning", "inkasso_days",    int(self.f_inkasso_tage.value()))
        c.set("dunning", "cost_erinnerung", float(self.f_cost_erinnerung.value().replace(",", ".")))
        c.set("dunning", "cost_mahnung1",   float(self.f_cost_mahnung1.value().replace(",", ".")))
        c.set("dunning", "cost_mahnung2",   float(self.f_cost_mahnung2.value().replace(",", ".")))
        c.set("dunning", "cost_inkasso",    float(self.f_cost_inkasso.value().replace(",", ".")))

        # SMTP
        c.set("smtp", "server",     self.f_smtp_server.value())
        c.set("smtp", "port",       int(self.f_smtp_port.value() or "587"))
        c.set("smtp", "user",       self.f_smtp_user.value())
        # Passwort sicher im OS-Schlüsselbund speichern (NICHT in config.toml)
        from core.services.credential_service import passwort_speichern
        passwort_speichern(self.f_smtp_password.value())
        c.set("smtp", "encryption", self._smtp_enc_combo.currentText())

        # Pfade
        c.set("paths", "documents",       self.f_pfad_dokumente.value())
        c.set("paths", "pdf_background",  self.f_pdf_bg.value())

        # Aktuelle Textvorlage mitschreiben (falls Tab geöffnet war)
        if hasattr(self, "_current_vorlage_key") and self._current_vorlage_key:
            self._vorlagen[self._current_vorlage_key] = \
                self._vorlage_editor.toPlainText()
            save_vorlagen(self._vorlagen)

        # Auf Disk schreiben
        try:
            c.save()
            self._banner.show_success("Einstellungen gespeichert.")
            self.settings_saved.emit()
            logger.info("Einstellungen gespeichert.")
        except Exception as e:
            self._banner.show_error(f"Fehler beim Speichern: {e}")

    def _validiere(self) -> str:
        """Gibt Fehlermeldung zurück oder ''."""
        if not self.f_firma_name.value():
            return "Firmenname darf nicht leer sein."

        for lbl, feld in [
            ("Standard-MwSt.", self.f_mwst),
            ("Zahlungsziel",   self.f_zahlungsziel),
        ]:
            try:
                val = float(feld.value().replace(",", "."))
                assert val >= 0
            except (ValueError, AssertionError):
                return f"{lbl}: Bitte eine gültige nicht-negative Zahl eingeben."

        for lbl, feld in [
            ("Erinnerung Tage",  self.f_erinnerung_tage),
            ("Mahnung1 Tage",    self.f_mahnung1_tage),
            ("Mahnung2 Tage",    self.f_mahnung2_tage),
            ("Inkasso Tage",     self.f_inkasso_tage),
        ]:
            try:
                val = int(feld.value())
                assert val > 0
            except (ValueError, AssertionError):
                return f"{lbl}: Bitte eine positive ganze Zahl eingeben."

        tage = [
            int(self.f_erinnerung_tage.value()),
            int(self.f_mahnung1_tage.value()),
            int(self.f_mahnung2_tage.value()),
            int(self.f_inkasso_tage.value()),
        ]
        if tage != sorted(tage):
            return "Die Mahnstufen-Tage müssen aufsteigend sein (z.B. 7, 21, 35, 49)."

        for lbl, feld in [
            ("Mahngebühr Erinnerung", self.f_cost_erinnerung),
            ("Mahngebühr Mahnung1",   self.f_cost_mahnung1),
            ("Mahngebühr Mahnung2",   self.f_cost_mahnung2),
            ("Mahngebühr Inkasso",    self.f_cost_inkasso),
        ]:
            try:
                val = float(feld.value().replace(",", "."))
                assert val >= 0
            except (ValueError, AssertionError):
                return f"{lbl}: Bitte einen gültigen Betrag eingeben."

        smtp_port = self.f_smtp_port.value()
        if smtp_port:
            try:
                p = int(smtp_port)
                assert 1 <= p <= 65535
            except (ValueError, AssertionError):
                return "SMTP-Port muss eine Zahl zwischen 1 und 65535 sein."

        return ""

    def _db_wechseln_lokal(self) -> None:
        pfad, _ = QFileDialog.getOpenFileName(
            self,
            "SQLite-Datenbankdatei öffnen",
            "",
            "SQLite-Datenbanken (*.db *.sqlite *.sqlite3);;Alle Dateien (*.*)",
        )
        if pfad:
            config.set("database", "mode", "local")
            config.set("database", "path", pfad)
            try:
                config.save()
                self._banner.show_warning(
                    f"Datenbank gewechselt auf: {pfad}\n"
                    "Bitte die Anwendung neu starten.",
                    timeout_ms=0,
                )
            except Exception as e:
                self._banner.show_error(f"Fehler: {e}")

    # ------------------------------------------------------------------
    # Hilfsmethoden
    # ------------------------------------------------------------------

    def _test_smtp(self) -> None:
        """Testet die SMTP-Verbindung mit den aktuell eingetragenen Werten."""
        import smtplib
        from PySide6.QtWidgets import QInputDialog

        server_host = self.f_smtp_server.value().strip()
        port_str    = self.f_smtp_port.value().strip()
        user        = self.f_smtp_user.value().strip()
        password    = self.f_smtp_password.value().strip()
        if not password:
            from core.services.credential_service import passwort_laden
            password = passwort_laden()
        encryption  = self._smtp_enc_combo.currentText().upper()

        if not server_host:
            self._smtp_test_lbl.setStyleSheet(f"color: {Colors.WARNING};")
            self._smtp_test_lbl.setText("⚠  Kein SMTP-Server eingetragen.")
            return
        if not user:
            self._smtp_test_lbl.setStyleSheet(f"color: {Colors.WARNING};")
            self._smtp_test_lbl.setText("⚠  Kein Benutzername eingetragen.")
            return

        try:
            port = int(port_str) if port_str else 587
        except ValueError:
            self._smtp_test_lbl.setStyleSheet(f"color: {Colors.ERROR};")
            self._smtp_test_lbl.setText("✗  Ungültiger Port.")
            return

        # Passwort ggf. abfragen
        if not password:
            from PySide6.QtWidgets import QLineEdit
            pw, ok = QInputDialog.getText(
                self, "SMTP-Passwort",
                f"Passwort für '{user}':",
                QLineEdit.EchoMode.Password,
            )
            if not ok or not pw:
                self._smtp_test_lbl.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
                self._smtp_test_lbl.setText("Abgebrochen.")
                return
            password = pw

        self._smtp_test_btn.setEnabled(False)
        self._smtp_test_btn.setText("Verbinde …")
        self._smtp_test_lbl.setText("")

        try:
            if encryption == "SSL/TLS":
                server = smtplib.SMTP_SSL(server_host, port, timeout=10)
            else:
                server = smtplib.SMTP(server_host, port, timeout=10)
                if encryption == "STARTTLS":
                    server.starttls()

            server.login(user, password)
            server.quit()

            self._smtp_test_lbl.setStyleSheet(f"color: {Colors.SUCCESS};")
            self._smtp_test_lbl.setText(
                f"✓  Verbindung erfolgreich! ({server_host}:{port}, {encryption})"
            )

        except smtplib.SMTPAuthenticationError:
            self._smtp_test_lbl.setStyleSheet(f"color: {Colors.ERROR};")
            self._smtp_test_lbl.setText(
                "✗  Authentifizierung fehlgeschlagen. Benutzername/Passwort prüfen.\n"
                "   Microsoft-Nutzer: Bitte ein App-Passwort verwenden."
            )
        except smtplib.SMTPConnectError as e:
            self._smtp_test_lbl.setStyleSheet(f"color: {Colors.ERROR};")
            self._smtp_test_lbl.setText(f"✗  Verbindung fehlgeschlagen: {e}")
        except OSError as e:
            self._smtp_test_lbl.setStyleSheet(f"color: {Colors.ERROR};")
            self._smtp_test_lbl.setText(f"✗  Netzwerkfehler: {e}")
        except Exception as e:
            self._smtp_test_lbl.setStyleSheet(f"color: {Colors.ERROR};")
            self._smtp_test_lbl.setText(f"✗  Fehler: {e}")
        finally:
            self._smtp_test_btn.setEnabled(True)
            self._smtp_test_btn.setText("Verbindung testen")

    def _scroll_tab(self) -> tuple[QWidget, QVBoxLayout]:
        """Erstellt ein scrollbares Tab-Widget und gibt (tab, inner_layout) zurück."""
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")

        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(Spacing.XL, Spacing.LG, Spacing.XL, Spacing.LG)
        layout.setSpacing(Spacing.SM)
        scroll.setWidget(inner)
        outer.addWidget(scroll)

        return tab, layout


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _info(text: str) -> QLabel:
    """Erstellt ein Info-Label mit gedämpfter Schrift."""
    lbl = QLabel(text)
    lbl.setFont(Fonts.caption())
    lbl.setStyleSheet(
        f"color: {Colors.TEXT_SECONDARY}; "
        f"background-color: {Colors.BG_ELEVATED}; "
        f"border-radius: {Radius.SM}px; "
        f"padding: {Spacing.SM}px {Spacing.MD}px;"
    )
    lbl.setWordWrap(True)
    return lbl
