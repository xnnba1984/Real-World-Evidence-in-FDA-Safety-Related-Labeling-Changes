#!/usr/bin/env python3
"""Build an analysis-ready event table from the final adjudicated annotations."""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Set


REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_DIR = REPO_ROOT
EVENTS_CSV = BASE_DIR / "srlc_events_expanded.csv"
FINAL_ANNOTATIONS_CSV = BASE_DIR / "annotation_production_v2" / "final_adjudicated" / "parsed" / "first_pass_annotations.csv"
EVENT_DOC_MAP_CSV = BASE_DIR / "event_document_map.csv"
EVIDENCE_DOCS_CSV = BASE_DIR / "evidence_documents.csv"
OUT_DIR = BASE_DIR / "analysis_ready"

ANALYSIS_READY_CSV = OUT_DIR / "srlc_annotation_analysis_ready.csv"
ISSUE_FLAGS_CSV = OUT_DIR / "srlc_annotation_issue_flags.csv"
SUMMARY_COUNTS_CSV = OUT_DIR / "annotation_results_counts.csv"
BUILD_REPORT_MD = OUT_DIR / "analysis_ready_build_report.md"
TABLE_DICT_MD = OUT_DIR / "analysis_ready_table_dictionary.md"
RESULTS_SUMMARY_MD = OUT_DIR / "annotation_results_summary.md"

TRANSPARENCY_FIELDS = [
    "design_stated",
    "population_stated",
    "comparator_stated",
    "effect_measure_stated",
    "confounding_strategy_stated",
    "missing_data_stated",
    "sensitivity_analysis_stated",
    "uncertainty_measure_stated",
]


def load_csv_rows(path: Path) -> List[Dict[str, str]]:
    with path.open() as handle:
        return list(csv.DictReader(handle))


def parse_json_array(text: str) -> list:
    if not text:
        return []
    try:
        value = json.loads(text)
    except Exception:  # noqa: BLE001
        return []
    return value if isinstance(value, list) else []


def transparency_score(row: Dict[str, str]) -> int:
    return sum(1 for field in TRANSPARENCY_FIELDS if row.get(field) == "yes")


def transparency_band(score: int) -> str:
    if score == 0:
        return "0"
    if score <= 2:
        return "1_2"
    if score <= 4:
        return "3_4"
    return "5_plus"


def collapse_source(value: str) -> str:
    if value in {"claims", "ehr", "active_surveillance_network"}:
        return "structured_data_or_active_surveillance"
    if value in {"registry", "spontaneous_reports", "other", "unknown"}:
        return value
    return "other"


def collapse_design(value: str) -> str:
    if value in {"cohort_non_active_comparator", "active_comparator_cohort", "case_control", "self_controlled_or_case_only"}:
        return "comparative_or_analytic_observational"
    mapping = {
        "spontaneous_reporting_analysis": "spontaneous_reporting",
        "registry_analysis": "registry_analysis",
        "descriptive_observational": "descriptive_observational",
        "active_surveillance_network_analysis": "active_surveillance_network",
        "unknown": "unknown",
        "other": "other",
    }
    return mapping.get(value, "other")


def build_doc_coverage() -> Dict[str, Dict[str, int]]:
    doc_rows = {row["doc_id"]: row for row in load_csv_rows(EVIDENCE_DOCS_CSV)}
    coverage: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in load_csv_rows(EVENT_DOC_MAP_CSV):
        event_id = row["event_id"]
        doc = doc_rows.get(row["doc_id"], {})
        coverage[event_id]["linked_doc_count"] += 1
        if doc.get("download_status") == "downloaded":
            coverage[event_id]["downloaded_doc_count"] += 1
        if doc.get("text_extract_status") == "extracted":
            coverage[event_id]["extracted_doc_count"] += 1
        if doc.get("download_status") == "access_restricted":
            coverage[event_id]["access_restricted_doc_count"] += 1
        if doc.get("download_status") == "error":
            coverage[event_id]["error_doc_count"] += 1
        if doc.get("content_type", "").startswith("application/pdf") or doc.get("url_type_guess") == "pdf":
            coverage[event_id]["pdf_doc_count"] += 1
        if doc.get("content_type", "").startswith("text/html") or doc.get("url_type_guess") in {"html", "cfm", "aspx"}:
            coverage[event_id]["html_like_doc_count"] += 1
    return coverage


def derive_issue_flags(rows: List[Dict[str, str]]) -> Dict[str, Dict[str, object]]:
    event_to_docs: Dict[str, Set[str]] = defaultdict(set)
    for row in load_csv_rows(EVENT_DOC_MAP_CSV):
        event_to_docs[row["event_id"]].add(row["doc_id"])
    evidence_doc_ids = {row["doc_id"] for row in load_csv_rows(EVIDENCE_DOCS_CSV)}

    issue_map: Dict[str, Dict[str, object]] = {}
    for row in rows:
        event_id = row["event_id"]
        logic_violations: Set[str] = set()
        logic_warnings: Set[str] = set()
        grounding_issues: Set[str] = set()

        if row["analytic_rwe_documented"] == "yes" and row["rwe_documented_publicly"] != "yes":
            logic_violations.add("analytic_yes_without_primary_yes")
        if row["rwe_documented_publicly"] == "yes" and row["rwe_relevance_to_change"] != "direct":
            logic_violations.add("primary_yes_without_direct_relevance")
        if row["public_evidence_available"] == "no" and row["rwe_relevance_to_change"] != "not_apparent":
            logic_violations.add(f"no_public_evidence_with_relevance_{row['rwe_relevance_to_change']}")
        if row["evidence_explicitness_tier"] == "no_public_basis_found" and row["public_evidence_available"] != "no":
            logic_warnings.add("no_public_basis_found_with_public_evidence")
        if row["annotation_evidence_strength"] == "insufficient":
            if not (
                row["public_evidence_available"] == "no"
                and row["rwe_documented_publicly"] == "no"
                and row["analytic_rwe_documented"] == "no"
            ):
                logic_warnings.add("insufficient_strength_conflict")

        source_all = parse_json_array(row.get("rwe_source_type_all", ""))
        if row["rwe_source_type_primary"] == "unknown" and source_all:
            logic_warnings.add("unknown_primary_with_nonempty_sources")
        if row["rwe_source_type_primary"] != "unknown" and source_all and row["rwe_source_type_primary"] not in set(source_all):
            logic_violations.add("primary_source_not_in_all_sources")
        if int(row["transparency_score"]) != transparency_score(row):
            logic_violations.add("transparency_score_mismatch")

        evidence = parse_json_array(row.get("supporting_evidence_json", ""))
        positive_or_method = (
            row["rwe_documented_publicly"] == "yes"
            or row["analytic_rwe_documented"] == "yes"
            or row["missing_data_handling_documented"] == "yes"
            or row["sensitivity_analyses_documented"] == "yes"
            or row["negative_controls_documented"] == "yes"
            or transparency_score(row) > 0
        )
        if positive_or_method and not evidence:
            grounding_issues.add("missing_supporting_evidence")
        if row["public_evidence_available"] == "no" and evidence:
            grounding_issues.add("support_present_despite_no_public_evidence")

        linked_docs = event_to_docs.get(event_id, set())
        for item in evidence:
            doc_id = item.get("doc_id", "")
            if doc_id and doc_id not in evidence_doc_ids:
                grounding_issues.add("unknown_doc_id")
            if doc_id and doc_id not in linked_docs:
                grounding_issues.add("support_doc_not_linked")

        issue_map[event_id] = {
            "remaining_logic_violation_flag": "yes" if logic_violations else "no",
            "remaining_logic_warning_flag": "yes" if logic_warnings else "no",
            "remaining_grounding_issue_flag": "yes" if grounding_issues else "no",
            "hard_issue_flag": "yes" if (logic_violations or grounding_issues) else "no",
            "remaining_logic_violation_count": str(len(logic_violations)),
            "remaining_logic_warning_count": str(len(logic_warnings)),
            "remaining_grounding_issue_count": str(len(grounding_issues)),
            "remaining_logic_violation_types": "|".join(sorted(logic_violations)),
            "remaining_logic_warning_types": "|".join(sorted(logic_warnings)),
            "remaining_grounding_issue_types": "|".join(sorted(grounding_issues)),
        }
    return issue_map


def write_csv(path: Path, rows: List[Dict[str, str]], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_counts(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    subsets = {
        "overall": rows,
        "primary_yes": [row for row in rows if row["rwe_documented_publicly"] == "yes"],
        "analytic_yes": [row for row in rows if row["analytic_rwe_documented"] == "yes"],
    }
    count_rows: List[Dict[str, str]] = []
    fields = [
        "rwe_documented_publicly",
        "analytic_rwe_documented",
        "rwe_source_type_primary",
        "primary_design_category",
        "confounding_control",
        "missing_data_handling_documented",
        "sensitivity_analyses_documented",
        "negative_controls_documented",
        "public_evidence_available",
        "evidence_explicitness_tier",
        "analytic_signal_present",
        "annotation_evidence_strength",
        "rwe_relevance_to_change",
        "transparency_score",
        "transparency_score_band",
        "final_label_source",
        "hard_issue_flag",
    ]
    for subset_name, subset_rows in subsets.items():
        n = len(subset_rows)
        for field in fields:
            counter = Counter(row[field] for row in subset_rows)
            for value, count in counter.most_common():
                count_rows.append(
                    {
                        "subset": subset_name,
                        "subset_n": str(n),
                        "field": field,
                        "value": value,
                        "count": str(count),
                        "pct": f"{(count / n * 100) if n else 0:.4f}",
                    }
                )
    return count_rows


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    event_rows = {row["event_id"]: row for row in load_csv_rows(EVENTS_CSV)}
    annotation_rows = load_csv_rows(FINAL_ANNOTATIONS_CSV)
    coverage = build_doc_coverage()
    issue_map = derive_issue_flags(annotation_rows)

    analysis_rows: List[Dict[str, str]] = []
    issue_rows: List[Dict[str, str]] = []

    for ann in annotation_rows:
        event_id = ann["event_id"]
        event = event_rows[event_id]
        cov = coverage.get(event_id, {})
        issues = issue_map[event_id]
        score = int(ann["transparency_score"])
        method_detail_any = (
            ann["confounding_control"] not in {"none_documented", "unknown"}
            or ann["missing_data_handling_documented"] == "yes"
            or ann["sensitivity_analyses_documented"] == "yes"
            or ann["negative_controls_documented"] == "yes"
        )
        row = {
            **event,
            "strict_primary_cohort": "yes" if ann["rwe_documented_publicly"] == "yes" else "no",
            "analytic_cohort": "yes" if ann["analytic_rwe_documented"] == "yes" else "no",
            "direct_relevance_flag": "yes" if ann["rwe_relevance_to_change"] == "direct" else "no",
            "explicit_public_rwe_any_flag": "yes" if ann["evidence_explicitness_tier"] in {"explicit_rwe", "explicit_observational_real_world"} else "no",
            "spontaneous_reports_only_flag": "yes" if ann["evidence_explicitness_tier"] == "spontaneous_reports_only" else "no",
            "method_detail_any_documented_flag": "yes" if method_detail_any else "no",
            "comparative_design_flag": "yes" if ann["primary_design_category"] in {"cohort_non_active_comparator", "active_comparator_cohort", "case_control", "self_controlled_or_case_only"} else "no",
            "structured_data_source_flag": "yes" if ann["rwe_source_type_primary"] in {"claims", "ehr", "active_surveillance_network"} else "no",
            "source_group_collapsed": collapse_source(ann["rwe_source_type_primary"]),
            "design_group_collapsed": collapse_design(ann["primary_design_category"]),
            "transparency_score_band": transparency_band(score),
            "linked_doc_count": str(cov.get("linked_doc_count", 0)),
            "downloaded_doc_count": str(cov.get("downloaded_doc_count", 0)),
            "extracted_doc_count": str(cov.get("extracted_doc_count", 0)),
            "access_restricted_doc_count": str(cov.get("access_restricted_doc_count", 0)),
            "error_doc_count": str(cov.get("error_doc_count", 0)),
            "pdf_doc_count": str(cov.get("pdf_doc_count", 0)),
            "html_like_doc_count": str(cov.get("html_like_doc_count", 0)),
            "has_downloaded_doc": "yes" if cov.get("downloaded_doc_count", 0) > 0 else "no",
            "has_extracted_doc": "yes" if cov.get("extracted_doc_count", 0) > 0 else "no",
            **{k: ann[k] for k in [
                "rwe_documented_publicly",
                "analytic_rwe_documented",
                "rwe_source_type_primary",
                "rwe_source_type_all",
                "primary_design_category",
                "confounding_control",
                "missing_data_handling_documented",
                "sensitivity_analyses_documented",
                "negative_controls_documented",
                "public_evidence_available",
                "evidence_explicitness_tier",
                "analytic_signal_present",
                "annotation_evidence_strength",
                "rwe_relevance_to_change",
                "transparency_score",
                "design_stated",
                "population_stated",
                "comparator_stated",
                "effect_measure_stated",
                "confounding_strategy_stated",
                "missing_data_stated",
                "sensitivity_analysis_stated",
                "uncertainty_measure_stated",
                "annotation_confidence",
                "notes",
                "supporting_doc_ids",
                "supporting_evidence_json",
                "final_label_source",
                "merge_source",
                "pre_adjudication_label_source",
                "first_pass_model",
                "repair_model",
                "adjudication_model",
                "adjudication_applied",
                "adjudication_available",
            ]},
            **issues,
        }
        analysis_rows.append(row)
        issue_rows.append({"event_id": event_id, **issues})

    analysis_rows.sort(key=lambda r: r["event_id"])
    issue_rows.sort(key=lambda r: r["event_id"])

    analysis_fieldnames = list(analysis_rows[0].keys())
    write_csv(ANALYSIS_READY_CSV, analysis_rows, analysis_fieldnames)
    write_csv(ISSUE_FLAGS_CSV, issue_rows, list(issue_rows[0].keys()))

    count_rows = build_counts(analysis_rows)
    write_csv(SUMMARY_COUNTS_CSV, count_rows, list(count_rows[0].keys()))

    n = len(analysis_rows)
    primary_yes = sum(1 for row in analysis_rows if row["rwe_documented_publicly"] == "yes")
    analytic_yes = sum(1 for row in analysis_rows if row["analytic_rwe_documented"] == "yes")
    hard_issue = sum(1 for row in analysis_rows if row["hard_issue_flag"] == "yes")
    extracted = sum(1 for row in analysis_rows if row["has_extracted_doc"] == "yes")

    BUILD_REPORT_MD.write_text(
        "\n".join(
            [
                "# Analysis-Ready Build Report",
                "",
                f"- Input final annotations: `{FINAL_ANNOTATIONS_CSV}`",
                f"- Input event table: `{EVENTS_CSV}`",
                f"- Output analysis-ready table: `{ANALYSIS_READY_CSV}`",
                f"- Rows: `{n}`",
                f"- Primary yes: `{primary_yes}`",
                f"- Analytic yes: `{analytic_yes}`",
                f"- Hard issue rows: `{hard_issue}`",
                f"- Rows with extracted docs: `{extracted}`",
                f"- Summary counts CSV: `{SUMMARY_COUNTS_CSV}`",
                f"- Issue flags CSV: `{ISSUE_FLAGS_CSV}`",
            ]
        )
        + "\n"
    )

    TABLE_DICT_MD.write_text(
        "\n".join(
            [
                "# Analysis-Ready Table Dictionary",
                "",
                "Core source columns come from the event master `srlc_events_expanded.csv` and preserve event identity, drug metadata, label section, and `change_text`.",
                "",
                "## Recommended analysis columns",
                "",
                "- `strict_primary_cohort`: `yes` when `rwe_documented_publicly = yes`.",
                "- `analytic_cohort`: `yes` when `analytic_rwe_documented = yes`.",
                "- `direct_relevance_flag`: `yes` when `rwe_relevance_to_change = direct`.",
                "- `explicit_public_rwe_any_flag`: `yes` when `evidence_explicitness_tier` is `explicit_rwe` or `explicit_observational_real_world`.",
                "- `spontaneous_reports_only_flag`: `yes` when the public basis is spontaneous reports only.",
                "- `method_detail_any_documented_flag`: `yes` if any confounding, missing-data, sensitivity, or negative-control method detail is documented.",
                "- `source_group_collapsed`: analysis-friendly collapse of the primary source label.",
                "- `design_group_collapsed`: analysis-friendly collapse of the design label.",
                "- `transparency_score_band`: `0`, `1_2`, `3_4`, or `5_plus`.",
                "- `has_downloaded_doc` / `has_extracted_doc`: event-level evidence availability flags from the downloaded evidence package.",
                "- `hard_issue_flag`: `yes` when a residual hard logic violation or grounding issue remains after adjudication.",
                "- `remaining_logic_violation_types`, `remaining_logic_warning_types`, `remaining_grounding_issue_types`: pipe-delimited QC issue categories for sensitivity analyses.",
                "- `final_label_source`: where the current final labels came from: `first_pass`, `repair`, or `adjudication`.",
                "- `adjudication_applied`: `yes` if the event was reviewed in the third-run adjudication pass.",
                "",
                "## Recommended sensitivity exclusions",
                "",
                "- Exclude `hard_issue_flag = yes` for a strict sensitivity analysis.",
                "- Stratify by `final_label_source` to show how much the repair/adjudication stages changed results.",
                "- Restrict to `has_extracted_doc = yes` if you want an evidence-availability sensitivity cohort.",
            ]
        )
        + "\n"
    )

    RESULTS_SUMMARY_MD.write_text(
        "\n".join(
            [
                "# Annotation Results Summary",
                "",
                f"- Total events: `{n}`",
                f"- `rwe_documented_publicly = yes`: `{primary_yes}` (`{primary_yes / n * 100:.1f}%`)",
                f"- `analytic_rwe_documented = yes`: `{analytic_yes}` (`{analytic_yes / n * 100:.1f}%`)",
                f"- `hard_issue_flag = yes`: `{hard_issue}` (`{hard_issue / n * 100:.1f}%`)",
                "",
                "Key pattern: public evidence is often available, but explicit analytic RWE and deeper methodological transparency are much rarer.",
            ]
        )
        + "\n"
    )

    print(f"Analysis-ready CSV: {ANALYSIS_READY_CSV}")
    print(f"Issue flags CSV: {ISSUE_FLAGS_CSV}")
    print(f"Summary counts CSV: {SUMMARY_COUNTS_CSV}")
    print(f"Build report: {BUILD_REPORT_MD}")
    print(f"Table dictionary: {TABLE_DICT_MD}")
    print(f"Results summary: {RESULTS_SUMMARY_MD}")


if __name__ == "__main__":
    main()
