"""
Anzeigentext- & Keyword-Generator für Hofmann SEA-Kampagnen
============================================================
Generiert auf Basis der Job-Daten:
  - Keywords (Broad Match + Exact Match)
  - Responsive Search Ads (RSA) Headlines & Descriptions
  - Kampagnen-Einstellungen

Google Ads RSA Limits:
  - Headlines: max. 30 Zeichen
  - Descriptions: max. 90 Zeichen
  - Min. 3 Headlines, max. 15
  - Min. 2 Descriptions, max. 4

Microsoft Ads hat dieselben Limits für RSA.
"""

import re


# Standardmäßige Keyword-Erweiterungen für Personalvermittlung
JOB_SUFFIXES = [
    "job",
    "stelle",
    "stellen",
    "stellenangebot",
    "stellenangebote",
    "arbeit",
    "jobs",
    "bewerben",
]

# Hofmann-spezifische Brand-Keywords
BRAND_TERMS = [
    "hofmann personal",
    "hofmann zeitarbeit",
    "zeitarbeit",
    "personalvermittlung",
    "leiharbeit",
]


def generate_keywords(job_data: dict) -> dict:
    """
    Generiert ein strukturiertes Keyword-Set für die Kampagne.

    Returns:
        dict mit:
          - broad_match: Liste von Broad Match Keywords
          - exact_match: Liste von Exact Match Keywords (in [eckigen Klammern])
          - phrase_match: Liste von Phrase Match Keywords (in "Anführungszeichen")
    """
    title = job_data.get("job_title", "")
    city = job_data.get("city") or extract_city(job_data.get("location", ""))
    url_keywords = job_data.get("keywords_from_page", [])

    # Jobtitel bereinigen (m/w/d entfernen für Keywords)
    clean_title = clean_job_title(title)
    title_parts = clean_title.lower().split()

    broad = []
    exact = []
    phrase = []

    # ---- Basis-Keywords: Jobtitel + Job-Suffixe ----
    for suffix in JOB_SUFFIXES[:4]:  # Nicht zu viele
        # Phrase Match
        kw = f"{clean_title} {suffix}".strip()
        if len(kw) <= 80:
            phrase.append(f'"{kw}"')

        # Mit Ort
        if city:
            kw_city = f"{clean_title} {suffix} {city}".strip()
            if len(kw_city) <= 80:
                broad.append(kw_city)

    # ---- Exact Match: wichtigste Varianten ----
    if clean_title:
        exact.append(f"[{clean_title}]")
        if city:
            exact.append(f"[{clean_title} {city}]")
        exact.append(f"[{clean_title} job]")
        exact.append(f"[{clean_title} stelle]")

    # ---- Broad Match: allgemeine Varianten ----
    if city:
        broad.append(f"jobs {city}")
        broad.append(f"arbeit {city}")
        for part in title_parts:
            if len(part) > 3:
                broad.append(f"{part} {city}")

    # ---- URL-basierte Keywords (aus Scraping) ----
    for kw in url_keywords:
        if 3 < len(kw) < 25 and kw not in ["mwd", "mw"]:
            broad.append(kw)

    # Duplikate entfernen, leere raus
    return {
        "broad_match": list(dict.fromkeys(filter(None, broad)))[:15],
        "phrase_match": list(dict.fromkeys(filter(None, phrase)))[:10],
        "exact_match": list(dict.fromkeys(filter(None, exact)))[:10],
    }


def generate_ad_copy(job_data: dict) -> dict:
    """
    Generiert Responsive Search Ad (RSA) Copy für Google Ads & Microsoft Ads.

    Returns:
        dict mit headlines (list) und descriptions (list)
        Alle Limits eingehalten: Headlines ≤30 Zeichen, Descriptions ≤90 Zeichen
    """
    title = job_data.get("job_title", "Ihre neue Stelle")
    city = job_data.get("city") or extract_city(job_data.get("location", ""))
    clean_title = clean_job_title(title)

    headlines = []
    descriptions = []

    # ---- Headlines (max. 30 Zeichen) ----

    # Jobtitel (ggf. kürzen)
    add_headline(headlines, clean_title)
    add_headline(headlines, f"{clean_title} (m/w/d)")
    add_headline(headlines, f"Job: {clean_title}")

    # Mit Ort
    if city:
        add_headline(headlines, f"{clean_title} {city}")
        add_headline(headlines, f"Jobs in {city}")
        add_headline(headlines, city)

    # Generische starke Headlines
    add_headline(headlines, "Jetzt bewerben!")
    add_headline(headlines, "Hofmann Personal")
    add_headline(headlines, "Stellen sofort verfügbar")
    add_headline(headlines, "Schnelle Jobvermittlung")
    add_headline(headlines, "Direkt zum Arbeitgeber")
    add_headline(headlines, "Bewerbung in 2 Minuten")
    add_headline(headlines, "Top Gehalt + Benefits")
    add_headline(headlines, "Jetzt Stelle sichern")
    add_headline(headlines, "Kostenlose Vermittlung")

    # ---- Descriptions (max. 90 Zeichen) ----

    # Beschreibungen mit Jobtitel und Ort
    if city:
        add_description(descriptions,
            f"Wir suchen {clean_title} (m/w/d) in {city}. Jetzt einfach online bewerben!")
        add_description(descriptions,
            f"{clean_title}-Stelle in {city} – attraktives Gehalt & schnelle Vermittlung.")
    else:
        add_description(descriptions,
            f"Wir suchen {clean_title} (m/w/d). Jetzt einfach online bewerben!")
        add_description(descriptions,
            f"Ihre neue {clean_title}-Stelle – attraktives Gehalt & schnelle Vermittlung.")

    add_description(descriptions,
        "Hofmann Personal – Ihr Partner für Zeitarbeit & Personalvermittlung seit 1985.")
    add_description(descriptions,
        "Kostenlose Bewerbung online – wir vermitteln Sie schnell und unkompliziert.")

    return {
        "headlines": headlines[:15],      # Max. 15 für RSA
        "descriptions": descriptions[:4],  # Max. 4 für RSA
    }


# ---- Hilfsfunktionen ----

def add_headline(headlines: list, text: str) -> None:
    """Fügt eine Headline hinzu, wenn sie ≤30 Zeichen und noch nicht vorhanden ist."""
    text = text.strip()
    if text and len(text) <= 30 and text not in headlines:
        headlines.append(text)


def add_description(descriptions: list, text: str) -> None:
    """Fügt eine Description hinzu, wenn sie ≤90 Zeichen und noch nicht vorhanden ist."""
    text = text.strip()
    if text and len(text) <= 90 and text not in descriptions:
        descriptions.append(text)


def clean_job_title(title: str) -> str:
    """
    Bereinigt einen Jobtitel für die Verwendung in Keywords und Anzeigentexten.
    Entfernt Geschlechterangaben wie (m/w/d), (m/f/d), (w/m/d) etc.
    """
    # Klammern mit Geschlechterangaben entfernen
    cleaned = re.sub(r"\s*\([mwdf/]+\)\s*", " ", title, flags=re.IGNORECASE)
    # Mehrfache Leerzeichen normalisieren
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def extract_city(location_str: str) -> str:
    """Extrahiert den Stadtname aus 'PLZ Stadt' Format."""
    parts = location_str.strip().split(None, 1)
    if len(parts) == 2 and parts[0].isdigit():
        return parts[1]
    return location_str
