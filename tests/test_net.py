# tests/test_net.py
from fastapi import Request


def _make_request(headers=None, client_host="10.0.0.5"):
    scope = {
        "type": "http",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "client": (client_host, 12345) if client_host is not None else None,
    }
    return Request(scope)


def test_client_ip_prefers_cf_connecting_ip_header():
    from app.net import client_ip

    request = _make_request(headers={"CF-Connecting-IP": "203.0.113.42"})
    assert client_ip(request) == "203.0.113.42"


def test_client_ip_falls_back_to_request_client_host():
    from app.net import client_ip

    request = _make_request(headers={}, client_host="10.0.0.5")
    assert client_ip(request) == "10.0.0.5"


def test_client_ip_returns_unknown_when_no_client_info():
    from app.net import client_ip

    request = _make_request(headers={}, client_host=None)
    assert client_ip(request) == "unknown"
