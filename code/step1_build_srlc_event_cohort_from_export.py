#!/usr/bin/env python3

import argparse
import csv
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.parse import urljoin

import lxml.html


EXTRA_OUTPUT_COLUMNS = [
    "source_row_number",
    "drug_name_id",
    "event_id",
    "event_sequence_on_page",
    "event_header",
    "event_date",
    "event_date_iso",
    "supplement_number",
    "label_section_changed",
    "change_text",
    "event_links_raw",
]

JINA_PREFIX = "https://r.jina.ai/http://"


@dataclass(frozen=True)
class SourceRow:
    row_number: int
    data: Dict[str, str]
    link: str
    drug_name_id: str


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def parse_mmddyyyy(value: str) -> Optional[datetime]:
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(normalize_space(value), fmt)
        except Exception:
            pass
    return None


def date_key(value: str) -> str:
    parsed = parse_mmddyyyy(value)
    return parsed.strftime("%Y-%m-%d") if parsed else ""


def extract_drug_name_id(url: str) -> str:
    match = re.search(r"DrugNameID=(\d+)", str(url or ""))
    return match.group(1) if match else ""


def normalize_section_title(raw: str) -> str:
    text = normalize_space(raw)
    text = re.sub(r"^\d+(\.\d+)?\s*", "", text)
    text = text.replace(
        "PCI/PI/MG (Patient Counseling Information/Patient Information/Medication Guide)",
        "PCI/PI/MG",
    )
    text = text.replace(
        "MG/PCI/PI (Medication Guide/Patient Counseling Information/Package Insert)",
        "PCI/PI/MG",
    )
    return text or "Unknown"


def unique_preserve_order(values: Sequence[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for value in values:
        item = normalize_space(value)
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def build_ssl_context(insecure_ssl: bool) -> Optional[ssl.SSLContext]:
    if insecure_ssl:
        return ssl._create_unverified_context()
    return None


def jina_proxy_url(url: str) -> str:
    return f"{JINA_PREFIX}{url}"


def fetch_text(
    url: str,
    *,
    timeout: int,
    ssl_context: Optional[ssl.SSLContext],
    transport: str,
    retries: int = 1,
) -> str:
    last_err: Optional[Exception] = None
    effective_ssl_context = ssl_context
    attempts = retries
    if transport == "direct" and ssl_context is None:
        attempts = max(attempts, 2)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    for _ in range(attempts):
        try:
            request_url = jina_proxy_url(url) if transport == "jina" else url
            request = urllib.request.Request(request_url, headers=headers)
            with urllib.request.urlopen(request, timeout=timeout, context=effective_ssl_context) as response:
                return response.read().decode("utf-8", "ignore")
        except Exception as err:  # pragma: no cover
            if (
                transport == "direct"
                and effective_ssl_context is None
                and "CERTIFICATE_VERIFY_FAILED" in str(err)
            ):
                effective_ssl_context = ssl._create_unverified_context()
                last_err = err
                continue
            last_err = err

    if last_err is not None:
        raise last_err
    raise RuntimeError(f"Unable to fetch {url}")


def node_text(node) -> str:
    return normalize_space(node.text_content())


def join_event_blocks(blocks: Sequence[Sequence[str]]) -> str:
    out: List[str] = []
    for block in blocks:
        parts = [normalize_space(part) for part in block if normalize_space(part)]
        if parts:
            out.append(" | ".join(parts))
    return " || ".join(out)


def build_change_text(content) -> Tuple[str, str]:
    sections: List[Tuple[str, List[str]]] = []
    current_index: Optional[int] = None
    fallback_chunks: List[str] = []

    for node in content.iterchildren():
        tag = getattr(node, "tag", "")
        if not isinstance(tag, str):
            continue
        tag = tag.lower()
        if tag in {"script", "style"}:
            continue

        if tag == "h4":
            title = normalize_section_title(node.text_content())
            sections.append((title, []))
            current_index = len(sections) - 1
            continue

        chunk = node_text(node)
        if not chunk:
            continue
        if re.fullmatch(r"Approved Drug Label\s*\(PDF\)", chunk, flags=re.IGNORECASE):
            continue

        if current_index is None:
            fallback_chunks.append(chunk)
        else:
            sections[current_index][1].append(chunk)

    label_sections = "; ".join(unique_preserve_order([title for title, _ in sections]))
    block_parts: List[List[str]] = []
    for title, chunks in sections:
        parts: List[str] = []
        if title:
            parts.append(title)
        parts.extend(chunks)
        block_parts.append(parts)

    change_text = join_event_blocks(block_parts)
    if not change_text:
        change_text = " | ".join(unique_preserve_order(fallback_chunks))
    return label_sections, change_text


def parse_detail_events(html_text: str, detail_url: str) -> List[Dict[str, str]]:
    document = lxml.html.fromstring(html_text)
    containers = document.xpath('//div[@id="accordion"]')
    if not containers:
        return []

    events: List[Dict[str, str]] = []
    for sequence, header in enumerate(containers[0].xpath("./h3"), start=1):
        event_header = normalize_space(header.text_content())
        date_match = re.search(r"\b\d{2}/\d{2}/\d{4}\b", event_header)
        if not date_match:
            continue

        content = header.getnext()
        while content is not None and getattr(content, "tag", "").lower() != "div":
            content = content.getnext()
        if content is None:
            continue

        supplement_match = re.search(r"SUPPL-?([A-Z0-9-]+)", event_header, flags=re.IGNORECASE)
        supplement_number = supplement_match.group(1) if supplement_match else ""
        event_date = date_match.group(0)
        event_date_iso = date_key(event_date)
        label_sections, change_text = build_change_text(content)
        event_links = unique_preserve_order([urljoin(detail_url, href) for href in content.xpath(".//a/@href")])

        events.append(
            {
                "event_sequence_on_page": str(sequence),
                "event_header": event_header,
                "event_date": event_date,
                "event_date_iso": event_date_iso,
                "supplement_number": supplement_number,
                "label_section_changed": label_sections,
                "change_text": change_text,
                "event_links_raw": " | ".join(event_links),
            }
        )

    return events


def clean_markdown_line(line: str) -> str:
    text = line.strip()
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1", text)
    text = re.sub(r"`+", "", text)
    text = re.sub(r"[*_]+", "", text)
    return normalize_space(text)


def build_change_text_from_markdown(event_body: str) -> Tuple[str, str]:
    sections: List[Tuple[str, List[str]]] = []
    current_index: Optional[int] = None
    fallback_chunks: List[str] = []

    for raw_line in event_body.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped.startswith("### "):
            break
        if stripped.startswith("## ") or stripped.startswith("# "):
            if sections or fallback_chunks:
                break
            continue
        if stripped.startswith("[Approved Drug Label"):
            continue

        if stripped.startswith("#### "):
            title = normalize_section_title(clean_markdown_line(stripped[5:]))
            sections.append((title, []))
            current_index = len(sections) - 1
            continue

        chunk = clean_markdown_line(stripped)
        if not chunk:
            continue

        if current_index is None:
            fallback_chunks.append(chunk)
        else:
            sections[current_index][1].append(chunk)

    label_sections = "; ".join(unique_preserve_order([title for title, _ in sections]))
    block_parts: List[List[str]] = []
    for title, chunks in sections:
        parts: List[str] = []
        if title:
            parts.append(title)
        parts.extend(chunks)
        block_parts.append(parts)

    change_text = join_event_blocks(block_parts)
    if not change_text:
        change_text = " | ".join(unique_preserve_order(fallback_chunks))
    return label_sections, change_text


def parse_detail_events_from_markdown(markdown_text: str, detail_url: str) -> List[Dict[str, str]]:
    if "Markdown Content:" in markdown_text:
        markdown_text = markdown_text.split("Markdown Content:", 1)[1]

    header_pattern = re.compile(r"(?m)^###\s+(\d{2}/\d{2}/\d{4})([^\n]*)$")
    matches = list(header_pattern.finditer(markdown_text))
    if not matches:
        return []

    events: List[Dict[str, str]] = []
    for sequence, match in enumerate(matches, start=1):
        start = match.end()
        end = matches[sequence].start() if sequence < len(matches) else len(markdown_text)
        event_body = markdown_text[start:end]

        event_header = clean_markdown_line(match.group(0).lstrip("# "))
        event_date = match.group(1)
        event_date_iso = date_key(event_date)
        supplement_match = re.search(r"SUPPL-?([A-Z0-9-]+)", match.group(0), flags=re.IGNORECASE)
        supplement_number = supplement_match.group(1) if supplement_match else ""
        label_sections, change_text = build_change_text_from_markdown(event_body)
        event_links = unique_preserve_order(re.findall(r"\((https?://[^)\s]+)", event_body))

        events.append(
            {
                "event_sequence_on_page": str(sequence),
                "event_header": event_header,
                "event_date": event_date,
                "event_date_iso": event_date_iso,
                "supplement_number": supplement_number,
                "label_section_changed": label_sections,
                "change_text": change_text,
                "event_links_raw": " | ".join(event_links),
            }
        )

    return events


def make_event_id(source_row: SourceRow, event: Dict[str, str]) -> str:
    seq = normalize_space(event.get("event_sequence_on_page", ""))
    supplement_number = normalize_space(event.get("supplement_number", ""))
    suffix = f"SUPPL-{supplement_number}" if supplement_number else f"SEQ-{seq or '0'}"
    return "|".join(
        [
            source_row.drug_name_id or f"row-{source_row.row_number}",
            normalize_space(event.get("event_date_iso", "")) or normalize_space(event.get("event_date", "")),
            suffix,
        ]
    )


def read_source_rows(input_csv: str) -> Tuple[List[str], List[SourceRow]]:
    with open(input_csv, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []

        needed = {
            "Drug Name",
            "Active Ingredient",
            "Application Number",
            "Application Type",
            "Supplement Date",
            "Database Updated",
            "Link",
        }
        missing = sorted(needed - set(fieldnames))
        if missing:
            raise ValueError(f"Input CSV missing required columns: {missing}")

        rows: List[SourceRow] = []
        for row_number, row in enumerate(reader, start=1):
            cleaned = {key: normalize_space(value) for key, value in row.items()}
            link = cleaned.get("Link", "")
            rows.append(
                SourceRow(
                    row_number=row_number,
                    data=cleaned,
                    link=link,
                    drug_name_id=extract_drug_name_id(link),
                )
            )

    return fieldnames, rows


def write_csv(path: str, fieldnames: Sequence[str], rows: Sequence[Dict[str, str]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Expand the SrLC export into an event-level CSV by scraping each FDA detail page"
    )
    parser.add_argument("--input-csv", default="Drug Safety-related Labeling Changes (SrLC) 3_20.csv")
    parser.add_argument("--output-csv", default="srlc_events_expanded.csv")
    parser.add_argument("--failures-csv", default="srlc_events_expanded_failures.csv")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--transport", choices=["direct", "jina"], default="direct")
    parser.add_argument("--request-delay", type=float, default=0.25)
    parser.add_argument("--pause-every", type=int, default=50)
    parser.add_argument("--pause-seconds", type=float, default=10.0)
    parser.add_argument("--max-403-retries", type=int, default=3)
    parser.add_argument("--retry-wait-seconds", type=float, default=60.0)
    parser.add_argument("--start-row", type=int, default=1, help="1-based data row index")
    parser.add_argument("--end-row", type=int, default=0, help="Inclusive 1-based data row index; 0 means all rows")
    parser.add_argument("--insecure-ssl", action="store_true")
    args = parser.parse_args(list(argv))

    source_columns, source_rows = read_source_rows(args.input_csv)
    if args.start_row < 1:
        raise ValueError("--start-row must be >= 1")
    if args.end_row and args.end_row < args.start_row:
        raise ValueError("--end-row must be >= --start-row")
    source_rows = [
        row
        for row in source_rows
        if row.row_number >= args.start_row and (args.end_row == 0 or row.row_number <= args.end_row)
    ]
    ssl_context = build_ssl_context(args.insecure_ssl)

    parsed_events: Dict[str, List[Dict[str, str]]] = {}
    failures: List[Dict[str, str]] = []

    total = len(source_rows)
    for index, source_row in enumerate(source_rows, start=1):
        attempts = 0
        while True:
            try:
                html_text = fetch_text(
                    source_row.link,
                    timeout=args.timeout,
                    ssl_context=ssl_context,
                    transport=args.transport,
                    retries=1,
                )
                if args.transport == "jina":
                    events = parse_detail_events_from_markdown(html_text, source_row.link)
                else:
                    events = parse_detail_events(html_text, source_row.link)
                parsed_events[source_row.link] = events
                if not events:
                    failures.append(
                        {
                            "source_row_number": str(source_row.row_number),
                            "drug_name_id": source_row.drug_name_id,
                            "link": source_row.link,
                            "error": "No dated events parsed from detail page",
                        }
                    )
                break
            except urllib.error.HTTPError as err:  # pragma: no cover
                if err.code == 403 and attempts < args.max_403_retries:
                    attempts += 1
                    wait_seconds = args.retry_wait_seconds * attempts
                    print(
                        f"403 for row {source_row.row_number} ({index}/{total}); "
                        f"waiting {wait_seconds:.0f}s before retry {attempts}/{args.max_403_retries}",
                        flush=True,
                    )
                    time.sleep(wait_seconds)
                    continue

                parsed_events[source_row.link] = []
                failures.append(
                    {
                        "source_row_number": str(source_row.row_number),
                        "drug_name_id": source_row.drug_name_id,
                        "link": source_row.link,
                        "error": normalize_space(str(err)),
                    }
                )
                break
            except Exception as err:  # pragma: no cover
                parsed_events[source_row.link] = []
                failures.append(
                    {
                        "source_row_number": str(source_row.row_number),
                        "drug_name_id": source_row.drug_name_id,
                        "link": source_row.link,
                        "error": normalize_space(str(err)),
                    }
                )
                break

        if index % 20 == 0 or index == total:
            print(f"Detail pages processed: {index}/{total}", flush=True)

        if index < total and args.request_delay > 0:
            time.sleep(args.request_delay)
        if args.pause_every > 0 and index % args.pause_every == 0 and index < total:
            print(f"Pausing for {args.pause_seconds:.0f}s after {index} requests", flush=True)
            time.sleep(args.pause_seconds)

    output_rows: List[Dict[str, str]] = []
    for source_row in source_rows:
        for event in parsed_events.get(source_row.link, []):
            row = dict(source_row.data)
            row.update(
                {
                    "source_row_number": str(source_row.row_number),
                    "drug_name_id": source_row.drug_name_id,
                    "event_id": make_event_id(source_row, event),
                    "event_sequence_on_page": event["event_sequence_on_page"],
                    "event_header": event["event_header"],
                    "event_date": event["event_date"],
                    "event_date_iso": event["event_date_iso"],
                    "supplement_number": event["supplement_number"],
                    "label_section_changed": event["label_section_changed"],
                    "change_text": event["change_text"],
                    "event_links_raw": event["event_links_raw"],
                }
            )
            output_rows.append(row)

    output_columns = ["source_row_number"] + source_columns + EXTRA_OUTPUT_COLUMNS[1:]
    write_csv(args.output_csv, output_columns, output_rows)

    if failures:
        failure_columns = ["source_row_number", "drug_name_id", "link", "error"]
        write_csv(args.failures_csv, failure_columns, failures)
        print(f"Wrote {args.failures_csv} with {len(failures)} failure rows.")
    elif os.path.exists(args.failures_csv):
        os.remove(args.failures_csv)

    print(f"Source rows: {len(source_rows)}")
    print(f"Expanded event rows: {len(output_rows)}")
    print(f"Wrote {args.output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
