"""
ui/modules/dashboard/panel.py – Übersichts-Dashboard
=====================================================
Zeigt die wichtigsten Kennzahlen auf einen Blick:
- KPI-Kacheln: Kunden, offene Rechnungen, Umsatz, Mahnwesen
- Balkendiagramm: Umsatz der letzten 6 Monate
- Letzte Aktivitäten: Neueste Rechnungen & überfällige Posten
"""

import logging
from decimal import Decimal
from datetime import date, datetime, timedelta
from typing import Optional

from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QColor, QPainter, QPen, QBrush, QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QSizePolicy, QGridLayout,
)

from core.db.engine import db
from core.config import config
from ui.components.widgets import NotificationBanner, SectionTitle, StatusBadge
from ui.theme.theme import Colors, Fonts, Spacing, Radius, on_theme_changed, get_current_mode

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Hilfsfunktion Währungsformatierung
# ---------------------------------------------------------------------------

def _badge_bg(accent_color: str) -> str:
    """Gibt einen theme-passenden Badge-Hintergrund zurück."""
    mode = get_current_mode()
    if mode == "light":
        # Im Light Mode: helle, desaturierte Hintergründe
        # Wir erzeugen ein transparentes Farb-Overlay via QColor
        c = QColor(accent_color)
        c.setAlpha(20)
        # Aber CSS unterstützt kein rgba bei setStyleSheet direkt mit QColor
        # Daher nutzen wir vordefinierte helle Farben
        error_hex   = "#DC2626"
        warning_hex = "#D97706"
        success_hex = "#059669"
        info_hex    = "#2563EB"
        primary_hex = "#2563EB"
        color_map = {
            error_hex:   "#FEF2F2",
            warning_hex: "#FFFBEB",
            success_hex: "#F0FDF4",
            info_hex:    "#EFF6FF",
            primary_hex: "#EFF6FF",
        }
        # Auch dark-mode Varianten mappen (falls accent_color aus Dark-Mode stammt)
        color_map.update({
            "#EF4444": "#FEF2F2",
            "#F59E0B": "#FFFBEB",
            "#10B981": "#F0FDF4",
            "#3B82F6": "#EFF6FF",
        })
        return color_map.get(accent_color, "#F1F5F9")
    else:
        return f"{accent_color}21"


def _fmt(v: Decimal) -> str:
    return f"{v:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


# ---------------------------------------------------------------------------
# KPI-Kachel
# ---------------------------------------------------------------------------

class KPICard(QFrame):
    """Eine einzelne Kennzahl-Kachel mit Icon, Wert und Beschriftung."""

    def __init__(
        self,
        icon: str,
        title: str,
        accent_color: str = Colors.PRIMARY,
        parent=None,
    ):
        super().__init__(parent)
        self._accent = accent_color
        self._icon_str = icon
        self._title_str = title
        self.setMinimumSize(190, 120)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_style(hover=False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.MD)
        layout.setSpacing(2)

        # Kopfzeile: Icon-Badge + Titel
        head = QHBoxLayout()
        head.setSpacing(Spacing.SM)

        icon_badge = QFrame()
        icon_badge.setFixedSize(36, 36)
        icon_badge.setStyleSheet(f"""
            QFrame {{
                background-color: {_badge_bg(accent_color)};
                border-radius: 10px;
                border: none;
            }}
        """)
        badge_layout = QVBoxLayout(icon_badge)
        badge_layout.setContentsMargins(0, 0, 0, 0)
        icon_lbl = QLabel(icon)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet("font-size: 17px; background: transparent;")
        badge_layout.addWidget(icon_lbl)

        head.addWidget(icon_badge)
        title_lbl = QLabel(title)
        title_lbl.setFont(Fonts.get(Fonts.SIZE_SM))
        title_lbl.setWordWrap(True)
        title_lbl.setStyleSheet(
            f"color: {Colors.TEXT_SECONDARY}; background: transparent;"
        )
        head.addWidget(title_lbl, 1)
        layout.addLayout(head)

        layout.addSpacing(Spacing.XS)

        # Hauptwert
        self._value_lbl = QLabel("–")
        self._value_lbl.setFont(Fonts.get(Fonts.SIZE_2XL, bold=True))
        self._value_lbl.setStyleSheet(
            f"color: {Colors.TEXT_PRIMARY}; background: transparent;"
        )
        layout.addWidget(self._value_lbl)

        # Untertitel / Delta
        self._sub_lbl = QLabel("")
        self._sub_lbl.setFont(Fonts.caption())
        self._sub_lbl.setStyleSheet(
            f"color: {accent_color}; background: transparent; font-weight: bold;"
        )
        layout.addWidget(self._sub_lbl)

        # Accent-Linie unten
        layout.addStretch()
        accent_line = QFrame()
        accent_line.setFixedHeight(3)
        accent_line.setStyleSheet(f"""
            QFrame {{
                background-color: {accent_color};
                border-radius: 2px;
                border: none;
            }}
        """)
        layout.addWidget(accent_line)

    def _apply_style(self, hover: bool) -> None:
        bg = Colors.BG_ELEVATED if hover else Colors.BG_SURFACE
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {bg};
                border: 1px solid {Colors.BORDER};
                border-radius: {Radius.XL}px;
            }}
        """)

    def enterEvent(self, event):
        self._apply_style(hover=True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._apply_style(hover=False)
        super().leaveEvent(event)

    def set_value(self, value: str, subtitle: str = "") -> None:
        self._value_lbl.setText(value)
        self._sub_lbl.setText(subtitle)
        self._sub_lbl.setVisible(bool(subtitle))


# ---------------------------------------------------------------------------
# Einfaches Balkendiagramm (ohne externe Bibliothek)
# ---------------------------------------------------------------------------

class BalkenDiagramm(QWidget):
    """
    Modernes monatliches Balkendiagramm mit Wert-Labels und Hover-Highlight.
    Zeigt Brutto-Umsatz der letzten N Monate.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._daten: list[tuple[str, Decimal]] = []
        self._hover_idx: int = -1
        self.setMinimumHeight(200)
        self.setMouseTracking(True)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )

    def set_daten(self, daten: list[tuple[str, Decimal]]) -> None:
        """daten = [(Monatsname, Brutto-Summe), ...]"""
        self._daten = daten
        self.update()

    def mouseMoveEvent(self, event):
        if not self._daten:
            return
        w = self.width()
        h = self.height()
        pad_l, pad_r, pad_t, pad_b = 52, 16, 24, 40
        n = len(self._daten)
        bar_area_w = w - pad_l - pad_r
        bar_w = max(10, int(bar_area_w / n * 0.55))
        gap = (bar_area_w - bar_w * n) // max(n - 1, 1) if n > 1 else 0
        x_mouse = event.position().x()
        new_hover = -1
        for i in range(n):
            x = pad_l + i * (bar_w + gap)
            if x - 4 <= x_mouse <= x + bar_w + 4:
                new_hover = i
                break
        if new_hover != self._hover_idx:
            self._hover_idx = new_hover
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._hover_idx = -1
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        if not self._daten:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        w = self.width()
        h = self.height()
        pad_l, pad_r, pad_t, pad_b = 52, 16, 24, 40

        max_val = max((v for _, v in self._daten), default=Decimal("1"))
        if max_val == 0:
            max_val = Decimal("1")

        n = len(self._daten)
        bar_area_w = w - pad_l - pad_r
        bar_w = max(10, int(bar_area_w / n * 0.55))
        gap = (bar_area_w - bar_w * n) // max(n - 1, 1) if n > 1 else 0

        accent_color = QColor(Colors.PRIMARY)
        accent_dim = QColor(Colors.PRIMARY)
        accent_dim.setAlpha(110)
        accent_hover = QColor(Colors.PRIMARY)
        accent_hover.setAlpha(255)

        # Hintergrund-Raster (feine horizontale Linien)
        grid_pen = QPen(QColor(Colors.BORDER))
        grid_pen.setStyle(Qt.PenStyle.DashLine)
        grid_pen.setWidth(1)
        steps = 4
        for i in range(1, steps + 1):
            y = pad_t + int((h - pad_t - pad_b) * (1 - i / steps))
            painter.setPen(grid_pen)
            painter.drawLine(pad_l, y, w - pad_r, y)
            # Y-Label
            val_label = _fmt(max_val * i / steps).replace(" €", "")
            painter.setPen(QPen(QColor(Colors.TEXT_DISABLED)))
            painter.setFont(QFont("Segoe UI", 8))
            painter.drawText(0, y - 8, pad_l - 6, 16,
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             val_label)

        # X-Achse
        painter.setPen(QPen(QColor(Colors.BORDER), 1))
        painter.drawLine(pad_l, h - pad_b, w - pad_r, h - pad_b)

        # Balken + Labels
        for i, (label, val) in enumerate(self._daten):
            x = pad_l + i * (bar_w + gap)
            bar_h = max(3, int((h - pad_t - pad_b) * float(val / max_val)))
            y_bar = h - pad_b - bar_h

            is_hover = (i == self._hover_idx)
            is_last = (i == len(self._daten) - 1)

            if is_hover:
                color = accent_hover
            elif is_last:
                color = QColor(Colors.PRIMARY)
                color.setAlpha(230)
            else:
                color = accent_dim

            painter.setBrush(QBrush(color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(x, y_bar, bar_w, bar_h, 4, 4)

            # Wert-Label über Balken (nur bei Hover oder letztem Monat)
            if is_hover or is_last:
                val_str = _fmt(val)
                painter.setPen(QPen(QColor(Colors.TEXT_PRIMARY)))
                painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
                painter.drawText(
                    x - 20, y_bar - 20, bar_w + 40, 18,
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                    val_str
                )

            # Monats-Label
            label_color = QColor(Colors.TEXT_PRIMARY) if (is_hover or is_last) else QColor(Colors.TEXT_SECONDARY)
            painter.setPen(QPen(label_color))
            painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold if (is_hover or is_last) else QFont.Weight.Normal))
            painter.drawText(
                x - 6, h - pad_b + 6, bar_w + 12, 22,
                Qt.AlignmentFlag.AlignHCenter, label
            )

        painter.end()


# ---------------------------------------------------------------------------
# Aktivitätsliste (letzte Rechnungen)
# ---------------------------------------------------------------------------

class AktivitaetsListe(QFrame):
    """Zeigt die letzten N Rechnungen als kompakte Liste."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QFrame#aktivitaetsListeFrame {{
                background-color: {Colors.BG_SURFACE};
                border: 1px solid {Colors.BORDER};
                border-radius: {Radius.XL}px;
            }}
        """)
        self.setObjectName("aktivitaetsListeFrame")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.MD)
        layout.setSpacing(0)

        head_row = QHBoxLayout()
        head_row.setSpacing(Spacing.SM)
        head = QLabel(title)
        head.setFont(Fonts.get(Fonts.SIZE_BASE, bold=True))
        head.setStyleSheet(
            f"color: {Colors.TEXT_PRIMARY}; background: transparent;"
            f"padding-bottom: {Spacing.XS}px;"
        )
        head_row.addWidget(head, 1)
        layout.addLayout(head_row)

        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background-color: {Colors.BORDER}; margin-bottom: 4px;")
        layout.addWidget(line)
        layout.addSpacing(Spacing.XS)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._inner = QWidget()
        self._inner.setObjectName("dashInner")
        self._inner.setStyleSheet("#dashInner { background: transparent; }")
        self._inner_layout = QVBoxLayout(self._inner)
        self._inner_layout.setContentsMargins(0, 0, 0, 0)
        self._inner_layout.setSpacing(2)
        self._scroll.setWidget(self._inner)
        layout.addWidget(self._scroll)

    def set_eintraege(self, eintraege: list[tuple]) -> None:
        """
        eintraege = [(icon, haupttext, subtext, farbe_str), ...]
        """
        while self._inner_layout.count():
            item = self._inner_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not eintraege:
            empty = QLabel("Keine Einträge")
            empty.setFont(Fonts.caption())
            empty.setStyleSheet(
                f"color: {Colors.TEXT_DISABLED}; padding: {Spacing.MD}px;"
            )
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._inner_layout.addWidget(empty)
            return

        for icon, haupt, sub, farbe in eintraege:
            row = QFrame()
            row.setObjectName("aktivRow")
            row.setStyleSheet(f"""
                QFrame#aktivRow {{
                    background: transparent;
                    border: none;
                    border-radius: {Radius.MD}px;
                }}
                QFrame#aktivRow:hover {{
                    background-color: {Colors.BG_ELEVATED};
                }}
            """)
            rl = QHBoxLayout(row)
            rl.setContentsMargins(Spacing.XS, Spacing.SM, Spacing.SM, Spacing.SM)
            rl.setSpacing(Spacing.SM)

            # Farbiger Akzent-Streifen links
            accent_bar = QFrame()
            accent_bar.setFixedWidth(3)
            accent_bar.setStyleSheet(f"""
                QFrame {{
                    background-color: {farbe};
                    border-radius: 2px;
                    border: none;
                }}
            """)
            rl.addWidget(accent_bar)

            icon_lbl = QLabel(icon)
            icon_lbl.setFixedWidth(22)
            icon_lbl.setStyleSheet("background: transparent; font-size: 14px;")
            rl.addWidget(icon_lbl)

            text_col = QVBoxLayout()
            text_col.setSpacing(1)
            haupt_lbl = QLabel(haupt)
            haupt_lbl.setFont(Fonts.get(Fonts.SIZE_SM, bold=True))
            haupt_lbl.setStyleSheet(
                f"color: {Colors.TEXT_PRIMARY}; background: transparent;"
            )
            haupt_lbl.setTextFormat(Qt.TextFormat.PlainText)
            sub_lbl = QLabel(sub)
            sub_lbl.setFont(Fonts.caption())
            sub_lbl.setStyleSheet(
                f"color: {Colors.TEXT_SECONDARY}; background: transparent;"
            )
            text_col.addWidget(haupt_lbl)
            if sub:
                text_col.addWidget(sub_lbl)
            rl.addLayout(text_col, 1)

            self._inner_layout.addWidget(row)

        self._inner_layout.addStretch()


# ---------------------------------------------------------------------------
# Dashboard-Panel
# ---------------------------------------------------------------------------

class DashboardPanel(QWidget):
    """
    Übersichts-Dashboard mit KPIs, Umsatzverlauf und Aktivitätslisten.
    Wird beim Aktivieren automatisch neu geladen.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._root_layout = None
        self._build_ui()
        QTimer.singleShot(300, self._laden)
        on_theme_changed(self._on_theme_changed)

    def _on_theme_changed(self, _mode: str) -> None:
        """Dashboard bei Theme-Wechsel komplett neu aufbauen (hat keine ungespeicherten Daten)."""
        self._rebuild_ui()

    def _rebuild_ui(self) -> None:
        """Löscht das gesamte UI und baut es mit neuen Farben neu auf."""
        if self._root_layout is not None:
            # Altes Layout und alle Kinder entfernen
            while self._root_layout.count():
                item = self._root_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            from PySide6.QtWidgets import QLayout
            # Layout selbst entfernen
            QWidget().setLayout(self._root_layout)
        self._build_ui()
        self._laden()

    def showEvent(self, event):
        """Neu laden wenn Panel sichtbar wird."""
        super().showEvent(event)
        self._laden()

    # ------------------------------------------------------------------
    # UI aufbauen
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        self._root_layout = root
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())

        # Scrollbarer Hauptbereich
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setObjectName("dashboardScroll")
        scroll.setStyleSheet(f"#dashboardScroll {{ background-color: {Colors.BG_APP}; }}")

        content = QWidget()
        content.setObjectName("dashboardContent")
        content.setStyleSheet(f"#dashboardContent {{ background-color: {Colors.BG_APP}; }}")
        self._content_layout = QVBoxLayout(content)
        self._content_layout.setContentsMargins(
            Spacing.XL, Spacing.XL, Spacing.XL, Spacing.XL
        )
        self._content_layout.setSpacing(Spacing.LG)

        # KPI-Zeile
        self._content_layout.addWidget(self._build_kpi_row())

        # Mittlere Zeile: Diagramm + Mahnwesen-Zusammenfassung
        mitte = QHBoxLayout()
        mitte.setSpacing(Spacing.LG)
        mitte.addWidget(self._build_umsatz_chart(), 3)
        mitte.addWidget(self._build_mahnwesen_box(), 2)
        self._content_layout.addLayout(mitte)

        # Untere Zeile: letzte Rechnungen + kritischer Bestand
        unten = QHBoxLayout()
        unten.setSpacing(Spacing.LG)
        self._letzte_rechnungen = AktivitaetsListe("🧾  Letzte Rechnungen")
        self._letzte_rechnungen.setMinimumHeight(240)
        self._kritischer_bestand = AktivitaetsListe("📦  Kritischer Lagerbestand")
        self._kritischer_bestand.setMinimumHeight(240)
        unten.addWidget(self._letzte_rechnungen, 1)
        unten.addWidget(self._kritischer_bestand, 1)
        self._content_layout.addLayout(unten)

        self._content_layout.addStretch()
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("dashboardHeader")
        header.setFixedHeight(68)
        header.setStyleSheet(f"""
            #dashboardHeader {{
                background-color: {Colors.BG_SURFACE};
                border-bottom: 1px solid {Colors.BORDER};
            }}
        """)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(Spacing.XL, 0, Spacing.XL, 0)

        # Icon mit Badge-Hintergrund
        icon_badge = QFrame()
        icon_badge.setFixedSize(40, 40)
        icon_badge.setStyleSheet(f"""
            QFrame {{
                background-color: {_badge_bg(Colors.PRIMARY)};
                border-radius: 12px;
                border: none;
            }}
        """)
        badge_l = QVBoxLayout(icon_badge)
        badge_l.setContentsMargins(0, 0, 0, 0)
        icon = QLabel("📊")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("font-size: 20px; background: transparent;")
        badge_l.addWidget(icon)

        title_col = QVBoxLayout()
        title_col.setSpacing(0)
        title = QLabel("Dashboard")
        title.setFont(Fonts.get(Fonts.SIZE_XL, bold=True))
        title.setStyleSheet(
            f"color: {Colors.TEXT_PRIMARY}; background: transparent;"
        )
        firma = config.get("company", "name", "")
        self._firma_lbl = QLabel(firma)
        self._firma_lbl.setFont(Fonts.get(Fonts.SIZE_SM))
        self._firma_lbl.setStyleSheet(
            f"color: {Colors.TEXT_SECONDARY}; background: transparent;"
        )
        title_col.addWidget(title)
        if firma:
            title_col.addWidget(self._firma_lbl)

        layout.addWidget(icon_badge)
        layout.addSpacing(Spacing.MD)
        layout.addLayout(title_col)
        layout.addStretch()

        self._datum_lbl = QLabel(
            date.today().strftime("Stand: %d.%m.%Y")
        )
        self._datum_lbl.setFont(Fonts.caption())
        self._datum_lbl.setStyleSheet(
            f"color: {Colors.TEXT_DISABLED}; background: transparent;"
        )
        layout.addWidget(self._datum_lbl)
        layout.addSpacing(Spacing.MD)

        btn = QPushButton("↻  Aktualisieren")
        btn.setProperty("role", "secondary")
        btn.clicked.connect(self._laden)
        layout.addWidget(btn)

        return header

    def _build_kpi_row(self) -> QWidget:
        row = QWidget()
        row.setObjectName("dashboardKpiRow")
        row.setStyleSheet("#dashboardKpiRow { background: transparent; }")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Spacing.MD)

        self._kpi_kunden = KPICard("👥", "Aktive Kunden", Colors.INFO)
        self._kpi_rechnungen = KPICard("🧾", "Offene Rechnungen", Colors.WARNING)
        self._kpi_umsatz = KPICard("💶", "Umsatz (lfd. Monat)", Colors.SUCCESS)
        self._kpi_umsatz_gesamt = KPICard("📈", "Umsatz (lfd. Jahr)", Colors.PRIMARY)
        self._kpi_mahnwesen = KPICard("📨", "Überfällige Rechnungen", Colors.ERROR)

        for karte in [
            self._kpi_kunden, self._kpi_rechnungen,
            self._kpi_umsatz, self._kpi_umsatz_gesamt,
            self._kpi_mahnwesen,
        ]:
            layout.addWidget(karte, 1)

        return row

    def _build_umsatz_chart(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.BG_SURFACE};
                border: 1px solid {Colors.BORDER};
                border-radius: {Radius.XL}px;
            }}
        """)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.MD)
        layout.setSpacing(Spacing.SM)

        head_row = QHBoxLayout()
        head = QLabel("Umsatz – letzte 6 Monate")
        head.setFont(Fonts.get(Fonts.SIZE_BASE, bold=True))
        head.setStyleSheet(
            f"color: {Colors.TEXT_PRIMARY}; background: transparent;"
        )
        head_row.addWidget(head, 1)
        layout.addLayout(head_row)

        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background-color: {Colors.BORDER};")
        layout.addWidget(line)

        self._diagramm = BalkenDiagramm()
        layout.addWidget(self._diagramm)

        return frame

    def _build_mahnwesen_box(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.BG_SURFACE};
                border: 1px solid {Colors.BORDER};
                border-radius: {Radius.XL}px;
            }}
        """)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        layout.setSpacing(Spacing.SM)

        head = QLabel("Mahnwesen-Übersicht")
        head.setFont(Fonts.get(Fonts.SIZE_BASE, bold=True))
        head.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; background: transparent;")
        layout.addWidget(head)

        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background-color: {Colors.BORDER};")
        layout.addWidget(line)

        is_light = get_current_mode() == "light"
        self._mahn_rows: dict[str, tuple[QLabel, QLabel]] = {}

        # Feste Hex-Werte damit _badge_bg sie korrekt mappen kann
        stufen = [
            ("Inkasso",    "⛔", "#DC2626"),
            ("Mahnung 2",  "🚨", "#EF4444"),
            ("Mahnung 1",  "⚠️",  "#F97316"),
            ("Erinnerung", "🔔", "#F59E0B"),
        ]
        for name, icon_str, farbe in stufen:
            row_frame = QFrame()
            row_frame.setObjectName("mahnRow")

            if is_light:
                row_bg = _badge_bg(farbe)
                row_css = f"""
                    QFrame#mahnRow {{
                        background-color: {row_bg};
                        border-radius: {Radius.MD}px;
                        border: 1px solid {farbe}55;
                    }}
                """
                text_color = "#1E293B"
            else:
                row_bg = f"{farbe}18"
                row_css = f"""
                    QFrame#mahnRow {{
                        background-color: {row_bg};
                        border-radius: {Radius.MD}px;
                        border: none;
                    }}
                """
                text_color = farbe

            row_frame.setStyleSheet(row_css)
            row = QHBoxLayout(row_frame)
            row.setContentsMargins(Spacing.SM, Spacing.XS + 1, Spacing.SM, Spacing.XS + 1)
            row.setSpacing(Spacing.SM)

            icon_lbl = QLabel(icon_str)
            icon_lbl.setStyleSheet("background: transparent; font-size: 13px;")
            icon_lbl.setFixedWidth(20)

            lbl = QLabel(name)
            lbl.setFont(Fonts.get(Fonts.SIZE_SM, bold=True))
            lbl.setStyleSheet(f"color: {text_color}; background: transparent;")

            anzahl = QLabel("0")
            anzahl.setFont(Fonts.get(Fonts.SIZE_SM, bold=True))
            anzahl.setStyleSheet(f"color: {farbe}; background: transparent;")

            betrag = QLabel("0,00 €")
            betrag.setFont(Fonts.caption())
            betrag.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; background: transparent;")

            row.addWidget(icon_lbl)
            row.addWidget(lbl, 1)
            row.addWidget(anzahl)
            row.addSpacing(Spacing.XS)
            row.addWidget(betrag)
            layout.addWidget(row_frame)
            self._mahn_rows[f"⛔  {name}" if "Inkasso" in name
                            else f"🚨  {name}" if "Mahnung 2" in name
                            else f"⚠️  {name}" if "Mahnung 1" in name
                            else f"🔔  {name}"] = (anzahl, betrag)

        layout.addStretch()

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background-color: {Colors.BORDER};")
        layout.addWidget(sep)

        gesamt_frame = QFrame()
        if is_light:
            gesamt_frame.setStyleSheet(f"""
                QFrame {{
                    background-color: #FEF2F2;
                    border-radius: {Radius.MD}px;
                    border: 1px solid #DC262655;
                }}
            """)
        else:
            gesamt_frame.setStyleSheet(f"""
                QFrame {{
                    background-color: #EF444418;
                    border-radius: {Radius.MD}px;
                    border: none;
                }}
            """)
        gesamt_row = QHBoxLayout(gesamt_frame)
        gesamt_row.setContentsMargins(Spacing.SM, Spacing.SM, Spacing.SM, Spacing.SM)

        gesamt_lbl = QLabel("Gesamt")
        gesamt_lbl.setFont(Fonts.get(Fonts.SIZE_SM, bold=True))
        gesamt_lbl.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; background: transparent;")

        self._mahn_gesamt_anzahl = QLabel("0")
        self._mahn_gesamt_anzahl.setFont(Fonts.get(Fonts.SIZE_BASE, bold=True))
        self._mahn_gesamt_anzahl.setStyleSheet(f"color: {Colors.ERROR}; background: transparent;")

        self._mahn_gesamt_betrag = QLabel("0,00 €")
        self._mahn_gesamt_betrag.setFont(Fonts.get(Fonts.SIZE_BASE, bold=True))
        self._mahn_gesamt_betrag.setStyleSheet(f"color: {Colors.ERROR}; background: transparent;")

        gesamt_row.addWidget(gesamt_lbl)
        gesamt_row.addStretch()
        gesamt_row.addWidget(self._mahn_gesamt_anzahl)
        gesamt_row.addSpacing(Spacing.SM)
        gesamt_row.addWidget(self._mahn_gesamt_betrag)
        layout.addWidget(gesamt_frame)

        return frame

    # ------------------------------------------------------------------
    # Daten laden
    # ------------------------------------------------------------------

    def _laden(self) -> None:
        try:
            self._laden_kpis()
            self._laden_umsatzverlauf()
            self._laden_mahnwesen()
            self._laden_letzte_rechnungen()
            self._laden_kritischer_bestand()
        except Exception as e:
            logger.exception("Dashboard-Ladefehler:")

    def _laden_kpis(self) -> None:
        from sqlalchemy import func
        from core.models import Kunde, Rechnung
        from core.services.rechnungen_service import RechnungStatus

        with db.session() as session:
            # Aktive Kunden
            n_kunden = (
                session.query(func.count(Kunde.id))
                .filter(Kunde.is_active == True)
                .scalar() or 0
            )

            # Offene Rechnungen
            n_offen = (
                session.query(func.count(Rechnung.id))
                .filter(
                    Rechnung.is_finalized == True,
                    Rechnung.status.in_([
                        RechnungStatus.OFFEN,
                        RechnungStatus.ERINNERUNG,
                        RechnungStatus.MAHNUNG1,
                        RechnungStatus.MAHNUNG2,
                        RechnungStatus.INKASSO,
                    ])
                )
                .scalar() or 0
            )
            sum_offen = (
                session.query(func.sum(Rechnung.offener_betrag))
                .filter(
                    Rechnung.is_finalized == True,
                    Rechnung.status.in_([
                        RechnungStatus.OFFEN,
                        RechnungStatus.ERINNERUNG,
                        RechnungStatus.MAHNUNG1,
                        RechnungStatus.MAHNUNG2,
                    ])
                )
                .scalar() or 0
            )

            # Umsatz laufender Monat
            heute = date.today()
            monat_start = heute.replace(day=1).strftime("%d.%m.%Y")
            umsatz_monat = (
                session.query(func.sum(Rechnung.summe_brutto))
                .filter(
                    Rechnung.is_finalized == True,
                    Rechnung.status != RechnungStatus.STORNIERT,
                    Rechnung.rechnungsdatum >= monat_start,
                )
                .scalar() or 0
            )

            # Umsatz laufendes Jahr
            jahr_start = heute.replace(month=1, day=1).strftime("%d.%m.%Y")
            umsatz_jahr = (
                session.query(func.sum(Rechnung.summe_brutto))
                .filter(
                    Rechnung.is_finalized == True,
                    Rechnung.status != RechnungStatus.STORNIERT,
                    Rechnung.rechnungsdatum >= jahr_start,
                )
                .scalar() or 0
            )

            # Überfällige
            n_ueberfaellig = (
                session.query(func.count(Rechnung.id))
                .filter(
                    Rechnung.is_finalized == True,
                    Rechnung.status.in_([
                        RechnungStatus.ERINNERUNG,
                        RechnungStatus.MAHNUNG1,
                        RechnungStatus.MAHNUNG2,
                        RechnungStatus.INKASSO,
                    ])
                )
                .scalar() or 0
            )

        self._kpi_kunden.set_value(str(n_kunden))
        self._kpi_rechnungen.set_value(
            str(n_offen),
            subtitle=f"Offen: {_fmt(Decimal(str(sum_offen)))}",
        )
        self._kpi_umsatz.set_value(
            _fmt(Decimal(str(umsatz_monat))),
            subtitle=heute.strftime("%B %Y"),
        )
        self._kpi_umsatz_gesamt.set_value(
            _fmt(Decimal(str(umsatz_jahr))),
            subtitle=str(heute.year),
        )
        self._kpi_mahnwesen.set_value(
            str(n_ueberfaellig),
            subtitle="Rechnungen überfällig" if n_ueberfaellig else "Alles im grünen Bereich ✓",
        )

    def _laden_umsatzverlauf(self) -> None:
        """Berechnet Monatsumsätze der letzten 6 Monate."""
        from core.models import Rechnung
        from core.services.rechnungen_service import RechnungStatus

        heute = date.today()
        monate = []
        for i in range(5, -1, -1):
            if heute.month - i <= 0:
                monat = heute.month - i + 12
                jahr = heute.year - 1
            else:
                monat = heute.month - i
                jahr = heute.year
            monate.append((jahr, monat))

        daten = []
        with db.session() as session:
            for jahr, monat in monate:
                prefix = f"{monat:02d}.{jahr}"
                # Alle Rechnungen des Monats: Datum beginnt mit MM.JJJJ
                rechnungen = (
                    session.query(Rechnung)
                    .filter(
                        Rechnung.is_finalized == True,
                        Rechnung.status != RechnungStatus.STORNIERT,
                        Rechnung.rechnungsdatum.like(f"%.{monat:02d}.{jahr}"),
                    )
                    .all()
                )
                summe = sum(
                    Decimal(str(r.summe_brutto or 0)) for r in rechnungen
                )
                monatsname = [
                    "Jan", "Feb", "Mär", "Apr", "Mai", "Jun",
                    "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"
                ][monat - 1]
                daten.append((monatsname, summe))

        self._diagramm.set_daten(daten)

    def _laden_mahnwesen(self) -> None:
        from core.services.mahnwesen_service import mahnwesen_service, MahnKonfig
        from core.services.rechnungen_service import RechnungStatus

        with db.session() as session:
            ueb = mahnwesen_service.uebersicht(
                session, MahnKonfig.aus_config()
            )

        mapping = {
            "⛔  Inkasso":    ueb.inkasso,
            "🚨  Mahnung 2":  ueb.mahnung2,
            "⚠️  Mahnung 1":   ueb.mahnung1,
            "🔔  Erinnerung": ueb.erinnerung,
        }
        for label, dtos in mapping.items():
            betrag = sum(d.gesamtforderung for d in dtos)
            anzahl_lbl, betrag_lbl = self._mahn_rows[label]
            anzahl_lbl.setText(str(len(dtos)))
            betrag_lbl.setText(_fmt(betrag))

        stats = ueb.statistik
        self._mahn_gesamt_anzahl.setText(str(stats["gesamt"]))
        self._mahn_gesamt_betrag.setText(_fmt(stats["betrag"]))

    def _laden_letzte_rechnungen(self) -> None:
        from core.models import Rechnung, Kunde
        from core.services.rechnungen_service import RechnungStatus

        STATUS_FARBE = {
            RechnungStatus.ENTWURF:    Colors.TEXT_DISABLED,
            RechnungStatus.OFFEN:      Colors.INFO,
            RechnungStatus.BEZAHLT:    Colors.SUCCESS,
            RechnungStatus.ERINNERUNG: Colors.WARNING,
            RechnungStatus.MAHNUNG1:   "#F97316",
            RechnungStatus.MAHNUNG2:   Colors.ERROR,
            RechnungStatus.INKASSO:    "#DC2626",
            RechnungStatus.STORNIERT:  Colors.TEXT_DISABLED,
        }

        from sqlalchemy.orm import contains_eager
        with db.session() as session:
            rechnungen = (
                session.query(Rechnung)
                .join(Rechnung.kunde)
                .options(contains_eager(Rechnung.kunde))
                .order_by(Rechnung.id.desc())
                .limit(10)
                .all()
            )
            eintraege = []
            for r in rechnungen:
                icon = "🧾" if r.is_finalized else "📝"
                haupt = f"{r.rechnungsnummer}  –  {r.kunde.vorname} {r.kunde.name}"
                brutto = _fmt(Decimal(str(r.summe_brutto or 0)))
                sub = f"{r.rechnungsdatum}  ·  {brutto}  ·  {r.status}"
                farbe = STATUS_FARBE.get(r.status, Colors.TEXT_SECONDARY)
                eintraege.append((icon, haupt, sub, farbe))

        self._letzte_rechnungen.set_eintraege(eintraege)

    def _laden_kritischer_bestand(self) -> None:
        from core.models import Artikel

        with db.session() as session:
            artikel = (
                session.query(Artikel)
                .filter(
                    Artikel.is_active == True,
                    Artikel.verfuegbar <= 5,
                )
                .order_by(Artikel.verfuegbar)
                .limit(10)
                .all()
            )
            eintraege = []
            for a in artikel:
                icon = "🔴" if float(a.verfuegbar) < 0 else "🟡"
                haupt = f"{a.artikelnummer}  –  {a.beschreibung}"
                einheit = a.einheit or ""
                sub = (
                    f"Bestand: {float(a.verfuegbar):g} {einheit}  ·  "
                    f"Preis: {_fmt(Decimal(str(a.einzelpreis_netto)))}"
                )
                farbe = Colors.ERROR if float(a.verfuegbar) < 0 else Colors.WARNING
                eintraege.append((icon, haupt, sub, farbe))

        if not eintraege:
            eintraege = [("✅", "Alle Bestände im grünen Bereich", "", Colors.SUCCESS)]

        self._kritischer_bestand.set_eintraege(eintraege)
