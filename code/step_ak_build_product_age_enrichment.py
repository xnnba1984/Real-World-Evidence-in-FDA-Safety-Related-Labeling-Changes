#!/usr/bin/env python3
"""Build approval-year and product-age enrichment outputs."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf


REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_DIR = REPO_ROOT
INPUT_CSV = BASE_DIR / "analysis_ready" / "srlc_analysis_endpoint_layer.csv"
DRUGSFDA_CACHE_DIR = BASE_DIR / "analysis_ready" / "therapeutic_area" / "cache" / "drugsfda"

ENRICH_DIR = BASE_DIR / "analysis_ready" / "product_age"
OUT_ANALYSIS_DIR = BASE_DIR / "analysis_outputs" / "product_age"

LOOKUP_CSV = ENRICH_DIR / "application_approval_age_lookup.csv"
ENRICHED_CSV = ENRICH_DIR / "srlc_analysis_endpoint_layer_product_age.csv"
QC_MD = ENRICH_DIR / "product_age_enrichment_qc.md"

OUTCOME_CSV = OUT_ANALYSIS_DIR / "product_age_outcomes.csv"
TRANSPARENCY_CSV = OUT_ANALYSIS_DIR / "product_age_transparency.csv"
MODEL_CSV = OUT_ANALYSIS_DIR / "product_age_models.csv"
MODEL_FIT_CSV = OUT_ANALYSIS_DIR / "product_age_model_fit_summary.csv"
REPORT_MD = OUT_ANALYSIS_DIR / "product_age_report.md"


SECTION_PREDICTORS = [
    "section_boxed_warning_num",
    "section_contraindications_num",
    "section_warnings_precautions_num",
    "section_adverse_reactions_num",
    "section_drug_interactions_num",
    "section_use_in_specific_populations_num",
]


def ensure_dirs() -> None:
    ENRICH_DIR.mkdir(parents=True, exist_ok=True)
    OUT_ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)


def text_join(values: list[str]) -> str:
    seen = set()
    out = []
    for value in values:
        value = str(value or "").strip()
        if value and value not in seen:
            out.append(value)
            seen.add(value)
    return " | ".join(out)


def yes_no_to_num(series: pd.Series) -> pd.Series:
    return series.eq("yes").astype(int)


def parse_yyyymmdd(value: Any) -> pd.Timestamp | pd.NaT:
    text = str(value or "").strip()
    if len(text) != 8 or not text.isdigit():
        return pd.NaT
    return pd.to_datetime(text, format="%Y%m%d", errors="coerce")


def prefixed_app_number(app_type: str, app_number: Any) -> str:
    return f"{str(app_type).strip().upper()}{int(app_number):06d}"


def derive_approval_row(cache_path: Path, row: dict[str, Any]) -> dict[str, Any]:
    app_prefixed = row["application_number_prefixed"]
    out: dict[str, Any] = {
        "application_number_prefixed": app_prefixed,
        "Application Number": row["Application Number"],
        "Application Type": row["Application Type"],
        "Drug Name": row["Drug Name"],
        "Active Ingredient": row["Active Ingredient"],
        "drugsfda_status": "missing_cache",
        "approval_date": "",
        "approval_year": np.nan,
        "approval_date_source": "missing",
        "approval_submission_type": "",
        "approval_submission_class_code": "",
        "approval_submission_class_description": "",
        "sponsor_name": "",
        "manufacturer_name": "",
        "n_submissions_total": 0,
        "n_approved_submissions": 0,
    }

    if not cache_path.exists():
        return out

    obj = json.loads(cache_path.read_text())
    out["drugsfda_status"] = obj.get("status", "")
    if obj.get("status") != "ok":
        return out

    payload = obj.get("payload", {})
    results = payload.get("results", []) if isinstance(payload, dict) else []
    if not results:
        return out

    res = results[0]
    submissions = res.get("submissions", []) if isinstance(res.get("submissions"), list) else []
    approved = []
    for sub in submissions:
        if str(sub.get("submission_status", "")).upper() != "AP":
            continue
        dt = parse_yyyymmdd(sub.get("submission_status_date"))
        if pd.isna(dt):
            continue
        approved.append((dt, sub))

    approved.sort(key=lambda item: item[0])
    orig_approved = [item for item in approved if str(item[1].get("submission_type", "")).upper() == "ORIG"]

    chosen: tuple[pd.Timestamp, dict[str, Any]] | None = None
    source = "missing"
    if orig_approved:
        chosen = orig_approved[0]
        source = "orig_ap"
    elif approved:
        chosen = approved[0]
        source = "first_ap_fallback"

    openfda = res.get("openfda", {}) if isinstance(res.get("openfda"), dict) else {}
    out["sponsor_name"] = str(res.get("sponsor_name", "")).strip()
    out["manufacturer_name"] = text_join(openfda.get("manufacturer_name", []) if isinstance(openfda.get("manufacturer_name"), list) else [])
    out["n_submissions_total"] = len(submissions)
    out["n_approved_submissions"] = len(approved)

    if chosen is None:
        return out

    dt, sub = chosen
    out["approval_date"] = dt.date().isoformat()
    out["approval_year"] = int(dt.year)
    out["approval_date_source"] = source
    out["approval_submission_type"] = str(sub.get("submission_type", "")).strip()
    out["approval_submission_class_code"] = str(sub.get("submission_class_code", "")).strip()
    out["approval_submission_class_description"] = str(sub.get("submission_class_code_description", "")).strip()
    return out


def approval_era(year: Any) -> str:
    if pd.isna(year):
        return "unknown"
    year = int(year)
    if year < 1990:
        return "pre_1990"
    if year < 2000:
        return "1990s"
    if year < 2010:
        return "2000s"
    if year < 2020:
        return "2010s"
    return "2020s"


def approval_era_label(key: str) -> str:
    mapping = {
        "pre_1990": "Pre-1990",
        "1990s": "1990s",
        "2000s": "2000s",
        "2010s": "2010s",
        "2020s": "2020s",
        "unknown": "Unknown",
    }
    return mapping[key]


def product_age_band(age_years: Any) -> str:
    if pd.isna(age_years):
        return "unknown"
    age = float(age_years)
    if age < 5:
        return "0_4"
    if age < 10:
        return "5_9"
    if age < 20:
        return "10_19"
    if age < 30:
        return "20_29"
    return "30_plus"


def product_age_band_label(key: str) -> str:
    mapping = {
        "0_4": "0-4 years",
        "5_9": "5-9 years",
        "10_19": "10-19 years",
        "20_29": "20-29 years",
        "30_plus": "30+ years",
        "unknown": "Unknown",
    }
    return mapping[key]


def fit_modified_poisson(
    data: pd.DataFrame,
    outcome: str,
    outcome_label: str,
    formula_rhs: str,
    model_name: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
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
                "model_name": model_name,
                "outcome": outcome,
                "outcome_label": outcome_label,
                "formula": formula,
                "term": term,
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
        "product_age_decade": "Product age (per 10 years)",
        "approval_year_centered": "Approval year (per 1 year)",
        "C(app_type)[T.NDA]": "NDA vs BLA",
        "section_boxed_warning_num": "Boxed Warning present",
        "section_contraindications_num": "Contraindications present",
        "section_warnings_precautions_num": "Warnings and Precautions present",
        "section_adverse_reactions_num": "Adverse Reactions present",
        "section_drug_interactions_num": "Drug Interactions present",
        "section_use_in_specific_populations_num": "Use in Specific Populations present",
    }
    return mapping.get(term, term)


def summarize_by_group(df: pd.DataFrame, group_col: str, group_label_col: str, group_type: str) -> pd.DataFrame:
    rows = []
    total = len(df)
    for key, group in df.groupby(group_col, dropna=False):
        rows.append(
            {
                "group_type": group_type,
                "group_key": key,
                "group_label": group[group_label_col].iloc[0],
                "n_events": len(group),
                "pct_all_events": len(group) / total * 100.0,
                "main_public_rwe_yes": int(group["endpoint_main_public_rwe"].eq("yes").sum()),
                "main_public_rwe_pct": group["endpoint_main_public_rwe"].eq("yes").mean() * 100.0,
                "analytic_public_rwe_yes": int(group["endpoint_secondary_analytic_public_rwe"].eq("yes").sum()),
                "analytic_public_rwe_pct": group["endpoint_secondary_analytic_public_rwe"].eq("yes").mean() * 100.0,
                "mean_transparency_score": float(group["transparency_score"].astype(float).mean()),
            }
        )
    return pd.DataFrame(rows)


def summarize_transparency(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    analytic = df[df["endpoint_secondary_analytic_public_rwe"].eq("yes")].copy()
    for group_col, label_col, group_type in [
        ("product_age_band", "product_age_band_label", "product_age_band"),
        ("approval_era", "approval_era_label", "approval_era"),
    ]:
        for key, group in analytic.groupby(group_col, dropna=False):
            score = group["transparency_score"].astype(float)
            rows.append(
                {
                    "group_type": group_type,
                    "group_key": key,
                    "group_label": group[label_col].iloc[0],
                    "n_events": len(group),
                    "mean_transparency_score": float(score.mean()),
                    "median_transparency_score": float(score.median()),
                    "transparency_ge_3_pct": float((score >= 3).mean() * 100.0),
                    "transparency_ge_5_pct": float((score >= 5).mean() * 100.0),
                }
            )
    return pd.DataFrame(rows)


def main() -> None:
    ensure_dirs()
    df = pd.read_csv(INPUT_CSV)
    df["event_date"] = pd.to_datetime(df["event_date_iso"], errors="coerce")
    df["application_number_prefixed"] = df.apply(
        lambda row: prefixed_app_number(row["Application Type"], row["Application Number"]),
        axis=1,
    )

    app_df = df[["Application Number", "Application Type", "Drug Name", "Active Ingredient"]].copy()
    app_df["application_number_prefixed"] = app_df.apply(
        lambda row: prefixed_app_number(row["Application Type"], row["Application Number"]),
        axis=1,
    )
    app_df = (
        app_df.groupby(["application_number_prefixed", "Application Number", "Application Type"], as_index=False)
        .agg(
            {
                "Drug Name": lambda s: text_join(sorted(set(str(v).strip() for v in s if str(v).strip()))),
                "Active Ingredient": lambda s: text_join(sorted(set(str(v).strip() for v in s if str(v).strip()))),
            }
        )
    )

    lookup_rows = []
    for row in app_df.to_dict("records"):
        cache_path = DRUGSFDA_CACHE_DIR / f"{row['application_number_prefixed']}.json"
        lookup_rows.append(derive_approval_row(cache_path, row))
    lookup_df = pd.DataFrame(lookup_rows)
    lookup_df["approval_era"] = lookup_df["approval_year"].apply(approval_era)
    lookup_df["approval_era_label"] = lookup_df["approval_era"].apply(approval_era_label)
    lookup_df.to_csv(LOOKUP_CSV, index=False)

    enriched_df = df.merge(
        lookup_df[
            [
                "application_number_prefixed",
                "Application Number",
                "Application Type",
                "approval_date",
                "approval_year",
                "approval_date_source",
                "approval_submission_type",
                "approval_submission_class_code",
                "approval_submission_class_description",
                "sponsor_name",
                "manufacturer_name",
                "n_submissions_total",
                "n_approved_submissions",
                "drugsfda_status",
                "approval_era",
                "approval_era_label",
            ]
        ],
        on=["application_number_prefixed", "Application Number", "Application Type"],
        how="left",
    )
    enriched_df["approval_date"] = pd.to_datetime(enriched_df["approval_date"], errors="coerce")
    enriched_df["product_age_years_at_event"] = (
        (enriched_df["event_date"] - enriched_df["approval_date"]).dt.days / 365.25
    )
    fallback_age = enriched_df["event_year"].astype(float) - enriched_df["approval_year"].astype(float)
    enriched_df["product_age_years_at_event"] = enriched_df["product_age_years_at_event"].fillna(fallback_age)
    enriched_df["product_age_years_at_event"] = enriched_df["product_age_years_at_event"].where(
        enriched_df["product_age_years_at_event"] >= 0,
        np.nan,
    )
    enriched_df["product_age_band"] = enriched_df["product_age_years_at_event"].apply(product_age_band)
    enriched_df["product_age_band_label"] = enriched_df["product_age_band"].apply(product_age_band_label)
    enriched_df["approval_era"] = enriched_df["approval_era"].fillna("unknown")
    enriched_df["approval_era_label"] = enriched_df["approval_era"].apply(approval_era_label)
    enriched_df.to_csv(ENRICHED_CSV, index=False)

    outcomes_df = pd.concat(
        [
            summarize_by_group(enriched_df, "product_age_band", "product_age_band_label", "product_age_band"),
            summarize_by_group(enriched_df, "approval_era", "approval_era_label", "approval_era"),
        ],
        ignore_index=True,
    )
    outcomes_df.to_csv(OUTCOME_CSV, index=False)

    transparency_df = summarize_transparency(enriched_df)
    transparency_df.to_csv(TRANSPARENCY_CSV, index=False)

    model_df = enriched_df.copy()
    model_df["application_number_cluster"] = model_df["Application Number"].astype(str)
    model_df["app_type"] = model_df["Application Type"].astype(str)
    model_df["product_age_decade"] = model_df["product_age_years_at_event"].astype(float) / 10.0
    model_df["approval_year_centered"] = model_df["approval_year"].astype(float) - 2005.0
    model_df["y_main_public_rwe"] = yes_no_to_num(model_df["endpoint_main_public_rwe"])
    model_df["y_analytic_public_rwe"] = yes_no_to_num(model_df["endpoint_secondary_analytic_public_rwe"])
    model_df["section_boxed_warning_num"] = yes_no_to_num(model_df["section_boxed_warning"])
    model_df["section_contraindications_num"] = yes_no_to_num(model_df["section_contraindications"])
    model_df["section_warnings_precautions_num"] = yes_no_to_num(model_df["section_warnings_precautions"])
    model_df["section_adverse_reactions_num"] = yes_no_to_num(model_df["section_adverse_reactions"])
    model_df["section_drug_interactions_num"] = yes_no_to_num(model_df["section_drug_interactions"])
    model_df["section_use_in_specific_populations_num"] = yes_no_to_num(model_df["section_use_in_specific_populations"])

    model_df = model_df[model_df["product_age_decade"].notna()].copy()
    rhs = "product_age_decade + C(app_type) + " + " + ".join(SECTION_PREDICTORS)

    main_model_df, main_fit = fit_modified_poisson(
        data=model_df,
        outcome="y_main_public_rwe",
        outcome_label="Main public RWE endpoint with product age",
        formula_rhs=rhs,
        model_name="model_main_public_rwe_with_product_age",
    )
    analytic_model_df, analytic_fit = fit_modified_poisson(
        data=model_df,
        outcome="y_analytic_public_rwe",
        outcome_label="Analytic public RWE endpoint with product age",
        formula_rhs=rhs,
        model_name="model_analytic_public_rwe_with_product_age",
    )
    combined_model_df = pd.concat([main_model_df, analytic_model_df], ignore_index=True)
    combined_model_df["term_label"] = combined_model_df["term"].apply(prettify_term)
    combined_model_df.to_csv(MODEL_CSV, index=False)
    pd.DataFrame([main_fit, analytic_fit]).to_csv(MODEL_FIT_CSV, index=False)

    approval_missing = int(lookup_df["approval_year"].isna().sum())
    orig_source = int(lookup_df["approval_date_source"].eq("orig_ap").sum())
    fallback_source = int(lookup_df["approval_date_source"].eq("first_ap_fallback").sum())
    age_stats = enriched_df["product_age_years_at_event"].describe()

    lines = [
        "# Product Age Enrichment QC",
        "",
        f"- input endpoint layer: `{INPUT_CSV}`",
        f"- unique applications: `{len(lookup_df)}`",
        f"- cache source: `{DRUGSFDA_CACHE_DIR}`",
        f"- applications with derived approval year: `{len(lookup_df) - approval_missing}`",
        f"- `orig_ap` approval-date source: `{orig_source}`",
        f"- `first_ap_fallback` approval-date source: `{fallback_source}`",
        f"- applications missing approval year: `{approval_missing}`",
        f"- event rows preserved after join: `{len(enriched_df)}`",
        "",
        "## Product age summary",
        "",
        f"- mean age at event: `{age_stats['mean']:.2f}` years",
        f"- median age at event: `{age_stats['50%']:.2f}` years",
        f"- 25th percentile: `{age_stats['25%']:.2f}` years",
        f"- 75th percentile: `{age_stats['75%']:.2f}` years",
        "",
        "## Largest age bands by event count",
        "",
    ]
    age_band_rows = outcomes_df[outcomes_df["group_type"] == "product_age_band"].sort_values("n_events", ascending=False)
    for _, row in age_band_rows.iterrows():
        lines.append(
            f"- `{row['group_label']}`: n=`{int(row['n_events'])}`, "
            f"main public RWE=`{row['main_public_rwe_pct']:.1f}%`, "
            f"analytic public RWE=`{row['analytic_public_rwe_pct']:.1f}%`"
        )
    QC_MD.write_text("\n".join(lines) + "\n")

    report_lines = [
        "# Product Age Enrichment Report",
        "",
        f"- lookup file: `{LOOKUP_CSV}`",
        f"- enriched endpoint layer: `{ENRICHED_CSV}`",
        f"- QC report: `{QC_MD}`",
        f"- outcome summaries: `{OUTCOME_CSV}`",
        f"- transparency summaries: `{TRANSPARENCY_CSV}`",
        f"- model results: `{MODEL_CSV}`",
        "",
        "## Design",
        "",
        "- source metadata: cached FDA `drugsfda` application payloads",
        "- approval-date rule: earliest approved `ORIG` submission when present; otherwise earliest approved submission",
        "- derived variables: `approval_year`, `approval_era`, `product_age_years_at_event`, `product_age_band`",
        "- this is an exploratory enrichment layer and does not alter the annotation endpoints",
        "",
        "## Coverage",
        "",
        f"- unique applications: `{len(lookup_df)}`",
        f"- applications with derived approval year: `{len(lookup_df) - approval_missing}`",
        f"- missing approval year: `{approval_missing}`",
        "",
        "## Descriptive highlights",
        "",
    ]
    for group_type, title in [("approval_era", "Approval era"), ("product_age_band", "Product age band")]:
        report_lines.append(f"- `{title}`:")
        subset = outcomes_df[outcomes_df["group_type"] == group_type].sort_values("n_events", ascending=False)
        for _, row in subset.iterrows():
            report_lines.append(
                f"  - `{row['group_label']}`: n=`{int(row['n_events'])}`, "
                f"main public RWE=`{row['main_public_rwe_pct']:.1f}%`, "
                f"analytic public RWE=`{row['analytic_public_rwe_pct']:.1f}%`, "
                f"mean transparency=`{row['mean_transparency_score']:.2f}`"
            )

    report_lines.extend(["", "## Modeling highlights", ""])
    for outcome_label, subset in combined_model_df[combined_model_df["term"] != "Intercept"].sort_values(["outcome_label", "p_value"]).groupby("outcome_label"):
        report_lines.append(f"- `{outcome_label}`:")
        for _, row in subset.head(8).iterrows():
            report_lines.append(
                f"  - `{row['term_label']}`: PR `{row['prevalence_ratio']:.3f}` "
                f"(95% CI `{row['pr_ci_lower']:.3f}` to `{row['pr_ci_upper']:.3f}`), p=`{row['p_value']:.4g}`"
            )

    report_lines.extend(
        [
            "",
            "## Initial recommendation",
            "",
            "- keep this enrichment if it shows a clear lifecycle pattern that sharpens interpretation of public RWE documentation",
            "- otherwise use it as a supplement table and discussion aid rather than a main-text result",
        ]
    )
    REPORT_MD.write_text("\n".join(report_lines) + "\n")


if __name__ == "__main__":
    main()
