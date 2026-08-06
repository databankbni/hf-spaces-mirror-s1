"""
constants.py — Shared reference data for the luther_mcp package.

Book name lists are 1-indexed (index 0 is an empty string placeholder).
"""

BOOK_NAMES_EN = [
    "",
    "Genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy",
    "Joshua", "Judges", "Ruth", "1 Samuel", "2 Samuel",
    "1 Kings", "2 Kings", "1 Chronicles", "2 Chronicles", "Ezra",
    "Nehemiah", "Esther", "Job", "Psalms", "Proverbs",
    "Ecclesiastes", "Song of Solomon", "Isaiah", "Jeremiah", "Lamentations",
    "Ezekiel", "Daniel", "Hosea", "Joel", "Amos",
    "Obadiah", "Jonah", "Micah", "Nahum", "Habakkuk",
    "Zephaniah", "Haggai", "Zechariah", "Malachi",
    "Matthew", "Mark", "Luke", "John", "Acts",
    "Romans", "1 Corinthians", "2 Corinthians", "Galatians", "Ephesians",
    "Philippians", "Colossians", "1 Thessalonians", "2 Thessalonians", "1 Timothy",
    "2 Timothy", "Titus", "Philemon", "Hebrews", "James",
    "1 Peter", "2 Peter", "1 John", "2 John", "3 John",
    "Jude", "Revelation",
]

BOOK_NAMES_DE = [
    "",
    "1. Mose", "2. Mose", "3. Mose", "4. Mose", "5. Mose",
    "Josua", "Richter", "Ruth", "1. Samuel", "2. Samuel",
    "1. Könige", "2. Könige", "1. Chronik", "2. Chronik", "Esra",
    "Nehemia", "Esther", "Hiob", "Psalmen", "Sprüche",
    "Prediger", "Hoheslied", "Jesaja", "Jeremia", "Klagelieder",
    "Hesekiel", "Daniel", "Hosea", "Joel", "Amos",
    "Obadja", "Jona", "Micha", "Nahum", "Habakuk",
    "Zefanja", "Haggai", "Sacharja", "Maleachi",
    "Matthäus", "Markus", "Lukas", "Johannes", "Apostelgeschichte",
    "Römer", "1. Korinther", "2. Korinther", "Galater", "Epheser",
    "Philipper", "Kolosser", "1. Thessalonicher", "2. Thessalonicher", "1. Timotheus",
    "2. Timotheus", "Titus", "Philemon", "Hebräer", "Jakobus",
    "1. Petrus", "2. Petrus", "1. Johannes", "2. Johannes", "3. Johannes",
    "Judas", "Offenbarung",
]

# Build lookup: lowercase name -> book number (1-66)
_BOOK_LOOKUP: dict[str, int] = {}
for _i, _name in enumerate(BOOK_NAMES_EN):
    if _name:
        _BOOK_LOOKUP[_name.lower()] = _i
for _i, _name in enumerate(BOOK_NAMES_DE):
    if _name:
        _BOOK_LOOKUP[_name.lower()] = _i

TRANSLATION_META = {
    "GerBoLut": {
        "language": "German",
        "description": "Luther Bible 1545 (modern spelling)",
    },
    "KJV": {
        "language": "English",
        "description": "King James Version",
    },
    "web": {
        "language": "English",
        "description": "New Heart English Bible (based on World English Bible)",
    },
}

ALL_TRANSLATIONS = list(TRANSLATION_META.keys())

# Indexer: (collection_name, db_filename, use_german_names)
# Files live under formats/sqlite/ in scrollmapper/bible_databases.
# "web" collection uses NHEB.db (New Heart English Bible, based on WEB).
TRANSLATIONS = [
    ("GerBoLut", "GerBoLut.db", True),
    ("KJV",      "KJV.db",      False),
    ("web",      "NHEB.db",     False),
]
