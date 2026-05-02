#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generic error-handler responses: shape and request_id correlation."""

import re

REQ_ID_RE = re.compile(r"^[0-9a-f]{12}$")


def test_404_shape(client):
    resp = client.get("/api/does-not-exist")
    assert resp.status_code == 404
    body = resp.get_json()
    assert body["error"] == "Not Found"
    assert REQ_ID_RE.match(body["request_id"])
    assert set(body.keys()) == {"error", "request_id"}


def test_405_shape(client):
    resp = client.patch("/api/health")
    assert resp.status_code == 405
    body = resp.get_json()
    assert body["error"] == "Method Not Allowed"
    assert REQ_ID_RE.match(body["request_id"])
    assert set(body.keys()) == {"error", "request_id"}


def test_request_id_changes_per_request(client):
    a = client.get("/api/does-not-exist").get_json()["request_id"]
    b = client.get("/api/does-not-exist").get_json()["request_id"]
    assert a != b
