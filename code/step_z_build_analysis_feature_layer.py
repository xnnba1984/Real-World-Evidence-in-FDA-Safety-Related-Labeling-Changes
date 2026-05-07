#!/usr/bin/env python3
"""Build the derived feature layer used for downstream analysis."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_DIR = REPO_ROOT
IN_CSV = BASE_DIR / "analysis_ready" / "srlc_annotation_analysis_ready.csv"
OUT_DIR = BASE_DIR / "analysis_ready"

OUT_CSV = OUT_DIR / "srlc_analysis_feature_layer.csv"
DICT_MD = OUT_DIR / "analysis_feature_layer_dictionary.md"
QC_MD = OUT_DIR / "analysis_feature_layer_qc.md"


SECTION_ORDER = [
    "Boxed Warning",
    "Contraindications",
    "Warnings and Precautions",
    "Adverse Reactions",
    "Drug Interactions",
    "Use in Specific Populations",
    "PCI/PI/MG",
    "Other",
]

SECTION_FLAG_MAP = {
    "Boxed Warning": "section_boxed_warning",
    "Contraindications": "section_contraindications",
    "Warnings and Precautions": "section_warnings_precautions",
    "Adverse Reactions": "section_adverse_reactions",
    "Drug Interactions": "section_drug_interactions",
    "Use in Specific Populations": "section_use_in_specific_populations",
    "PCI/PI/MG": "section_patient_labeling",
    "Other": "section_other_safety",
}

SECTION_SHORT_MAP = {
    "Boxed Warning": "boxed_warning",
    "Contraindications": "contraindications",
    "Warnings and Precautions": "warnings_precautions",
    "Adverse Reactions": "adverse_reactions",
    "Drug Interactions": "drug_interactions",
    "Use in Specific Populations": "use_in_specific_populations",
    "PCI/PI/MG": "patient_labeling",
    "Other": "other",
}


def yes_no(flag: bool) -> str:
    return "yes" if flag else "no"


def normalize_section_tokens(value: object) -> list[str]:
    if pd.isna(value):
        return []
    tokens = [part.strip() for part in str(value).split(";") if part.strip()]
    return tokens


def normalize_change_text(text: object) -> str:
    if pd.isna(text):
        return ""
    normalized = str(text).lower()
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def method_detail_score(row: pd.Series) -> int:
    score = 0
    if row["confounding_control"] not in {"none_documented", "unknown"}:
        score += 1
    for field in [
        "missing_data_handling_documented",
        "sensitivity_analyses_documented",
        "negative_controls_documented",
    ]:
        if row[field] == "yes":
            score += 1
    return score


def funnel_stage(row: pd.Series) -> str:
    if row["public_evidence_available"] != "yes":
        return "no_public_evidence"
    if row["rwe_documented_publicly"] != "yes":
        return "public_evidence_no_rwe"
    if row["analytic_rwe_documented"] != "yes":
        return "documented_rwe_nonanalytic"
    if int(row["method_detail_score"]) > 0:
        return "documented_analytic_rwe_with_method_detail"
    return "documented_analytic_rwe"


def doc_coverage_band(row: pd.Series) -> str:
    linked = int(row["linked_doc_count"])
    downloaded = int(row["downloaded_doc_count"])
    extracted = int(row["extracted_doc_count"])
    if linked == 0:
        return "no_linked_docs"
    if extracted >= 2:
        return "extracted_2_plus"
    if extracted == 1:
        return "extracted_1"
    if downloaded >= 1:
        return "downloaded_no_extracted"
    return "linked_no_download"


def issue_burden_band(score: int) -> str:
    if score == 0:
        return "0"
    if score == 1:
        return "1"
    if score <= 3:
        return "2_3"
    return "4_plus"


def primary_section_group(row: pd.Series) -> str:
    for token in SECTION_ORDER:
        if row[SECTION_FLAG_MAP[token]] == "yes":
            return SECTION_SHORT_MAP[token]
    return "unknown"


def severity_tier(row: pd.Series) -> int:
    if row["section_boxed_warning"] == "yes":
        return 3
    if row["section_contraindications"] == "yes" or row["section_warnings_precautions"] == "yes":
        return 2
    return 1


def severity_tier_label(value: int) -> str:
    if value == 3:
        return "tier_3_boxed_warning"
    if value == 2:
        return "tier_2_contra_or_warnings"
    return "tier_1_other_safety_only"


def transparency_score_band(score: int) -> str:
    if score == 0:
        return "0"
    if score <= 2:
        return "1_2"
    if score <= 4:
        return "3_4"
    return "5_plus"


def build_dictionary() -> str:
    return """# Analysis Feature Layer Dictionary

This table extends the base analysis-ready table:
- [<repository-root>/analysis_ready/srlc_annotation_analysis_ready.csv](<repository-root>/analysis_ready/srlc_annotation_analysis_ready.csv)

It preserves all original columns and adds derived fields for downstream descriptive analyses, sensitivity analyses, and modeling.

## Time variables

- `event_year`: calendar year from `event_date_iso`
- `event_month`: calendar month number from `event_date_iso`
- `event_quarter`: quarter label `Q1`-`Q4`
- `year_trend_window_flag`: `yes` for `2016-2025`, `no` otherwise. This is for trend-specific analyses only and is not the default cohort restriction.

## Section normalization

Derived from `label_section_changed`:

- `section_boxed_warning`
- `section_contraindications`
- `section_warnings_precautions`
- `section_adverse_reactions`
- `section_drug_interactions`
- `section_use_in_specific_populations`
- `section_patient_labeling`
- `section_other_safety`

Additional helpers:

- `normalized_section_signature`: pipe-delimited ordered section signature
- `section_count`: number of changed normalized section groups, including patient labeling and `Other`
- `safety_section_count`: number of changed safety sections excluding patient labeling
- `primary_section_group`: highest-priority normalized section group present in the event

## Severity variables

- `severity_tier`: integer severity proxy
  - `3` if boxed warning
  - `2` if contraindications or warnings/precautions without boxed warning
  - `1` otherwise
- `severity_tier_label`: descriptive label for the severity tier

## Funnel / method variables

- `method_detail_score`: count of documented method-detail components:
  - confounding control documented
  - missing-data handling documented
  - sensitivity analyses documented
  - negative controls documented
- `any_method_detail_flag`: `yes` if `method_detail_score > 0`
- `public_documentation_funnel_stage`:
  - `no_public_evidence`
  - `public_evidence_no_rwe`
  - `documented_rwe_nonanalytic`
  - `documented_analytic_rwe`
  - `documented_analytic_rwe_with_method_detail`

## Document coverage variables

- `doc_coverage_band`:
  - `no_linked_docs`
  - `linked_no_download`
  - `downloaded_no_extracted`
  - `extracted_1`
  - `extracted_2_plus`

## QC / issue burden variables

- `issue_burden_score`: simple sum of remaining logic violations, logic warnings, and grounding issues
- `issue_burden_band`: `0`, `1`, `2_3`, `4_plus`

## Duplicate-cluster sensitivity variables

- `change_text_signature`: 16-character SHA1 prefix of normalized `change_text`
- `event_cluster_id_sensitivity`: cluster key based on application number, date, supplement number, normalized section signature, and `change_text` signature
- `event_cluster_size_sensitivity`: number of events sharing the sensitivity cluster key
"""


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(IN_CSV)
    input_rows = len(df)

    df["event_date_dt"] = pd.to_datetime(df["event_date_iso"], errors="coerce")
    df["event_year"] = df["event_date_dt"].dt.year.astype("Int64")
    df["event_month"] = df["event_date_dt"].dt.month.astype("Int64")
    df["event_quarter"] = "Q" + df["event_date_dt"].dt.quarter.astype("Int64").astype(str)
    df["year_trend_window_flag"] = df["event_year"].between(2016, 2025, inclusive="both").map(yes_no)

    raw_section_tokens = []
    unresolved_counter: Counter[str] = Counter()
    section_signature_values = []
    section_count_values = []
    safety_section_count_values = []

    known_tokens = set(SECTION_ORDER)
    for value in df["label_section_changed"]:
        tokens = normalize_section_tokens(value)
        raw_section_tokens.append(tokens)
        unresolved = [token for token in tokens if token not in known_tokens]
        for token in unresolved:
            unresolved_counter[token] += 1
        ordered_present = [token for token in SECTION_ORDER if token in tokens]
        section_signature_values.append("|".join(SECTION_SHORT_MAP[token] for token in ordered_present))
        section_count_values.append(len(ordered_present))
        safety_section_count_values.append(
            sum(1 for token in ordered_present if token not in {"PCI/PI/MG", "Other"})
        )

    df["_section_tokens"] = raw_section_tokens
    for token, flag_name in SECTION_FLAG_MAP.items():
        df[flag_name] = df["_section_tokens"].apply(lambda tokens, token=token: yes_no(token in tokens))

    df["normalized_section_signature"] = section_signature_values
    df["section_count"] = section_count_values
    df["safety_section_count"] = safety_section_count_values
    df["primary_section_group"] = df.apply(primary_section_group, axis=1)
    df["severity_tier"] = df.apply(severity_tier, axis=1)
    df["severity_tier_label"] = df["severity_tier"].apply(severity_tier_label)

    df["method_detail_score"] = df.apply(method_detail_score, axis=1)
    df["any_method_detail_flag"] = df["method_detail_score"].gt(0).map(yes_no)
    df["public_documentation_funnel_stage"] = df.apply(funnel_stage, axis=1)

    df["doc_coverage_band"] = df.apply(doc_coverage_band, axis=1)
    df["issue_burden_score"] = (
        pd.to_numeric(df["remaining_logic_violation_count"], errors="coerce").fillna(0).astype(int)
        + pd.to_numeric(df["remaining_logic_warning_count"], errors="coerce").fillna(0).astype(int)
        + pd.to_numeric(df["remaining_grounding_issue_count"], errors="coerce").fillna(0).astype(int)
    )
    df["issue_burden_band"] = df["issue_burden_score"].apply(issue_burden_band)

    df["change_text_signature"] = df["change_text"].apply(
        lambda value: hashlib.sha1(normalize_change_text(value).encode("utf-8")).hexdigest()[:16]
    )
    df["event_cluster_id_sensitivity"] = df.apply(
        lambda row: "|".join(
            [
                str(row["Application Number"]),
                str(row["event_date_iso"]),
                f"SUPPL-{int(row['supplement_number'])}" if pd.notna(row["supplement_number"]) else "SUPPL-NA",
                row["normalized_section_signature"] or "no_section",
                row["change_text_signature"],
            ]
        ),
        axis=1,
    )
    cluster_sizes = df["event_cluster_id_sensitivity"].value_counts()
    df["event_cluster_size_sensitivity"] = df["event_cluster_id_sensitivity"].map(cluster_sizes).astype(int)

    # Keep consistent band definition here as a sanity check even though it already exists upstream.
    df["feature_layer_transparency_score_band"] = df["transparency_score"].astype(int).apply(transparency_score_band)

    df = df.drop(columns=["event_date_dt", "_section_tokens"])
    df.to_csv(OUT_CSV, index=False)
    DICT_MD.write_text(build_dictionary())

    section_token_counter = Counter(token for tokens in raw_section_tokens for token in tokens)
    severity_counter = Counter(df["severity_tier_label"])
    funnel_counter = Counter(df["public_documentation_funnel_stage"])
    coverage_counter = Counter(df["doc_coverage_band"])
    issue_counter = Counter(df["issue_burden_band"])
    year_counter = Counter(df["event_year"].astype(str))
    duplicate_clusters = cluster_sizes[cluster_sizes > 1]

    qc_lines = [
        "# Analysis Feature Layer QC",
        "",
        f"- input table: `{IN_CSV}`",
        f"- output table: `{OUT_CSV}`",
        f"- input rows: `{input_rows}`",
        f"- output rows: `{len(df)}`",
        "",
        "## Time coverage",
        "",
        f"- year_trend_window_flag = yes: `{int((df['year_trend_window_flag'] == 'yes').sum())}`",
        f"- year_trend_window_flag = no: `{int((df['year_trend_window_flag'] == 'no').sum())}`",
        "",
        "Event counts by year:",
        "",
    ]
    for year, count in sorted(year_counter.items()):
        qc_lines.append(f"- `{year}`: `{count}`")

    qc_lines.extend(["", "## Section token coverage", ""])
    for token in SECTION_ORDER:
        qc_lines.append(f"- `{token}`: `{section_token_counter.get(token, 0)}`")
    qc_lines.extend(
        [
            "",
            f"- unresolved raw section tokens: `{sum(unresolved_counter.values())}`",
        ]
    )
    if unresolved_counter:
        qc_lines.append("")
        qc_lines.append("Unresolved token counts:")
        qc_lines.append("")
        for token, count in unresolved_counter.most_common():
            qc_lines.append(f"- `{token}`: `{count}`")

    qc_lines.extend(["", "## Severity distribution", ""])
    for label, count in sorted(severity_counter.items()):
        qc_lines.append(f"- `{label}`: `{count}`")

    qc_lines.extend(["", "## Funnel-stage distribution", ""])
    for label, count in sorted(funnel_counter.items()):
        qc_lines.append(f"- `{label}`: `{count}`")

    qc_lines.extend(["", "## Document coverage band distribution", ""])
    for label, count in sorted(coverage_counter.items()):
        qc_lines.append(f"- `{label}`: `{count}`")

    qc_lines.extend(["", "## Issue burden band distribution", ""])
    for label, count in sorted(issue_counter.items()):
        qc_lines.append(f"- `{label}`: `{count}`")

    qc_lines.extend(
        [
            "",
            "## Duplicate-cluster summary",
            "",
            f"- unique event clusters: `{cluster_sizes.shape[0]}`",
            f"- clusters with more than one event: `{duplicate_clusters.shape[0]}`",
            f"- max cluster size: `{int(cluster_sizes.max())}`",
        ]
    )
    if not duplicate_clusters.empty:
        qc_lines.extend(["", "Largest duplicate clusters:", ""])
        for cluster_id, size in duplicate_clusters.head(10).items():
            example_events = df.loc[df["event_cluster_id_sensitivity"] == cluster_id, "event_id"].head(5).tolist()
            qc_lines.append(f"- `{cluster_id}`: `{int(size)}` events; examples: `{', '.join(example_events)}`")

    QC_MD.write_text("\n".join(qc_lines) + "\n")


if __name__ == "__main__":
    main()
