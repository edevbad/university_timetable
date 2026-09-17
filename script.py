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
                lines = [l.strip() for l in text.split("\n") if l.strip()]
                if lines:
                    course = lines[0]
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
        sb.sleep(10)  # wait for any potential JS redirects to finish
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

        with open("timetable.json", "w", encoding="utf-8") as f:
            json.dump(all_data, f, indent=2, ensure_ascii=False)

        print("\nDone. Saved to timetable.json")

    sb.driver.close()


if __name__ == "__main__":
    main()