"""
E-Mail-Parser für Hofmann SEA-Beauftragungen
=============================================
Parst den strukturierten E-Mail-Text im Hofmann-Format und extrahiert
alle relevanten Kampagnen-Felder.

Beispiel-E-Mail-Block:
==========
Job-Titel: Recruiter (m/w/d)
Job-Url: https://www.hofmann.info/jobs/stellenanzeige/...
Niederlassung / GruppenID: 2129
Einsatzort: 15890 Eisenhüttenstadt
Kostenstelle: 180
SMA Budget: 250,- €
Datum (zuletzt aktualisiert): Donnerstag, 9. April 2026 um 15:10:25
Job-ID:  898874
JUQ: adeKxd0IHhZhtavG5ALs2gAAAAc
==========
"""

import re
from typing import Optional


# Mapping von E-Mail-Feldern zu internen Schlüsseln
FIELD_MAP = {
    r"job-titel":            "job_title",
    r"job-url":              "job_url",
    r"niederlassung\s*/\s*gruppenid": "group_id",
    r"einsatzort":           "location",
    r"kostenstelle":         "kostenstelle",
    r"sma budget":           "budget",
    r"job-id":               "job_id",
    r"juq":                  "juq",
    r"datum.*aktualisiert":  "updated_at",
}


def parse_email(email_text: str) -> dict:
    """
    Parst einen Hofmann SEA-Beauftragungstext und gibt ein dict mit
    allen extrahierten Feldern zurück.

    Args:
        email_text: Der vollständige E-Mail-Text (oder nur der Job-Block)

    Returns:
        dict mit den extrahierten Feldern

    Raises:
        ValueError: wenn kein gültiger Job-Block gefunden wurde
    """
    if not email_text or not email_text.strip():
        raise ValueError("E-Mail-Text ist leer.")

    # Alle Job-Blöcke zwischen ========== extrahieren
    blocks = extract_job_blocks(email_text)

    if not blocks:
        # Fallback: ganzen Text versuchen zu parsen
        blocks = [email_text]

    # Ersten (oder einzigen) Block parsen
    result = parse_block(blocks[0])

    if not result.get("job_title") and not result.get("job_url"):
        raise ValueError(
            "Kein gültiger Job-Block gefunden. "
            "Bitte den kompletten E-Mail-Text inkl. ========== einfügen."
        )

    # Budget bereinigen: "250,- €" → "250"
    if "budget" in result:
        result["budget"] = clean_budget(result["budget"])

    # Location bereinigen: "15890 Eisenhüttenstadt" → behalten, Stadt extra
    if "location" in result:
        result["city"] = extract_city(result["location"])

    # Fehlende Felder mit Leerstring füllen
    for key in FIELD_MAP.values():
        result.setdefault(key, "")

    return result


def extract_job_blocks(text: str) -> list[str]:
    """Extrahiert alle Job-Blöcke zwischen ========== Trennern."""
    # Pattern: alles zwischen zwei ========== Zeilen
    pattern = r"={5,}(.*?)={5,}"
    matches = re.findall(pattern, text, re.DOTALL)
    return [m.strip() for m in matches if m.strip()]


def parse_block(block: str) -> dict:
    """Parst einen einzelnen Job-Block zeilenweise."""
    result = {}
    lines = block.strip().splitlines()

    for line in lines:
        line = line.strip()
        if not line or line.startswith("="):
            continue

        # Format: "Feld-Name: Wert"
        if ":" not in line:
            continue

        # Ersten Doppelpunkt als Trenner verwenden
        colon_idx = line.index(":")
        raw_key = line[:colon_idx].strip()
        raw_value = line[colon_idx + 1:].strip()

        # URL-Ausnahme: URLs enthalten Doppelpunkte (https://)
        # Falls Wert mit http beginnt → komplette restliche Zeile nehmen
        # Das ist bereits abgedeckt, da wir nur beim ERSTEN Doppelpunkt trennen

        # Feld-Namen matchen
        internal_key = match_field(raw_key)
        if internal_key:
            result[internal_key] = raw_value

    return result


def match_field(raw_key: str) -> Optional[str]:
    """Findet den internen Schlüssel für einen Rohfeld-Namen."""
    normalized = raw_key.lower().strip()
    for pattern, internal_key in FIELD_MAP.items():
        if re.search(pattern, normalized):
            return internal_key
    return None


def clean_budget(budget_str: str) -> str:
    """
    Bereinigt den Budget-String zu einer reinen Zahl.
    "250,- €"  → "250"
    "1.500,- €" → "1500"
    "300"       → "300"
    """
    # Alle Nicht-Ziffern und Komma/Punkt entfernen, außer Dezimalzahlen
    cleaned = re.sub(r"[^\d,.]", "", budget_str)
    # Deutsches Format: Punkt als Tausender, Komma als Dezimal
    cleaned = cleaned.replace(".", "").replace(",", ".")
    # Trailing dot/comma entfernen
    cleaned = cleaned.rstrip(".,")
    # Nur Ganzzahl (kein Dezimalteil bei Budget nötig)
    try:
        return str(int(float(cleaned)))
    except (ValueError, TypeError):
        return budget_str


def extract_city(location_str: str) -> str:
    """
    Extrahiert den Stadtname aus "PLZ Stadt" Format.
    "15890 Eisenhüttenstadt" → "Eisenhüttenstadt"
    "Berlin"                 → "Berlin"
    """
    parts = location_str.strip().split(None, 1)  # maxsplit=1
    if len(parts) == 2 and parts[0].isdigit():
        return parts[1]
    return location_str
