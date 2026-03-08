"""
ui/modules/kunden/dokumente_dialog.py – Dokumentenverwaltung pro Kunde
=======================================================================
Zeigt alle Dokumente eines Kunden, ermöglicht Hinzufügen,
Öffnen, Löschen und E-Mail-Versand.
"""

import smtplib
import subprocess
import sys
import urllib.parse
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QFrame, QFileDialog, QListWidget, QListWidgetItem,
    QAbstractItemView, QWidget, QMenu, QLineEdit, QTextEdit,
    QFormLayout, QComboBox,
)

from core.db.engine import db
from core.services.kunden_service import kunden_service, KundeDTO, DokumentDTO
from core.config import config
from ui.components.widgets import NotificationBanner, ConfirmDialog, EmptyState
from ui.theme.theme import Colors, Fonts, Spacing, Radius


class DokumenteDialog(QDialog):
    """Dialog zur Verwaltung von Kundendokumenten."""

    documents_changed = Signal()

    def __init__(self, dto: KundeDTO, parent=None):
        super().__init__(parent)
        self._dto = dto
        self.setWindowTitle(f"Dokumente – {dto.display_name}")
        self.setModal(True)
        self.setMinimumSize(580, 460)
        self._build_ui()
        self._load_documents()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        header = QFrame()
        header.setFixedHeight(56)
        header.setStyleSheet(f"""
            background-color: {Colors.BG_SURFACE};
            border-bottom: 1px solid {Colors.BORDER};
        """)
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(Spacing.XL, 0, Spacing.XL, 0)
        icon = QLabel("📂")
        icon.setStyleSheet("font-size: 20px; background: transparent;")
        title = QLabel(f"Dokumente: {self._dto.display_name}")
        title.setFont(Fonts.heading3())
        title.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; background: transparent;")
        h_layout.addWidget(icon)
        h_layout.addSpacing(Spacing.SM)
        h_layout.addWidget(title)
        h_layout.addStretch()
        root.addWidget(header)

        # Banner
        content = QWidget()
        c_layout = QVBoxLayout(content)
        c_layout.setContentsMargins(Spacing.XL, Spacing.MD, Spacing.XL, Spacing.MD)
        c_layout.setSpacing(Spacing.SM)

        self._banner = NotificationBanner()
        c_layout.addWidget(self._banner)

        # Toolbar
        toolbar = QHBoxLayout()
        add_btn = QPushButton("➕  Dokument hinzufügen")
        add_btn.clicked.connect(self._add_document)
        self._open_btn = QPushButton("📂  Öffnen")
        self._open_btn.setProperty("role", "secondary")
        self._open_btn.setEnabled(False)
        self._open_btn.clicked.connect(self._open_document)
        self._delete_btn = QPushButton("🗑  Löschen")
        self._delete_btn.setProperty("role", "danger")
        self._delete_btn.setEnabled(False)
        self._delete_btn.clicked.connect(self._delete_document)
        toolbar.addWidget(add_btn)
        toolbar.addStretch()
        toolbar.addWidget(self._open_btn)
        toolbar.addWidget(self._delete_btn)
        c_layout.addLayout(toolbar)

        # Dokumentenliste
        self._list = QListWidget()
        self._list.setAlternatingRowColors(True)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.itemSelectionChanged.connect(self._on_selection)
        self._list.itemDoubleClicked.connect(lambda _: self._open_document())
        self._list.setMinimumHeight(260)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._show_context_menu)
        c_layout.addWidget(self._list)

        # Empty State
        self._empty = EmptyState(
            "📭", "Keine Dokumente",
            "Klicken Sie auf '+ Dokument hinzufügen' um eine Datei zuzuordnen."
        )
        self._empty.setVisible(False)
        c_layout.addWidget(self._empty)

        root.addWidget(content, 1)

        # Footer
        footer = QFrame()
        footer.setFixedHeight(56)
        footer.setStyleSheet(f"""
            background-color: {Colors.BG_SURFACE};
            border-top: 1px solid {Colors.BORDER};
        """)
        f_layout = QHBoxLayout(footer)
        f_layout.setContentsMargins(Spacing.XL, 0, Spacing.XL, 0)
        f_layout.addStretch()
        close_btn = QPushButton("Schließen")
        close_btn.setProperty("role", "secondary")
        close_btn.clicked.connect(self.accept)
        f_layout.addWidget(close_btn)
        root.addWidget(footer)

    # ------------------------------------------------------------------
    # Daten
    # ------------------------------------------------------------------

    def _load_documents(self) -> None:
        self._list.clear()
        with db.session() as session:
            docs = kunden_service.dokumente(session, self._dto.id)

        has_docs = len(docs) > 0
        self._list.setVisible(has_docs)
        self._empty.setVisible(not has_docs)

        for doc in docs:
            item = QListWidgetItem()
            missing = not doc.exists
            if missing:
                item.setText(f"⚠  {doc.dateiname}  [DATEI FEHLT]")
                item.setForeground(QColor(Colors.ERROR))
            else:
                suffix = Path(doc.dateiname).suffix.upper().lstrip(".")
                item.setText(f"📄  {doc.dateiname}")
            item.setData(Qt.ItemDataRole.UserRole, doc)
            self._list.addItem(item)

    def _on_selection(self) -> None:
        has_sel = len(self._list.selectedItems()) > 0
        self._open_btn.setEnabled(has_sel)
        self._delete_btn.setEnabled(has_sel)

    def _selected_doc(self):
        items = self._list.selectedItems()
        if not items:
            return None
        return items[0].data(Qt.ItemDataRole.UserRole)

    # ------------------------------------------------------------------
    # Aktionen
    # ------------------------------------------------------------------

    def _add_document(self) -> None:
        pfad, _ = QFileDialog.getOpenFileName(
            self, "Dokument auswählen", "", "Alle Dateien (*.*)"
        )
        if not pfad:
            return

        basis = config.get("paths", "documents", "")
        if not basis:
            self._banner.show_warning(
                "Kein Dokumentenordner konfiguriert. "
                "Bitte unter Einstellungen → Dokumentenordner festlegen."
            )
            return

        with db.session() as session:
            result = kunden_service.dokument_zuordnen(
                session, self._dto.id, pfad, basis
            )

        if result.success:
            self._banner.show_success(result.message)
            self._load_documents()
            self.documents_changed.emit()
        else:
            self._banner.show_error(result.message)

    def _open_document(self) -> None:
        doc = self._selected_doc()
        if not doc:
            return
        if not doc.exists:
            self._banner.show_error(
                f"Die Datei '{doc.dateiname}' wurde nicht gefunden."
            )
            return
        try:
            if sys.platform == "win32":
                import os
                os.startfile(doc.dokument_pfad)
            elif sys.platform == "darwin":
                subprocess.run(["open", doc.dokument_pfad])
            else:
                subprocess.run(["xdg-open", doc.dokument_pfad])
        except Exception as e:
            self._banner.show_error(f"Datei konnte nicht geöffnet werden: {e}")

    def _delete_document(self) -> None:
        doc = self._selected_doc()
        if not doc:
            return

        if not ConfirmDialog.ask(
            title="Dokument löschen",
            message=f"'{doc.dateiname}' wirklich löschen?",
            detail="Die Datei wird dauerhaft gelöscht und kann nicht wiederhergestellt werden.",
            confirm_text="Löschen",
            danger=True,
            parent=self,
        ):
            return

        with db.session() as session:
            result = kunden_service.dokument_loeschen(session, doc.id)

        if result.success:
            self._banner.show_success(result.message)
            self._load_documents()
            self.documents_changed.emit()
        else:
            self._banner.show_error(result.message)

    # ------------------------------------------------------------------
    # Kontextmenü
    # ------------------------------------------------------------------

    def _show_context_menu(self, pos) -> None:
        doc = self._selected_doc()
        if not doc:
            return
        smtp_ok = bool(config.get("smtp", "server", ""))
        menu = QMenu(self)
        act_open   = menu.addAction("📂  Öffnen")
        menu.addSeparator()
        act_system = menu.addAction("📧  Per System-E-Mail senden")
        act_smtp   = menu.addAction("✉  Per SMTP direkt senden")
        if not smtp_ok:
            act_smtp.setEnabled(False)
            act_smtp.setToolTip("Kein SMTP konfiguriert (Einstellungen → E-Mail)")
        menu.addSeparator()
        act_delete = menu.addAction("🗑  Löschen")
        act_open.triggered.connect(self._open_document)
        act_system.triggered.connect(lambda: self._email_system(doc))
        act_smtp.triggered.connect(lambda: self._email_smtp_dialog(doc))
        act_delete.triggered.connect(self._delete_document)
        menu.exec(self._list.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------------
    # E-Mail: System-Mailprogramm
    # ------------------------------------------------------------------

    def _email_system(self, doc: DokumentDTO) -> None:
        """Öffnet das Standard-Mailprogramm mit dem Dokument als Anhang."""
        empfaenger = self._dto.email or ""
        betreff    = urllib.parse.quote(f"Dokument: {doc.dateiname}")
        empf_enc   = urllib.parse.quote(empfaenger)
        mailto     = f"mailto:{empf_enc}?subject={betreff}"
        try:
            if sys.platform == "win32":
                import os
                os.startfile(mailto)
            elif sys.platform == "darwin":
                subprocess.run(["open", mailto])
            else:
                subprocess.run(["xdg-open", mailto])
            self._banner.show_info(
                f"System-E-Mail-Programm geöffnet. "
                f"Bitte '{doc.dateiname}' manuell als Anhang hinzufügen."
            )
        except Exception as e:
            self._banner.show_error(f"System-Mail konnte nicht geöffnet werden: {e}")

    # ------------------------------------------------------------------
    # E-Mail: Interner SMTP-Versand
    # ------------------------------------------------------------------

    def _email_smtp_dialog(self, doc: DokumentDTO) -> None:
        """Öffnet einen Dialog zum direkten SMTP-Versand des Dokuments."""
        if not doc.exists:
            self._banner.show_error(
                f"Datei '{doc.dateiname}' wurde nicht gefunden."
            )
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Dokument per E-Mail senden")
        dlg.setModal(True)
        dlg.setMinimumSize(480, 380)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(Spacing.XL, Spacing.LG, Spacing.XL, Spacing.LG)
        layout.setSpacing(Spacing.MD)

        # Info-Header
        info = QLabel(f"Anhang: <b>{doc.dateiname}</b>")
        info.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        layout.addWidget(info)

        form = QFormLayout()
        form.setSpacing(Spacing.SM)

        f_to = QLineEdit(self._dto.email or "")
        f_to.setPlaceholderText("empfaenger@beispiel.de")
        form.addRow("An *", f_to)

        try:
            from core.services.platzhalter_service import load_vorlagen, resolve, build_context
            _vorlagen2 = load_vorlagen()
            _ctx2 = build_context(dateiname=doc.dateiname)
            _subj_tpl = _vorlagen2.get("email_standard_betreff", "Dokument: {{DATEINAME}}")
            _subj_default = resolve(_subj_tpl, _ctx2)
        except Exception:
            _subj_default = f"Dokument: {doc.dateiname}"
        f_subj = QLineEdit(_subj_default)
        form.addRow("Betreff *", f_subj)

        f_body = QTextEdit()
        f_body.setPlaceholderText("Nachrichtentext (optional)...")
        f_body.setFixedHeight(100)
        smtp_user = config.get("smtp", "user", "")
        firma = config.get("firma", "name", "")
        # Text aus editierbarer Vorlage laden
        try:
            from core.services.platzhalter_service import load_vorlagen, resolve, build_context
            _vorlagen = load_vorlagen()
            _ctx = build_context(dateiname=doc.dateiname)
            _body_tpl = _vorlagen.get("email_standard_text", "")
            _body_text = resolve(_body_tpl, _ctx) if _body_tpl else (
                f"Sehr geehrte Damen und Herren,\n\n"
                f"anbei erhalten Sie das Dokument '{doc.dateiname}'.\n\n"
                f"Mit freundlichen Grüßen\n{firma}"
            )
        except Exception:
            _body_text = (
                f"Sehr geehrte Damen und Herren,\n\n"
                f"anbei erhalten Sie das Dokument '{doc.dateiname}'.\n\n"
                f"Mit freundlichen Grüßen\n{firma}"
            )
        f_body.setPlainText(_body_text)
        form.addRow("Nachricht", f_body)

        f_pw = QLineEdit()
        f_pw.setPlaceholderText("SMTP-Passwort")
        f_pw.setEchoMode(QLineEdit.EchoMode.Password)
        from core.services.credential_service import passwort_laden
        smtp_pw_hint = "(gespeichert)" if passwort_laden() else ""
        if smtp_pw_hint:
            f_pw.setPlaceholderText(f"SMTP-Passwort {smtp_pw_hint}")
        form.addRow("Passwort", f_pw)

        layout.addLayout(form)

        # Hinweis SMTP-Einstellungen
        hint = QLabel(
            f"SMTP: {config.get('smtp','server','')}:{config.get('smtp','port',587)}"
            f"  ·  Benutzer: {smtp_user}"
        )
        hint.setStyleSheet(f"color: {Colors.TEXT_DISABLED}; font-size: 11px;")
        layout.addWidget(hint)

        layout.addStretch()

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_cancel = QPushButton("Abbrechen")
        btn_cancel.setProperty("role", "secondary")
        btn_cancel.clicked.connect(dlg.reject)
        btn_send = QPushButton("Senden")
        btn_send.setDefault(True)

        def do_send():
            to      = f_to.text().strip()
            subject = f_subj.text().strip()
            body    = f_body.toPlainText()
            from core.services.credential_service import passwort_laden as _pw_laden
            pw      = f_pw.text() or _pw_laden()
            if not to:
                f_to.setFocus()
                return
            if not subject:
                f_subj.setFocus()
                return
            btn_send.setEnabled(False)
            btn_send.setText("Sende...")
            try:
                self._smtp_send(to, subject, body, doc.dokument_pfad, pw)
                self._banner.show_success(f"E-Mail an {to} erfolgreich gesendet.")
                dlg.accept()
            except Exception as ex:
                self._banner.show_error(f"Fehler beim Senden: {ex}")
                btn_send.setEnabled(True)
                btn_send.setText("Senden")

        btn_send.clicked.connect(do_send)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_send)
        layout.addLayout(btn_row)
        dlg.exec()

    def _smtp_send(
        self, to: str, subject: str, body: str,
        attachment_path: str, password: str
    ) -> None:
        """Sendet eine E-Mail mit Anhang via SMTP."""
        server_host = config.get("smtp", "server", "")
        port        = int(config.get("smtp", "port", 587))
        user        = config.get("smtp", "user", "")
        encryption  = config.get("smtp", "encryption", "STARTTLS").upper()

        if not server_host:
            raise ValueError("Kein SMTP-Server konfiguriert.")
        if not user:
            raise ValueError("Kein SMTP-Benutzer konfiguriert.")
        if not password:
            raise ValueError("Kein Passwort angegeben.")

        msg = MIMEMultipart()
        msg["From"]    = user
        msg["To"]      = to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))

        filename = Path(attachment_path).name
        with open(attachment_path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        from email.header import Header
        part.add_header(
            "Content-Disposition", "attachment",
            filename=Header(filename, "utf-8").encode()
        )
        msg.attach(part)

        if encryption == "SSL/TLS":
            server = smtplib.SMTP_SSL(server_host, port, timeout=20)
        else:
            server = smtplib.SMTP(server_host, port, timeout=20)
            if encryption == "STARTTLS":
                server.starttls()

        try:
            server.login(user, password)
            server.send_message(msg)
        finally:
            server.quit()

