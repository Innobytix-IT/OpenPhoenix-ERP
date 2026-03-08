"""
core/services/pdf_service.py – PDF-Generierung für Rechnungen (v2)
"""

import logging
import os
from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO
from pathlib import Path
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate,
    Paragraph, Spacer, Table, TableStyle, HRFlowable,
)

from core.config import config
from core.services.platzhalter_service import load_vorlagen, resolve, build_context

logger = logging.getLogger(__name__)

C_PRIMARY    = HexColor("#6C63FF")
C_DARK       = HexColor("#111827")
C_SECONDARY  = HexColor("#6B7280")
C_BORDER     = HexColor("#E5E7EB")
C_BG_LIGHT   = HexColor("#F9FAFB")
C_TABLE_HEAD = HexColor("#F3F4F6")
C_TOTAL_BG   = HexColor("#EEF2FF")


def _fmt(v: Decimal) -> str:
    r = v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    s = f"{r:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s} \u20ac"

def _fmt_menge(v: Decimal) -> str:
    return f"{v:g}".replace(".", ",")

def _has_background() -> bool:
    """Gibt True zurück wenn ein Hintergrundbild konfiguriert und vorhanden ist."""
    bg = config.get("paths", "pdf_background", "").strip().strip('"').strip("'")
    return bool(bg and os.path.exists(bg))


def _draw_background(canvas, sw, sh) -> None:
    """Zeichnet das konfigurierte PDF-Hintergrundbild auf die gesamte Seite."""
    bg_path = config.get("paths", "pdf_background", "").strip().strip('"').strip("'")
    if not bg_path or not os.path.exists(bg_path):
        return
    try:
        canvas.saveState()
        canvas.drawImage(
            bg_path, 0, 0,
            width=sw, height=sh,
            preserveAspectRatio=True,
            anchor="c",
            mask="auto",
        )
        canvas.restoreState()
        logger.debug(f"PDF-Hintergrund gezeichnet: {bg_path}")
    except Exception as e:
        logger.warning(f"PDF-Hintergrund konnte nicht gezeichnet werden: {e}")


def _styles() -> dict:
    base = getSampleStyleSheet()
    s = {}
    def add(name, **kw):
        s[name] = ParagraphStyle(name, parent=base["Normal"], **kw)
    add("titel",       fontSize=22, textColor=C_PRIMARY, fontName="Helvetica-Bold", leading=26, spaceAfter=2)
    add("nr",          fontSize=10, textColor=C_SECONDARY, spaceAfter=8)
    add("summen_key",  fontSize=9.5, textColor=C_SECONDARY, alignment=TA_RIGHT)
    add("summen_val",  fontSize=9.5, textColor=C_DARK, fontName="Helvetica-Bold", alignment=TA_RIGHT)
    add("gesamt_key",  fontSize=12, textColor=C_DARK, fontName="Helvetica-Bold", alignment=TA_RIGHT)
    add("gesamt_val",  fontSize=12, textColor=C_PRIMARY, fontName="Helvetica-Bold", alignment=TA_RIGHT)
    add("hinweis",     fontSize=9, textColor=C_SECONDARY, leading=13, spaceBefore=6)
    return s


class PDFService:

    def rechnung_als_pdf_bytes(self, dto, session=None) -> bytes:
        buf = BytesIO()
        self._build(buf, dto, session)
        return buf.getvalue()

    def rechnung_als_datei(self, dto, ausgabe_verzeichnis=None, session=None):
        try:
            data = self.rechnung_als_pdf_bytes(dto, session)
            if not ausgabe_verzeichnis:
                ausgabe_verzeichnis = config.get("paths", "pdf_output", "")
            if not ausgabe_verzeichnis:
                ausgabe_verzeichnis = str(Path.home() / "OpenPhoenix" / "Rechnungen")
            os.makedirs(ausgabe_verzeichnis, exist_ok=True)
            safe = dto.rechnungsnummer.replace("/", "-").replace("\\", "-")
            pfad = str(Path(ausgabe_verzeichnis) / f"Rechnung_{safe}.pdf")
            with open(pfad, "wb") as f:
                f.write(data)
            logger.info(f"PDF erstellt: {pfad}")
            return True, pfad
        except Exception as e:
            logger.exception("PDF-Fehler:")
            return False, str(e)

    def _build(self, buf, dto, session):
        s   = _styles()
        sw, sh = A4          # 595.27pt × 841.89pt
        kunde  = self._kundenadresse(dto, session)

        # Mit Hintergrundbild: größerer oberer Rand, da Briefkopf im BG enthalten
        bg_aktiv  = _has_background()
        top_m     = 80*mm if bg_aktiv else 77*mm

        frame = Frame(
            20*mm, 22*mm,
            sw - 40*mm,
            sh - top_m - 22*mm,
            leftPadding=0, rightPadding=0,
            topPadding=0, bottomPadding=0,
        )
        def hf(canvas, doc):
            _draw_background(canvas, sw, sh)
            canvas.saveState()
            self._kopf(canvas, sw, sh, kunde)
            self._fuss(canvas, sw)
            canvas.restoreState()

        doc = BaseDocTemplate(
            buf, pagesize=A4,
            pageTemplates=[PageTemplate(id="R", frames=[frame], onPage=hf)],
            leftMargin=20*mm, rightMargin=20*mm,
            topMargin=top_m, bottomMargin=22*mm,
        )
        doc.build(self._story(dto, s, sw - 40*mm, session=session))

    def _kopf(self, canvas, sw, sh, kunde):
        c = config
        firma   = c.get("company", "name",         "Ihr Unternehmen")
        adresse = c.get("company", "address",       "")
        plz_ort = c.get("company", "zip_city",      "")
        telefon = c.get("company", "phone",         "")
        email   = c.get("company", "email",         "")
        ust     = c.get("company", "tax_id",        "")
        bg_aktiv = _has_background()

        if not bg_aktiv:
            # ── Standard-Modus: Blauer Balken + Firmenkopf (DIN 5008) ───
            # Blauer Balken oben
            canvas.setFillColor(C_PRIMARY)
            canvas.rect(0, sh - 14*mm, sw, 14*mm, fill=1, stroke=0)
            canvas.setFillColor(colors.white)
            canvas.setFont("Helvetica-Bold", 14)
            canvas.drawString(20*mm, sh - 9.5*mm, firma)

            # Firmendaten rechts (ab 19mm, je 4mm Abstand)
            canvas.setFillColor(C_SECONDARY)
            canvas.setFont("Helvetica", 7.5)
            y = sh - 19*mm
            for z in filter(None, [adresse, plz_ort, telefon, email,
                                    f"USt-ID/St.-Nr.: {ust}" if ust else ""]):
                canvas.drawRightString(sw - 20*mm, y, z)
                y -= 4*mm

            # Absenderzeile (DIN 5008: Zone I, 45mm v. oben, mini 6pt)
            canvas.setFillColor(C_SECONDARY)
            canvas.setFont("Helvetica", 6)
            canvas.drawString(20*mm, sh - 45*mm,
                f"{firma}  ·  {adresse}  ·  {plz_ort}"[:90])

            # Empfängeranschrift (DIN 5008: Anschriftfeld 50–85mm)
            canvas.setFillColor(C_DARK)
            canvas.setFont("Helvetica", 10)
            y = sh - 50*mm
            for z in filter(None, [
                kunde.get("name", ""),
                kunde.get("strasse", ""),
                (kunde.get("plz","") + " " + kunde.get("ort","")).strip(),
            ]):
                canvas.drawString(20*mm, y, z)
                y -= 5*mm

            # Trennlinie (72mm v. oben, unter Anschrift)
            canvas.setStrokeColor(C_BORDER)
            canvas.setLineWidth(0.5)
            canvas.line(20*mm, sh - 72*mm, sw - 20*mm, sh - 72*mm)

            # Kundennummer + Datum rechts (auf Höhe Anschrift)
            kundennr = kunde.get("zifferncode", "")
            from datetime import date
            datum_str = date.today().strftime("%d.%m.%Y")
            label_x = sw - 70*mm
            value_x = sw - 20*mm
            y_info  = sh - 55*mm
            if kundennr:
                canvas.setFont("Helvetica", 9)
                canvas.setFillColor(C_SECONDARY)
                canvas.drawString(label_x, y_info, "Kundennummer:")
                canvas.setFont("Helvetica-Bold", 9)
                canvas.setFillColor(C_DARK)
                canvas.drawRightString(value_x, y_info, str(kundennr))
                y_info -= 5.5*mm
            canvas.setFont("Helvetica", 9)
            canvas.setFillColor(C_SECONDARY)
            canvas.drawString(label_x, y_info, "Datum:")
            canvas.setFont("Helvetica-Bold", 9)
            canvas.setFillColor(C_DARK)
            canvas.drawRightString(value_x, y_info, datum_str)

        else:
            # ── Briefpapier-Modus: Layout wie im Beispiel ────────────────
            # DIN-5008: Anschriftfeld 45–85mm von oben
            # Absenderzeile (Rücksendeadresse, 6pt, unterstrichen)
            absender = f"{firma}  –  {adresse}  –  {plz_ort}"
            canvas.setFillColor(C_SECONDARY)
            canvas.setFont("Helvetica", 6)
            canvas.drawString(20*mm, sh - 45*mm, absender[:100])
            # Unterstreichung unter Absenderzeile
            canvas.setStrokeColor(C_SECONDARY)
            canvas.setLineWidth(0.3)
            canvas.line(20*mm, sh - 45.8*mm,
                        canvas.stringWidth(absender[:100], "Helvetica", 6) + 20*mm,
                        sh - 45.8*mm)

            # Empfängeranschrift links (DIN-Fenster: 50–85mm v. oben)
            canvas.setFillColor(C_DARK)
            canvas.setFont("Helvetica", 10)
            y = sh - 50*mm
            for z in filter(None, [
                kunde.get("name", ""),
                kunde.get("strasse", ""),
                (kunde.get("plz","") + " " + kunde.get("ort","")).strip(),
            ]):
                canvas.drawString(20*mm, y, z)
                y -= 5*mm

            # Kundennummer + Datum rechts (auf Höhe Anschrift)
            canvas.setFont("Helvetica-Bold", 9)
            canvas.setFillColor(C_DARK)
            kundennr = kunde.get("zifferncode", "")
            from datetime import date
            datum_str = date.today().strftime("%d.%m.%Y")
            label_x  = sw - 70*mm
            value_x  = sw - 20*mm
            y_info   = sh - 55*mm
            if kundennr:
                canvas.setFont("Helvetica", 9)
                canvas.setFillColor(C_SECONDARY)
                canvas.drawString(label_x, y_info, "Kundennummer:")
                canvas.setFont("Helvetica-Bold", 9)
                canvas.setFillColor(C_DARK)
                canvas.drawRightString(value_x, y_info, str(kundennr))
                y_info -= 5.5*mm
            canvas.setFont("Helvetica", 9)
            canvas.setFillColor(C_SECONDARY)
            canvas.drawString(label_x, y_info, "Datum:")
            canvas.setFont("Helvetica-Bold", 9)
            canvas.setFillColor(C_DARK)
            canvas.drawRightString(value_x, y_info, datum_str)

    def _fuss(self, canvas, sw):
        c     = config
        firma = c.get("company", "name",          "")
        tel   = c.get("company", "phone",         "")
        email = c.get("company", "email",         "")
        bank  = c.get("company", "bank_details",  "")

        canvas.setStrokeColor(C_BORDER)
        canvas.setLineWidth(0.5)
        canvas.line(20*mm, 19*mm, sw - 20*mm, 19*mm)

        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(C_SECONDARY)
        col = (sw - 40*mm) / 3
        x1, x2 = 20*mm, 20*mm + col

        canvas.drawString(x1, 15*mm, firma)
        if tel:   canvas.drawString(x1, 12*mm,  f"Tel: {tel}")
        if email: canvas.drawString(x1,  9.5*mm, email)

        if bank:
            y = 15*mm
            for z in bank.split("\n")[:3]:
                canvas.drawString(x2, y, z.strip()[:44])
                y -= 2.8*mm

        canvas.drawRightString(sw - 20*mm, 12*mm, "Seite 1")

    def _story(self, dto, s, w, session=None):
        story = [Spacer(1, 6*mm)]

        # Titel – bei Gutschriften abweichender Titel
        storno_zu = getattr(dto, "storno_zu_nr", "")
        is_gutschrift = storno_zu or getattr(dto, "status", "") == "Gutschrift"
        titel_text = "GUTSCHRIFT" if is_gutschrift else "RECHNUNG"
        story.append(Paragraph(titel_text, s["titel"]))
        story.append(Paragraph(f"Rechnungsnummer: {dto.rechnungsnummer}", s["nr"]))

        # Metadaten
        meta = [["Rechnungsdatum:", dto.rechnungsdatum],
                ["Fällig bis:",     dto.faelligkeitsdatum or "–"]]
        if getattr(dto, "kunde_zifferncode", None):
            meta.append(["Kundennummer:", str(dto.kunde_zifferncode)])
        if storno_zu:
            meta.append(["Gutschrift zu:", storno_zu])

        mt = Table(meta, colWidths=[42*mm, 65*mm], hAlign="LEFT")
        mt.setStyle(TableStyle([
            ("FONTNAME",      (0,0),(-1,-1),"Helvetica"),
            ("FONTSIZE",      (0,0),(-1,-1), 9),
            ("TEXTCOLOR",     (0,0),(0,-1),  C_SECONDARY),
            ("TEXTCOLOR",     (1,0),(1,-1),  C_DARK),
            ("FONTNAME",      (1,0),(1,-1),  "Helvetica-Bold"),
            ("TOPPADDING",    (0,0),(-1,-1), 2),
            ("BOTTOMPADDING", (0,0),(-1,-1), 2),
            ("BACKGROUND",    (0,0),(-1,-1), C_BG_LIGHT),
            ("GRID",          (0,0),(-1,-1), 0.3, C_BORDER),
        ]))
        story.append(mt)
        story.append(Spacer(1, 8*mm))

        # ── Positionstabelle ──────────────────────────────────────────
        # Feste Spaltenbreiten in mm (Summe = 167mm ≈ 170mm Nutzbreite)
        WP  = 10*mm   # Pos
        WM  = 18*mm   # Menge
        WE  = 16*mm   # Einheit
        WEP = 28*mm   # Einzelpreis
        WG  = 28*mm   # Gesamt
        WB  = w - WP - WM - WE - WEP - WG  # Bezeichnung (Rest ~67mm)

        kopf = ["Pos.", "Bezeichnung", "Menge", "Einheit", "Einzelpreis", "Gesamt"]
        rows = [kopf]
        for p in dto.posten:
            bez = p.beschreibung or ""
            if getattr(p, "artikelnummer", None):
                bez += f"\n{p.artikelnummer}"
            rows.append([
                str(p.position), bez,
                _fmt_menge(p.menge), p.einheit or "",
                _fmt(p.einzelpreis_netto), _fmt(p.gesamtpreis_netto),
            ])

        pt = Table(rows, colWidths=[WP, WB, WM, WE, WEP, WG], repeatRows=1)
        pt.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),(-1,0),  C_TABLE_HEAD),
            ("FONTNAME",      (0,0),(-1,0),  "Helvetica-Bold"),
            ("FONTSIZE",      (0,0),(-1,0),  8.5),
            ("TEXTCOLOR",     (0,0),(-1,0),  C_SECONDARY),
            ("TOPPADDING",    (0,0),(-1,0),  5),
            ("BOTTOMPADDING", (0,0),(-1,0),  5),
            ("LINEBELOW",     (0,0),(-1,0),  0.8, C_PRIMARY),
            ("FONTNAME",      (0,1),(-1,-1), "Helvetica"),
            ("FONTSIZE",      (0,1),(-1,-1), 9),
            ("TEXTCOLOR",     (0,1),(-1,-1), C_DARK),
            ("TOPPADDING",    (0,1),(-1,-1), 5),
            ("BOTTOMPADDING", (0,1),(-1,-1), 5),
            ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
            ("ALIGN",         (2,0),(-1,-1), "RIGHT"),   # Menge, EP, Gesamt rechts
            ("LINEBELOW",     (0,1),(-1,-1), 0.3, C_BORDER),
            *[("BACKGROUND",  (0,i),(-1,i),  C_BG_LIGHT) for i in range(2,len(rows),2)],
        ]))
        story.append(pt)
        story.append(Spacer(1, 5*mm))

        # ── Summen ────────────────────────────────────────────────────
        mwst_pct = dto.mwst_prozent
        summen = [
            [Paragraph("Nettobetrag:",           s["summen_key"]),
             Paragraph(_fmt(dto.summe_netto),     s["summen_val"])],
            [Paragraph(f"MwSt. {mwst_pct:g} %:", s["summen_key"]),
             Paragraph(_fmt(dto.summe_mwst),      s["summen_val"])],
        ]
        if getattr(dto, "mahngebuehren", None) and dto.mahngebuehren > 0:
            summen.append([
                Paragraph("Mahngebühren:", s["summen_key"]),
                Paragraph(_fmt(dto.mahngebuehren), s["summen_val"]),
            ])
        summen.append([
            Paragraph("Gesamtbetrag:", s["gesamt_key"]),
            Paragraph(_fmt(dto.summe_brutto), s["gesamt_val"]),
        ])

        st = Table(summen, colWidths=[w - 55*mm, 55*mm], hAlign="RIGHT")
        st.setStyle(TableStyle([
            ("TOPPADDING",    (0,0),(-1,-2), 2),
            ("BOTTOMPADDING", (0,0),(-1,-2), 2),
            ("TOPPADDING",    (0,-1),(-1,-1), 6),
            ("BOTTOMPADDING", (0,-1),(-1,-1), 6),
            ("LINEABOVE",     (0,-1),(-1,-1), 1.2, C_PRIMARY),
            ("BACKGROUND",    (0,-1),(-1,-1), C_TOTAL_BG),
        ]))
        story.append(st)

        # ── Bemerkung ─────────────────────────────────────────────────
        if getattr(dto, "bemerkung", None):
            story.append(Spacer(1, 6*mm))
            story.append(HRFlowable(width="100%", thickness=0.5, color=C_BORDER))
            story.append(Paragraph(
                f"<b>Bemerkung:</b><br/>"
                + dto.bemerkung.replace("\n", "<br/>"),
                s["hinweis"],
            ))

        # ── Zahlungshinweis (editierbar via Textvorlagen) ───────────
        story.append(Spacer(1, 8*mm))
        bank = config.get("company", "bank_details", "")
        _vorlagen = load_vorlagen()
        _ctx = build_context(dto, session)
        _hint = resolve(_vorlagen.get("rechnung_hinweis", ""), _ctx)
        if not _hint:
            fällig = getattr(dto, "faelligkeitsdatum", None) or "–"
            _hint = (f"Bitte überweisen Sie den Gesamtbetrag von "
                     f"<b>{_fmt(dto.summe_brutto)}</b> bis zum <b>{fällig}</b>.")
        if bank:
            _hint += f"<br/><b>Bankverbindung:</b> {bank}"
        story.append(Paragraph(_hint, s["hinweis"]))

        return story


    # ------------------------------------------------------------------
    # Mahnschreiben
    # ------------------------------------------------------------------

    def mahnung_als_pdf_bytes(self, dto, konfig=None) -> bytes:
        """Erzeugt ein Mahnschreiben als PDF-Bytes für dto (UeberfaelligeDTO)."""
        from io import BytesIO
        buf = BytesIO()
        self._build_mahnung(buf, dto, konfig)
        return buf.getvalue()

    def mahnung_als_datei(self, dto, konfig=None, ausgabe_verzeichnis=None) -> tuple:
        """Speichert Mahnschreiben als PDF-Datei, gibt (ok, pfad_oder_fehler) zurück."""
        try:
            data = self.mahnung_als_pdf_bytes(dto, konfig)
            if not ausgabe_verzeichnis:
                ausgabe_verzeichnis = config.get("paths", "pdf_output", "")
            if not ausgabe_verzeichnis:
                ausgabe_verzeichnis = str(Path.home() / "OpenPhoenix" / "Mahnungen")
            os.makedirs(ausgabe_verzeichnis, exist_ok=True)
            safe_nr = dto.rechnungsnummer.replace("/", "-").replace("\\", "-")
            stufe_key = dto.status.replace(" ", "_")[:20]
            pfad = str(Path(ausgabe_verzeichnis) / f"Mahnung_{safe_nr}_{stufe_key}.pdf")
            with open(pfad, "wb") as f:
                f.write(data)
            return True, pfad
        except Exception as e:
            logger.exception("Mahnschreiben-PDF fehlgeschlagen:")
            return False, str(e)

    def _build_mahnung(self, buf, dto, konfig):
        sw, sh = A4
        s = _styles()

        # Kundenadresse + Session für Platzhalter
        from core.db.engine import db
        from core.models import Kunde as KundeModel
        kunde = {"name": dto.kunde_display}
        _session = db.get_session()
        try:
            k = _session.get(KundeModel, dto.kunde_id)
            if k:
                kunde["strasse"] = " ".join(filter(None, [k.strasse or "", k.hausnummer or ""])).strip()
                kunde["plz"] = k.plz or ""
                kunde["ort"] = k.ort or ""
        except Exception:
            _session = None

        bg_aktiv  = _has_background()
        top_m     = 80*mm if bg_aktiv else 77*mm

        frame = Frame(
            20*mm, 22*mm, sw - 40*mm, sh - top_m - 22*mm,
            leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
        )
        def hf(canvas, doc):
            _draw_background(canvas, sw, sh)
            canvas.saveState()
            self._kopf(canvas, sw, sh, kunde)
            self._fuss(canvas, sw)
            canvas.restoreState()

        doc = BaseDocTemplate(
            buf, pagesize=A4,
            pageTemplates=[PageTemplate(id="M", frames=[frame], onPage=hf)],
            leftMargin=20*mm, rightMargin=20*mm,
            topMargin=top_m, bottomMargin=22*mm,
        )
        try:
            doc.build(self._mahnung_story(dto, s, sw - 40*mm, konfig,
                                          session=_session))
        finally:
            if _session is not None:
                try:
                    _session.close()
                except Exception:
                    pass

    def _mahnung_story(self, dto, s, w, konfig, session=None):
        from decimal import Decimal as D
        from datetime import date
        from core.services.platzhalter_service import (
            load_vorlagen, resolve, build_context, vorlagen_key_fuer_status
        )

        STUFEN_LABEL = {
            "Steht zur Erinnerung an":          ("ZAHLUNGSERINNERUNG",  "#3B82F6"),
            "Steht zur Mahnung an":             ("1. MAHNUNG",           "#F97316"),
            "Steht zur Mahnung 2 an":           ("2. MAHNUNG",           "#EF4444"),
            "Bitte an Inkasso weiterleiten":    ("LETZTE MAHNUNG / INKASSO", "#DC2626"),
        }
        titel_text, titel_farbe = STUFEN_LABEL.get(dto.status, ("MAHNUNG", "#EF4444"))
        titel_farbe_hex = HexColor(titel_farbe)

        c_firma = config.get("company", "name", "Ihr Unternehmen")
        heute = date.today().strftime("%d.%m.%Y")

        mahngebuehr = D(str(dto.mahngebuehren or "0"))
        offen       = D(str(dto.offener_betrag or "0"))
        gesamt      = offen + mahngebuehr

        zahlungsziel = konfig.reminder_days if konfig else 7
        from datetime import date as ddate, timedelta
        faellig_neu = (ddate.today() + timedelta(days=zahlungsziel)).strftime("%d.%m.%Y")

        # Extra-Style für Mahnung-Titel
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.enums import TA_LEFT
        s_titel = ParagraphStyle(
            "mahnung_titel", fontSize=18, fontName="Helvetica-Bold",
            textColor=titel_farbe_hex, leading=22, spaceAfter=4,
        )
        s_normal = ParagraphStyle(
            "m_normal", fontSize=10, leading=15, spaceAfter=4,
            textColor=HexColor("#111827"),
        )
        s_bold = ParagraphStyle(
            "m_bold", fontSize=10, fontName="Helvetica-Bold",
            leading=15, spaceAfter=4, textColor=HexColor("#111827"),
        )
        s_klein = ParagraphStyle(
            "m_klein", fontSize=8.5, leading=13, textColor=HexColor("#6B7280"),
        )

        story = [Spacer(1, 4*mm)]

        # Titel
        story.append(Paragraph(titel_text, s_titel))
        story.append(Paragraph(f"Datum: {heute}", s_klein))
        story.append(Spacer(1, 6*mm))

        # Anschreiben – Text aus editierbaren Textvorlagen
        _vorlagen = load_vorlagen()
        _ctx = build_context(dto, session=session, extra={"MAHNSTUFE": titel_text})
        _k_titel, _k_text, _k_schluss = vorlagen_key_fuer_status(dto.status)
        _intro = resolve(_vorlagen.get(_k_text, ""), _ctx)
        # Intro-Text: erste Zeile als Anrede, Rest als Body
        _lines = _intro.split("\n", 2)
        if len(_lines) >= 1:
            story.append(Paragraph(_lines[0], s_normal))
            story.append(Spacer(1, 3*mm))
        if len(_lines) >= 3:
            story.append(Paragraph(_lines[2].strip(), s_normal))
        elif len(_lines) == 2:
            story.append(Paragraph(_lines[1].strip(), s_normal))
        story.append(Spacer(1, 5*mm))

        # Tabelle Rechnungsdetails
        tdata = [
            ["Rechnungsnummer:", dto.rechnungsnummer],
            ["Rechnungsdatum:", dto.rechnungsdatum],
            ["Fällig seit:", dto.faelligkeitsdatum],
            ["Rechnungsbetrag:", _fmt(D(str(dto.summe_brutto or "0")))],
        ]
        if offen < D(str(dto.summe_brutto or "0")):
            tdata.append(["Bereits gezahlt:", _fmt(D(str(dto.summe_brutto or "0")) - offen)])
        tdata.append(["Offener Betrag:", _fmt(offen)])
        if mahngebuehr > 0:
            tdata.append(["Mahngebühr:", _fmt(mahngebuehr)])
            tdata.append(["Gesamtbetrag:", _fmt(gesamt)])

        tbl = Table(tdata, colWidths=[55*mm, w - 55*mm])
        tbl.setStyle(TableStyle([
            ("FONTNAME",    (0,0), (-1,-1), "Helvetica"),
            ("FONTSIZE",    (0,0), (-1,-1), 10),
            ("FONTNAME",    (0,0), (0,-1),  "Helvetica-Bold"),
            ("TEXTCOLOR",   (0,0), (0,-1),  HexColor("#6B7280")),
            ("TEXTCOLOR",   (1,0), (1,-1),  HexColor("#111827")),
            ("ROWBACKGROUNDS", (0,0), (-1,-1), [HexColor("#F9FAFB"), colors.white]),
            ("TOPPADDING",  (0,0), (-1,-1), 5),
            ("BOTTOMPADDING",(0,0),(-1,-1), 5),
            ("LEFTPADDING", (0,0), (-1,-1), 8),
            ("FONTNAME",    (0,-1),(1,-1),  "Helvetica-Bold"),
            ("FONTSIZE",    (0,-1),(1,-1),  11),
            ("BACKGROUND",  (0,-1),(-1,-1), HexColor("#EEF2FF")),
            ("TEXTCOLOR",   (1,-1),(1,-1),  HexColor("#6C63FF")),
        ]))
        story.append(tbl)
        story.append(Spacer(1, 5*mm))

        # Schlusstext aus Vorlage
        _schluss = resolve(_vorlagen.get(_k_schluss, ""), _ctx)
        bank = config.get("company", "bank_details", "")
        if bank:
            story.append(Paragraph(
                f"Bitte überweisen Sie auf unser Konto:", s_normal))
            story.append(Spacer(1, 2*mm))
            story.append(Paragraph(bank.replace("\n", "<br/>"), s_bold))
            story.append(Spacer(1, 4*mm))
        if _schluss:
            for _line in _schluss.split("\n"):
                if _line.strip():
                    story.append(Paragraph(_line, s_normal))
                else:
                    story.append(Spacer(1, 3*mm))
        else:
            story.append(Paragraph(f"Mit freundlichen Grüßen", s_normal))
            story.append(Spacer(1, 2*mm))
            story.append(Paragraph(f"<b>{c_firma}</b>", s_normal))

        return story

    def _kundenadresse(self, dto, session) -> dict:
        result = {"name": getattr(dto, "kunde_display", "")}
        if session is None:
            return result
        try:
            from core.models import Kunde
            k = session.get(Kunde, dto.kunde_id)
            if k:
                result["strasse"] = " ".join(
                    filter(None, [k.strasse or "", k.hausnummer or ""])
                ).strip()
                result["plz"]        = k.plz or ""
                result["ort"]        = k.ort or ""
                result["zifferncode"] = k.zifferncode or ""
        except Exception:
            pass
        return result


pdf_service = PDFService()
