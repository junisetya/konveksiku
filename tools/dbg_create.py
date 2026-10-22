import os, sys, json
os.environ.update(SQLITE_PATH="data/rofi-dbg.sqlite3", OWNER_PASSWORD="uji-konveksi-2026",
  SECRET_KEY="z"*64, DATABASE_URL="", APP_ORIGIN="http://127.0.0.1", FONNTE_TOKEN="")
sys.path.insert(0,'.')
import app as A, rofi_api_v2 as V
A.initialize()
c = A.app.test_client()
r = c.post("/api/login", data=json.dumps({"password":"uji-konveksi-2026"}), headers={"Origin":"http://127.0.0.1"}, content_type="application/json")
csrf = r.get_json()["csrf"]
print(V.v2_ready)
payload = {"customer":"Budi","wa":"081234567890","deal":A.today(),"target":A.today(),
 "items":[{"garment":"Batik","qty":10,"price":100000,"sizes":[]}]}
try:
    d = V._validate_order_payload(payload)
    print("validated", d["total"])
    V.v2_create_order.__wrapped__ if hasattr(V.v2_create_order,'__wrapped__') else None
except Exception:
    import traceback; traceback.print_exc()
r = c.post("/api/v2/orders", data=json.dumps(payload), headers={"Origin":"http://127.0.0.1","X-CSRF-Token":csrf}, content_type="application/json")
print(r.status_code, r.get_json())
with A.connect() as db:
    print("orders:", len(db.execute("select * from orders").fetchall()))
