import os
import json
from urllib.parse import urlparse
from pathlib import Path
from dotenv import load_dotenv
import psycopg2

# load env
env_path = Path(__file__).resolve().parent.parent / '.env'
if env_path.exists():
    load_dotenv(dotenv_path=env_path, override=False)

DATABASE_URL = os.getenv('DATABASE_URL')
if not DATABASE_URL:
    print(json.dumps({'error': 'DATABASE_URL not set'}))
    raise SystemExit(1)

# connect
conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

# list public tables
cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name;")
rows = cur.fetchall()

tables = [r[0] for r in rows]
output = {}
for t in tables:
    try:
        cur.execute(f'SELECT COUNT(*) FROM "{t}"')
        cnt = cur.fetchone()[0]
    except Exception as e:
        cnt = str(e)
    sample = []
    if isinstance(cnt, int) and cnt > 0:
        try:
            cur.execute(f'SELECT * FROM "{t}" LIMIT 5')
            cols = [d[0] for d in cur.description]
            for r in cur.fetchall():
                row = {}
                for i in range(len(cols)):
                    v = r[i]
                    if isinstance(v, bytes):
                        row[cols[i]] = '<binary>'
                    else:
                        try:
                            json.dumps(v)
                            row[cols[i]] = v
                        except Exception:
                            try:
                                row[cols[i]] = v.isoformat()
                            except Exception:
                                row[cols[i]] = str(v)
                sample.append(row)
        except Exception as e:
            sample = [str(e)]
    output[t] = {'count': cnt, 'sample': sample}

cur.close()
conn.close()
print(json.dumps(output, indent=2, ensure_ascii=False))
