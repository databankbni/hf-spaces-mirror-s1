"""Task 1 — robots.txt compliance check.

For every domain in the source list, fetch robots.txt with our project
User-Agent, parse it with urllib.robotparser, and test each specific URL we
intend to fetch. Nothing here downloads a content page; it only reads robots.txt
and evaluates our URL list against it.

Run:  py src/tools/check_robots.py
"""

import sys
import urllib.request
import urllib.error
from urllib.robotparser import RobotFileParser
from urllib.parse import urlsplit

# Identifies this as a personal research project (same UA fetch.py will use).
USER_AGENT = (
    "NurtureDE-Research/0.1 "
    "(personal portfolio research project; "
    "contact: shwetaswain13november@gmail.com)"
)

# The full set of URLs we intend to fetch (sources.yaml candidates only —
# referrals are NOT fetched and are excluded by design).
URLS = [
    # Familienportal des Bundes
    "https://familienportal.de/familienportal/familienleistungen/mutterschutz",
    "https://familienportal.de/familienportal/familienleistungen/mutterschaftsleistungen",
    "https://familienportal.de/familienportal/familienleistungen/elterngeld",
    "https://familienportal.de/familienportal/familienleistungen/elterngeld/faq",
    "https://familienportal.de/familienportal/familienleistungen/elterngeld/faq/wie-kann-ich-elterngeld-beantragen--124762",
    "https://familienportal.de/familienportal/familienleistungen/kindergeld",
    "https://familienportal.de/familienportal/familienleistungen/elternzeit",
    "https://familienportal.de/familienportal/lebenslagen/schwangerschaft-geburt/staatliche-leistungen",
    "https://familienportal.de/familienportal/familienleistungen/familienleistungen-ueberblick",
    # gesund.bund.de (Bundesministerium für Gesundheit)
    "https://gesund.bund.de/wege-im-gesundheitswesen/schwangerschaft-und-geburt/schwangerschaft/schwangerschaftsvorsorge",
    "https://gesund.bund.de/en/schwangerschaftsvorsorge",
    "https://gesund.bund.de/en/geburtsvorbereitung",
    "https://gesund.bund.de/wege-im-gesundheitswesen/schwangerschaft-und-geburt/nach-der-geburt/wochenbett",
    "https://gesund.bund.de/unterstuetzung-fuer-familien-nach-der-geburt",
    "https://gesund.bund.de/wege-im-gesundheitswesen/kindheit/gesund-aufwachsen/fruehe-hilfen",
    # Techniker Krankenkasse
    "https://www.tk.de/en/tk-services-benefits-/service/life-change/maternity-benefits-2079196",
    "https://www.tk.de/en/tk-services-benefits-/service/life-change/pregnancy-maternity-payment-in-germany/maternity-pay-germany-2218042",
    "https://www.tk.de/en/tk-services-benefits-/service/life-change/pregnancy-maternity-payment-in-germany/apply-for-maternity-pay-germany-2218044",
    "https://www.tk.de/en/tk-services-benefits-/service/life-change/find-midwife-2079398",
]

# tk.de disallow list the user checked manually — verify independently.
TK_KNOWN_DISALLOWED = [
    "https://www.tk.de/service/app/2009028/gesundheitskurs/auskunft.app",
    "https://www.tk.de/europaservice-de/",
    "https://www.tk.de/europaservice-en/",
    "https://www.tk.de/vertriebspartner/faq/kuendigung",  # pattern kuendigung*
]


def fetch_robots(domain):
    """Fetch robots.txt for a domain with our UA. Returns (text, error)."""
    url = "https://%s/robots.txt" % domain
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
            return raw.decode("utf-8", errors="replace"), None
    except urllib.error.HTTPError as e:
        return None, "HTTP %s" % e.code
    except Exception as e:  # noqa: BLE001 — report, never crash
        return None, str(e)


def parser_for(text):
    rp = RobotFileParser()
    rp.parse(text.splitlines())
    return rp


def raw_rules(text):
    """Return the User-agent groups and their Allow/Disallow lines, verbatim."""
    groups = []
    cur = None
    for line in text.splitlines():
        s = line.split("#", 1)[0].strip()
        if not s:
            continue
        if ":" not in s:
            continue
        field, value = s.split(":", 1)
        field = field.strip().lower()
        value = value.strip()
        if field == "user-agent":
            if cur is None or cur["directives"]:
                cur = {"agents": [value], "directives": []}
                groups.append(cur)
            else:
                cur["agents"].append(value)
        elif field in ("allow", "disallow"):
            if cur is None:
                cur = {"agents": ["*"], "directives": []}
                groups.append(cur)
            cur["directives"].append((field, value))
    return groups


def main():
    domains = []
    for u in URLS:
        d = urlsplit(u).netloc
        if d not in domains:
            domains.append(d)

    print("=" * 72)
    print("NurtureDE — robots.txt compliance (Task 1)")
    print("User-Agent tested: %s" % USER_AGENT)
    print("=" * 72)

    parsers = {}
    any_blocked = False

    for domain in domains:
        print("\n" + "-" * 72)
        print("DOMAIN: %s" % domain)
        print("-" * 72)
        text, err = fetch_robots(domain)
        if err:
            print("  robots.txt fetch FAILED: %s" % err)
            print("  -> Treating as: no robots.txt / fetch allowed by default.")
            parsers[domain] = None
            continue
        rp = parser_for(text)
        parsers[domain] = rp

        groups = raw_rules(text)
        if not groups:
            print("  (robots.txt present but contains no Allow/Disallow rules)")
        for g in groups:
            print("  User-agent: %s" % ", ".join(g["agents"]))
            if not g["directives"]:
                print("      (no directives)")
            for field, value in g["directives"]:
                label = "DISALLOW" if field == "disallow" else "allow   "
                print("      %s %s" % (label, value if value else "(empty = allow all)"))

    # Per-URL verdicts
    print("\n" + "=" * 72)
    print("PER-URL VERDICTS (our intended fetch list)")
    print("=" * 72)
    for u in URLS:
        domain = urlsplit(u).netloc
        rp = parsers.get(domain)
        allowed = True if rp is None else rp.can_fetch(USER_AGENT, u)
        mark = "ALLOWED" if allowed else "BLOCKED  <-- SKIP"
        if not allowed:
            any_blocked = True
        print("  [%s] %s" % (mark, u))

    # Independent verification of the tk.de disallow list
    print("\n" + "=" * 72)
    print("tk.de DISALLOW LIST — independent verification")
    print("=" * 72)
    rp = parsers.get("www.tk.de")
    if rp is None:
        print("  Could not verify: www.tk.de robots.txt not available.")
    else:
        print("  Confirming the paths you flagged are actually disallowed:")
        for u in TK_KNOWN_DISALLOWED:
            blocked = not rp.can_fetch(USER_AGENT, u)
            print("    [%s] %s" % ("disallowed OK" if blocked else "NOT disallowed?!", u))
        print("\n  Confirming NONE of our tk.de fetch URLs are disallowed:")
        for u in URLS:
            if urlsplit(u).netloc == "www.tk.de":
                ok = rp.can_fetch(USER_AGENT, u)
                print("    [%s] %s" % ("clear" if ok else "BLOCKED", u))

    print("\n" + "=" * 72)
    if any_blocked:
        print("RESULT: One or more URLs are BLOCKED. They will be skipped.")
    else:
        print("RESULT: All intended fetch URLs are ALLOWED by robots.txt.")
    print("=" * 72)
    return 1 if any_blocked else 0


if __name__ == "__main__":
    sys.exit(main())
