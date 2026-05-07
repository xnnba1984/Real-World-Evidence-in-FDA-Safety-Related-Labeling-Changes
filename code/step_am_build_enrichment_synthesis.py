from __future__ import annotations

import csv
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = REPO_ROOT / "analysis_outputs" / "enrichment_synthesis"


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def pct(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return 100.0 * numerator / denominator


def to_float(value: str) -> float:
    return float(value) if value not in {"", "NA", "nan", "None"} else float("nan")


def format_pct(value: float) -> str:
    return f"{value:.1f}%"


def format_pr(row: dict[str, str], prefix: str = "PR") -> str:
    pr = float(row["prevalence_ratio"])
    lower = float(row["pr_ci_lower"])
    upper = float(row["pr_ci_upper"])
    return f"{prefix} {pr:.3f} (95% CI {lower:.3f} to {upper:.3f})"


def unique_nonmissing(rows: list[dict[str, str]], app_key: str, value_key: str) -> int:
    return len({row[app_key] for row in rows if row.get(value_key, "").strip() != ""})


def unique_filtered(rows: list[dict[str, str]], app_key: str, predicate) -> int:
    return len({row[app_key] for row in rows if predicate(row)})


def range_summary(
    rows: list[dict[str, str]],
    group_label_key: str,
    main_key: str,
    analytic_key: str,
    exclude_labels: set[str] | None = None,
) -> dict[str, str]:
    exclude_labels = exclude_labels or set()
    usable_rows = [row for row in rows if row[group_label_key] not in exclude_labels]
    main_min = min(usable_rows, key=lambda row: float(row[main_key]))
    main_max = max(usable_rows, key=lambda row: float(row[main_key]))
    analytic_min = min(usable_rows, key=lambda row: float(row[analytic_key]))
    analytic_max = max(usable_rows, key=lambda row: float(row[analytic_key]))
    return {
        "main_range": (
            f"{main_min[group_label_key]} {float(main_min[main_key]):.1f}% to "
            f"{main_max[group_label_key]} {float(main_max[main_key]):.1f}%"
        ),
        "analytic_range": (
            f"{analytic_min[group_label_key]} {float(analytic_min[analytic_key]):.1f}% to "
            f"{analytic_max[group_label_key]} {float(analytic_max[analytic_key]):.1f}%"
        ),
    }


def first_row(rows: list[dict[str, str]], **criteria: str) -> dict[str, str]:
    for row in rows:
        if all(row.get(key) == value for key, value in criteria.items()):
            return row
    raise KeyError(f"Row not found for criteria={criteria}")


def build_rows() -> list[dict[str, str]]:
    therapeutic_table = read_csv_rows(
        REPO_ROOT / "analysis_ready" / "therapeutic_area" / "srlc_analysis_endpoint_layer_therapeutic_area.csv"
    )
    therapeutic_outcomes = read_csv_rows(
        REPO_ROOT / "analysis_outputs" / "therapeutic_area" / "therapeutic_area_outcomes.csv"
    )
    therapeutic_models = read_csv_rows(
        REPO_ROOT / "analysis_outputs" / "therapeutic_area" / "therapeutic_area_models.csv"
    )

    product_age_table = read_csv_rows(
        REPO_ROOT / "analysis_ready" / "product_age" / "srlc_analysis_endpoint_layer_product_age.csv"
    )
    product_age_outcomes = read_csv_rows(
        REPO_ROOT / "analysis_outputs" / "product_age" / "product_age_outcomes.csv"
    )
    product_age_models = read_csv_rows(
        REPO_ROOT / "analysis_outputs" / "product_age" / "product_age_models.csv"
    )

    sponsor_table = read_csv_rows(
        REPO_ROOT
        / "analysis_ready"
        / "sponsor_manufacturer"
        / "srlc_analysis_endpoint_layer_sponsor_manufacturer.csv"
    )
    sponsor_outcomes = read_csv_rows(
        REPO_ROOT / "analysis_outputs" / "sponsor_manufacturer" / "sponsor_manufacturer_outcomes.csv"
    )
    sponsor_models = read_csv_rows(
        REPO_ROOT / "analysis_outputs" / "sponsor_manufacturer" / "sponsor_manufacturer_models.csv"
    )

    event_total = len(product_age_table)
    application_total = len({row["application_number_prefixed"] for row in product_age_table})

    therapeutic_specific_apps = unique_filtered(
        therapeutic_table,
        "application_number_prefixed",
        lambda row: row.get("therapeutic_area_collapsed", "").strip() not in {"", "other_or_multisystem"},
    )
    therapeutic_ranges = range_summary(
        therapeutic_outcomes,
        "therapeutic_area_label",
        "main_public_rwe_pct",
        "analytic_public_rwe_pct",
    )
    therapeutic_main_model = first_row(
        therapeutic_models,
        outcome="y_main_public_rwe",
        term_label="Therapeutic area: Endocrine/reproductive",
    )
    therapeutic_analytic_model = first_row(
        therapeutic_models,
        outcome="y_analytic_public_rwe",
        term_label="Therapeutic area: Endocrine/reproductive",
    )

    product_age_nonmissing_apps = unique_nonmissing(
        product_age_table, "application_number_prefixed", "approval_year"
    )
    product_age_nonmissing_events = sum(1 for row in product_age_table if row.get("approval_year", "").strip() != "")
    product_age_band_rows = [row for row in product_age_outcomes if row.get("group_type") == "product_age_band"]
    product_age_ranges = range_summary(
        product_age_band_rows,
        "group_label",
        "main_public_rwe_pct",
        "analytic_public_rwe_pct",
        exclude_labels={"Unknown"},
    )
    product_age_main_model = first_row(
        product_age_models,
        outcome="y_main_public_rwe",
        term_label="Product age (per 10 years)",
    )
    product_age_analytic_model = first_row(
        product_age_models,
        outcome="y_analytic_public_rwe",
        term_label="Product age (per 10 years)",
    )

    sponsor_nonmissing_apps = unique_nonmissing(
        sponsor_table, "application_number_prefixed", "sponsor_manufacturer_structure"
    )
    sponsor_supported_apps = unique_filtered(
        sponsor_table,
        "application_number_prefixed",
        lambda row: row.get("sponsor_manufacturer_structure", "").strip() != "manufacturer_missing",
    )
    sponsor_structure_rows = [
        row for row in sponsor_outcomes if row.get("group_type") == "sponsor_manufacturer_structure"
    ]
    sponsor_ranges = range_summary(
        sponsor_structure_rows,
        "group_label",
        "main_public_rwe_pct",
        "analytic_public_rwe_pct",
    )
    sponsor_main_model = first_row(
        sponsor_models,
        outcome="y_main_public_rwe",
        term_label="Generic/biosimilar-like company",
    )
    sponsor_analytic_model = first_row(
        sponsor_models,
        outcome="y_analytic_public_rwe",
        term_label="Generic/biosimilar-like company",
    )
    sponsor_missing_main_model = first_row(
        sponsor_models,
        outcome="y_main_public_rwe",
        term_label="Structure: Manufacturer missing",
    )
    sponsor_missing_analytic_model = first_row(
        sponsor_models,
        outcome="y_analytic_public_rwe",
        term_label="Structure: Manufacturer missing",
    )

    rows = [
        {
            "rank_for_paper": "2",
            "enrichment_name": "Therapeutic area",
            "primary_variable": "Collapsed FDA-derived therapeutic-area taxonomy",
            "source_metadata": "FDA drugsfda with FDA label fallback",
            "event_rows": str(event_total),
            "unique_applications": str(application_total),
            "nonmissing_application_n": str(unique_nonmissing(therapeutic_table, "application_number_prefixed", "therapeutic_area_collapsed")),
            "nonmissing_application_pct": format_pct(
                pct(unique_nonmissing(therapeutic_table, "application_number_prefixed", "therapeutic_area_collapsed"), application_total)
            ),
            "support_quality_n": str(therapeutic_specific_apps),
            "support_quality_pct": format_pct(pct(therapeutic_specific_apps, application_total)),
            "support_quality_note": "Applications with a specific non-other classification",
            "main_descriptive_range": therapeutic_ranges["main_range"],
            "analytic_descriptive_range": therapeutic_ranges["analytic_range"],
            "adjusted_main_signal": (
                "Endocrine/reproductive vs oncology: "
                + format_pr(therapeutic_main_model)
            ),
            "adjusted_analytic_signal": (
                "Endocrine/reproductive vs oncology: "
                + format_pr(therapeutic_analytic_model)
            ),
            "interpretability_rating": "Moderate",
            "confounding_risk_rating": "Moderate",
            "policy_value_rating": "Moderate",
            "recommended_manuscript_placement": "Secondary result; brief main-text mention or supplement table",
            "recommended_use_in_paper": (
                "Use to show clinical heterogeneity beyond label section and severity, but avoid treating the taxonomy as a primary causal construct."
            ),
            "editorial_rationale": (
                "Signal is real and large, but classification depends on a rule-based taxonomy and still leaves a meaningful other/multisystem bucket."
            ),
        },
        {
            "rank_for_paper": "1",
            "enrichment_name": "Approval year / product age",
            "primary_variable": "FDA approval year and product age at event",
            "source_metadata": "FDA drugsfda approval history",
            "event_rows": str(event_total),
            "unique_applications": str(application_total),
            "nonmissing_application_n": str(product_age_nonmissing_apps),
            "nonmissing_application_pct": format_pct(pct(product_age_nonmissing_apps, application_total)),
            "support_quality_n": str(product_age_nonmissing_events),
            "support_quality_pct": format_pct(pct(product_age_nonmissing_events, event_total)),
            "support_quality_note": "Events with directly derivable approval-year metadata",
            "main_descriptive_range": product_age_ranges["main_range"],
            "analytic_descriptive_range": product_age_ranges["analytic_range"],
            "adjusted_main_signal": format_pr(product_age_main_model, prefix="PR per 10 years"),
            "adjusted_analytic_signal": format_pr(product_age_analytic_model, prefix="PR per 10 years"),
            "interpretability_rating": "High",
            "confounding_risk_rating": "Low-to-moderate",
            "policy_value_rating": "Moderate-to-high",
            "recommended_manuscript_placement": "Main-text secondary enrichment",
            "recommended_use_in_paper": (
                "Use as the one enrichment result promoted into the core Results section to show a lifecycle gradient in public and analytic RWE documentation."
            ),
            "editorial_rationale": (
                "Coverage is effectively complete, the variable comes directly from FDA approval metadata, and the adjusted signal is stable and straightforward to explain."
            ),
        },
        {
            "rank_for_paper": "3",
            "enrichment_name": "Sponsor / manufacturer",
            "primary_variable": "Sponsor-manufacturer structure plus generic/biosimilar-like flag",
            "source_metadata": "FDA drugsfda sponsor and manufacturer fields",
            "event_rows": str(event_total),
            "unique_applications": str(application_total),
            "nonmissing_application_n": str(sponsor_nonmissing_apps),
            "nonmissing_application_pct": format_pct(pct(sponsor_nonmissing_apps, application_total)),
            "support_quality_n": str(sponsor_supported_apps),
            "support_quality_pct": format_pct(pct(sponsor_supported_apps, application_total)),
            "support_quality_note": "Applications with sponsor-manufacturer structure not driven by manufacturer-missing",
            "main_descriptive_range": sponsor_ranges["main_range"],
            "analytic_descriptive_range": sponsor_ranges["analytic_range"],
            "adjusted_main_signal": (
                "Generic-like flag: "
                + format_pr(sponsor_main_model)
                + "; manufacturer-missing proxy: "
                + format_pr(sponsor_missing_main_model)
            ),
            "adjusted_analytic_signal": (
                "Generic-like flag: "
                + format_pr(sponsor_analytic_model)
                + "; manufacturer-missing proxy: "
                + format_pr(sponsor_missing_analytic_model)
            ),
            "interpretability_rating": "Low-to-moderate",
            "confounding_risk_rating": "High",
            "policy_value_rating": "Low-to-moderate",
            "recommended_manuscript_placement": "Supplement-only exploratory analysis",
            "recommended_use_in_paper": (
                "Keep as hypothesis-generating context only; do not elevate company-type findings into the headline narrative."
            ),
            "editorial_rationale": (
                "The signal is nontrivial, but the construct is heuristic and likely mixes lifecycle, portfolio, and metadata-completeness effects."
            ),
        },
    ]
    return rows


def markdown_table(rows: list[dict[str, str]]) -> str:
    columns = [
        "rank_for_paper",
        "enrichment_name",
        "nonmissing_application_pct",
        "support_quality_pct",
        "main_descriptive_range",
        "analytic_descriptive_range",
        "recommended_manuscript_placement",
    ]
    header = "| " + " | ".join(
        [
            "Rank",
            "Enrichment",
            "Application coverage",
            "Support metric",
            "Main endpoint range",
            "Analytic endpoint range",
            "Placement",
        ]
    ) + " |"
    divider = "| --- | --- | --- | --- | --- | --- | --- |"
    body = []
    for row in sorted(rows, key=lambda item: int(item["rank_for_paper"])):
        body.append(
            "| "
            + " | ".join(
                [
                    row["rank_for_paper"],
                    row["enrichment_name"],
                    row["nonmissing_application_pct"],
                    row["support_quality_pct"],
                    row["main_descriptive_range"],
                    row["analytic_descriptive_range"],
                    row["recommended_manuscript_placement"],
                ]
            )
            + " |"
        )
    return "\n".join([header, divider, *body])


def build_report(rows: list[dict[str, str]]) -> str:
    product_age = next(row for row in rows if row["enrichment_name"] == "Approval year / product age")
    therapeutic = next(row for row in rows if row["enrichment_name"] == "Therapeutic area")
    sponsor = next(row for row in rows if row["enrichment_name"] == "Sponsor / manufacturer")

    return f"""# Enrichment Synthesis Report

## Purpose

This report compares the three completed enrichment analyses on the dimensions that matter for manuscript use:

- data coverage
- construct cleanliness
- descriptive signal
- adjusted signal
- interpretability and policy value
- final main-text versus supplement placement

## Final ranking

1. Approval year / product age
2. Therapeutic area
3. Sponsor / manufacturer

## Cross-enrichment summary

{markdown_table(rows)}

## Final manuscript placement

- `Approval year / product age`: keep in the main paper as the strongest secondary enrichment. It adds a clean lifecycle interpretation without changing the primary endpoint story.
- `Therapeutic area`: keep as a tracked heterogeneity analysis. Use a brief main-text mention only if space allows; otherwise place the full table in the supplement.
- `Sponsor / manufacturer`: keep as exploratory supplement material only. It is useful for reviewer response and context, but it is not a clean enough construct for headline claims.

## Writing-ready interpretation

- The enrichment layer that is most defensible for the paper is product age. Coverage is effectively complete, the derivation is direct from FDA approval history, and the adjusted association remains positive for both the main and analytic endpoints. This gives the paper one concrete lifecycle result: older products are more likely than newer products to have public and analytic RWE documentation tied to safety-labeling changes.
- Therapeutic area adds clear heterogeneity, with much lower documentation in oncology and much higher documentation in endocrine/reproductive, supportive-care/pain, and selected chronic-disease domains. That pattern is worth reporting, but the taxonomy is still a rule-based abstraction and should be framed as heterogeneity rather than as a primary explanatory mechanism.
- Sponsor/manufacturer enrichment also shows signal, but the construct is the least stable. Generic-like flags and manufacturer-missing categories are best interpreted as exploratory proxies that may partly capture lifecycle mix, portfolio composition, or metadata completeness rather than a clean company-type effect.

## Evidence anchors

- `Approval year / product age`
  - descriptive range, main endpoint: {product_age["main_descriptive_range"]}
  - descriptive range, analytic endpoint: {product_age["analytic_descriptive_range"]}
  - adjusted main signal: {product_age["adjusted_main_signal"]}
  - adjusted analytic signal: {product_age["adjusted_analytic_signal"]}
- `Therapeutic area`
  - descriptive range, main endpoint: {therapeutic["main_descriptive_range"]}
  - descriptive range, analytic endpoint: {therapeutic["analytic_descriptive_range"]}
  - adjusted main signal: {therapeutic["adjusted_main_signal"]}
  - adjusted analytic signal: {therapeutic["adjusted_analytic_signal"]}
- `Sponsor / manufacturer`
  - descriptive range, main endpoint: {sponsor["main_descriptive_range"]}
  - descriptive range, analytic endpoint: {sponsor["analytic_descriptive_range"]}
  - adjusted main signal: {sponsor["adjusted_main_signal"]}
  - adjusted analytic signal: {sponsor["adjusted_analytic_signal"]}

## Locked decision

The enrichment phase is complete. No additional sponsor-name mining or new enrichment variables are needed before manuscript drafting. The next step is writing from the locked analytic set, using product age as the promoted enrichment result and treating the other two layers as secondary or exploratory support.
"""


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = build_rows()
    rows = sorted(rows, key=lambda item: int(item["rank_for_paper"]))

    fieldnames = [
        "rank_for_paper",
        "enrichment_name",
        "primary_variable",
        "source_metadata",
        "event_rows",
        "unique_applications",
        "nonmissing_application_n",
        "nonmissing_application_pct",
        "support_quality_n",
        "support_quality_pct",
        "support_quality_note",
        "main_descriptive_range",
        "analytic_descriptive_range",
        "adjusted_main_signal",
        "adjusted_analytic_signal",
        "interpretability_rating",
        "confounding_risk_rating",
        "policy_value_rating",
        "recommended_manuscript_placement",
        "recommended_use_in_paper",
        "editorial_rationale",
    ]
    write_csv(OUTPUT_DIR / "enrichment_comparison_table.csv", rows, fieldnames)
    (OUTPUT_DIR / "enrichment_synthesis_report.md").write_text(
        build_report(rows),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
