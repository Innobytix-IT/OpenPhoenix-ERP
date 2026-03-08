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
)

from ui.theme.theme import Colors, Fonts, Spacing, Radius

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
        ("🧾", "Rechnungen",         "rechnungen"),
        ("📦", "Lagerverwaltung",    "lager"),
        ("📨", "Mahnwesen",          "mahnwesen"),
        ("📊", "Dashboard",          "dashboard"),
        ("🖹",  "XRechnung",          "xrechnung"),
        ("✏️",  "Rechnungskorrektur", "korrektur"),
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
        self._build_ui()

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
        logo_frame.setFixedHeight(64)
        logo_frame.setStyleSheet("background-color: transparent;")
        logo_layout = QVBoxLayout(logo_frame)
        logo_layout.setContentsMargins(Spacing.SM, Spacing.MD, Spacing.SM, Spacing.MD)

        logo_label = QLabel("🔥 OpenPhoenix")
        logo_label.setFont(Fonts.get(Fonts.SIZE_LG, bold=True))
        logo_label.setStyleSheet(f"color: {Colors.TEXT_PRIMARY};")

        version_label = QLabel("ERP v2.0")
        version_label.setFont(Fonts.get(Fonts.SIZE_XS))
        version_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")

        logo_layout.addWidget(logo_label)
        logo_layout.addWidget(version_label)
        layout.addWidget(logo_frame)

        # --- Trennlinie ---
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background-color: {Colors.BORDER};")
        layout.addWidget(line)
        layout.addSpacing(Spacing.SM)

        # --- Navigations-Items ---
        section_label = QLabel("NAVIGATION")
        section_label.setFont(Fonts.get(Fonts.SIZE_XS, bold=True))
        section_label.setStyleSheet(f"color: {Colors.TEXT_DISABLED}; padding-left: 8px;")
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
    """Das Hauptfenster von OpenPhoenix ERP v2."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("OpenPhoenix ERP v2.0")
        self.setMinimumSize(1280, 800)
        self.resize(1440, 900)

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
        self._stack.setStyleSheet(f"background-color: {Colors.BG_APP};")
        root_layout.addWidget(self._stack)

        # Module registrieren
        self._register_modules()

    def _register_modules(self) -> None:
        """Alle Module als Panels registrieren."""
        # Kunden-Modul (erstes, vollständig implementiertes)
        try:
            from ui.modules.kunden.panel import KundenPanel
            kunden_panel = KundenPanel()
        except ImportError:
            kunden_panel = PlaceholderPanel("Kundenverwaltung", "👥")

        # Rechnungsmodul
        try:
            from ui.modules.rechnungen.panel import RechnungenPanel
            rechnungen_panel = RechnungenPanel()
        except ImportError:
            rechnungen_panel = PlaceholderPanel("Rechnungen", "🧾")

        self._panels["rechnungen"] = rechnungen_panel
        self._stack.addWidget(rechnungen_panel)

        # Lagermodul
        try:
            from ui.modules.lager.panel import LagerPanel
            lager_panel = LagerPanel()
        except ImportError:
            lager_panel = PlaceholderPanel("Lagerverwaltung", "📦")

        self._panels["lager"] = lager_panel
        self._stack.addWidget(lager_panel)

        # Mahnwesen-Modul
        try:
            from ui.modules.mahnwesen.panel import MahnwesenPanel
            mahnwesen_panel = MahnwesenPanel()
        except Exception as _e:
            import traceback as _tb
            _err = _tb.format_exc()
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
        except ImportError:
            dashboard_panel = PlaceholderPanel("Dashboard", "📊")

        self._panels["dashboard"] = dashboard_panel
        self._stack.addWidget(dashboard_panel)

        # Einstellungen
        try:
            from ui.modules.einstellungen.panel import EinstellungenPanel
            einstellungen_panel = EinstellungenPanel()
            einstellungen_panel.settings_saved.connect(self._on_settings_saved)
        except ImportError:
            einstellungen_panel = PlaceholderPanel("Einstellungen", "⚙️")

        self._panels["einstellungen"] = einstellungen_panel
        self._stack.addWidget(einstellungen_panel)

        # XRechnung & PDF-Export
        try:
            from ui.modules.xrechnung.panel import XRechnungPanel
            xrechnung_panel = XRechnungPanel()
        except ImportError:
            xrechnung_panel = PlaceholderPanel("XRechnung", "🖹")

        self._panels["xrechnung"] = xrechnung_panel
        self._stack.addWidget(xrechnung_panel)

        # Rechnungskorrektur-Modul
        try:
            from ui.modules.rechnungskorrektur.panel import RechnungskorrekturPanel
            korrektur_panel = RechnungskorrekturPanel()
        except Exception as _e:
            logger.exception(f"Rechnungskorrektur-Modul konnte nicht geladen werden: {_e}")
            korrektur_panel = PlaceholderPanel("Rechnungskorrektur", "✏️")

        self._panels["kunden"] = kunden_panel
        self._stack.addWidget(kunden_panel)

        self._panels["korrektur"] = korrektur_panel
        self._stack.addWidget(korrektur_panel)

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
        action_db = QAction("Datenbank wechseln...", self)
        action_quit = QAction("Beenden", self)
        action_quit.setShortcut("Ctrl+Q")
        action_quit.triggered.connect(self.close)
        datei_menu.addAction(action_db)
        datei_menu.addSeparator()
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

        version_label = QLabel("OpenPhoenix ERP v2.0.0")
        version_label.setStyleSheet(f"color: {Colors.TEXT_DISABLED}; padding-right: 8px;")
        status.addPermanentWidget(version_label)

    # ------------------------------------------------------------------
    # Modul-Navigation
    # ------------------------------------------------------------------

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
            "<h2>🔥 OpenPhoenix ERP v2.0.0</h2>"
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
