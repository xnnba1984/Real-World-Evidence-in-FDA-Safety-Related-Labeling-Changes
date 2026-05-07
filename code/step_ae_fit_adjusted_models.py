#!/usr/bin/env python3
"""Fit adjusted prevalence models for the main analysis."""

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

MAIN_CSV = OUT_DIR / "model_main_public_rwe.csv"
ANALYTIC_CSV = OUT_DIR / "model_analytic_public_rwe.csv"
TRANSPARENCY_CSV = OUT_DIR / "model_transparency.csv"
FIT_SUMMARY_CSV = OUT_DIR / "model_fit_summary.csv"
REPORT_MD = OUT_DIR / "model_report.md"


SECTION_PREDICTORS = [
    "section_boxed_warning_num",
    "section_contraindications_num",
    "section_warnings_precautions_num",
    "section_adverse_reactions_num",
    "section_drug_interactions_num",
    "section_use_in_specific_populations_num",
]


def yes_no_to_num(series: pd.Series) -> pd.Series:
    return series.eq("yes").astype(int)


def fit_modified_poisson(
    data: pd.DataFrame,
    outcome: str,
    outcome_label: str,
    formula_rhs: str,
    model_name: str,
) -> tuple[pd.DataFrame, dict]:
    formula = f"{outcome} ~ {formula_rhs}"
    model = smf.glm(formula=formula, data=data, family=sm.families.Poisson())
    result = model.fit(cov_type="cluster", cov_kwds={"groups": data["application_number_cluster"]})

    conf = result.conf_int()
    rows = []
    for term in result.params.index:
        coef = float(result.params[term])
        se = float(result.bse[term])
        lower = float(conf.loc[term, 0])
        upper = float(conf.loc[term, 1])
        rows.append(
            {
                "model_name": model_name,
                "outcome": outcome,
                "outcome_label": outcome_label,
                "formula": formula,
                "term": term,
                "coef_log": coef,
                "std_err": se,
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


def top_terms(df: pd.DataFrame, exclude_intercept: bool = True) -> pd.DataFrame:
    subset = df.copy()
    if exclude_intercept:
        subset = subset[subset["term"] != "Intercept"]
    subset = subset.sort_values(["p_value", "prevalence_ratio"], ascending=[True, False])
    return subset.head(6).copy()


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(IN_CSV)

    # Modeling dataset with stable column names.
    model_df = df.copy()
    model_df["application_number_cluster"] = model_df["Application Number"].astype(str)
    model_df["app_type"] = model_df["Application Type"].astype(str)
    model_df["year_centered"] = model_df["event_year"].astype(float) - 2020.0

    for src, dst in [
        ("endpoint_main_public_rwe", "y_main_public_rwe"),
        ("endpoint_secondary_analytic_public_rwe", "y_analytic_public_rwe"),
    ]:
        model_df[dst] = yes_no_to_num(model_df[src])

    model_df["transparency_ge_3"] = (model_df["transparency_score"].astype(int) >= 3).astype(int)

    for src, dst in [
        ("section_boxed_warning", "section_boxed_warning_num"),
        ("section_contraindications", "section_contraindications_num"),
        ("section_warnings_precautions", "section_warnings_precautions_num"),
        ("section_adverse_reactions", "section_adverse_reactions_num"),
        ("section_drug_interactions", "section_drug_interactions_num"),
        ("section_use_in_specific_populations", "section_use_in_specific_populations_num"),
    ]:
        model_df[dst] = yes_no_to_num(model_df[src])

    rhs = "year_centered + C(app_type) + " + " + ".join(SECTION_PREDICTORS)

    main_results, main_summary = fit_modified_poisson(
        data=model_df,
        outcome="y_main_public_rwe",
        outcome_label="Main public RWE endpoint",
        formula_rhs=rhs,
        model_name="model_main_public_rwe",
    )

    analytic_results, analytic_summary = fit_modified_poisson(
        data=model_df,
        outcome="y_analytic_public_rwe",
        outcome_label="Analytic public RWE endpoint",
        formula_rhs=rhs,
        model_name="model_analytic_public_rwe",
    )

    analytic_subset = model_df[model_df["y_analytic_public_rwe"] == 1].copy()
    transparency_results, transparency_summary = fit_modified_poisson(
        data=analytic_subset,
        outcome="transparency_ge_3",
        outcome_label="Transparency score >= 3 among analytic-positive events",
        formula_rhs=rhs,
        model_name="model_transparency_ge_3_among_analytic",
    )

    # Add readable labels.
    for result_df in [main_results, analytic_results, transparency_results]:
        result_df["term_label"] = result_df["term"].apply(prettify_term)

    main_results.to_csv(MAIN_CSV, index=False)
    analytic_results.to_csv(ANALYTIC_CSV, index=False)
    transparency_results.to_csv(TRANSPARENCY_CSV, index=False)

    fit_summary_df = pd.DataFrame([main_summary, analytic_summary, transparency_summary])
    fit_summary_df.to_csv(FIT_SUMMARY_CSV, index=False)

    top_main = top_terms(main_results)
    top_analytic = top_terms(analytic_results)
    top_transparency = top_terms(transparency_results)

    lines = [
        "# Model Report",
        "",
        f"- input endpoint layer: `{IN_CSV}`",
        f"- output main model: `{MAIN_CSV}`",
        f"- output analytic model: `{ANALYTIC_CSV}`",
        f"- output transparency model: `{TRANSPARENCY_CSV}`",
        f"- fit summary: `{FIT_SUMMARY_CSV}`",
        "",
        "## Modeling approach",
        "",
        "- family: modified Poisson regression",
        "- link: log",
        "- covariance: cluster-robust by `Application Number`",
        "- full cohort kept for the main and analytic endpoint models, including 2026 events",
        "- transparency model fit among analytic-positive events only",
        "- reference application type in the current specification: `BLA` (so the application-type term is `NDA vs BLA`)",
        "",
        "## Model formulas",
        "",
        f"- main public RWE: `{main_summary['formula']}`",
        f"- analytic public RWE: `{analytic_summary['formula']}`",
        f"- transparency >= 3 among analytic positives: `{transparency_summary['formula']}`",
        "",
        "## Fit summary",
        "",
    ]
    for summary in [main_summary, analytic_summary, transparency_summary]:
        lines.extend(
            [
                f"- `{summary['model_name']}`: n=`{summary['n_obs']}`, positive=`{summary['n_positive']}`, clusters=`{summary['n_clusters']}`, converged=`{summary['converged']}`, AIC=`{summary['aic']:.2f}`",
            ]
        )

    def add_top_terms(title: str, df_terms: pd.DataFrame) -> None:
        lines.extend(["", f"## {title}", ""])
        for _, row in df_terms.iterrows():
            lines.append(
                f"- `{row['term_label']}`: PR `{row['prevalence_ratio']:.3f}` "
                f"(95% CI `{row['pr_ci_lower']:.3f}` to `{row['pr_ci_upper']:.3f}`), p=`{row['p_value']:.4g}`"
            )

    add_top_terms("Top signals in the main public RWE model", top_main)
    add_top_terms("Top signals in the analytic public RWE model", top_analytic)
    add_top_terms("Top signals in the transparency model", top_transparency)

    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- These are inferential models on the current machine-annotated endpoints.",
            "- Sensitivity analyses have not yet been applied to these models.",
            "- If human validation later suggests that the broad endpoint overcalls positives, the explicit or analytic endpoint may deserve greater emphasis in the manuscript.",
        ]
    )
    REPORT_MD.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
