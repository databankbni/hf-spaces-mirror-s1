#!/usr/bin/env python3
"""Derive every figure used on index.html from the WhatsApp export.

Usage:  python3 analysis/extract.py [path/to/_chat.txt]

Reads the export from data/_chat.txt by default (unzipping the archive in data/
if the text file is not there yet) and prints the numbers that appear on the
page, so any claim can be re-checked against the source.  Nothing in data/ is
tracked by git: the export carries members' names and phone numbers.
"""
import collections
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# ---------------------------------------------------------------- the export

LINE = re.compile(
    r"^‎?\[(\d+)/(\d+)/(\d+), (\d+):(\d+):(\d+)\s?([AP]M)\] ([^:]+): ‎?(.*)$"
)


def load(path=None):
    """Return the export's lines, unzipping the archive if needed."""
    if path:
        return Path(path).read_text(encoding="utf-8").split("\n")
    txt = DATA / "_chat.txt"
    if not txt.exists():
        zips = sorted(DATA.glob("*.zip"))
        if not zips:
            sys.exit(f"no export found: put _chat.txt or the WhatsApp zip in {DATA}")
        with zipfile.ZipFile(zips[0]) as z:
            z.extract("_chat.txt", DATA)
    return txt.read_text(encoding="utf-8").split("\n")


def norm(name):
    for ch in ("‪", "‬", " ", "\xa0"):
        name = name.replace(ch, " ")
    return re.sub(r"\s+", " ", name.strip().lstrip("~").strip())


def parse(lines):
    """One dict per message; continuation lines fold into the message above."""
    msgs, cur = [], None
    for ln in lines:
        m = LINE.match(ln)
        if m:
            if cur:
                msgs.append(cur)
            mo, d, y, h, mi, _s, ap, sender, body = m.groups()
            cur = dict(
                date=f"20{y}-{int(mo):02d}-{int(d):02d}",
                month=f"20{y}-{int(mo):02d}",
                hour=int(h) % 12 + (12 if ap == "PM" else 0),
                sender=norm(sender),
                body=body.replace("‎", ""),
            )
        elif cur is not None:
            cur["body"] += "\n" + ln
    if cur:
        msgs.append(cur)
    return msgs


# ------------------------------------------------------- membership timeline

ADD = re.compile(r"^(.+?) added (.+)$")
REMOVED = re.compile(r"^(.+?) removed (.+)$")
JOINED = re.compile(r"^(.+?) joined using (?:your invite|.{0,30}link)$")
LEFT = re.compile(r"^(.{1,60}) left$")
NOT_AN_EVENT = ("looks like", "someone", "i ", "they ")


def split_names(s):
    return [n for n in (norm(x) for x in re.sub(r",? and ", ", ", s).split(", ")) if n]


def membership(msgs):
    """Daily roster size, reconstructed from add/join/leave/remove events.

    Anyone who speaks without ever having been added is treated as present from
    the start -- the export does not log the members the group opened with.
    """
    present, ever, founders, events = set(), set(), set(), 0
    daily = {}
    for m in msgs:
        # an event is always the first line of the message; anything folded in
        # underneath it is someone's chat, not part of the event
        body, hit = m["body"].split("\n")[0].strip(), False
        if len(body) < 200:
            if ADD.match(body) and not body.lower().startswith(NOT_AN_EVENT):
                for n in split_names(ADD.match(body).group(2)):
                    present.add(n)
                    ever.add(n)
                    events += 1
                hit = True
            elif REMOVED.match(body):
                for n in split_names(REMOVED.match(body).group(2)):
                    present.discard(n)
                    events += 1
                hit = True
            elif JOINED.match(body):
                n = norm(JOINED.match(body).group(1))
                present.add(n)
                ever.add(n)
                events += 1
                hit = True
            elif LEFT.match(body):
                present.discard(norm(LEFT.match(body).group(1)))
                events += 1
                hit = True
        if not hit and m["sender"] not in ever and m["sender"] != "Abu Dhabi Pickleball Club":
            founders.add(m["sender"])
            present.add(m["sender"])
            ever.add(m["sender"])
        daily[m["date"]] = len(present)
    return daily, dict(events=events, ever=len(ever), founders=len(founders))


# ------------------------------------------------------------------- polls
# A session is a scheduling poll posted in the group.  Nothing else counts:
# games arranged by phone or in side chats leave no trace in the export.


def polls(lines):
    out, cur, collecting = [], None, False
    for ln in lines:
        m = LINE.match(ln)
        if m:
            body = m.group(9).replace("‎", "")
            if body.strip().startswith("POLL:"):
                mo, d, y = m.group(1), m.group(2), m.group(3)
                cur = dict(
                    date=f"20{y}-{int(mo):02d}-{int(d):02d}",
                    month=f"20{y}-{int(mo):02d}",
                    q=body.strip()[5:].strip(),
                    opts=[],
                )
                out.append(cur)
                collecting = True
            else:
                cur, collecting = None, False
        elif cur is not None and collecting:
            t = ln.replace("‎", "").strip()
            if t.startswith("OPTION:"):
                cur["opts"].append(t[7:].strip())
            elif t:
                cur["q"] += " " + t
    return out


VOTES = re.compile(r"\((\d+) votes?\)")
CAP = re.compile(r"\b(?:max|maximum|limit(?:ed)?(?: to)?|up to|only)\s*[:\-]?\s*(\d{1,2})\b", re.I)


def signups(ps):
    total = sum(int(v) for p in ps for o in p["opts"] for v in VOTES.findall(o))
    busiest = max(sum(int(v) for o in p["opts"] for v in VOTES.findall(o)) for p in ps)
    return total, busiest


VENUES = collections.OrderedDict([
    ("Sadim Park", re.compile(r"sadim", re.I)),
    ("Al Masar Park", re.compile(r"al\s*masar|masar\s*park|\bmasar\b", re.I)),
    ("Raheeq Park", re.compile(r"raheeq", re.I)),
    ("Al Zuwar", re.compile(r"zuwar", re.I)),
    ("Masdar Park", re.compile(r"masdar", re.I)),
])


def venues(ps):
    """Sessions whose poll text names each known venue.

    Matched against a short list of the parks this group has actually used --
    a session can name more than one when play was relocated mid-week, so
    these do not sum to len(ps).
    """
    counts = collections.Counter()
    for p in ps:
        t = p["q"] + " " + " ".join(p["opts"])
        for name, rx in VENUES.items():
            if rx.search(t):
                counts[name] += 1
    return counts


def capacity(ps):
    """Slots whose organiser stated a player cap, and how they filled."""
    slots = filled = over = 0
    for p in ps:
        for o in p["opts"]:
            cap = CAP.search(o)
            if not cap:
                continue
            c = int(cap.group(1))
            if not 4 <= c <= 40:
                continue
            v = VOTES.search(o)
            v = int(v.group(1)) if v else 0
            slots += 1
            filled += v >= c
            over += v > c
    return slots, filled, over


# -------------------------------------------------------- session start times
# Read from the poll text only, one count per session.  Counting every
# time-like string in every message instead sweeps in scores, dates and player
# caps, which is what once made the chart show play proposed at 3 and 4am.

MER = r"(a\.?\s?m\.?|p\.?\s?m\.?)"
RANGE_MER = re.compile(
    r"\b(\d{1,2})(?:[:.](\d{2}))?\s*" + MER + r"?\s*(?:-|–|—|to|till|until|~)\s*"
    r"(\d{1,2})(?:[:.](\d{2}))?\s*" + MER,
    re.I,
)
SINGLE_MER = re.compile(r"\b(\d{1,2})(?:[:.](\d{2}))?\s*\.?\s*" + MER, re.I)
BARE_RANGE = re.compile(
    r"\b(\d{1,2})(?:[:.](\d{2}))?\s*(?:-|–|—|to|till|until)\s*(\d{1,2})(?:[:.](\d{2}))?\b"
)
MORNING = re.compile(r"\b(morning|sunrise|breakfast|early)\b", re.I)
EVENING = re.compile(r"\b(night|evening|under the lights|after work|sunset|tonight|lights)\b", re.I)


def strip_non_times(t):
    """Remove the numbers that look like clock times but are not."""
    t = re.sub(r"[0-9]️?⃣", " ", t)                     # keycap emoji 1..9
    t = re.split(r"\[\d{1,2}/\d{1,2}/\d{2},", t)[0]               # a leaked next message
    t = re.sub(r"\b(?:max|maximum|min|minimum|limit(?:ed)?(?: to)?|up to|only)"
               r"\s*[:\-]?\s*\d{1,2}\b", " CAP ", t, flags=re.I)  # MAX 12 MEMBERS
    t = re.sub(r"\b\d{1,2}\s*(?:members|players|people|spots|slots|pax|votes?)\b",
               " CAP ", t, flags=re.I)
    t = re.sub(r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b", " DATE ", t)  # 18.12.25
    t = re.sub(r"\b\d{1,2}[/]\d{1,2}\b", " DATE ", t)                # 28/3
    months = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"
    t = re.sub(r"\b\d{1,2}\s*[-–]\s*" + months + r"\w*", " DATE ", t, flags=re.I)
    t = re.sub(months + r"\w*\.?\s*\d{1,2}\b", " DATE ", t, flags=re.I)
    return t


def to_24h(h, meridiem):
    if meridiem == "pm" and h < 12:
        h += 12
    if meridiem == "am" and h == 12:
        h = 0
    return h


def meridiem(s):
    if not s:
        return None
    return "am" if s.lower().replace(".", "").replace(" ", "")[0] == "a" else "pm"


def _end_hour(h2, mer):
    """h2 as a 24h end hour. An unqualified 12 at the end of a range means
    midnight, not noon -- "9 to 12" at night runs to 12am, not through the
    next day -- so 12 follows the range's own meridiem instead of to_24h's
    literal one-off-noon rule."""
    if h2 == 12:
        return 24 if mer == "pm" else 0
    return to_24h(h2, mer)


def _read_span(num_txt, word_txt):
    """Find a (start hour, end hour, tag) span in num_txt; morning/night words
    come from word_txt. end is exclusive of the hour itself and can run past
    24 for a span that crosses midnight. When no end is stated, the span is
    assumed to run 2 hours -- the length of all but a handful of the sessions
    that do state both ends."""
    h = end = tag = None

    m = RANGE_MER.search(num_txt)                       # "6:30-9:30pm", "7-9.30 PM"
    if m:
        h1, m1 = int(m.group(1)), meridiem(m.group(3))
        h2, m2 = int(m.group(4)), meridiem(m.group(6))
        if h1 <= 12 and h2 <= 12:
            h = to_24h(h1, m1) if m1 else to_24h(h1, m2)
            if not m1 and h > to_24h(h2, m2):       # meridiem sat on the end time
                h = to_24h(h1, "am" if m2 == "pm" else "pm")
            tag = "clock time"
            end = _end_hour(h2, m2)
            if end <= h:
                end += 24
    if h is None:
        m = SINGLE_MER.search(num_txt)              # "from 6.30 am", "7pm"
        if m and int(m.group(1)) <= 12:
            h, tag = to_24h(int(m.group(1)), meridiem(m.group(3))), "clock time"
            end = h + 2
    if h is None:
        m = BARE_RANGE.search(num_txt)              # "7 to 9.30" + morning/night
        if m:
            h1, h2 = int(m.group(1)), int(m.group(3))
            if h1 <= 12 and h2 <= 12 and h1 != h2:
                morning, evening = MORNING.search(word_txt), EVENING.search(word_txt)
                if morning and not evening:
                    h, tag = to_24h(h1, "am"), "range + word"
                    end = _end_hour(h2, "am")
                elif evening and not morning:
                    h, tag = to_24h(h1, "pm"), "range + word"
                    end = _end_hour(h2, "pm")
                if h is not None and end <= h:
                    end += 24
    if h is None:
        morning, evening = MORNING.search(word_txt), EVENING.search(word_txt)
        tag = ("window word only" if (bool(morning) != bool(evening))
               else "no time stated")
    return h, end, tag


def _read_hour(num_txt, word_txt):
    """Find one start hour in num_txt; morning/night words come from word_txt."""
    h, _end, tag = _read_span(num_txt, word_txt)
    return h, tag


def session_slots(ps):
    """Every stated start time in the record, one entry per session slot.

    Most polls state a single time for the whole poll ("Wednesday 7-9:30pm"),
    which is one slot. From 30 April 2026, most evening polls switched to
    offering several time slots in one poll instead -- 5:30, 7:30 and 9:30pm
    are the usual three -- each its own option with its own sign-ups. Reading
    one hour per poll, as the group's own scheduling data is structured before
    that date, collapsed every slot in one of these polls into a single count
    at whichever option came first and discarded the sign-ups on the rest.
    This reads a time from each option on its own, and only falls back to
    reading the poll as a single slot when none of its options states one.
    """
    hours, interest, how = [0] * 24, [0] * 24, collections.Counter()
    multi_slot_polls = 0
    for p in ps:
        qtxt = strip_non_times(p["q"])
        opt_slots = []
        for o in p["opts"]:
            otxt = strip_non_times(o)
            h, tag = _read_hour(otxt, otxt + " " + qtxt)
            if h is not None:
                opt_slots.append((h, sum(int(v) for v in VOTES.findall(o)), tag))
        if opt_slots:
            if len(opt_slots) > 1:
                multi_slot_polls += 1
            for h, v, tag in opt_slots:
                hours[h] += 1
                interest[h] += v
                how[tag] += 1
        else:
            combined = qtxt + " || " + " | ".join(strip_non_times(o) for o in p["opts"])
            h, tag = _read_hour(combined, combined)
            how[tag] += 1
            if h is not None:
                hours[h] += 1
                interest[h] += sum(int(v) for o in p["opts"] for v in VOTES.findall(o))
    return hours, interest, how, multi_slot_polls


def hourly_activity(ps):
    """Sessions actually under way during each hour of the day, not just the
    hour they started -- a 7:30-9:30pm slot counts toward both 7pm and 8pm.
    This is what turns a start-time count with a hole at 6pm and 8pm (nothing
    starts on the hour between the 5:30/7:30/9:30 slots) into a smooth picture
    of when courts are actually occupied. Uses the same per-option / whole-poll
    reading as session_slots(), and assumes a 2-hour session -- the length of
    all but a handful of the sessions that do state both ends -- when no end
    time is given.
    """
    running = [0] * 24
    for p in ps:
        qtxt = strip_non_times(p["q"])
        opt_spans = []
        for o in p["opts"]:
            otxt = strip_non_times(o)
            h, end, _tag = _read_span(otxt, otxt + " " + qtxt)
            if h is not None:
                opt_spans.append((h, end))
        if not opt_spans:
            combined = qtxt + " || " + " | ".join(strip_non_times(o) for o in p["opts"])
            h, end, _tag = _read_span(combined, combined)
            if h is not None:
                opt_spans.append((h, end))
        for h, end in opt_spans:
            for hh in range(h, end):
                running[hh % 24] += 1
    return running


# ------------------------------------------------------------------- report

def main():
    lines = load(sys.argv[1] if len(sys.argv) > 1 else None)
    msgs = parse(lines)
    daily, mstat = membership(msgs)
    ps = polls(lines)

    days = sorted(daily)
    month_end = collections.OrderedDict((d[:7], daily[d]) for d in days)
    per_month = collections.Counter(p["month"] for p in ps)
    msgs_per_month = collections.Counter(m["month"] for m in msgs)
    hours, interest, how, multi_slot_polls = session_slots(ps)
    running = hourly_activity(ps)
    votes, busiest = signups(ps)
    slots, filled, over = capacity(ps)
    vcounts = venues(ps)

    system = re.compile(
        r"(?i)^(.+ (?:added|removed) .+|.+ joined using .+|.{1,60} left"
        r"|.+ pinned a message|you (?:created group|changed|deleted this message)"
        r"|.+ changed (?:this group|the group|their phone number).*"
        r"|messages and calls are end-to-end encrypted.*|.+ turned (?:on|off) .+"
        r"|.+ updated .+|this message was deleted.*)$")
    written = sum(not system.match(m["body"].split("\n")[0].strip()) for m in msgs)

    text = "\n".join(m["body"] for m in msgs).lower()
    waitlist = sum(text.count(w) for w in ("waitlist", "waiting list", "wait list"))
    header = re.compile(r"(?i)(?:waitlist|wait ?list|waiting ?list)\s*[:\-]")
    published = sum(bool(header.search(m["body"])) for m in msgs)

    n = sum(hours)
    say = lambda k, v: print(f"  {k:<34}{v}")

    print(f"\nexport: {len(lines):,} lines, {len(msgs):,} timestamped entries, "
          f"{written:,} of them written by a member, {days[0]} to {days[-1]}")

    print("\nMEMBERSHIP")
    say("roster now", daily[days[-1]])
    say("membership events", mstat["events"])
    say("people ever on the roster", mstat["ever"])
    say("members the group opened with", mstat["founders"])
    print("  month end:", dict(month_end))

    print("\nSESSIONS  (scheduling polls)")
    say("sessions", len(ps))
    say("sign-ups cast", f"{votes:,} ({votes / len(ps):.1f} per session, busiest {busiest})")
    say("slots with a stated player cap", slots)
    say("  filled to the cap", filled)
    say("  oversubscribed", over)
    say("waitlist mentions", waitlist)
    say("waitlists published as a list", published)
    print("  per month:", dict(sorted(per_month.items())))
    print("  messages per month:", dict(sorted(msgs_per_month.items())))

    print("\nVENUES  (sessions naming each in its poll text)")
    for name, c in vcounts.items():
        say(name, c)

    print("\nSTART TIMES  (session slots: one poll can offer several)")
    say("session slots with a start hour", f"{n} from {len(ps)} polls")
    say("polls offering >1 time slot", multi_slot_polls)
    for k, v in how.most_common():
        say(f"  {k}", v)
    say("starting 5-9am", f"{sum(hours[5:10])} ({100 * sum(hours[5:10]) / n:.0f}%)")
    say("starting 10am-4pm", sum(hours[10:17]))
    say("starting 5-8:59pm", sum(hours[17:21]))
    say("starting 9-9:59pm", sum(hours[21:22]))
    say("starting 5pm or later", f"{sum(hours[17:])} ({100 * sum(hours[17:]) / n:.0f}%)")
    say("starting 10pm-5am", sum(hours[22:]) + sum(hours[:5]))
    print("  slots by hour:", hours)
    print("  sign-ups by hour:", interest)
    print("  sessions running by hour (counts a slot in every hour it spans):", running)

    out = DATA / "derived.json"
    out.write_text(json.dumps(dict(
        daily=[[d, daily[d]] for d in days],
        month_end=month_end,
        sessions_per_month=dict(sorted(per_month.items())),
        start_hours=hours,
        start_hour_signups=interest,
        sessions_running_by_hour=running,
        signups=votes,
        capacity=dict(slots=slots, filled=filled, over=over),
        venues=dict(vcounts),
    ), indent=1))
    print(f"\nwrote {out.relative_to(ROOT)}  (untracked)\n")


if __name__ == "__main__":
    main()
