import os, sys, json
os.environ.update(SQLITE_PATH="data/rofi-e2e.sqlite3", OWNER_PASSWORD="uji-konveksi-2026",
  SECRET_KEY="z"*64, DATABASE_URL="", APP_ORIGIN="http://127.0.0.1", FONNTE_TOKEN="")
sys.path.insert(0,'.')
import app as A
with A.connect() as c:
    for row in c.execute("SELECT * FROM orders").fetchall():
        print(row["number"], "keys:", sorted(json.loads(row["data"]).keys())[:6])
