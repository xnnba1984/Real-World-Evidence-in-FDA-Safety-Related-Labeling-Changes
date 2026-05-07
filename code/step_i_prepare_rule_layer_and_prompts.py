#!/usr/bin/env python3
"""Build local rule-layer outputs and prompt-ready renders from annotation packets."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from statistics import mean, median
from typing import Dict, Iterable, List, Tuple


REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_DIR = REPO_ROOT
PACKET_DIR = BASE_DIR / "annotation_packets"
DESIGN_DIR = BASE_DIR / "annotation_design"
OUTPUT_DIR = BASE_DIR / "annotation_runtime"
DESIGN_VERSION = "v2"
PACKET_VERSION = "v1"
PROMPT_VERSION = "v2"

PACKETS_JSONL = PACKET_DIR / f"annotation_event_packets_{PACKET_VERSION}.jsonl"
PACKET_INDEX_CSV = PACKET_DIR / f"annotation_event_packet_index_{PACKET_VERSION}.csv"
CODEBOOK_MD = DESIGN_DIR / f"annotation_codebook_{DESIGN_VERSION}.md"
SCHEMA_JSON = DESIGN_DIR / f"annotation_output_schema_{DESIGN_VERSION}.json"

RULE_JSONL = OUTPUT_DIR / f"annotation_rule_layer_{PROMPT_VERSION}.jsonl"
RULE_INDEX_CSV = OUTPUT_DIR / f"annotation_rule_layer_index_{PROMPT_VERSION}.csv"
PROMPT_RENDER_JSONL = OUTPUT_DIR / f"annotation_prompt_render_{PROMPT_VERSION}.jsonl"
PROMPT_INDEX_CSV = OUTPUT_DIR / f"annotation_prompt_render_index_{PROMPT_VERSION}.csv"
PROMPT_SYSTEM_MD = OUTPUT_DIR / f"annotation_system_prompt_{PROMPT_VERSION}.md"
PROMPT_USER_TEMPLATE_MD = OUTPUT_DIR / f"annotation_user_prompt_template_{PROMPT_VERSION}.md"
REPORT_MD = OUTPUT_DIR / f"annotation_rule_prompt_report_{PROMPT_VERSION}.md"
STATS_JSON = OUTPUT_DIR / f"annotation_rule_prompt_stats_{PROMPT_VERSION}.json"


SOURCE_PATTERNS = {
    "claims": re.compile(r"\b(claims?|administrative claims|insurance claims)\b", re.IGNORECASE),
    "ehr": re.compile(r"\b(ehr|electronic health records?|medical records?)\b", re.IGNORECASE),
    "registry": re.compile(r"\b(registry|pregnancy registry|patient registry|disease registry)\b", re.IGNORECASE),
    "active_surveillance_network": re.compile(
        r"\b(sentinel|prism|best initiative|active surveillance|distributed data network)\b",
        re.IGNORECASE,
    ),
    "spontaneous_reports": re.compile(
        r"\b(spontaneous reports?|postmarketing reports?|pharmacovigilance|faers|medwatch|disproportionality)\b",
        re.IGNORECASE,
    ),
}

DESIGN_PATTERNS = {
    "active_comparator_cohort": re.compile(
        r"\b(active comparator|active-comparator|new user active comparator|new-user active comparator)\b",
        re.IGNORECASE,
    ),
    "case_control": re.compile(r"\b(case-control|case control)\b", re.IGNORECASE),
    "self_controlled_or_case_only": re.compile(
        r"\b(self-controlled|self controlled|sccs|scri|case-crossover|case crossover)\b",
        re.IGNORECASE,
    ),
    "cohort_non_active_comparator": re.compile(r"\b(cohort|retrospective cohort|prospective cohort)\b", re.IGNORECASE),
    "registry_analysis": re.compile(r"\b(registry|pregnancy registry|patient registry)\b", re.IGNORECASE),
    "active_surveillance_network_analysis": re.compile(
        r"\b(sentinel|prism|best initiative|active surveillance|distributed data network)\b",
        re.IGNORECASE,
    ),
    "spontaneous_reporting_analysis": re.compile(
        r"\b(spontaneous reports?|faers|medwatch|disproportionality)\b",
        re.IGNORECASE,
    ),
    "descriptive_observational": re.compile(
        r"\b(observational|retrospective|prospective|database study|medical record review)\b",
        re.IGNORECASE,
    ),
}

CONFOUNDING_PATTERNS = {
    "propensity_score_matching": re.compile(
        r"\b(propensity score matching|ps matching|matched on propensity score)\b",
        re.IGNORECASE,
    ),
    "propensity_score_weighting": re.compile(
        r"\b(propensity score weighting|inverse probability treatment weighting|iptw|stabilized weights?)\b",
        re.IGNORECASE,
    ),
    "propensity_score_stratification": re.compile(
        r"\b(propensity score stratification|stratified by propensity score)\b",
        re.IGNORECASE,
    ),
    "multivariable_regression": re.compile(
        r"\b(multivariable|multivariable regression|multivariate|adjusted model|cox regression|logistic regression|poisson regression)\b",
        re.IGNORECASE,
    ),
    "matching_non_ps": re.compile(r"\b(matched cohort|matching|matched analysis)\b", re.IGNORECASE),
    "stratification": re.compile(r"\b(stratified analysis|stratification)\b", re.IGNORECASE),
}

TRANSPARENCY_PATTERNS = {
    "design_stated": re.compile(
        r"\b(cohort|case-control|case control|registry|sentinel|observational|retrospective|prospective|self-controlled|active comparator)\b",
        re.IGNORECASE,
    ),
    "population_stated": re.compile(
        r"\b(patient|patients|population|cohort|women|men|adults?|children|neonates?|pregnan(?:t|cy)|subjects?)\b",
        re.IGNORECASE,
    ),
    "comparator_stated": re.compile(
        r"\b(comparator|control group|reference group|versus|vs\.?|compared with|compared to|active comparator)\b",
        re.IGNORECASE,
    ),
    "effect_measure_stated": re.compile(
        r"\b(hazard ratio|odds ratio|risk ratio|relative risk|incidence rate ratio|rate ratio|risk difference|rate difference)\b",
        re.IGNORECASE,
    ),
    "confounding_strategy_stated": re.compile(
        r"\b(propensity|matching|weighting|inverse probability|multivariable|multivariate|adjusted model|stratification)\b",
        re.IGNORECASE,
    ),
    "missing_data_stated": re.compile(
        r"\b(missing data|imputation|multiple imputation|complete case)\b",
        re.IGNORECASE,
    ),
    "sensitivity_analysis_stated": re.compile(
        r"\b(sensitivity analys(?:is|es)|robustness analys(?:is|es)|secondary analys(?:is|es)|alternate specification)\b",
        re.IGNORECASE,
    ),
    "uncertainty_measure_stated": re.compile(
        r"\b(confidence interval|credible interval|\bp-value\b|\bp value\b|standard error|95% ci)\b",
        re.IGNORECASE,
    ),
}

RWE_GENERIC_PATTERN = re.compile(
    r"\b(real[- ]world evidence|real[- ]world data|\brwe\b|\brwd\b)\b",
    re.IGNORECASE,
)

NEGATIVE_CONTROL_PATTERN = re.compile(
    r"\b(negative control|falsification outcome|falsification exposure)\b",
    re.IGNORECASE,
)

SENSITIVITY_PATTERN = TRANSPARENCY_PATTERNS["sensitivity_analysis_stated"]
MISSING_DATA_PATTERN = TRANSPARENCY_PATTERNS["missing_data_stated"]
ANALYTIC_PATTERN = re.compile(
    r"\b(observational|cohort|case-control|case control|retrospective|prospective|self-controlled|sccs|scri|case-crossover|matching|weighting|multivariable|adjusted model|hazard ratio|odds ratio|risk ratio|confidence interval|p-value)\b",
    re.IGNORECASE,
)


RULE_FIELDS = [
    "event_id",
    "packet_hash",
    "packet_type",
    "selected_doc_count",
    "selected_snippet_count",
    "public_evidence_available_rule",
    "evidence_explicitness_tier_rule",
    "analytic_signal_present_rule",
    "rwe_documented_publicly_rule",
    "analytic_rwe_documented_rule",
    "rwe_source_type_candidates",
    "primary_design_category_rule",
    "confounding_control_rule",
    "transparency_score_rule",
    "design_stated_rule",
    "population_stated_rule",
    "comparator_stated_rule",
    "effect_measure_stated_rule",
    "confounding_strategy_stated_rule",
    "missing_data_stated_rule",
    "missing_data_handling_documented_rule",
    "sensitivity_analysis_stated_rule",
    "sensitivity_analyses_documented_rule",
    "uncertainty_measure_stated_rule",
    "negative_controls_documented_rule",
    "expand_context_candidate",
    "expand_context_reasons",
    "needs_strong_model_candidate",
]

PROMPT_INDEX_FIELDS = [
    "event_id",
    "packet_hash",
    "prompt_version",
    "prompt_char_count",
    "system_prompt_path",
    "schema_path",
    "expand_context_candidate",
    "needs_strong_model_candidate",
    "rule_rwe_documented_publicly",
    "rule_analytic_rwe_documented",
]


def yes_no(value: bool) -> str:
    return "yes" if value else "no"


def likely(value: str) -> str:
    return value


def packet_text(packet: Dict[str, object]) -> str:
    chunks: List[str] = [str(packet["event"].get("change_text", ""))]
    for doc in packet.get("selected_documents", []):
        for snippet in doc.get("snippets", []):
            chunks.append(str(snippet.get("text", "")))
    return "\n".join(chunk for chunk in chunks if chunk).strip()


def doc_summary(packet: Dict[str, object]) -> List[Dict[str, object]]:
    docs: List[Dict[str, object]] = []
    for doc in packet.get("selected_documents", []):
        docs.append(
            {
                "doc_id": doc.get("doc_id", ""),
                "source_domain": doc.get("source_domain", ""),
                "url_type_guess": doc.get("url_type_guess", ""),
                "download_status": doc.get("download_status", ""),
                "text_extract_status": doc.get("text_extract_status", ""),
                "selection_reason": doc.get("selection_reason", []),
                "snippet_count": len(doc.get("snippets", [])),
            }
        )
    return docs


def choose_source_candidates(text: str) -> List[str]:
    return [name for name, pattern in SOURCE_PATTERNS.items() if pattern.search(text)]


def choose_design(text: str, source_candidates: List[str]) -> str:
    if DESIGN_PATTERNS["active_comparator_cohort"].search(text):
        return "active_comparator_cohort"
    if DESIGN_PATTERNS["case_control"].search(text):
        return "case_control"
    if DESIGN_PATTERNS["self_controlled_or_case_only"].search(text):
        return "self_controlled_or_case_only"
    if DESIGN_PATTERNS["active_surveillance_network_analysis"].search(text):
        return "active_surveillance_network_analysis"
    if DESIGN_PATTERNS["registry_analysis"].search(text) and "registry" in source_candidates:
        return "registry_analysis"
    if DESIGN_PATTERNS["spontaneous_reporting_analysis"].search(text) and not set(source_candidates).intersection(
        {"claims", "ehr", "registry", "active_surveillance_network"}
    ):
        return "spontaneous_reporting_analysis"
    if DESIGN_PATTERNS["cohort_non_active_comparator"].search(text):
        return "cohort_non_active_comparator"
    if DESIGN_PATTERNS["descriptive_observational"].search(text):
        return "descriptive_observational"
    return "unknown"


def choose_confounding(text: str) -> str:
    hits = [
        name
        for name, pattern in CONFOUNDING_PATTERNS.items()
        if pattern.search(text)
    ]
    if not hits:
        return "none_documented"

    ordered = []
    for name in hits:
        if name == "matching_non_ps" and (
            "propensity_score_matching" in hits
            or "propensity_score_weighting" in hits
            or "propensity_score_stratification" in hits
        ):
            continue
        ordered.append(name)

    ordered = list(dict.fromkeys(ordered))
    if len(ordered) > 1:
        return "multiple_methods"
    return ordered[0]


def transparency_components(text: str) -> Dict[str, str]:
    result = {}
    for name, pattern in TRANSPARENCY_PATTERNS.items():
        result[name] = yes_no(bool(pattern.search(text)))
    return result


def evidence_explicitness_tier(
    public_evidence_available: bool,
    has_explicit_rwe: bool,
    source_candidates: List[str],
    analytic_signal: bool,
    spontaneous_only: bool,
) -> str:
    if not public_evidence_available:
        return "no_public_basis_found"
    if has_explicit_rwe:
        return "explicit_rwe"
    if set(source_candidates).intersection({"claims", "ehr", "registry", "active_surveillance_network"}) and analytic_signal:
        return "explicit_observational_real_world"
    if spontaneous_only:
        return "spontaneous_reports_only"
    return "unclear_public_basis"


def expand_context_decision(packet: Dict[str, object], source_candidates: List[str], analytic_signal: bool) -> Tuple[str, List[str]]:
    retrieval = packet["retrieval"]
    linked_total = int(retrieval.get("linked_doc_count_total", 0))
    selected_docs = int(retrieval.get("selected_doc_count", 0))
    extracted_docs = int(retrieval.get("extracted_doc_count", 0))
    selected_snippets = int(retrieval.get("selected_snippet_count", 0))
    reasons: List[str] = []

    if extracted_docs > selected_docs:
        reasons.append("omitted_extracted_docs")
    if selected_docs >= 3:
        reasons.append("multi_doc_selection")
    if selected_snippets >= 4:
        reasons.append("dense_selected_snippets")
    if len(source_candidates) >= 2:
        reasons.append("multiple_source_types")
    if analytic_signal and linked_total > 1:
        reasons.append("analytic_signal_with_multi_doc_context")

    reasons = list(dict.fromkeys(reasons))
    return yes_no(bool(reasons)), reasons


def heuristic_rule_output(packet: Dict[str, object]) -> Dict[str, object]:
    retrieval = packet["retrieval"]
    text = packet_text(packet)
    public_evidence_available = int(retrieval.get("selected_snippet_count", 0)) > 0
    has_explicit_rwe = bool(RWE_GENERIC_PATTERN.search(text))
    source_candidates = choose_source_candidates(text)
    analytic_signal = bool(ANALYTIC_PATTERN.search(text))
    spontaneous_only = "spontaneous_reports" in source_candidates and not set(source_candidates).intersection(
        {"claims", "ehr", "registry", "active_surveillance_network"}
    )

    tier = evidence_explicitness_tier(
        public_evidence_available,
        has_explicit_rwe,
        source_candidates,
        analytic_signal,
        spontaneous_only,
    )
    if has_explicit_rwe or (
        set(source_candidates).intersection({"claims", "ehr", "registry", "active_surveillance_network"}) and analytic_signal
    ):
        rwe_rule = "likely_yes"
    elif public_evidence_available and (source_candidates or analytic_signal):
        rwe_rule = "uncertain"
    else:
        rwe_rule = "likely_no"

    if set(source_candidates).intersection({"claims", "ehr", "registry", "active_surveillance_network"}) and analytic_signal:
        analytic_rule = "likely_yes"
    elif public_evidence_available and (analytic_signal or source_candidates):
        analytic_rule = "uncertain"
    else:
        analytic_rule = "likely_no"

    design_rule = choose_design(text, source_candidates)
    confounding_rule = choose_confounding(text)
    transparency = transparency_components(text)
    transparency_score = sum(1 for value in transparency.values() if value == "yes")
    negative_controls = yes_no(bool(NEGATIVE_CONTROL_PATTERN.search(text)))
    sensitivity_yes = yes_no(bool(SENSITIVITY_PATTERN.search(text)))
    missing_data_yes = yes_no(bool(MISSING_DATA_PATTERN.search(text)))
    expand_flag, expand_reasons = expand_context_decision(packet, source_candidates, analytic_signal)

    needs_strong_model = (
        rwe_rule != "likely_no"
        or analytic_rule != "likely_no"
        or expand_flag == "yes"
        or retrieval.get("packet_type") == "metadata_only"
    )

    return {
        "event_id": packet["event"]["event_id"],
        "packet_hash": packet["packet_hash"],
        "packet_type": retrieval["packet_type"],
        "selected_doc_count": int(retrieval.get("selected_doc_count", 0)),
        "selected_snippet_count": int(retrieval.get("selected_snippet_count", 0)),
        "public_evidence_available_rule": yes_no(public_evidence_available),
        "evidence_explicitness_tier_rule": tier,
        "analytic_signal_present_rule": yes_no(analytic_signal),
        "rwe_documented_publicly_rule": likely(rwe_rule),
        "analytic_rwe_documented_rule": likely(analytic_rule),
        "rwe_source_type_candidates": source_candidates,
        "primary_design_category_rule": design_rule,
        "confounding_control_rule": confounding_rule,
        "negative_controls_documented_rule": negative_controls,
        "missing_data_handling_documented_rule": missing_data_yes,
        "sensitivity_analyses_documented_rule": sensitivity_yes,
        "design_stated_rule": transparency["design_stated"],
        "population_stated_rule": transparency["population_stated"],
        "comparator_stated_rule": transparency["comparator_stated"],
        "effect_measure_stated_rule": transparency["effect_measure_stated"],
        "confounding_strategy_stated_rule": transparency["confounding_strategy_stated"],
        "missing_data_stated_rule": transparency["missing_data_stated"],
        "sensitivity_analysis_stated_rule": transparency["sensitivity_analysis_stated"],
        "uncertainty_measure_stated_rule": transparency["uncertainty_measure_stated"],
        "transparency_score_rule": transparency_score,
        "expand_context_candidate": expand_flag,
        "expand_context_reasons": expand_reasons,
        "needs_strong_model_candidate": yes_no(needs_strong_model),
        "doc_summary": doc_summary(packet),
    }


def build_system_prompt(schema_path: Path, codebook_path: Path) -> str:
    return (
        "You are annotating one FDA SrLC event for real-world-evidence documentation.\n\n"
        "Use only the supplied event packet, heuristic summary, and selected evidence snippets.\n"
        "Do not use outside knowledge. Do not infer unsupported methods or data sources.\n"
        "When evidence is absent or weak, stay conservative.\n"
        "Keep the response compact.\n\n"
        "Core label meanings:\n"
        "- `rwe_documented_publicly = yes` only if the public materials explicitly document RWE/RWD or explicit observational real-world evidence relevant to the specific safety labeling change.\n"
        "- `analytic_rwe_documented = yes` only if an analytic use of real-world data is explicitly documented; spontaneous reports alone do not qualify.\n"
        "- `rwe_relevance_to_change = direct` only when the public evidence is clearly tied to the specific safety issue or label change in this event.\n"
        "- Use `possible_but_not_explicit` or `unclear` when public evidence exists but the link to the event-specific change is indirect or uncertain.\n"
        "- Use `not_apparent` when no usable public evidence appears relevant to the specific safety change.\n"
        "- For `rwe_source_type_primary`, `primary_design_category`, and `confounding_control`, use explicit evidence only; otherwise prefer `unknown` or `none_documented`.\n"
        "- `public_evidence_available = yes` only when the packet contains usable public material relevant to the event evidence basis.\n"
        "- `evidence_explicitness_tier` captures whether the packet shows explicit RWE, explicit observational real-world evidence, spontaneous reports only, unclear public basis, or no public basis found.\n"
        "- If you choose `evidence_explicitness_tier = no_public_basis_found`, then `public_evidence_available` should be `no`.\n"
        "- `annotation_evidence_strength` should reflect how substantively useful the public evidence is for this event: `strong`, `moderate`, `weak`, or `insufficient`.\n"
        "- The transparency component fields should be `yes` only when the corresponding item is explicitly stated in the supplied evidence.\n\n"
        "Required behavior:\n"
        "- Return one JSON object only.\n"
        "- Follow the output schema exactly.\n"
        "- Treat the heuristic summary as fallible hints, not as truth.\n"
        "- Support any positive or method-detail label with snippet-backed evidence.\n"
        "- If the evidence is insufficient, reflect that in the output rather than guessing.\n"
        "- Use at most 2 supporting_evidence items unless absolutely necessary.\n"
        "- For each supporting_evidence item, list only the labels directly supported by that snippet.\n"
        "- Do not repeat the same label name multiple times inside supports_labels.\n"
        "- Keep notes brief and non-redundant.\n"
        "- `transparency_score` is computed locally later; do not output it.\n\n"
        "Key consistency rules:\n"
        "- `analytic_rwe_documented = yes` requires `rwe_documented_publicly = yes`.\n"
        "- `rwe_documented_publicly = yes` should usually coincide with `rwe_relevance_to_change = direct`.\n"
        "- If `public_evidence_available = no`, use empty `supporting_evidence` and do not claim positive RWE or analytic detail labels.\n\n"
        f"Schema path: {schema_path}\n"
        f"Codebook path: {codebook_path}\n"
    )


def build_user_prompt(packet: Dict[str, object], rule_row: Dict[str, object]) -> str:
    event = packet["event"]
    retrieval = packet["retrieval"]
    lines: List[str] = []
    lines.append(f"Event ID: {event['event_id']}")
    lines.append(f"Drug: {event['drug_name']} ({event['active_ingredient']})")
    lines.append(f"Application: {event['application_number']} {event['application_type']}")
    lines.append(f"Event header: {event['event_header']}")
    lines.append(f"Label sections changed: {event['label_section_changed']}")
    lines.append("")
    lines.append("Change text:")
    lines.append(event["change_text"])
    lines.append("")
    lines.append("Local heuristic summary (non-binding, may be wrong):")
    lines.append(f"- public_evidence_available_rule: {rule_row['public_evidence_available_rule']}")
    lines.append(f"- evidence_explicitness_tier_rule: {rule_row['evidence_explicitness_tier_rule']}")
    lines.append(f"- analytic_signal_present_rule: {rule_row['analytic_signal_present_rule']}")
    lines.append(f"- rwe_documented_publicly_rule: {rule_row['rwe_documented_publicly_rule']}")
    lines.append(f"- analytic_rwe_documented_rule: {rule_row['analytic_rwe_documented_rule']}")
    lines.append(
        "- rwe_source_type_candidates: "
        + (", ".join(rule_row["rwe_source_type_candidates"]) if rule_row["rwe_source_type_candidates"] else "none")
    )
    lines.append(f"- primary_design_category_rule: {rule_row['primary_design_category_rule']}")
    lines.append(f"- confounding_control_rule: {rule_row['confounding_control_rule']}")
    lines.append(f"- transparency_score_rule: {rule_row['transparency_score_rule']}")
    lines.append(f"- expand_context_candidate: {rule_row['expand_context_candidate']}")
    if rule_row["expand_context_reasons"]:
        lines.append("- expand_context_reasons: " + ", ".join(rule_row["expand_context_reasons"]))
    lines.append("")
    lines.append("Evidence packet:")
    lines.append(
        f"- packet_type: {retrieval['packet_type']}; selected_doc_count: {retrieval['selected_doc_count']}; selected_snippet_count: {retrieval['selected_snippet_count']}"
    )
    lines.append(
        f"- query_terms: {', '.join(retrieval['query_terms']) if retrieval['query_terms'] else 'none'}"
    )
    lines.append("")
    for idx, doc in enumerate(packet.get("selected_documents", []), 1):
        lines.append(
            f"Document {idx}: doc_id={doc.get('doc_id','')} domain={doc.get('source_domain','')} "
            f"type={doc.get('url_type_guess','')} download_status={doc.get('download_status','')} "
            f"text_extract_status={doc.get('text_extract_status','')} selection_reason={','.join(doc.get('selection_reason', []))}"
        )
        if doc.get("snippets"):
            for snip_idx, snippet in enumerate(doc["snippets"], 1):
                lines.append(
                    f"Snippet {snip_idx} from Document {idx}: {snippet.get('text','')}"
                )
        lines.append("")
    if not packet.get("selected_documents"):
        lines.append("No selected documents were available for this event.")
        lines.append("")
    lines.append("Return only the annotation JSON object.")
    return "\n".join(lines).strip() + "\n"


def prompt_template_text() -> str:
    return (
        f"# Annotation User Prompt Template {PROMPT_VERSION}\n\n"
        "Each rendered prompt contains:\n"
        "- event metadata\n"
        "- full `change_text`\n"
        "- a non-binding heuristic summary from the local rule layer\n"
        "- selected document metadata\n"
        "- selected evidence snippets\n\n"
        "The heuristic section is included to guide attention, but the model is instructed to treat it as fallible.\n"
        "The final annotation must be grounded in the packet evidence rather than in the heuristic itself.\n"
    )


def build_report(rule_rows: List[Dict[str, object]], prompt_rows: List[Dict[str, object]]) -> Tuple[Dict[str, object], str]:
    rwe_counts = Counter(row["rwe_documented_publicly_rule"] for row in rule_rows)
    analytic_counts = Counter(row["analytic_rwe_documented_rule"] for row in rule_rows)
    packet_types = Counter(row["packet_type"] for row in rule_rows)
    expand_counts = Counter(row["expand_context_candidate"] for row in rule_rows)
    strong_model_counts = Counter(row["needs_strong_model_candidate"] for row in rule_rows)
    prompt_sizes = [row["prompt_char_count"] for row in prompt_rows]

    stats = {
        "rule_rows": len(rule_rows),
        "prompt_rows": len(prompt_rows),
        "packet_type_counts": dict(packet_types),
        "rwe_rule_counts": dict(rwe_counts),
        "analytic_rule_counts": dict(analytic_counts),
        "expand_context_counts": dict(expand_counts),
        "needs_strong_model_counts": dict(strong_model_counts),
        "prompt_char_mean": round(mean(prompt_sizes), 1) if prompt_sizes else 0,
        "prompt_char_median": median(prompt_sizes) if prompt_sizes else 0,
        "prompt_char_p90": sorted(prompt_sizes)[int(0.9 * len(prompt_sizes)) - 1] if prompt_sizes else 0,
    }

    lines = [
        f"# Annotation Rule Layer And Prompt Preparation Report {PROMPT_VERSION}",
        "",
        f"- Rule rows: `{stats['rule_rows']}`",
        f"- Prompt rows: `{stats['prompt_rows']}`",
        f"- Mean prompt size (chars): `{stats['prompt_char_mean']}`",
        f"- Median prompt size (chars): `{stats['prompt_char_median']}`",
        f"- P90 prompt size (chars): `{stats['prompt_char_p90']}`",
        "",
        "## Packet Types",
    ]
    for key, value in sorted(packet_types.items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Rule-Level RWE Counts"])
    for key, value in sorted(rwe_counts.items()):
        lines.append(f"- `rwe_documented_publicly_rule={key}`: `{value}`")
    lines.extend(["", "## Rule-Level Analytic Counts"])
    for key, value in sorted(analytic_counts.items()):
        lines.append(f"- `analytic_rwe_documented_rule={key}`: `{value}`")
    lines.extend(["", "## Expansion And Strong-Model Candidates"])
    for key, value in sorted(expand_counts.items()):
        lines.append(f"- `expand_context_candidate={key}`: `{value}`")
    for key, value in sorted(strong_model_counts.items()):
        lines.append(f"- `needs_strong_model_candidate={key}`: `{value}`")
    return stats, "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-dir", type=Path, default=BASE_DIR)
    args = parser.parse_args()

    base_dir = args.base_dir.resolve()
    output_dir = base_dir / OUTPUT_DIR.relative_to(BASE_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    system_prompt = build_system_prompt(
        base_dir / SCHEMA_JSON.relative_to(BASE_DIR),
        base_dir / CODEBOOK_MD.relative_to(BASE_DIR),
    )
    (output_dir / PROMPT_SYSTEM_MD.name).write_text(system_prompt)
    (output_dir / PROMPT_USER_TEMPLATE_MD.name).write_text(prompt_template_text())

    rule_rows: List[Dict[str, object]] = []
    prompt_rows: List[Dict[str, object]] = []

    with (base_dir / PACKETS_JSONL.relative_to(BASE_DIR)).open() as src, \
        (output_dir / RULE_JSONL.name).open("w") as rule_handle, \
        (output_dir / PROMPT_RENDER_JSONL.name).open("w") as prompt_handle:
        for line in src:
            packet = json.loads(line)
            rule_row = heuristic_rule_output(packet)
            user_prompt = build_user_prompt(packet, rule_row)
            prompt_hash = hashlib.sha1(
                (
                    packet["packet_hash"]
                    + "::"
                    + str(rule_row["rwe_documented_publicly_rule"])
                    + "::"
                    + user_prompt
                ).encode("utf-8")
            ).hexdigest()

            prompt_row = {
                "event_id": packet["event"]["event_id"],
                "packet_hash": packet["packet_hash"],
                "prompt_version": PROMPT_VERSION,
                "prompt_hash": prompt_hash,
                "prompt_char_count": len(user_prompt),
                "system_prompt_path": str(output_dir / PROMPT_SYSTEM_MD.name),
                "schema_path": str(base_dir / SCHEMA_JSON.relative_to(BASE_DIR)),
                "expand_context_candidate": rule_row["expand_context_candidate"],
                "needs_strong_model_candidate": rule_row["needs_strong_model_candidate"],
                "rule_rwe_documented_publicly": rule_row["rwe_documented_publicly_rule"],
                "rule_analytic_rwe_documented": rule_row["analytic_rwe_documented_rule"],
                "user_prompt": user_prompt,
            }

            rule_handle.write(json.dumps(rule_row, ensure_ascii=True) + "\n")
            prompt_handle.write(json.dumps(prompt_row, ensure_ascii=True) + "\n")
            rule_rows.append(rule_row)
            prompt_rows.append(prompt_row)

    with (output_dir / RULE_INDEX_CSV.name).open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RULE_FIELDS)
        writer.writeheader()
        for row in rule_rows:
            csv_row = {
                "event_id": row["event_id"],
                "packet_hash": row["packet_hash"],
                "packet_type": row["packet_type"],
                "selected_doc_count": row["selected_doc_count"],
                "selected_snippet_count": row["selected_snippet_count"],
                "public_evidence_available_rule": row["public_evidence_available_rule"],
                "evidence_explicitness_tier_rule": row["evidence_explicitness_tier_rule"],
                "analytic_signal_present_rule": row["analytic_signal_present_rule"],
                "rwe_documented_publicly_rule": row["rwe_documented_publicly_rule"],
                "analytic_rwe_documented_rule": row["analytic_rwe_documented_rule"],
                "rwe_source_type_candidates": "|".join(row["rwe_source_type_candidates"]),
                "primary_design_category_rule": row["primary_design_category_rule"],
                "confounding_control_rule": row["confounding_control_rule"],
                "transparency_score_rule": row["transparency_score_rule"],
                "design_stated_rule": row["design_stated_rule"],
                "population_stated_rule": row["population_stated_rule"],
                "comparator_stated_rule": row["comparator_stated_rule"],
                "effect_measure_stated_rule": row["effect_measure_stated_rule"],
                "confounding_strategy_stated_rule": row["confounding_strategy_stated_rule"],
                "missing_data_stated_rule": row["missing_data_stated_rule"],
                "missing_data_handling_documented_rule": row["missing_data_handling_documented_rule"],
                "sensitivity_analysis_stated_rule": row["sensitivity_analysis_stated_rule"],
                "sensitivity_analyses_documented_rule": row["sensitivity_analyses_documented_rule"],
                "uncertainty_measure_stated_rule": row["uncertainty_measure_stated_rule"],
                "negative_controls_documented_rule": row["negative_controls_documented_rule"],
                "expand_context_candidate": row["expand_context_candidate"],
                "expand_context_reasons": "|".join(row["expand_context_reasons"]),
                "needs_strong_model_candidate": row["needs_strong_model_candidate"],
            }
            writer.writerow(csv_row)

    with (output_dir / PROMPT_INDEX_CSV.name).open("w", newline="") as handle:
        fieldnames = PROMPT_INDEX_FIELDS
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in prompt_rows:
            writer.writerow({key: row[key] for key in fieldnames})

    stats, report_text = build_report(rule_rows, prompt_rows)
    (output_dir / STATS_JSON.name).write_text(json.dumps(stats, indent=2))
    (output_dir / REPORT_MD.name).write_text(report_text)

    print(f"Rule rows written: {len(rule_rows)}")
    print(f"Prompt rows written: {len(prompt_rows)}")
    print(f"Rule JSONL: {output_dir / RULE_JSONL.name}")
    print(f"Prompt JSONL: {output_dir / PROMPT_RENDER_JSONL.name}")
    print(f"Report: {output_dir / REPORT_MD.name}")


if __name__ == "__main__":
    main()
