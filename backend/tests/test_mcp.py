"""MCP Streamable HTTP：鉴权、initialize、tools/list、tools/call、批量与通知。"""
from fastapi.testclient import TestClient

from app.main import app


def _token(client) -> str:
    return client.post("/api/tokens", json={"name": "mcp-test", "scopes": "mcp"}).json()["token"]


def _rpc(c: TestClient, token: str, method: str, params=None, id_=1):
    body = {"jsonrpc": "2.0", "id": id_, "method": method}
    if params is not None:
        body["params"] = params
    return c.post("/mcp", json=body, headers={"Authorization": f"Bearer {token}"})


def test_mcp_requires_token(anon_client):
    r = anon_client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 401
    assert anon_client.get("/mcp").status_code == 405


def test_mcp_flow(client, clean_meals):
    token = _token(client)
    with TestClient(app) as c:
        r = _rpc(c, token, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}})
        assert r.status_code == 200
        body = r.json()
        assert body["result"]["protocolVersion"] == "2025-03-26"
        assert body["result"]["serverInfo"]["name"] == "diet-diary"
        assert "Mcp-Session-Id" in r.headers
        # 通知 → 202 无正文
        r = c.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                   headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 202
        names = {t["name"] for t in _rpc(c, token, "tools/list").json()["result"]["tools"]}
        assert {"log_meal", "list_meals", "get_stats", "ask_diet_question", "generate_report", "get_today_summary", "list_tags"} <= names
        # 记一餐
        r = _rpc(c, token, "tools/call", {"name": "log_meal", "arguments": {
            "meal_type": "午餐", "items": [{"name": "番茄炒蛋", "category": "蛋白质", "tags": ["egg", "蔬菜"]},
                                           {"name": "奶茶", "category": "饮品", "tags": ["sugary_drink"]}]}})
        res = r.json()["result"]
        assert not res.get("isError"), res
        assert '"ok": true' in res["content"][0]["text"]
        # 今日小结 / 查询 / 统计
        txt = _rpc(c, token, "tools/call", {"name": "get_today_summary", "arguments": {}}).json()["result"]["content"][0]["text"]
        assert "番茄炒蛋" in txt
        r = _rpc(c, token, "tools/call", {"name": "ask_diet_question", "arguments": {"question": "这周喝过几次含糖饮料"}})
        assert '"count": 1' in r.json()["result"]["content"][0]["text"]
        r = _rpc(c, token, "tools/call", {"name": "get_stats", "arguments": {"range": "week"}})
        assert '"meal_count": 1' in r.json()["result"]["content"][0]["text"]
        # 错误参数 → isError
        r = _rpc(c, token, "tools/call", {"name": "log_meal", "arguments": {"meal_type": "下午茶", "items": []}})
        assert r.json()["result"]["isError"] is True
        # 未知工具 / 方法
        assert _rpc(c, token, "tools/call", {"name": "nope", "arguments": {}}).json()["error"]["code"] == -32602
        assert _rpc(c, token, "foo/bar").json()["error"]["code"] == -32601
        # 批量
        r = c.post("/mcp", json=[{"jsonrpc": "2.0", "id": 1, "method": "ping"}, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}],
                   headers={"Authorization": f"Bearer {token}"})
        assert isinstance(r.json(), list) and len(r.json()) == 2
    # 记录归属令牌对应用户
    assert client.get("/api/meals").json()["total"] == 1
    assert client.get("/api/meals").json()["items"][0]["source"] == "mcp"
    assert client.get("/api/mcp/info").json()["endpoint"].endswith("/mcp")
