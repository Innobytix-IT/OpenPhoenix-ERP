"""
core/models/__init__.py – Alle Datenbankmodelle für OpenPhoenix ERP
====================================================================
Jedes Modell entspricht einer Datenbanktabelle.
SQLAlchemy übersetzt diese Klassen automatisch in SQL —
egal ob SQLite oder PostgreSQL.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, Numeric,
    String, Text, func, UniqueConstraint
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.db.engine import Base


# ---------------------------------------------------------------------------
# Kunde
# ---------------------------------------------------------------------------

class Kunde(Base):
    __tablename__ = "kunden"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    zifferncode: Mapped[Optional[int]] = mapped_column(Integer, unique=True, index=True)
    anrede: Mapped[Optional[str]] = mapped_column(String(20))  # Herr / Frau / Divers
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    vorname: Mapped[str] = mapped_column(String(100), nullable=False)
    titel_firma: Mapped[Optional[str]] = mapped_column(String(200))
    geburtsdatum: Mapped[Optional[str]] = mapped_column(String(10))  # TT.MM.JJJJ
    strasse: Mapped[Optional[str]] = mapped_column(String(200))
    hausnummer: Mapped[Optional[str]] = mapped_column(String(20))
    plz: Mapped[Optional[str]] = mapped_column(String(10))
    ort: Mapped[Optional[str]] = mapped_column(String(100))
    telefon: Mapped[Optional[str]] = mapped_column(String(50))
    email: Mapped[Optional[str]] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    erstellt_am: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )
    geaendert_am: Mapped[Optional[datetime]] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=True
    )

    # Beziehungen
    rechnungen: Mapped[list["Rechnung"]] = relationship(
        back_populates="kunde",
        cascade="save-update, merge",
        passive_deletes=True,
    )
    dokumente: Mapped[list["KundenDokument"]] = relationship(
        back_populates="kunde",
        cascade="all, delete-orphan",
    )
    notizen: Mapped[list["KundenNotiz"]] = relationship(
        back_populates="kunde",
        cascade="all, delete-orphan",
        order_by="KundenNotiz.erstellt_am.desc()",
    )
    angebote: Mapped[list["Angebot"]] = relationship(
        back_populates="kunde",
        cascade="save-update, merge",
    )

    @property
    def display_name(self) -> str:
        parts = [self.vorname, self.name]
        if self.titel_firma:
            parts.append(f"({self.titel_firma})")
        return " ".join(p for p in parts if p)

    def __repr__(self) -> str:
        return f"<Kunde id={self.id} name='{self.display_name}' nr={self.zifferncode}>"


# ---------------------------------------------------------------------------
# KundenDokument
# ---------------------------------------------------------------------------

class KundenDokument(Base):
    __tablename__ = "kunden_dokumente"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kunde_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("kunden.id", ondelete="CASCADE"), nullable=False,
        index=True,
    )
    dokument_pfad: Mapped[str] = mapped_column(Text, nullable=False)
    dateiname: Mapped[str] = mapped_column(String(255), nullable=False)
    erstellt_am: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    # Beziehungen
    kunde: Mapped["Kunde"] = relationship(back_populates="dokumente")

    def __repr__(self) -> str:
        return f"<KundenDokument id={self.id} datei='{self.dateiname}'>"


# ---------------------------------------------------------------------------
# Artikel
# ---------------------------------------------------------------------------

class Artikel(Base):
    __tablename__ = "artikel"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    artikelnummer: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    beschreibung: Mapped[str] = mapped_column(String(500), nullable=False)
    einheit: Mapped[Optional[str]] = mapped_column(String(20))
    einzelpreis_netto: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal("0"))
    verfuegbar: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    erstellt_am: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    def __repr__(self) -> str:
        return f"<Artikel nr='{self.artikelnummer}' beschreibung='{self.beschreibung}'>"


# ---------------------------------------------------------------------------
# LagerBewegung – vollständige Buchungshistorie
# ---------------------------------------------------------------------------

class LagerBewegung(Base):
    """
    Jede Bestandsänderung wird hier unveränderbar protokolliert.
    Erlaubt vollständige Rekonstruktion des Lagerbestands.
    """
    __tablename__ = "lager_bewegungen"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    artikelnummer: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("artikel.artikelnummer", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    buchungsart: Mapped[str] = mapped_column(String(30), nullable=False)
    menge: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    bestand_vor: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    bestand_nach: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    referenz: Mapped[Optional[str]] = mapped_column(String(100))
    notiz: Mapped[Optional[str]] = mapped_column(Text)
    user: Mapped[str] = mapped_column(String(100), default="system", nullable=False)
    erstellt_am: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False, index=True
    )

    def __repr__(self) -> str:
        return (
            f"<LagerBewegung art='{self.artikelnummer}' "
            f"typ='{self.buchungsart}' menge={self.menge}>"
        )


# ---------------------------------------------------------------------------
# Rechnung
# ---------------------------------------------------------------------------

class Rechnung(Base):
    __tablename__ = "rechnungen"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kunde_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("kunden.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    rechnungsnummer: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    rechnungsdatum: Mapped[str] = mapped_column(String(10), nullable=False)  # TT.MM.JJJJ
    faelligkeitsdatum: Mapped[Optional[str]] = mapped_column(String(10))
    mwst_prozent: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("19.00"))
    summe_netto: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 4))
    summe_mwst: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 4))
    summe_brutto: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 4))
    mahngebuehren: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal("0"))
    offener_betrag: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 4))
    status: Mapped[str] = mapped_column(String(50), default="Entwurf", nullable=False, index=True)
    bemerkung: Mapped[Optional[str]] = mapped_column(Text)
    is_finalized: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    storno_zu_nr: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # Originalnummer bei Gutschriften
    erstellt_am: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    geaendert_am: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now()
    )

    # Beziehungen
    kunde: Mapped["Kunde"] = relationship(back_populates="rechnungen")
    posten: Mapped[list["Rechnungsposten"]] = relationship(
        back_populates="rechnung",
        cascade="all, delete-orphan",
        order_by="Rechnungsposten.position",
    )

    def __repr__(self) -> str:
        return f"<Rechnung nr='{self.rechnungsnummer}' status='{self.status}'>"


# ---------------------------------------------------------------------------
# Rechnungsposten
# ---------------------------------------------------------------------------

class Rechnungsposten(Base):
    __tablename__ = "rechnungsposten"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rechnung_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("rechnungen.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    artikelnummer: Mapped[Optional[str]] = mapped_column(
        String(50), index=True,
    )  # Informativ – kein FK, da freie Artikelnummern auf Rechnungen erlaubt sind
    beschreibung: Mapped[str] = mapped_column(String(500), nullable=False)
    menge: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    einheit: Mapped[Optional[str]] = mapped_column(String(20))
    einzelpreis_netto: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    gesamtpreis_netto: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)

    # Beziehungen
    rechnung: Mapped["Rechnung"] = relationship(back_populates="posten")

    def __repr__(self) -> str:
        return f"<Rechnungsposten pos={self.position} '{self.beschreibung}'>"


# ---------------------------------------------------------------------------
# AuditLog (GoBD)
# ---------------------------------------------------------------------------

class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False, index=True
    )
    user: Mapped[str] = mapped_column(String(100), default="system", nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    record_id: Mapped[Optional[int]] = mapped_column(Integer)
    table_name: Mapped[Optional[str]] = mapped_column(String(50))
    details: Mapped[Optional[str]] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"<AuditLog action='{self.action}' user='{self.user}' ts='{self.timestamp}'>"


# ---------------------------------------------------------------------------
# Alle Modelle exportieren
# ---------------------------------------------------------------------------

__all__ = [
    "Base",
    "Kunde",
    "KundenDokument",
    "Artikel",
    "LagerBewegung",
    "Rechnung",
    "Rechnungsposten",
    "Angebot",
    "AngebotsPosten",
    "EingangsRechnung",
    "AuditLog",
]

# ---------------------------------------------------------------------------
# KundenNotiz
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Angebot
# ---------------------------------------------------------------------------

class Angebot(Base):
    """
    Ein Angebot / Kostenvoranschlag für einen Kunden.
    Status-Workflow: Entwurf → Offen → Angenommen / Abgelehnt / Abgelaufen
    """
    __tablename__ = "angebote"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kunde_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("kunden.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    angebotsnummer: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    angebotsdatum: Mapped[str] = mapped_column(String(10), nullable=False)  # TT.MM.JJJJ
    gueltig_bis: Mapped[Optional[str]] = mapped_column(String(10))  # TT.MM.JJJJ
    mwst_prozent: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("19.00"))
    summe_netto: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 4))
    summe_mwst: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 4))
    summe_brutto: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 4))
    status: Mapped[str] = mapped_column(String(50), default="Entwurf", nullable=False)
    bemerkung: Mapped[Optional[str]] = mapped_column(Text)
    erstellt_am: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    geaendert_am: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now()
    )

    # Beziehungen
    kunde: Mapped["Kunde"] = relationship(back_populates="angebote")
    posten: Mapped[list["AngebotsPosten"]] = relationship(
        back_populates="angebot",
        cascade="all, delete-orphan",
        order_by="AngebotsPosten.position",
    )

    def __repr__(self) -> str:
        return f"<Angebot nr='{self.angebotsnummer}' status='{self.status}'>"


# ---------------------------------------------------------------------------
# AngebotsPosten
# ---------------------------------------------------------------------------

class AngebotsPosten(Base):
    """Einzelne Position in einem Angebot – entweder aus Artikelstamm oder frei."""
    __tablename__ = "angebotsposten"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    angebot_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("angebote.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    artikelnummer: Mapped[Optional[str]] = mapped_column(
        String(50), index=True,
    )  # Informativ – kein FK, da freie Artikelnummern auf Angeboten erlaubt sind
    beschreibung: Mapped[str] = mapped_column(String(500), nullable=False)
    menge: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    einheit: Mapped[Optional[str]] = mapped_column(String(20))
    einzelpreis_netto: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    gesamtpreis_netto: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)

    # Beziehungen
    angebot: Mapped["Angebot"] = relationship(back_populates="posten")

    def __repr__(self) -> str:
        return f"<AngebotsPosten pos={self.position} '{self.beschreibung}'>"


# ---------------------------------------------------------------------------
# KundenNotiz
# ---------------------------------------------------------------------------

class KundenNotiz(Base):
    __tablename__ = "kunden_notizen"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kunde_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("kunden.id", ondelete="CASCADE"), nullable=False, index=True
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    autor: Mapped[Optional[str]] = mapped_column(String(100))
    erstellt_am: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)

    kunde: Mapped["Kunde"] = relationship(back_populates="notizen")

    def __repr__(self) -> str:
        return f"<KundenNotiz id={self.id} kunde_id={self.kunde_id}>"


# ---------------------------------------------------------------------------
# EingangsRechnung (Belege / Ausgaben)
# ---------------------------------------------------------------------------

class EingangsRechnung(Base):
    """
    Eingangsrechnung / Beleg – z.B. Tankquittung, Lieferantenrechnung.
    Ermöglicht die Erfassung von Ausgaben für die vorbereitende Buchhaltung.
    """
    __tablename__ = "eingangsrechnungen"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    datum: Mapped[str] = mapped_column(String(10), nullable=False)  # TT.MM.JJJJ
    lieferant: Mapped[str] = mapped_column(String(200), nullable=False)
    belegnummer: Mapped[Optional[str]] = mapped_column(String(100))
    betrag_netto: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    mwst_satz: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("19.00"))
    mwst_betrag: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 4))
    betrag_brutto: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 4))
    kategorie: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    bemerkung: Mapped[Optional[str]] = mapped_column(Text)
    zahlungsstatus: Mapped[str] = mapped_column(
        String(20), default="Offen", nullable=False, index=True
    )
    beleg_pfad: Mapped[Optional[str]] = mapped_column(Text)
    beleg_dateiname: Mapped[Optional[str]] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    erstellt_am: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )
    geaendert_am: Mapped[Optional[datetime]] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=True
    )

    def __repr__(self) -> str:
        return f"<EingangsRechnung id={self.id} lieferant='{self.lieferant}' brutto={self.betrag_brutto}>"
