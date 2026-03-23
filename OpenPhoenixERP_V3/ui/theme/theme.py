"""
ui/theme/theme.py – Design-System für OpenPhoenix ERP
======================================================
Zentrales, konsistentes Design für die gesamte Anwendung.
Farben, Schriften, Abstände und Stile sind hier definiert —
kein magic number irgendwo im UI-Code.

Unterstützt Dark-Mode und Light-Mode mit Umschaltung zur Laufzeit.
"""

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt


# ---------------------------------------------------------------------------
# Farben – Dark Mode (Standard)
# ---------------------------------------------------------------------------

_DARK_COLORS = {
    "PRIMARY":          "#2563EB",
    "PRIMARY_HOVER":    "#1D4ED8",
    "PRIMARY_LIGHT":    "#EFF6FF",
    "PRIMARY_DARK":     "#1E3A5F",
    "BG_APP":           "#0F172A",
    "BG_SURFACE":       "#1E293B",
    "BG_ELEVATED":      "#273449",
    "BG_INPUT":         "#1A2540",
    "SIDEBAR_BG":       "#0F172A",
    "SIDEBAR_ITEM":     "#1E293B",
    "SIDEBAR_ACTIVE":   "#2563EB",
    "SIDEBAR_HOVER":    "#1E3A5F",
    "SIDEBAR_TEXT":     "#94A3B8",
    "SIDEBAR_TEXT_ACT": "#FFFFFF",
    "TEXT_PRIMARY":     "#F1F5F9",
    "TEXT_SECONDARY":   "#94A3B8",
    "TEXT_DISABLED":    "#475569",
    "TEXT_INVERSE":     "#0F172A",
    "BORDER":           "#334155",
    "BORDER_FOCUS":     "#2563EB",
    "BORDER_ERROR":     "#EF4444",
    "SUCCESS":          "#10B981",
    "SUCCESS_BG":       "#064E3B",
    "WARNING":          "#F59E0B",
    "WARNING_BG":       "#451A03",
    "ERROR":            "#EF4444",
    "ERROR_BG":         "#450A0A",
    "INFO":             "#3B82F6",
    "INFO_BG":          "#1E3A5F",
    "STATUS_ENTWURF":         "#94A3B8",
    "STATUS_OFFEN":           "#3B82F6",
    "STATUS_ERINNERUNG":      "#F59E0B",
    "STATUS_MAHNUNG":         "#F97316",
    "STATUS_MAHNUNG2":        "#EF4444",
    "STATUS_INKASSO":         "#DC2626",
    "STATUS_BEZAHLT":         "#10B981",
    "STATUS_STORNIERT":       "#475569",
    "STATUS_GUTSCHRIFT":      "#8B5CF6",
    "TABLE_HEADER_BG":  "#1E293B",
    "TABLE_ROW_ALT":    "#1A2540",
    "TABLE_SELECTED":   "#1D4ED8",
    "TABLE_HOVER":      "#273449",
}

# ---------------------------------------------------------------------------
# Farben – Light Mode
# ---------------------------------------------------------------------------

_LIGHT_COLORS = {
    "PRIMARY":          "#2563EB",
    "PRIMARY_HOVER":    "#1D4ED8",
    "PRIMARY_LIGHT":    "#DBEAFE",
    "PRIMARY_DARK":     "#1E40AF",
    "BG_APP":           "#F1F5F9",      # Leicht grau statt fast-weiß
    "BG_SURFACE":       "#FFFFFF",      # Karten/Panels bleiben weiß
    "BG_ELEVATED":      "#E2E8F0",      # Deutlicher Kontrast für Dropdowns etc.
    "BG_INPUT":         "#F8FAFC",      # Leicht getönt damit sichtbar auf weißen Flächen
    "SIDEBAR_BG":       "#1E293B",      # Sidebar bleibt dunkel
    "SIDEBAR_ITEM":     "#334155",
    "SIDEBAR_ACTIVE":   "#2563EB",
    "SIDEBAR_HOVER":    "#334155",
    "SIDEBAR_TEXT":     "#CBD5E1",
    "SIDEBAR_TEXT_ACT": "#FFFFFF",
    "TEXT_PRIMARY":     "#0F172A",      # Fast schwarz
    "TEXT_SECONDARY":   "#475569",      # Dunkler als vorher für bessere Lesbarkeit
    "TEXT_DISABLED":    "#94A3B8",
    "TEXT_INVERSE":     "#F8FAFC",
    "BORDER":           "#CBD5E1",      # Sichtbare Ränder
    "BORDER_FOCUS":     "#2563EB",
    "BORDER_ERROR":     "#EF4444",
    "SUCCESS":          "#059669",      # Etwas dunkler für besseren Kontrast auf Hell
    "SUCCESS_BG":       "#ECFDF5",
    "WARNING":          "#D97706",      # Dunkler für Kontrast
    "WARNING_BG":       "#FFFBEB",
    "ERROR":            "#DC2626",
    "ERROR_BG":         "#FEF2F2",
    "INFO":             "#2563EB",
    "INFO_BG":          "#DBEAFE",
    "STATUS_ENTWURF":         "#64748B",
    "STATUS_OFFEN":           "#2563EB",
    "STATUS_ERINNERUNG":      "#D97706",
    "STATUS_MAHNUNG":         "#EA580C",
    "STATUS_MAHNUNG2":        "#DC2626",
    "STATUS_INKASSO":         "#B91C1C",
    "STATUS_BEZAHLT":         "#059669",
    "STATUS_STORNIERT":       "#64748B",
    "STATUS_GUTSCHRIFT":      "#7C3AED",
    "TABLE_HEADER_BG":  "#E2E8F0",     # Deutlich sichtbarer Header
    "TABLE_ROW_ALT":    "#F8FAFC",
    "TABLE_SELECTED":   "#2563EB",
    "TABLE_HOVER":      "#DBEAFE",
}


# ---------------------------------------------------------------------------
# Aktueller Modus – wird zur Laufzeit gesetzt
# ---------------------------------------------------------------------------

_current_mode: str = "dark"

# Callbacks die nach jedem Theme-Wechsel aufgerufen werden.
# Jedes Callback bekommt den neuen Modus ("dark"/"light") übergeben.
_theme_listeners: list = []


def on_theme_changed(callback) -> None:
    """Registriert einen Callback der bei Theme-Wechsel aufgerufen wird."""
    if callback not in _theme_listeners:
        _theme_listeners.append(callback)


def remove_theme_listener(callback) -> None:
    """Entfernt einen zuvor registrierten Callback."""
    try:
        _theme_listeners.remove(callback)
    except ValueError:
        pass


def _notify_listeners() -> None:
    """Benachrichtigt alle registrierten Listener über den Theme-Wechsel."""
    for cb in _theme_listeners[:]:  # Kopie, falls Listener sich entfernen
        try:
            cb(_current_mode)
        except Exception:
            pass


def _get_colors_dict() -> dict:
    return _DARK_COLORS if _current_mode == "dark" else _LIGHT_COLORS


class _ColorProxy:
    """
    Dynamischer Proxy für Farbzugriff.
    Erlaubt Colors.PRIMARY etc. und liefert je nach Modus den richtigen Wert.
    """
    def __getattr__(self, name: str) -> str:
        colors = _get_colors_dict()
        if name in colors:
            return colors[name]
        raise AttributeError(f"Colors hat kein Attribut '{name}'")


Colors = _ColorProxy()


# ---------------------------------------------------------------------------
# Schriften
# ---------------------------------------------------------------------------

class Fonts:
    """Schriftdefinitionen für OpenPhoenix ERP."""

    FAMILY_PRIMARY   = "Inter"
    FAMILY_MONO      = "JetBrains Mono"
    FAMILY_FALLBACK  = "Segoe UI, Arial, sans-serif"

    SIZE_XS     = 10
    SIZE_SM     = 11
    SIZE_BASE   = 12
    SIZE_MD     = 13
    SIZE_LG     = 15
    SIZE_XL     = 18
    SIZE_2XL    = 22
    SIZE_3XL    = 28

    @staticmethod
    def get(size: int = 12, bold: bool = False, italic: bool = False) -> QFont:
        font = QFont("Segoe UI")
        font.setPointSize(size)
        font.setBold(bold)
        font.setItalic(italic)
        return font

    @staticmethod
    def heading1() -> QFont:
        return Fonts.get(Fonts.SIZE_2XL, bold=True)

    @staticmethod
    def heading2() -> QFont:
        return Fonts.get(Fonts.SIZE_XL, bold=True)

    @staticmethod
    def heading3() -> QFont:
        return Fonts.get(Fonts.SIZE_LG, bold=True)

    @staticmethod
    def body() -> QFont:
        return Fonts.get(Fonts.SIZE_BASE)

    @staticmethod
    def caption() -> QFont:
        return Fonts.get(Fonts.SIZE_SM)

    @staticmethod
    def mono() -> QFont:
        font = QFont("Consolas")
        font.setPointSize(Fonts.SIZE_BASE)
        return font


# ---------------------------------------------------------------------------
# Abstände
# ---------------------------------------------------------------------------

class Spacing:
    """Konsistente Abstände."""
    XS   = 4
    SM   = 8
    MD   = 12
    LG   = 16
    XL   = 24
    XXL  = 32
    XXXL = 48


# ---------------------------------------------------------------------------
# Radien
# ---------------------------------------------------------------------------

class Radius:
    SM  = 4
    MD  = 6
    LG  = 8
    XL  = 12
    FULL = 9999


# ---------------------------------------------------------------------------
# Haupt-Stylesheet (dynamisch generiert je nach Modus)
# ---------------------------------------------------------------------------

def _light_overrides(C: dict) -> str:
    """Zusätzliche CSS-Regeln nur für den Light-Mode, um Kontrast sicherzustellen."""
    return f"""
/* ===================================================
   Light-Mode Overrides – stärkere Kontraste
   =================================================== */

/* Ghost-Buttons: leichte Border im Light-Mode */
QPushButton[role="ghost"] {{
    border: 1px solid {C['BORDER']};
    color: {C['TEXT_SECONDARY']};
}}

QPushButton[role="ghost"]:hover {{
    border-color: #94A3B8;
    background-color: {C['BG_ELEVATED']};
    color: {C['TEXT_PRIMARY']};
}}

/* Eingabefelder: stärkere Border auf weißem Hintergrund */
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QDateEdit {{
    border: 1px solid #94A3B8;
}}

QComboBox {{
    border: 1px solid #94A3B8;
}}

/* Farbige Buttons: weiße Schrift explizit erzwingen (Palette-Override) */
QPushButton {{
    color: white;
}}
QPushButton[role="secondary"] {{
    color: {C['TEXT_PRIMARY']};
}}
QPushButton[role="ghost"] {{
    color: {C['TEXT_SECONDARY']};
}}
QPushButton:disabled {{
    color: {C['TEXT_DISABLED']};
}}

/* Tabellen: stärkere Umrandung */
QTableWidget, QTreeWidget, QTreeView, QTableView, QListWidget, QListView {{
    border: 1px solid #94A3B8;
}}

QHeaderView::section {{
    border-right: 1px solid #94A3B8;
    border-bottom: 2px solid #94A3B8;
}}
"""


def _build_stylesheet() -> str:
    """Generiert das vollständige Stylesheet basierend auf dem aktuellen Farbmodus."""
    C = _get_colors_dict()
    return f"""
/* ===================================================
   OpenPhoenix ERP – Globales Stylesheet ({_current_mode} mode)
   =================================================== */

QWidget {{
    background-color: {C['BG_APP']};
    color: {C['TEXT_PRIMARY']};
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: {Fonts.SIZE_BASE}pt;
    border: none;
    outline: none;
}}

/* --- Hauptfenster --- */
QMainWindow {{
    background-color: {C['BG_APP']};
}}

/* --- Frames / Container --- */
QFrame {{
    background-color: transparent;
}}

QFrame[frameRole="surface"] {{
    background-color: {C['BG_SURFACE']};
    border-radius: {Radius.LG}px;
    border: 1px solid {C['BORDER']};
}}

QFrame[frameRole="elevated"] {{
    background-color: {C['BG_ELEVATED']};
    border-radius: {Radius.MD}px;
    border: 1px solid {C['BORDER']};
}}

/* --- Labels --- */
QLabel {{
    background-color: transparent;
    color: {C['TEXT_PRIMARY']};
}}

QLabel[role="heading1"] {{
    font-size: {Fonts.SIZE_2XL}pt;
    font-weight: bold;
}}

QLabel[role="heading2"] {{
    font-size: {Fonts.SIZE_XL}pt;
    font-weight: bold;
}}

QLabel[role="caption"] {{
    font-size: {Fonts.SIZE_SM}pt;
    color: {C['TEXT_SECONDARY']};
}}

QLabel[role="badge-success"] {{
    background-color: {C['SUCCESS_BG']};
    color: {C['SUCCESS']};
    border-radius: {Radius.SM}px;
    padding: 2px 8px;
    font-size: {Fonts.SIZE_SM}pt;
    font-weight: bold;
}}

QLabel[role="badge-error"] {{
    background-color: {C['ERROR_BG']};
    color: {C['ERROR']};
    border-radius: {Radius.SM}px;
    padding: 2px 8px;
    font-size: {Fonts.SIZE_SM}pt;
    font-weight: bold;
}}

QLabel[role="badge-warning"] {{
    background-color: {C['WARNING_BG']};
    color: {C['WARNING']};
    border-radius: {Radius.SM}px;
    padding: 2px 8px;
    font-size: {Fonts.SIZE_SM}pt;
    font-weight: bold;
}}

/* --- Eingabefelder --- */
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QDateEdit {{
    background-color: {C['BG_INPUT']};
    color: {C['TEXT_PRIMARY']};
    border: 1px solid {C['BORDER']};
    border-radius: {Radius.MD}px;
    padding: 6px 10px;
    font-size: {Fonts.SIZE_BASE}pt;
    selection-background-color: {C['PRIMARY']};
}}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus, QDateEdit:focus {{
    border: 2px solid {C['BORDER_FOCUS']};
    background-color: {C['BG_ELEVATED']};
}}

QLineEdit:disabled, QTextEdit:disabled {{
    color: {C['TEXT_DISABLED']};
    background-color: {C['BG_SURFACE']};
    border-color: {C['BORDER']};
}}

QLineEdit[valid="false"], QComboBox[valid="false"] {{
    border-color: {C['BORDER_ERROR']};
}}

/* --- Combobox --- */
QComboBox {{
    background-color: {C['BG_INPUT']};
    color: {C['TEXT_PRIMARY']};
    border: 1px solid {C['BORDER']};
    border-radius: {Radius.MD}px;
    padding: 6px 10px;
    min-height: 28px;
}}

QComboBox:focus {{
    border: 2px solid {C['BORDER_FOCUS']};
}}

QComboBox::drop-down {{
    border: none;
    width: 28px;
}}

QComboBox::down-arrow {{
    width: 12px;
    height: 12px;
}}

QComboBox QAbstractItemView {{
    background-color: {C['BG_ELEVATED']};
    border: 1px solid {C['BORDER']};
    border-radius: {Radius.MD}px;
    color: {C['TEXT_PRIMARY']};
    selection-background-color: {C['PRIMARY']};
    selection-color: white;
    outline: none;
}}

/* --- Buttons --- */
QPushButton {{
    background-color: {C['PRIMARY']};
    color: white;
    border: 1px solid {C['PRIMARY_HOVER']};
    border-radius: {Radius.MD}px;
    padding: 8px 16px;
    font-size: {Fonts.SIZE_BASE}pt;
    font-weight: bold;
    min-height: 32px;
}}

QPushButton:hover {{
    background-color: {C['PRIMARY_HOVER']};
    border-color: {C['PRIMARY_DARK']};
}}

QPushButton:pressed {{
    background-color: {C['PRIMARY_DARK']};
}}

QPushButton:disabled {{
    background-color: {C['BG_ELEVATED']};
    color: {C['TEXT_DISABLED']};
    border: 1px solid {C['BORDER']};
}}

QPushButton[role="primary"] {{
    background-color: {C['PRIMARY']};
    color: white;
    border: 1px solid {C['PRIMARY_DARK']};
    font-weight: bold;
}}

QPushButton[role="primary"]:hover {{
    background-color: {C['PRIMARY_HOVER']};
    border-color: {C['PRIMARY_DARK']};
}}

QPushButton[role="secondary"] {{
    background-color: {C['BG_ELEVATED']};
    color: {C['TEXT_PRIMARY']};
    border: 1px solid {C['TEXT_DISABLED']};
}}

QPushButton[role="secondary"]:hover {{
    background-color: {C['BG_ELEVATED']};
    border-color: {C['TEXT_SECONDARY']};
}}

QPushButton[role="danger"] {{
    background-color: {C['ERROR']};
    color: white;
    border: 1px solid #DC2626;
}}

QPushButton[role="danger"]:hover {{
    background-color: #DC2626;
    border-color: #B91C1C;
}}

QPushButton[role="success"] {{
    background-color: {C['SUCCESS']};
    color: white;
    border: 1px solid #059669;
}}

QPushButton[role="success"]:hover {{
    background-color: #059669;
    border-color: #047857;
}}

QPushButton[role="ghost"] {{
    background-color: transparent;
    color: {C['TEXT_SECONDARY']};
    border: none;
    font-weight: normal;
    padding: 2px;
    min-height: 0px;
}}

QPushButton[role="ghost"]:hover {{
    color: {C['TEXT_PRIMARY']};
    background-color: {C['BG_ELEVATED']};
}}

/* --- Tabellen --- */
QTableWidget, QTreeWidget, QTreeView, QTableView, QListWidget, QListView {{
    background-color: {C['BG_SURFACE']};
    alternate-background-color: {C['TABLE_ROW_ALT']};
    color: {C['TEXT_PRIMARY']};
    border: 1px solid {C['BORDER']};
    border-radius: {Radius.MD}px;
    gridline-color: {C['BORDER']};
    outline: none;
}}

QTableWidget::item, QTreeWidget::item, QListWidget::item {{
    padding: 6px 8px;
    border-bottom: 1px solid {C['BORDER']};
}}

QTableWidget::item:selected, QTreeWidget::item:selected,
QListWidget::item:selected, QTreeView::item:selected {{
    background-color: {C['TABLE_SELECTED']};
    color: white;
}}

QTableWidget::item:hover, QTreeWidget::item:hover,
QListWidget::item:hover {{
    background-color: {C['TABLE_HOVER']};
}}

QHeaderView::section {{
    background-color: {C['TABLE_HEADER_BG']};
    color: {C['TEXT_SECONDARY']};
    border: none;
    border-right: 1px solid {C['BORDER']};
    border-bottom: 2px solid {C['BORDER']};
    padding: 8px 10px;
    font-weight: bold;
    font-size: {Fonts.SIZE_SM}pt;
    text-transform: uppercase;
}}

QHeaderView::section:hover {{
    background-color: {C['BG_ELEVATED']};
    color: {C['TEXT_PRIMARY']};
}}

/* --- Scrollbars --- */
QScrollBar:vertical {{
    background-color: {C['BG_SURFACE']};
    width: 8px;
    border-radius: 4px;
}}

QScrollBar::handle:vertical {{
    background-color: {C['BORDER']};
    border-radius: 4px;
    min-height: 30px;
}}

QScrollBar::handle:vertical:hover {{
    background-color: {C['TEXT_DISABLED']};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

QScrollBar:horizontal {{
    background-color: {C['BG_SURFACE']};
    height: 8px;
    border-radius: 4px;
}}

QScrollBar::handle:horizontal {{
    background-color: {C['BORDER']};
    border-radius: 4px;
    min-width: 30px;
}}

QScrollBar::handle:horizontal:hover {{
    background-color: {C['TEXT_DISABLED']};
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}

/* --- Tabs --- */
QTabWidget::pane {{
    background-color: {C['BG_SURFACE']};
    border: 1px solid {C['BORDER']};
    border-radius: {Radius.MD}px;
    top: -1px;
}}

QTabBar::tab {{
    background-color: transparent;
    color: {C['TEXT_SECONDARY']};
    padding: 8px 16px;
    border-bottom: 2px solid transparent;
    margin-right: 2px;
}}

QTabBar::tab:selected {{
    color: {C['PRIMARY']};
    border-bottom: 2px solid {C['PRIMARY']};
}}

QTabBar::tab:hover {{
    color: {C['TEXT_PRIMARY']};
    background-color: {C['BG_ELEVATED']};
}}

/* --- Dialoge --- */
QDialog {{
    background-color: {C['BG_SURFACE']};
    border-radius: {Radius.LG}px;
}}

/* --- Menü --- */
QMenuBar {{
    background-color: {C['BG_APP']};
    color: {C['TEXT_PRIMARY']};
    padding: 2px;
}}

QMenuBar::item:selected {{
    background-color: {C['BG_ELEVATED']};
    border-radius: {Radius.SM}px;
}}

QMenu {{
    background-color: {C['BG_ELEVATED']};
    border: 1px solid {C['BORDER']};
    border-radius: {Radius.MD}px;
    padding: 4px;
}}

QMenu::item {{
    padding: 6px 24px;
    border-radius: {Radius.SM}px;
}}

QMenu::item:selected {{
    background-color: {C['PRIMARY']};
    color: white;
}}

QMenu::separator {{
    height: 1px;
    background-color: {C['BORDER']};
    margin: 4px 8px;
}}

/* --- Checkboxen / Radiobuttons --- */
QCheckBox, QRadioButton {{
    color: {C['TEXT_PRIMARY']};
    spacing: 8px;
}}

QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border: 2px solid {C['BORDER']};
    border-radius: {Radius.SM}px;
    background-color: {C['BG_INPUT']};
}}

QCheckBox::indicator:checked {{
    background-color: {C['PRIMARY']};
    border-color: {C['PRIMARY']};
}}

QCheckBox::indicator:hover {{
    border-color: {C['BORDER_FOCUS']};
}}

/* --- Statusleiste --- */
QStatusBar {{
    background-color: {C['BG_SURFACE']};
    color: {C['TEXT_SECONDARY']};
    border-top: 1px solid {C['BORDER']};
    font-size: {Fonts.SIZE_SM}pt;
}}

/* --- Splitter --- */
QSplitter::handle {{
    background-color: {C['BORDER']};
}}

/* --- Tooltip --- */
QToolTip {{
    background-color: {C['BG_ELEVATED']};
    color: {C['TEXT_PRIMARY']};
    border: 1px solid {C['BORDER']};
    border-radius: {Radius.SM}px;
    padding: 4px 8px;
    font-size: {Fonts.SIZE_SM}pt;
}}

/* --- GroupBox --- */
QGroupBox {{
    border: 1px solid {C['BORDER']};
    border-radius: {Radius.MD}px;
    margin-top: 12px;
    padding-top: 8px;
    color: {C['TEXT_SECONDARY']};
    font-size: {Fonts.SIZE_SM}pt;
    font-weight: bold;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 6px;
    left: 10px;
}}

/* --- Progress Bar --- */
QProgressBar {{
    background-color: {C['BG_INPUT']};
    border: 1px solid {C['BORDER']};
    border-radius: {Radius.SM}px;
    height: 8px;
    text-align: center;
    color: transparent;
}}

QProgressBar::chunk {{
    background-color: {C['PRIMARY']};
    border-radius: {Radius.SM}px;
}}

/* --- Slider --- */
QSlider::groove:horizontal {{
    height: 4px;
    background-color: {C['BORDER']};
    border-radius: 2px;
}}

QSlider::handle:horizontal {{
    background-color: {C['PRIMARY']};
    width: 16px;
    height: 16px;
    margin: -6px 0;
    border-radius: 8px;
}}

QSlider::sub-page:horizontal {{
    background-color: {C['PRIMARY']};
    border-radius: 2px;
}}
""" + (_light_overrides(C) if _current_mode == "light" else "")


# Für Rückwärtskompatibilität: MAIN_STYLESHEET als Property
MAIN_STYLESHEET = _build_stylesheet()


def _apply_palette(app: QApplication) -> None:
    """Setzt die Qt-Palette passend zum aktuellen Modus."""
    C = _get_colors_dict()
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(C['BG_APP']))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(C['TEXT_PRIMARY']))
    palette.setColor(QPalette.ColorRole.Base, QColor(C['BG_SURFACE']))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(C['TABLE_ROW_ALT']))
    palette.setColor(QPalette.ColorRole.Text, QColor(C['TEXT_PRIMARY']))
    palette.setColor(QPalette.ColorRole.Button, QColor(C['BG_ELEVATED']))
    # ButtonText wird NICHT gesetzt – Stylesheet steuert Button-Farben
    palette.setColor(QPalette.ColorRole.Highlight, QColor(C['PRIMARY']))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(C['BG_ELEVATED']))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(C['TEXT_PRIMARY']))
    app.setPalette(palette)


def apply_theme(app: QApplication, mode: str = None) -> None:
    """
    Wendet das OpenPhoenix-Theme auf die gesamte Anwendung an.

    Args:
        app:  Die QApplication-Instanz
        mode: "dark" oder "light" (None = aus Config lesen)
    """
    global _current_mode, MAIN_STYLESHEET

    if mode is None:
        try:
            from core.config import config
            mode = config.get("app", "theme", "dark")
        except Exception:
            mode = "dark"

    _current_mode = mode if mode in ("dark", "light") else "dark"

    MAIN_STYLESHEET = _build_stylesheet()
    _apply_palette(app)       # Palette VOR Stylesheet – CSS hat dann Vorrang
    app.setStyleSheet(MAIN_STYLESHEET)
    app.setFont(Fonts.body())


def get_current_mode() -> str:
    """Gibt den aktuellen Theme-Modus zurück ('dark' oder 'light')."""
    return _current_mode


def switch_theme(app: QApplication, mode: str) -> None:
    """
    Wechselt das Theme zur Laufzeit und speichert die Einstellung.

    Args:
        app:  Die QApplication-Instanz
        mode: "dark" oder "light"
    """
    apply_theme(app, mode)
    _notify_listeners()
    try:
        from core.config import config
        config.set("app", "theme", mode)
        config.save()
    except Exception:
        pass
