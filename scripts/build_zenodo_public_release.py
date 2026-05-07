#!/usr/bin/env python3
"""Build a curated Zenodo public-release package for the SRLC RWE annotation data."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import zipfile
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "zenodo_public_release"
ZIP_PATH = ROOT / f"zenodo_public_release_{date.today().isoformat()}.zip"

SOURCE_DATA = ROOT / "analysis_ready" / "srlc_annotation_analysis_ready.csv"
SOURCE_ISSUE_FLAGS = ROOT / "analysis_ready" / "srlc_annotation_issue_flags.csv"
SOURCE_CODEBOOK = ROOT / "annotation_design" / "annotation_codebook_v2.md"
SOURCE_PIPELINE = ROOT / "analysis_ready" / "annotation_pipeline_summary.md"
SOURCE_RESULTS_SUMMARY = ROOT / "analysis_ready" / "annotation_results_summary.md"
SOURCE_TABLE_DICTIONARY = ROOT / "analysis_ready" / "analysis_ready_table_dictionary.md"
SOURCE_FEATURE_DICTIONARY = ROOT / "analysis_ready" / "analysis_feature_layer_dictionary.md"
SOURCE_COUNTS = ROOT / "analysis_ready" / "annotation_results_counts.csv"
VALIDATION_DIR = ROOT / "analysis_ready" / "human_validation_package" / "final_validation_round_1"


PUBLIC_COLUMN_MAP = [
    ("source_row_number", "source_row_number"),
    ("Drug Name", "drug_name"),
    ("Active Ingredient", "active_ingredient"),
    ("Application Number", "application_number"),
    ("Application Type", "application_type"),
    ("Supplement Date", "supplement_date"),
    ("Database Updated", "database_updated"),
    ("Link", "fda_srlc_event_url"),
    ("drug_name_id", "drug_name_id"),
    ("event_id", "event_id"),
    ("event_sequence_on_page", "event_sequence_on_page"),
    ("event_header", "event_header"),
    ("event_date", "event_date"),
    ("event_date_iso", "event_date_iso"),
    ("supplement_number", "supplement_number"),
    ("label_section_changed", "label_sections_changed"),
    ("event_links_raw", "public_evidence_links"),
    ("strict_primary_cohort", "strict_primary_cohort"),
    ("analytic_cohort", "analytic_cohort"),
    ("direct_relevance_flag", "direct_relevance_flag"),
    ("explicit_public_rwe_any_flag", "explicit_public_rwe_any_flag"),
    ("spontaneous_reports_only_flag", "spontaneous_reports_only_flag"),
    ("method_detail_any_documented_flag", "method_detail_any_documented_flag"),
    ("comparative_design_flag", "comparative_design_flag"),
    ("structured_data_source_flag", "structured_data_source_flag"),
    ("source_group_collapsed", "source_group_collapsed"),
    ("design_group_collapsed", "design_group_collapsed"),
    ("transparency_score_band", "transparency_score_band"),
    ("linked_doc_count", "linked_doc_count"),
    ("downloaded_doc_count", "downloaded_doc_count"),
    ("extracted_doc_count", "extracted_doc_count"),
    ("access_restricted_doc_count", "access_restricted_doc_count"),
    ("error_doc_count", "error_doc_count"),
    ("pdf_doc_count", "pdf_doc_count"),
    ("html_like_doc_count", "html_like_doc_count"),
    ("has_downloaded_doc", "has_downloaded_doc"),
    ("has_extracted_doc", "has_extracted_doc"),
    ("public_evidence_available", "public_evidence_available"),
    ("rwe_documented_publicly", "broad_public_rwe"),
    ("analytic_rwe_documented", "analytic_public_rwe"),
    ("rwe_source_type_primary", "rwe_source_type_primary"),
    ("rwe_source_type_all", "rwe_source_type_all"),
    ("primary_design_category", "primary_design_category"),
    ("confounding_control", "confounding_control"),
    ("missing_data_handling_documented", "missing_data_handling_documented"),
    ("sensitivity_analyses_documented", "sensitivity_analyses_documented"),
    ("negative_controls_documented", "negative_controls_documented"),
    ("evidence_explicitness_tier", "evidence_explicitness_tier"),
    ("analytic_signal_present", "analytic_signal_present"),
    ("annotation_evidence_strength", "annotation_evidence_strength"),
    ("rwe_relevance_to_change", "rwe_relevance_to_change"),
    ("transparency_score", "transparency_score"),
    ("design_stated", "design_stated"),
    ("population_stated", "population_stated"),
    ("comparator_stated", "comparator_stated"),
    ("effect_measure_stated", "effect_measure_stated"),
    ("confounding_strategy_stated", "confounding_strategy_stated"),
    ("missing_data_stated", "missing_data_stated"),
    ("sensitivity_analysis_stated", "sensitivity_analysis_stated"),
    ("uncertainty_measure_stated", "uncertainty_measure_stated"),
    ("annotation_confidence", "annotation_confidence"),
    ("final_label_source", "final_label_source"),
    ("merge_source", "merge_source"),
    ("pre_adjudication_label_source", "pre_adjudication_label_source"),
    ("first_pass_model", "first_pass_model"),
    ("repair_model", "repair_model"),
    ("adjudication_model", "adjudication_model"),
    ("adjudication_applied", "adjudication_applied"),
    ("adjudication_available", "adjudication_available"),
    ("remaining_logic_violation_flag", "remaining_logic_violation_flag"),
    ("remaining_logic_warning_flag", "remaining_logic_warning_flag"),
    ("remaining_grounding_issue_flag", "remaining_grounding_issue_flag"),
    ("hard_issue_flag", "hard_issue_flag"),
    ("remaining_logic_violation_count", "remaining_logic_violation_count"),
    ("remaining_logic_warning_count", "remaining_logic_warning_count"),
    ("remaining_grounding_issue_count", "remaining_grounding_issue_count"),
    ("remaining_logic_violation_types", "remaining_logic_violation_types"),
    ("remaining_logic_warning_types", "remaining_logic_warning_types"),
    ("remaining_grounding_issue_types", "remaining_grounding_issue_types"),
]

EXCLUDED_SOURCE_FIELDS = {
    "change_text",
    "notes",
    "supporting_doc_ids",
    "supporting_evidence_json",
}

PUBLIC_DESCRIPTIONS = {
    "source_row_number": "Row number in the source SRLC event master used for this study.",
    "drug_name": "Drug name as listed in the FDA Safety-related Labeling Changes database export.",
    "active_ingredient": "Active ingredient as listed in the source event table.",
    "application_number": "FDA application number.",
    "application_type": "FDA application type, primarily NDA or BLA.",
    "supplement_date": "Supplement date as listed in the source event table.",
    "database_updated": "Database update date as listed in the source event table.",
    "fda_srlc_event_url": "FDA Safety-related Labeling Changes event page URL.",
    "drug_name_id": "FDA SRLC drug-name identifier parsed from the event page.",
    "event_id": "Internal event identifier used throughout the analysis files.",
    "event_sequence_on_page": "Sequence of the event on the FDA SRLC detail page.",
    "event_header": "Event header text, usually date plus supplement number.",
    "event_date": "Event date as parsed from the source table.",
    "event_date_iso": "Event date in ISO format.",
    "supplement_number": "Parsed supplement number.",
    "label_sections_changed": "Label section or sections changed for the event.",
    "public_evidence_links": "Public FDA-linked evidence or label URLs extracted for the event, when available.",
    "strict_primary_cohort": "Flag for broad public RWE under the study's primary public-RWE measure.",
    "analytic_cohort": "Flag for analytic public RWE under the study's analytically interpretable RWE measure.",
    "direct_relevance_flag": "Flag for RWE judged directly relevant to the labeling change.",
    "explicit_public_rwe_any_flag": "Flag for explicit public RWE or explicit observational real-world terminology.",
    "spontaneous_reports_only_flag": "Flag for events where the public basis was spontaneous reports only.",
    "method_detail_any_documented_flag": "Flag for any documented confounding, missing-data, sensitivity, or negative-control method detail.",
    "comparative_design_flag": "Flag for an annotated comparative observational design.",
    "structured_data_source_flag": "Flag for a structured real-world data source such as claims, EHR, registry, or active surveillance.",
    "source_group_collapsed": "Analysis-friendly collapsed RWE source category.",
    "design_group_collapsed": "Analysis-friendly collapsed design category.",
    "transparency_score_band": "Grouped transparency score category.",
    "linked_doc_count": "Number of public document links identified for the event.",
    "downloaded_doc_count": "Number of linked documents downloaded in the evidence package.",
    "extracted_doc_count": "Number of linked documents with extractable text.",
    "access_restricted_doc_count": "Number of linked documents that were access restricted.",
    "error_doc_count": "Number of linked documents with download or extraction errors.",
    "pdf_doc_count": "Number of linked PDF documents.",
    "html_like_doc_count": "Number of linked HTML-like documents.",
    "has_downloaded_doc": "Whether at least one document was downloaded.",
    "has_extracted_doc": "Whether at least one document had extractable text.",
    "public_evidence_available": "Whether public evidence or label material was available for annotation.",
    "broad_public_rwe": "Primary event-level label for publicly documented RWE, including broader public RWE documentation.",
    "analytic_public_rwe": "Event-level label for analytic public RWE documentation.",
    "rwe_source_type_primary": "Primary annotated real-world data source type.",
    "rwe_source_type_all": "All annotated real-world data source types.",
    "primary_design_category": "Primary annotated study or evidence design category.",
    "confounding_control": "Annotated confounding-control category.",
    "missing_data_handling_documented": "Whether missing-data handling was publicly documented.",
    "sensitivity_analyses_documented": "Whether sensitivity analyses were publicly documented.",
    "negative_controls_documented": "Whether negative-control methods were publicly documented.",
    "evidence_explicitness_tier": "Annotated explicitness tier of the public evidence basis.",
    "analytic_signal_present": "Whether an analytic real-world evidence signal was present in the public record.",
    "annotation_evidence_strength": "Annotation evidence-strength category.",
    "rwe_relevance_to_change": "Annotated relevance of RWE to the safety labeling change.",
    "transparency_score": "0-8 score counting documented analytic transparency components.",
    "design_stated": "Whether the design was stated.",
    "population_stated": "Whether the study population was stated.",
    "comparator_stated": "Whether the comparator was stated.",
    "effect_measure_stated": "Whether an effect measure was stated.",
    "confounding_strategy_stated": "Whether a confounding strategy was stated.",
    "missing_data_stated": "Whether missing-data handling was stated.",
    "sensitivity_analysis_stated": "Whether sensitivity analysis was stated.",
    "uncertainty_measure_stated": "Whether an uncertainty measure was stated.",
    "annotation_confidence": "Final annotation confidence category.",
    "final_label_source": "Annotation stage that supplied the final label.",
    "merge_source": "Merge provenance from the annotation processing pipeline.",
    "pre_adjudication_label_source": "Label source before adjudication.",
    "first_pass_model": "Model recorded for the first-pass annotation stage.",
    "repair_model": "Model recorded for the repair annotation stage, when applicable.",
    "adjudication_model": "Model recorded for the adjudication stage, when applicable.",
    "adjudication_applied": "Whether the event was included in the adjudication pass.",
    "adjudication_available": "Whether adjudication output was available.",
    "remaining_logic_violation_flag": "Residual post-QC logic violation flag.",
    "remaining_logic_warning_flag": "Residual post-QC logic warning flag.",
    "remaining_grounding_issue_flag": "Residual post-QC grounding issue flag.",
    "hard_issue_flag": "Strict residual issue flag used for sensitivity analyses.",
    "remaining_logic_violation_count": "Count of residual logic violations.",
    "remaining_logic_warning_count": "Count of residual logic warnings.",
    "remaining_grounding_issue_count": "Count of residual grounding issues.",
    "remaining_logic_violation_types": "Pipe-delimited residual logic violation categories.",
    "remaining_logic_warning_types": "Pipe-delimited residual logic warning categories.",
    "remaining_grounding_issue_types": "Pipe-delimited residual grounding issue categories.",
}


VALIDATION_COLUMN_MAP = [
    ("validation_sample_id", "validation_sample_id"),
    ("event_id", "event_id"),
    ("Drug Name", "drug_name"),
    ("Active Ingredient", "active_ingredient"),
    ("Application Number", "application_number"),
    ("Application Type", "application_type"),
    ("event_date_iso", "event_date_iso"),
    ("label_section_changed", "label_sections_changed"),
    ("validation_primary_stratum", "validation_primary_stratum"),
    ("annotation_confidence", "annotation_confidence"),
    ("final_label_source", "final_label_source"),
    ("hard_issue_flag", "hard_issue_flag"),
    ("human_consensus_public_evidence_available", "human_consensus_public_evidence_available"),
    ("human_consensus_rwe_documented_publicly", "human_consensus_broad_public_rwe"),
    ("human_consensus_analytic_rwe_documented", "human_consensus_analytic_public_rwe"),
    ("human_consensus_rwe_relevance_to_change", "human_consensus_rwe_relevance_to_change"),
    ("human_consensus_rwe_source_type_primary", "human_consensus_rwe_source_type_primary"),
    ("human_consensus_primary_design_category", "human_consensus_primary_design_category"),
    ("human_consensus_transparency_score", "human_consensus_transparency_score"),
    ("human_consensus_design_stated", "human_consensus_design_stated"),
    ("human_consensus_population_stated", "human_consensus_population_stated"),
    ("human_consensus_comparator_stated", "human_consensus_comparator_stated"),
    ("human_consensus_effect_measure_stated", "human_consensus_effect_measure_stated"),
    ("human_consensus_confounding_strategy_stated", "human_consensus_confounding_strategy_stated"),
    ("human_consensus_missing_data_stated", "human_consensus_missing_data_stated"),
    ("human_consensus_sensitivity_analysis_stated", "human_consensus_sensitivity_analysis_stated"),
    ("human_consensus_uncertainty_measure_stated", "human_consensus_uncertainty_measure_stated"),
    ("public_evidence_available", "machine_public_evidence_available"),
    ("rwe_documented_publicly", "machine_broad_public_rwe"),
    ("analytic_rwe_documented", "machine_analytic_public_rwe"),
    ("rwe_relevance_to_change", "machine_rwe_relevance_to_change"),
    ("rwe_source_type_primary", "machine_rwe_source_type_primary"),
    ("primary_design_category", "machine_primary_design_category"),
    ("transparency_score", "machine_transparency_score"),
]


def reset_output_dir() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "data").mkdir(parents=True)
    (OUT / "docs").mkdir(parents=True)
    (OUT / "validation").mkdir(parents=True)


def read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), list(reader)


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_public_dataset() -> dict[str, int]:
    source_cols, source_rows = read_csv_rows(SOURCE_DATA)
    missing = [src for src, _ in PUBLIC_COLUMN_MAP if src not in source_cols]
    if missing:
        raise RuntimeError(f"Missing expected source columns: {missing}")

    public_cols = [dst for _, dst in PUBLIC_COLUMN_MAP]
    public_rows = []
    for row in source_rows:
        public_rows.append({dst: row.get(src, "") for src, dst in PUBLIC_COLUMN_MAP})
    write_csv(OUT / "data" / "srlc_annotation_public_release.csv", public_cols, public_rows)
    return {"rows": len(public_rows), "columns": len(public_cols)}


def build_validation_consensus_public() -> dict[str, int]:
    source = VALIDATION_DIR / "final_human_consensus_labels.csv"
    source_cols, source_rows = read_csv_rows(source)
    missing = [src for src, _ in VALIDATION_COLUMN_MAP if src not in source_cols]
    if missing:
        raise RuntimeError(f"Missing expected validation columns: {missing}")

    public_cols = [dst for _, dst in VALIDATION_COLUMN_MAP]
    public_rows = []
    for row in source_rows:
        public_rows.append({dst: row.get(src, "") for src, dst in VALIDATION_COLUMN_MAP})
    write_csv(OUT / "validation" / "human_validation_consensus_public.csv", public_cols, public_rows)
    return {"rows": len(public_rows), "columns": len(public_cols)}


def copy_support_files() -> None:
    copies = [
        (SOURCE_ISSUE_FLAGS, OUT / "data" / "srlc_annotation_issue_flags.csv"),
        (SOURCE_COUNTS, OUT / "data" / "annotation_results_counts.csv"),
        (SOURCE_CODEBOOK, OUT / "docs" / "annotation_codebook_v2.md"),
        (SOURCE_PIPELINE, OUT / "docs" / "annotation_pipeline_summary.md"),
        (SOURCE_RESULTS_SUMMARY, OUT / "docs" / "annotation_results_summary.md"),
        (SOURCE_TABLE_DICTIONARY, OUT / "docs" / "analysis_ready_table_dictionary.md"),
        (SOURCE_FEATURE_DICTIONARY, OUT / "docs" / "analysis_feature_layer_dictionary.md"),
        (VALIDATION_DIR / "human_validation_final_report.md", OUT / "validation" / "human_validation_final_report.md"),
        (VALIDATION_DIR / "machine_vs_human_binary_metrics.csv", OUT / "validation" / "machine_vs_human_binary_metrics.csv"),
        (VALIDATION_DIR / "machine_vs_human_confusion_tables.csv", OUT / "validation" / "machine_vs_human_confusion_tables.csv"),
        (VALIDATION_DIR / "machine_vs_human_multiclass_metrics.csv", OUT / "validation" / "machine_vs_human_multiclass_metrics.csv"),
        (VALIDATION_DIR / "machine_vs_human_transparency_metrics.csv", OUT / "validation" / "machine_vs_human_transparency_metrics.csv"),
    ]
    for source, target in copies:
        if not source.exists():
            raise RuntimeError(f"Missing support file: {source}")
        shutil.copy2(source, target)


def write_public_dictionary(public_stats: dict[str, int], validation_stats: dict[str, int]) -> None:
    lines = [
        "# Public Release Data Dictionary",
        "",
        "## Main Dataset",
        "",
        "- File: `data/srlc_annotation_public_release.csv`",
        f"- Rows: `{public_stats['rows']}`",
        f"- Columns: `{public_stats['columns']}`",
        "",
        "This is the curated public-release version of the event-level annotated dataset. It excludes raw labeling-change text, free-text annotation notes, supporting-evidence JSON snippets, and internal reviewer workbooks.",
        "",
        "| Column | Description |",
        "|---|---|",
    ]
    for _, public_col in PUBLIC_COLUMN_MAP:
        desc = PUBLIC_DESCRIPTIONS.get(public_col, "")
        lines.append(f"| `{public_col}` | {desc} |")

    lines.extend(
        [
            "",
            "## Human Validation Consensus Dataset",
            "",
            "- File: `validation/human_validation_consensus_public.csv`",
            f"- Rows: `{validation_stats['rows']}`",
            f"- Columns: `{validation_stats['columns']}`",
            "",
            "This file contains validation-sample event identifiers, final human consensus labels, and corresponding machine labels. It excludes individual reviewer workbooks, free-text reviewer notes, and adjudication worksheet internals.",
            "",
            "| Column | Description |",
            "|---|---|",
        ]
    )
    for _, public_col in VALIDATION_COLUMN_MAP:
        lines.append(f"| `{public_col}` | Public validation-sample field. |")

    lines.extend(
        [
            "",
            "## Excluded Internal Fields",
            "",
            "The following source fields were intentionally excluded from the main public-release CSV:",
            "",
        ]
    )
    for field in sorted(EXCLUDED_SOURCE_FIELDS):
        lines.append(f"- `{field}`")

    lines.append("")
    (OUT / "docs" / "public_release_data_dictionary.md").write_text("\n".join(lines), encoding="utf-8")


def write_readme(public_stats: dict[str, int], validation_stats: dict[str, int]) -> None:
    readme = f"""# SRLC RWE Annotation Public Release

Release date: {date.today().isoformat()}

This folder contains a curated public-release package for the event-level annotation dataset used in the manuscript on public documentation of real-world evidence in FDA safety-related labeling changes.

## Recommended Zenodo Upload Files

- `data/srlc_annotation_public_release.csv`: main event-level clean annotated dataset (`{public_stats['rows']}` rows; `{public_stats['columns']}` columns).
- `docs/public_release_data_dictionary.md`: public-release data dictionary.
- `docs/annotation_codebook_v2.md`: annotation label and scoring definitions.
- `docs/annotation_pipeline_summary.md`: annotation workflow summary.
- `docs/annotation_results_summary.md`: aggregate annotation results summary.
- `data/annotation_results_counts.csv`: aggregate annotation counts.
- `data/srlc_annotation_issue_flags.csv`: residual QC issue flags by event.
- `validation/human_validation_final_report.md`: human validation summary.
- `validation/human_validation_consensus_public.csv`: public validation consensus file (`{validation_stats['rows']}` rows; `{validation_stats['columns']}` columns).
- `validation/machine_vs_human_*`: machine-versus-human validation metric tables.
- `FILE_MANIFEST.csv`: file list with sizes and SHA-256 checksums.

## What Is Not Included

The release intentionally excludes raw annotation runtime files, model prompts, batch artifacts, individual reviewer workbooks, adjudication worksheets, free-text reviewer notes, packet Markdown files, raw labeling-change text, and supporting-evidence JSON snippets. These exclusions keep the release focused on clean, reusable event-level annotations while avoiding unnecessary internal workflow artifacts.

## Suggested Zenodo Description

Event-level annotated dataset for FDA Safety-related Labeling Changes, including public evidence availability, broad public RWE documentation, analytic public RWE documentation, RWE source/design categories, transparency components, annotation provenance, QC flags, and human-validation summary files.

## Suggested License Note

Choose the final Zenodo license before public deposition according to the manuscript team's preference and institutional policy. The event metadata and public links derive from FDA public sources; the annotation labels and derived variables were generated for this study.
"""
    (OUT / "README.md").write_text(readme, encoding="utf-8")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest() -> list[dict[str, str]]:
    descriptions = {
        "README.md": "Top-level release README.",
        "FILE_MANIFEST.csv": "Release file manifest with checksums.",
        "BUILD_REPORT.md": "Build and QC report for this release package.",
        "data/srlc_annotation_public_release.csv": "Main curated public-release annotated event dataset.",
        "data/srlc_annotation_issue_flags.csv": "Residual QC flags by event.",
        "data/annotation_results_counts.csv": "Aggregate annotation counts.",
        "docs/public_release_data_dictionary.md": "Public-release data dictionary.",
        "docs/annotation_codebook_v2.md": "Annotation codebook.",
        "docs/annotation_pipeline_summary.md": "Annotation workflow summary.",
        "docs/annotation_results_summary.md": "Aggregate annotation results summary.",
        "docs/analysis_ready_table_dictionary.md": "Original analysis-ready table dictionary.",
        "docs/analysis_feature_layer_dictionary.md": "Analysis feature-layer dictionary.",
        "validation/human_validation_final_report.md": "Human validation final report.",
        "validation/human_validation_consensus_public.csv": "Curated validation-sample consensus labels and machine labels.",
        "validation/machine_vs_human_binary_metrics.csv": "Machine-versus-human binary validation metrics.",
        "validation/machine_vs_human_confusion_tables.csv": "Machine-versus-human confusion tables.",
        "validation/machine_vs_human_multiclass_metrics.csv": "Machine-versus-human multiclass validation metrics.",
        "validation/machine_vs_human_transparency_metrics.csv": "Machine-versus-human transparency validation metrics.",
    }
    rows = []
    for path in sorted(p for p in OUT.rglob("*") if p.is_file() and p.name != "FILE_MANIFEST.csv"):
        rel = path.relative_to(OUT).as_posix()
        rows.append(
            {
                "path": rel,
                "size_bytes": str(path.stat().st_size),
                "sha256": sha256_file(path),
                "description": descriptions.get(rel, ""),
            }
        )
    write_csv(OUT / "FILE_MANIFEST.csv", ["path", "size_bytes", "sha256", "description"], rows)
    rows.append(
        {
            "path": "FILE_MANIFEST.csv",
            "size_bytes": str((OUT / "FILE_MANIFEST.csv").stat().st_size),
            "sha256": sha256_file(OUT / "FILE_MANIFEST.csv"),
            "description": descriptions["FILE_MANIFEST.csv"],
        }
    )
    return rows


def build_report(public_stats: dict[str, int], validation_stats: dict[str, int], manifest_rows: list[dict[str, str]]) -> None:
    public_header, _ = read_csv_rows(OUT / "data" / "srlc_annotation_public_release.csv")
    forbidden_present = sorted(EXCLUDED_SOURCE_FIELDS.intersection(public_header))
    report = {
        "release_date": date.today().isoformat(),
        "output_folder": str(OUT),
        "zip_file": str(ZIP_PATH),
        "main_public_dataset": public_stats,
        "validation_consensus_dataset": validation_stats,
        "file_count": len([p for p in OUT.rglob("*") if p.is_file()]),
        "forbidden_internal_fields_present": forbidden_present,
    }
    lines = [
        "# Zenodo Public Release Build Report",
        "",
        f"- Release date: `{report['release_date']}`",
        f"- Output folder: `{report['output_folder']}`",
        f"- Zip file: `{report['zip_file']}`",
        f"- Main public dataset rows: `{public_stats['rows']}`",
        f"- Main public dataset columns: `{public_stats['columns']}`",
        f"- Validation consensus rows: `{validation_stats['rows']}`",
        f"- Validation consensus columns: `{validation_stats['columns']}`",
        f"- File count before zip: `{report['file_count']}`",
        f"- Forbidden internal fields present in public CSV: `{', '.join(forbidden_present) if forbidden_present else 'none'}`",
        "",
        "## Machine-Readable Summary",
        "",
        "```json",
        json.dumps(report, indent=2),
        "```",
    ]
    (OUT / "BUILD_REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    build_manifest()


def build_zip() -> None:
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(p for p in OUT.rglob("*") if p.is_file()):
            zf.write(path, arcname=f"{OUT.name}/{path.relative_to(OUT).as_posix()}")


def main() -> None:
    reset_output_dir()
    public_stats = build_public_dataset()
    validation_stats = build_validation_consensus_public()
    copy_support_files()
    write_public_dictionary(public_stats, validation_stats)
    write_readme(public_stats, validation_stats)
    manifest_rows = build_manifest()
    build_report(public_stats, validation_stats, manifest_rows)
    build_zip()
    print(f"Built {OUT}")
    print(f"Built {ZIP_PATH}")
    print(f"Main public dataset: {public_stats['rows']} rows, {public_stats['columns']} columns")
    print(f"Validation consensus: {validation_stats['rows']} rows, {validation_stats['columns']} columns")


if __name__ == "__main__":
    main()
