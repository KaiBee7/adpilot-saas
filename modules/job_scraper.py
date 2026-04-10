"""
Job-Scraper für Hofmann Stellenanzeigen
========================================
Scrapt eine Hofmann-Stellenanzeige und extrahiert Jobtitel,
Beschreibung, Qualifikationen und Ort – als Basis für
Keyword-Generierung und Anzeigentexte.
"""

import re
import time
import requests
from bs4 import BeautifulSoup


# HTTP-Timeout in Sekunden
REQUEST_TIMEOUT = 10

# User-Agent (normaler Browser, um Blocking zu vermeiden)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def scrape_job(url: str) -> dict:
    """
    Scrapt eine Hofmann-Stellenanzeige und gibt ein dict mit den
    extrahierten Daten zurück.

    Args:
        url: URL der Stellenanzeige auf hofmann.info

    Returns:
        dict mit: job_title, location, description_text, requirements,
                  job_type, keywords_from_page
    """
    try:
        response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as e:
        raise RuntimeError(f"Stellenanzeige konnte nicht geladen werden: {e}")

    soup = BeautifulSoup(response.text, "html.parser")
    return extract_job_data(soup, url)


def extract_job_data(soup: BeautifulSoup, url: str) -> dict:
    """Extrahiert alle relevanten Daten aus dem geparsten HTML."""
    data = {
        "scraped_url": url,
        "job_title": "",
        "location": "",
        "job_type": "",          # Vollzeit, Teilzeit, etc.
        "description_text": "",
        "requirements": [],
        "benefits": [],
        "keywords_from_page": [],
    }

    # --- Jobtitel ---
    # Hofmann verwendet h1 für den Jobtitel
    title_selectors = [
        "h1.job-title",
        "h1.stellenanzeige-title",
        "h1[class*='title']",
        ".job-detail h1",
        "h1",
    ]
    for selector in title_selectors:
        title_el = soup.select_one(selector)
        if title_el and title_el.get_text(strip=True):
            data["job_title"] = title_el.get_text(strip=True)
            break

    # --- Standort ---
    location_selectors = [
        "[class*='location']",
        "[class*='ort']",
        "[class*='einsatzort']",
        "[itemprop='jobLocation']",
        ".job-location",
    ]
    for selector in location_selectors:
        loc_el = soup.select_one(selector)
        if loc_el:
            data["location"] = loc_el.get_text(strip=True)
            break

    # --- Beschreibung ---
    desc_selectors = [
        ".job-description",
        ".stellenanzeige-content",
        "[class*='description']",
        ".job-detail-content",
        "main",
    ]
    for selector in desc_selectors:
        desc_el = soup.select_one(selector)
        if desc_el:
            # Navigationsmenüs etc. entfernen
            for tag in desc_el.select("nav, header, footer, script, style"):
                tag.decompose()
            text = desc_el.get_text(separator=" ", strip=True)
            if len(text) > 100:
                data["description_text"] = clean_text(text)
                break

    # --- Listen extrahieren (Anforderungen, Benefits) ---
    all_lists = soup.select("ul li, ol li")
    for li in all_lists:
        text = li.get_text(strip=True)
        if 5 < len(text) < 200:
            data["requirements"].append(text)

    # --- Keywords aus URL extrahieren (einfache, aber effektive Methode) ---
    url_keywords = extract_keywords_from_url(url)
    data["keywords_from_page"] = url_keywords

    # --- Jobtitel aus URL als Fallback ---
    if not data["job_title"] and url_keywords:
        data["job_title"] = " ".join(url_keywords[:3]).title()

    return data


def extract_keywords_from_url(url: str) -> list[str]:
    """
    Extrahiert sinnvolle Keywords aus der Stellenanzeigen-URL.
    Beispiel:
      .../Z18Y8HC-recruiter-mwd_15890-eisenhuettenstadt
      → ["recruiter", "mwd", "eisenhuettenstadt"]
    """
    # Letzten URL-Segment nehmen
    path = url.rstrip("/").split("/")[-1]

    # Alfanumerische Teile extrahieren (Kleinbuchstaben)
    parts = re.split(r"[-_]", path)

    # IDs (reine Zahlen oder kurze Hash-Codes) herausfiltern
    keywords = []
    for part in parts:
        # Überspringen: reine Zahl, sehr kurz, oder Hash-Code
        if re.match(r"^\d+$", part):
            continue
        if len(part) <= 2:
            continue
        if re.match(r"^[A-Z0-9]{6,}$", part):  # Looks like hash
            continue
        keywords.append(part.lower())

    return keywords


def clean_text(text: str) -> str:
    """Bereinigt Scraping-Text (mehrfache Leerzeichen, etc.)."""
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\n+", "\n", text)
    return text.strip()
