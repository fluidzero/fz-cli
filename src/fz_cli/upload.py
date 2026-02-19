"""Multipart upload engine using the 4-step presigned URL flow."""

from __future__ import annotations

import base64
import hashlib
import os
import random
import signal
import sys
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import click
import httpx
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TransferSpeedColumn

from .client import FZClient
from .constants import UPLOAD_CONCURRENCY, UPLOAD_DIRECT_THRESHOLD, UPLOAD_RETRY_ATTEMPTS


class _UploadAborted(Exception):
    """Raised when the user cancels an upload with Ctrl+C."""


def _guess_mime(path: Path) -> str:
    ext = path.suffix.lower()
    mime_map = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".tiff": "image/tiff",
        ".tif": "image/tiff",
        ".doc": "application/msword",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xls": "application/vnd.ms-excel",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".csv": "text/csv",
        ".txt": "text/plain",
    }
    return mime_map.get(ext, "application/octet-stream")


def _retry_delay(attempt: int) -> float:
    """Exponential backoff with jitter, aligned with web UI base delays."""
    base_delays = [1, 2, 4]
    base = base_delays[attempt] if attempt < len(base_delays) else base_delays[-1] * (2 ** (attempt - len(base_delays) + 1))
    return min(base + random.random(), 30.0)


def _part_timeout(size_bytes: int) -> float:
    """Size-based timeout instead of a flat 300s."""
    size_mb = size_bytes / (1024 * 1024)
    return max(60.0, size_mb * 30.0)


def _content_md5(data: bytes) -> str:
    """Base64-encoded MD5 digest for the S3 Content-MD5 header."""
    return base64.b64encode(hashlib.md5(data).digest()).decode()


def _upload_part(
    url: str,
    file_path: Path,
    offset: int,
    size: int,
    part_number: int,
    is_single_part: bool,
    mime_type: str,
    max_retries: int,
    client: httpx.Client,
    aborted: threading.Event,
) -> tuple[int, str, int]:
    """Upload a single part to S3 via presigned URL. Returns (part_number, etag, size)."""
    for attempt in range(max_retries):
        if aborted.is_set():
            raise _UploadAborted(f"Part {part_number} cancelled")

        try:
            with open(file_path, "rb") as f:
                f.seek(offset)
                chunk = f.read(size)

            headers = {"Content-MD5": _content_md5(chunk)}
            if is_single_part:
                headers["Content-Type"] = mime_type

            resp = client.put(
                url,
                content=chunk,
                headers=headers,
                timeout=_part_timeout(size),
            )
            resp.raise_for_status()

            etag = resp.headers.get("etag", "").strip('"')
            return part_number, etag, len(chunk)

        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:500] if exc.response else ""
            msg = f"Part {part_number}: HTTP {exc.response.status_code} — {body}"
            if attempt == max_retries - 1:
                raise RuntimeError(msg) from exc
            click.echo(f"  Retry {attempt + 1}/{max_retries} for part {part_number} (HTTP {exc.response.status_code})", err=True)

        except httpx.TimeoutException as exc:
            msg = f"Part {part_number}: upload timed out after {_part_timeout(size):.0f}s"
            if attempt == max_retries - 1:
                raise RuntimeError(msg) from exc
            click.echo(f"  Retry {attempt + 1}/{max_retries} for part {part_number} (timeout)", err=True)

        except _UploadAborted:
            raise

        except Exception as exc:
            msg = f"Part {part_number}: {type(exc).__name__}: {exc}"
            if attempt == max_retries - 1:
                raise RuntimeError(msg) from exc
            click.echo(f"  Retry {attempt + 1}/{max_retries} for part {part_number} ({type(exc).__name__})", err=True)

        time.sleep(_retry_delay(attempt))

    raise RuntimeError(f"Failed to upload part {part_number} after {max_retries} retries")


def _report_part_bg(
    fz: FZClient,
    upload_id: str,
    part_number: int,
    etag: str,
    size: int,
    aborted: threading.Event,
) -> None:
    """Report a completed part to the backend (non-blocking, non-fatal)."""
    if aborted.is_set():
        return
    try:
        fz.post(
            f"/api/uploads/{upload_id}/parts",
            json={
                "partNumber": part_number,
                "etag": etag,
                "sizeBytes": size,
            },
        )
    except Exception as exc:
        click.echo(f"  Warning: failed to report part {part_number}: {exc}", err=True)


def upload_file(
    fz: FZClient,
    project_id: str,
    file_path: Path,
    *,
    wait: bool = False,
    resume: bool = False,
    concurrency: int = UPLOAD_CONCURRENCY,
    max_retries: int = UPLOAD_RETRY_ATTEMPTS,
    progress: Progress | None = None,
) -> dict[str, Any]:
    """Upload a single file using the multipart upload flow.

    Returns the document dict from the API.
    """
    file_size = file_path.stat().st_size
    file_name = file_path.name
    mime_type = _guess_mime(file_path)

    # Step 1: Init upload
    init_resp = fz.post(
        f"/api/projects/{project_id}/uploads/init",
        json={
            "fileName": file_name,
            "fileSizeBytes": file_size,
            "mimeType": mime_type,
            "sourceType": "cli",
        },
    )
    init_data = init_resp.json()
    upload_id = init_data["uploadId"]
    part_size = init_data["partSizeBytes"]
    total_parts = init_data["totalParts"]
    presigned_urls = init_data["presignedUrls"]
    is_single_part = init_data["isSinglePart"]

    # If resuming, check for already-uploaded parts
    if resume and not is_single_part:
        status_resp = fz.get(f"/api/uploads/{upload_id}")
        status_data = status_resp.json()
        already_uploaded = status_data.get("partsUploaded", 0)
        if already_uploaded > 0:
            # Get fresh URLs for remaining parts
            resume_resp = fz.post(f"/api/uploads/{upload_id}/resume")
            resume_data = resume_resp.json()
            presigned_urls = resume_data["presignedUrls"]
            click.echo(f"  Resuming: {already_uploaded}/{total_parts} parts already uploaded", err=True)

    # Create progress task if we have a progress display
    task_id = None
    if progress is not None:
        task_id = progress.add_task(f"  {file_name}", total=file_size)

    # Step 2: Upload parts in parallel
    parts_to_upload = []
    for url_info in presigned_urls:
        pn = url_info["partNumber"]
        offset = (pn - 1) * part_size
        size = min(part_size, file_size - offset)
        parts_to_upload.append((url_info["url"], offset, size, pn))

    uploaded_parts: list[tuple[int, str, int]] = []
    aborted = threading.Event()
    first_error: Exception | None = None

    # Graceful Ctrl+C handling
    original_sigint = signal.getsignal(signal.SIGINT)
    ctrl_c_count = 0

    def _sigint_handler(signum: int, frame: Any) -> None:
        nonlocal ctrl_c_count
        ctrl_c_count += 1
        if ctrl_c_count == 1:
            click.echo("\n  Upload cancelling… (press Ctrl+C again to force exit)", err=True)
            aborted.set()
        else:
            signal.signal(signal.SIGINT, original_sigint)
            os.kill(os.getpid(), signal.SIGINT)

    signal.signal(signal.SIGINT, _sigint_handler)

    try:
        limits = httpx.Limits(
            max_connections=concurrency + 2,
            max_keepalive_connections=concurrency,
        )
        with (
            httpx.Client(limits=limits) as s3_client,
            ThreadPoolExecutor(max_workers=concurrency) as upload_pool,
            ThreadPoolExecutor(max_workers=2) as report_pool,
        ):
            futures: dict[Future[tuple[int, str, int]], int] = {
                upload_pool.submit(
                    _upload_part,
                    url,
                    file_path,
                    offset,
                    size,
                    pn,
                    is_single_part,
                    mime_type,
                    max_retries,
                    s3_client,
                    aborted,
                ): pn
                for url, offset, size, pn in parts_to_upload
            }

            report_futures: list[Future[None]] = []

            for future in as_completed(futures):
                if aborted.is_set() and first_error is None:
                    first_error = _UploadAborted("Upload cancelled by user")
                    break

                try:
                    pn, etag, size = future.result()
                except _UploadAborted:
                    first_error = _UploadAborted("Upload cancelled by user")
                    aborted.set()
                    break
                except Exception as exc:
                    first_error = exc
                    aborted.set()
                    # Cancel pending futures
                    for f in futures:
                        f.cancel()
                    break

                uploaded_parts.append((pn, etag, size))

                # Step 3: Report each part (non-blocking)
                rf = report_pool.submit(
                    _report_part_bg, fz, upload_id, pn, etag, size, aborted,
                )
                report_futures.append(rf)

                if progress is not None and task_id is not None:
                    progress.advance(task_id, size)

            # Wait for all part reports to finish
            for rf in report_futures:
                try:
                    rf.result(timeout=30)
                except Exception:
                    pass

        # Handle abort / error
        if first_error is not None:
            try:
                fz.delete(f"/api/uploads/{upload_id}")
            except Exception:
                pass
            if isinstance(first_error, _UploadAborted):
                raise first_error
            raise RuntimeError(f"Upload failed: {first_error}") from first_error

    finally:
        signal.signal(signal.SIGINT, original_sigint)

    # Step 4: Complete upload
    complete_resp = fz.post(f"/api/uploads/{upload_id}/complete")
    complete_data = complete_resp.json()
    document = complete_data.get("document", {})
    doc_id = document.get("id", upload_id)

    # Optionally wait for processing
    if wait:
        document = _wait_for_ready(fz, doc_id, progress=progress, file_name=file_name)

    return document


def _wait_for_ready(
    fz: FZClient,
    doc_id: str,
    *,
    progress: Progress | None = None,
    file_name: str = "",
    poll_interval: float = 2.0,
    timeout: float = 600.0,
) -> dict[str, Any]:
    """Poll until document status is ready or failed."""
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        resp = fz.get(f"/api/documents/{doc_id}")
        doc = resp.json()
        status = doc.get("status", "")

        if status == "ready":
            elapsed = time.monotonic() - start
            if progress is None:
                click.echo(f"  Processing... ready ({elapsed:.0f}s)", err=True)
            return doc
        elif status == "failed":
            msg = doc.get("errorMessage", "unknown error")
            click.echo(f"  Processing... failed: {msg}", err=True)
            return doc

        time.sleep(poll_interval)

    click.echo(f"  Processing... timed out after {timeout:.0f}s", err=True)
    return {"id": doc_id, "status": "timeout"}


def upload_files(
    fz: FZClient,
    project_id: str,
    file_paths: list[Path],
    *,
    wait: bool = False,
    resume: bool = False,
    concurrency: int = UPLOAD_CONCURRENCY,
    max_retries: int = UPLOAD_RETRY_ATTEMPTS,
) -> list[dict[str, Any]]:
    """Upload multiple files with a rich progress display."""
    documents = []
    total_bytes = sum(p.stat().st_size for p in file_paths)
    total_files = len(file_paths)

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TransferSpeedColumn(),
        transient=True,
    ) as progress:
        for fp in file_paths:
            click.echo(f"Uploading {fp.name} ({_human_size(fp.stat().st_size)})", err=True)
            try:
                doc = upload_file(
                    fz,
                    project_id,
                    fp,
                    wait=wait,
                    resume=resume,
                    concurrency=concurrency,
                    max_retries=max_retries,
                    progress=progress,
                )
                documents.append(doc)
            except _UploadAborted:
                click.echo("Upload cancelled by user.", err=True)
                break
            except Exception as exc:
                click.echo(f"Error uploading {fp.name}: {exc}", err=True)
                break

    total_size_str = _human_size(total_bytes)
    if len(documents) == total_files:
        click.echo(f"\nUploaded {len(documents)} document(s) ({total_size_str} total)", err=True)
    else:
        click.echo(f"\nUploaded {len(documents)} of {total_files} document(s)", err=True)
    return documents


def _human_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"
