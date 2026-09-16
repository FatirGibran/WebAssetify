"""Tests for keep-alive micro-HTTP web server."""

import json
import pytest
from aiohttp.test_utils import make_mocked_request

from main import create_web_app, health_endpoint


@pytest.mark.asyncio
async def test_health_endpoint():
    req = make_mocked_request("GET", "/health")
    resp = await health_endpoint(req)
    assert resp.status == 200
    data = json.loads(resp.text)
    assert data["status"] == "alive"
    assert data["service"] == "WebAssetify"
    assert "uptime_seconds" in data
    assert data["uptime_seconds"] >= 0


@pytest.mark.asyncio
async def test_root_endpoint():
    req = make_mocked_request("GET", "/")
    resp = await health_endpoint(req)
    assert resp.status == 200
    data = json.loads(resp.text)
    assert data["status"] == "alive"
    assert data["service"] == "WebAssetify"


def test_app_router_routes():
    app = create_web_app()
    routes = [r.resource.canonical for r in app.router.routes()]
    assert "/" in routes
    assert "/health" in routes
