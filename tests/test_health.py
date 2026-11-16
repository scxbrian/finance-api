def test_health_is_ok_and_not_cacheable(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_ready_reports_unavailable_in_the_standard_error_shape(client):
    response = client.get("/api/ready")
    assert response.status_code == 503
    assert response.json() == {
        "error": {"code": "unavailable", "message": "The database is not reachable."}
    }
    assert response.headers["cache-control"] == "no-store"


def test_unknown_path_uses_the_error_shape(client):
    response = client.get("/api/nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_wrong_method_uses_the_error_shape(client):
    response = client.post("/api/health")
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"