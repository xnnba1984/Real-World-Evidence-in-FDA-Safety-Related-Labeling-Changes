#!/usr/bin/env python3
"""Build sponsor/manufacturer enrichment outputs."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf


REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_DIR = REPO_ROOT
INPUT_CSV = BASE_DIR / "analysis_ready" / "srlc_analysis_endpoint_layer.csv"
APP_INPUT_CSV = BASE_DIR / "analysis_ready" / "therapeutic_area" / "application_therapeutic_area_lookup.csv"

ENRICH_DIR = BASE_DIR / "analysis_ready" / "sponsor_manufacturer"
OUT_ANALYSIS_DIR = BASE_DIR / "analysis_outputs" / "sponsor_manufacturer"

LOOKUP_CSV = ENRICH_DIR / "application_sponsor_manufacturer_lookup.csv"
ENRICHED_CSV = ENRICH_DIR / "srlc_analysis_endpoint_layer_sponsor_manufacturer.csv"
QC_MD = ENRICH_DIR / "sponsor_manufacturer_enrichment_qc.md"

OUTCOME_CSV = OUT_ANALYSIS_DIR / "sponsor_manufacturer_outcomes.csv"
TRANSPARENCY_CSV = OUT_ANALYSIS_DIR / "sponsor_manufacturer_transparency.csv"
TOP_FAMILY_CSV = OUT_ANALYSIS_DIR / "sponsor_family_top_counts.csv"
MODEL_CSV = OUT_ANALYSIS_DIR / "sponsor_manufacturer_models.csv"
MODEL_FIT_CSV = OUT_ANALYSIS_DIR / "sponsor_manufacturer_model_fit_summary.csv"
REPORT_MD = OUT_ANALYSIS_DIR / "sponsor_manufacturer_report.md"


SECTION_PREDICTORS = [
    "section_boxed_warning_num",
    "section_contraindications_num",
    "section_warnings_precautions_num",
    "section_adverse_reactions_num",
    "section_drug_interactions_num",
    "section_use_in_specific_populations_num",
]

GENERIC_BIOSIMILAR_KEYWORDS = [
    "teva",
    "mylan",
    "viatris",
    "sandoz",
    "amneal",
    "apotex",
    "dr reddy",
    "sun pharma",
    "hikma",
    "zydus",
    "aurobindo",
    "lupin",
    "actavis",
    "watson",
    "par pharma",
    "alvogen",
    "lannett",
    "padagis",
    "slayback",
    "alembic",
    "torrent",
    "camber",
    "strides",
    "epic pharma",
    "rising pharma",
    "breckenridge",
    "annora",
    "alvotech",
    "celltrion",
    "samsung bioepis",
    "biocon biologics",
    "cordavis",
]


def ensure_dirs() -> None:
    ENRICH_DIR.mkdir(parents=True, exist_ok=True)
    OUT_ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)


def yes_no_to_num(series: pd.Series) -> pd.Series:
    return series.eq("yes").astype(int)


def prefixed_app_number(app_type: str, app_number: Any) -> str:
    return f"{str(app_type).strip().upper()}{int(app_number):06d}"


def normalize_company_name(value: Any) -> str:
    if pd.isna(value):
        return ""
    text = str(value).lower().replace("&", " and ")
    text = re.sub(
        r"\b(incorporated|inc|llc|ltd|limited|corp|corporation|co|company|pharmaceuticals|pharmaceutical|pharma|"
        r"laboratories|laboratory|therapeutics|therapeutic|healthcare|health|usa|us|u s|u\.s\.|biotech|"
        r"biopharmaceuticals|biopharmaceutical|holdings|brands|div|division|medical|specialty|lp|gmbh|ag|sa|plc)\b",
        " ",
        text,
    )
    text = re.sub(r"[^a-z0-9]+", " ", text)
    tokens = [tok for tok in text.split() if tok and tok != "and"]
    deduped = []
    seen = set()
    for tok in tokens:
        if tok not in seen:
            deduped.append(tok)
            seen.add(tok)
    return " ".join(deduped)


def first_manufacturer(value: Any) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if not text:
        return ""
    return text.split("|")[0].strip()


def company_flag_generic_like(sponsor_name: Any, manufacturer_name: Any) -> str:
    text = f"{'' if pd.isna(sponsor_name) else sponsor_name} || {'' if pd.isna(manufacturer_name) else manufacturer_name}".lower()
    return "yes" if any(keyword in text for keyword in GENERIC_BIOSIMILAR_KEYWORDS) else "no"


def structure_type(sponsor_name: Any, manufacturer_name: Any) -> str:
    sponsor_text = "" if pd.isna(sponsor_name) else str(sponsor_name).strip()
    manufacturer_text = "" if pd.isna(manufacturer_name) else str(manufacturer_name).strip()
    if not manufacturer_text:
        return "manufacturer_missing"
    if "|" in manufacturer_text:
        return "multi_manufacturer_listed"
    sponsor_norm = normalize_company_name(sponsor_text)
    manufacturer_norm = normalize_company_name(manufacturer_text)
    if sponsor_norm and manufacturer_norm and (
        sponsor_norm == manufacturer_norm or sponsor_norm in manufacturer_norm or manufacturer_norm in sponsor_norm
    ):
        return "same_family_single_manufacturer"
    return "different_sponsor_manufacturer"


def structure_label(key: str) -> str:
    mapping = {
        "same_family_single_manufacturer": "Same-family single manufacturer",
        "different_sponsor_manufacturer": "Different sponsor/manufacturer",
        "multi_manufacturer_listed": "Multiple manufacturers listed",
        "manufacturer_missing": "Manufacturer missing",
    }
    return mapping[key]


def primary_company_raw(sponsor_name: Any, manufacturer_name: Any) -> str:
    manufacturer_first = first_manufacturer(manufacturer_name)
    if manufacturer_first:
        return manufacturer_first
    return "" if pd.isna(sponsor_name) else str(sponsor_name).strip()


def titleize_family(value: str) -> str:
    if not value:
        return "Unknown"
    parts = value.split()
    return " ".join(part.upper() if len(part) <= 4 else part.title() for part in parts)


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
        "generic_biosimilar_like_num": "Generic/biosimilar-like company",
        "C(app_type)[T.NDA]": "NDA vs BLA",
        "section_boxed_warning_num": "Boxed Warning present",
        "section_contraindications_num": "Contraindications present",
        "section_warnings_precautions_num": "Warnings and Precautions present",
        "section_adverse_reactions_num": "Adverse Reactions present",
        "section_drug_interactions_num": "Drug Interactions present",
        "section_use_in_specific_populations_num": "Use in Specific Populations present",
        "C(sponsor_manufacturer_structure, Treatment(reference='same_family_single_manufacturer'))[T.different_sponsor_manufacturer]": "Structure: Different sponsor/manufacturer",
        "C(sponsor_manufacturer_structure, Treatment(reference='same_family_single_manufacturer'))[T.manufacturer_missing]": "Structure: Manufacturer missing",
        "C(sponsor_manufacturer_structure, Treatment(reference='same_family_single_manufacturer'))[T.multi_manufacturer_listed]": "Structure: Multiple manufacturers listed",
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
    analytic = df[df["endpoint_secondary_analytic_public_rwe"].eq("yes")].copy()
    rows = []
    for group_col, label_col, group_type in [
        ("generic_biosimilar_like_flag", "generic_biosimilar_like_label", "generic_biosimilar_like_flag"),
        ("sponsor_manufacturer_structure", "sponsor_manufacturer_structure_label", "sponsor_manufacturer_structure"),
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

    events_df = pd.read_csv(INPUT_CSV)
    events_df["application_number_prefixed"] = events_df.apply(
        lambda row: prefixed_app_number(row["Application Type"], row["Application Number"]),
        axis=1,
    )
    app_df = pd.read_csv(
        APP_INPUT_CSV,
        usecols=[
            "application_number_prefixed",
            "Application Number",
            "Application Type",
            "Drug Name",
            "Active Ingredient",
            "sponsor_name",
            "manufacturer_name",
        ],
    )

    app_df["sponsor_manufacturer_structure"] = app_df.apply(
        lambda row: structure_type(row["sponsor_name"], row["manufacturer_name"]),
        axis=1,
    )
    app_df["sponsor_manufacturer_structure_label"] = app_df["sponsor_manufacturer_structure"].apply(structure_label)
    app_df["generic_biosimilar_like_flag"] = app_df.apply(
        lambda row: company_flag_generic_like(row["sponsor_name"], row["manufacturer_name"]),
        axis=1,
    )
    app_df["generic_biosimilar_like_label"] = app_df["generic_biosimilar_like_flag"].map(
        {"yes": "Generic/biosimilar-like company", "no": "Non-generic-like company"}
    )
    app_df["primary_company_raw"] = app_df.apply(
        lambda row: primary_company_raw(row["sponsor_name"], row["manufacturer_name"]),
        axis=1,
    )
    app_df["primary_company_family"] = app_df["primary_company_raw"].apply(normalize_company_name)
    app_df["primary_company_family_label"] = app_df["primary_company_family"].apply(titleize_family)

    app_df.to_csv(LOOKUP_CSV, index=False)

    enriched_df = events_df.merge(
        app_df[
            [
                "application_number_prefixed",
                "Application Number",
                "Application Type",
                "sponsor_name",
                "manufacturer_name",
                "sponsor_manufacturer_structure",
                "sponsor_manufacturer_structure_label",
                "generic_biosimilar_like_flag",
                "generic_biosimilar_like_label",
                "primary_company_raw",
                "primary_company_family",
                "primary_company_family_label",
            ]
        ],
        on=["application_number_prefixed", "Application Number", "Application Type"],
        how="left",
    )
    ENRICHED_CSV.write_text("")
    enriched_df.to_csv(ENRICHED_CSV, index=False)

    outcomes_df = pd.concat(
        [
            summarize_by_group(
                enriched_df,
                "sponsor_manufacturer_structure",
                "sponsor_manufacturer_structure_label",
                "sponsor_manufacturer_structure",
            ),
            summarize_by_group(
                enriched_df,
                "generic_biosimilar_like_flag",
                "generic_biosimilar_like_label",
                "generic_biosimilar_like_flag",
            ),
        ],
        ignore_index=True,
    )
    outcomes_df.to_csv(OUTCOME_CSV, index=False)

    transparency_df = summarize_transparency(enriched_df)
    transparency_df.to_csv(TRANSPARENCY_CSV, index=False)

    top_family_df = (
        enriched_df.groupby(["primary_company_family", "primary_company_family_label"], dropna=False)
        .agg(
            n_events=("event_id", "count"),
            main_public_rwe_yes=("endpoint_main_public_rwe", lambda s: int((s == "yes").sum())),
            analytic_public_rwe_yes=("endpoint_secondary_analytic_public_rwe", lambda s: int((s == "yes").sum())),
        )
        .reset_index()
    )
    top_family_df["main_public_rwe_pct"] = top_family_df["main_public_rwe_yes"] / top_family_df["n_events"] * 100.0
    top_family_df["analytic_public_rwe_pct"] = top_family_df["analytic_public_rwe_yes"] / top_family_df["n_events"] * 100.0
    top_family_df = top_family_df.sort_values(["n_events", "main_public_rwe_yes"], ascending=[False, False]).head(30)
    top_family_df.to_csv(TOP_FAMILY_CSV, index=False)

    model_df = enriched_df.copy()
    model_df["application_number_cluster"] = model_df["Application Number"].astype(str)
    model_df["app_type"] = model_df["Application Type"].astype(str)
    model_df["generic_biosimilar_like_num"] = yes_no_to_num(model_df["generic_biosimilar_like_flag"])
    model_df["y_main_public_rwe"] = yes_no_to_num(model_df["endpoint_main_public_rwe"])
    model_df["y_analytic_public_rwe"] = yes_no_to_num(model_df["endpoint_secondary_analytic_public_rwe"])
    model_df["section_boxed_warning_num"] = yes_no_to_num(model_df["section_boxed_warning"])
    model_df["section_contraindications_num"] = yes_no_to_num(model_df["section_contraindications"])
    model_df["section_warnings_precautions_num"] = yes_no_to_num(model_df["section_warnings_precautions"])
    model_df["section_adverse_reactions_num"] = yes_no_to_num(model_df["section_adverse_reactions"])
    model_df["section_drug_interactions_num"] = yes_no_to_num(model_df["section_drug_interactions"])
    model_df["section_use_in_specific_populations_num"] = yes_no_to_num(model_df["section_use_in_specific_populations"])

    rhs = (
        "generic_biosimilar_like_num + "
        "C(sponsor_manufacturer_structure, Treatment(reference='same_family_single_manufacturer')) + "
        "C(app_type) + "
        + " + ".join(SECTION_PREDICTORS)
    )

    main_model_df, main_fit = fit_modified_poisson(
        data=model_df,
        outcome="y_main_public_rwe",
        outcome_label="Main public RWE endpoint with sponsor/manufacturer enrichment",
        formula_rhs=rhs,
        model_name="model_main_public_rwe_with_sponsor_manufacturer",
    )
    analytic_model_df, analytic_fit = fit_modified_poisson(
        data=model_df,
        outcome="y_analytic_public_rwe",
        outcome_label="Analytic public RWE endpoint with sponsor/manufacturer enrichment",
        formula_rhs=rhs,
        model_name="model_analytic_public_rwe_with_sponsor_manufacturer",
    )
    combined_model_df = pd.concat([main_model_df, analytic_model_df], ignore_index=True)
    combined_model_df["term_label"] = combined_model_df["term"].apply(prettify_term)
    combined_model_df.to_csv(MODEL_CSV, index=False)
    pd.DataFrame([main_fit, analytic_fit]).to_csv(MODEL_FIT_CSV, index=False)

    structure_counts = app_df["sponsor_manufacturer_structure"].value_counts()
    generic_counts = app_df["generic_biosimilar_like_flag"].value_counts()
    lines = [
        "# Sponsor/Manufacturer Enrichment QC",
        "",
        f"- input endpoint layer: `{INPUT_CSV}`",
        f"- application lookup source: `{APP_INPUT_CSV}`",
        f"- unique applications: `{len(app_df)}`",
        f"- event rows preserved after join: `{len(enriched_df)}`",
        "",
        "## Structure counts at the application level",
        "",
    ]
    for key, value in structure_counts.items():
        lines.append(f"- `{structure_label(key)}`: `{int(value)}`")
    lines.extend(["", "## Generic/biosimilar-like flag counts at the application level", ""])
    for key, value in generic_counts.items():
        label = "Generic/biosimilar-like company" if key == "yes" else "Non-generic-like company"
        lines.append(f"- `{label}`: `{int(value)}`")
    lines.extend(["", "## Top sponsor families by event count", ""])
    for _, row in top_family_df.head(12).iterrows():
        lines.append(
            f"- `{row['primary_company_family_label']}`: n=`{int(row['n_events'])}`, "
            f"main public RWE=`{row['main_public_rwe_pct']:.1f}%`, "
            f"analytic public RWE=`{row['analytic_public_rwe_pct']:.1f}%`"
        )
    QC_MD.write_text("\n".join(lines) + "\n")

    report_lines = [
        "# Sponsor/Manufacturer Enrichment Report",
        "",
        f"- lookup file: `{LOOKUP_CSV}`",
        f"- enriched endpoint layer: `{ENRICHED_CSV}`",
        f"- QC report: `{QC_MD}`",
        f"- outcomes: `{OUTCOME_CSV}`",
        f"- transparency: `{TRANSPARENCY_CSV}`",
        f"- top sponsor families: `{TOP_FAMILY_CSV}`",
        f"- model results: `{MODEL_CSV}`",
        "",
        "## Design",
        "",
        "- source metadata: sponsor and manufacturer fields already captured from FDA `drugsfda` application records",
        "- sponsor/manufacturer type is operationalized conservatively as:",
        "  - structure: same-family single manufacturer / different sponsor-manufacturer / multiple manufacturers listed / manufacturer missing",
        "  - generic/biosimilar-like company flag based on sponsor/manufacturer name heuristics",
        "- no external corporate taxonomy was used",
        "",
        "## Descriptive highlights",
        "",
    ]
    for group_type, title in [
        ("sponsor_manufacturer_structure", "Sponsor/manufacturer structure"),
        ("generic_biosimilar_like_flag", "Generic/biosimilar-like company flag"),
    ]:
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
            "- use this enrichment only if the structure or generic-like patterns are coherent enough to sharpen interpretation",
            "- otherwise keep it as an exploratory supplement analysis because the company-typing construct is more heuristic than the product-age enrichment",
        ]
    )
    REPORT_MD.write_text("\n".join(report_lines) + "\n")


if __name__ == "__main__":
    main()
