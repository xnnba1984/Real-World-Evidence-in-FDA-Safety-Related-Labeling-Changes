#!/usr/bin/env python3
"""Build an application-level therapeutic-area enrichment layer."""

from __future__ import annotations

import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf


REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_DIR = REPO_ROOT
INPUT_CSV = BASE_DIR / "analysis_ready" / "srlc_analysis_endpoint_layer.csv"

ENRICH_DIR = BASE_DIR / "analysis_ready" / "therapeutic_area"
CACHE_DIR = ENRICH_DIR / "cache"
DRUGSFDA_CACHE_DIR = CACHE_DIR / "drugsfda"
LABEL_CACHE_DIR = CACHE_DIR / "label"

OUT_ANALYSIS_DIR = BASE_DIR / "analysis_outputs" / "therapeutic_area"

LOOKUP_CSV = ENRICH_DIR / "application_therapeutic_area_lookup.csv"
ENRICHED_CSV = ENRICH_DIR / "srlc_analysis_endpoint_layer_therapeutic_area.csv"
QC_MD = ENRICH_DIR / "therapeutic_area_enrichment_qc.md"

OUTCOME_CSV = OUT_ANALYSIS_DIR / "therapeutic_area_outcomes.csv"
TRANSPARENCY_CSV = OUT_ANALYSIS_DIR / "therapeutic_area_transparency.csv"
MODEL_CSV = OUT_ANALYSIS_DIR / "therapeutic_area_models.csv"
MODEL_FIT_CSV = OUT_ANALYSIS_DIR / "therapeutic_area_model_fit_summary.csv"
REPORT_MD = OUT_ANALYSIS_DIR / "therapeutic_area_report.md"

USER_AGENT = "Codex-RWE-TherapeuticArea/1.0 (academic-analysis)"
REQUEST_TIMEOUT = 30
MAX_WORKERS = 3
MAX_RETRIES = 4
MIN_CATEGORY_EVENTS = 150


def ensure_dirs() -> None:
    for path in [
        ENRICH_DIR,
        CACHE_DIR,
        DRUGSFDA_CACHE_DIR,
        LABEL_CACHE_DIR,
        OUT_ANALYSIS_DIR,
    ]:
        path.mkdir(parents=True, exist_ok=True)


def prefixed_app_number(app_type: str, app_number: Any) -> str:
    return f"{str(app_type).strip().upper()}{int(app_number):06d}"


def text_join(values: list[str]) -> str:
    cleaned = []
    seen = set()
    for value in values:
        value = re.sub(r"\s+", " ", str(value or "")).strip()
        if value and value not in seen:
            cleaned.append(value)
            seen.add(value)
    return " | ".join(cleaned)


def list_join(values: Any) -> str:
    if not isinstance(values, list):
        return ""
    return text_join([str(v) for v in values if str(v).strip()])


def first_nonempty(*values: str) -> str:
    for value in values:
        value = str(value or "").strip()
        if value:
            return value
    return ""


def http_get_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_json_with_cache(cache_dir: Path, cache_key: str, url: str) -> dict[str, Any]:
    cache_path = cache_dir / f"{cache_key}.json"
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text())
        except json.JSONDecodeError:
            cache_path.unlink(missing_ok=True)

    wrapper: dict[str, Any] | None = None
    sleep_seconds = 1.0
    for attempt in range(MAX_RETRIES):
        try:
            payload = http_get_json(url)
            wrapper = {"status": "ok", "payload": payload, "url": url}
            break
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8")
            except Exception:
                body = ""
            if exc.code == 404:
                wrapper = {"status": "not_found", "url": url, "http_code": 404}
                break
            if exc.code in {429, 500, 502, 503, 504} and attempt < MAX_RETRIES - 1:
                time.sleep(sleep_seconds)
                sleep_seconds *= 2.0
                continue
            wrapper = {
                "status": "http_error",
                "url": url,
                "http_code": int(exc.code),
                "message": str(exc),
                "body": body[:1000],
            }
            break
        except Exception as exc:  # pragma: no cover - network variability
            if attempt < MAX_RETRIES - 1:
                time.sleep(sleep_seconds)
                sleep_seconds *= 2.0
                continue
            wrapper = {"status": "error", "url": url, "message": str(exc)}
            break

    assert wrapper is not None
    tmp_path = cache_path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(wrapper, ensure_ascii=True, indent=2) + "\n")
    tmp_path.replace(cache_path)
    return wrapper


def drugsfda_url(app_prefixed: str) -> str:
    query = f'application_number:"{app_prefixed}"'
    return "https://api.fda.gov/drug/drugsfda.json?search=" + urllib.parse.quote(query) + "&limit=1"


def label_app_url(app_prefixed: str) -> str:
    query = f'openfda.application_number:"{app_prefixed}"'
    return (
        "https://api.fda.gov/drug/label.json?search="
        + urllib.parse.quote(query)
        + "&limit=1&sort=effective_time:desc"
    )


def label_brand_url(brand_name: str) -> str:
    query = f'openfda.brand_name:"{brand_name}"'
    return (
        "https://api.fda.gov/drug/label.json?search="
        + urllib.parse.quote(query)
        + "&limit=1&sort=effective_time:desc"
    )


def label_generic_url(generic_name: str) -> str:
    query = f'openfda.generic_name:"{generic_name}"'
    return (
        "https://api.fda.gov/drug/label.json?search="
        + urllib.parse.quote(query)
        + "&limit=1&sort=effective_time:desc"
    )


def fetch_drugsfda_row(row: dict[str, Any]) -> dict[str, Any]:
    app_prefixed = row["application_number_prefixed"]
    wrapper = fetch_json_with_cache(DRUGSFDA_CACHE_DIR, app_prefixed, drugsfda_url(app_prefixed))
    return {"application_number_prefixed": app_prefixed, "wrapper": wrapper}


def parse_drugsfda_wrapper(row: dict[str, Any], wrapper: dict[str, Any]) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "application_number_prefixed": row["application_number_prefixed"],
        "Application Number": row["Application Number"],
        "Application Type": row["Application Type"],
        "Drug Name": row["Drug Name"],
        "Active Ingredient": row["Active Ingredient"],
        "drugsfda_status": wrapper.get("status", ""),
        "drugsfda_lookup_url": wrapper.get("url", ""),
    }
    payload = wrapper.get("payload", {})
    results = payload.get("results", []) if isinstance(payload, dict) else []
    if wrapper.get("status") != "ok" or not results:
        meta.update(
            {
                "sponsor_name": "",
                "manufacturer_name": "",
                "product_brand_name": "",
                "generic_name": "",
                "route": "",
                "product_type": "",
                "dosage_form": "",
                "substance_name": "",
                "pharm_class_epc": "",
                "pharm_class_cs": "",
                "pharm_class_pe": "",
                "pharm_class_moa": "",
            }
        )
        return meta

    result = results[0]
    products = result.get("products", []) if isinstance(result.get("products"), list) else []
    first_product = products[0] if products else {}
    openfda = result.get("openfda", {}) if isinstance(result.get("openfda"), dict) else {}

    route = first_nonempty(
        list_join(openfda.get("route")),
        first_product.get("route", ""),
    )
    dosage_form = first_product.get("dosage_form", "")

    meta.update(
        {
            "sponsor_name": str(result.get("sponsor_name", "")).strip(),
            "manufacturer_name": list_join(openfda.get("manufacturer_name")),
            "product_brand_name": first_nonempty(
                first_product.get("brand_name", ""),
                list_join(openfda.get("brand_name")),
                row["Drug Name"],
            ),
            "generic_name": first_nonempty(
                list_join(openfda.get("generic_name")),
                row["Active Ingredient"],
            ),
            "route": route,
            "product_type": list_join(openfda.get("product_type")),
            "dosage_form": dosage_form,
            "substance_name": list_join(openfda.get("substance_name")),
            "pharm_class_epc": list_join(openfda.get("pharm_class_epc")),
            "pharm_class_cs": list_join(openfda.get("pharm_class_cs")),
            "pharm_class_pe": list_join(openfda.get("pharm_class_pe")),
            "pharm_class_moa": list_join(openfda.get("pharm_class_moa")),
        }
    )
    return meta


def parse_label_payload(wrapper: dict[str, Any]) -> dict[str, Any]:
    payload = wrapper.get("payload", {})
    results = payload.get("results", []) if isinstance(payload, dict) else []
    if wrapper.get("status") != "ok" or not results:
        return {
            "label_status": wrapper.get("status", ""),
            "label_lookup_mode": "",
            "label_brand_name": "",
            "label_generic_name": "",
            "label_route": "",
            "label_pharm_class_epc": "",
            "label_pharm_class_cs": "",
            "label_pharm_class_pe": "",
            "label_pharm_class_moa": "",
            "label_indications_text": "",
            "label_effective_time": "",
            "label_lookup_url": wrapper.get("url", ""),
        }

    result = results[0]
    openfda = result.get("openfda", {}) if isinstance(result.get("openfda"), dict) else {}
    indications = result.get("indications_and_usage", [])
    return {
        "label_status": wrapper.get("status", ""),
        "label_lookup_mode": "",
        "label_brand_name": list_join(openfda.get("brand_name")),
        "label_generic_name": list_join(openfda.get("generic_name")),
        "label_route": list_join(openfda.get("route")),
        "label_pharm_class_epc": list_join(openfda.get("pharm_class_epc")),
        "label_pharm_class_cs": list_join(openfda.get("pharm_class_cs")),
        "label_pharm_class_pe": list_join(openfda.get("pharm_class_pe")),
        "label_pharm_class_moa": list_join(openfda.get("pharm_class_moa")),
        "label_indications_text": text_join([str(v) for v in indications]),
        "label_effective_time": str(result.get("effective_time", "")).strip(),
        "label_lookup_url": wrapper.get("url", ""),
    }


def fetch_label_row(row: dict[str, Any]) -> dict[str, Any]:
    app_prefixed = row["application_number_prefixed"]
    product_brand_name = str(row.get("product_brand_name", "")).strip()
    generic_name = str(row.get("generic_name", "")).strip()
    app_wrapper = fetch_json_with_cache(LABEL_CACHE_DIR, f"{app_prefixed}__app", label_app_url(app_prefixed))
    parsed = parse_label_payload(app_wrapper)
    if parsed["label_status"] == "ok":
        parsed["label_lookup_mode"] = "app"
        return {"application_number_prefixed": app_prefixed, **parsed}

    if product_brand_name:
        brand_wrapper = fetch_json_with_cache(
            LABEL_CACHE_DIR,
            f"{app_prefixed}__brand",
            label_brand_url(product_brand_name),
        )
        parsed = parse_label_payload(brand_wrapper)
        if parsed["label_status"] == "ok":
            parsed["label_lookup_mode"] = "brand"
            return {"application_number_prefixed": app_prefixed, **parsed}

    if generic_name:
        generic_wrapper = fetch_json_with_cache(
            LABEL_CACHE_DIR,
            f"{app_prefixed}__generic",
            label_generic_url(generic_name),
        )
        parsed = parse_label_payload(generic_wrapper)
        if parsed["label_status"] == "ok":
            parsed["label_lookup_mode"] = "generic"
            return {"application_number_prefixed": app_prefixed, **parsed}

    parsed["label_lookup_mode"] = "missing"
    return {"application_number_prefixed": app_prefixed, **parsed}


def contains_any(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def classify_therapeutic_area(row: pd.Series) -> tuple[str, str, str, str]:
    pharm_text = " ".join(
        [
            str(row.get("pharm_class_epc", "")),
            str(row.get("pharm_class_cs", "")),
            str(row.get("pharm_class_pe", "")),
            str(row.get("pharm_class_moa", "")),
            str(row.get("label_pharm_class_epc", "")),
            str(row.get("label_pharm_class_cs", "")),
            str(row.get("label_pharm_class_pe", "")),
            str(row.get("label_pharm_class_moa", "")),
        ]
    ).lower()
    indication_text = str(row.get("label_indications_text", "")).lower()
    product_text = " ".join(
        [
            str(row.get("Drug Name", "")),
            str(row.get("Active Ingredient", "")),
            str(row.get("product_brand_name", "")),
            str(row.get("generic_name", "")),
            str(row.get("substance_name", "")),
            str(row.get("label_brand_name", "")),
            str(row.get("label_generic_name", "")),
        ]
    ).lower()
    route_text = " ".join(
        [
            str(row.get("route", "")),
            str(row.get("dosage_form", "")),
            str(row.get("label_route", "")),
        ]
    ).lower()
    combined = " ".join([pharm_text, indication_text, product_text, route_text])

    rules: list[tuple[str, str, str, list[str], list[str], list[str]]] = [
        (
            "imaging_diagnostics",
            "Imaging/diagnostics",
            "pharm_or_indication_imaging",
            ["contrast agent", "radiographic", "diagnostic imaging", "myelography", "angiography", "urography"],
            ["contrast agent", "radiographic", "imaging procedure", "myelography", "angiography", "ct scan", "mri"],
            [],
        ),
        (
            "ophthalmology",
            "Ophthalmology",
            "route_or_ocular",
            ["ophthalmic", "ocular", "glaucoma"],
            ["ocular", "ophthalmic", "intravitreal", "retinal", "glaucoma", "intraocular", "eye"],
            ["ophthalmic", "intravitreal"],
        ),
        (
            "oncology",
            "Oncology",
            "oncology_signal",
            ["antineoplastic", "vascular endothelial growth factor inhibitor", "kinase inhibitor"],
            ["cancer", "carcinoma", "lymphoma", "leukemia", "myeloma", "tumor", "tumour", "melanoma", "metastatic", "oncology", "neoplasm"],
            [],
        ),
        (
            "infectious_disease",
            "Infectious disease",
            "infection_signal",
            ["antiviral", "antibacterial", "antifungal", "antimicrobial", "vaccine"],
            ["infection", "infectious", "hepatitis", "hiv", "hbv", "hcv", "influenza", "herpes", "bacterial", "fungal", "viral", "antiretroviral", "antibiotic", "pneumocystis", "tuberculosis", "candid", "pneumonia"],
            [],
        ),
        (
            "genetic_metabolic",
            "Genetic/metabolic disorders",
            "genetic_metabolic_signal",
            [
                "lysosomal",
                "glycosaminoglycan-specific enzyme",
                "glucocerebroside-specific enzyme",
                "glycogen-specific enzyme",
                "cholesteryl ester-specific enzyme",
                "uric acid-specific enzyme",
                "sucrose-specific enzyme",
                "alkaline phosphatase",
            ],
            [
                "fabry",
                "gaucher",
                "mucopolysaccharidosis",
                "hunter syndrome",
                "pompe",
                "hypophosphatasia",
                "lysosomal acid lipase deficiency",
                "congenital sucrase-isomaltase deficiency",
                "metabolic disorder",
            ],
            [],
        ),
        (
            "hematology_transplant",
            "Hematology/transplant",
            "blood_or_transplant_signal",
            ["erythropoiesis stimulant", "colony stimulating factor", "immunosuppressant", "platelet aggregation inhibitor"],
            ["transplant", "organ rejection", "anemia", "anaemia", "hemophilia", "thrombocytopenia", "neutropenia", "blood disorder", "coagulation", "hematologic", "hematology", "renal transplant"],
            [],
        ),
        (
            "immunology_rheumatology",
            "Immunology/rheumatology",
            "immunology_signal",
            ["interleukin inhibitor", "tumor necrosis factor blocker", "immunomodulator", "anti-inflammatory", "complement inhibitor", "interleukin-1 blocker"],
            ["rheumatoid arthritis", "psoriasis", "psoriatic", "crohn", "ulcerative colitis", "lupus", "ankylosing", "immune", "immunologic", "dermatitis", "eczema", "hereditary angioedema"],
            [],
        ),
        (
            "endocrine_reproductive",
            "Endocrine/reproductive",
            "endocrine_signal",
            ["estrogen", "progestin", "androgen", "thyroid hormone", "parathyroid hormone", "bisphosphonate", "growth hormone"],
            ["menopause", "hormone", "contraception", "pregnancy", "fertility", "uterine", "endometriosis", "osteoporosis", "thyroid", "parathyroid", "hypophosphatasia", "hypogonad", "postmenopausal", "growth hormone deficiency", "short stature"],
            [],
        ),
        (
            "cardiometabolic",
            "Cardiometabolic",
            "cardiometabolic_signal",
            ["antihypertensive", "beta blocker", "ace inhibitor", "angiotensin", "anticoagulant", "antiplatelet", "statin", "pcsk9", "glucagon-like peptide-1", "dipeptidyl peptidase", "sodium-glucose cotransporter", "insulin", "biguanide"],
            ["hypertension", "hyperlipid", "cholesterol", "triglyceride", "heart failure", "atrial", "myocardial", "angina", "stroke prevention", "diabetes", "glycemic", "glucose", "insulin", "obesity", "weight loss", "atherosclerotic", "renal protection"],
            [],
        ),
        (
            "respiratory_allergy",
            "Respiratory/allergy",
            "respiratory_signal",
            ["bronchodilator", "corticosteroid", "antihistamine", "leukotriene"],
            ["asthma", "copd", "bronchospasm", "allergic rhinitis", "rhinitis", "nasal", "pulmonary", "respiratory", "anaphylaxis", "cystic fibrosis"],
            ["nasal", "inhalation"],
        ),
        (
            "neurology_psychiatry",
            "Neurology/psychiatry",
            "neuro_signal",
            ["antiepileptic", "antidepressant", "antipsychotic", "dopamine agonist", "serotonin"],
            ["seizure", "epilepsy", "depress", "anxiety", "schizophrenia", "bipolar", "migraine", "multiple sclerosis", "parkinson", "alzheimer", "adhd", "attention-deficit", "narcolepsy", "cns", "neuropathic", "obsessive-compulsive", "panic disorder", "insomnia"],
            [],
        ),
        (
            "nephrology_urology",
            "Nephrology/urology",
            "renal_signal",
            ["diuretic", "urologic"],
            ["renal", "kidney", "bladder", "urinary", "urolog", "prostate", "benign prostatic"],
            [],
        ),
        (
            "gastroenterology_hepatology",
            "Gastroenterology/hepatology",
            "gi_signal",
            ["proton pump inhibitor", "h2 antagonist", "laxative", "antidiarrheal"],
            ["diarrhea", "constipation", "gastro", "reflux", "gerd", "ulcer", "hepatic", "liver disease", "cirrhosis", "nausea", "vomiting", "pancreatic insufficiency"],
            [],
        ),
        (
            "dermatology",
            "Dermatology",
            "derm_signal",
            ["topical corticosteroid", "retinoid"],
            ["acne", "skin", "cutaneous", "topical", "dermatology", "alopecia", "rosacea"],
            ["topical"],
        ),
        (
            "supportive_care_pain",
            "Supportive care/pain",
            "supportive_signal",
            ["analgesic", "anesthetic", "antiemetic", "sedative"],
            ["pain", "analgesia", "anesthesia", "sedation", "antiemetic", "postoperative", "supportive care", "opioid use disorder", "opioid dependence", "opioid withdrawal"],
            [],
        ),
    ]

    for key, label, rule_name, pharm_keywords, indication_keywords, route_keywords in rules:
        if contains_any(pharm_text, pharm_keywords):
            return key, label, rule_name, "high"
        if contains_any(route_text, route_keywords) and key in {"ophthalmology", "endocrine_reproductive", "respiratory_allergy", "gastroenterology_hepatology", "dermatology"}:
            return key, label, f"{rule_name}_route", "high"
        if contains_any(indication_text, indication_keywords):
            return key, label, f"{rule_name}_indication", "medium"
        if contains_any(product_text, indication_keywords + pharm_keywords):
            return key, label, f"{rule_name}_product", "low"

    return "other_or_multisystem", "Other/multisystem", "fallback_other", "low"


def yes_no_to_num(series: pd.Series) -> pd.Series:
    return series.eq("yes").astype(int)


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


def summarize_outcomes(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    total = len(df)
    for area_key, group in df.groupby("therapeutic_area_collapsed", dropna=False):
        n_events = len(group)
        rows.append(
            {
                "therapeutic_area_collapsed": area_key,
                "therapeutic_area_label": group["therapeutic_area_collapsed_label"].iloc[0],
                "n_events": n_events,
                "pct_all_events": n_events / total * 100.0,
                "main_public_rwe_yes": int(group["endpoint_main_public_rwe"].eq("yes").sum()),
                "main_public_rwe_pct": group["endpoint_main_public_rwe"].eq("yes").mean() * 100.0,
                "analytic_public_rwe_yes": int(group["endpoint_secondary_analytic_public_rwe"].eq("yes").sum()),
                "analytic_public_rwe_pct": group["endpoint_secondary_analytic_public_rwe"].eq("yes").mean() * 100.0,
                "explicit_public_rwe_yes": int(group["endpoint_sens_explicit_public_rwe"].eq("yes").sum()),
                "explicit_public_rwe_pct": group["endpoint_sens_explicit_public_rwe"].eq("yes").mean() * 100.0,
                "mean_transparency_score": float(group["transparency_score"].astype(float).mean()),
            }
        )
    return pd.DataFrame(rows).sort_values(["n_events", "main_public_rwe_yes"], ascending=[False, False])


def summarize_transparency(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    subsets = [
        ("all_events", df),
        ("main_public_rwe_positive", df[df["endpoint_main_public_rwe"].eq("yes")].copy()),
        ("analytic_public_rwe_positive", df[df["endpoint_secondary_analytic_public_rwe"].eq("yes")].copy()),
    ]
    for subset_name, subset in subsets:
        for area_key, group in subset.groupby("therapeutic_area_collapsed", dropna=False):
            if len(group) == 0:
                continue
            score = group["transparency_score"].astype(float)
            rows.append(
                {
                    "subset": subset_name,
                    "therapeutic_area_collapsed": area_key,
                    "therapeutic_area_label": group["therapeutic_area_collapsed_label"].iloc[0],
                    "n_events": len(group),
                    "mean_transparency_score": float(score.mean()),
                    "median_transparency_score": float(score.median()),
                    "transparency_ge_3_pct": float((score >= 3).mean() * 100.0),
                    "transparency_ge_5_pct": float((score >= 5).mean() * 100.0),
                }
            )
    return pd.DataFrame(rows).sort_values(["subset", "n_events"], ascending=[True, False])


def prettify_term(term: str, category_labels: dict[str, str]) -> str:
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
    if term in mapping:
        return mapping[term]
    category_prefix = "C(therapeutic_area_collapsed, Treatment(reference='"
    if term.startswith("C(therapeutic_area_collapsed"):
        match = re.search(r"\[T\.(.+)\]$", term)
        if match:
            cat = match.group(1)
            label = category_labels.get(cat, cat)
            return f"Therapeutic area: {label}"
    return term


def write_reports(
    lookup_df: pd.DataFrame,
    enriched_df: pd.DataFrame,
    outcomes_df: pd.DataFrame,
    transparency_df: pd.DataFrame,
    model_df: pd.DataFrame,
    fit_summary_df: pd.DataFrame,
) -> None:
    unique_apps = len(lookup_df)
    drugsfda_hit = int(lookup_df["drugsfda_status"].eq("ok").sum())
    label_hit = int(lookup_df["label_status"].eq("ok").sum())
    app_mode = int(lookup_df["label_lookup_mode"].eq("app").sum())
    brand_mode = int(lookup_df["label_lookup_mode"].eq("brand").sum())

    top_area_rows = outcomes_df.head(8)
    rare_count = int((lookup_df["therapeutic_area_collapsed"] == "other_or_multisystem").sum())

    qc_lines = [
        "# Therapeutic Area Enrichment QC",
        "",
        f"- input endpoint layer: `{INPUT_CSV}`",
        f"- unique applications: `{unique_apps}`",
        f"- event rows preserved after join: `{len(enriched_df)}`",
        f"- `drugsfda` application hits: `{drugsfda_hit}` ({drugsfda_hit / unique_apps * 100:.1f}%)",
        f"- label hits after fallback: `{label_hit}` ({label_hit / unique_apps * 100:.1f}%)",
        f"- label lookup by application number: `{app_mode}`",
        f"- label lookup by brand fallback: `{brand_mode}`",
        f"- final `other_or_multisystem` applications: `{rare_count}` ({rare_count / unique_apps * 100:.1f}%)",
        "",
        "## Top therapeutic areas by event count",
        "",
    ]
    for _, row in top_area_rows.iterrows():
        qc_lines.append(
            f"- `{row['therapeutic_area_label']}`: n=`{int(row['n_events'])}`, "
            f"main public RWE=`{row['main_public_rwe_pct']:.1f}%`, "
            f"analytic public RWE=`{row['analytic_public_rwe_pct']:.1f}%`"
        )

    unresolved = lookup_df[lookup_df["therapeutic_area_collapsed"].eq("other_or_multisystem")].head(12)
    if not unresolved.empty:
        qc_lines.extend(["", "## Example applications still grouped as other/multisystem", ""])
        for _, row in unresolved.iterrows():
            qc_lines.append(
                f"- `{row['application_number_prefixed']}` `{row['Drug Name']}` "
                f"(rule=`{row['therapeutic_area_rule']}`, confidence=`{row['therapeutic_area_confidence']}`)"
            )

    QC_MD.write_text("\n".join(qc_lines) + "\n")

    report_lines = [
        "# Therapeutic Area Enrichment Report",
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
        "- source metadata: FDA `drugsfda` application endpoint plus FDA `drug/label` endpoint fallback",
        "- application key: prefixed application number such as `NDA020870`",
        "- therapeutic area classification: deterministic rule-based crosswalk using pharm class, indication text, route, and product metadata",
        "- this is an exploratory enrichment layer; it does not change the annotation endpoints",
        "",
        "## Coverage",
        "",
        f"- unique applications in the SrLC cohort: `{unique_apps}`",
        f"- `drugsfda` hits: `{drugsfda_hit}` ({drugsfda_hit / unique_apps * 100:.1f}%)",
        f"- label hits after fallback: `{label_hit}` ({label_hit / unique_apps * 100:.1f}%)",
        "",
        "## Highest-volume therapeutic areas",
        "",
    ]
    for _, row in top_area_rows.iterrows():
        report_lines.append(
            f"- `{row['therapeutic_area_label']}`: n=`{int(row['n_events'])}`, "
            f"main public RWE=`{row['main_public_rwe_pct']:.1f}%`, "
            f"analytic public RWE=`{row['analytic_public_rwe_pct']:.1f}%`, "
            f"mean transparency=`{row['mean_transparency_score']:.2f}`"
        )

    if not model_df.empty:
        report_lines.extend(["", "## Modeling highlights", ""])
        non_intercept = model_df[model_df["term"] != "Intercept"].sort_values(["outcome_label", "p_value"])
        for outcome_label, subset in non_intercept.groupby("outcome_label"):
            report_lines.append(f"- `{outcome_label}`:")
            top_subset = subset.head(6)
            for _, row in top_subset.iterrows():
                report_lines.append(
                    f"  - `{row['term_label']}`: PR `{row['prevalence_ratio']:.3f}` "
                    f"(95% CI `{row['pr_ci_lower']:.3f}` to `{row['pr_ci_upper']:.3f}`), p=`{row['p_value']:.4g}`"
                )

    report_lines.extend(
        [
            "",
            "## Initial recommendation",
            "",
            "- include therapeutic area in the paper only if it adds a clear heterogeneity result beyond section/severity",
            "- otherwise keep it as a supplement enrichment table and use it mainly to sharpen discussion and reviewer response",
        ]
    )

    REPORT_MD.write_text("\n".join(report_lines) + "\n")


def main() -> None:
    ensure_dirs()
    df = pd.read_csv(INPUT_CSV)

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
        .copy()
    )

    # First pass: drugsfda metadata for every application.
    app_records = app_df.to_dict("records")
    app_record_map = {row["application_number_prefixed"]: row for row in app_records}
    drugsfda_rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(fetch_drugsfda_row, row) for row in app_records]
        for future in as_completed(futures):
            result = future.result()
            row = app_record_map[result["application_number_prefixed"]]
            drugsfda_rows.append(parse_drugsfda_wrapper(row, result["wrapper"]))

    lookup_df = pd.DataFrame(drugsfda_rows).sort_values("application_number_prefixed").reset_index(drop=True)

    # Initial classification from drugsfda fields alone.
    initial_assignments = lookup_df.apply(classify_therapeutic_area, axis=1, result_type="expand")
    initial_assignments.columns = [
        "therapeutic_area_initial",
        "therapeutic_area_initial_label",
        "therapeutic_area_initial_rule",
        "therapeutic_area_initial_confidence",
    ]
    lookup_df = pd.concat([lookup_df, initial_assignments], axis=1)

    need_label_mask = (
        lookup_df["therapeutic_area_initial_confidence"].ne("high")
        | lookup_df["therapeutic_area_initial"].eq("other_or_multisystem")
        | lookup_df["pharm_class_epc"].eq("")
    )
    label_candidates = lookup_df[need_label_mask].copy()

    label_rows: list[dict[str, Any]] = []
    if not label_candidates.empty:
        label_records = label_candidates.to_dict("records")
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = [executor.submit(fetch_label_row, row) for row in label_records]
            for future in as_completed(futures):
                label_rows.append(future.result())

    label_df = pd.DataFrame(label_rows)
    if label_df.empty:
        for column in [
            "application_number_prefixed",
            "label_status",
            "label_lookup_mode",
            "label_brand_name",
            "label_generic_name",
            "label_route",
            "label_pharm_class_epc",
            "label_pharm_class_cs",
            "label_pharm_class_pe",
            "label_pharm_class_moa",
            "label_indications_text",
            "label_effective_time",
            "label_lookup_url",
        ]:
            label_df[column] = []

    lookup_df = lookup_df.merge(label_df, on="application_number_prefixed", how="left")
    for column in [
        "label_status",
        "label_lookup_mode",
        "label_brand_name",
        "label_generic_name",
        "label_route",
        "label_pharm_class_epc",
        "label_pharm_class_cs",
        "label_pharm_class_pe",
        "label_pharm_class_moa",
        "label_indications_text",
        "label_effective_time",
        "label_lookup_url",
    ]:
        if column not in lookup_df:
            lookup_df[column] = ""
        lookup_df[column] = lookup_df[column].fillna("")

    final_assignments = lookup_df.apply(classify_therapeutic_area, axis=1, result_type="expand")
    final_assignments.columns = [
        "therapeutic_area_raw",
        "therapeutic_area_raw_label",
        "therapeutic_area_rule",
        "therapeutic_area_confidence",
    ]
    lookup_df = pd.concat([lookup_df, final_assignments], axis=1)

    # Collapse rare groups for downstream modeling.
    app_counts = (
        lookup_df.groupby("therapeutic_area_raw", dropna=False)["application_number_prefixed"]
        .nunique()
        .sort_values(ascending=False)
    )
    rare_raw = set(app_counts[app_counts < 15].index.tolist())
    lookup_df["therapeutic_area_collapsed"] = lookup_df["therapeutic_area_raw"].where(
        ~lookup_df["therapeutic_area_raw"].isin(rare_raw),
        "other_or_multisystem",
    )

    label_map = (
        lookup_df.groupby("therapeutic_area_raw", dropna=False)["therapeutic_area_raw_label"]
        .first()
        .to_dict()
    )
    lookup_df["therapeutic_area_collapsed_label"] = lookup_df["therapeutic_area_collapsed"].map(
        lambda key: "Other/multisystem" if key == "other_or_multisystem" else label_map.get(key, key)
    )

    lookup_df.to_csv(LOOKUP_CSV, index=False)

    enriched_df = df.merge(
        lookup_df[
            [
                "application_number_prefixed",
                "Application Number",
                "Application Type",
                "therapeutic_area_raw",
                "therapeutic_area_raw_label",
                "therapeutic_area_collapsed",
                "therapeutic_area_collapsed_label",
                "therapeutic_area_rule",
                "therapeutic_area_confidence",
                "drugsfda_status",
                "label_status",
                "label_lookup_mode",
                "sponsor_name",
                "manufacturer_name",
                "product_brand_name",
                "generic_name",
                "route",
                "pharm_class_epc",
                "pharm_class_cs",
                "pharm_class_pe",
                "pharm_class_moa",
                "label_indications_text",
            ]
        ],
        on=["Application Number", "Application Type"],
        how="left",
    )
    enriched_df.to_csv(ENRICHED_CSV, index=False)

    outcomes_df = summarize_outcomes(enriched_df)
    outcomes_df.to_csv(OUTCOME_CSV, index=False)

    transparency_df = summarize_transparency(enriched_df)
    transparency_df.to_csv(TRANSPARENCY_CSV, index=False)

    # Modeling layer with therapeutic area added as a predictor.
    model_df = enriched_df.copy()
    model_df["application_number_cluster"] = model_df["Application Number"].astype(str)
    model_df["app_type"] = model_df["Application Type"].astype(str)
    model_df["year_centered"] = model_df["event_year"].astype(float) - 2020.0
    model_df["y_main_public_rwe"] = yes_no_to_num(model_df["endpoint_main_public_rwe"])
    model_df["y_analytic_public_rwe"] = yes_no_to_num(model_df["endpoint_secondary_analytic_public_rwe"])
    model_df["section_boxed_warning_num"] = yes_no_to_num(model_df["section_boxed_warning"])
    model_df["section_contraindications_num"] = yes_no_to_num(model_df["section_contraindications"])
    model_df["section_warnings_precautions_num"] = yes_no_to_num(model_df["section_warnings_precautions"])
    model_df["section_adverse_reactions_num"] = yes_no_to_num(model_df["section_adverse_reactions"])
    model_df["section_drug_interactions_num"] = yes_no_to_num(model_df["section_drug_interactions"])
    model_df["section_use_in_specific_populations_num"] = yes_no_to_num(model_df["section_use_in_specific_populations"])

    event_counts = (
        model_df.groupby("therapeutic_area_collapsed")["event_id"]
        .count()
        .sort_values(ascending=False)
    )
    rare_event_categories = set(event_counts[event_counts < MIN_CATEGORY_EVENTS].index.tolist())
    model_df["therapeutic_area_collapsed"] = model_df["therapeutic_area_collapsed"].where(
        ~model_df["therapeutic_area_collapsed"].isin(rare_event_categories),
        "other_or_multisystem",
    )
    collapsed_label_map = (
        lookup_df.groupby("therapeutic_area_collapsed")["therapeutic_area_collapsed_label"]
        .first()
        .to_dict()
    )
    model_df["therapeutic_area_collapsed_label"] = model_df["therapeutic_area_collapsed"].map(
        lambda key: "Other/multisystem" if key == "other_or_multisystem" else collapsed_label_map.get(key, key)
    )
    ordered_categories = model_df["therapeutic_area_collapsed"].value_counts().index.tolist()
    reference_category = ordered_categories[0]
    model_df["therapeutic_area_collapsed"] = pd.Categorical(
        model_df["therapeutic_area_collapsed"],
        categories=ordered_categories,
        ordered=True,
    )

    rhs = (
        "year_centered + C(app_type) + "
        "section_boxed_warning_num + section_contraindications_num + "
        "section_warnings_precautions_num + section_adverse_reactions_num + "
        "section_drug_interactions_num + section_use_in_specific_populations_num + "
        f"C(therapeutic_area_collapsed, Treatment(reference='{reference_category}'))"
    )

    main_model_df, main_fit = fit_modified_poisson(
        data=model_df,
        outcome="y_main_public_rwe",
        outcome_label="Main public RWE endpoint with therapeutic area",
        formula_rhs=rhs,
        model_name="model_main_public_rwe_with_therapeutic_area",
    )
    analytic_model_df, analytic_fit = fit_modified_poisson(
        data=model_df,
        outcome="y_analytic_public_rwe",
        outcome_label="Analytic public RWE endpoint with therapeutic area",
        formula_rhs=rhs,
        model_name="model_analytic_public_rwe_with_therapeutic_area",
    )

    category_labels = (
        model_df.groupby("therapeutic_area_collapsed", observed=False)["therapeutic_area_collapsed_label"]
        .first()
        .to_dict()
    )
    main_model_df["term_label"] = main_model_df["term"].apply(lambda term: prettify_term(term, category_labels))
    analytic_model_df["term_label"] = analytic_model_df["term"].apply(lambda term: prettify_term(term, category_labels))

    combined_model_df = pd.concat([main_model_df, analytic_model_df], ignore_index=True)
    combined_model_df.to_csv(MODEL_CSV, index=False)
    fit_summary_df = pd.DataFrame([main_fit, analytic_fit])
    fit_summary_df.to_csv(MODEL_FIT_CSV, index=False)

    write_reports(
        lookup_df=lookup_df,
        enriched_df=enriched_df,
        outcomes_df=outcomes_df,
        transparency_df=transparency_df,
        model_df=combined_model_df,
        fit_summary_df=fit_summary_df,
    )


if __name__ == "__main__":
    main()
