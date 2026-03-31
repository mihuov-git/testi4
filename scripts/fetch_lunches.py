from __future__ import annotations

import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; LunchBot/1.0; +https://github.com/)"}
DAY_NAMES = {0: "maanantai", 1: "tiistai", 2: "keskiviikko", 3: "torstai", 4: "perjantai", 5: "lauantai", 6: "sunnuntai"}
DAY_EN = {"maanantai":"Monday","tiistai":"Tuesday","keskiviikko":"Wednesday","torstai":"Thursday","perjantai":"Friday","lauantai":"Saturday","sunnuntai":"Sunday"}
WEEKDAY_CAP = {"maanantai":"Maanantai","tiistai":"Tiistai","keskiviikko":"Keskiviikko","torstai":"Torstai","perjantai":"Perjantai","lauantai":"Lauantai","sunnuntai":"Sunnuntai"}

SOURCES = [
    {"key":"grillit","name":"Grill it! Marina","subtitle":"Raflaamo","url":"https://www.raflaamo.fi/fi/ravintola/turku/grill-it-marina-turku/menu/lounas"},
    {"key":"viides","name":"Viides Näyttämö","subtitle":"Kulttuuriranta","url":"https://www.viidesnayttamo.fi/?page_id=73"},
    {"key":"aitiopaikka","name":"Aitiopaikka","subtitle":"Fresco Ravintolat","url":"https://www.frescoravintolat.fi/lounas/aitiopaikan-lounaslista/"},
]

def helsinki_now() -> datetime:
    return datetime.now(ZoneInfo("Europe/Helsinki"))

def today_name() -> str:
    return DAY_NAMES[helsinki_now().weekday()]

def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()

def fetch_html(url: str) -> str:
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.text

def lines_from_html(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    lines = [normalize(x) for x in soup.get_text("\n").splitlines()]
    return [x for x in lines if x]

def dedupe_keep_order(items: list[str]) -> list[str]:
    out, seen = [], set()
    for item in items:
        item = normalize(item)
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out

def parse_grillit_playwright(day_name: str) -> tuple[list[str], str]:
    day = DAY_EN[day_name]
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("https://www.raflaamo.fi/en/restaurant/turku/grill-it-marina-turku/menu/lunch", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)
        text = page.locator("body").inner_text()
        browser.close()

    lines = [normalize(x) for x in text.splitlines() if normalize(x)]
    start = None
    for i, line in enumerate(lines):
        if line.startswith(f"{day} ") and (re.search(r"\d{1,2}/\d{1,2}", line) or re.search(r"\d{1,2}\.\d{1,2}", line)):
            start = i
            break
    if start is None:
        for i, line in enumerate(lines):
            if line.startswith(f"{day} "):
                start = i
                break
    if start is None:
        return [], "14,80 €"

    weekdays = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
    items = []
    for line in lines[start + 1:]:
        if any(line.startswith(w + " ") for w in weekdays if w != day):
            break
        if line in {"Lunch","Lunch menu","L","G","M","VE","VL","VN","VEP","GP"}:
            continue
        if line.startswith("Price:") or line.startswith("Owner customer price:"):
            continue
        if re.fullmatch(r"\d{1,2},\d{2}\s*€", line):
            continue
        if line.startswith("Welcome to lunch!") or line.startswith("Lunch includes") or line.startswith("At lunch time") or line.startswith("From the buffet") or line.startswith("Please ask our staff"):
            continue
        if "***" in line:
            parts = [normalize(x) for x in line.split("***") if normalize(x)]
            items.append("Lounasmenu: " + " + ".join(parts))
            continue
        items.append(line)

    cleaned = []
    for item in dedupe_keep_order(items):
        if item == day or re.fullmatch(r"\d{1,2}[./]\d{1,2}[./]?", item):
            continue
        cleaned.append(item)
    return cleaned[:6], "14,80 €"

def parse_viides(html: str, day_name: str) -> tuple[list[str], str]:
    text = "\n".join(lines_from_html(html))
    heading = WEEKDAY_CAP[day_name]
    m = re.search(r"Buffetlounas\s*(\d{1,2},\d{2})\s*€", text)
    price = f"{m.group(1)} €" if m else "-"
    pat = rf"{heading} \d{{1,2}}\.\d{{1,2}}\.(.*?)(?=(Maanantai|Tiistai|Keskiviikko|Torstai|Perjantai) \d{{1,2}}\.\d{{1,2}}\.|L=laktoositon|Kysy henkilökunnalta|$)"
    m2 = re.search(pat, text, re.S)
    if not m2:
        return [], price
    block = [normalize(x) for x in m2.group(1).split("\n") if normalize(x)]
    items = [x for x in block if not x.startswith("Kysy henkilökunnalta") and not x.startswith("Kaikki käyttämämme")]
    return dedupe_keep_order(items)[:4], price

def parse_aitiopaikka(html: str, day_name: str) -> tuple[list[str], str]:
    text = "\n".join(lines_from_html(html))
    heading = WEEKDAY_CAP[day_name]
    m = re.search(r"Lämminruokalounas\s*(\d{1,2},\d{2})\s*€", text)
    price = f"{m.group(1)} €" if m else "-"
    pat = rf"{heading}(.*?)(?=(Maanantai|Tiistai|Keskiviikko|Torstai|Perjantai)|L = laktoositon|Lihojen ja broilerin|Tutustu ravintola Aitiopaikkaan|$)"
    m2 = re.search(pat, text, re.S)
    if not m2:
        return [], price
    block = [normalize(x) for x in m2.group(1).split("\n") if normalize(x)]
    items = [x for x in block if x not in {"Ravintola suljettu!", "PITKÄPERJANTAI"}]
    items = [x for x in items if not re.fullmatch(r"\d{1,2}\.\d{1,2}\.?", x)]
    return dedupe_keep_order(items)[:4], price

def main() -> None:
    day = today_name()
    debug = []
    restaurants = []
    for source in SOURCES:
        try:
            if source["key"] == "grillit":
                items, price = parse_grillit_playwright(day)
            else:
                html = fetch_html(source["url"])
                if source["key"] == "viides":
                    items, price = parse_viides(html, day)
                else:
                    items, price = parse_aitiopaikka(html, day)
            status = "ok" if items else "error"
            restaurants.append({
                "key": source["key"],
                "name": source["name"],
                "subtitle": source["subtitle"],
                "url": source["url"],
                "price": price or "-",
                "items": items,
                "status": status,
            })
            debug.append(f'{source["name"]}: {status}, {len(items)} riviä, hinta {price}')
        except Exception as exc:
            restaurants.append({
                "key": source["key"],
                "name": source["name"],
                "subtitle": source["subtitle"],
                "url": source["url"],
                "price": "14,80 €" if source["key"] == "grillit" else "-",
                "items": [],
                "status": "error",
            })
            debug.append(f'{source["name"]}: virhe {type(exc).__name__}: {exc}')
    now = helsinki_now()
    payload = {
        "updated_at": now.isoformat(),
        "updated_at_fi": now.strftime("%d.%m.%Y %H:%M"),
        "today_name": day,
        "debug": debug,
        "restaurants": restaurants,
    }
    with open("data/lunches.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
