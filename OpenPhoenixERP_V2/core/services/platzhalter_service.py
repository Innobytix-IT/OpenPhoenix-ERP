"""
core/services/platzhalter_service.py – Zentraler Platzhalter- und Textvorlagen-Service
========================================================================================
Verwaltet:
  - Eingebaute Platzhalter ({{KEY}} → Wert aus Rechnungs-/Kundendaten)
  - Benutzerdefinierte Platzhalter ({{EIGENER_KEY}} → fester Text, gespeichert in JSON)
  - Editierbare Textvorlagen (Mahnschreiben, Rechnungshinweis, E-Mail)
"""

import json
import logging
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Optional

from core.config import config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dateipfade
# ---------------------------------------------------------------------------

def _config_dir() -> Path:
    p = Path("config")
    p.mkdir(exist_ok=True)
    return p

CUSTOM_PH_FILE    = lambda: _config_dir() / "custom_placeholders.json"
VORLAGEN_FILE     = lambda: _config_dir() / "text_vorlagen.json"

# ---------------------------------------------------------------------------
# Eingebaute Platzhalter – Beschreibungen (für Editor-Anzeige)
# ---------------------------------------------------------------------------

BUILTIN_PLACEHOLDERS: dict[str, str] = {
    # Kundendaten
    "KUNDE_NAME":           "Vollständiger Name des Kunden",
    "KUNDE_VORNAME":        "Vorname des Kunden",
    "KUNDE_NACHNAME":       "Nachname / Firmenname des Kunden",
    "BRIEFANREDE":          "Vollständige Anredezeile (z.B. 'Sehr geehrter Herr Müller,')",
    "KUNDE_ANREDE_NAME":    "Anrede + Name (z.B. 'Herr Mustermann')",
    "KUNDE_STRASSE_NR":     "Straße und Hausnummer des Kunden",
    "KUNDE_PLZ_ORT":        "PLZ und Ort des Kunden",
    "KUNDENNUMMER":         "Kundennummer (Zifferncode)",
    # Rechnungsdaten
    "RECHNUNGSNUMMER":      "Rechnungsnummer",
    "RECHNUNGSDATUM":       "Rechnungsdatum (TT.MM.JJJJ)",
    "FAELLIGKEITSDATUM":    "Fälligkeitsdatum (TT.MM.JJJJ)",
    "BETRAG_BRUTTO":        "Gesamtbetrag brutto (z.B. 1.234,56 €)",
    "BETRAG_NETTO":         "Gesamtbetrag netto",
    "BETRAG_OFFEN":         "Noch offener Betrag",
    "BETRAG_MWST":          "MwSt.-Betrag",
    # Mahnwesen
    "MAHNKOSTEN":           "Mahngebühr dieser Stufe",
    "BETRAG_GESAMT_MAHNUNG":"Offener Betrag + Mahngebühr",
    "MAHNSTUFE":            "Aktuelle Mahnstufe (z.B. '1. Mahnung')",
    "DATUM_ZAHLUNGSZIEL":   "Neues Zahlungsziel (heute + Reminder-Tage)",
    # Datumshelfer
    "HEUTIGES_DATUM":       "Heutiges Datum (TT.MM.JJJJ)",
    "DATUM_IN_7_TAGEN":     "Datum in 7 Tagen",
    "DATUM_IN_5_TAGEN":     "Datum in 5 Tagen",
    "DATUM_IN_14_TAGEN":    "Datum in 14 Tagen",
    # Eigene Firmendaten
    "EIGENE_FIRMA_NAME":    "Eigener Firmenname",
    "EIGENE_FIRMA_ADRESSE": "Eigene Adresse",
    "EIGENE_FIRMA_PLZ_ORT": "Eigene PLZ + Ort",
    "EIGENE_FIRMA_TELEFON": "Eigene Telefonnummer",
    "EIGENE_FIRMA_EMAIL":   "Eigene E-Mail-Adresse",
    "EIGENE_FIRMA_STEUERID":"Eigene USt-ID / Steuernummer",
    "EIGENE_FIRMA_BANK":    "Eigene Bankverbindung",
    # Dokumentinfo
    "DATEINAME":            "Dateiname des Anhangs (nur E-Mail)",
}

# ---------------------------------------------------------------------------
# Standard-Textvorlagen
# ---------------------------------------------------------------------------

DEFAULT_VORLAGEN: dict[str, str] = {
    # ── Rechnungs-PDF ──────────────────────────────────────────────────────
    "rechnung_hinweis": (
        "Bitte überweisen Sie den Gesamtbetrag von <b>{{BETRAG_BRUTTO}}</b> "
        "bis zum <b>{{FAELLIGKEITSDATUM}}</b> unter Angabe der Rechnungsnummer "
        "auf unser Konto."
    ),

    # ── Mahnschreiben ──────────────────────────────────────────────────────
    "mahnung_erinnerung_titel":
        "Zahlungserinnerung zu Rechnung Nr. {{RECHNUNGSNUMMER}}",
    "mahnung_erinnerung_text": (
        "{{BRIEFANREDE}}\n\n"
        "wir erlauben uns, Sie freundlich daran zu erinnern, dass die Rechnung "
        "Nr. {{RECHNUNGSNUMMER}} vom {{RECHNUNGSDATUM}} über {{BETRAG_BRUTTO}} "
        "noch nicht beglichen wurde. Das Zahlungsziel war der {{FAELLIGKEITSDATUM}}.\n\n"
        "Sollte sich Ihre Zahlung mit diesem Schreiben gekreuzt haben, betrachten "
        "Sie diese Erinnerung bitte als gegenstandslos."
    ),
    "mahnung_erinnerung_schluss": (
        "Bitte überweisen Sie den offenen Betrag von {{BETRAG_OFFEN}} bis zum "
        "{{DATUM_ZAHLUNGSZIEL}} auf unser Konto.\n\nMit freundlichen Grüßen\n{{EIGENE_FIRMA_NAME}}"
    ),

    "mahnung_1_titel":
        "1. Mahnung zu Rechnung Nr. {{RECHNUNGSNUMMER}}",
    "mahnung_1_text": (
        "{{BRIEFANREDE}}\n\n"
        "trotz unserer Zahlungserinnerung konnten wir für Ihre Rechnung "
        "Nr. {{RECHNUNGSNUMMER}} vom {{RECHNUNGSDATUM}} über {{BETRAG_BRUTTO}} "
        "leider noch keinen Zahlungseingang verzeichnen.\n\n"
        "Für den hierdurch entstandenen Aufwand berechnen wir Ihnen eine "
        "Mahngebühr von {{MAHNKOSTEN}}."
    ),
    "mahnung_1_schluss": (
        "Wir fordern Sie auf, den Gesamtbetrag von {{BETRAG_GESAMT_MAHNUNG}} "
        "bis zum {{DATUM_IN_7_TAGEN}} zu überweisen.\n\n"
        "Mit freundlichen Grüßen\n{{EIGENE_FIRMA_NAME}}"
    ),

    "mahnung_2_titel":
        "2. Mahnung zu Rechnung Nr. {{RECHNUNGSNUMMER}}",
    "mahnung_2_text": (
        "{{BRIEFANREDE}}\n\n"
        "trotz unserer 1. Mahnung steht die Zahlung der Rechnung "
        "Nr. {{RECHNUNGSNUMMER}} vom {{RECHNUNGSDATUM}} über {{BETRAG_BRUTTO}} "
        "noch immer aus.\n\n"
        "Wir fordern Sie hiermit letztmalig auf, den Betrag unverzüglich zu "
        "überweisen, um weitere Maßnahmen zu vermeiden."
    ),
    "mahnung_2_schluss": (
        "Überweisen Sie den Gesamtbetrag von {{BETRAG_GESAMT_MAHNUNG}} "
        "bis spätestens {{DATUM_IN_5_TAGEN}}.\n\n"
        "Mit freundlichen Grüßen\n{{EIGENE_FIRMA_NAME}}"
    ),

    "mahnung_inkasso_titel":
        "Letzte Mahnung / Inkasso-Ankündigung zu Rechnung Nr. {{RECHNUNGSNUMMER}}",
    "mahnung_inkasso_text": (
        "{{BRIEFANREDE}}\n\n"
        "da Sie trotz mehrfacher Aufforderung die Rechnung "
        "Nr. {{RECHNUNGSNUMMER}} vom {{RECHNUNGSDATUM}} über {{BETRAG_BRUTTO}} "
        "nicht beglichen haben, sehen wir uns gezwungen, diese Forderung an "
        "ein Inkassounternehmen zu übergeben, sofern kein Zahlungseingang bis "
        "zum angegebenen Datum erfolgt.\n\n"
        "Die dadurch entstehenden Kosten gehen zu Ihren Lasten."
    ),
    "mahnung_inkasso_schluss": (
        "Letzte Zahlungsmöglichkeit bis zum {{DATUM_IN_5_TAGEN}}.\n\n"
        "Mit freundlichen Grüßen\n{{EIGENE_FIRMA_NAME}}"
    ),

    # ── E-Mail ─────────────────────────────────────────────────────────────
    "email_standard_betreff":
        "Dokument: {{DATEINAME}}",
    "email_standard_text": (
        "Sehr geehrte Damen und Herren,\n\n"
        "anbei erhalten Sie das Dokument '{{DATEINAME}}'.\n\n"
        "Mit freundlichen Grüßen\n{{EIGENE_FIRMA_NAME}}"
    ),
    "email_rechnung_betreff":
        "Rechnung Nr. {{RECHNUNGSNUMMER}} von {{EIGENE_FIRMA_NAME}}",
    "email_rechnung_text": (
        "{{BRIEFANREDE}}\n\n"
        "anbei erhalten Sie unsere Rechnung Nr. {{RECHNUNGSNUMMER}} "
        "vom {{RECHNUNGSDATUM}} über {{BETRAG_BRUTTO}}.\n\n"
        "Bitte überweisen Sie den Betrag bis zum {{FAELLIGKEITSDATUM}}.\n\n"
        "Mit freundlichen Grüßen\n{{EIGENE_FIRMA_NAME}}"
    ),
    "email_mahnung_betreff":
        "{{MAHNSTUFE}} zu Rechnung Nr. {{RECHNUNGSNUMMER}}",
    "email_mahnung_text": (
        "{{BRIEFANREDE}}\n\n"
        "anbei erhalten Sie unsere {{MAHNSTUFE}} zur Rechnung "
        "Nr. {{RECHNUNGSNUMMER}}.\n\n"
        "Mit freundlichen Grüßen\n{{EIGENE_FIRMA_NAME}}"
    ),
}

# ---------------------------------------------------------------------------
# Vorlagen laden / speichern
# ---------------------------------------------------------------------------

def load_vorlagen() -> dict[str, str]:
    """Lädt Textvorlagen – fehlende Keys werden mit Defaults aufgefüllt."""
    path = VORLAGEN_FILE()
    result = dict(DEFAULT_VORLAGEN)
    if path.exists():
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                # Migration: alten Platzhalter-Namen ersetzen
                saved = _migrate_vorlagen(saved)
                result.update(saved)
        except Exception as e:
            logger.warning(f"Textvorlagen konnten nicht geladen werden: {e}")
    return result


def _migrate_vorlagen(vorlagen: dict) -> dict:
    """Migriert veraltete Platzhalter-Namen in gespeicherten Vorlagen."""
    replacements = {
        # Alt → Neu
        "Sehr geehrte/r {{KUNDE_ANREDE_NAME}},": "{{BRIEFANREDE}}",
        "{{KUNDE_ANREDE_NAME}}":                 "{{BRIEFANREDE}}",
    }
    result = {}
    for key, text in vorlagen.items():
        for old, new in replacements.items():
            text = text.replace(old, new)
        result[key] = text
    return result

def save_vorlagen(vorlagen: dict[str, str]) -> bool:
    """Speichert Textvorlagen."""
    try:
        VORLAGEN_FILE().write_text(
            json.dumps(vorlagen, indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        return True
    except Exception as e:
        logger.error(f"Textvorlagen speichern fehlgeschlagen: {e}")
        return False

def reset_vorlage(key: str) -> str:
    """Gibt den Default-Text für einen Vorlagen-Key zurück."""
    return DEFAULT_VORLAGEN.get(key, "")

# ---------------------------------------------------------------------------
# Benutzerdefinierte Platzhalter laden / speichern
# ---------------------------------------------------------------------------

def load_custom_placeholders() -> dict[str, str]:
    """Lädt benutzerdefinierte Platzhalter aus JSON."""
    path = CUSTOM_PH_FILE()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning(f"Custom-Platzhalter konnten nicht geladen werden: {e}")
        return {}

def save_custom_placeholders(ph: dict[str, str]) -> bool:
    """Speichert benutzerdefinierte Platzhalter."""
    try:
        CUSTOM_PH_FILE().write_text(
            json.dumps(ph, indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        return True
    except Exception as e:
        logger.error(f"Custom-Platzhalter speichern fehlgeschlagen: {e}")
        return False

# ---------------------------------------------------------------------------
# Platzhalter auflösen
# ---------------------------------------------------------------------------

def _fmt_decimal(v) -> str:
    """Formatiert einen Decimal/float-Wert als Währungsstring."""
    try:
        d = Decimal(str(v)).quantize(Decimal("0.01"))
        s = f"{d:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"{s} €"
    except Exception:
        return str(v)

def _briefanrede(anrede: str, vorname: str, nachname: str) -> str:
    """
    Baut die grammatikalisch korrekte deutsche Anredezeile:
      Herr   → "Sehr geehrter Herr Müller,"
      Frau   → "Sehr geehrte Frau Müller,"
      Divers → "Sehr geehrte/r [Vorname] [Nachname],"
      (leer) → "Sehr geehrte/r [Vorname] [Nachname],"
    """
    name_voll = f"{vorname} {nachname}".strip() or nachname or vorname
    if anrede == "Herr":
        return f"Sehr geehrter Herr {nachname},"
    elif anrede == "Frau":
        return f"Sehr geehrte Frau {nachname},"
    else:
        # Divers oder keine Angabe: geschlechtsneutral mit vollem Namen
        return f"Sehr geehrte/r {name_voll},"


def resolve(template: str, context: dict[str, str]) -> str:
    """Ersetzt alle {{KEY}}-Platzhalter im Template durch context-Werte."""
    if not template:
        return ""
    result = template
    for key, value in context.items():
        result = result.replace(f"{{{{{key}}}}}", str(value) if value is not None else "")
    return result

def build_context(
    dto=None,
    session=None,
    dateiname: str = "",
    extra: Optional[dict] = None,
) -> dict[str, str]:
    """
    Baut den kompletten Platzhalter-Kontext aus einem Rechnungs-/Mahnungs-DTO,
    Firmendaten aus config und optional extra-Werten.
    """
    c = config
    heute = date.today()
    ctx: dict[str, str] = {
        # Datum-Helfer
        "HEUTIGES_DATUM":   heute.strftime("%d.%m.%Y"),
        "DATUM_IN_5_TAGEN": (heute + timedelta(days=5)).strftime("%d.%m.%Y"),
        "DATUM_IN_7_TAGEN": (heute + timedelta(days=7)).strftime("%d.%m.%Y"),
        "DATUM_IN_14_TAGEN":(heute + timedelta(days=14)).strftime("%d.%m.%Y"),
        # Eigene Firma
        "EIGENE_FIRMA_NAME":    c.get("company", "name", ""),
        "EIGENE_FIRMA_ADRESSE": c.get("company", "address", ""),
        "EIGENE_FIRMA_PLZ_ORT": c.get("company", "zip_city", ""),
        "EIGENE_FIRMA_TELEFON": c.get("company", "phone", ""),
        "EIGENE_FIRMA_EMAIL":   c.get("company", "email", ""),
        "EIGENE_FIRMA_STEUERID":c.get("company", "tax_id", ""),
        "EIGENE_FIRMA_BANK":    c.get("company", "bank_details", ""),
        # Dokument
        "DATEINAME": dateiname,
    }

    if dto is not None:
        # Rechnungsdaten
        ctx["RECHNUNGSNUMMER"]   = getattr(dto, "rechnungsnummer", "")
        ctx["RECHNUNGSDATUM"]    = str(getattr(dto, "rechnungsdatum", ""))
        ctx["FAELLIGKEITSDATUM"] = str(getattr(dto, "faelligkeitsdatum", "") or "")
        ctx["BETRAG_BRUTTO"]     = _fmt_decimal(getattr(dto, "summe_brutto", 0))
        ctx["BETRAG_NETTO"]      = _fmt_decimal(getattr(dto, "summe_netto", 0))
        ctx["BETRAG_OFFEN"]      = _fmt_decimal(getattr(dto, "offener_betrag", 0)
                                                or getattr(dto, "summe_brutto", 0))
        ctx["BETRAG_MWST"]       = _fmt_decimal(getattr(dto, "summe_mwst", 0))
        ctx["KUNDENNUMMER"]      = str(getattr(dto, "kunde_zifferncode", "") or "")
        ctx["MAHNSTUFE"]         = _mahnstufe_label(getattr(dto, "status", ""))

        # Mahngebühren
        mahn = Decimal(str(getattr(dto, "mahngebuehren", 0) or 0))
        offen = Decimal(str(getattr(dto, "offener_betrag", 0)
                            or getattr(dto, "summe_brutto", 0)))
        ctx["MAHNKOSTEN"]              = _fmt_decimal(mahn)
        ctx["BETRAG_GESAMT_MAHNUNG"]   = _fmt_decimal(offen + mahn)

        # Zahlungsziel (Reminder-Tage aus config)
        reminder = int(c.get("mahnwesen", "reminder_days", 7))
        ctx["DATUM_ZAHLUNGSZIEL"] = (heute + timedelta(days=reminder)).strftime("%d.%m.%Y")

        # Kundendaten aus Session laden
        if session is not None:
            try:
                from core.models import Kunde
                k = session.get(Kunde, dto.kunde_id)
                if k:
                    vorname  = k.vorname or ""
                    nachname = k.name or ""       # Kunde.name = Nachname
                    anrede   = k.anrede or ""
                    ctx["KUNDE_VORNAME"]   = vorname
                    ctx["KUNDE_NACHNAME"]  = nachname
                    ctx["KUNDE_NAME"]      = f"{vorname} {nachname}".strip()
                    # KUNDE_ANREDE_NAME: Anrede + Nachname (z.B. "Herr Müller")
                    ctx["KUNDE_ANREDE_NAME"] = f"{anrede} {nachname}".strip() if anrede else f"{vorname} {nachname}".strip()
                    # BRIEFANREDE: grammatikalisch korrekte Anredezeile
                    ctx["BRIEFANREDE"] = _briefanrede(anrede, vorname, nachname)
                    ctx["KUNDE_STRASSE_NR"] = " ".join(
                        filter(None, [k.strasse or "", k.hausnummer or ""])
                    ).strip()
                    ctx["KUNDE_PLZ_ORT"] = f"{k.plz or ''} {k.ort or ''}".strip()
                    ctx["KUNDENNUMMER"]  = str(k.zifferncode or "")
            except Exception as e:
                logger.warning(f"Kundendaten für Platzhalter nicht ladbar: {e}")
        # Fallback: wenn Session fehlt oder DB-Abfrage fehlschlug
        if "BRIEFANREDE" not in ctx and hasattr(dto, "kunde_display"):
            ctx["KUNDE_NAME"]        = dto.kunde_display
            ctx["KUNDE_ANREDE_NAME"] = dto.kunde_display
            ctx["KUNDE_NACHNAME"]    = dto.kunde_display
            ctx["BRIEFANREDE"]       = f"Sehr geehrte/r {dto.kunde_display},"

    # Benutzerdefinierte Platzhalter (überschreiben nichts Eingebautes)
    for key, val in load_custom_placeholders().items():
        inner = key.strip("{}").strip()
        if inner not in ctx:
            ctx[inner] = val

    if extra:
        ctx.update(extra)

    return ctx

def _mahnstufe_label(status: str) -> str:
    return {
        "Steht zur Erinnerung an":       "Zahlungserinnerung",
        "Steht zur Mahnung an":          "1. Mahnung",
        "Steht zur Mahnung 2 an":        "2. Mahnung",
        "Bitte an Inkasso weiterleiten": "Letzte Mahnung / Inkasso",
    }.get(status, "Mahnung")

def vorlagen_key_fuer_status(status: str) -> tuple[str, str, str]:
    """Gibt die drei Vorlagen-Keys (Titel, Text, Schluss) für einen Mahnstatus zurück."""
    prefix = {
        "Steht zur Erinnerung an":       "erinnerung",
        "Steht zur Mahnung an":          "1",
        "Steht zur Mahnung 2 an":        "2",
        "Bitte an Inkasso weiterleiten": "inkasso",
    }.get(status, "erinnerung")
    p = f"mahnung_{prefix}"
    return f"{p}_titel", f"{p}_text", f"{p}_schluss"
