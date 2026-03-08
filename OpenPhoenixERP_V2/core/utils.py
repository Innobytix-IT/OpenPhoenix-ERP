"""core/utils.py – Allgemeine Hilfsfunktionen"""
from datetime import datetime


def parse_datum(datum_str: str):
    """Parst TT.MM.JJJJ oder JJJJ-MM-TT → date-Objekt, oder None."""
    if not datum_str:
        return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(datum_str.strip(), fmt).date()
        except ValueError:
            continue
    return None
