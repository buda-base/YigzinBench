"""Download prediction files, but only from hosts we trust to serve user uploads."""
from __future__ import annotations

import re
import urllib.request

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


def is_allowed(url: str) -> bool:
    return any(p.match(url) for p in ALLOWED_URLS)


def find_url(text: str) -> str:
    """Return the first allowed URL in free text (e.g. a markdown attachment link)."""
    urls = URL_RE.findall(text or "")
    for url in urls:
        if is_allowed(url):
            return url
    if urls:
        raise SubmissionError(
            "The predictions link must be a file attached to the issue (drag the CSV into the box), "
            "a Hugging Face `/resolve/` URL, or a raw gist URL."
        )
    raise SubmissionError("No predictions file found. Drag your CSV into the *Predictions CSV* box.")


def download(url: str) -> bytes:
    if not is_allowed(url):
        raise SubmissionError("That predictions URL is not on an allowed host.")
    req = urllib.request.Request(url, headers={"User-Agent": "YigzinBench-scorer"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read(MAX_BYTES + 1)
    except Exception as exc:  # network errors are reported to the submitter
        raise SubmissionError(f"Could not download the predictions file ({exc}).") from None
    if len(data) > MAX_BYTES:
        raise SubmissionError(f"The file is larger than {MAX_BYTES // (1024 * 1024)} MB.")
    return data
