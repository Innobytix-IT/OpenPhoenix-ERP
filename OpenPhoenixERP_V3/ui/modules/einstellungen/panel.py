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
    QMessageBox, QProgressDialog, QApplication,
)

from core.config import config
from core.services.backup_service import (
    erstelle_backup, vorgeschlagener_dateiname, BackupError,
    restore_backup, validiere_backup, RestoreError,
)
from core.services.platzhalter_service import (
    load_vorlagen, save_vorlagen, reset_vorlage,
    load_custom_placeholders, save_custom_placeholders,
    BUILTIN_PLACEHOLDERS, DEFAULT_VORLAGEN,
)
from ui.components.widgets import FormField, SectionTitle, NotificationBanner
from ui.theme.theme import Colors, Fonts, Spacing, Radius, on_theme_changed

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
        self._styled_widgets: list = []
        self._build_ui()
        self._laden()
        on_theme_changed(self._on_theme_changed)

    def _on_theme_changed(self, _mode: str) -> None:
        """Aktualisiert inline Styles nach Theme-Wechsel (ohne Datenverlust)."""
        for widget, style_fn in self._styled_widgets:
            widget.setStyleSheet(style_fn())

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
        bw.setContentsMargins(Spacing.XXL, Spacing.SM, Spacing.XXL, 0)
        self._banner = NotificationBanner()
        bw.addWidget(self._banner)
        root.addWidget(banner_wrap)

        self._tabs = QTabWidget()
        _tabs_style = lambda: f"""
            QTabWidget::pane {{
                background-color: {Colors.BG_APP};
                border: none;
            }}
            QTabBar {{
                background: transparent;
            }}
            QTabBar::tab {{
                background: transparent;
                color: {Colors.TEXT_SECONDARY};
                padding: 12px 22px;
                margin-right: 4px;
                border-bottom: 3px solid transparent;
                font-size: {Fonts.SIZE_BASE}pt;
                font-weight: 600;
            }}
            QTabBar::tab:selected {{
                color: {Colors.PRIMARY};
                border-bottom: 3px solid {Colors.PRIMARY};
            }}
            QTabBar::tab:hover:!selected {{
                color: {Colors.TEXT_PRIMARY};
                background-color: {Colors.BG_ELEVATED};
                border-radius: {Radius.SM}px {Radius.SM}px 0 0;
            }}
        """
        self._tabs.setStyleSheet(_tabs_style())
        self._styled_widgets.append((self._tabs, _tabs_style))

        self._tabs.addTab(self._build_firma_tab(),      "🏢  Firma")
        self._tabs.addTab(self._build_rechnung_tab(),   "🧾  Rechnungen")
        self._tabs.addTab(self._build_mahnwesen_tab(),  "📨  Mahnwesen")
        self._tabs.addTab(self._build_email_tab(),      "📧  E-Mail")
        self._tabs.addTab(self._build_vorlagen_tab(),   "📝  Textvorlagen")
        self._tabs.addTab(self._build_pfade_tab(),      "📁  Pfade")
        self._tabs.addTab(self._build_datenbank_tab(),  "🗄  Datenbank")

        root.addWidget(self._tabs, 1)
        root.addWidget(self._build_footer())

    def _build_header(self) -> QWidget:
        wrapper = QWidget()
        wrapper.setObjectName("einstellungenHeaderWrap")
        wrapper_layout = QVBoxLayout(wrapper)
        wrapper_layout.setContentsMargins(0, 0, 0, 0)
        wrapper_layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("einstellungenHeader")
        header.setFixedHeight(68)
        _hdr_style = lambda: f"""
            #einstellungenHeader {{
                background-color: {Colors.BG_SURFACE};
                border-bottom: 1px solid {Colors.BORDER};
            }}
        """
        header.setStyleSheet(_hdr_style())
        self._styled_widgets.append((header, _hdr_style))
        layout = QHBoxLayout(header)
        layout.setContentsMargins(Spacing.XXL, 0, Spacing.XXL, 0)

        icon = QLabel("⚙️")
        icon.setStyleSheet("font-size: 24px; background: transparent;")
        title = QLabel("Einstellungen")
        title.setFont(Fonts.heading2())
        _title_style = lambda: f"color: {Colors.TEXT_PRIMARY}; background: transparent;"
        title.setStyleSheet(_title_style())
        self._styled_widgets.append((title, _title_style))

        subtitle = QLabel("Programmkonfiguration und Systemeinstellungen")
        subtitle.setFont(Fonts.caption())
        _sub_style = lambda: f"color: {Colors.TEXT_SECONDARY}; background: transparent;"
        subtitle.setStyleSheet(_sub_style())
        self._styled_widgets.append((subtitle, _sub_style))

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        text_col.addWidget(title)
        text_col.addWidget(subtitle)

        layout.addWidget(icon)
        layout.addSpacing(Spacing.MD)
        layout.addLayout(text_col)
        layout.addStretch()

        # Akzentlinie unter dem Header
        accent = QFrame()
        accent.setFixedHeight(3)
        _accent_style = lambda: f"background-color: {Colors.PRIMARY};"
        accent.setStyleSheet(_accent_style())
        self._styled_widgets.append((accent, _accent_style))

        wrapper_layout.addWidget(header)
        wrapper_layout.addWidget(accent)
        return wrapper

    def _build_footer(self) -> QFrame:
        footer = QFrame()
        footer.setObjectName("einstellungenFooter")
        footer.setFixedHeight(60)
        _ftr_style = lambda: f"""
            #einstellungenFooter {{
                background-color: {Colors.BG_SURFACE};
                border-top: 2px solid {Colors.BORDER};
            }}
        """
        footer.setStyleSheet(_ftr_style())
        self._styled_widgets.append((footer, _ftr_style))
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(Spacing.XXL, 0, Spacing.XXL, 0)
        layout.setSpacing(Spacing.MD)

        hint = QLabel('Änderungen werden erst beim Klick auf „Speichern" übernommen.')
        hint.setFont(Fonts.caption())
        _hint_style = lambda: f"color: {Colors.TEXT_DISABLED}; font-style: italic;"
        hint.setStyleSheet(_hint_style())
        self._styled_widgets.append((hint, _hint_style))
        layout.addWidget(hint)
        layout.addStretch()

        save_btn = QPushButton("💾  Speichern")
        save_btn.setMinimumWidth(150)
        save_btn.clicked.connect(self._speichern)
        save_btn.setDefault(True)
        layout.addWidget(save_btn)

        return footer

    # ------------------------------------------------------------------
    # Tab: Firma
    # ------------------------------------------------------------------

    def _build_firma_tab(self) -> QWidget:
        tab, layout = self._scroll_tab()

        # ── Karte: Unternehmensangaben ──
        card1, cl1 = self._make_card("Unternehmensangaben", "🏢")
        cl1.addWidget(
            _info("Diese Daten erscheinen auf Rechnungen und Mahnschreiben.")
        )

        self.f_firma_name = FormField(
            "Firmenname *", placeholder="Muster GmbH", max_length=200
        )
        cl1.addWidget(self.f_firma_name)

        self.f_firma_strasse = FormField(
            "Straße & Hausnummer", placeholder="Musterstraße 1", max_length=200
        )
        cl1.addWidget(self.f_firma_strasse)

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
        cl1.addLayout(row2)

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
        cl1.addLayout(row3)
        layout.addWidget(card1)

        # ── Karte: Steuer & Bank ──
        card2, cl2 = self._make_card("Steuer & Bankverbindung", "🏦")
        self.f_firma_steuernr = FormField(
            "Steuernummer / USt-ID",
            placeholder="DE123456789 oder 123/456/78901",
            max_length=50,
        )
        cl2.addWidget(self.f_firma_steuernr)

        self.f_firma_bank = FormField(
            "Bankverbindung (erscheint auf Rechnung)",
            placeholder="IBAN: DE00 1234 … | BIC: XXXXDEXX | Bank AG",
            max_length=300,
        )
        cl2.addWidget(self.f_firma_bank)
        layout.addWidget(card2)

        # ── Karte: XRechnung ──
        card3, cl3 = self._make_card("XRechnung / E-Rechnung", "📄")
        cl3.addWidget(
            _info(
                "Elektronische Adresse für XRechnung (BT-34, Pflichtfeld). "
                "Leitweg-ID für Rechnungen an Behörden (z.B. 04011000-1234561234-56). "
                "Wenn leer, wird automatisch die E-Mail-Adresse verwendet."
            )
        )
        self.f_firma_leitweg = FormField(
            "Leitweg-ID (optional, nur für Behörden)",
            placeholder="z.B. 04011000-1234561234-56",
            max_length=100,
        )
        cl3.addWidget(self.f_firma_leitweg)
        layout.addWidget(card3)

        layout.addStretch()
        return tab

    # ------------------------------------------------------------------
    # Tab: Rechnungen
    # ------------------------------------------------------------------

    def _build_rechnung_tab(self) -> QWidget:
        tab, layout = self._scroll_tab()

        # ── Karte: Mehrwertsteuer ──
        card1, cl1 = self._make_card("Mehrwertsteuer", "💰")
        cl1.addWidget(
            _info(
                "Definieren Sie zwei MwSt-Sätze, die bei der Rechnungsstellung "
                "zur Auswahl stehen. Zusätzlich steht immer '0 % (steuerfrei)' "
                "zur Verfügung. Der Regelsteuersatz wird als Vorauswahl verwendet."
            )
        )

        row_mwst = QHBoxLayout()
        row_mwst.setSpacing(Spacing.MD)
        self.f_mwst = FormField(
            "Regelsteuersatz (%)", placeholder="19", max_length=5
        )
        self.f_mwst.setFixedWidth(200)
        self.f_mwst_ermaessigt = FormField(
            "Ermäßigter Satz (%)", placeholder="7", max_length=5
        )
        self.f_mwst_ermaessigt.setFixedWidth(200)
        row_mwst.addWidget(self.f_mwst)
        row_mwst.addWidget(self.f_mwst_ermaessigt)
        row_mwst.addStretch()
        cl1.addLayout(row_mwst)
        layout.addWidget(card1)

        # ── Karte: Zahlungsziel ──
        card2, cl2 = self._make_card("Zahlungsziel", "📅")

        row1 = QHBoxLayout()
        row1.setSpacing(Spacing.MD)
        self.f_zahlungsziel = FormField(
            "Zahlungsziel (Tage)", placeholder="14", max_length=4
        )
        self.f_zahlungsziel.setFixedWidth(200)
        row1.addWidget(self.f_zahlungsziel)
        row1.addStretch()
        cl2.addLayout(row1)
        layout.addWidget(card2)

        # ── Karte: Rechnungsnummer ──
        card3, cl3 = self._make_card("Rechnungsnummer-Format", "🔢")
        cl3.addWidget(
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
        cl3.addWidget(self.f_nummer_format)
        layout.addWidget(card3)

        layout.addStretch()
        return tab

    # ------------------------------------------------------------------
    # Tab: Mahnwesen
    # ------------------------------------------------------------------

    def _build_mahnwesen_tab(self) -> QWidget:
        tab, layout = self._scroll_tab()

        # ── Karte: Fristen ──
        card1, cl1 = self._make_card("Mahnstufen-Fristen (Tage nach Fälligkeit)", "⏱")
        cl1.addWidget(
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
        cl1.addLayout(grid)
        layout.addWidget(card1)

        # ── Karte: Gebühren ──
        card2, cl2 = self._make_card("Mahngebühren (€)", "💶")
        cl2.addWidget(
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
        cl2.addLayout(fees)
        layout.addWidget(card2)

        layout.addStretch()
        return tab

    # ------------------------------------------------------------------
    # Tab: E-Mail
    # ------------------------------------------------------------------

    def _build_email_tab(self) -> QWidget:
        tab, layout = self._scroll_tab()

        # ── Karte: SMTP ──
        card1, cl1 = self._make_card("SMTP-Konfiguration", "📧")
        cl1.addWidget(
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
        cl1.addLayout(row1)

        self.f_smtp_user = FormField(
            "Benutzername / E-Mail",
            placeholder="absender@beispiel.de",
            max_length=200,
        )
        cl1.addWidget(self.f_smtp_user)

        self.f_smtp_password = FormField(
            "Passwort", placeholder="••••••••", max_length=200
        )
        # Passwortfeld: Eingabe verbergen
        self.f_smtp_password._input.setEchoMode(
            self.f_smtp_password._input.EchoMode.Password
        )
        cl1.addWidget(self.f_smtp_password)
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
        cl1.addWidget(self._smtp_sicher_lbl)

        # Verschlüsselung innerhalb der Karte
        enc_sep = QFrame()
        enc_sep.setFixedHeight(1)
        enc_sep.setStyleSheet(f"background-color: {Colors.BORDER};")
        cl1.addWidget(enc_sep)

        enc_title = QLabel("Verschlüsselung")
        enc_title.setFont(Fonts.get(Fonts.SIZE_SM, bold=True))
        enc_title.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; background: transparent;")
        cl1.addWidget(enc_title)

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
        cl1.addLayout(enc_row)
        layout.addWidget(card1)

        # ── Karte: Verbindungstest ──
        card_test, cl_test = self._make_card("Verbindungstest", "🔌")
        test_row = QHBoxLayout()
        self._smtp_test_btn = QPushButton("🔍  Verbindung testen")
        self._smtp_test_btn.setProperty("role", "secondary")
        self._smtp_test_btn.setMinimumWidth(200)
        self._smtp_test_btn.setMinimumHeight(40)
        self._smtp_test_btn.clicked.connect(self._test_smtp)
        self._smtp_test_lbl = QLabel("")
        self._smtp_test_lbl.setFont(Fonts.caption())
        self._smtp_test_lbl.setWordWrap(True)
        test_row.addWidget(self._smtp_test_btn)
        test_row.addWidget(self._smtp_test_lbl, 1)
        test_row.addStretch()
        cl_test.addLayout(test_row)
        layout.addWidget(card_test)

        # ── Karte: Hinweise ──
        card_hints, cl_hints = self._make_card("Provider-Hinweise", "💡")
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
            cl_hints.addWidget(lbl)
        layout.addWidget(card_hints)

        layout.addStretch()
        return tab

    # ------------------------------------------------------------------
    # Tab: Pfade
    # ------------------------------------------------------------------

    def _build_pfade_tab(self) -> QWidget:
        tab, layout = self._scroll_tab()

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

        # ── Karte: Kundendokumente ──
        card1, cl1 = self._make_card("Kundendokumente", "📂")
        cl1.addWidget(
            _info("Alle Pfade können leer gelassen werden — "
                  "die entsprechenden Funktionen sind dann deaktiviert.")
        )
        self.f_pfad_dokumente, row_dok = pfad_zeile(
            "Kundendokumente",
            "z.B. C:/Firma/Kundendokumente",
        )
        cl1.addLayout(row_dok)
        layout.addWidget(card1)

        # ── Karte: Belege ──
        card2, cl2 = self._make_card("Eingangsrechnungen / Belege", "🧾")
        cl2.addWidget(
            _info(
                "Basispfad für die Ablage von Eingangsrechnungen und Belegen. "
                "Unterordner werden automatisch als Kategorien erkannt — "
                "legen Sie z.B. Ordner wie 'Material', 'Kraftstoff', 'Miete' an. "
                "Belege werden in der Struktur Kategorie/JJJJ/MM/ gespeichert."
            )
        )
        self.f_pfad_belege, row_belege = pfad_zeile(
            "Belege-Ordner",
            "z.B. C:/Firma/Belege",
        )
        cl2.addLayout(row_belege)
        layout.addWidget(card2)

        # ── Karte: Rechnungs-PDF ──
        card3, cl3 = self._make_card("Rechnungs-PDF / Briefpapier", "🖨")
        cl3.addWidget(
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
        cl3.addLayout(bg_row)
        layout.addWidget(card3)

        layout.addStretch()
        return tab

    # ------------------------------------------------------------------
    # Tab: Textvorlagen & Platzhalter
    # ------------------------------------------------------------------

    def _build_vorlagen_tab(self) -> QWidget:
        tab = QWidget()
        root_layout = QVBoxLayout(tab)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ── Unter-Tabs: Vorlagen | Eigene Platzhalter ──
        sub_tabs = QTabWidget()
        sub_tabs.setStyleSheet(
            f"QTabWidget::pane {{ border: none; }}"
            f"QTabBar::tab {{ padding: 8px 20px; font-size: {Fonts.SIZE_SM}pt; }}"
            f"QTabBar::tab:selected {{ color: {Colors.PRIMARY}; "
            f"border-bottom: 2px solid {Colors.PRIMARY}; font-weight: bold; }}"
        )

        # ══════════════════════════════════════════════════════════════
        # SUB-TAB 1: Vorlagen bearbeiten
        # ══════════════════════════════════════════════════════════════
        tab_editor = QWidget()
        editor_root = QVBoxLayout(tab_editor)
        editor_root.setContentsMargins(Spacing.XXL, Spacing.XL, Spacing.XXL, Spacing.XL)
        editor_root.setSpacing(Spacing.MD)

        editor_root.addWidget(_info(
            "Bearbeiten Sie Texte für Rechnungshinweis, Mahnschreiben und E-Mails. "
            "Platzhalter wie {{RECHNUNGSNUMMER}} werden beim Erstellen automatisch ersetzt."
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
        lbl_sel.setFont(Fonts.get(Fonts.SIZE_SM, bold=True))
        lbl_sel.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        lbl_sel.setFixedWidth(70)
        self._vorlage_combo = QComboBox()
        self._vorlage_combo.addItems(list(vorlage_keys.keys()))
        self._vorlage_combo.setMinimumHeight(38)
        sel_row.addWidget(lbl_sel)
        sel_row.addWidget(self._vorlage_combo, 1)
        editor_root.addLayout(sel_row)

        # Splitter: Texteditor links | Platzhalter-Auswahl rechts
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # ── Linke Seite: Editor ────────────────────────────────────────
        editor_widget = QWidget()
        editor_layout = QVBoxLayout(editor_widget)
        editor_layout.setContentsMargins(0, 0, Spacing.SM, 0)
        editor_layout.setSpacing(Spacing.XS if hasattr(Spacing, "XS") else 4)

        self._vorlage_editor = QTextEdit()
        self._vorlage_editor.setPlaceholderText("Vorlage oben auswählen …")
        self._vorlage_editor.setStyleSheet(
            f"background: {Colors.BG_ELEVATED}; "
            f"color: {Colors.TEXT_PRIMARY}; "
            f"border: 1px solid {Colors.BORDER}; "
            f"border-radius: {Radius.SM}px; "
            f"padding: 10px; font-family: monospace; font-size: {Fonts.SIZE_BASE}pt;"
        )
        editor_layout.addWidget(self._vorlage_editor, 1)

        btn_editor_row = QHBoxLayout()
        btn_save_vorlage = QPushButton("💾  Speichern")
        btn_save_vorlage.setProperty("role", "primary")
        btn_save_vorlage.setFixedHeight(38)
        btn_save_vorlage.setMinimumWidth(130)
        btn_reset_vorlage = QPushButton("↩  Standard")
        btn_reset_vorlage.setProperty("role", "secondary")
        btn_reset_vorlage.setFixedHeight(38)
        btn_reset_vorlage.setMinimumWidth(130)
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
        ph_lbl.setFont(Fonts.get(Fonts.SIZE_SM, bold=True))
        ph_lbl.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        ph_layout.addWidget(ph_lbl)

        self._ph_list = QListWidget()
        self._ph_list.setAlternatingRowColors(True)
        self._ph_list.setStyleSheet(
            f"QListWidget {{ background: {Colors.BG_ELEVATED}; "
            f"border: 1px solid {Colors.BORDER}; border-radius: {Radius.SM}px; }}"
            f"QListWidget::item {{ padding: 4px 8px; font-size: 11px; }}"
            f"QListWidget::item:selected {{ background: {Colors.PRIMARY}; color: white; }}"
        )
        ph_layout.addWidget(self._ph_list, 1)

        btn_insert = QPushButton("✓  In Text einfügen")
        btn_insert.setProperty("role", "secondary")
        btn_insert.setFixedHeight(36)
        ph_layout.addWidget(btn_insert)
        splitter.addWidget(ph_widget)
        splitter.setSizes([520, 200])
        editor_root.addWidget(splitter, 1)

        sub_tabs.addTab(tab_editor, "📝  Vorlagen bearbeiten")

        # ══════════════════════════════════════════════════════════════
        # SUB-TAB 2: Eigene Platzhalter
        # ══════════════════════════════════════════════════════════════
        tab_ph = QWidget()
        ph_root = QVBoxLayout(tab_ph)
        ph_root.setContentsMargins(Spacing.XXL, Spacing.XL, Spacing.XXL, Spacing.XL)
        ph_root.setSpacing(Spacing.MD)

        ph_root.addWidget(_info(
            "Definieren Sie eigene statische Platzhalter, z.B. {{SACHBEARBEITER}} = 'Max Muster'. "
            "Sie erscheinen in der Platzhalter-Liste im Editor und können in allen Vorlagen "
            "verwendet werden."
        ))

        add_row = QHBoxLayout()
        add_row.setSpacing(Spacing.MD)
        self._new_ph_key   = FormField("Name (ohne {{}})", placeholder="MEIN_PLATZHALTER", max_length=50)
        self._new_ph_value = FormField("Wert", placeholder="Beliebiger Text", max_length=200)
        btn_add_ph = QPushButton("➕  Hinzufügen")
        btn_add_ph.setProperty("role", "secondary")
        btn_add_ph.setFixedHeight(38)
        btn_add_ph.setMinimumWidth(140)
        add_row.addWidget(self._new_ph_key, 1)
        add_row.addWidget(self._new_ph_value, 2)
        add_row.addWidget(btn_add_ph)
        ph_root.addLayout(add_row)

        self._custom_ph_list = QListWidget()
        self._custom_ph_list.setAlternatingRowColors(True)
        self._custom_ph_list.setStyleSheet(
            f"QListWidget {{ background: {Colors.BG_ELEVATED}; "
            f"border: 1px solid {Colors.BORDER}; border-radius: {Radius.SM}px; }}"
            f"QListWidget::item {{ padding: 6px 10px; font-size: {Fonts.SIZE_SM}pt; }}"
            f"QListWidget::item:selected {{ background: {Colors.PRIMARY}; color: white; }}"
        )
        ph_root.addWidget(self._custom_ph_list, 1)

        btn_del_ph = QPushButton("🗑  Ausgewählten löschen")
        btn_del_ph.setProperty("role", "danger")
        btn_del_ph.setMaximumWidth(240)
        btn_del_ph.setFixedHeight(36)
        ph_root.addWidget(btn_del_ph)

        sub_tabs.addTab(tab_ph, "🏷  Eigene Platzhalter")
        root_layout.addWidget(sub_tabs)

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
        # System-Platzhalter dürfen nicht überschrieben werden
        from core.services.platzhalter_service import BUILTIN_PLACEHOLDERS
        if key in BUILTIN_PLACEHOLDERS:
            self._banner.show_warning(
                f"'{key}' ist ein reservierter System-Platzhalter und kann nicht überschrieben werden."
            )
            return
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

        modus = "Lokale SQLite-Datenbank" if config.is_local_db() else "PostgreSQL-Server"

        # ── Karte: Aktueller Modus ──
        card1, cl1 = self._make_card("Aktueller Modus", "🗂")
        modus_lbl = QLabel(f"{'🗂' if config.is_local_db() else '🖧'}  {modus}")
        modus_lbl.setFont(Fonts.get(Fonts.SIZE_MD, bold=True))
        modus_lbl.setStyleSheet(
            f"color: {Colors.SUCCESS if config.is_local_db() else Colors.INFO};"
        )
        cl1.addWidget(modus_lbl)

        if config.is_local_db():
            db_path = config.get("database", "path", "openphoenix.db")
            path_lbl = QLabel(f"📍  Datei: {db_path}")
            path_lbl.setFont(Fonts.caption())
            path_lbl.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
            cl1.addWidget(path_lbl)

        btn_row = QHBoxLayout()
        btn_local = QPushButton("🗂  Lokale SQLite-Datei öffnen")
        btn_local.setProperty("role", "secondary")
        btn_local.setMinimumHeight(38)
        btn_local.clicked.connect(self._db_wechseln_lokal)
        btn_row.addWidget(btn_local)
        btn_row.addStretch()
        cl1.addLayout(btn_row)

        cl1.addWidget(
            _info(
                "⚠  Beim Wechsel der Datenbank wird die Anwendung neu gestartet. "
                "Alle nicht gespeicherten Daten gehen verloren."
            )
        )
        layout.addWidget(card1)

        # ── Karte: Backup ──
        card2, cl2 = self._make_card("Backup & Wiederherstellung", "💾")
        cl2.addWidget(
            _info(
                "Erstellt ein ZIP-Archiv mit Datenbank, config.toml, "
                "Kundendokumenten und Belegen. Bei PostgreSQL wird die "
                "Datenbank nicht einbezogen — nutzen Sie dafür pg_dump."
            )
        )

        backup_row = QHBoxLayout()
        backup_row.setSpacing(Spacing.MD)

        self._btn_backup = QPushButton("💾  Komplettes Backup erstellen")
        self._btn_backup.setMinimumHeight(44)
        self._btn_backup.setMinimumWidth(260)
        self._btn_backup.clicked.connect(self._backup_erstellen)
        backup_row.addWidget(self._btn_backup)

        self._btn_restore = QPushButton("📂  Backup wiederherstellen")
        self._btn_restore.setMinimumHeight(44)
        self._btn_restore.setMinimumWidth(260)
        self._btn_restore.setProperty("role", "secondary")
        self._btn_restore.clicked.connect(self._backup_wiederherstellen)
        backup_row.addWidget(self._btn_restore)

        backup_row.addStretch()
        cl2.addLayout(backup_row)
        layout.addWidget(card2)

        # ── Karte: System-Info ──
        card3, cl3 = self._make_card("System-Informationen", "ℹ️")
        infos = [
            ("Version",       "OpenPhoenix ERP v3.0.0"),
            ("Datenbank",     modus),
            ("Python",        __import__("sys").version.split()[0]),
            ("Lizenz",        "GPL v3"),
        ]
        for schluessel, wert in infos:
            row = QHBoxLayout()
            k_lbl = QLabel(schluessel)
            k_lbl.setFixedWidth(120)
            k_lbl.setFont(Fonts.get(Fonts.SIZE_SM, bold=True))
            k_lbl.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
            v_lbl = QLabel(wert)
            v_lbl.setFont(Fonts.get(Fonts.SIZE_SM))
            v_lbl.setStyleSheet(f"color: {Colors.TEXT_PRIMARY};")
            row.addWidget(k_lbl)
            row.addWidget(v_lbl)
            row.addStretch()
            cl3.addLayout(row)
        layout.addWidget(card3)

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
        self.f_firma_leitweg.set_value(c.get("company", "leitweg_id", ""))

        # Rechnungen
        self.f_mwst.set_value(str(c.get("invoice", "default_vat", 19)).replace(".", ","))
        self.f_mwst_ermaessigt.set_value(str(c.get("invoice", "reduced_vat", 7)).replace(".", ","))
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
        self.f_pfad_belege.set_value(c.get("paths", "belege", ""))
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
        c.set("company", "leitweg_id",  self.f_firma_leitweg.value())

        # Rechnungen
        c.set("invoice", "default_vat",    float(self.f_mwst.value().replace(",", ".")))
        c.set("invoice", "reduced_vat",   float(self.f_mwst_ermaessigt.value().replace(",", ".")))
        c.set("invoice", "payment_days",   int(self.f_zahlungsziel.value()))
        c.set("invoice", "number_format",  self.f_nummer_format.value())

        # Mahnwesen
        c.set("dunning", "reminder_days",   int(self.f_erinnerung_tage.value()))
        c.set("dunning", "mahnung1_days",   int(self.f_mahnung1_tage.value()))
        c.set("dunning", "mahnung2_days",   int(self.f_mahnung2_tage.value()))
        c.set("dunning", "inkasso_days",    int(self.f_inkasso_tage.value()))
        c.set("dunning", "cost_erinnerung", float(self.f_cost_erinnerung.value().replace(".", "").replace(",", ".")))
        c.set("dunning", "cost_mahnung1",   float(self.f_cost_mahnung1.value().replace(".", "").replace(",", ".")))
        c.set("dunning", "cost_mahnung2",   float(self.f_cost_mahnung2.value().replace(".", "").replace(",", ".")))
        c.set("dunning", "cost_inkasso",    float(self.f_cost_inkasso.value().replace(".", "").replace(",", ".")))

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
        c.set("paths", "belege",          self.f_pfad_belege.value())
        c.set("paths", "pdf_background",  self.f_pdf_bg.value())

        # Standard-Kategorie-Ordner anlegen wenn Belege-Pfad gesetzt
        belege_pfad = self.f_pfad_belege.value().strip()
        if belege_pfad:
            try:
                from pathlib import Path
                from core.services.belege_service import BelegKategorie
                BelegKategorie.standard_ordner_anlegen(Path(belege_pfad))
            except Exception as e:
                logger.warning(f"Konnte Belege-Ordner nicht anlegen: {e}")

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
            ("Regelsteuersatz", self.f_mwst),
            ("Ermäßigter Satz", self.f_mwst_ermaessigt),
            ("Zahlungsziel",    self.f_zahlungsziel),
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
                val = float(feld.value().replace(".", "").replace(",", "."))
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
    # Backup
    # ------------------------------------------------------------------

    def _backup_erstellen(self) -> None:
        """Öffnet Speichern-Dialog und erstellt ein komplettes Backup."""
        vorschlag = vorgeschlagener_dateiname()

        pfad, _ = QFileDialog.getSaveFileName(
            self,
            "Backup speichern unter",
            vorschlag,
            "ZIP-Archiv (*.zip)",
        )
        if not pfad:
            return  # Abgebrochen

        # Button deaktivieren während des Backups
        self._btn_backup.setEnabled(False)
        self._btn_backup.setText("⏳  Backup wird erstellt …")
        QApplication.processEvents()

        try:
            ergebnis = erstelle_backup(pfad)
            groesse_mb = ergebnis.stat().st_size / (1024 * 1024)
            self._banner.show_success(
                f"Backup erfolgreich erstellt!\n"
                f"📁 {ergebnis}\n"
                f"📦 Größe: {groesse_mb:.1f} MB",
                timeout_ms=10000,
            )
        except BackupError as e:
            self._banner.show_error(f"Backup fehlgeschlagen: {e}")
            logger.error(f"Backup fehlgeschlagen: {e}")
        except Exception as e:
            self._banner.show_error(f"Unerwarteter Fehler: {e}")
            logger.exception("Unerwarteter Fehler beim Backup")
        finally:
            self._btn_backup.setEnabled(True)
            self._btn_backup.setText("💾  Komplettes Backup erstellen")

    def _backup_wiederherstellen(self) -> None:
        """Öffnet ein Backup-ZIP und stellt es vollständig wieder her."""
        pfad, _ = QFileDialog.getOpenFileName(
            self,
            "Backup-Datei auswählen",
            "",
            "ZIP-Archiv (*.zip);;Alle Dateien (*.*)",
        )
        if not pfad:
            return

        # 1) Inhalt prüfen und dem Nutzer zeigen
        try:
            inhalt = validiere_backup(pfad)
        except RestoreError as e:
            self._banner.show_error(str(e))
            return

        # Zusammenfassung erstellen
        teile = []
        if inhalt["config"]:
            teile.append("config.toml")
        if inhalt["datenbank"]:
            teile.append("Datenbank (SQLite)")
        if inhalt["dokumente"]:
            teile.append("Kundendokumente")
        if inhalt["belege"]:
            teile.append("Belege")

        if not teile:
            self._banner.show_warning(
                "Das ZIP-Archiv enthält keine erkennbaren Backup-Daten."
            )
            return

        # 2) Sicherheitsabfrage
        antwort = QMessageBox.warning(
            self,
            "Backup wiederherstellen",
            f"Folgende Daten werden wiederhergestellt:\n\n"
            f"  • {'  • '.join(t + chr(10) for t in teile)}\n"
            f"⚠ Vorhandene Daten werden überschrieben!\n"
            f"(Ein Sicherheits-Backup wird automatisch erstellt.)\n\n"
            f"Fortfahren?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if antwort != QMessageBox.StandardButton.Yes:
            return

        # 3) Restore durchführen
        self._btn_restore.setEnabled(False)
        self._btn_restore.setText("⏳  Wird wiederhergestellt …")
        QApplication.processEvents()

        try:
            ergebnis = restore_backup(pfad)
            self._banner.show_success(
                f"Backup erfolgreich wiederhergestellt!\n"
                f"📦 {ergebnis.get('wiederhergestellt', '')}\n"
                f"🔒 Sicherheits-Backup: {ergebnis.get('sicherheits_backup', '–')}\n\n"
                f"Bitte starten Sie die Anwendung neu.",
                timeout_ms=0,  # Kein Auto-Hide
            )
        except RestoreError as e:
            self._banner.show_error(f"Wiederherstellung fehlgeschlagen:\n{e}")
            logger.error(f"Restore fehlgeschlagen: {e}")
        except Exception as e:
            self._banner.show_error(f"Unerwarteter Fehler:\n{e}")
            logger.exception("Unerwarteter Fehler beim Restore")
        finally:
            self._btn_restore.setEnabled(True)
            self._btn_restore.setText("📂  Backup wiederherstellen")

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
        scroll.setObjectName("settingsScroll")
        scroll.setStyleSheet("#settingsScroll { background: transparent; }")

        inner = QWidget()
        inner.setObjectName("settingsInner")
        inner.setStyleSheet("#settingsInner { background: transparent; }")
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(Spacing.XXL, Spacing.XL, Spacing.XXL, Spacing.XL)
        layout.setSpacing(Spacing.MD)
        scroll.setWidget(inner)
        outer.addWidget(scroll)

        return tab, layout

    def _make_card(self, title: str = "", icon: str = "") -> tuple[QFrame, QVBoxLayout]:
        """Erstellt eine Card (Surface-Container) mit optionalem Titel."""
        card = QFrame()
        card.setObjectName(f"card_{id(card)}")
        obj_name = card.objectName()
        _card_style = lambda on=obj_name: (
            f"#{on} {{"
            f"  background-color: {Colors.BG_SURFACE};"
            f"  border: 1px solid {Colors.BORDER};"
            f"  border-radius: {Radius.LG}px;"
            f"}}"
        )
        card.setStyleSheet(_card_style())
        self._styled_widgets.append((card, _card_style))

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(Spacing.XL, Spacing.LG, Spacing.XL, Spacing.LG)
        card_layout.setSpacing(Spacing.SM)

        if title:
            header_row = QHBoxLayout()
            header_row.setSpacing(Spacing.SM)
            if icon:
                icon_lbl = QLabel(icon)
                icon_lbl.setStyleSheet("font-size: 16px; background: transparent;")
                header_row.addWidget(icon_lbl)
            title_lbl = QLabel(title)
            title_lbl.setFont(Fonts.get(Fonts.SIZE_MD, bold=True))
            _title_s = lambda: f"color: {Colors.TEXT_PRIMARY}; background: transparent;"
            title_lbl.setStyleSheet(_title_s())
            self._styled_widgets.append((title_lbl, _title_s))
            header_row.addWidget(title_lbl)
            header_row.addStretch()
            card_layout.addLayout(header_row)

            # Trennlinie unter dem Titel
            sep = QFrame()
            sep.setFixedHeight(1)
            _sep_style = lambda: f"background-color: {Colors.BORDER};"
            sep.setStyleSheet(_sep_style())
            self._styled_widgets.append((sep, _sep_style))
            card_layout.addWidget(sep)
            card_layout.addSpacing(Spacing.XS)

        return card, card_layout


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _info(text: str) -> QFrame:
    """Erstellt eine Info-Box mit farbigem Akzent-Rand links."""
    box = QFrame()
    box.setStyleSheet(
        f"QFrame {{"
        f"  background-color: {Colors.INFO_BG};"
        f"  border-left: 3px solid {Colors.INFO};"
        f"  border-radius: {Radius.SM}px;"
        f"  padding: {Spacing.SM}px {Spacing.MD}px;"
        f"}}"
    )
    lay = QHBoxLayout(box)
    lay.setContentsMargins(Spacing.SM, Spacing.SM, Spacing.SM, Spacing.SM)
    lbl = QLabel(text)
    lbl.setFont(Fonts.caption())
    lbl.setStyleSheet(
        f"color: {Colors.TEXT_SECONDARY}; "
        f"background: transparent;"
    )
    lbl.setWordWrap(True)
    lay.addWidget(lbl)
    return box
