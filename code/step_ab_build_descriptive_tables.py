#!/usr/bin/env python3
"""Build descriptive analysis tables and figure datasets."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_DIR = REPO_ROOT
IN_CSV = BASE_DIR / "analysis_ready" / "srlc_analysis_endpoint_layer.csv"
OUT_DIR = BASE_DIR / "analysis_outputs"

TABLE1 = OUT_DIR / "table1_cohort_description.csv"
TABLE2 = OUT_DIR / "table2_primary_outcomes.csv"
TABLE3 = OUT_DIR / "table3_source_design_transparency.csv"
SUPP_YEAR_APP = OUT_DIR / "supplement_year_application_type_outcomes.csv"
SUPP_SECTION = OUT_DIR / "supplement_section_severity_outcomes.csv"
SUPP_LABEL_SOURCE = OUT_DIR / "supplement_outcome_by_label_source.csv"
SUPP_CONFIDENCE = OUT_DIR / "supplement_outcome_by_annotation_confidence.csv"
SUPP_HARD_ISSUE = OUT_DIR / "supplement_outcome_by_hard_issue_flag.csv"
SUPP_TRANSPARENCY_COMPONENTS = OUT_DIR / "supplement_transparency_components_by_subset.csv"
FIG1 = OUT_DIR / "figure1_funnel.csv"
FIG2 = OUT_DIR / "figure2_annual_trends.csv"
FIG3 = OUT_DIR / "figure3_section_severity_counts.csv"
FIG4 = OUT_DIR / "figure4_explicitness_counts.csv"
FIG5 = OUT_DIR / "figure5_transparency_distribution.csv"
REPORT = OUT_DIR / "descriptive_tables_report.md"


TRANSPARENCY_COMPONENTS = [
    "design_stated",
    "population_stated",
    "comparator_stated",
    "effect_measure_stated",
    "confounding_strategy_stated",
    "missing_data_stated",
    "sensitivity_analysis_stated",
    "uncertainty_measure_stated",
]

SECTION_FLAGS = [
    ("section_boxed_warning", "Boxed Warning"),
    ("section_contraindications", "Contraindications"),
    ("section_warnings_precautions", "Warnings and Precautions"),
    ("section_adverse_reactions", "Adverse Reactions"),
    ("section_drug_interactions", "Drug Interactions"),
    ("section_use_in_specific_populations", "Use in Specific Populations"),
    ("section_patient_labeling", "Patient Labeling"),
]

ENDPOINT_FIELDS = [
    ("endpoint_main_public_rwe", "Main public RWE"),
    ("endpoint_secondary_analytic_public_rwe", "Analytic public RWE"),
    ("endpoint_sens_explicit_public_rwe", "Explicit public RWE"),
    ("endpoint_sens_non_spontaneous_public_rwe", "Public RWE excluding spontaneous-only"),
    ("endpoint_sens_qc_strict_public_rwe", "QC-strict public RWE"),
]


def pct(numer: int, denom: int) -> float:
    return round((numer / denom * 100) if denom else 0.0, 4)


def add_rows(rows: list[dict], section: str, variable: str, value: str, count: int, denom: int) -> None:
    rows.append(
        {
            "section": section,
            "variable": variable,
            "value": value,
            "count": count,
            "denominator": denom,
            "pct": pct(count, denom),
        }
    )


def build_table1(df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    n = len(df)
    add_rows(rows, "overall", "events", "all", n, n)

    ordered_fields = ["Application Type", "event_year", "severity_tier_label", "doc_coverage_band", "hard_issue_flag", "final_label_source"]
    for field in ordered_fields:
        counter = Counter(df[field])
        if field == "event_year":
            items = sorted(counter.items(), key=lambda x: (str(x[0])))
        else:
            items = sorted(counter.items(), key=lambda x: str(x[0]))
        for value, count in items:
            add_rows(rows, field, field, str(value), int(count), n)

    for flag, label in SECTION_FLAGS:
        count = int((df[flag] == "yes").sum())
        add_rows(rows, "section_flags", flag, label, count, n)

    return pd.DataFrame(rows)


def build_table2(df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    n = len(df)

    for field, label in ENDPOINT_FIELDS:
        yes_n = int((df[field] == "yes").sum())
        add_rows(rows, "endpoint", field, label, yes_n, n)

    for field, label in [
        ("public_evidence_available", "Public evidence available"),
        ("endpoint_main_public_rwe", "Main public RWE"),
        ("endpoint_secondary_analytic_public_rwe", "Analytic public RWE"),
    ]:
        yes_n = int((df[field] == "yes").sum())
        add_rows(rows, "documentation_backbone", field, label, yes_n, n)

    return pd.DataFrame(rows)


def subset_distribution(df: pd.DataFrame, subset_name: str, field: str) -> list[dict]:
    n = len(df)
    rows: list[dict] = []
    counter = Counter(df[field])
    for value, count in counter.items():
        rows.append(
            {
                "subset": subset_name,
                "subset_n": n,
                "field": field,
                "value": str(value),
                "count": int(count),
                "pct": pct(int(count), n),
            }
        )
    return rows


def build_table3(df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    subsets = {
        "main_public_rwe_positive": df[df["endpoint_main_public_rwe"] == "yes"],
        "analytic_public_rwe_positive": df[df["endpoint_secondary_analytic_public_rwe"] == "yes"],
    }
    fields = [
        "rwe_source_type_primary",
        "primary_design_category",
        "confounding_control",
        "transparency_score_band",
        "annotation_evidence_strength",
        "method_detail_score",
        "missing_data_handling_documented",
        "sensitivity_analyses_documented",
        "negative_controls_documented",
    ]
    for subset_name, subset_df in subsets.items():
        for field in fields:
            rows.extend(subset_distribution(subset_df, subset_name, field))
    return pd.DataFrame(rows)


def build_year_app_table(df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    for (year, app_type), group in df.groupby(["event_year", "Application Type"], dropna=False):
        denom = len(group)
        for field, label in ENDPOINT_FIELDS[:3]:
            yes_n = int((group[field] == "yes").sum())
            rows.append(
                {
                    "event_year": int(year),
                    "application_type": app_type,
                    "endpoint": field,
                    "endpoint_label": label,
                    "count_yes": yes_n,
                    "denominator": denom,
                    "pct_yes": pct(yes_n, denom),
                }
            )
    return pd.DataFrame(rows)


def build_section_severity_table(df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    for flag, label in SECTION_FLAGS:
        group = df[df[flag] == "yes"]
        denom = len(group)
        for field, endpoint_label in ENDPOINT_FIELDS[:3]:
            yes_n = int((group[field] == "yes").sum())
            rows.append(
                {
                    "group_type": "section_flag",
                    "group_value": flag,
                    "group_label": label,
                    "endpoint": field,
                    "endpoint_label": endpoint_label,
                    "count_yes": yes_n,
                    "denominator": denom,
                    "pct_yes": pct(yes_n, denom),
                }
            )
    for severity, group in df.groupby("severity_tier_label"):
        denom = len(group)
        for field, endpoint_label in ENDPOINT_FIELDS[:3]:
            yes_n = int((group[field] == "yes").sum())
            rows.append(
                {
                    "group_type": "severity_tier",
                    "group_value": severity,
                    "group_label": severity,
                    "endpoint": field,
                    "endpoint_label": endpoint_label,
                    "count_yes": yes_n,
                    "denominator": denom,
                    "pct_yes": pct(yes_n, denom),
                }
            )
    return pd.DataFrame(rows)


def build_outcome_by(df: pd.DataFrame, stratifier: str) -> pd.DataFrame:
    rows: list[dict] = []
    for value, group in df.groupby(stratifier, dropna=False):
        denom = len(group)
        for field, label in ENDPOINT_FIELDS:
            yes_n = int((group[field] == "yes").sum())
            rows.append(
                {
                    "stratifier": stratifier,
                    "stratum": str(value),
                    "endpoint": field,
                    "endpoint_label": label,
                    "count_yes": yes_n,
                    "denominator": denom,
                    "pct_yes": pct(yes_n, denom),
                }
            )
    return pd.DataFrame(rows)


def build_transparency_components(df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    subsets = {
        "all_events": df,
        "main_public_rwe_positive": df[df["endpoint_main_public_rwe"] == "yes"],
        "analytic_public_rwe_positive": df[df["endpoint_secondary_analytic_public_rwe"] == "yes"],
    }
    for subset_name, subset_df in subsets.items():
        denom = len(subset_df)
        for field in TRANSPARENCY_COMPONENTS:
            yes_n = int((subset_df[field] == "yes").sum())
            rows.append(
                {
                    "subset": subset_name,
                    "component": field,
                    "count_yes": yes_n,
                    "denominator": denom,
                    "pct_yes": pct(yes_n, denom),
                }
            )
    return pd.DataFrame(rows)


def build_funnel(df: pd.DataFrame) -> pd.DataFrame:
    stage_order = [
        "all_events",
        "public_evidence_available",
        "main_public_rwe",
        "analytic_public_rwe",
        "analytic_public_rwe_with_method_detail",
    ]
    counts = {
        "all_events": len(df),
        "public_evidence_available": int((df["public_evidence_available"] == "yes").sum()),
        "main_public_rwe": int((df["endpoint_main_public_rwe"] == "yes").sum()),
        "analytic_public_rwe": int((df["endpoint_secondary_analytic_public_rwe"] == "yes").sum()),
        "analytic_public_rwe_with_method_detail": int(
            (df["public_documentation_funnel_stage"] == "documented_analytic_rwe_with_method_detail").sum()
        ),
    }
    rows = []
    total = len(df)
    prev = total
    for stage in stage_order:
        count = counts[stage]
        rows.append(
            {
                "stage_order": stage_order.index(stage) + 1,
                "stage": stage,
                "count": count,
                "pct_of_total": pct(count, total),
                "pct_of_previous_stage": pct(count, prev),
            }
        )
        prev = count
    return pd.DataFrame(rows)


def build_annual_trends(df: pd.DataFrame) -> pd.DataFrame:
    trend_df = df[df["year_trend_window_flag"] == "yes"].copy()
    rows: list[dict] = []
    for year, group in trend_df.groupby("event_year"):
        denom = len(group)
        for field, label in [
            ("public_evidence_available", "Public evidence available"),
            ("endpoint_main_public_rwe", "Main public RWE"),
            ("endpoint_secondary_analytic_public_rwe", "Analytic public RWE"),
        ]:
            yes_n = int((group[field] == "yes").sum())
            rows.append(
                {
                    "event_year": int(year),
                    "series": field,
                    "series_label": label,
                    "count_yes": yes_n,
                    "denominator": denom,
                    "pct_yes": pct(yes_n, denom),
                }
            )
        mean_transparency = round(float(group["transparency_score"].mean()), 4)
        pct_transparency_3 = pct(int((group["transparency_score"] >= 3).sum()), denom)
        rows.append(
            {
                "event_year": int(year),
                "series": "mean_transparency_score",
                "series_label": "Mean transparency score",
                "count_yes": mean_transparency,
                "denominator": denom,
                "pct_yes": mean_transparency,
            }
        )
        rows.append(
            {
                "event_year": int(year),
                "series": "transparency_score_ge_3",
                "series_label": "Transparency score >= 3",
                "count_yes": int((group["transparency_score"] >= 3).sum()),
                "denominator": denom,
                "pct_yes": pct_transparency_3,
            }
        )
    return pd.DataFrame(rows)


def build_section_severity_fig(df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    for flag, label in SECTION_FLAGS:
        group = df[df[flag] == "yes"]
        denom = len(group)
        for field, endpoint_label in ENDPOINT_FIELDS[:2]:
            yes_n = int((group[field] == "yes").sum())
            rows.append(
                {
                    "dimension": "section",
                    "group": label,
                    "endpoint": field,
                    "endpoint_label": endpoint_label,
                    "count_yes": yes_n,
                    "denominator": denom,
                    "pct_yes": pct(yes_n, denom),
                }
            )
    for label, group in df.groupby("severity_tier_label"):
        denom = len(group)
        for field, endpoint_label in ENDPOINT_FIELDS[:2]:
            yes_n = int((group[field] == "yes").sum())
            rows.append(
                {
                    "dimension": "severity",
                    "group": label,
                    "endpoint": field,
                    "endpoint_label": endpoint_label,
                    "count_yes": yes_n,
                    "denominator": denom,
                    "pct_yes": pct(yes_n, denom),
                }
            )
    return pd.DataFrame(rows)


def build_explicitness_fig(df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    overall_denom = len(df)
    for value, count in Counter(df["evidence_explicitness_tier"]).items():
        rows.append(
            {
                "panel": "overall",
                "group": "overall",
                "evidence_explicitness_tier": value,
                "count": int(count),
                "denominator": overall_denom,
                "pct": pct(int(count), overall_denom),
            }
        )
    for app_type, group in df.groupby("Application Type"):
        denom = len(group)
        for value, count in Counter(group["evidence_explicitness_tier"]).items():
            rows.append(
                {
                    "panel": "application_type",
                    "group": app_type,
                    "evidence_explicitness_tier": value,
                    "count": int(count),
                    "denominator": denom,
                    "pct": pct(int(count), denom),
                }
            )
    return pd.DataFrame(rows)


def build_transparency_fig(df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    subsets = {
        "all_events": df,
        "main_public_rwe_positive": df[df["endpoint_main_public_rwe"] == "yes"],
        "analytic_public_rwe_positive": df[df["endpoint_secondary_analytic_public_rwe"] == "yes"],
    }
    for subset_name, subset_df in subsets.items():
        denom = len(subset_df)
        for score, count in Counter(subset_df["transparency_score"]).items():
            rows.append(
                {
                    "subset": subset_name,
                    "score": int(score),
                    "count": int(count),
                    "denominator": denom,
                    "pct": pct(int(count), denom),
                }
            )
    return pd.DataFrame(rows)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(IN_CSV)

    table1 = build_table1(df)
    table2 = build_table2(df)
    table3 = build_table3(df)
    supp_year_app = build_year_app_table(df)
    supp_section = build_section_severity_table(df)
    supp_label_source = build_outcome_by(df, "final_label_source")
    supp_confidence = build_outcome_by(df, "annotation_confidence")
    supp_hard_issue = build_outcome_by(df, "hard_issue_flag")
    supp_transparency = build_transparency_components(df)

    fig1 = build_funnel(df)
    fig2 = build_annual_trends(df)
    fig3 = build_section_severity_fig(df)
    fig4 = build_explicitness_fig(df)
    fig5 = build_transparency_fig(df)

    table1.to_csv(TABLE1, index=False)
    table2.to_csv(TABLE2, index=False)
    table3.to_csv(TABLE3, index=False)
    supp_year_app.to_csv(SUPP_YEAR_APP, index=False)
    supp_section.to_csv(SUPP_SECTION, index=False)
    supp_label_source.to_csv(SUPP_LABEL_SOURCE, index=False)
    supp_confidence.to_csv(SUPP_CONFIDENCE, index=False)
    supp_hard_issue.to_csv(SUPP_HARD_ISSUE, index=False)
    supp_transparency.to_csv(SUPP_TRANSPARENCY_COMPONENTS, index=False)
    fig1.to_csv(FIG1, index=False)
    fig2.to_csv(FIG2, index=False)
    fig3.to_csv(FIG3, index=False)
    fig4.to_csv(FIG4, index=False)
    fig5.to_csv(FIG5, index=False)

    total_n = len(df)
    main_n = int((df["endpoint_main_public_rwe"] == "yes").sum())
    analytic_n = int((df["endpoint_secondary_analytic_public_rwe"] == "yes").sum())
    explicit_n = int((df["endpoint_sens_explicit_public_rwe"] == "yes").sum())
    method_detail_analytic_n = int(
        (df["public_documentation_funnel_stage"] == "documented_analytic_rwe_with_method_detail").sum()
    )

    boxed = df[df["section_boxed_warning"] == "yes"]
    boxed_main = int((boxed["endpoint_main_public_rwe"] == "yes").sum())
    boxed_analytic = int((boxed["endpoint_secondary_analytic_public_rwe"] == "yes").sum())

    report_lines = [
        "# Descriptive Tables Report",
        "",
        f"- input endpoint layer: `{IN_CSV}`",
        f"- total events: `{total_n}`",
        "",
        "## Key descriptive results",
        "",
        f"- main public RWE endpoint: `{main_n}` ({pct(main_n, total_n)}%)",
        f"- analytic public RWE endpoint: `{analytic_n}` ({pct(analytic_n, total_n)}%)",
        f"- explicit public RWE sensitivity endpoint: `{explicit_n}` ({pct(explicit_n, total_n)}%)",
        f"- analytic positives with any documented method detail: `{method_detail_analytic_n}` ({pct(method_detail_analytic_n, analytic_n)}% of analytic positives)",
        "",
        "## Boxed warning signals",
        "",
        f"- boxed warning events: `{len(boxed)}`",
        f"- boxed warning events with main public RWE: `{boxed_main}` ({pct(boxed_main, len(boxed))}%)",
        f"- boxed warning events with analytic public RWE: `{boxed_analytic}` ({pct(boxed_analytic, len(boxed))}%)",
        "",
        "## Output files",
        "",
        f"- `{TABLE1}`",
        f"- `{TABLE2}`",
        f"- `{TABLE3}`",
        f"- `{SUPP_YEAR_APP}`",
        f"- `{SUPP_SECTION}`",
        f"- `{SUPP_LABEL_SOURCE}`",
        f"- `{SUPP_CONFIDENCE}`",
        f"- `{SUPP_HARD_ISSUE}`",
        f"- `{SUPP_TRANSPARENCY_COMPONENTS}`",
        f"- `{FIG1}`",
        f"- `{FIG2}`",
        f"- `{FIG3}`",
        f"- `{FIG4}`",
        f"- `{FIG5}`",
        "",
        "## Notes",
        "",
        "- All descriptive tables use the full cohort, including 2026 events.",
        "- The annual trend figure dataset uses `year_trend_window_flag = yes` and is therefore restricted to the trend window.",
        "- Figure datasets are plot-ready long-format summaries, while the table outputs are analysis-facing count tables.",
    ]
    REPORT.write_text("\n".join(report_lines) + "\n")


if __name__ == "__main__":
    main()
