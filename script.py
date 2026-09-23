"""
COMSATS Attock Timetable Scraper — stealthy browser version
=============================================================
Same output format as the original requests/BeautifulSoup scraper, but
drives a real (undetected) Chrome via seleniumbase's CDP mode + Playwright,
so it can get past Cloudflare and run the ASP.NET dropdown postbacks like
a real browser instead of manually replaying __VIEWSTATE tokens.

Setup:
    pip install seleniumbase playwright beautifulsoup4
    playwright install chromium   # only needed if NOT passing an executable path

Run:
    python scrape_timetable_stealthy.py

Output:
    timetable.json — { "<section>": { "<Day>": [ {slot info...}, ... ] } }
"""

import json
import re
import sys
import time
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from seleniumbase import sb_cdp

URL = "https://cuonline.cuiatd.edu.pk/Timetable/COMSATSTimeTablePrintVersion.aspx"

TIME_SLOTS = [
    "09:00-10:30", "10:30-12:00", "12:00-13:30", "13:30-15:00",
    "15:00-16:30", "16:30-18:00", "18:00-19:30", "19:30-21:00",
]

# Politeness delay between sections (seconds).
DELAY_SECONDS = 3.0

# Room code like "A114", "A-114", "S-108".
ROOM_CODE_RE = re.compile(r"\b([A-Z])-?(\d{3})\b")
# Capacity annotations the site appends to rooms: "(60M)", "(M)", "(58)", "[50M]".
CAPACITY_RE = re.compile(r"\s*[(\[]\s*\d*\s*M?\s*[)\]]")
ORDINAL_SUFFIX_RE = re.compile(r"^(st|nd|rd|th)\b")


def merge_split_lines(lines):
    """Rejoin ordinals the site renders with <sup>, e.g. "18" + "th Century" -> "18th Century"."""
    merged = []
    for line in lines:
        if merged and merged[-1][-1:].isdigit() and ORDINAL_SUFFIX_RE.match(line):
            merged[-1] += line
        else:
            merged.append(line)
    return [re.sub(r"(\d) (st|nd|rd|th)\b", r"\1\2", l) for l in merged]


def normalize_room(room):
    """Normalize a room to "<CODE>" (e.g. "A-114") or "<Lab name> (<CODE>)"."""
    room = CAPACITY_RE.sub("", room)
    room = re.sub(r"\s*\(L\)", " Lab", room)  # "(L)" marks a lab: "High Voltage (L)"
    room = room.replace("Dhamtor", "Dhamtour")
    room = re.sub(r"\bLAB\b", "Lab", room)
    room = ROOM_CODE_RE.sub(r"\1-\2", room)
    room = re.sub(r"\s+", " ", room).strip()

    code_match = ROOM_CODE_RE.search(room)
    if not code_match:
        return room
    code = code_match.group(0)
    if room == code:
        return code

    # Everything except the code (and parens around it) is the lab name,
    # so "Lab C-207 (Dhamtour)" and "Lab (C-312) CISCO" both end in "(CODE)".
    name = room.replace(code, " ")
    name = re.sub(r"[()]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    # "Microbiology Lab 124 (A-124)" repeats the room number in the name.
    name = re.sub(rf"\s*\b{code_match.group(2)}$", "", name)
    return f"{name} ({code})" if name else code


def unify_room_names(all_data):
    """Rename bare codes (e.g. "A-106") to the lab name used elsewhere for that code."""
    named = {}
    for days in all_data.values():
        for entries in days.values():
            for e in entries:
                m = re.search(r"\(([A-Z]-\d{3})\)$", e["room"])
                if m:
                    named.setdefault(m.group(1), e["room"])
    for days in all_data.values():
        for entries in days.values():
            for e in entries:
                e["room"] = named.get(e["room"], e["room"])
    return all_data


def parse_timetable(soup):
    """Parse the gvTimeTable1 grid into {day: [ {start_slot, end_slot, course, room, instructor} ]}."""
    table = soup.find("table", id="gvTimeTable1")
    if not table:
        return {}

    schedule = {}
    rows = table.find_all("tr")[1:]  # skip header row

    for row in rows:
        cells = row.find_all("td")
        if not cells:
            continue

        day = cells[0].get_text(strip=True)
        entries = []
        slot_idx = 0

        for cell in cells[1:]:
            span = int(cell.get("colspan", 1))
            text = cell.get_text(separator="\n", strip=True)

            if text:
                lines = merge_split_lines(
                    [l.strip() for l in text.split("\n") if l.strip()]
                )
                if lines:
                    course = lines[0]
                    # Room name and room code sometimes render as separate
                    # lines within the cell (e.g. "Computer LAB 2" then
                    # "(S-314)" on their own lines) rather than one combined
                    # line - join everything between course and instructor
                    # so the room code isn't silently dropped.
                    if len(lines) >= 3:
                        room = " ".join(lines[1:-1])
                        instructor = lines[-1]
                    elif len(lines) == 2:
                        room = lines[1]
                        instructor = ""
                    else:
                        room = ""
                        instructor = ""
                    end_idx = min(slot_idx + span - 1, len(TIME_SLOTS) - 1)
                    entries.append({
                        "start_slot": TIME_SLOTS[slot_idx],
                        "end_slot": TIME_SLOTS[end_idx],
                        "course": course,
                        "room": normalize_room(room),
                        "instructor": instructor,
                    })

            slot_idx += span

        schedule[day] = entries

    return schedule


def main():
    print("Launching stealthy Chrome...")
    # headless=False for the first run so you can manually click through
    # Cloudflare Turnstile if it appears. Switch to True once you've
    # confirmed it passes unattended (or keep False if it always shows up).
    sb = sb_cdp.Chrome()
    endpoint_url = sb.get_endpoint_url()

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(endpoint_url)
        page = browser.contexts[0].pages[0]

        print("Loading initial page...")
        page.goto(URL, wait_until="networkidle")

        # If Cloudflare Turnstile shows up, pause here for a manual click.
        # Comment this out once you confirm undetected mode passes it alone.
        # input("If a Cloudflare checkbox appeared, solve it now, then press Enter to continue...")
        sb.sleep(20)  # wait for any potential JS redirects to finish
        page.wait_for_load_state("networkidle")

        soup = BeautifulSoup(page.content(), "html.parser")
        dropdown = soup.find("select", id="ddlClasses")
        sections = [opt["value"] for opt in dropdown.find_all("option") if opt["value"]]
        print(f"Found {len(sections)} sections.")

        all_data = {}

        for i, section in enumerate(sections, start=1):
            # select_option triggers the client-side onchange -> __doPostBack
            with page.expect_navigation(wait_until="networkidle"):
                page.select_option("#ddlClasses", section)

            soup = BeautifulSoup(page.content(), "html.parser")
            all_data[section] = parse_timetable(soup)
            print(f"[{i}/{len(sections)}] scraped {section}")

            time.sleep(DELAY_SECONDS)

        save(unify_room_names(all_data))

    sb.driver.close()


def save(all_data):
    with open("timetable.json", "w", encoding="utf-8") as f:
        json.dump(all_data, f, indent=2, ensure_ascii=False)
    print("\nDone. Saved to timetable.json")


def renormalize_existing():
    """Re-apply room normalization to an existing timetable.json without scraping."""
    with open("timetable.json", encoding="utf-8") as f:
        all_data = json.load(f)
    for days in all_data.values():
        for entries in days.values():
            for e in entries:
                e["room"] = normalize_room(e["room"])
    save(unify_room_names(all_data))


if __name__ == "__main__":
    if "--normalize" in sys.argv:
        renormalize_existing()
    else:
        main()