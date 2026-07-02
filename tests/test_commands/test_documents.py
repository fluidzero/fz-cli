"""Tests for `fz documents` (except the multipart upload engine — see test_upload_engine)."""

from __future__ import annotations


DOC = "66666666-6666-6666-6666-666666666666"
PROJ = "22222222-2222-2222-2222-222222222222"
DOCUMENT = {
    "id": DOC,
    "fileName": "spec.pdf",
    "fileType": "pdf",
    "fileSizeBytes": 1234,
    "status": "ready",
    "createdAt": "2026-07-01",
}


def test_list(invoke, api):
    api.add("GET", f"/api/projects/{PROJ}/documents", 200, [DOCUMENT])
    result = invoke(["-p", PROJ, "documents", "list"])
    assert result.exit_code == 0, result.output
    assert "spec.pdf" in result.output


def test_get(invoke, api):
    api.add("GET", f"/api/documents/{DOC}", 200, DOCUMENT)
    result = invoke(["documents", "get", DOC])
    assert result.exit_code == 0
    assert "spec.pdf" in result.output


def test_delete_confirm(invoke, api):
    api.add("DELETE", f"/api/documents/{DOC}", 204)
    result = invoke(["documents", "delete", DOC, "--confirm"])
    assert result.exit_code == 0
    assert api.last.method == "DELETE"


def test_delete_conflict_active_run(invoke, api):
    api.add("DELETE", f"/api/documents/{DOC}", 409, {"detail": "referenced by an active run"})
    result = invoke(["documents", "delete", DOC, "--confirm"])
    assert result.exit_code == 5
    assert "active run" in result.output


def test_download(invoke, api, tmp_path, monkeypatch):
    api.add("GET", f"/api/documents/{DOC}", 200, DOCUMENT)
    api.add("GET", f"/api/documents/{DOC}/preview", 200,
            {"url": "https://s3.test/presigned", "expiresAt": "3600s"})

    class FakeStream:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def iter_bytes(self):
            yield b"%PDF-1.4 content"

    class FakeRaw:
        def stream(self, method, url):
            assert url == "https://s3.test/presigned"
            return FakeStream()

    monkeypatch.setattr("fz_cli.client.FZClient.raw_client", lambda self: FakeRaw())
    result = invoke(["documents", "download", DOC, "-o", str(tmp_path)])
    assert result.exit_code == 0, result.output
    saved = tmp_path / "spec.pdf"
    assert saved.read_bytes() == b"%PDF-1.4 content"


def test_download_url_only(invoke, api):
    api.add("GET", f"/api/documents/{DOC}", 200, DOCUMENT)
    api.add("GET", f"/api/documents/{DOC}/preview", 200, {"url": "https://s3.test/u"})
    result = invoke(["documents", "download", DOC, "--url-only"])
    assert result.exit_code == 0
    assert "https://s3.test/u" in result.output


def test_replace(invoke, api, tmp_path):
    f = tmp_path / "v2.pdf"
    f.write_bytes(b"%PDF v2")
    api.add("POST", f"/api/documents/{DOC}/versions", 201, DOCUMENT)
    result = invoke(["documents", "replace", DOC, str(f)])
    assert result.exit_code == 0, result.output
    assert api.last.files is not None
    fname, content, mime = api.last.files["file"]
    assert fname == "v2.pdf" and content == b"%PDF v2" and mime == "application/pdf"


def test_sheets(invoke, api):
    api.add("GET", f"/api/documents/{DOC}/sheets", 200,
            {"sheets": [{"name": "Sheet1", "dimensions": "A1:C9"}], "totalSheetCount": 1})
    result = invoke(["-o", "json", "documents", "sheets", DOC])
    assert result.exit_code == 0
    assert "Sheet1" in result.output


def test_status_single_document(invoke, api):
    api.add("GET", f"/api/documents/{DOC}/status", 200, {"id": DOC, "status": "processing"})
    result = invoke(["documents", "status", "--document", DOC])
    assert result.exit_code == 0
    assert "processing" in result.output


def test_status_project_batch(invoke, api):
    api.add("GET", f"/api/projects/{PROJ}/documents/status", 200,
            {"documents": [{"id": DOC, "status": "ready"}]})
    result = invoke(["-p", PROJ, "documents", "status"])
    assert result.exit_code == 0


def test_no_project_errors(invoke, api):
    result = invoke(["documents", "list"])
    assert result.exit_code == 1
    assert "No project specified" in result.output
