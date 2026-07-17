"""Health route tests (P2 / PY-D12)."""


def test_startup_ok(client):
    r = client.get("/health/startup")
    assert r.status_code == 200
    assert r.json()["status"] == "started"


def test_live_ok(client):
    r = client.get("/health/live")
    assert r.status_code == 200
    assert r.json()["status"] == "alive"


def test_ready_ok(client):
    r = client.get("/health/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready"
    assert body["checks"]["config"] == "ok"


def test_health_is_at_root_not_under_api(client):
    # The proxy bypasses auth+metering on the root /health/* paths only — there must be no
    # /api-prefixed variant (PY-D12).
    assert client.get("/api/health/startup").status_code == 404
