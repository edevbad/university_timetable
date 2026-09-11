"""
COMSATS Attock Timetable Scraper
=================================
Scrapes https://cuonline.cuiatd.edu.pk/Timetable/COMSATSTimeTablePrintVersion.aspx
for every class/section listed in the ddlClasses dropdown, and writes one
timetable.json file containing the whole university's schedule.

Setup:
    pip install requests beautifulsoup4

Run:
    python scrape_timetable.py

Output:
    timetable.json — { "<section>": { "<Day>": [ {slot info...}, ... ] } }
"""

import json
import time
import requests
from bs4 import BeautifulSoup

URL = "https://cuonline.cuiatd.edu.pk/Timetable/COMSATSTimeTablePrintVersion.aspx"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Referer": URL,
}

# The fixed time-slot columns used by the timetable grid, in order.
TIME_SLOTS = [
    "09:00-10:30", "10:30-12:00", "12:00-13:30", "13:30-15:00",
    "15:00-16:30", "16:30-18:00", "18:00-19:30", "19:30-21:00",
]

# Politeness delay between requests (seconds). Raise this if the site
# starts throttling/blocking you.
DELAY_SECONDS = 1.0


def get_hidden_fields(soup):
    """Pull the ASP.NET postback tokens out of the page so we can replay them."""
    return {
        "__VIEWSTATE": soup.find("input", id="__VIEWSTATE")["value"],
        "__VIEWSTATEGENERATOR": soup.find("input", id="__VIEWSTATEGENERATOR")["value"],
        "__EVENTVALIDATION": soup.find("input", id="__EVENTVALIDATION")["value"],
    }


def parse_timetable(soup):
    """Parse the gvTimeTable1 grid into {day: [ {start_slot, end_slot, course, room, instructor} ]}."""
    table = soup.find("table", id="gvTimeTable1")
    if not table:
        return {}

    schedule = {}
    rows = table.find_all("tr")[1:]  # skip header row (DayTitle + slot headers)

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
                lines = [l.strip() for l in text.split("\n") if l.strip()]
                if lines:
                    course = lines[0]
                    # Room info is always the 2nd line; instructor is always the
                    # last line (there's sometimes a "01 Hr Class" marker line
                    # in between, which we just skip).
                    room = lines[1] if len(lines) > 1 else ""
                    instructor = lines[-1] if len(lines) > 1 else ""
                    end_idx = min(slot_idx + span - 1, len(TIME_SLOTS) - 1)
                    entries.append({
                        "start_slot": TIME_SLOTS[slot_idx],
                        "end_slot": TIME_SLOTS[end_idx],
                        "course": course,
                        "room": room,
                        "instructor": instructor,
                    })

            slot_idx += span

        schedule[day] = entries

    return schedule


def main():
    session = requests.Session()

    print("Fetching initial page + section list...")
    resp = session.get(URL, headers=HEADERS, timeout=20)
    soup = BeautifulSoup(resp.text, "html.parser")

    dropdown = soup.find("select", id="ddlClasses")
    sections = [opt["value"] for opt in dropdown.find_all("option")]
    print(f"Found {len(sections)} sections.")

    hidden = get_hidden_fields(soup)
    all_data = {}

    for i, section in enumerate(sections, start=1):
        payload = {
            "__EVENTTARGET": "ddlClasses",
            "__EVENTARGUMENT": "",
            **hidden,
            "ddlClasses": section,
        }
        resp = session.post(URL, data=payload, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(resp.text, "html.parser")
        hidden = get_hidden_fields(soup)  # tokens refresh with every response

        all_data[section] = parse_timetable(soup)
        print(f"[{i}/{len(sections)}] scraped {section}")

        time.sleep(DELAY_SECONDS)

    with open("timetable.json", "w", encoding="utf-8") as f:
        json.dump(all_data, f, indent=2, ensure_ascii=False)

    print("\nDone. Saved to timetable.json")


if __name__ == "__main__":
    main()