"""ทดสอบระบบหลักฐานการจ่ายเงิน: ชนิดไฟล์ (ดูจากเนื้อไฟล์), ขนาด, จำนวน, เฉพาะรายจ่าย, ลบแบบซ่อน, ชื่อไฟล์ปลอดภัย"""
import base64
import importlib
import io
import os
import re
import sys
import tempfile

import pytest

import evidence as ev_mod

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# รูป PNG 1x1 พิกเซลที่ถูกต้อง (ใช้ทดสอบว่าไฟล์ที่ผ่านการตรวจถูกเก็บและเปิดดูได้)
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


def load_app(db_path):
    """โหลดแอปด้วยฐานข้อมูลชั่วคราว (โฟลเดอร์หลักฐานจะอยู่ข้าง ๆ ไฟล์ฐานข้อมูลโดยอัตโนมัติ)"""
    os.environ.update(SECRET_KEY="test-secret", DATABASE_PATH=db_path,
                      COLLECTOR_TOKENS="ฉัตร=password-1,มีมี่=password-2,เพียว=password-3")
    os.environ.pop("EVIDENCE_DIR", None)
    sys.path.insert(0, ROOT)
    for m in ("app", "config", "db", "evidence"):
        sys.modules.pop(m, None)
    app = importlib.import_module("app").app
    app.config.update(TESTING=True, ACTION_COOLDOWN_MS=0)
    return app


@pytest.fixture
def client(tmp_path):
    app = load_app(str(tmp_path / "t.db"))
    c = app.test_client()
    c.get("/")
    with c.session_transaction() as s:
        csrf = s["csrf"]
    c.h = {"X-CSRF-Token": csrf}
    assert c.post("/api/login", json={"token": "password-1"}, headers=c.h).json["ok"]
    c.folder = app.config["EVIDENCE_DIR"]
    return c


def new_expense(c, item="ซื้อวัสดุ", amt=120):
    """สร้างรายจ่ายหนึ่งรายการ แล้วคืน id ของรายการ"""
    r = c.post("/api/transactions", json={"type": "out", "d": "2026-10-30", "item": item, "amt": amt}, headers=c.h)
    assert r.json["ok"]
    return r.json["id"]


def upload(c, tid, data, filename="receipt.png"):
    """อัปโหลดไฟล์แบบ multipart เหมือนหน้าเว็บส่ง"""
    return c.post(f"/api/transactions/{tid}/evidence",
                  data={"file": (io.BytesIO(data), filename)}, headers=c.h)


def tx_of(c, tid):
    return next(t for t in c.get("/api/data").json["transactions"] if t["id"] == tid)


# ---------- ตรรกะล้วน ----------
@pytest.mark.parametrize("data,expected", [
    (PNG_1X1, ("png", "image/png")),
    (b"\xff\xd8\xff\xe0" + b"\x00" * 20, ("jpg", "image/jpeg")),
    (b"GIF89a" + b"\x00" * 20, ("gif", "image/gif")),
    (b"RIFF\x10\x00\x00\x00WEBPVP8 " + b"\x00" * 10, ("webp", "image/webp")),
    (b"%PDF-1.7\n" + b"\x00" * 20, ("pdf", "application/pdf")),
    (b"<html><script>alert(1)</script></html>", None),     # HTML ปลอม ไม่ใช่ไฟล์ที่รับ
    (b"hello", None),
])
def test_detect_type_uses_content_not_name(data, expected):
    assert ev_mod.detect_type(data) == expected


def test_clean_display_name_strips_paths_and_forces_extension():
    assert ev_mod.clean_display_name("../../etc/passwd.png", "png") == "passwd.png"
    assert ev_mod.clean_display_name("C:\\Users\\x\\ใบเสร็จ.jpg", "jpg") == "ใบเสร็จ.jpg"
    assert ev_mod.clean_display_name("evil<script>.png", "png") == "evilscript.png"
    assert ev_mod.clean_display_name("", "pdf") == "หลักฐาน.pdf"
    assert ev_mod.clean_display_name("receipt.exe", "pdf") == "receipt.pdf"   # นามสกุลต้องตรงกับไฟล์จริง


def test_stored_name_format_is_strict():
    assert ev_mod.is_valid_stored_name(ev_mod.new_stored_name("png"))
    assert not ev_mod.is_valid_stored_name("../secret.db")
    assert not ev_mod.is_valid_stored_name("a" * 32 + ".exe")


# ---------- API ----------
def test_upload_to_expense_then_view_and_log(client):
    tid = new_expense(client)
    r = upload(client, tid, PNG_1X1, "ใบเสร็จ.png")
    assert r.json["ok"]
    files = tx_of(client, tid)["ev"]
    assert len(files) == 1 and files[0]["name"] == "ใบเสร็จ.png" and files[0]["mime"] == "image/png"
    view = client.get(f"/api/evidence/{files[0]['id']}")
    assert view.status_code == 200 and view.mimetype == "image/png" and view.data == PNG_1X1
    assert "default-src 'none'" in view.headers["Content-Security-Policy"]
    assert client.get("/api/data").json["audit"][0]["action"] == "upload_evidence"


def test_pdf_is_served_as_pdf(client):
    tid = new_expense(client)
    upload(client, tid, b"%PDF-1.4\n%%EOF\n", "bill.pdf")
    eid = tx_of(client, tid)["ev"][0]["id"]
    resp = client.get(f"/api/evidence/{eid}")
    assert resp.mimetype == "application/pdf" and "Content-Security-Policy" not in resp.headers


def test_fake_extension_is_rejected_and_nothing_is_stored(client):
    tid = new_expense(client)
    r = upload(client, tid, b"<html>not an image</html>", "receipt.png")
    assert r.status_code == 415 and r.json["error"] == "bad_type"
    assert tx_of(client, tid)["ev"] == []
    assert not os.path.isdir(client.folder) or os.listdir(client.folder) == []


def test_too_large_file_is_rejected_with_json(client):
    tid = new_expense(client)
    big = PNG_1X1 + b"\x00" * (5 * 1024 * 1024)            # เกินเพดาน 5 MB แต่ยังไม่เกินเพดาน request
    r = upload(client, tid, big)
    assert r.status_code == 413 and r.json["error"] == "too_big"
    way_big = PNG_1X1 + b"\x00" * (6 * 1024 * 1024)        # เกินเพดาน request ทั้งหมด -> ต้องได้ JSON ไม่ใช่ HTML
    r2 = upload(client, tid, way_big)
    assert r2.status_code == 413 and r2.is_json and r2.json["error"] == "too_big"


def test_only_expense_accepts_evidence(client):
    income = client.post("/api/transactions", json={"type": "in", "d": "2026-10-30", "item": "เงินบริจาค", "amt": 50},
                         headers=client.h).json["id"]
    r = upload(client, income, PNG_1X1)
    assert r.status_code == 409 and r.json["error"] == "not_expense"


def test_limit_of_files_per_expense(client):
    tid = new_expense(client)
    for i in range(5):
        assert upload(client, tid, PNG_1X1, f"f{i}.png").json["ok"]
    r = upload(client, tid, PNG_1X1, "extra.png")
    assert r.status_code == 409 and r.json["error"] == "too_many_evidence"


def test_delete_hides_file_keeps_it_on_disk_and_logs(client):
    tid = new_expense(client)
    upload(client, tid, PNG_1X1, "a.png")
    eid = tx_of(client, tid)["ev"][0]["id"]
    assert client.delete(f"/api/evidence/{eid}", headers=client.h).json["ok"]
    assert tx_of(client, tid)["ev"] == []
    assert client.get(f"/api/evidence/{eid}").status_code == 404
    assert len(os.listdir(client.folder)) == 1                 # ไฟล์ยังอยู่ (soft delete)
    assert client.get("/api/data").json["audit"][0]["action"] == "delete_evidence"


def test_deleted_expense_hides_its_evidence(client):
    tid = new_expense(client)
    upload(client, tid, PNG_1X1)
    eid = tx_of(client, tid)["ev"][0]["id"]
    assert client.delete(f"/api/transactions/{tid}", headers=client.h).json["ok"]
    assert client.get(f"/api/evidence/{eid}").status_code == 404


def test_stored_file_name_never_comes_from_user(client):
    tid = new_expense(client)
    upload(client, tid, PNG_1X1, "../../../../tmp/owned.png")
    names = os.listdir(client.folder)
    assert len(names) == 1 and re.match(r"^[0-9a-f]{32}\.png$", names[0])
    assert not os.path.exists("/tmp/owned.png")
    assert tx_of(client, tid)["ev"][0]["name"] == "owned.png"   # ชื่อที่แสดงยังอ่านได้


def test_requires_login_and_csrf(client):
    tid = new_expense(client)
    anon = client.application.test_client()
    anon.get("/")
    assert anon.post(f"/api/transactions/{tid}/evidence", data={"file": (io.BytesIO(PNG_1X1), "a.png")}).status_code == 403
    with anon.session_transaction() as s:
        h = {"X-CSRF-Token": s["csrf"]}
    r = anon.post(f"/api/transactions/{tid}/evidence", data={"file": (io.BytesIO(PNG_1X1), "a.png")}, headers=h)
    assert r.status_code == 401


def test_anonymous_visitor_can_view_evidence_list_and_file(client):
    """ผู้ชมทั่วไป (ไม่ล็อกอิน) ต้องเห็นรายการหลักฐานและเปิดไฟล์ได้ แต่ข้อมูลส่วนนี้ไม่ได้ผูกกับการล็อกอิน"""
    tid = new_expense(client)
    upload(client, tid, PNG_1X1, "public.png")
    anon = client.application.test_client()
    anon.get("/")
    row = next(t for t in anon.get("/api/data").json["transactions"] if t["id"] == tid)
    assert [f["name"] for f in row["ev"]] == ["public.png"]
    assert anon.get(f"/api/evidence/{row['ev'][0]['id']}").status_code == 200
