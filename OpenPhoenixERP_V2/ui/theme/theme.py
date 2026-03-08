"""
ui/theme/theme.py – Design-System für OpenPhoenix ERP
======================================================
Zentrales, konsistentes Design für die gesamte Anwendung.
Farben, Schriften, Abstände und Stile sind hier definiert —
kein magic number irgendwo im UI-Code.
"""

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt


# ---------------------------------------------------------------------------
# Farben
# ---------------------------------------------------------------------------

class Colors:
    """OpenPhoenix ERP Farbpalette."""

    # Primärfarben
    PRIMARY          = "#2563EB"   # Blau – Buttons, Akzente
    PRIMARY_HOVER    = "#1D4ED8"
    PRIMARY_LIGHT    = "#EFF6FF"
    PRIMARY_DARK     = "#1E3A5F"

    # Neutrale Töne
    BG_APP           = "#0F172A"   # Dunkelster Hintergrund (App-Ebene)
    BG_SURFACE       = "#1E293B"   # Karten, Panels
    BG_ELEVATED      = "#273449"   # Erhöhte Elemente (Dialoge, Dropdowns)
    BG_INPUT         = "#1A2540"   # Eingabefelder

    # Seitenleiste
    SIDEBAR_BG       = "#0F172A"
    SIDEBAR_ITEM     = "#1E293B"
    SIDEBAR_ACTIVE   = "#2563EB"
    SIDEBAR_HOVER    = "#1E3A5F"
    SIDEBAR_TEXT     = "#94A3B8"
    SIDEBAR_TEXT_ACT = "#FFFFFF"

    # Text
    TEXT_PRIMARY     = "#F1F5F9"   # Haupttext
    TEXT_SECONDARY   = "#94A3B8"   # Beschriftungen, Hinweise
    TEXT_DISABLED    = "#475569"
    TEXT_INVERSE     = "#0F172A"   # Text auf hellen Backgrounds

    # Rahmen
    BORDER           = "#334155"
    BORDER_FOCUS     = "#2563EB"
    BORDER_ERROR     = "#EF4444"

    # Status-Farben
    SUCCESS          = "#10B981"
    SUCCESS_BG       = "#064E3B"
    WARNING          = "#F59E0B"
    WARNING_BG       = "#451A03"
    ERROR            = "#EF4444"
    ERROR_BG         = "#450A0A"
    INFO             = "#3B82F6"
    INFO_BG          = "#1E3A5F"

    # Rechnungsstatus
    STATUS_ENTWURF         = "#94A3B8"
    STATUS_OFFEN           = "#3B82F6"
    STATUS_ERINNERUNG      = "#F59E0B"
    STATUS_MAHNUNG         = "#F97316"
    STATUS_MAHNUNG2        = "#EF4444"
    STATUS_INKASSO         = "#DC2626"
    STATUS_BEZAHLT         = "#10B981"
    STATUS_STORNIERT       = "#475569"
    STATUS_GUTSCHRIFT      = "#8B5CF6"

    # Tabellen
    TABLE_HEADER_BG  = "#1E293B"
    TABLE_ROW_ALT    = "#1A2540"
    TABLE_SELECTED   = "#1D4ED8"
    TABLE_HOVER      = "#273449"


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
# Haupt-Stylesheet
# ---------------------------------------------------------------------------

MAIN_STYLESHEET = f"""
/* ===================================================
   OpenPhoenix ERP – Globales Stylesheet
   =================================================== */

QWidget {{
    background-color: {Colors.BG_APP};
    color: {Colors.TEXT_PRIMARY};
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: {Fonts.SIZE_BASE}pt;
    border: none;
    outline: none;
}}

/* --- Hauptfenster --- */
QMainWindow {{
    background-color: {Colors.BG_APP};
}}

/* --- Frames / Container --- */
QFrame {{
    background-color: transparent;
}}

QFrame[frameRole="surface"] {{
    background-color: {Colors.BG_SURFACE};
    border-radius: {Radius.LG}px;
    border: 1px solid {Colors.BORDER};
}}

QFrame[frameRole="elevated"] {{
    background-color: {Colors.BG_ELEVATED};
    border-radius: {Radius.MD}px;
    border: 1px solid {Colors.BORDER};
}}

/* --- Labels --- */
QLabel {{
    background-color: transparent;
    color: {Colors.TEXT_PRIMARY};
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
    color: {Colors.TEXT_SECONDARY};
}}

QLabel[role="badge-success"] {{
    background-color: {Colors.SUCCESS_BG};
    color: {Colors.SUCCESS};
    border-radius: {Radius.SM}px;
    padding: 2px 8px;
    font-size: {Fonts.SIZE_SM}pt;
    font-weight: bold;
}}

QLabel[role="badge-error"] {{
    background-color: {Colors.ERROR_BG};
    color: {Colors.ERROR};
    border-radius: {Radius.SM}px;
    padding: 2px 8px;
    font-size: {Fonts.SIZE_SM}pt;
    font-weight: bold;
}}

QLabel[role="badge-warning"] {{
    background-color: {Colors.WARNING_BG};
    color: {Colors.WARNING};
    border-radius: {Radius.SM}px;
    padding: 2px 8px;
    font-size: {Fonts.SIZE_SM}pt;
    font-weight: bold;
}}

/* --- Eingabefelder --- */
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QDateEdit {{
    background-color: {Colors.BG_INPUT};
    color: {Colors.TEXT_PRIMARY};
    border: 1px solid {Colors.BORDER};
    border-radius: {Radius.MD}px;
    padding: 6px 10px;
    font-size: {Fonts.SIZE_BASE}pt;
    selection-background-color: {Colors.PRIMARY};
}}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus, QDateEdit:focus {{
    border: 2px solid {Colors.BORDER_FOCUS};
    background-color: {Colors.BG_ELEVATED};
}}

QLineEdit:disabled, QTextEdit:disabled {{
    color: {Colors.TEXT_DISABLED};
    background-color: {Colors.BG_SURFACE};
    border-color: {Colors.BORDER};
}}

QLineEdit[valid="false"], QComboBox[valid="false"] {{
    border-color: {Colors.BORDER_ERROR};
}}

/* --- Combobox --- */
QComboBox {{
    background-color: {Colors.BG_INPUT};
    color: {Colors.TEXT_PRIMARY};
    border: 1px solid {Colors.BORDER};
    border-radius: {Radius.MD}px;
    padding: 6px 10px;
    min-height: 28px;
}}

QComboBox:focus {{
    border: 2px solid {Colors.BORDER_FOCUS};
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
    background-color: {Colors.BG_ELEVATED};
    border: 1px solid {Colors.BORDER};
    border-radius: {Radius.MD}px;
    color: {Colors.TEXT_PRIMARY};
    selection-background-color: {Colors.PRIMARY};
    selection-color: white;
    outline: none;
}}

/* --- Buttons --- */
QPushButton {{
    background-color: {Colors.PRIMARY};
    color: white;
    border: none;
    border-radius: {Radius.MD}px;
    padding: 8px 16px;
    font-size: {Fonts.SIZE_BASE}pt;
    font-weight: bold;
    min-height: 32px;
}}

QPushButton:hover {{
    background-color: {Colors.PRIMARY_HOVER};
}}

QPushButton:pressed {{
    background-color: {Colors.PRIMARY_DARK};
}}

QPushButton:disabled {{
    background-color: {Colors.BG_ELEVATED};
    color: {Colors.TEXT_DISABLED};
}}

QPushButton[role="secondary"] {{
    background-color: transparent;
    color: {Colors.TEXT_PRIMARY};
    border: 1px solid {Colors.BORDER};
}}

QPushButton[role="secondary"]:hover {{
    background-color: {Colors.BG_ELEVATED};
    border-color: {Colors.TEXT_SECONDARY};
}}

QPushButton[role="danger"] {{
    background-color: {Colors.ERROR};
}}

QPushButton[role="danger"]:hover {{
    background-color: #DC2626;
}}

QPushButton[role="success"] {{
    background-color: {Colors.SUCCESS};
    color: white;
}}

QPushButton[role="success"]:hover {{
    background-color: #059669;
}}

QPushButton[role="ghost"] {{
    background-color: transparent;
    color: {Colors.TEXT_SECONDARY};
    border: none;
    font-weight: normal;
}}

QPushButton[role="ghost"]:hover {{
    color: {Colors.TEXT_PRIMARY};
    background-color: {Colors.BG_ELEVATED};
}}

/* --- Tabellen --- */
QTableWidget, QTreeWidget, QTreeView, QTableView, QListWidget, QListView {{
    background-color: {Colors.BG_SURFACE};
    alternate-background-color: {Colors.TABLE_ROW_ALT};
    color: {Colors.TEXT_PRIMARY};
    border: 1px solid {Colors.BORDER};
    border-radius: {Radius.MD}px;
    gridline-color: {Colors.BORDER};
    outline: none;
}}

QTableWidget::item, QTreeWidget::item, QListWidget::item {{
    padding: 6px 8px;
    border-bottom: 1px solid {Colors.BORDER};
}}

QTableWidget::item:selected, QTreeWidget::item:selected,
QListWidget::item:selected, QTreeView::item:selected {{
    background-color: {Colors.TABLE_SELECTED};
    color: white;
}}

QTableWidget::item:hover, QTreeWidget::item:hover,
QListWidget::item:hover {{
    background-color: {Colors.TABLE_HOVER};
}}

QHeaderView::section {{
    background-color: {Colors.TABLE_HEADER_BG};
    color: {Colors.TEXT_SECONDARY};
    border: none;
    border-right: 1px solid {Colors.BORDER};
    border-bottom: 2px solid {Colors.BORDER};
    padding: 8px 10px;
    font-weight: bold;
    font-size: {Fonts.SIZE_SM}pt;
    text-transform: uppercase;
}}

QHeaderView::section:hover {{
    background-color: {Colors.BG_ELEVATED};
    color: {Colors.TEXT_PRIMARY};
}}

/* --- Scrollbars --- */
QScrollBar:vertical {{
    background-color: {Colors.BG_SURFACE};
    width: 8px;
    border-radius: 4px;
}}

QScrollBar::handle:vertical {{
    background-color: {Colors.BORDER};
    border-radius: 4px;
    min-height: 30px;
}}

QScrollBar::handle:vertical:hover {{
    background-color: {Colors.TEXT_DISABLED};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

QScrollBar:horizontal {{
    background-color: {Colors.BG_SURFACE};
    height: 8px;
    border-radius: 4px;
}}

QScrollBar::handle:horizontal {{
    background-color: {Colors.BORDER};
    border-radius: 4px;
    min-width: 30px;
}}

QScrollBar::handle:horizontal:hover {{
    background-color: {Colors.TEXT_DISABLED};
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}

/* --- Tabs --- */
QTabWidget::pane {{
    background-color: {Colors.BG_SURFACE};
    border: 1px solid {Colors.BORDER};
    border-radius: {Radius.MD}px;
    top: -1px;
}}

QTabBar::tab {{
    background-color: transparent;
    color: {Colors.TEXT_SECONDARY};
    padding: 8px 16px;
    border-bottom: 2px solid transparent;
    margin-right: 2px;
}}

QTabBar::tab:selected {{
    color: {Colors.PRIMARY};
    border-bottom: 2px solid {Colors.PRIMARY};
}}

QTabBar::tab:hover {{
    color: {Colors.TEXT_PRIMARY};
    background-color: {Colors.BG_ELEVATED};
}}

/* --- Dialoge --- */
QDialog {{
    background-color: {Colors.BG_SURFACE};
    border-radius: {Radius.LG}px;
}}

/* --- Menü --- */
QMenuBar {{
    background-color: {Colors.BG_APP};
    color: {Colors.TEXT_PRIMARY};
    padding: 2px;
}}

QMenuBar::item:selected {{
    background-color: {Colors.BG_ELEVATED};
    border-radius: {Radius.SM}px;
}}

QMenu {{
    background-color: {Colors.BG_ELEVATED};
    border: 1px solid {Colors.BORDER};
    border-radius: {Radius.MD}px;
    padding: 4px;
}}

QMenu::item {{
    padding: 6px 24px;
    border-radius: {Radius.SM}px;
}}

QMenu::item:selected {{
    background-color: {Colors.PRIMARY};
    color: white;
}}

QMenu::separator {{
    height: 1px;
    background-color: {Colors.BORDER};
    margin: 4px 8px;
}}

/* --- Checkboxen / Radiobuttons --- */
QCheckBox, QRadioButton {{
    color: {Colors.TEXT_PRIMARY};
    spacing: 8px;
}}

QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border: 2px solid {Colors.BORDER};
    border-radius: {Radius.SM}px;
    background-color: {Colors.BG_INPUT};
}}

QCheckBox::indicator:checked {{
    background-color: {Colors.PRIMARY};
    border-color: {Colors.PRIMARY};
}}

QCheckBox::indicator:hover {{
    border-color: {Colors.BORDER_FOCUS};
}}

/* --- Statusleiste --- */
QStatusBar {{
    background-color: {Colors.BG_SURFACE};
    color: {Colors.TEXT_SECONDARY};
    border-top: 1px solid {Colors.BORDER};
    font-size: {Fonts.SIZE_SM}pt;
}}

/* --- Splitter --- */
QSplitter::handle {{
    background-color: {Colors.BORDER};
}}

/* --- Tooltip --- */
QToolTip {{
    background-color: {Colors.BG_ELEVATED};
    color: {Colors.TEXT_PRIMARY};
    border: 1px solid {Colors.BORDER};
    border-radius: {Radius.SM}px;
    padding: 4px 8px;
    font-size: {Fonts.SIZE_SM}pt;
}}

/* --- GroupBox --- */
QGroupBox {{
    border: 1px solid {Colors.BORDER};
    border-radius: {Radius.MD}px;
    margin-top: 12px;
    padding-top: 8px;
    color: {Colors.TEXT_SECONDARY};
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
    background-color: {Colors.BG_INPUT};
    border: 1px solid {Colors.BORDER};
    border-radius: {Radius.SM}px;
    height: 8px;
    text-align: center;
    color: transparent;
}}

QProgressBar::chunk {{
    background-color: {Colors.PRIMARY};
    border-radius: {Radius.SM}px;
}}

/* --- Slider --- */
QSlider::groove:horizontal {{
    height: 4px;
    background-color: {Colors.BORDER};
    border-radius: 2px;
}}

QSlider::handle:horizontal {{
    background-color: {Colors.PRIMARY};
    width: 16px;
    height: 16px;
    margin: -6px 0;
    border-radius: 8px;
}}

QSlider::sub-page:horizontal {{
    background-color: {Colors.PRIMARY};
    border-radius: 2px;
}}
"""


def apply_theme(app: QApplication) -> None:
    """Wendet das OpenPhoenix-Theme auf die gesamte Anwendung an."""
    app.setStyleSheet(MAIN_STYLESHEET)
    app.setFont(Fonts.body())

    # Dark-Mode Palette setzen (verhindert weiße Flackerer beim Start)
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(Colors.BG_APP))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(Colors.TEXT_PRIMARY))
    palette.setColor(QPalette.ColorRole.Base, QColor(Colors.BG_SURFACE))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(Colors.TABLE_ROW_ALT))
    palette.setColor(QPalette.ColorRole.Text, QColor(Colors.TEXT_PRIMARY))
    palette.setColor(QPalette.ColorRole.Button, QColor(Colors.BG_ELEVATED))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(Colors.TEXT_PRIMARY))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(Colors.PRIMARY))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(Colors.BG_ELEVATED))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(Colors.TEXT_PRIMARY))
    app.setPalette(palette)
