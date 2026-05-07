#!/usr/bin/env python3
"""Build event-level annotation packets from the frozen SrLC evidence package."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
from statistics import mean, median
from typing import Dict, Iterable, List, Sequence, Tuple


REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_DIR = REPO_ROOT
DESIGN_DIR = BASE_DIR / "annotation_design"
OUTPUT_DIR = BASE_DIR / "annotation_packets"

EVENTS_CSV = BASE_DIR / "srlc_events_expanded.csv"
EVENT_DOC_MAP_CSV = BASE_DIR / "event_document_map.csv"
DOCS_CSV = BASE_DIR / "evidence_documents.csv"
FREEZE_JSON = DESIGN_DIR / "annotation_design_freeze_v1.json"

PACKETS_JSONL = OUTPUT_DIR / "annotation_event_packets_v1.jsonl"
PACKET_INDEX_CSV = OUTPUT_DIR / "annotation_event_packet_index_v1.csv"
PACKET_STATS_JSON = OUTPUT_DIR / "annotation_packet_build_stats_v1.json"
PACKET_REPORT_MD = OUTPUT_DIR / "annotation_packet_build_report_v1.md"


GENERIC_TERMS = {
    "ability",
    "addition",
    "additions",
    "adverse",
    "approval",
    "approved",
    "because",
    "boxed",
    "change",
    "changes",
    "clinical",
    "contraindications",
    "data",
    "documented",
    "drug",
    "drugs",
    "effect",
    "effects",
    "event",
    "events",
    "experience",
    "following",
    "identified",
    "including",
    "indicated",
    "information",
    "label",
    "labeling",
    "labels",
    "material",
    "materials",
    "medguide",
    "medication",
    "patient",
    "patients",
    "population",
    "populations",
    "postmarketing",
    "precautions",
    "pregnancy",
    "published",
    "reaction",
    "reactions",
    "related",
    "reported",
    "reports",
    "revisions",
    "risk",
    "risks",
    "section",
    "sections",
    "specific",
    "study",
    "studies",
    "supplement",
    "supply",
    "safety",
    "underlined",
    "warning",
    "warnings",
    "women",
    "wording",
    "use",
}

STOPWORDS = GENERIC_TERMS.union(
    {
        "about",
        "after",
        "again",
        "against",
        "all",
        "also",
        "although",
        "among",
        "amongst",
        "and",
        "another",
        "any",
        "are",
        "around",
        "because",
        "been",
        "before",
        "being",
        "between",
        "both",
        "but",
        "can",
        "cannot",
        "could",
        "did",
        "does",
        "doing",
        "done",
        "down",
        "during",
        "each",
        "either",
        "especially",
        "few",
        "from",
        "further",
        "generally",
        "had",
        "has",
        "have",
        "having",
        "here",
        "however",
        "into",
        "its",
        "itself",
        "just",
        "made",
        "make",
        "makes",
        "many",
        "may",
        "might",
        "more",
        "most",
        "much",
        "must",
        "need",
        "needed",
        "needs",
        "not",
        "other",
        "our",
        "out",
        "overall",
        "over",
        "same",
        "such",
        "than",
        "that",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "thus",
        "under",
        "upon",
        "using",
        "very",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "who",
        "with",
        "within",
        "without",
        "would",
        "your",
    }
)

CUE_PATTERNS: Dict[str, re.Pattern[str]] = {
    "rwe_generic": re.compile(
        r"\b(real[- ]world evidence|real[- ]world data|\brwe\b|\brwd\b)\b",
        re.IGNORECASE,
    ),
    "claims": re.compile(
        r"\b(claims?|administrative claims|insurance claims)\b",
        re.IGNORECASE,
    ),
    "ehr": re.compile(
        r"\b(ehr|electronic health records?|medical records?)\b",
        re.IGNORECASE,
    ),
    "registry": re.compile(
        r"\b(registry|pregnancy registry|patient registry|disease registry)\b",
        re.IGNORECASE,
    ),
    "active_surveillance": re.compile(
        r"\b(sentinel|prism|best initiative|active surveillance|distributed data network)\b",
        re.IGNORECASE,
    ),
    "spontaneous_reports": re.compile(
        r"\b(spontaneous reports?|postmarketing reports?|faers|medwatch|pharmacovigilance)\b",
        re.IGNORECASE,
    ),
    "observational_design": re.compile(
        r"\b(observational|cohort|case-control|case control|retrospective|prospective|case-crossover|case crossover|sccs|scri|self-controlled)\b",
        re.IGNORECASE,
    ),
    "confounding_control": re.compile(
        r"\b(propensity|matching|weighted|weighting|inverse probability|multivariable|multivariate|adjusted analysis|confounding|stratified|stratification)\b",
        re.IGNORECASE,
    ),
    "missing_data": re.compile(
        r"\b(missing data|imputation|multiple imputation|complete case)\b",
        re.IGNORECASE,
    ),
    "sensitivity_analysis": re.compile(
        r"\b(sensitivity analys(?:is|es)|robustness analys(?:is|es)|secondary analys(?:is|es)|alternate specification)\b",
        re.IGNORECASE,
    ),
    "negative_control": re.compile(
        r"\b(negative control|falsification outcome|falsification exposure)\b",
        re.IGNORECASE,
    ),
    "effect_measure": re.compile(
        r"\b(hazard ratio|odds ratio|risk ratio|relative risk|incidence rate ratio|rate ratio|risk difference|rate difference)\b",
        re.IGNORECASE,
    ),
    "uncertainty_measure": re.compile(
        r"\b(confidence interval|credible interval|\bp-value\b|\bp value\b|standard error|95% ci)\b",
        re.IGNORECASE,
    ),
}

CUE_WEIGHTS = {
    "rwe_generic": 9.0,
    "claims": 5.0,
    "ehr": 5.0,
    "registry": 5.0,
    "active_surveillance": 6.0,
    "spontaneous_reports": 3.0,
    "observational_design": 4.0,
    "confounding_control": 4.0,
    "missing_data": 4.0,
    "sensitivity_analysis": 4.0,
    "negative_control": 4.0,
    "effect_measure": 2.5,
    "uncertainty_measure": 2.0,
}

INDEX_FIELDS = [
    "event_id",
    "source_row_number",
    "Drug Name",
    "Active Ingredient",
    "Application Number",
    "Application Type",
    "event_header",
    "event_date_iso",
    "supplement_number",
    "linked_doc_count_total",
    "downloaded_doc_count",
    "extracted_doc_count",
    "access_restricted_doc_count",
    "error_doc_count",
    "selected_doc_count",
    "selected_snippet_count",
    "query_term_count",
    "packet_type",
    "packet_hash",
    "packet_char_count",
    "top_selected_doc_ids",
    "cue_any_hits",
]


def load_csv_rows(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def safe_int(value: str) -> int:
    value = (value or "").strip()
    return int(value) if value and value.isdigit() else 0


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z][a-z0-9_-]{2,}", text.lower())


def extract_query_terms(event_row: Dict[str, str], max_terms: int = 14) -> List[str]:
    pieces = [
        event_row.get("Drug Name", ""),
        event_row.get("Active Ingredient", ""),
        event_row.get("label_section_changed", ""),
        event_row.get("change_text", ""),
    ]
    tokens = tokenize(" ".join(pieces))
    counts = Counter(t for t in tokens if t not in STOPWORDS and len(t) >= 4)
    ranked = sorted(counts.items(), key=lambda item: (-item[1], -len(item[0]), item[0]))
    return [term for term, _ in ranked[:max_terms]]


def chunk_text(text: str, window_lines: int = 8, step_lines: int = 6) -> List[str]:
    lines = [normalize_space(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return []

    chunks: List[str] = []
    seen: set[str] = set()
    for start in range(0, len(lines), step_lines):
        block = lines[start : start + window_lines]
        if not block:
            continue
        chunk = normalize_space(" ".join(block))
        if len(chunk) < 80 or chunk in seen:
            continue
        seen.add(chunk)
        chunks.append(chunk)
    return chunks


@lru_cache(maxsize=256)
def read_doc_chunks(text_file_path: str) -> List[str]:
    text = Path(text_file_path).read_text(errors="ignore")
    return chunk_text(text)


def matched_cues(text: str) -> List[str]:
    return [name for name, pattern in CUE_PATTERNS.items() if pattern.search(text or "")]


def score_chunk(
    chunk: str,
    query_terms: Sequence[str],
    source_domain: str,
    url_type_guess: str,
) -> Tuple[float, List[str], List[str]]:
    token_set = set(tokenize(chunk))
    overlap_terms = [term for term in query_terms if term in token_set]
    cue_hits = matched_cues(chunk)
    score = 0.0
    score += min(len(overlap_terms), 6) * 1.4
    score += sum(CUE_WEIGHTS[name] for name in cue_hits)
    if source_domain and source_domain not in {"www.accessdata.fda.gov", "www.fda.gov"}:
        score += 1.2
    if url_type_guess and url_type_guess != "pdf":
        score += 0.6
    return score, cue_hits, overlap_terms


def build_rule_cues(
    change_text: str,
    docs_for_event: Sequence[Dict[str, str]],
    selected_docs: Sequence[Dict[str, object]],
) -> Dict[str, Dict[str, object]]:
    result: Dict[str, Dict[str, object]] = {}
    selected_doc_ids = {
        str(doc["doc_id"])
        for doc in selected_docs
        if doc.get("doc_id")
    }
    for cue_name, pattern in CUE_PATTERNS.items():
        meta_doc_ids: List[str] = []
        snippet_doc_ids: List[str] = []
        change_text_hit = bool(pattern.search(change_text or ""))

        for doc in docs_for_event:
            doc_meta_text = " ".join(
                [
                    doc.get("normalized_source_url", ""),
                    doc.get("source_domain", ""),
                    doc.get("text_preview", ""),
                ]
            )
            if pattern.search(doc_meta_text):
                meta_doc_ids.append(doc["doc_id"])

        for doc in selected_docs:
            for snippet in doc.get("snippets", []):
                if cue_name in snippet.get("cue_hits", []):
                    snippet_doc_ids.append(str(doc["doc_id"]))
                    break

        meta_doc_ids = sorted(set(meta_doc_ids))
        snippet_doc_ids = sorted(set(snippet_doc_ids))
        result[cue_name] = {
            "change_text_hit": change_text_hit,
            "doc_meta_hit": bool(meta_doc_ids),
            "snippet_hit": bool(snippet_doc_ids),
            "any_hit": change_text_hit or bool(meta_doc_ids) or bool(snippet_doc_ids),
            "doc_ids_from_meta": meta_doc_ids[:5],
            "doc_ids_from_snippets": snippet_doc_ids[:5],
            "selected_doc_overlap": sorted(selected_doc_ids.intersection(meta_doc_ids))[:5],
        }
    return result


def packet_type_from_counts(linked: int, extracted: int, selected_docs: int, selected_snippets: int) -> str:
    if linked == 0:
        return "no_docs"
    if extracted == 0 or selected_snippets == 0:
        return "metadata_only"
    return "full"


def select_docs_for_event(
    docs_for_event: Sequence[Dict[str, str]],
    query_terms: Sequence[str],
    max_docs: int = 4,
    max_snippets_per_doc: int = 2,
) -> List[Dict[str, object]]:
    selected: List[Dict[str, object]] = []

    scored_docs: List[Tuple[float, Dict[str, object]]] = []
    fallback_docs: List[Dict[str, object]] = []

    for doc in docs_for_event:
        base = {
            "doc_id": doc["doc_id"],
            "doc_order_on_event": safe_int(doc.get("doc_order_on_event", "")),
            "normalized_source_url": doc.get("normalized_source_url", ""),
            "source_url": doc.get("source_url", ""),
            "source_domain": doc.get("source_domain", ""),
            "url_type_guess": doc.get("url_type_guess", ""),
            "download_status": doc.get("download_status", ""),
            "text_extract_status": doc.get("text_extract_status", ""),
            "text_char_count": safe_int(doc.get("text_char_count", "")),
            "text_preview": doc.get("text_preview", ""),
            "raw_file_path": doc.get("raw_file_path", ""),
            "text_file_path": doc.get("text_file_path", ""),
            "snippets": [],
            "selection_score": 0.0,
            "selection_reason": [],
        }

        if doc.get("download_status") != "downloaded" or doc.get("text_extract_status") != "extracted":
            fallback_docs.append(base)
            continue

        try:
            chunks = read_doc_chunks(doc["text_file_path"])
        except FileNotFoundError:
            fallback_docs.append(base)
            continue

        scored_snippets: List[Tuple[float, Dict[str, object]]] = []
        for chunk in chunks:
            score, cue_hits, overlap_terms = score_chunk(
                chunk,
                query_terms,
                doc.get("source_domain", ""),
                doc.get("url_type_guess", ""),
            )
            if score <= 0:
                continue
            scored_snippets.append(
                (
                    score,
                    {
                        "score": round(score, 2),
                        "text": chunk[:1200],
                        "cue_hits": cue_hits,
                        "query_term_hits": overlap_terms[:10],
                    },
                )
            )

        scored_snippets.sort(key=lambda item: (-item[0], -len(item[1]["text"])))
        top_snippets = [item[1] for item in scored_snippets[:max_snippets_per_doc]]
        if top_snippets:
            base["snippets"] = top_snippets
            base["selection_score"] = round(max(item[0] for item in scored_snippets), 2)
            base["selection_reason"] = ["retrieved_relevant_snippet"]
            scored_docs.append((float(base["selection_score"]), base))
            continue

        preview = normalize_space(doc.get("text_preview", ""))[:1200]
        if preview:
            base["snippets"] = [
                {
                    "score": 0.1,
                    "text": preview,
                    "cue_hits": matched_cues(preview),
                    "query_term_hits": [term for term in query_terms if term in set(tokenize(preview))][:10],
                }
            ]
            base["selection_score"] = 0.1
            base["selection_reason"] = ["fallback_text_preview"]
            scored_docs.append((0.1, base))
        else:
            fallback_docs.append(base)

    scored_docs.sort(
        key=lambda item: (
            -item[0],
            item[1]["doc_order_on_event"],
            item[1]["doc_id"],
        )
    )
    selected = [item[1] for item in scored_docs[:max_docs]]

    if not selected and fallback_docs:
        fallback_docs.sort(key=lambda doc: (doc["doc_order_on_event"], doc["doc_id"]))
        for doc in fallback_docs[: min(2, len(fallback_docs))]:
            doc["selection_reason"] = ["metadata_only_fallback"]
            selected.append(doc)

    return selected


def build_packet(
    event_row: Dict[str, str],
    docs_for_event: Sequence[Dict[str, str]],
    design_version: str,
) -> Tuple[Dict[str, object], Dict[str, object]]:
    query_terms = extract_query_terms(event_row)
    selected_docs = select_docs_for_event(docs_for_event, query_terms)

    linked_doc_count_total = len(docs_for_event)
    downloaded_doc_count = sum(1 for doc in docs_for_event if doc.get("download_status") == "downloaded")
    extracted_doc_count = sum(1 for doc in docs_for_event if doc.get("text_extract_status") == "extracted")
    access_restricted_doc_count = sum(
        1 for doc in docs_for_event if doc.get("download_status") == "access_restricted"
    )
    error_doc_count = sum(1 for doc in docs_for_event if doc.get("download_status") == "error")
    selected_snippet_count = sum(len(doc.get("snippets", [])) for doc in selected_docs)

    rule_cues = build_rule_cues(event_row.get("change_text", ""), docs_for_event, selected_docs)
    cue_any_hits = sorted(name for name, payload in rule_cues.items() if payload["any_hit"])

    packet = {
        "annotation_design_version": design_version,
        "packet_version": "v1",
        "event": {
            "event_id": event_row["event_id"],
            "source_row_number": event_row["source_row_number"],
            "drug_name_id": event_row.get("drug_name_id", ""),
            "drug_name": event_row.get("Drug Name", ""),
            "active_ingredient": event_row.get("Active Ingredient", ""),
            "application_number": event_row.get("Application Number", ""),
            "application_type": event_row.get("Application Type", ""),
            "event_header": event_row.get("event_header", ""),
            "event_date_iso": event_row.get("event_date_iso", ""),
            "supplement_number": event_row.get("supplement_number", ""),
            "label_section_changed": event_row.get("label_section_changed", ""),
            "change_text": event_row.get("change_text", ""),
            "source_link": event_row.get("Link", ""),
        },
        "retrieval": {
            "query_terms": query_terms,
            "linked_doc_count_total": linked_doc_count_total,
            "downloaded_doc_count": downloaded_doc_count,
            "extracted_doc_count": extracted_doc_count,
            "access_restricted_doc_count": access_restricted_doc_count,
            "error_doc_count": error_doc_count,
            "selected_doc_count": len(selected_docs),
            "selected_snippet_count": selected_snippet_count,
            "packet_type": packet_type_from_counts(
                linked_doc_count_total,
                extracted_doc_count,
                len(selected_docs),
                selected_snippet_count,
            ),
        },
        "rule_cues": rule_cues,
        "selected_documents": selected_docs,
        "omitted_doc_ids": [
            doc["doc_id"]
            for doc in docs_for_event
            if doc["doc_id"] not in {str(item["doc_id"]) for item in selected_docs}
        ],
    }

    packet_json = json.dumps(packet, sort_keys=True, ensure_ascii=True)
    packet_hash = hashlib.sha1(packet_json.encode("utf-8")).hexdigest()
    packet["packet_hash"] = packet_hash

    index_row = {
        "event_id": event_row["event_id"],
        "source_row_number": event_row["source_row_number"],
        "Drug Name": event_row.get("Drug Name", ""),
        "Active Ingredient": event_row.get("Active Ingredient", ""),
        "Application Number": event_row.get("Application Number", ""),
        "Application Type": event_row.get("Application Type", ""),
        "event_header": event_row.get("event_header", ""),
        "event_date_iso": event_row.get("event_date_iso", ""),
        "supplement_number": event_row.get("supplement_number", ""),
        "linked_doc_count_total": linked_doc_count_total,
        "downloaded_doc_count": downloaded_doc_count,
        "extracted_doc_count": extracted_doc_count,
        "access_restricted_doc_count": access_restricted_doc_count,
        "error_doc_count": error_doc_count,
        "selected_doc_count": len(selected_docs),
        "selected_snippet_count": selected_snippet_count,
        "query_term_count": len(query_terms),
        "packet_type": packet["retrieval"]["packet_type"],
        "packet_hash": packet_hash,
        "packet_char_count": len(json.dumps(packet, ensure_ascii=True)),
        "top_selected_doc_ids": "|".join(str(doc["doc_id"]) for doc in selected_docs[:4]),
        "cue_any_hits": "|".join(cue_any_hits),
    }
    return packet, index_row


def build_report(index_rows: Sequence[Dict[str, object]], packets_path: Path) -> Tuple[Dict[str, object], str]:
    packet_sizes = [int(row["packet_char_count"]) for row in index_rows]
    linked_docs = [int(row["linked_doc_count_total"]) for row in index_rows]
    selected_docs = [int(row["selected_doc_count"]) for row in index_rows]
    selected_snippets = [int(row["selected_snippet_count"]) for row in index_rows]

    cue_counts = Counter()
    packet_type_counts = Counter(row["packet_type"] for row in index_rows)
    for row in index_rows:
        cues = [item for item in str(row["cue_any_hits"]).split("|") if item]
        cue_counts.update(cues)

    stats = {
        "packet_count": len(index_rows),
        "packets_jsonl_path": str(packets_path),
        "packet_type_counts": dict(packet_type_counts),
        "packet_char_mean": round(mean(packet_sizes), 1) if packet_sizes else 0,
        "packet_char_median": median(packet_sizes) if packet_sizes else 0,
        "packet_char_p90": sorted(packet_sizes)[max(0, math.ceil(0.9 * len(packet_sizes)) - 1)]
        if packet_sizes
        else 0,
        "linked_doc_mean": round(mean(linked_docs), 2) if linked_docs else 0,
        "selected_doc_mean": round(mean(selected_docs), 2) if selected_docs else 0,
        "selected_snippet_mean": round(mean(selected_snippets), 2) if selected_snippets else 0,
        "events_with_no_selected_snippets": sum(1 for value in selected_snippets if value == 0),
        "events_with_any_selected_snippet": sum(1 for value in selected_snippets if value > 0),
        "cue_event_counts": dict(sorted(cue_counts.items())),
    }

    lines = [
        "# Annotation Packet Build Report v1",
        "",
        f"- Packet count: `{stats['packet_count']}`",
        f"- Mean packet size (chars): `{stats['packet_char_mean']}`",
        f"- Median packet size (chars): `{stats['packet_char_median']}`",
        f"- P90 packet size (chars): `{stats['packet_char_p90']}`",
        f"- Mean linked docs per event: `{stats['linked_doc_mean']}`",
        f"- Mean selected docs per event: `{stats['selected_doc_mean']}`",
        f"- Mean selected snippets per event: `{stats['selected_snippet_mean']}`",
        f"- Events with any selected snippet: `{stats['events_with_any_selected_snippet']}`",
        f"- Events with no selected snippets: `{stats['events_with_no_selected_snippets']}`",
        "",
        "## Packet Types",
    ]
    for key, value in sorted(packet_type_counts.items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Cue Event Counts"])
    for key, value in sorted(cue_counts.items()):
        lines.append(f"- `{key}`: `{value}`")

    return stats, "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-dir", type=Path, default=BASE_DIR)
    args = parser.parse_args()

    base_dir = args.base_dir.resolve()
    output_dir = base_dir / "annotation_packets"
    output_dir.mkdir(parents=True, exist_ok=True)

    events = load_csv_rows(base_dir / EVENTS_CSV.name)
    event_doc_map = load_csv_rows(base_dir / EVENT_DOC_MAP_CSV.name)
    docs = load_csv_rows(base_dir / DOCS_CSV.name)
    freeze = json.loads((base_dir / FREEZE_JSON.relative_to(BASE_DIR)).read_text())
    design_version = str(freeze["annotation_design_version"])

    docs_by_id = {row["doc_id"]: row for row in docs}
    docs_for_event: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for row in event_doc_map:
        doc_row = docs_by_id.get(row["doc_id"], {})
        merged = dict(row)
        merged.update(doc_row)
        docs_for_event[row["event_id"]].append(merged)

    index_rows: List[Dict[str, object]] = []
    with (output_dir / PACKETS_JSONL.name).open("w") as packets_handle:
        for event_row in events:
            packet, index_row = build_packet(
                event_row,
                docs_for_event.get(event_row["event_id"], []),
                design_version,
            )
            packets_handle.write(json.dumps(packet, ensure_ascii=True) + "\n")
            index_rows.append(index_row)

    with (output_dir / PACKET_INDEX_CSV.name).open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=INDEX_FIELDS)
        writer.writeheader()
        writer.writerows(index_rows)

    stats, report_text = build_report(index_rows, output_dir / PACKETS_JSONL.name)
    (output_dir / PACKET_STATS_JSON.name).write_text(json.dumps(stats, indent=2))
    (output_dir / PACKET_REPORT_MD.name).write_text(report_text)

    print(f"Packets written: {len(index_rows)}")
    print(f"JSONL: {output_dir / PACKETS_JSONL.name}")
    print(f"Index CSV: {output_dir / PACKET_INDEX_CSV.name}")
    print(f"Report: {output_dir / PACKET_REPORT_MD.name}")


if __name__ == "__main__":
    main()
