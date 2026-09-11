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

resp = requests.get(URL, headers=HEADERS, timeout=20)

print("Status code:", resp.status_code)
print("Final URL (after any redirects):", resp.url)
print("Response length:", len(resp.text))
print("\n--- First 1000 characters of response ---\n")
print(resp.text[:1000])

soup = BeautifulSoup(resp.text, "html.parser")
dropdown = soup.find("select", id="ddlClasses")
print("\nDropdown found:", dropdown is not None)