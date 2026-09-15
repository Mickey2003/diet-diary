"""
v0.8.3 测试：生成中状态接口、报告空正文兜底、网络加速、设置项读写。
"""
from app.models import User
from app.services import report as report_service


# ---------- 生成中状态接口 ----------

def test_plan_generating_endpoint(client):
    r = client.get("/api/health/plans/generating")
    assert r.status_code == 200
    assert "generating" in r.json()
    assert isinstance(r.json()["generating"], bool)


def test_report_generating_endpoint(client):
    r = client.get("/api/reports/generating")
    assert r.status_code == 200
    assert isinstance(r.json()["generating"], bool)


def test_report_concurrent_409(client, db):
    """报告生成中再次请求应返回 409（前端据此轮询而非重复生成）。"""
    from app.services import task_state
    uid = db.query(User).filter(User.username == "tester").first().id
    task_state.begin("report", uid)
    try:
        r = client.post("/api/reports", json={"period_type": "week"})
        assert r.status_code == 409
    finally:
        task_state.end("report", uid)


# ---------- 报告空正文兜底 ----------

class _EmptyClient:
    def chat(self, *a, **k):  # noqa: ANN002, ANN003
        return "   "

    def model_name(self, *a, **k):  # noqa: ANN002, ANN003
        return "empty-model"


def test_report_empty_summary_fallback(monkeypatch, db):
    """模型返回空正文时，应使用事实兜底，保证正文非空。"""
    monkeypatch.setattr(report_service.llm_client, "get_client", lambda _db: _EmptyClient())
    rep = report_service.generate_report(db, "week", None, None)
    assert rep.summary_md.strip()
    assert "饮食观察" in rep.summary_md


# ---------- 网络加速 ----------

def test_net_proxy_wrap(monkeypatch):
    from app.services import net_proxy
    monkeypatch.setattr(net_proxy, "get_mode", lambda db=None: "on")
    wrapped = net_proxy.wrap("https://zh.wikipedia.org/w/api.php")
    assert wrapped.startswith("https://proxy.linjiam.in/")
    # 国内域名直连，不加前缀
    assert net_proxy.wrap("https://api.vvhan.com/api/barcode") == "https://api.vvhan.com/api/barcode"
    # 关闭时原样返回
    monkeypatch.setattr(net_proxy, "get_mode", lambda db=None: "off")
    assert net_proxy.wrap("https://zh.wikipedia.org/w/api.php") == "https://zh.wikipedia.org/w/api.php"


# ---------- 设置项 ----------

def test_net_proxy_mode_setting_roundtrip(client):
    r = client.put("/api/settings", json={"net_proxy_mode": "on"})
    assert r.status_code == 200
    assert r.json()["net_proxy_mode"] == "on"
    assert client.get("/api/settings").json()["net_proxy_mode"] == "on"
    # 复位为测试默认
    client.put("/api/settings", json={"net_proxy_mode": "off"})


def test_net_proxy_status_endpoint(client):
    r = client.get("/api/settings/net-proxy/status")
    assert r.status_code == 200
    data = r.json()
    assert {"mode", "enabled", "detected", "url"} <= set(data.keys())
