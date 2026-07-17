"""Sample route tests, incl. intrinsic Pydantic validation (P15 / PY-D21 / J3)."""


def test_hello_shape(client):
    r = client.get("/v1/hello")
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == "v1"
    assert body["score"] == 110
    assert body["environment"] == "development"


def test_echo_valid(client):
    r = client.post("/v1/echo", json={"name": "Acme"})
    assert r.status_code == 200
    assert r.json() == {"message": "echo", "name": "Acme"}


def test_echo_missing_field_returns_422(client):
    # Malformed body → 422 automatically (validation is intrinsic to FastAPI).
    r = client.post("/v1/echo", json={})
    assert r.status_code == 422


def test_echo_empty_name_returns_422(client):
    r = client.post("/v1/echo", json={"name": ""})
    assert r.status_code == 422
