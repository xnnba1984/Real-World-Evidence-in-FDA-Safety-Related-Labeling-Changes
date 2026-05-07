#!/usr/bin/env python3

import argparse
import csv
import hashlib
import json
import re
import ssl
import threading
import time
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urldefrag, urlparse, urlunparse
from urllib.request import Request, urlopen

import lxml.html
from lxml import etree
from pypdf import PdfReader


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

REQUEST_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

ACCESS_RESTRICTED_HOSTS = {"login.microsoftonline.com"}

OFFICE_CONTENT_TYPE_TO_EXTENSION = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-excel": ".xls",
    "application/rtf": ".rtf",
    "text/rtf": ".rtf",
}

FDA_BOT_RE = re.compile(
    r'public_salt = "([^"]+)";.*?candidates = "([^"]+)"\.split',
    re.S,
)

FDA_GATE_COOKIE_CACHE: Dict[str, str] = {}
FDA_GATE_COOKIE_LOCK = threading.Lock()

EVENT_MAP_COLUMNS = [
    "event_id",
    "source_row_number",
    "Drug Name",
    "Application Number",
    "event_header",
    "event_date_iso",
    "doc_order_on_event",
    "doc_id",
    "source_url",
]

DOC_COLUMNS = [
    "doc_id",
    "normalized_source_url",
    "source_domain",
    "url_type_guess",
    "shared_event_count",
    "linked_event_count",
    "download_status",
    "download_http_status",
    "content_type",
    "final_url",
    "raw_file_path",
    "raw_file_size_bytes",
    "raw_sha1",
    "text_extract_status",
    "text_file_path",
    "text_char_count",
    "text_line_count",
    "text_sha1",
    "text_preview",
    "download_error",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_url(url: str) -> str:
    cleaned = normalize_space(url)
    cleaned = cleaned.strip("|;,")
    cleaned = urldefrag(cleaned)[0]
    parsed = urlparse(cleaned)
    if parsed.netloc.endswith(")"):
        cleaned = cleaned[:-1]
        parsed = urlparse(cleaned)
    if parsed.netloc == "www.fda":
        cleaned = cleaned.replace("https://www.fda/gov/", "https://www.fda.gov/")
        cleaned = cleaned.replace("http://www.fda/gov/", "https://www.fda.gov/")
        parsed = urlparse(cleaned)
    if parsed.netloc == "womansmentalhealth.org":
        cleaned = cleaned.replace("https://womansmentalhealth.org/", "https://www.womensmentalhealth.org/")
        cleaned = cleaned.replace("http://womansmentalhealth.org/", "https://www.womensmentalhealth.org/")
        parsed = urlparse(cleaned)
    if parsed.scheme == "http":
        cleaned = urlunparse(parsed._replace(scheme="https"))
        parsed = urlparse(cleaned)
    if parsed.netloc.lower() == "www.accessdata.fda.gov" and parsed.path.lower().endswith(".pdf"):
        cleaned = cleaned.replace(", ", ",").replace("; ", ";").replace(" ", "")
    return cleaned


def sha1_text(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


def guess_url_type(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.lower()
    if path.endswith(".pdf"):
        return "pdf"
    if path.endswith((".html", ".htm")):
        return "html"
    if path.endswith((".txt", ".csv", ".xml", ".json")):
        return "text"
    if path.endswith((".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip", ".rtf")):
        return "binary_other"
    if "download" in path:
        return "download"
    return "other"


def split_event_links(value: str) -> List[str]:
    return [normalize_url(part) for part in str(value or "").split(" | ") if normalize_url(part)]


def write_csv(path: Path, fieldnames: Sequence[str], rows: Iterable[Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def read_event_rows(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return [{key: value or "" for key, value in row.items()} for row in reader]


def read_doc_id_filter(path: Path) -> List[str]:
    with path.open(encoding="utf-8") as handle:
        return [normalize_space(line) for line in handle if normalize_space(line)]


def request_open(url: str, timeout_s: int, ssl_context: ssl.SSLContext):
    request = Request(url, headers=REQUEST_HEADERS)
    return urlopen(request, timeout=timeout_s, context=ssl_context)


def safe_file_name(doc_id: str, extension: str) -> str:
    suffix = extension if extension.startswith(".") else f".{extension}"
    return f"{doc_id}{suffix}"


def short_preview(text: str, max_chars: int = 500) -> str:
    value = normalize_space(text)
    return value[:max_chars]


def extract_pdf_text(pdf_path: Path) -> str:
    try:
        reader = PdfReader(str(pdf_path))
    except Exception:
        return ""
    chunks: List[str] = []
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        if text:
            chunks.append(text)
    return "\n".join(chunks).strip()


def extract_html_text(html_bytes: bytes) -> str:
    try:
        document = lxml.html.fromstring(html_bytes)
    except Exception:
        return ""
    for node in document.xpath("//script|//style|//noscript"):
        parent = node.getparent()
        if parent is not None:
            parent.remove(node)
    return normalize_space(document.text_content())


def extract_docx_text(docx_path: Path) -> str:
    try:
        with zipfile.ZipFile(docx_path) as archive:
            xml_bytes = archive.read("word/document.xml")
    except Exception:
        return ""
    try:
        root = etree.fromstring(xml_bytes)
    except Exception:
        return ""
    text_nodes = root.xpath(".//w:t", namespaces={"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"})
    return normalize_space(" ".join(node.text or "" for node in text_nodes))


def compute_file_sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class DownloadResult:
    download_status: str
    http_status: str
    content_type: str
    final_url: str
    raw_file_path: str
    raw_file_size_bytes: str
    raw_sha1: str
    download_error: str


@dataclass
class ExtractResult:
    text_extract_status: str
    text_file_path: str
    text_char_count: str
    text_line_count: str
    text_sha1: str
    text_preview: str


@dataclass
class FetchResult:
    ok: bool
    http_status: str
    content_type: str
    final_url: str
    body: bytes
    error: str


@dataclass
class PayloadValidation:
    status: str
    error: str
    extension: str


@dataclass
class ProcessResult:
    before_download: str
    before_extract: str
    doc: Dict[str, str]


def fetch_url(
    url: str,
    timeout_s: int,
    ssl_context: ssl.SSLContext,
    extra_headers: Optional[Dict[str, str]] = None,
) -> FetchResult:
    headers = dict(REQUEST_HEADERS)
    if extra_headers:
        headers.update(extra_headers)
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=timeout_s, context=ssl_context) as response:
            return FetchResult(
                ok=True,
                http_status=str(getattr(response, "status", "") or ""),
                content_type=response.headers.get("Content-Type", ""),
                final_url=response.geturl(),
                body=response.read(),
                error="",
            )
    except HTTPError as exc:
        return FetchResult(
            ok=False,
            http_status=str(exc.code),
            content_type=exc.headers.get("Content-Type", ""),
            final_url=getattr(exc, "url", url),
            body=exc.read(),
            error=normalize_space(str(exc)),
        )
    except URLError as exc:
        return FetchResult(
            ok=False,
            http_status="",
            content_type="",
            final_url=url,
            body=b"",
            error=normalize_space(str(exc)),
        )
    except Exception as exc:
        return FetchResult(
            ok=False,
            http_status="",
            content_type="",
            final_url=url,
            body=b"",
            error=normalize_space(str(exc)),
        )


def parse_fda_bot_cookie_header(body: bytes) -> Optional[str]:
    text = body.decode("utf-8", errors="replace")
    if "I am not a bot" not in text or "automated request" not in text:
        return None
    match = FDA_BOT_RE.search(text)
    if not match:
        return None
    public_salt = match.group(1)
    candidates = match.group(2).split("/")
    values = [
        hashlib.sha256(f"{public_salt}{candidate}".encode("utf-8")).hexdigest().upper()
        for candidate in candidates
    ]
    return f"authorization_1={values[0]}; authorization_2={values[1]}"


def content_type_starts_with(content_type: str, prefix: str) -> bool:
    return content_type.lower().startswith(prefix.lower())


def is_pdf_body(body: bytes) -> bool:
    return body.startswith(b"%PDF")


def decode_html_body(body: bytes) -> str:
    return body.decode("utf-8", errors="replace")


def expected_binary_document(url_type_guess: str) -> bool:
    return url_type_guess in {"pdf", "download", "binary_other"}


def extension_from_content(
    url_type_guess: str,
    source_url: str,
    final_url: str,
    content_type: str,
    body: bytes,
) -> str:
    final_path = urlparse(final_url or source_url).path.lower()
    extension = Path(final_path).suffix
    if extension:
        return extension
    lowered_type = content_type.lower()
    if is_pdf_body(body) or "pdf" in lowered_type:
        return ".pdf"
    for mime, candidate_extension in OFFICE_CONTENT_TYPE_TO_EXTENSION.items():
        if mime in lowered_type:
            return candidate_extension
    if "html" in lowered_type:
        return ".html"
    if "text/plain" in lowered_type:
        return ".txt"
    if "json" in lowered_type:
        return ".json"
    if "xml" in lowered_type:
        return ".xml"
    return ".bin"


def validate_payload(
    source_url: str,
    url_type_guess: str,
    content_type: str,
    final_url: str,
    body: bytes,
) -> PayloadValidation:
    final_host = urlparse(final_url).netloc.lower()
    source_host = urlparse(source_url).netloc.lower()

    if source_host in {"fda-my.sharepoint.com", "sharepoint.fda.gov", "intranetapps.fda.gov"}:
        return PayloadValidation(status="access_restricted", error="Restricted FDA intranet/sharepoint document", extension="")

    if not body:
        return PayloadValidation(status="error", error="Downloaded empty response body", extension="")

    normalized_final_url = normalize_url(final_url or source_url)
    lower_content_type = content_type.lower()
    html_text = ""
    normalized_text = ""

    if "html" in lower_content_type or Path(urlparse(normalized_final_url).path).suffix.lower() in {".html", ".htm", ".cfm", ".aspx"}:
        html_text = decode_html_body(body)
        normalized_text = extract_html_text(body)
        lower_html = html_text.lower()
        lower_text = normalized_text.lower()

        if "i am not a bot" in lower_html and "automated request" in lower_html:
            return PayloadValidation(status="error", error="FDA bot challenge page returned instead of document", extension="")

        if "page not found | fda" in lower_html:
            return PayloadValidation(status="error", error="FDA page not found", extension="")

        if final_host in ACCESS_RESTRICTED_HOSTS:
            return PayloadValidation(status="access_restricted", error="Access restricted by Microsoft login", extension="")

        if source_host.endswith("sharepoint.com"):
            return PayloadValidation(status="access_restricted", error="SharePoint document requires authenticated access", extension="")

        if "data-ubc-ajax-url=\"!main\"" in lower_html and "ubc-panel-container" in lower_html:
            return PayloadValidation(status="error", error="HTML application shell returned instead of document content", extension="")

        if lower_text in {"redirecting", "vrg rems", "welcome to lwc communities!"}:
            return PayloadValidation(status="error", error=f"Thin HTML redirect page returned: {normalized_text or 'empty html'}", extension="")

        if expected_binary_document(url_type_guess):
            return PayloadValidation(
                status="error",
                error=f"Expected binary document but received HTML from {normalize_space(final_url)}",
                extension="",
            )

        return PayloadValidation(status="valid", error="", extension=extension_from_content(url_type_guess, source_url, final_url, content_type, body))

    if url_type_guess == "pdf" and not is_pdf_body(body) and "pdf" not in lower_content_type:
        return PayloadValidation(
            status="error",
            error=f"Expected PDF but received {content_type or 'unknown content type'}",
            extension="",
        )

    return PayloadValidation(status="valid", error="", extension=extension_from_content(url_type_guess, source_url, final_url, content_type, body))


def local_raw_file_is_valid(doc: Dict[str, str], raw_path: Path) -> bool:
    try:
        body = raw_path.read_bytes()
    except Exception:
        return False
    validation = validate_payload(
        source_url=doc["normalized_source_url"],
        url_type_guess=doc["url_type_guess"],
        content_type=doc.get("content_type", ""),
        final_url=doc.get("final_url", "") or doc["normalized_source_url"],
        body=body,
    )
    return validation.status == "valid"


def clear_doc_artifacts(doc: Dict[str, str]) -> None:
    for field in ("raw_file_path", "text_file_path"):
        path = Path(doc[field]) if doc.get(field) else None
        if path and path.exists():
            path.unlink()
    for field in (
        "download_status",
        "download_http_status",
        "content_type",
        "final_url",
        "raw_file_path",
        "raw_file_size_bytes",
        "raw_sha1",
        "text_extract_status",
        "text_file_path",
        "text_char_count",
        "text_line_count",
        "text_sha1",
        "text_preview",
        "download_error",
    ):
        doc[field] = ""
    doc["download_status"] = "pending"
    doc["text_extract_status"] = "pending"


def download_document(
    source_url: str,
    url_type_guess: str,
    doc_id: str,
    raw_root: Path,
    timeout_s: int,
    insecure_ssl: bool,
) -> DownloadResult:
    ssl_context = ssl._create_unverified_context() if insecure_ssl else ssl.create_default_context()
    raw_dir = raw_root / doc_id[:2]
    raw_dir.mkdir(parents=True, exist_ok=True)

    candidate_urls = [source_url]
    parsed = urlparse(source_url)
    if parsed.scheme == "http":
        https_url = urlunparse(parsed._replace(scheme="https"))
        if https_url not in candidate_urls:
            candidate_urls.append(https_url)

    last_failure = DownloadResult(
        download_status="error",
        http_status="",
        content_type="",
        final_url=source_url,
        raw_file_path="",
        raw_file_size_bytes="",
        raw_sha1="",
        download_error="No candidate URL produced a valid document",
    )

    for candidate_url in candidate_urls:
        candidate_host = urlparse(candidate_url).netloc.lower()
        with FDA_GATE_COOKIE_LOCK:
            cached_cookie = FDA_GATE_COOKIE_CACHE.get(candidate_host)
        response = fetch_url(
            candidate_url,
            timeout_s,
            ssl_context,
            extra_headers={"Cookie": cached_cookie} if cached_cookie else None,
        )
        if response.http_status == "401":
            cookie_header = parse_fda_bot_cookie_header(response.body)
            if cookie_header:
                with FDA_GATE_COOKIE_LOCK:
                    FDA_GATE_COOKIE_CACHE[candidate_host] = cookie_header
                response = fetch_url(
                    candidate_url,
                    timeout_s,
                    ssl_context,
                    extra_headers={"Cookie": cookie_header},
                )

        validation = validate_payload(
            source_url=candidate_url,
            url_type_guess=url_type_guess,
            content_type=response.content_type,
            final_url=response.final_url,
            body=response.body,
        )

        if not response.ok or validation.status != "valid":
            status = validation.status if validation.status != "valid" else "error"
            error = validation.error or response.error or "Download failed"
            last_failure = DownloadResult(
                download_status=status,
                http_status=response.http_status,
                content_type=response.content_type,
                final_url=response.final_url,
                raw_file_path="",
                raw_file_size_bytes="",
                raw_sha1="",
                download_error=error,
            )
            if candidate_url != candidate_urls[-1]:
                continue
            return last_failure

        extension = validation.extension
        body = response.body
        final_url = response.final_url
        content_type = response.content_type
        http_status = response.http_status
        break
    else:
        return last_failure

    raw_path = raw_dir / safe_file_name(doc_id, extension)
    raw_path.write_bytes(body)

    return DownloadResult(
        download_status="downloaded",
        http_status=http_status,
        content_type=content_type,
        final_url=final_url,
        raw_file_path=str(raw_path),
        raw_file_size_bytes=str(raw_path.stat().st_size),
        raw_sha1=compute_file_sha1(raw_path),
        download_error="",
    )


def extract_text_file(raw_path: Path, content_type: str, text_root: Path, doc_id: str) -> ExtractResult:
    text_dir = text_root / doc_id[:2]
    text_dir.mkdir(parents=True, exist_ok=True)
    text_path = text_dir / safe_file_name(doc_id, ".txt")

    extension = raw_path.suffix.lower()
    text = ""
    status = "unsupported"
    if extension == ".pdf" or "pdf" in content_type.lower():
        text = extract_pdf_text(raw_path)
        status = "extracted" if text else "empty"
    elif extension == ".docx" or "wordprocessingml.document" in content_type.lower():
        text = extract_docx_text(raw_path)
        status = "extracted" if text else "empty"
    elif extension in {".html", ".htm"} or "html" in content_type.lower():
        text = extract_html_text(raw_path.read_bytes())
        status = "extracted" if text else "empty"
    elif extension in {".txt", ".csv", ".json", ".xml"} or "text/" in content_type.lower():
        text = raw_path.read_text(encoding="utf-8", errors="ignore")
        status = "extracted" if normalize_space(text) else "empty"

    if status == "unsupported":
        return ExtractResult(
            text_extract_status=status,
            text_file_path="",
            text_char_count="",
            text_line_count="",
            text_sha1="",
            text_preview="",
        )

    normalized = text.strip()
    text_path.write_text(normalized, encoding="utf-8")
    return ExtractResult(
        text_extract_status=status,
        text_file_path=str(text_path),
        text_char_count=str(len(normalized)),
        text_line_count=str(normalized.count("\n") + 1 if normalized else 0),
        text_sha1=sha1_text(normalized) if normalized else "",
        text_preview=short_preview(normalized),
    )


def read_existing_docs(path: Path) -> Dict[str, Dict[str, str]]:
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return {row["doc_id"]: {key: value or "" for key, value in row.items()} for row in reader}


def build_event_document_rows(event_rows: Sequence[Dict[str, str]]) -> Tuple[List[Dict[str, str]], Dict[str, Dict[str, str]]]:
    mapping_rows: List[Dict[str, str]] = []
    documents: Dict[str, Dict[str, str]] = {}
    linked_event_counts: Dict[str, set] = {}

    for event in event_rows:
        seen_for_event = set()
        for order, source_url in enumerate(split_event_links(event.get("event_links_raw", "")), start=1):
            doc_id = sha1_text(source_url)[:16]
            mapping_rows.append(
                {
                    "event_id": event["event_id"],
                    "source_row_number": event["source_row_number"],
                    "Drug Name": event["Drug Name"],
                    "Application Number": event["Application Number"],
                    "event_header": event["event_header"],
                    "event_date_iso": event["event_date_iso"],
                    "doc_order_on_event": str(order),
                    "doc_id": doc_id,
                    "source_url": source_url,
                }
            )
            if doc_id not in documents:
                parsed = urlparse(source_url)
                documents[doc_id] = {
                    "doc_id": doc_id,
                    "normalized_source_url": source_url,
                    "source_domain": parsed.netloc.lower(),
                    "url_type_guess": guess_url_type(source_url),
                    "shared_event_count": "",
                    "linked_event_count": "",
                    "download_status": "pending",
                    "download_http_status": "",
                    "content_type": "",
                    "final_url": "",
                    "raw_file_path": "",
                    "raw_file_size_bytes": "",
                    "raw_sha1": "",
                    "text_extract_status": "pending",
                    "text_file_path": "",
                    "text_char_count": "",
                    "text_line_count": "",
                    "text_sha1": "",
                    "text_preview": "",
                    "download_error": "",
                }
                linked_event_counts[doc_id] = set()
            linked_event_counts[doc_id].add(event["event_id"])
            seen_for_event.add(doc_id)

    shared_event_counter: Dict[str, int] = {}
    for row in mapping_rows:
        shared_event_counter[row["doc_id"]] = shared_event_counter.get(row["doc_id"], 0) + 1

    for doc_id, document in documents.items():
        document["shared_event_count"] = str(shared_event_counter.get(doc_id, 0))
        document["linked_event_count"] = str(len(linked_event_counts.get(doc_id, set())))

    return mapping_rows, documents


def apply_existing_state(
    current_docs: Dict[str, Dict[str, str]],
    existing_docs: Dict[str, Dict[str, str]],
) -> None:
    for doc_id, current in current_docs.items():
        previous = existing_docs.get(doc_id)
        if not previous:
            continue
        for field in DOC_COLUMNS:
            if field in {
                "doc_id",
                "normalized_source_url",
                "source_domain",
                "url_type_guess",
                "shared_event_count",
                "linked_event_count",
            }:
                continue
            if previous.get(field):
                current[field] = previous[field]


def ensure_downloaded_and_extracted(
    doc: Dict[str, str],
    raw_root: Path,
    text_root: Path,
    timeout_s: int,
    insecure_ssl: bool,
) -> None:
    if doc.get("download_status") == "access_restricted" and not doc.get("raw_file_path"):
        doc["text_file_path"] = ""
        doc["text_char_count"] = ""
        doc["text_line_count"] = ""
        doc["text_sha1"] = ""
        doc["text_preview"] = ""
        doc["text_extract_status"] = "access_restricted"
        return

    raw_path = Path(doc["raw_file_path"]) if doc.get("raw_file_path") else None
    if raw_path and raw_path.exists():
        if local_raw_file_is_valid(doc, raw_path):
            doc["download_status"] = "downloaded"
            if not doc.get("raw_file_size_bytes"):
                doc["raw_file_size_bytes"] = str(raw_path.stat().st_size)
            if not doc.get("raw_sha1"):
                doc["raw_sha1"] = compute_file_sha1(raw_path)
        else:
            clear_doc_artifacts(doc)
            raw_path = None

    if raw_path is None or not raw_path.exists():
        result = download_document(
            source_url=doc["normalized_source_url"],
            url_type_guess=doc["url_type_guess"],
            doc_id=doc["doc_id"],
            raw_root=raw_root,
            timeout_s=timeout_s,
            insecure_ssl=insecure_ssl,
        )
        doc["download_status"] = result.download_status
        doc["download_http_status"] = result.http_status
        doc["content_type"] = result.content_type
        doc["final_url"] = result.final_url
        doc["raw_file_path"] = result.raw_file_path
        doc["raw_file_size_bytes"] = result.raw_file_size_bytes
        doc["raw_sha1"] = result.raw_sha1
        doc["download_error"] = result.download_error
        raw_path = Path(result.raw_file_path) if result.raw_file_path else None

    if doc["download_status"] == "access_restricted":
        doc["text_file_path"] = ""
        doc["text_char_count"] = ""
        doc["text_line_count"] = ""
        doc["text_sha1"] = ""
        doc["text_preview"] = ""
        doc["text_extract_status"] = "access_restricted"
        return

    if doc["download_status"] != "downloaded" or raw_path is None or not raw_path.exists():
        if doc["text_extract_status"] == "pending":
            doc["text_extract_status"] = "not_downloaded"
        return

    text_path = Path(doc["text_file_path"]) if doc.get("text_file_path") else None
    if text_path and text_path.exists():
        text = text_path.read_text(encoding="utf-8", errors="ignore")
        doc["text_extract_status"] = doc.get("text_extract_status") or "extracted"
        doc["text_char_count"] = str(len(text))
        doc["text_line_count"] = str(text.count("\n") + 1 if text else 0)
        doc["text_sha1"] = sha1_text(text) if text else ""
        doc["text_preview"] = short_preview(text)
        return

    extract = extract_text_file(raw_path, doc.get("content_type", ""), text_root, doc["doc_id"])
    doc["text_extract_status"] = extract.text_extract_status
    doc["text_file_path"] = extract.text_file_path
    doc["text_char_count"] = extract.text_char_count
    doc["text_line_count"] = extract.text_line_count
    doc["text_sha1"] = extract.text_sha1
    doc["text_preview"] = extract.text_preview


def write_manifest_row(manifest_fp, payload: Dict[str, str]) -> None:
    manifest_fp.write(json.dumps(payload, ensure_ascii=False) + "\n")
    manifest_fp.flush()


def process_document(
    doc: Dict[str, str],
    raw_root: Path,
    text_root: Path,
    timeout_s: int,
    insecure_ssl: bool,
    request_delay: float,
) -> ProcessResult:
    before_download = doc.get("download_status", "pending")
    before_extract = doc.get("text_extract_status", "pending")
    try:
        ensure_downloaded_and_extracted(
            doc=doc,
            raw_root=raw_root,
            text_root=text_root,
            timeout_s=timeout_s,
            insecure_ssl=insecure_ssl,
        )
    except Exception as exc:
        doc["download_status"] = "error"
        doc["download_error"] = f"Unhandled exception: {normalize_space(str(exc))}"
        if doc.get("text_extract_status") == "pending":
            doc["text_extract_status"] = "not_downloaded"
    if request_delay > 0:
        time.sleep(request_delay)
    return ProcessResult(
        before_download=before_download,
        before_extract=before_extract,
        doc=doc,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a document package for SrLC event evidence with raw files, extracted text files, and relational CSVs."
    )
    parser.add_argument("--events-csv", default="srlc_events_expanded.csv")
    parser.add_argument("--event-map-csv", default="event_document_map.csv")
    parser.add_argument("--docs-csv", default="evidence_documents.csv")
    parser.add_argument("--output-dir", default="event_evidence")
    parser.add_argument("--manifest-jsonl", default="event_evidence_manifest.jsonl")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--request-delay", type=float, default=0.25)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--max-docs", type=int, default=0, help="Limit download/extract work to the first N unique documents; 0 means all")
    parser.add_argument("--doc-id-file", default="", help="Optional newline-delimited file of doc_id values to process")
    parser.add_argument("--skip-download", action="store_true", help="Only build the relational CSVs without downloading raw documents")
    parser.add_argument("--insecure-ssl", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    base = Path.cwd()
    events_csv = base / args.events_csv
    event_map_csv = base / args.event_map_csv
    docs_csv = base / args.docs_csv
    output_dir = base / args.output_dir
    raw_root = output_dir / "raw"
    text_root = output_dir / "text"
    manifest_path = base / args.manifest_jsonl

    event_rows = read_event_rows(events_csv)
    mapping_rows, documents = build_event_document_rows(event_rows)
    apply_existing_state(documents, read_existing_docs(docs_csv))

    write_csv(event_map_csv, EVENT_MAP_COLUMNS, mapping_rows)

    if not args.skip_download:
        doc_items = sorted(documents.values(), key=lambda item: item["doc_id"])
        if args.doc_id_file:
            selected_ids = set(read_doc_id_filter(base / args.doc_id_file))
            doc_items = [item for item in doc_items if item["doc_id"] in selected_ids]
        if args.max_docs > 0:
            doc_items = doc_items[: args.max_docs]
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with manifest_path.open("a", encoding="utf-8") as manifest_fp:
            if args.workers <= 1:
                for index, doc in enumerate(doc_items, start=1):
                    result = process_document(
                        doc=doc,
                        raw_root=raw_root,
                        text_root=text_root,
                        timeout_s=args.timeout,
                        insecure_ssl=args.insecure_ssl,
                        request_delay=args.request_delay,
                    )
                    documents[result.doc["doc_id"]] = result.doc
                    write_manifest_row(
                        manifest_fp,
                        {
                            "ts": utc_now_iso(),
                            "doc_id": result.doc["doc_id"],
                            "source_url": result.doc["normalized_source_url"],
                            "download_status_before": result.before_download,
                            "download_status_after": result.doc["download_status"],
                            "text_extract_status_before": result.before_extract,
                            "text_extract_status_after": result.doc["text_extract_status"],
                            "raw_file_path": result.doc["raw_file_path"],
                            "text_file_path": result.doc["text_file_path"],
                            "download_error": result.doc["download_error"],
                        },
                    )
                    if index % 20 == 0 or index == len(doc_items):
                        print(f"Documents processed: {index}/{len(doc_items)}", flush=True)
            else:
                completed = 0
                with ProcessPoolExecutor(max_workers=args.workers) as executor:
                    future_map = {
                        executor.submit(
                            process_document,
                            doc,
                            raw_root,
                            text_root,
                            args.timeout,
                            args.insecure_ssl,
                            args.request_delay,
                        ): doc["doc_id"]
                        for doc in doc_items
                    }
                    for future in as_completed(future_map):
                        result = future.result()
                        completed += 1
                        documents[result.doc["doc_id"]] = result.doc
                        write_manifest_row(
                            manifest_fp,
                            {
                                "ts": utc_now_iso(),
                                "doc_id": result.doc["doc_id"],
                                "source_url": result.doc["normalized_source_url"],
                                "download_status_before": result.before_download,
                                "download_status_after": result.doc["download_status"],
                                "text_extract_status_before": result.before_extract,
                                "text_extract_status_after": result.doc["text_extract_status"],
                                "raw_file_path": result.doc["raw_file_path"],
                                "text_file_path": result.doc["text_file_path"],
                                "download_error": result.doc["download_error"],
                            },
                        )
                        if completed % 20 == 0 or completed == len(doc_items):
                            print(f"Documents processed: {completed}/{len(doc_items)}", flush=True)

    doc_rows = [documents[doc_id] for doc_id in sorted(documents)]
    write_csv(docs_csv, DOC_COLUMNS, doc_rows)

    print(f"Event rows read: {len(event_rows)}")
    print(f"Event-document links written: {len(mapping_rows)}")
    print(f"Unique documents tracked: {len(doc_rows)}")
    print(f"Wrote {event_map_csv}")
    print(f"Wrote {docs_csv}")
    if args.skip_download:
        print("Download/extraction skipped; document rows remain pending until a non-skip run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
