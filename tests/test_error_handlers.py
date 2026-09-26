#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generic error-handler responses: shape and request_id correlation."""

import io
import logging
import re

REQ_ID_RE = re.compile(r"^[0-9a-f]{12}$")


def test_404_shape(client):
    """An unknown route returns the generic body, not a Flask HTML page."""
    resp = client.get("/api/does-not-exist")
    assert resp.status_code == 404
    body = resp.get_json()
    assert body["error"] == "Not Found"
    assert REQ_ID_RE.match(body["request_id"])
    assert set(body.keys()) == {"error", "request_id"}


def test_405_shape(client):
    """A wrong method on a known route returns the generic body."""
    resp = client.patch("/api/health")
    assert resp.status_code == 405
    body = resp.get_json()
    assert body["error"] == "Method Not Allowed"
    assert REQ_ID_RE.match(body["request_id"])
    assert set(body.keys()) == {"error", "request_id"}


def test_405_names_the_allowed_methods(client):
    """A 405 carries the Allow header RFC 9110 requires, naming what the route does accept."""
    resp = client.patch("/api/stt")
    assert resp.status_code == 405
    assert set(resp.headers["Allow"].split(", ")) >= {"POST", "OPTIONS"}


def test_undecodable_audio_is_a_warning_without_a_traceback(client, caplog):
    """A client upload that is not audio is the client's mistake: one WARNING line, no traceback."""
    caplog.set_level(logging.WARNING, logger="stt_server")
    resp = client.post("/api/stt", data={"file": (io.BytesIO(b"not audio at all"), "notes.txt")})
    assert resp.status_code == 400
    records = [record for record in caplog.records if "Audio conversion failed" in record.getMessage()]
    assert [record.levelname for record in records] == ["WARNING"]
    assert "Traceback" not in caplog.text


def test_request_id_changes_per_request(client):
    """Each request gets its own id, so log lines and reports can be matched up."""
    a = client.get("/api/does-not-exist").get_json()["request_id"]
    b = client.get("/api/does-not-exist").get_json()["request_id"]
    assert a != b
