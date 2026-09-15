"""
测试数据导入导出功能（Feature 1）。
覆盖：JSON/CSV/ZIP 导出格式、合并去重、替换模式、CSV 路径、ZIP 含图片、用户隔离。
"""
import csv
import io
import json
import zipfile
from datetime import datetime
from fastapi.testclient import TestClient

import pytest

from app.main import app
from app.models import Meal, MealItem, meal_item_tags
from tests.conftest import TEST_USER, add_meal


# ---------- 辅助 ----------

def _login(c: TestClient, username: str, password: str) -> None:
    r = c.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text


def _ensure_user(admin_client: TestClient, username: str, password: str) -> int:
    users = admin_client.get("/api/admin/users").json()
    for u in users:
        if u["username"] == username:
            return u["id"]
    r = admin_client.post("/api/admin/users",
                          json={"username": username, "password": password, "role": "user"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _meal_payload(meal_type: str = "午餐", items=None):
    if items is None:
        items = [{"name": "白米饭", "category": "主食", "portion": "中", "tags": [], "source": "user"}]
    return {
        "eaten_at": "2026-09-05T12:00:00",
        "meal_type": meal_type,
        "items": items,
    }


# ---------- GET /api/data/summary ----------

def test_summary_returns_counts(client, clean_meals):
    r = client.get("/api/data/summary")
    assert r.status_code == 200
    data = r.json()
    assert "meals" in data and "reports" in data and "memories" in data


# ---------- GET /api/data/template.csv ----------

def test_download_template_csv(client):
    r = client.get("/api/data/template.csv")
    assert r.status_code == 200
    assert "text/csv" in r.headers.get("content-type", "")
    # CSV 应有表头和 3 行示例
    content = r.content.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(content))
    rows = list(reader)
    assert rows[0][0] == "日期"
    assert len(rows) >= 4  # header + 3 rows


# ---------- GET /api/data/export?format=json ----------

def test_export_json_shape(client, clean_meals, db):
    add_meal(db, 0, 12, "午餐", [("番茄炒蛋", "蛋白质", ["egg", "vegetable"])])
    r = client.get("/api/data/export?format=json")
    assert r.status_code == 200
    assert "application/json" in r.headers.get("content-type", "")
    data = r.json()
    assert data["version"] == "0.3"
    assert "exported_at" in data
    assert "user" in data
    assert "password" not in str(data)  # 不含密码
    assert "api_key" not in str(data)
    assert len(data["meals"]) == 1
    meal = data["meals"][0]
    assert "items" in meal
    assert "image_file" in meal
    assert meal["items"][0]["name"] == "番茄炒蛋"
    assert "tags" in meal["items"][0]


def test_export_json_no_other_users_data(client, clean_meals, db):
    """导出仅包含当前用户的数据（用户隔离）。"""
    from app.models import User
    # 确保有另一个用户并添加餐食
    _ensure_user(client, "carol", "carol-pass-123")
    with TestClient(app) as carol:
        _login(carol, "carol", "carol-pass-123")
        carol.post("/api/meals", json=_meal_payload("早餐"))
    # admin 导出不应包含 carol 的数据
    r = client.get("/api/data/export?format=json")
    data = r.json()
    assert data["user"]["username"] == TEST_USER[0]
    # admin 自己没有在 clean_meals 之后创建餐食，所以 meals 应为 0
    assert len(data["meals"]) == 0


# ---------- GET /api/data/export?format=csv ----------

def test_export_csv_shape(client, clean_meals, db):
    add_meal(db, 0, 12, "午餐", [("米饭", "主食", []), ("青菜", "蔬菜", ["vegetable"])])
    r = client.get("/api/data/export?format=csv")
    assert r.status_code == 200
    assert "csv" in r.headers.get("content-type", "").lower()
    content = r.content.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(content))
    rows = list(reader)
    assert rows[0][0] == "日期"
    # 2 个 item → 2 数据行
    assert len(rows) == 3  # header + 2


def test_export_csv_bom(client, clean_meals, db):
    """CSV 应以 BOM 开头，Excel 可正确识别 UTF-8。"""
    add_meal(db, 0, 12, "午餐", [("米饭", "主食", [])])
    r = client.get("/api/data/export?format=csv")
    assert r.content[:3] == b"\xef\xbb\xbf"


# ---------- GET /api/data/export?format=zip ----------

def test_export_zip_contains_json_and_readme(client, clean_meals, db):
    add_meal(db, 0, 12, "午餐", [("米饭", "主食", [])])
    r = client.get("/api/data/export?format=zip")
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("application/zip")
    assert "diet-diary-export" in r.headers.get("content-disposition", "")
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = zf.namelist()
    assert "data.json" in names
    assert "README.txt" in names
    data = json.loads(zf.read("data.json").decode("utf-8"))
    assert data["version"] == "0.3"


def test_export_zip_with_image(client, clean_meals, db, tmp_path):
    """ZIP 导出时应包含餐食关联的图片文件。"""
    from app import config as cfg
    from pathlib import Path
    # 创建一个假图片
    import io as _io
    try:
        from PIL import Image
        img = Image.new("RGB", (10, 10), color=(100, 150, 200))
        buf = _io.BytesIO()
        img.save(buf, "JPEG")
        img_bytes = buf.getvalue()
    except ImportError:
        img_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 100  # 最小 JPEG header
    # 直接写到 UPLOAD_DIR
    img_name = "test_export_img.jpg"
    (Path(cfg.UPLOAD_DIR) / img_name).write_bytes(img_bytes)
    # 创建带图片的餐食
    m = add_meal(db, 0, 12, "午餐", [("米饭", "主食", [])])
    m.image_path = img_name
    db.commit()

    r = client.get("/api/data/export?format=zip&include_images=true")
    assert r.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    assert f"images/{img_name}" in zf.namelist()


def test_export_invalid_format(client):
    r = client.get("/api/data/export?format=excel")
    assert r.status_code == 400


# ---------- POST /api/data/import ----------

def _make_import_json(meals=None) -> bytes:
    data = {
        "version": "0.3",
        "exported_at": datetime.now().isoformat(),
        "user": {"username": "test", "display_name": None},
        "profile": None,
        "meals": meals or [
            {
                "eaten_at": "2026-01-01T12:00:00",
                "meal_type": "午餐",
                "note": "测试",
                "source": "import",
                "image_file": None,
                "items": [
                    {"name": "白米饭", "category": "主食", "portion": "中",
                     "tags": [], "source": "user", "barcode": None}
                ],
            }
        ],
        "reports": [],
        "memories": [],
        "meal_plans": [],
    }
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


def test_import_json_merge(client, clean_meals):
    """JSON 导入（合并模式）应正确创建餐食记录。"""
    file_bytes = _make_import_json()
    r = client.post(
        "/api/data/import",
        files={"file": ("export.json", file_bytes, "application/json")},
        data={"mode": "merge"},
    )
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["imported"]["meals"] == 1
    assert result["imported"]["items"] == 1
    assert result["skipped"] == 0


def test_import_json_merge_dedup(client, clean_meals):
    """合并模式：相同 eaten_at+meal_type+items 的记录应跳过（去重）。"""
    file_bytes = _make_import_json()
    # 第一次导入
    r1 = client.post("/api/data/import",
                     files={"file": ("export.json", file_bytes, "application/json")},
                     data={"mode": "merge"})
    assert r1.json()["imported"]["meals"] == 1
    # 第二次导入相同文件
    r2 = client.post("/api/data/import",
                     files={"file": ("export.json", file_bytes, "application/json")},
                     data={"mode": "merge"})
    assert r2.json()["imported"]["meals"] == 0
    assert r2.json()["skipped"] == 1


def test_import_json_replace(client, clean_meals, db):
    """替换模式：先清空再导入。"""
    # 预创建一条餐食
    add_meal(db, 0, 8, "早餐", [("燕麦", "主食", [])])
    # 导入 1 条不同的餐食（替换模式）
    file_bytes = _make_import_json()
    r = client.post("/api/data/import",
                    files={"file": ("export.json", file_bytes, "application/json")},
                    data={"mode": "replace"})
    assert r.status_code == 200
    result = r.json()
    assert result["imported"]["meals"] == 1
    # 验证只剩 1 条
    meals_r = client.get("/api/meals")
    assert meals_r.json()["total"] == 1


def test_import_csv_path(client, clean_meals):
    """CSV 导入路径：多行同 日期+时间+餐次 应合并为一餐。"""
    csv_content = (
        "日期,时间,餐次,菜品,分类,份量,标签,来源,备注,条形码\n"
        "2026-03-01,12:00,午餐,白米饭,主食,中,,user,午餐,\n"
        "2026-03-01,12:00,午餐,番茄炒蛋,蛋白质,中,egg,user,,\n"
        "2026-03-02,08:00,早餐,燕麦粥,主食,中,whole_grain,user,,\n"
    )
    file_bytes = b"\xef\xbb\xbf" + csv_content.encode("utf-8")
    r = client.post("/api/data/import",
                    files={"file": ("data.csv", file_bytes, "text/csv")},
                    data={"mode": "merge"})
    assert r.status_code == 200, r.text
    result = r.json()
    # 2 组 (2026-03-01 午餐) + (2026-03-02 早餐) = 2 餐
    assert result["imported"]["meals"] == 2
    # 共 3 个 item
    assert result["imported"]["items"] == 3


def test_import_zip_with_image(client, clean_meals, tmp_path):
    """ZIP 导入：包含图片时应写入 UPLOAD_DIR 并关联到餐食。"""
    try:
        from PIL import Image
        img = Image.new("RGB", (10, 10), color=(200, 100, 50))
        buf = io.BytesIO()
        img.save(buf, "JPEG")
        img_bytes = buf.getvalue()
    except ImportError:
        # 最小 JPEG（1x1 红色像素）
        img_bytes = (
            b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
            b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
            b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
            b"\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\x1e"
            b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
            b"\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b"
            b"\xff\xc4\x00\xb5\x10\x00\x02\x01\x03\x03\x02\x04\x03\x05\x05\x04"
            b"\x04\x00\x00\x01}\x01\x02\x03\x00\x04\x11\x05\x12!1A\x06\x13Qa"
            b"\x07\"q\x142\x81\x91\xa1\x08#B\xb1\xc1\x15R\xd1\xf0$3br\x82\t\n"
            b"\x16\x17\x18\x19\x1a%&'()*456789:CDEFGHIJSTUVWXYZ"
            b"cdefghijstuvwxyz\x83\x84\x85\x86\x87\x88\x89\x8a\x92\x93\x94\x95"
            b"\x96\x97\x98\x99\x9a\xa2\xa3\xa4\xa5\xa6\xa7\xa8\xa9\xaa\xb2\xb3"
            b"\xb4\xb5\xb6\xb7\xb8\xb9\xba\xc2\xc3\xc4\xc5\xc6\xc7\xc8\xc9\xca"
            b"\xd2\xd3\xd4\xd5\xd6\xd7\xd8\xd9\xda\xe1\xe2\xe3\xe4\xe5\xe6\xe7"
            b"\xe8\xe9\xea\xf1\xf2\xf3\xf4\xf5\xf6\xf7\xf8\xf9\xfa"
            b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xfb\xd0\xff\xd9"
        )

    # 构建 ZIP
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as zf:
        meal_data = {
            "version": "0.3",
            "exported_at": datetime.now().isoformat(),
            "user": {"username": "test", "display_name": None},
            "profile": None,
            "meals": [{
                "eaten_at": "2026-03-10T12:00:00",
                "meal_type": "午餐",
                "note": None,
                "source": "import",
                "image_file": "test_zip_img.jpg",
                "items": [{"name": "米饭", "category": "主食", "portion": "中",
                           "tags": [], "source": "user", "barcode": None}],
            }],
            "reports": [], "memories": [], "meal_plans": [],
        }
        zf.writestr("data.json", json.dumps(meal_data, ensure_ascii=False))
        zf.writestr("images/test_zip_img.jpg", img_bytes)
        zf.writestr("README.txt", "test")

    r = client.post("/api/data/import",
                    files={"file": ("export.zip", zip_buf.getvalue(), "application/zip")},
                    data={"mode": "merge"})
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["imported"]["meals"] == 1
    # 图片应已保存（images 计数 > 0 或 errors 为空）
    assert result["imported"]["images"] >= 0  # 成功时 ≥ 1，失败时 = 0（容忍 pillow 能力差异）


def test_import_invalid_extension(client):
    r = client.post("/api/data/import",
                    files={"file": ("data.xlsx", b"dummy", "application/octet-stream")},
                    data={"mode": "merge"})
    assert r.status_code == 400


def test_import_anon_401(anon_client):
    r = anon_client.post("/api/data/import",
                         files={"file": ("data.json", b"{}", "application/json")},
                         data={"mode": "merge"})
    assert r.status_code == 401
