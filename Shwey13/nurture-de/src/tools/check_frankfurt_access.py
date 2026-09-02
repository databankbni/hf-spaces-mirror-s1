"""frankfurt.de access check — why a robots-permitted source was still excluded.

frankfurt.de's robots.txt ALLOWS our URLs, but the site's WAF returns HTTP 403
to our honest research User-Agent on the actual page. A provenance project does
not spoof a browser UA to get around that, so frankfurt.de was excluded and the
birth-registration gap was covered by Familienportal instead.

This probe reproduces both facts live (robots 200, page 403). It fetches nothing
into the corpus.

Run:  py src/tools/check_frankfurt_access.py
"""

import sys
import urllib.request
import urllib.error

USER_AGENT = (
    "NurtureDE-Research/0.1 "
    "(personal portfolio research project; "
    "contact: shwetaswain13november@gmail.com)"
)

CHECKS = [
    ("robots.txt", "https://www.frankfurt.de/robots.txt"),
    ("page fetch", "https://www.frankfurt.de/"),
]


def status_for(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, ""
    except urllib.error.HTTPError as e:
        return e.code, e.reason or ""
    except Exception as e:  # noqa: BLE001 — report, never crash
        return None, str(e)


def main():
    bar = "=" * 72
    print(bar)
    print("NurtureDE — frankfurt.de access check")
    print("User-Agent: %s" % USER_AGENT)
    print(bar)

    results = {}
    for label, url in CHECKS:
        code, note = status_for(url)
        results[label] = code
        shown = "HTTP %s" % code if code is not None else "ERROR"
        tail = {200: "(allowed)", 403: "(Forbidden)"}.get(code, "(%s)" % note if note else "")
        print("  %-11s %-40s ->  %-9s %s" % (label, url, shown, tail))

    print()
    if results.get("robots.txt") == 200 and results.get("page fetch") == 403:
        print("VERDICT: robots.txt permits us, but the site WAF-blocks our honest research")
        print("UA with 403 on the page itself. We did NOT spoof a browser UA. frankfurt.de")
        print("is EXCLUDED from the corpus; Familienportal covers birth registration cleanly.")
    else:
        print("VERDICT: live status differs from the documented 403 (robots=%s, page=%s)."
              % (results.get("robots.txt"), results.get("page fetch")))
        print("Report what you actually see — do not stage a 403 that isn't happening.")
    print(bar)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
