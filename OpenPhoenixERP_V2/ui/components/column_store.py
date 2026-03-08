"""Persistente Spaltenbreiten-Speicherung für DataTable."""
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_DATEI = Path("config") / "column_widths.json"
_cache: dict = {}


def _laden() -> None:
    global _cache
    try:
        if _DATEI.exists():
            _cache = json.loads(_DATEI.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"Spaltenbreiten konnten nicht geladen werden: {e}")
        _cache = {}


def laden(table_id: str) -> dict[int, int]:
    """Gibt gespeicherte Spaltenbreiten für table_id zurück {col_index: width}."""
    if not _cache:
        _laden()
    return {int(k): v for k, v in _cache.get(table_id, {}).items()}


def speichern(table_id: str, breiten: dict[int, int]) -> None:
    """Speichert Spaltenbreiten für table_id persistent."""
    global _cache
    if not _cache and _DATEI.exists():
        _laden()
    _cache[table_id] = {str(k): v for k, v in breiten.items()}
    try:
        _DATEI.parent.mkdir(parents=True, exist_ok=True)
        _DATEI.write_text(json.dumps(_cache, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning(f"Spaltenbreiten konnten nicht gespeichert werden: {e}")
