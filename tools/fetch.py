"""Download prediction files, but only from hosts we trust to serve user uploads."""
from __future__ import annotations

import re
import socket
import urllib.error
import urllib.request
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from scorer.score import MAX_BYTES, SubmissionError

ALLOWED_URLS = [
    # Drag-and-drop attachments on GitHub issues (current and legacy formats).
    re.compile(r"^https://github\.com/user-attachments/files/\d+/[^/?#\s]+$"),
    re.compile(r"^https://github\.com/[\w.-]+/[\w.-]+/files/\d+/[^/?#\s]+$"),
    # Files on the Hugging Face Hub (model, dataset or space repos).
    re.compile(r"^https://huggingface\.co/(?:datasets/|spaces/)?[\w.-]+/[\w.-]+/resolve/[\w.%-]+/[^?#\s]+$"),
    # Raw GitHub gists.
    re.compile(r"^https://gist\.githubusercontent\.com/[\w-]+/[0-9a-f]+/raw/(?:[0-9a-f]+/)?[^?#\s]+$"),
]
URL_RE = re.compile(r"https://[^\s<>()\[\]\"'`]+")
BLOB_RE = re.compile(
    r"^(https://huggingface\.co/(?:datasets/|spaces/)?[\w.-]+/[\w.-]+)/blob/([\w.%-]+/.+)$"
)


def rewrite_url(url: str) -> str:
    """Normalize common Hugging Face link forms to a downloadable `/resolve/` URL."""
    url = (url or "").rstrip(").,;\"'")
    m = BLOB_RE.match(url)
    if m:
        url = f"{m.group(1)}/resolve/{m.group(2)}"
    parts = urlsplit(url)
    if parts.query:
        query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "download"]
        url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
    return url


def is_allowed(url: str) -> bool:
    return any(p.match(url) for p in ALLOWED_URLS)


def find_url(text: str) -> str:
    """Return the first allowed URL in free text (e.g. a markdown attachment link)."""
    urls = URL_RE.findall(text or "")
    for raw in urls:
        url = rewrite_url(raw)
        if is_allowed(url):
            return url
    if urls:
        raise SubmissionError(
            "The predictions link must be a file attached to the issue (drag the CSV into the box), "
            "a Hugging Face `/resolve/` or `/blob/` URL, or a raw gist URL."
        )
    raise SubmissionError("No predictions file found. Drag your CSV into the *Predictions CSV* box.")


def _download_error(exc: BaseException) -> SubmissionError:
    """Turn a network failure into a submitter-facing message."""
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code in (401, 403):
            return SubmissionError(
                f"Could not download the predictions file (HTTP {exc.code}). "
                "The file may be in a gated or private repository; make it public, "
                "or attach the CSV to the issue instead."
            )
        if exc.code == 404:
            return SubmissionError(
                "Could not download the predictions file (HTTP 404). "
                "Check that the link still points at the file."
            )
        if exc.code == 429 or exc.code >= 500:
            return SubmissionError(
                f"Could not download the predictions file (HTTP {exc.code}). "
                "This is probably temporary and your file does not need changing; "
                "a maintainer can re-run the job, or you can edit the issue to try again."
            )
        return SubmissionError(f"Could not download the predictions file (HTTP {exc.code}).")
    if isinstance(exc, (TimeoutError, socket.timeout, urllib.error.URLError, ConnectionError, OSError)):
        return SubmissionError(
            "Could not download the predictions file (connection failed or timed out). "
            "This is probably temporary and your file does not need changing; "
            "a maintainer can re-run the job, or you can edit the issue to try again."
        )
    return SubmissionError(f"Could not download the predictions file ({exc}).")


def download(url: str) -> bytes:
    if not is_allowed(url):
        raise SubmissionError("That predictions URL is not on an allowed host.")
    req = urllib.request.Request(url, headers={"User-Agent": "YigzinBench-scorer"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read(MAX_BYTES + 1)
    except Exception as exc:  # network errors are reported to the submitter
        raise _download_error(exc) from None
    if len(data) > MAX_BYTES:
        raise SubmissionError(f"The file is larger than {MAX_BYTES // (1024 * 1024)} MB.")
    return data
