"""Tests for the multipart upload engine (no network, no real S3)."""

from __future__ import annotations

import httpx
import pytest

from fz_cli.upload import upload_file

PROJ = "22222222-2222-2222-2222-222222222222"
UP = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


@pytest.fixture
def s3(monkeypatch):
    """Mock S3: every PUT succeeds and returns an ETag; records requests."""
    puts = []

    def handler(request: httpx.Request) -> httpx.Response:
        puts.append(request)
        return httpx.Response(200, headers={"ETag": f'"etag-{len(puts)}"'})

    real_client = httpx.Client

    def patched_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(**{k: v for k, v in kwargs.items() if k in {"transport", "limits", "timeout"}})

    monkeypatch.setattr("fz_cli.upload.httpx.Client", patched_client)
    return puts


def test_multipart_upload_flow(api, s3, tmp_path, monkeypatch):
    monkeypatch.setattr("fz_cli.upload.time.sleep", lambda s: None)
    f = tmp_path / "big.pdf"
    f.write_bytes(b"A" * 100)

    api.add("POST", f"/api/projects/{PROJ}/uploads/init", 201, {
        "uploadId": UP,
        "partSizeBytes": 60,
        "totalParts": 2,
        "presignedUrls": [
            {"partNumber": 1, "url": "https://s3.test/p1"},
            {"partNumber": 2, "url": "https://s3.test/p2"},
        ],
        "isSinglePart": False,
    })
    api.add("POST", f"/api/uploads/{UP}/parts", 200, {"ok": True})
    api.add("POST", f"/api/uploads/{UP}/complete", 200,
            {"document": {"id": "doc-1", "fileName": "big.pdf", "status": "pending"}})

    from fz_cli.client import FZClient

    fz = FZClient("http://ev.test")
    doc = upload_file(fz, PROJ, f)

    assert doc["id"] == "doc-1"
    # Both parts PUT to S3 with correct sizes (60 + 40).
    assert len(s3) == 2
    sizes = sorted(len(r.content) for r in s3)
    assert sizes == [40, 60]
    # Init -> 2 part reports -> complete, all against the API.
    paths = [r.path for r in api.requests]
    assert paths.count(f"/api/uploads/{UP}/parts") == 2
    assert paths[-1] == f"/api/uploads/{UP}/complete"
    reported = [r.json for r in api.requests if r.path == f"/api/uploads/{UP}/parts"]
    assert {p["partNumber"] for p in reported} == {1, 2}
    assert all(p["etag"].startswith("etag-") for p in reported)


def test_single_part_sets_content_type(api, s3, tmp_path):
    f = tmp_path / "small.pdf"
    f.write_bytes(b"tiny")

    api.add("POST", f"/api/projects/{PROJ}/uploads/init", 201, {
        "uploadId": UP,
        "partSizeBytes": 1024,
        "totalParts": 1,
        "presignedUrls": [{"partNumber": 1, "url": "https://s3.test/p1"}],
        "isSinglePart": True,
    })
    api.add("POST", f"/api/uploads/{UP}/parts", 200, {"ok": True})
    api.add("POST", f"/api/uploads/{UP}/complete", 200,
            {"document": {"id": "doc-2", "fileName": "small.pdf"}})

    from fz_cli.client import FZClient

    upload_file(FZClient("http://ev.test"), PROJ, f)
    assert s3[0].headers["content-type"] == "application/pdf"


def test_s3_failure_aborts_upload(api, tmp_path, monkeypatch):
    monkeypatch.setattr("fz_cli.upload.time.sleep", lambda s: None)

    def failing_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="S3 exploded")

    real_client = httpx.Client

    def patched_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(failing_handler)
        return real_client(**{k: v for k, v in kwargs.items() if k in {"transport", "limits", "timeout"}})

    monkeypatch.setattr("fz_cli.upload.httpx.Client", patched_client)

    f = tmp_path / "doomed.pdf"
    f.write_bytes(b"x" * 10)

    api.add("POST", f"/api/projects/{PROJ}/uploads/init", 201, {
        "uploadId": UP,
        "partSizeBytes": 1024,
        "totalParts": 1,
        "presignedUrls": [{"partNumber": 1, "url": "https://s3.test/p1"}],
        "isSinglePart": True,
    })
    api.add("DELETE", f"/api/uploads/{UP}", 204)

    from fz_cli.client import FZClient

    with pytest.raises(RuntimeError, match="Upload failed"):
        upload_file(FZClient("http://ev.test"), PROJ, f, max_retries=2)

    # The engine must clean up the abandoned upload.
    assert any(r.method == "DELETE" and r.path == f"/api/uploads/{UP}" for r in api.requests)
