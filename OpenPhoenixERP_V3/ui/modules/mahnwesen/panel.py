"""
ui/modules/mahnwesen/panel.py – Mahnwesen-Übersicht
====================================================
Zeigt alle überfälligen Rechnungen geordnet nach Mahnstufe.
Stufenampel oben, detaillierte Tabelle unten, Direktaktionen.
"""

import logging
from decimal import Decimal
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QTabWidget, QMenu, QScrollArea, QSizePolicy,
)

from core.db.engine import db
from core.services.mahnwesen_service import (
    mahnwesen_service, MahnKonfig, MahnUebersicht, UeberfaelligeDTO,
)
from core.services.rechnungen_service import RechnungStatus
from ui.components.widgets import (
    DataTable, NotificationBanner, EmptyState, ConfirmDialog,
)
from ui.theme.theme import Colors, Fonts, Spacing, Radius, on_theme_changed

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------
# Farbkodierung
# -----------------------------------------------------------------------
STUFEN_FARBEN = {
    RechnungStatus.ERINNERUNG: Colors.WARNING,
    RechnungStatus.MAHNUNG1:   "#F97316",
    RechnungStatus.MAHNUNG2:   Colors.ERROR,
    RechnungStatus.INKASSO:    "#DC2626",
}
STUFEN_ICONS = {
    RechnungStatus.ERINNERUNG: "🔔",
    RechnungStatus.MAHNUNG1:   "⚠️",
    RechnungStatus.MAHNUNG2:   "🚨",
    RechnungStatus.INKASSO:    "⛔",
}


# -----------------------------------------------------------------------
# Ampel-Karte für eine Mahnstufe
# -----------------------------------------------------------------------

class MahnstufenKarte(QFrame):
    """Kompakte Übersichtskarte für eine Mahnstufe."""

    def __init__(self, stufe: str, parent=None):
        super().__init__(parent)
        self._stufe = stufe
        self._styled_widgets: list = []
        farbe = STUFEN_FARBEN.get(stufe, Colors.TEXT_SECONDARY)
        icon = STUFEN_ICONS.get(stufe, "📋")

        _frame_style = lambda: f"""
            QFrame {{
                background-color: {Colors.BG_SURFACE};
                border: 1px solid {Colors.BORDER};
                border-left: 4px solid {STUFEN_FARBEN.get(stufe, Colors.TEXT_SECONDARY)};
                border-radius: {Radius.MD}px;
            }}
        """
        self.setStyleSheet(_frame_style())
        self._styled_widgets.append((self, _frame_style))
        self.setMinimumWidth(190)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.LG, Spacing.MD, Spacing.LG, Spacing.MD)
        layout.setSpacing(4)

        header = QHBoxLayout()
        icon_lbl = QLabel(icon)
        icon_lbl.setStyleSheet("font-size: 18px; background: transparent;")
        title_lbl = QLabel(stufe)
        title_lbl.setFont(Fonts.get(Fonts.SIZE_SM, bold=True))
        title_lbl.setStyleSheet(f"color: {farbe}; background: transparent;")
        title_lbl.setWordWrap(True)
        header.addWidget(icon_lbl)
        header.addSpacing(Spacing.XS)
        header.addWidget(title_lbl, 1)
        layout.addLayout(header)

        self._anzahl_lbl = QLabel("0")
        self._anzahl_lbl.setFont(Fonts.get(Fonts.SIZE_2XL, bold=True))
        self._anzahl_lbl.setStyleSheet(f"color: {farbe}; background: transparent;")
        layout.addWidget(self._anzahl_lbl)

        self._betrag_lbl = QLabel("0,00 €")
        self._betrag_lbl.setFont(Fonts.caption())
        _betrag_style = lambda: f"color: {Colors.TEXT_SECONDARY}; background: transparent;"
        self._betrag_lbl.setStyleSheet(_betrag_style())
        self._styled_widgets.append((self._betrag_lbl, _betrag_style))
        layout.addWidget(self._betrag_lbl)

    def update_daten(self, anzahl: int, betrag: Decimal) -> None:
        self._anzahl_lbl.setText(str(anzahl))
        self._betrag_lbl.setText(_fmt(betrag))

    def refresh_styles(self) -> None:
        """Aktualisiert inline Styles nach Theme-Wechsel."""
        for widget, style_fn in self._styled_widgets:
            widget.setStyleSheet(style_fn())


# -----------------------------------------------------------------------
# Hauptpanel
# -----------------------------------------------------------------------

class MahnwesenPanel(QWidget):
    """
    Vollständiges Mahnwesen-Modul.
    Aktualisiert beim Öffnen automatisch alle Mahnstufen.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._uebersicht: Optional[MahnUebersicht] = None
        self._alle_dtos: list[UeberfaelligeDTO] = []
        self._styled_widgets: list = []
        self._build_ui()
        self._connect_signals()
        # Verzögerter Start: erst laden wenn das Widget sichtbar ist
        QTimer.singleShot(200, self._auto_aktualisieren)
        self._erste_anzeige = True
        on_theme_changed(self._on_theme_changed)

    def _on_theme_changed(self, _mode: str) -> None:
        for widget, style_fn in self._styled_widgets:
            widget.setStyleSheet(style_fn())
        # Karten aktualisieren
        for karte in self._karten.values():
            karte.refresh_styles()

    def showEvent(self, event) -> None:
        """Lädt Mahnwesen-Daten neu bei jedem Modul-Wechsel."""
        super().showEvent(event)
        if self._erste_anzeige:
            self._erste_anzeige = False  # Erster Load läuft via QTimer
        else:
            self._auto_aktualisieren()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())

        banner_wrap = QWidget()
        bw_layout = QVBoxLayout(banner_wrap)
        bw_layout.setContentsMargins(Spacing.XL, Spacing.SM, Spacing.XL, 0)
        self._banner = NotificationBanner()
        bw_layout.addWidget(self._banner)
        root.addWidget(banner_wrap)

        root.addWidget(self._build_ampel_row())

        self._tabs = QTabWidget()
        _tabs_style = lambda: f"""
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
        """
        self._tabs.setStyleSheet(_tabs_style())
        self._styled_widgets.append((self._tabs, _tabs_style))

        for stufe, icon, farbe in [
            (RechnungStatus.INKASSO,    "⛔", Colors.ERROR),
            (RechnungStatus.MAHNUNG2,   "🚨", "#F97316"),
            (RechnungStatus.MAHNUNG1,   "⚠️", Colors.WARNING),
            (RechnungStatus.ERINNERUNG, "🔔", Colors.INFO),
        ]:
            tab = self._build_stufen_tab(stufe)
            self._tabs.addTab(tab, f"{icon}  {stufe}")

        # Tab: Alle
        alle_tab = self._build_alle_tab()
        self._tabs.addTab(alle_tab, "📋  Alle überfälligen")

        # Tab: Bald fällig
        bald_tab = self._build_bald_tab()
        self._tabs.addTab(bald_tab, "📅  Bald fällig")

        root.addWidget(self._tabs, 1)

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("mahnwesenPanelHeader")
        header.setFixedHeight(64)
        _hdr_style = lambda: f"""
            #mahnwesenPanelHeader {{
                background-color: {Colors.BG_SURFACE};
                border-bottom: 1px solid {Colors.BORDER};
            }}
        """
        header.setStyleSheet(_hdr_style())
        self._styled_widgets.append((header, _hdr_style))
        layout = QHBoxLayout(header)
        layout.setContentsMargins(Spacing.XL, 0, Spacing.XL, 0)

        icon = QLabel("📨")
        icon.setStyleSheet("font-size: 22px; background: transparent;")
        title = QLabel("Mahnwesen")
        title.setFont(Fonts.heading2())
        _title_style = lambda: f"color: {Colors.TEXT_PRIMARY}; background: transparent;"
        title.setStyleSheet(_title_style())
        self._styled_widgets.append((title, _title_style))
        self._last_update_lbl = QLabel("")
        self._last_update_lbl.setFont(Fonts.caption())
        _update_lbl_style = lambda: f"color: {Colors.TEXT_DISABLED};"
        self._last_update_lbl.setStyleSheet(_update_lbl_style())
        self._styled_widgets.append((self._last_update_lbl, _update_lbl_style))

        layout.addWidget(icon)
        layout.addSpacing(Spacing.SM)
        layout.addWidget(title)
        layout.addSpacing(Spacing.MD)
        layout.addWidget(self._last_update_lbl)
        layout.addStretch()

        btn_refresh = QPushButton("↻  Jetzt prüfen")
        btn_refresh.setProperty("role", "secondary")
        btn_refresh.clicked.connect(self._auto_aktualisieren)
        layout.addWidget(btn_refresh)

        return header

    def _build_ampel_row(self) -> QWidget:
        row = QWidget()
        row.setObjectName("mahnwesenRow")
        _row_style = lambda: f"""
            #mahnwesenRow {{
                background-color: {Colors.BG_SURFACE};
                border-bottom: 1px solid {Colors.BORDER};
            }}
        """
        row.setStyleSheet(_row_style())
        self._styled_widgets.append((row, _row_style))
        layout = QHBoxLayout(row)
        layout.setContentsMargins(Spacing.XL, Spacing.MD, Spacing.XL, Spacing.MD)
        layout.setSpacing(Spacing.LG)

        self._karten: dict[str, MahnstufenKarte] = {}
        for stufe in [
            RechnungStatus.ERINNERUNG,
            RechnungStatus.MAHNUNG1,
            RechnungStatus.MAHNUNG2,
            RechnungStatus.INKASSO,
        ]:
            karte = MahnstufenKarte(stufe)
            self._karten[stufe] = karte
            layout.addWidget(karte)

        layout.addStretch()

        # Gesamtsummen-Karte
        summen_frame = QFrame()
        summen_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.BG_ELEVATED};
                border: 1px solid {Colors.BORDER};
                border-radius: {Radius.MD}px;
            }}
        """)
        sf_layout = QVBoxLayout(summen_frame)
        sf_layout.setContentsMargins(Spacing.LG, Spacing.MD, Spacing.LG, Spacing.MD)
        sf_layout.setSpacing(4)
        gesamt_title = QLabel("Gesamtforderung")
        gesamt_title.setFont(Fonts.get(Fonts.SIZE_SM, bold=True))
        gesamt_title.setStyleSheet(
            f"color: {Colors.TEXT_SECONDARY}; background: transparent;"
        )
        self._gesamt_betrag_lbl = QLabel("0,00 €")
        self._gesamt_betrag_lbl.setFont(
            Fonts.get(Fonts.SIZE_2XL, bold=True)
        )
        self._gesamt_betrag_lbl.setStyleSheet(
            f"color: {Colors.ERROR}; background: transparent;"
        )
        self._gesamt_anzahl_lbl = QLabel("0 Rechnungen")
        self._gesamt_anzahl_lbl.setFont(Fonts.caption())
        self._gesamt_anzahl_lbl.setStyleSheet(
            f"color: {Colors.TEXT_SECONDARY}; background: transparent;"
        )
        sf_layout.addWidget(gesamt_title)
        sf_layout.addWidget(self._gesamt_betrag_lbl)
        sf_layout.addWidget(self._gesamt_anzahl_lbl)
        layout.addWidget(summen_frame)

        return row

    def _build_stufen_tab(self, stufe: str) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(Spacing.XL, Spacing.MD, Spacing.XL, Spacing.MD)
        layout.setSpacing(Spacing.SM)

        table = DataTable(
            columns=[
                "ID", "Rechnungsnr.", "Fällig am",
                "Tage überf.", "Kunde", "Brutto", "Offen",
                "Mahngebühren", "Nächste Stufe"
            ],
            column_widths=[0, 130, 100, 90, 200, 110, 110, 110, 160],
            stretch_column=4,
            table_id=f"mahnung_stufe_{self._stufe_key(stufe)}",
        )
        table.setColumnHidden(0, True)
        table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table.customContextMenuRequested.connect(
            lambda pos, t=table, s=stufe: self._context_menu(pos, t, s)
        )
        layout.addWidget(table)

        setattr(self, f"_table_{self._stufe_key(stufe)}", table)
        return tab

    def _build_alle_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(Spacing.XL, Spacing.MD, Spacing.XL, Spacing.MD)
        layout.setSpacing(Spacing.SM)

        self._alle_table = DataTable(
            columns=[
                "ID", "Rechnungsnr.", "Fällig am", "Tage überf.",
                "Kunde", "Status", "Brutto", "Offen", "Mahngebühren"
            ],
            column_widths=[0, 130, 100, 90, 200, 180, 110, 110, 110],
            stretch_column=4,
                    table_id="mahnung_alle",
        )
        self._alle_table.setColumnHidden(0, True)
        self._alle_table.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._alle_table.customContextMenuRequested.connect(
            lambda pos: self._context_menu(pos, self._alle_table, None)
        )
        layout.addWidget(self._alle_table)
        return tab

    def _build_bald_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(Spacing.XL, Spacing.MD, Spacing.XL, Spacing.MD)
        layout.setSpacing(Spacing.SM)

        info = QLabel(
            "ℹ  Diese Rechnungen sind noch nicht überfällig, werden es aber "
            "in den nächsten 7 Tagen."
        )
        info.setFont(Fonts.caption())
        info.setStyleSheet(
            f"color: {Colors.TEXT_SECONDARY}; padding: 4px;"
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self._bald_table = DataTable(
            columns=[
                "ID", "Rechnungsnr.", "Fällig am",
                "Tage bis Fälligkeit", "Kunde", "Brutto", "Offen"
            ],
            column_widths=[0, 130, 100, 140, 220, 110, 110],
            stretch_column=4,
                    table_id="mahnung_bald",
        )
        self._bald_table.setColumnHidden(0, True)
        layout.addWidget(self._bald_table)
        return tab

    # ------------------------------------------------------------------
    # Signale
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        pass  # Tabs haben eigene Signale per lambda

    # ------------------------------------------------------------------
    # Daten laden
    # ------------------------------------------------------------------

    def _auto_aktualisieren(self) -> None:
        """Eskaliert Stufen + lädt Übersicht neu."""
        try:
            with db.session() as session:
                ergebnis = mahnwesen_service.pruefe_und_eskaliere(session)
                self._uebersicht = mahnwesen_service.uebersicht(session)
        except Exception as e:
            self._banner.show_error(f"Fehler beim Laden: {e}")
            logger.exception("Mahnwesen-Aktualisierung fehlgeschlagen:")
            return

        self._refresh_ui()

        eskaliert = ergebnis["eskaliert"]
        if eskaliert:
            self._banner.show_warning(
                f"{eskaliert} Rechnung{'en' if eskaliert != 1 else ''} "
                f"automatisch eskaliert.",
                timeout_ms=6000,
            )

        from datetime import datetime
        self._last_update_lbl.setText(
            f"Zuletzt geprüft: {datetime.now().strftime('%H:%M:%S')}"
        )

    def _refresh_ui(self) -> None:
        if not self._uebersicht:
            return

        ueb = self._uebersicht
        stats = ueb.statistik

        # Ampel-Karten
        for stufe, key in [
            (RechnungStatus.ERINNERUNG, "erinnerung"),
            (RechnungStatus.MAHNUNG1,   "mahnung1"),
            (RechnungStatus.MAHNUNG2,   "mahnung2"),
            (RechnungStatus.INKASSO,    "inkasso"),
        ]:
            dtos = getattr(ueb, key)
            betrag = sum(d.gesamtforderung for d in dtos)
            self._karten[stufe].update_daten(len(dtos), betrag)

        self._gesamt_betrag_lbl.setText(_fmt(stats["betrag"]))
        n = stats["gesamt"]
        self._gesamt_anzahl_lbl.setText(
            f"{n} Rechnung{'en' if n != 1 else ''}"
        )

        # Stufen-Tabellen
        for stufe, key in [
            (RechnungStatus.ERINNERUNG, "erinnerung"),
            (RechnungStatus.MAHNUNG1,   "mahnung1"),
            (RechnungStatus.MAHNUNG2,   "mahnung2"),
            (RechnungStatus.INKASSO,    "inkasso"),
        ]:
            dtos = getattr(ueb, key)
            table = getattr(self, f"_table_{self._stufe_key(stufe)}")
            rows, colors = self._dtos_to_rows_stufe(dtos)
            table.set_data(rows)
            for row, color in colors.items():
                table.set_row_color(row, color)

        # Alle-Tabelle
        self._alle_dtos = ueb.alle
        rows, colors = self._dtos_to_rows_alle(self._alle_dtos)
        self._alle_table.set_data(rows)
        for row, color in colors.items():
            self._alle_table.set_row_color(row, color)

        # Bald-fällig-Tabelle
        bald_rows = []
        for dto in ueb.bald_faellig:
            tage = abs(dto.tage_ueberfaellig)
            bald_rows.append([
                dto.rechnung_id,
                dto.rechnungsnummer,
                dto.faelligkeitsdatum,
                f"in {tage} Tag{'en' if tage != 1 else ''}",
                dto.kunde_display,
                _fmt(dto.summe_brutto),
                _fmt(dto.offener_betrag),
            ])
        self._bald_table.set_data(bald_rows)

    def _dtos_to_rows_stufe(
        self, dtos: list[UeberfaelligeDTO]
    ) -> tuple[list, dict]:
        rows, colors = [], {}
        for i, dto in enumerate(dtos):
            tage = dto.tage_ueberfaellig
            naechste = (
                f"in {dto.tage_bis_naechste_stufe}d → {dto.naechste_stufe}"
                if dto.naechste_stufe else "–"
            )
            rows.append([
                dto.rechnung_id,
                dto.rechnungsnummer,
                dto.faelligkeitsdatum,
                f"{tage} Tage",
                dto.kunde_display,
                _fmt(dto.summe_brutto),
                _fmt(dto.offener_betrag),
                _fmt(dto.mahngebuehren),
                naechste,
            ])
            farbe = STUFEN_FARBEN.get(dto.status)
            if farbe:
                colors[i] = QColor(farbe)
        return rows, colors

    def _dtos_to_rows_alle(
        self, dtos: list[UeberfaelligeDTO]
    ) -> tuple[list, dict]:
        rows, colors = [], {}
        for i, dto in enumerate(dtos):
            rows.append([
                dto.rechnung_id,
                dto.rechnungsnummer,
                dto.faelligkeitsdatum,
                f"{dto.tage_ueberfaellig} Tage",
                dto.kunde_display,
                dto.status,
                _fmt(dto.summe_brutto),
                _fmt(dto.offener_betrag),
                _fmt(dto.mahngebuehren),
            ])
            farbe = STUFEN_FARBEN.get(dto.status)
            if farbe:
                colors[i] = QColor(farbe)
        return rows, colors

    # ------------------------------------------------------------------
    # Kontextmenü & Aktionen
    # ------------------------------------------------------------------

    def _context_menu(self, pos, table: DataTable, stufe: Optional[str]) -> None:
        row = table.current_source_row()
        if row < 0:
            return

        # DTO ermitteln
        dto = self._dto_aus_row(table, row, stufe)
        if not dto:
            return

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

        menu.addAction("📖  Rechnung öffnen").triggered.connect(
            lambda: self._rechnung_oeffnen(dto)
        )
        menu.addSeparator()
        menu.addAction("✅  Als bezahlt markieren").triggered.connect(
            lambda: self._als_bezahlt(dto)
        )
        menu.addSeparator()

        # Mahngebühr buchen
        konfig = MahnKonfig.aus_config()
        gebuehr = konfig.gebuehr_fuer_status(dto.status)
        if gebuehr > 0:
            menu.addAction(
                f"💶  Mahngebühr buchen ({gebuehr:.2f} €)"
            ).triggered.connect(
                lambda: self._mahngebuehr_buchen(dto, gebuehr)
            )

        if dto.mahngebuehren > 0:
            menu.addAction("↩  Mahngebühr stornieren").triggered.connect(
                lambda: self._mahngebuehr_stornieren(dto)
            )

        menu.addSeparator()
        menu.addAction("📄  Mahnschreiben als PDF").triggered.connect(
            lambda: self._mahnschreiben_export(dto)
        )
        menu.addSeparator()
        menu.addAction("📂  Kundendokumente").triggered.connect(
            lambda: self._show_kunde_documents(dto)
        )
        menu.addAction("📧  E-Mail senden").triggered.connect(
            lambda: self._send_email(dto)
        )

        menu.exec(table.viewport().mapToGlobal(pos))

    def _show_kunde_documents(self, dto) -> None:
        """Öffnet den Dokumenten-Dialog für den Kunden der Rechnung."""
        try:
            from core.services.kunden_service import kunden_service
            from ui.modules.kunden.dokumente_dialog import DokumenteDialog
            with db.session() as session:
                kunde_dto = kunden_service.nach_id(session, dto.kunde_id)
            if not kunde_dto:
                self._banner.show_error("Kunde nicht gefunden.")
                return
            dlg = DokumenteDialog(kunde_dto, parent=self)
            dlg.exec()
        except Exception as e:
            self._banner.show_error(f"Fehler beim Öffnen der Dokumente: {e}")

    def _send_email(self, dto) -> None:
        """Öffnet das System-Mailprogramm mit der Kundenadresse."""
        import urllib.parse
        try:
            from core.services.kunden_service import kunden_service
            with db.session() as session:
                kunde_dto = kunden_service.nach_id(session, dto.kunde_id)
            if not kunde_dto:
                self._banner.show_error("Kunde nicht gefunden.")
                return
            empfaenger = kunde_dto.email or ""
            betreff = urllib.parse.quote(f"Rechnung {dto.rechnungsnummer}")
            empf_enc = urllib.parse.quote(empfaenger)
            mailto = f"mailto:{empf_enc}?subject={betreff}"
            import os, sys
            if sys.platform == "win32":
                os.startfile(mailto)
            elif sys.platform == "darwin":
                import subprocess
                subprocess.run(["open", mailto])
            else:
                import subprocess
                subprocess.run(["xdg-open", mailto])
        except Exception as e:
            self._banner.show_error(f"E-Mail konnte nicht geöffnet werden: {e}")

    def _mahnschreiben_export(self, dto) -> None:
        """Exportiert Mahnschreiben als PDF in den Kunden-Dokumentenordner."""
        from core.services.pdf_service import pdf_service
        from core.services.mahnwesen_service import MahnKonfig
        from core.services.kunden_service import kunden_service
        import sys

        try:
            konfig = MahnKonfig.aus_config()
            # Dateiname
            safe_nr = dto.rechnungsnummer.replace("/", "-").replace("\\", "-")
            stufe_key = {
                "Steht zur Erinnerung an":       "Erinnerung",
                "Steht zur Mahnung an":          "Mahnung1",
                "Steht zur Mahnung 2 an":        "Mahnung2",
                "Bitte an Inkasso weiterleiten": "Inkasso",
            }.get(dto.status, "Mahnung")
            dateiname = f"Mahnung_{safe_nr}_{stufe_key}.pdf"

            # PDF-Bytes erzeugen
            pdf_bytes = pdf_service.mahnung_als_pdf_bytes(dto, konfig=konfig)

            # In Kundenordner speichern + DMS-Eintrag + PDF öffnen
            with db.session() as session:
                ordner = kunden_service.kunden_ordner_pfad(session, dto.kunde_id)
                if not ordner:
                    self._banner.show_error(
                        "Kein Dokumentenordner konfiguriert. "
                        "Bitte unter Einstellungen → Pfade → Dokumentenordner festlegen."
                    )
                    return
                ziel = kunden_service.dokument_in_kundenordner_erstellen(
                    session, dto.kunde_id, dateiname, pdf_bytes
                )

            if ziel:
                self._banner.show_success(f"Mahnschreiben gespeichert: {ziel.name}")
                # PDF mit Standard-Programm öffnen
                try:
                    import subprocess
                    if sys.platform == "win32":
                        os.startfile(str(ziel))
                    elif sys.platform == "darwin":
                        subprocess.Popen(["open", str(ziel)])
                    else:
                        subprocess.Popen(["xdg-open", str(ziel)])
                except Exception:
                    pass
            else:
                self._banner.show_error("Mahnschreiben konnte nicht gespeichert werden.")
        except Exception as e:
            self._banner.show_error(f"Fehler: {e}")

    def _dto_aus_row(
        self, table: DataTable, row: int, stufe: Optional[str]
    ) -> Optional[UeberfaelligeDTO]:
        if stufe is None:
            # Alle-Tab
            if 0 <= row < len(self._alle_dtos):
                return self._alle_dtos[row]
        else:
            ueb = self._uebersicht
            if ueb:
                key = {
                    RechnungStatus.ERINNERUNG: "erinnerung",
                    RechnungStatus.MAHNUNG1:   "mahnung1",
                    RechnungStatus.MAHNUNG2:   "mahnung2",
                    RechnungStatus.INKASSO:    "inkasso",
                }.get(stufe)
                if key:
                    dtos = getattr(ueb, key)
                    if 0 <= row < len(dtos):
                        return dtos[row]
        return None

    def _rechnung_oeffnen(self, dto: UeberfaelligeDTO) -> None:
        from core.services.rechnungen_service import rechnungen_service
        from ui.modules.rechnungen.dialog import RechnungDialog

        with db.session() as session:
            full_dto = rechnungen_service.nach_id(session, dto.rechnung_id)
        if not full_dto:
            self._banner.show_error("Rechnung nicht gefunden.")
            return

        dlg = RechnungDialog(
            parent=self,
            dto=full_dto,
            kunde_name=dto.kunde_display,
            title=f"Rechnung {full_dto.rechnungsnummer} – {dto.kunde_display}",
        )
        dlg.status_changed.connect(lambda *_: self._auto_aktualisieren())
        dlg.exec()

    def _als_bezahlt(self, dto: UeberfaelligeDTO) -> None:
        if not ConfirmDialog.ask(
            title="Als bezahlt markieren",
            message=f"Rechnung '{dto.rechnungsnummer}' als bezahlt markieren?",
            detail=(
                f"Offener Betrag: {_fmt(dto.offener_betrag)}\n"
                f"Mahngebühren: {_fmt(dto.mahngebuehren)}"
            ),
            confirm_text="Als bezahlt markieren",
            parent=self,
        ):
            return

        from core.services.rechnungen_service import rechnungen_service
        with db.session() as session:
            result = rechnungen_service.status_aendern(
                session, dto.rechnung_id, RechnungStatus.BEZAHLT
            )
        if result.success:
            self._banner.show_success(result.message)
            self._auto_aktualisieren()
        else:
            self._banner.show_error(result.message)

    def _mahngebuehr_buchen(
        self, dto: UeberfaelligeDTO, betrag: Decimal
    ) -> None:
        if not ConfirmDialog.ask(
            title="Mahngebühr buchen",
            message=f"Mahngebühr {betrag:.2f} € auf '{dto.rechnungsnummer}' buchen?",
            detail=(
                f"Stufe: {dto.status}\n"
                f"Die Mahngebühr erhöht den offenen Betrag."
            ),
            confirm_text="Buchen",
            parent=self,
        ):
            return

        with db.session() as session:
            result = mahnwesen_service.mahngebuehr_buchen(
                session, dto.rechnung_id, betrag,
                grund=f"Mahngebühr {dto.status}"
            )
        if result.success:
            self._banner.show_success(result.message)
            self._auto_aktualisieren()
        else:
            self._banner.show_error(result.message)

    def _mahngebuehr_stornieren(self, dto: UeberfaelligeDTO) -> None:
        if not ConfirmDialog.ask(
            title="Mahngebühr stornieren",
            message=f"Alle Mahngebühren auf '{dto.rechnungsnummer}' stornieren?",
            detail=f"Gebuchte Mahngebühren: {_fmt(dto.mahngebuehren)}",
            confirm_text="Stornieren",
            danger=True,
            parent=self,
        ):
            return

        with db.session() as session:
            result = mahnwesen_service.mahngebuehr_stornieren(
                session, dto.rechnung_id, dto.mahngebuehren,
                grund="Manuell storniert"
            )
        if result.success:
            self._banner.show_success(result.message)
            self._auto_aktualisieren()
        else:
            self._banner.show_error(result.message)

    # ------------------------------------------------------------------
    # Hilfsmethoden
    # ------------------------------------------------------------------

    @staticmethod
    def _stufe_key(stufe: str) -> str:
        return {
            RechnungStatus.ERINNERUNG: "erinnerung",
            RechnungStatus.MAHNUNG1:   "mahnung1",
            RechnungStatus.MAHNUNG2:   "mahnung2",
            RechnungStatus.INKASSO:    "inkasso",
        }.get(stufe, "unbekannt")


# -----------------------------------------------------------------------
# Hilfsfunktion
# -----------------------------------------------------------------------

def _fmt(v: Decimal) -> str:
    """Formatiert einen Decimal als deutschen Währungsbetrag."""
    return f"{v:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
