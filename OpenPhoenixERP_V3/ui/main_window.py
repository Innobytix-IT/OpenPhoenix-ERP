"""
ui/main_window.py – Hauptfenster für OpenPhoenix ERP v2
========================================================
Ein einziges Fenster mit seitlicher Navigation.
Alle Module werden als Panels innerhalb dieses Fensters geladen.
"""

import logging
from typing import Optional

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QIcon, QFont, QAction, QPixmap, QPainter, QColor
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QPushButton, QFrame, QStackedWidget,
    QSizePolicy, QStatusBar, QMessageBox, QSpacerItem,
    QApplication,
)

from ui.theme.theme import Colors, Fonts, Spacing, Radius, on_theme_changed

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sidebar-Navigation
# ---------------------------------------------------------------------------

class NavItem(QPushButton):
    """Ein einzelner Navigations-Button in der Seitenleiste."""

    def __init__(self, icon_text: str, label: str, module_id: str, parent=None):
        super().__init__(parent)
        self.module_id = module_id
        self._active = False

        self.setCheckable(True)
        self.setFixedHeight(52)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(Spacing.MD, 0, Spacing.MD, 0)
        layout.setSpacing(Spacing.SM)

        self._icon_label = QLabel(icon_text)
        self._icon_label.setFixedWidth(28)
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = QFont("Segoe UI Emoji", 16)
        self._icon_label.setFont(font)
        self._icon_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self._text_label = QLabel(label)
        self._text_label.setFont(Fonts.get(Fonts.SIZE_BASE))
        self._text_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        layout.addWidget(self._icon_label)
        layout.addWidget(self._text_label)
        layout.addStretch()

        self._update_style(False)
        on_theme_changed(self._on_theme_changed)

    def _on_theme_changed(self, _mode: str) -> None:
        self._update_style(self._active)

    def set_active(self, active: bool) -> None:
        self._active = active
        self.setChecked(active)
        self._update_style(active)

    def _update_style(self, active: bool) -> None:
        if active:
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: {Colors.SIDEBAR_ACTIVE};
                    border-radius: {Radius.MD}px;
                    border: none;
                    text-align: left;
                    padding: 0;
                }}
            """)
            self._text_label.setStyleSheet(f"color: {Colors.SIDEBAR_TEXT_ACT}; font-weight: bold;")
            self._icon_label.setStyleSheet("")
        else:
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    border-radius: {Radius.MD}px;
                    border: none;
                    text-align: left;
                    padding: 0;
                }}
                QPushButton:hover {{
                    background-color: {Colors.SIDEBAR_HOVER};
                }}
            """)
            self._text_label.setStyleSheet(f"color: {Colors.SIDEBAR_TEXT};")
            self._icon_label.setStyleSheet("")


class Sidebar(QFrame):
    """Die linke Navigationsleiste."""

    module_selected = Signal(str)  # Sendet module_id wenn geklickt

    NAV_ITEMS = [
        ("👥", "Kundenverwaltung",  "kunden"),
        ("📝", "Angebote",           "angebote"),
        ("🧾", "Rechnungen",         "rechnungen"),
        ("📦", "Lagerverwaltung",    "lager"),
        ("📥", "Eingangsrechnungen", "belege"),
        ("📨", "Mahnwesen",          "mahnwesen"),
        ("📊", "Dashboard",          "dashboard"),
        ("🖹",  "XRechnung",          "xrechnung"),
        ("✏️",  "Rechnungskorrektur", "korrektur"),
        ("📤", "DATEV-Export",       "datev"),
    ]

    BOTTOM_ITEMS = [
        ("⚙️", "Einstellungen", "einstellungen"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(220)
        self._nav_buttons: dict[str, NavItem] = {}
        self._current: Optional[str] = None
        self._styled_widgets: list = []  # Widgets die bei Theme-Wechsel aktualisiert werden
        self._build_ui()
        on_theme_changed(self._on_theme_changed)

    def _on_theme_changed(self, _mode: str) -> None:
        """Aktualisiert alle inline Styles nach Theme-Wechsel."""
        self._apply_styles()

    def _apply_styles(self) -> None:
        """Setzt alle inline Styles neu (mit aktuellen Colors-Werten)."""
        self.setStyleSheet(f"""
            QFrame#sidebar {{
                background-color: {Colors.SIDEBAR_BG};
                border-right: 1px solid {Colors.BORDER};
            }}
        """)
        for widget, style_fn in self._styled_widgets:
            widget.setStyleSheet(style_fn())

    def _build_ui(self) -> None:
        self.setStyleSheet(f"""
            QFrame#sidebar {{
                background-color: {Colors.SIDEBAR_BG};
                border-right: 1px solid {Colors.BORDER};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.SM, Spacing.SM, Spacing.SM, Spacing.SM)
        layout.setSpacing(2)

        # --- Logo / App-Name ---
        logo_frame = QFrame()
        logo_frame.setObjectName("sidebarLogoFrame")
        logo_frame.setFixedHeight(64)
        logo_frame.setStyleSheet("#sidebarLogoFrame { background-color: transparent; }")
        logo_layout = QVBoxLayout(logo_frame)
        logo_layout.setContentsMargins(Spacing.SM, Spacing.MD, Spacing.SM, Spacing.MD)

        logo_label = QLabel("🔥 OpenPhoenix")
        logo_label.setFont(Fonts.get(Fonts.SIZE_LG, bold=True))
        logo_label.setStyleSheet(f"color: {Colors.SIDEBAR_TEXT_ACT};")
        self._styled_widgets.append(
            (logo_label, lambda: f"color: {Colors.SIDEBAR_TEXT_ACT};")
        )

        version_label = QLabel("ERP v3.0")
        version_label.setFont(Fonts.get(Fonts.SIZE_XS))
        version_label.setStyleSheet(f"color: {Colors.SIDEBAR_TEXT};")
        self._styled_widgets.append(
            (version_label, lambda: f"color: {Colors.SIDEBAR_TEXT};")
        )

        logo_layout.addWidget(logo_label)
        logo_layout.addWidget(version_label)
        layout.addWidget(logo_frame)

        # --- Trennlinie ---
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background-color: {Colors.BORDER};")
        self._styled_widgets.append(
            (line, lambda: f"background-color: {Colors.BORDER};")
        )
        layout.addWidget(line)
        layout.addSpacing(Spacing.SM)

        # --- Navigations-Items ---
        section_label = QLabel("NAVIGATION")
        section_label.setFont(Fonts.get(Fonts.SIZE_XS, bold=True))
        section_label.setStyleSheet(f"color: {Colors.SIDEBAR_TEXT}; padding-left: 8px;")
        self._styled_widgets.append(
            (section_label, lambda: f"color: {Colors.SIDEBAR_TEXT}; padding-left: 8px;")
        )
        layout.addWidget(section_label)
        layout.addSpacing(Spacing.XS)

        for icon, label, module_id in self.NAV_ITEMS:
            btn = NavItem(icon, label, module_id)
            btn.clicked.connect(lambda checked, mid=module_id: self._on_nav_click(mid))
            self._nav_buttons[module_id] = btn
            layout.addWidget(btn)

        # --- Spacer ---
        layout.addStretch()

        # --- Trennlinie ---
        line2 = QFrame()
        line2.setFixedHeight(1)
        line2.setStyleSheet(f"background-color: {Colors.BORDER};")
        self._styled_widgets.append(
            (line2, lambda: f"background-color: {Colors.BORDER};")
        )
        layout.addWidget(line2)
        layout.addSpacing(Spacing.SM)

        # --- Untere Items (Einstellungen) ---
        for icon, label, module_id in self.BOTTOM_ITEMS:
            btn = NavItem(icon, label, module_id)
            btn.clicked.connect(lambda checked, mid=module_id: self._on_nav_click(mid))
            self._nav_buttons[module_id] = btn
            layout.addWidget(btn)

        layout.addSpacing(Spacing.SM)

    def _on_nav_click(self, module_id: str) -> None:
        self.activate(module_id)
        self.module_selected.emit(module_id)

    def activate(self, module_id: str) -> None:
        """Setzt den aktiven Navigations-Button."""
        if self._current:
            if self._current in self._nav_buttons:
                self._nav_buttons[self._current].set_active(False)
        if module_id in self._nav_buttons:
            self._nav_buttons[module_id].set_active(True)
            self._current = module_id


# ---------------------------------------------------------------------------
# Platzhalter-Panel (wird durch echte Module ersetzt)
# ---------------------------------------------------------------------------

class PlaceholderPanel(QWidget):
    """Temporärer Platzhalter bis das Modul implementiert ist."""

    def __init__(self, module_name: str, icon: str = "🚧", subtitle: str = "", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon_label = QLabel(icon)
        icon_label.setFont(QFont("Segoe UI Emoji", 48))
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet("background: transparent;")

        title = QLabel(module_name)
        title.setFont(Fonts.heading2())
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; background: transparent;")

        sub_text = subtitle or "Dieses Modul wird gerade implementiert."
        subtitle_lbl = QLabel(sub_text)
        subtitle_lbl.setFont(Fonts.get(Fonts.SIZE_MD))
        subtitle_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle_lbl.setWordWrap(True)
        subtitle_lbl.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; background: transparent;")

        layout.addWidget(icon_label)
        layout.addSpacing(Spacing.LG)
        layout.addWidget(title)
        layout.addSpacing(Spacing.SM)
        layout.addWidget(subtitle_lbl)


# ---------------------------------------------------------------------------
# Hauptfenster
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    """Das Hauptfenster von OpenPhoenix ERP v3."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("OpenPhoenix ERP v3.0")
        self.setMinimumSize(1280, 800)

        self._panels: dict[str, QWidget] = {}
        self._build_ui()
        self._build_menu()
        self._build_statusbar()

        # Erstes Modul aktivieren
        self._sidebar.activate("kunden")
        self._stack.setCurrentWidget(self._panels["kunden"])

    # ------------------------------------------------------------------
    # UI aufbauen
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Sidebar
        self._sidebar = Sidebar()
        self._sidebar.module_selected.connect(self._switch_module)
        root_layout.addWidget(self._sidebar)

        # Content-Bereich
        self._stack = QStackedWidget()
        self._stack.setObjectName("mainStack")
        self._stack.setStyleSheet(f"#mainStack {{ background-color: {Colors.BG_APP}; }}")
        root_layout.addWidget(self._stack)

        # Module registrieren
        self._register_modules()

    def _register_modules(self) -> None:
        """Alle Module als Panels registrieren."""
        # Kunden-Modul (erstes, vollständig implementiertes)
        try:
            from ui.modules.kunden.panel import KundenPanel
            kunden_panel = KundenPanel()
        except Exception as _e:
            logger.exception(f"Kunden-Modul konnte nicht geladen werden: {_e}")
            kunden_panel = PlaceholderPanel(
                "Kundenverwaltung", "👥",
                subtitle=f"Ladefehler: {type(_e).__name__}: {_e}"
            )

        self._panels["kunden"] = kunden_panel
        self._stack.addWidget(kunden_panel)

        # Rechnungsmodul
        try:
            from ui.modules.rechnungen.panel import RechnungenPanel
            rechnungen_panel = RechnungenPanel()
        except Exception as _e:
            logger.exception(f"Rechnungs-Modul konnte nicht geladen werden: {_e}")
            rechnungen_panel = PlaceholderPanel(
                "Rechnungen", "🧾",
                subtitle=f"Ladefehler: {type(_e).__name__}: {_e}"
            )

        self._panels["rechnungen"] = rechnungen_panel
        self._stack.addWidget(rechnungen_panel)

        # Angebotsmodul
        try:
            from ui.modules.angebote.panel import AngebotePanel
            angebote_panel = AngebotePanel()
        except Exception as _e:
            logger.exception(f"Angebots-Modul konnte nicht geladen werden: {_e}")
            angebote_panel = PlaceholderPanel(
                "Angebote", "📝",
                subtitle=f"Ladefehler: {type(_e).__name__}: {_e}"
            )

        self._panels["angebote"] = angebote_panel
        self._stack.addWidget(angebote_panel)

        # Lagermodul
        try:
            from ui.modules.lager.panel import LagerPanel
            lager_panel = LagerPanel()
        except Exception as _e:
            logger.exception(f"Lager-Modul konnte nicht geladen werden: {_e}")
            lager_panel = PlaceholderPanel(
                "Lagerverwaltung", "📦",
                subtitle=f"Ladefehler: {type(_e).__name__}: {_e}"
            )

        self._panels["lager"] = lager_panel
        self._stack.addWidget(lager_panel)

        # Eingangsrechnungen / Belege
        try:
            from ui.modules.belege.panel import BelegePanel
            belege_panel = BelegePanel()
        except Exception as _e:
            logger.exception(f"Belege-Modul konnte nicht geladen werden: {_e}")
            belege_panel = PlaceholderPanel(
                "Eingangsrechnungen", "📥",
                subtitle=f"Ladefehler: {type(_e).__name__}: {_e}"
            )

        self._panels["belege"] = belege_panel
        self._stack.addWidget(belege_panel)

        # Mahnwesen-Modul
        try:
            from ui.modules.mahnwesen.panel import MahnwesenPanel
            mahnwesen_panel = MahnwesenPanel()
        except Exception as _e:
            logger.exception(f"Mahnwesen-Modul konnte nicht geladen werden: {_e}")
            mahnwesen_panel = PlaceholderPanel(
                "Mahnwesen", "📨",
                subtitle=f"Ladefehler: {type(_e).__name__}: {_e}"
            )

        self._panels["mahnwesen"] = mahnwesen_panel
        self._stack.addWidget(mahnwesen_panel)

        # Dashboard
        try:
            from ui.modules.dashboard.panel import DashboardPanel
            dashboard_panel = DashboardPanel()
        except Exception as _e:
            logger.exception(f"Dashboard-Modul konnte nicht geladen werden: {_e}")
            dashboard_panel = PlaceholderPanel(
                "Dashboard", "📊",
                subtitle=f"Ladefehler: {type(_e).__name__}: {_e}"
            )

        self._panels["dashboard"] = dashboard_panel
        self._stack.addWidget(dashboard_panel)

        # Einstellungen
        try:
            from ui.modules.einstellungen.panel import EinstellungenPanel
            einstellungen_panel = EinstellungenPanel()
            einstellungen_panel.settings_saved.connect(self._on_settings_saved)
        except Exception as _e:
            logger.exception(f"Einstellungen-Modul konnte nicht geladen werden: {_e}")
            einstellungen_panel = PlaceholderPanel(
                "Einstellungen", "⚙️",
                subtitle=f"Ladefehler: {type(_e).__name__}: {_e}"
            )

        self._panels["einstellungen"] = einstellungen_panel
        self._stack.addWidget(einstellungen_panel)

        # XRechnung & PDF-Export
        try:
            from ui.modules.xrechnung.panel import XRechnungPanel
            xrechnung_panel = XRechnungPanel()
        except Exception as _e:
            logger.exception(f"XRechnung-Modul konnte nicht geladen werden: {_e}")
            xrechnung_panel = PlaceholderPanel(
                "XRechnung", "🖹",
                subtitle=f"Ladefehler: {type(_e).__name__}: {_e}"
            )

        self._panels["xrechnung"] = xrechnung_panel
        self._stack.addWidget(xrechnung_panel)

        # Rechnungskorrektur-Modul
        try:
            from ui.modules.rechnungskorrektur.panel import RechnungskorrekturPanel
            korrektur_panel = RechnungskorrekturPanel()
        except Exception as _e:
            logger.exception(f"Rechnungskorrektur-Modul konnte nicht geladen werden: {_e}")
            korrektur_panel = PlaceholderPanel("Rechnungskorrektur", "✏️")

        self._panels["korrektur"] = korrektur_panel
        self._stack.addWidget(korrektur_panel)

        # DATEV-Export
        try:
            from ui.modules.datev.panel import DatevPanel
            datev_panel = DatevPanel()
        except Exception as _e:
            logger.exception(f"DATEV-Modul konnte nicht geladen werden: {_e}")
            datev_panel = PlaceholderPanel(
                "DATEV-Export", "📤",
                subtitle=f"Ladefehler: {type(_e).__name__}: {_e}"
            )

        self._panels["datev"] = datev_panel
        self._stack.addWidget(datev_panel)

    def _on_settings_saved(self) -> None:
        """Aktualisiert den Firmennamen in der Titelleiste nach Einstellungsänderung."""
        from core.config import config
        firma = config.get("company", "name", "OpenPhoenix ERP")
        self.setWindowTitle(f"OpenPhoenix ERP v2  –  {firma}")

    def _build_menu(self) -> None:
        """Minimale Menüleiste."""
        menubar = self.menuBar()
        menubar.setStyleSheet(f"""
            QMenuBar {{
                background-color: {Colors.BG_APP};
                color: {Colors.TEXT_PRIMARY};
                border-bottom: 1px solid {Colors.BORDER};
                padding: 2px 8px;
                font-size: {Fonts.SIZE_SM}pt;
            }}
        """)

        # Datei-Menü
        datei_menu = menubar.addMenu("Datei")

        # Mode-Untermenü
        mode_menu = datei_menu.addMenu("🎨  Mode")

        from ui.theme.theme import get_current_mode
        current = get_current_mode()

        self._action_dark = QAction("🌙  Dark Mode", self)
        self._action_dark.setCheckable(True)
        self._action_dark.setChecked(current == "dark")
        self._action_dark.triggered.connect(lambda: self._switch_theme("dark"))
        mode_menu.addAction(self._action_dark)

        self._action_light = QAction("☀️  Light Mode", self)
        self._action_light.setCheckable(True)
        self._action_light.setChecked(current == "light")
        self._action_light.triggered.connect(lambda: self._switch_theme("light"))
        mode_menu.addAction(self._action_light)

        datei_menu.addSeparator()
        action_quit = QAction("Beenden", self)
        action_quit.setShortcut("Ctrl+Q")
        action_quit.triggered.connect(self.close)
        datei_menu.addAction(action_quit)

        # Hilfe-Menü
        hilfe_menu = menubar.addMenu("Hilfe")
        action_about = QAction("Über OpenPhoenix ERP", self)
        action_about.triggered.connect(self._show_about)
        hilfe_menu.addAction(action_about)

    def _build_statusbar(self) -> None:
        """Statusleiste am unteren Rand."""
        status = QStatusBar()
        self.setStatusBar(status)
        self._status_label = QLabel("Bereit")
        self._status_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        status.addWidget(self._status_label)

        # Rechte Seite: DB-Modus und Version
        from core.config import config
        db_mode = config.get("database", "mode", "local")
        db_indicator = QLabel(
            f"🗄️ {'Einzelplatz (SQLite)' if db_mode == 'local' else 'Netzwerk (PostgreSQL)'}"
        )
        db_indicator.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; padding-right: 8px;")
        status.addPermanentWidget(db_indicator)

        version_label = QLabel("OpenPhoenix ERP v3.0.0")
        version_label.setStyleSheet(f"color: {Colors.TEXT_DISABLED}; padding-right: 8px;")
        status.addPermanentWidget(version_label)

    # ------------------------------------------------------------------
    # Modul-Navigation
    # ------------------------------------------------------------------

    def _switch_theme(self, mode: str) -> None:
        """Wechselt zwischen Dark- und Light-Mode zur Laufzeit."""
        from ui.theme.theme import switch_theme, get_current_mode

        if get_current_mode() == mode:
            return

        app = QApplication.instance()
        if not app:
            return

        # Theme global umschalten – Stylesheet + Palette + Listener-Callbacks
        switch_theme(app, mode)

        # Inline Styles der MainWindow-eigenen Widgets aktualisieren
        self._refresh_main_styles()

        # Checkmarks in Menü aktualisieren
        self._action_dark.setChecked(mode == "dark")
        self._action_light.setChecked(mode == "light")

    def _refresh_main_styles(self) -> None:
        """Aktualisiert alle inline Styles des MainWindows nach Theme-Wechsel."""
        # Menübar
        self.menuBar().setStyleSheet(f"""
            QMenuBar {{
                background-color: {Colors.BG_APP};
                color: {Colors.TEXT_PRIMARY};
                border-bottom: 1px solid {Colors.BORDER};
                padding: 2px 8px;
                font-size: {Fonts.SIZE_SM}pt;
            }}
        """)

        # Stack-Container
        self._stack.setStyleSheet(
            f"#mainStack {{ background-color: {Colors.BG_APP}; }}"
        )

        # Statusbar-Labels
        if hasattr(self, '_status_label'):
            self._status_label.setStyleSheet(
                f"color: {Colors.TEXT_SECONDARY};"
            )

    def _switch_module(self, module_id: str) -> None:
        """Wechselt das angezeigte Modul."""
        if module_id in self._panels:
            self._stack.setCurrentWidget(self._panels[module_id])
            logger.debug(f"Modul gewechselt: {module_id}")

    def set_status(self, message: str, timeout_ms: int = 0) -> None:
        """Setzt eine Nachricht in der Statusleiste."""
        self._status_label.setText(message)
        if timeout_ms > 0:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(timeout_ms, lambda: self._status_label.setText("Bereit"))

    # ------------------------------------------------------------------
    # Dialoge
    # ------------------------------------------------------------------

    def _show_about(self) -> None:
        msg = QMessageBox(self)
        msg.setWindowTitle("Über OpenPhoenix ERP")
        msg.setText(
            "<h2>🔥 OpenPhoenix ERP v3.0.0</h2>"
            "<p>Freies, modulares ERP-System für kleine und mittlere Unternehmen.</p>"
            "<p><b>Lizenz:</b> GNU General Public License v3 (GPL-3.0)</p>"
            "<p><b>Technologie:</b> Python 3.11 · PySide6 · SQLAlchemy 2.0</p>"
            "<hr>"
            "<p style='color: gray;'>OpenPhoenix ERP ist eine kostenlose Software.<br>"
            "Dieses Programm kommt als frei erhältliche Software ohne Garantie und Support.<br>"
            "Weitergabe unter den Bedingungen der GPL v3.</p>"
            "OpenPhoenix ERP wurde von Innobytix-IT entwickelt.</p>"
        )
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()

    def closeEvent(self, event) -> None:
        """Sauberes Beenden: DB-Verbindungen schließen."""
        from core.db.engine import db
        db.dispose()
        logger.info("Anwendung beendet.")
        event.accept()
