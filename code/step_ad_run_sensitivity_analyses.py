#!/usr/bin/env python3
"""Run pre-specified sensitivity analyses for the SrLC annotation study."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf


REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_DIR = REPO_ROOT
IN_CSV = BASE_DIR / "analysis_ready" / "srlc_analysis_endpoint_layer.csv"
OUT_DIR = BASE_DIR / "analysis_outputs"

SUMMARY_CSV = OUT_DIR / "sensitivity_summary.csv"
PREVALENCE_CSV = OUT_DIR / "sensitivity_prevalence_tables.csv"
MODEL_RESULTS_CSV = OUT_DIR / "sensitivity_model_results.csv"
MODEL_FIT_CSV = OUT_DIR / "sensitivity_model_fit_summary.csv"
REPORT_MD = OUT_DIR / "sensitivity_report.md"


SECTION_PREDICTORS = [
    "section_boxed_warning_num",
    "section_contraindications_num",
    "section_warnings_precautions_num",
    "section_adverse_reactions_num",
    "section_drug_interactions_num",
    "section_use_in_specific_populations_num",
]

ENDPOINTS = [
    ("endpoint_main_public_rwe", "Main public RWE endpoint", "main"),
    ("endpoint_secondary_analytic_public_rwe", "Analytic public RWE endpoint", "secondary"),
    ("endpoint_sens_explicit_public_rwe", "Explicit public RWE sensitivity endpoint", "sensitivity"),
    ("endpoint_sens_non_spontaneous_public_rwe", "Non-spontaneous public RWE sensitivity endpoint", "sensitivity"),
    ("endpoint_sens_qc_strict_public_rwe", "QC-strict public RWE sensitivity endpoint", "sensitivity"),
]


def yes_no_to_num(series: pd.Series) -> pd.Series:
    return series.fillna("no").eq("yes").astype(int)


def prepare_model_df(df: pd.DataFrame) -> pd.DataFrame:
    model_df = df.copy()
    model_df["application_number_cluster"] = model_df["Application Number"].astype(str)
    model_df["app_type"] = model_df["Application Type"].astype(str)
    model_df["year_centered"] = model_df["event_year"].astype(float) - 2020.0

    for src, dst in [
        ("endpoint_main_public_rwe", "y_main_public_rwe"),
        ("endpoint_secondary_analytic_public_rwe", "y_analytic_public_rwe"),
        ("endpoint_sens_non_spontaneous_public_rwe", "y_non_spontaneous_public_rwe"),
    ]:
        model_df[dst] = yes_no_to_num(model_df[src])

    for src, dst in [
        ("section_boxed_warning", "section_boxed_warning_num"),
        ("section_contraindications", "section_contraindications_num"),
        ("section_warnings_precautions", "section_warnings_precautions_num"),
        ("section_adverse_reactions", "section_adverse_reactions_num"),
        ("section_drug_interactions", "section_drug_interactions_num"),
        ("section_use_in_specific_populations", "section_use_in_specific_populations_num"),
    ]:
        model_df[dst] = yes_no_to_num(model_df[src])
    return model_df


def collapse_duplicate_clusters(df: pd.DataFrame) -> pd.DataFrame:
    collapsed = (
        df.sort_values(["source_row_number", "event_id"], kind="stable")
        .drop_duplicates(subset=["event_cluster_id_sensitivity"], keep="first")
        .copy()
    )
    return collapsed


def prevalence_rows(
    df: pd.DataFrame,
    scenario_name: str,
    scenario_label: str,
    scenario_group: str,
    outcome_specs: list[tuple[str, str, str]],
    baseline_pct_lookup: dict[str, float],
    stratum_name: str | None = None,
    stratum_value: str | None = None,
) -> list[dict]:
    rows: list[dict] = []
    n_obs = len(df)
    for outcome_col, outcome_label, outcome_role in outcome_specs:
        yes_n = int(yes_no_to_num(df[outcome_col]).sum())
        pct_yes = (yes_n / n_obs * 100.0) if n_obs else np.nan
        baseline_pct = baseline_pct_lookup.get(outcome_col, np.nan)
        rows.append(
            {
                "scenario_name": scenario_name,
                "scenario_label": scenario_label,
                "scenario_group": scenario_group,
                "stratum_name": stratum_name or "",
                "stratum_value": stratum_value or "",
                "outcome": outcome_col,
                "outcome_label": outcome_label,
                "outcome_role": outcome_role,
                "n_obs": n_obs,
                "n_yes": yes_n,
                "pct_yes": pct_yes,
                "baseline_pct_yes": baseline_pct,
                "delta_pct_points_from_baseline": pct_yes - baseline_pct if pd.notna(baseline_pct) else np.nan,
                "relative_ratio_vs_baseline": (pct_yes / baseline_pct) if pd.notna(baseline_pct) and baseline_pct > 0 else np.nan,
            }
        )
    return rows


def fit_modified_poisson(
    data: pd.DataFrame,
    outcome: str,
    outcome_label: str,
    formula_rhs: str,
    model_name: str,
    scenario_name: str,
    scenario_label: str,
) -> tuple[pd.DataFrame, dict]:
    formula = f"{outcome} ~ {formula_rhs}"
    model = smf.glm(formula=formula, data=data, family=sm.families.Poisson())
    result = model.fit(cov_type="cluster", cov_kwds={"groups": data["application_number_cluster"]})

    conf = result.conf_int()
    rows = []
    for term in result.params.index:
        coef = float(result.params[term])
        lower = float(conf.loc[term, 0])
        upper = float(conf.loc[term, 1])
        rows.append(
            {
                "scenario_name": scenario_name,
                "scenario_label": scenario_label,
                "model_name": model_name,
                "outcome": outcome,
                "outcome_label": outcome_label,
                "formula": formula,
                "term": term,
                "term_label": prettify_term(term),
                "coef_log": coef,
                "std_err": float(result.bse[term]),
                "z_value": float(result.tvalues[term]),
                "p_value": float(result.pvalues[term]),
                "ci_lower_log": lower,
                "ci_upper_log": upper,
                "prevalence_ratio": float(np.exp(coef)),
                "pr_ci_lower": float(np.exp(lower)),
                "pr_ci_upper": float(np.exp(upper)),
                "n_obs": int(result.nobs),
                "n_positive": int(data[outcome].sum()),
                "n_clusters": int(data["application_number_cluster"].nunique()),
                "converged": bool(result.converged),
                "aic": float(result.aic),
            }
        )

    fit_summary = {
        "scenario_name": scenario_name,
        "scenario_label": scenario_label,
        "model_name": model_name,
        "outcome": outcome,
        "outcome_label": outcome_label,
        "formula": formula,
        "n_obs": int(result.nobs),
        "n_positive": int(data[outcome].sum()),
        "n_clusters": int(data["application_number_cluster"].nunique()),
        "converged": bool(result.converged),
        "aic": float(result.aic),
        "llf": float(result.llf),
    }
    return pd.DataFrame(rows), fit_summary


def prettify_term(term: str) -> str:
    mapping = {
        "Intercept": "Intercept",
        "year_centered": "Calendar year (per 1 year)",
        "C(app_type)[T.NDA]": "NDA vs BLA",
        "section_boxed_warning_num": "Boxed Warning present",
        "section_contraindications_num": "Contraindications present",
        "section_warnings_precautions_num": "Warnings and Precautions present",
        "section_adverse_reactions_num": "Adverse Reactions present",
        "section_drug_interactions_num": "Drug Interactions present",
        "section_use_in_specific_populations_num": "Use in Specific Populations present",
    }
    return mapping.get(term, term)


def top_terms(df: pd.DataFrame, model_name: str, n_terms: int = 5) -> pd.DataFrame:
    subset = df[(df["model_name"] == model_name) & (df["term"] != "Intercept")].copy()
    subset = subset.sort_values(["p_value", "prevalence_ratio"], ascending=[True, False], kind="stable")
    return subset.head(n_terms)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(IN_CSV)

    baseline_pct_lookup = {}
    for outcome_col, _, _ in ENDPOINTS:
        baseline_pct_lookup[outcome_col] = yes_no_to_num(df[outcome_col]).mean() * 100.0

    summary_rows: list[dict] = []
    prevalence_output_rows: list[dict] = []

    baseline_df = df.copy()
    summary_rows.append(
        {
            "scenario_name": "baseline_full_cohort",
            "scenario_label": "Baseline full cohort",
            "scenario_group": "baseline",
            "n_obs": len(baseline_df),
            "unique_applications": baseline_df["Application Number"].astype(str).nunique(),
            "unique_event_clusters": baseline_df["event_cluster_id_sensitivity"].astype(str).nunique(),
            "collapsed_clusters_applied": "no",
            "subset_rule": "none",
        }
    )
    prevalence_output_rows.extend(
        prevalence_rows(
            baseline_df,
            scenario_name="baseline_full_cohort",
            scenario_label="Baseline full cohort",
            scenario_group="baseline_endpoint_ladder",
            outcome_specs=ENDPOINTS,
            baseline_pct_lookup=baseline_pct_lookup,
        )
    )

    subset_scenarios = [
        ("qc_strict_no_hard_issue", "QC-strict: exclude hard issues", lambda x: x[x["hard_issue_flag"] == "no"].copy(), "hard_issue_flag = no"),
        ("extracted_doc_only", "Extracted-doc only", lambda x: x[x["has_extracted_doc"] == "yes"].copy(), "has_extracted_doc = yes"),
        (
            "confidence_high_medium",
            "Confidence restricted: high or medium",
            lambda x: x[x["annotation_confidence"].isin(["high", "medium"])].copy(),
            "annotation_confidence in {high, medium}",
        ),
        (
            "confidence_high_only",
            "Confidence restricted: high only",
            lambda x: x[x["annotation_confidence"] == "high"].copy(),
            "annotation_confidence = high",
        ),
        (
            "logic_warning_excluded",
            "Aggressive warning exclusion",
            lambda x: x[x["remaining_logic_warning_flag"] == "no"].copy(),
            "remaining_logic_warning_flag = no",
        ),
        (
            "duplicate_cluster_collapsed",
            "Duplicate-cluster collapsed",
            collapse_duplicate_clusters,
            "one row per event_cluster_id_sensitivity",
        ),
    ]

    for name, label, subset_fn, subset_rule in subset_scenarios:
        subset_df = subset_fn(df)
        summary_rows.append(
            {
                "scenario_name": name,
                "scenario_label": label,
                "scenario_group": "subset_restriction",
                "n_obs": len(subset_df),
                "unique_applications": subset_df["Application Number"].astype(str).nunique(),
                "unique_event_clusters": subset_df["event_cluster_id_sensitivity"].astype(str).nunique(),
                "collapsed_clusters_applied": "yes" if name == "duplicate_cluster_collapsed" else "no",
                "subset_rule": subset_rule,
            }
        )
        prevalence_output_rows.extend(
            prevalence_rows(
                subset_df,
                scenario_name=name,
                scenario_label=label,
                scenario_group="subset_restriction",
                outcome_specs=[
                    ("endpoint_main_public_rwe", "Main public RWE endpoint", "main"),
                    ("endpoint_secondary_analytic_public_rwe", "Analytic public RWE endpoint", "secondary"),
                ],
                baseline_pct_lookup=baseline_pct_lookup,
            )
        )

    for source_value, source_df in df.groupby("final_label_source", dropna=False):
        source_value_str = str(source_value)
        scenario_name = f"provenance_{source_value_str}"
        scenario_label = f"Provenance stratum: {source_value_str}"
        summary_rows.append(
            {
                "scenario_name": scenario_name,
                "scenario_label": scenario_label,
                "scenario_group": "provenance_stratification",
                "n_obs": len(source_df),
                "unique_applications": source_df["Application Number"].astype(str).nunique(),
                "unique_event_clusters": source_df["event_cluster_id_sensitivity"].astype(str).nunique(),
                "collapsed_clusters_applied": "no",
                "subset_rule": f"final_label_source = {source_value_str}",
            }
        )
        prevalence_output_rows.extend(
            prevalence_rows(
                source_df,
                scenario_name=scenario_name,
                scenario_label=scenario_label,
                scenario_group="provenance_stratification",
                outcome_specs=[
                    ("endpoint_main_public_rwe", "Main public RWE endpoint", "main"),
                    ("endpoint_secondary_analytic_public_rwe", "Analytic public RWE endpoint", "secondary"),
                ],
                baseline_pct_lookup=baseline_pct_lookup,
                stratum_name="final_label_source",
                stratum_value=source_value_str,
            )
        )

    summary_df = pd.DataFrame(summary_rows).sort_values(["scenario_group", "scenario_name"], kind="stable")
    prevalence_df = pd.DataFrame(prevalence_output_rows).sort_values(
        ["scenario_group", "scenario_name", "outcome_role", "outcome"],
        kind="stable",
    )

    model_df = prepare_model_df(df)
    rhs = "year_centered + C(app_type) + " + " + ".join(SECTION_PREDICTORS)

    model_scenarios = [
        (
            "baseline_main_public_rwe",
            "Baseline full cohort",
            lambda x: x.copy(),
            "y_main_public_rwe",
            "Main public RWE endpoint",
            "sens_model_main_public_rwe_baseline",
        ),
        (
            "qc_strict_main_public_rwe",
            "QC-strict: exclude hard issues",
            lambda x: x[x["hard_issue_flag"] == "no"].copy(),
            "y_main_public_rwe",
            "Main public RWE endpoint",
            "sens_model_main_public_rwe_qc_strict",
        ),
        (
            "extracted_doc_main_public_rwe",
            "Extracted-doc only",
            lambda x: x[x["has_extracted_doc"] == "yes"].copy(),
            "y_main_public_rwe",
            "Main public RWE endpoint",
            "sens_model_main_public_rwe_extracted_doc",
        ),
        (
            "duplicate_collapsed_main_public_rwe",
            "Duplicate-cluster collapsed",
            collapse_duplicate_clusters,
            "y_main_public_rwe",
            "Main public RWE endpoint",
            "sens_model_main_public_rwe_duplicate_collapsed",
        ),
        (
            "non_spontaneous_main_public_rwe",
            "Alternative outcome: non-spontaneous public RWE",
            lambda x: x.copy(),
            "y_non_spontaneous_public_rwe",
            "Non-spontaneous public RWE sensitivity endpoint",
            "sens_model_main_public_rwe_non_spontaneous",
        ),
        (
            "baseline_analytic_public_rwe",
            "Baseline full cohort",
            lambda x: x.copy(),
            "y_analytic_public_rwe",
            "Analytic public RWE endpoint",
            "sens_model_analytic_public_rwe_baseline",
        ),
        (
            "qc_strict_analytic_public_rwe",
            "QC-strict: exclude hard issues",
            lambda x: x[x["hard_issue_flag"] == "no"].copy(),
            "y_analytic_public_rwe",
            "Analytic public RWE endpoint",
            "sens_model_analytic_public_rwe_qc_strict",
        ),
        (
            "extracted_doc_analytic_public_rwe",
            "Extracted-doc only",
            lambda x: x[x["has_extracted_doc"] == "yes"].copy(),
            "y_analytic_public_rwe",
            "Analytic public RWE endpoint",
            "sens_model_analytic_public_rwe_extracted_doc",
        ),
        (
            "duplicate_collapsed_analytic_public_rwe",
            "Duplicate-cluster collapsed",
            collapse_duplicate_clusters,
            "y_analytic_public_rwe",
            "Analytic public RWE endpoint",
            "sens_model_analytic_public_rwe_duplicate_collapsed",
        ),
    ]

    model_result_frames = []
    fit_rows = []
    for scenario_name, scenario_label, subset_fn, outcome, outcome_label, model_name in model_scenarios:
        model_subset = subset_fn(model_df)
        result_df, fit_row = fit_modified_poisson(
            data=model_subset,
            outcome=outcome,
            outcome_label=outcome_label,
            formula_rhs=rhs,
            model_name=model_name,
            scenario_name=scenario_name,
            scenario_label=scenario_label,
        )
        model_result_frames.append(result_df)
        fit_rows.append(fit_row)

    model_results_df = pd.concat(model_result_frames, ignore_index=True)
    fit_summary_df = pd.DataFrame(fit_rows)

    summary_df.to_csv(SUMMARY_CSV, index=False)
    prevalence_df.to_csv(PREVALENCE_CSV, index=False)
    model_results_df.to_csv(MODEL_RESULTS_CSV, index=False)
    fit_summary_df.to_csv(MODEL_FIT_CSV, index=False)

    main_prev = baseline_pct_lookup["endpoint_main_public_rwe"]
    analytic_prev = baseline_pct_lookup["endpoint_secondary_analytic_public_rwe"]
    explicit_prev = baseline_pct_lookup["endpoint_sens_explicit_public_rwe"]
    non_sp_prev = baseline_pct_lookup["endpoint_sens_non_spontaneous_public_rwe"]
    qc_prev = baseline_pct_lookup["endpoint_sens_qc_strict_public_rwe"]

    qc_main_prev = float(
        prevalence_df.loc[
            (prevalence_df["scenario_name"] == "qc_strict_no_hard_issue")
            & (prevalence_df["outcome"] == "endpoint_main_public_rwe"),
            "pct_yes",
        ].iloc[0]
    )
    extracted_main_prev = float(
        prevalence_df.loc[
            (prevalence_df["scenario_name"] == "extracted_doc_only")
            & (prevalence_df["outcome"] == "endpoint_main_public_rwe"),
            "pct_yes",
        ].iloc[0]
    )
    duplicate_main_prev = float(
        prevalence_df.loc[
            (prevalence_df["scenario_name"] == "duplicate_cluster_collapsed")
            & (prevalence_df["outcome"] == "endpoint_main_public_rwe"),
            "pct_yes",
        ].iloc[0]
    )
    high_med_main_prev = float(
        prevalence_df.loc[
            (prevalence_df["scenario_name"] == "confidence_high_medium")
            & (prevalence_df["outcome"] == "endpoint_main_public_rwe"),
            "pct_yes",
        ].iloc[0]
    )
    high_only_main_prev = float(
        prevalence_df.loc[
            (prevalence_df["scenario_name"] == "confidence_high_only")
            & (prevalence_df["outcome"] == "endpoint_main_public_rwe"),
            "pct_yes",
        ].iloc[0]
    )
    warning_excluded_main_prev = float(
        prevalence_df.loc[
            (prevalence_df["scenario_name"] == "logic_warning_excluded")
            & (prevalence_df["outcome"] == "endpoint_main_public_rwe"),
            "pct_yes",
        ].iloc[0]
    )
    duplicate_analytic_prev = float(
        prevalence_df.loc[
            (prevalence_df["scenario_name"] == "duplicate_cluster_collapsed")
            & (prevalence_df["outcome"] == "endpoint_secondary_analytic_public_rwe"),
            "pct_yes",
        ].iloc[0]
    )

    top_main_baseline = top_terms(model_results_df, "sens_model_main_public_rwe_baseline")
    top_main_duplicate = top_terms(model_results_df, "sens_model_main_public_rwe_duplicate_collapsed")
    top_analytic_baseline = top_terms(model_results_df, "sens_model_analytic_public_rwe_baseline")

    lines = [
        "# Sensitivity Report",
        "",
        f"- input endpoint layer: `{IN_CSV}`",
        f"- scenario summary: `{SUMMARY_CSV}`",
        f"- prevalence output: `{PREVALENCE_CSV}`",
        f"- model results: `{MODEL_RESULTS_CSV}`",
        f"- model fit summary: `{MODEL_FIT_CSV}`",
        "",
        "## Scenario design",
        "",
        "- baseline endpoint ladder on the full cohort",
        "- subset restrictions: hard-issue exclusion, extracted-doc-only, confidence restrictions, warning exclusion, duplicate-cluster collapse",
        "- provenance stratification by final label source",
        "- model reruns only for the main and analytic outcomes under the high-value scenarios",
        "",
        "## Prevalence robustness highlights",
        "",
        f"- baseline main public RWE prevalence: `{main_prev:.2f}%`",
        f"- baseline analytic public RWE prevalence: `{analytic_prev:.2f}%`",
        f"- explicit endpoint prevalence: `{explicit_prev:.2f}%`",
        f"- non-spontaneous endpoint prevalence: `{non_sp_prev:.2f}%`",
        f"- QC-strict public RWE prevalence: `{qc_prev:.2f}%`",
        f"- extracted-doc-only main public RWE prevalence: `{extracted_main_prev:.2f}%`",
        f"- high/medium-confidence main public RWE prevalence: `{high_med_main_prev:.2f}%`",
        f"- high-confidence-only main public RWE prevalence: `{high_only_main_prev:.2f}%`",
        f"- duplicate-cluster-collapsed main public RWE prevalence: `{duplicate_main_prev:.2f}%`",
        f"- duplicate-cluster-collapsed analytic public RWE prevalence: `{duplicate_analytic_prev:.2f}%`",
        f"- warning-excluded main public RWE prevalence: `{warning_excluded_main_prev:.2f}%`",
        "",
        "## Interpretation",
        "",
        "- Hard-issue exclusion is a minor technical robustness check. It should not drive the manuscript framing unless it meaningfully changes the endpoints.",
        "- Endpoint strictness is the larger conceptual sensitivity. The gap between the broad endpoint and the explicit/non-spontaneous variants is more consequential than the QC-strict variant.",
        "- Duplicate-cluster collapse directly addresses repeated harmonized event structures and should be retained as a planned supplement sensitivity.",
        "- Confidence restriction is informative because low-confidence rows are enriched for broad positives. It should be reported as a robustness check, not used to redefine the main cohort.",
        "- Logic-warning exclusion is intentionally aggressive and raises prevalence by preferentially removing ambiguous negative rows. It is suitable for supplement-only stress testing, not for the main analysis.",
        "",
        "## Model robustness highlights",
        "",
    ]

    def add_top_terms(title: str, df_terms: pd.DataFrame) -> None:
        lines.extend(["", f"### {title}", ""])
        for _, row in df_terms.iterrows():
            lines.append(
                f"- `{row['term_label']}`: PR `{row['prevalence_ratio']:.3f}` "
                f"(95% CI `{row['pr_ci_lower']:.3f}` to `{row['pr_ci_upper']:.3f}`), p=`{row['p_value']:.4g}`"
            )

    add_top_terms("Baseline main public RWE model", top_main_baseline)
    add_top_terms("Duplicate-collapsed main public RWE model", top_main_duplicate)
    add_top_terms("Baseline analytic public RWE model", top_analytic_baseline)

    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- The sensitivity layer is designed as robustness analysis around the frozen main endpoint and analytic secondary endpoint.",
            "- Rendered paper figures have not yet been created; the current project state includes tables, figure datasets, models, and this sensitivity layer.",
        ]
    )

    REPORT_MD.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
