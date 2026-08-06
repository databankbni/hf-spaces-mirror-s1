import sqlite3

conn = sqlite3.connect("data/gita.sqlite")
total = conn.execute("select count(*) from verses").fetchone()[0]
missing = conn.execute(
    "select count(*) from verses where sa_seconds is null or en_seconds is null"
).fetchone()[0]
print("verses:", total, "| missing durations:", missing)
print("ensure_audio will skip synthesis:", missing == 0)
