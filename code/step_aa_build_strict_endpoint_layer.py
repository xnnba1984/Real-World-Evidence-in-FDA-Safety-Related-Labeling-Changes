#!/usr/bin/env python3
"""Build the narrowed endpoint layer and audit report for the main analysis."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_DIR = REPO_ROOT
IN_CSV = BASE_DIR / "analysis_ready" / "srlc_analysis_feature_layer.csv"
OUT_DIR = BASE_DIR / "analysis_ready"

OUT_CSV = OUT_DIR / "srlc_analysis_endpoint_layer.csv"
REPORT_MD = OUT_DIR / "endpoint_audit_report.md"
COUNTS_CSV = OUT_DIR / "endpoint_audit_counts.csv"


ENDPOINTS = [
    ("endpoint_main_public_rwe", "Main endpoint", "rwe_documented_publicly = yes"),
    ("endpoint_secondary_analytic_public_rwe", "Key secondary endpoint", "analytic_rwe_documented = yes"),
    ("endpoint_sens_explicit_public_rwe", "Sensitivity endpoint", "explicit_public_rwe_any_flag = yes"),
    (
        "endpoint_sens_non_spontaneous_public_rwe",
        "Sensitivity endpoint",
        "rwe_documented_publicly = yes and spontaneous_reports_only_flag = no",
    ),
    (
        "endpoint_sens_qc_strict_public_rwe",
        "Sensitivity endpoint",
        "rwe_documented_publicly = yes and hard_issue_flag = no",
    ),
]


def yes_no(flag: bool) -> str:
    return "yes" if flag else "no"


def pct(numer: int, denom: int) -> str:
    return f"{(numer / denom * 100) if denom else 0:.2f}%"


def count_table_rows(df: pd.DataFrame) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    total_n = len(df)
    for field, role, definition in ENDPOINTS:
        subset = df[df[field] == "yes"]
        rows.append(
            {
                "field": field,
                "role": role,
                "definition": definition,
                "subset": "overall",
                "value": "yes",
                "count": str(len(subset)),
                "pct": f"{(len(subset) / total_n * 100):.4f}",
            }
        )
        for subfield in ["final_label_source", "annotation_confidence", "hard_issue_flag", "spontaneous_reports_only_flag"]:
            counter = Counter(subset[subfield])
            for value, count in counter.items():
                rows.append(
                    {
                        "field": field,
                        "role": role,
                        "definition": definition,
                        "subset": subfield,
                        "value": str(value),
                        "count": str(count),
                        "pct": f"{(count / len(subset) * 100) if len(subset) else 0:.4f}",
                    }
                )
    return rows


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(IN_CSV)
    total_n = len(df)

    # Freeze the narrowed endpoint family.
    broad_yes = df["rwe_documented_publicly"].eq("yes")
    raw_analytic_yes = df["analytic_rwe_documented"].eq("yes")
    coerced_analytic_without_broad = raw_analytic_yes & ~broad_yes

    df["endpoint_main_public_rwe"] = broad_yes.map(yes_no)
    # Enforce the frozen codebook rule that analytic positives must also be broad positives.
    df["endpoint_secondary_analytic_public_rwe"] = (raw_analytic_yes & broad_yes).map(yes_no)
    df["endpoint_sens_explicit_public_rwe"] = df["explicit_public_rwe_any_flag"].eq("yes").map(yes_no)
    df["endpoint_sens_non_spontaneous_public_rwe"] = (
        broad_yes & df["spontaneous_reports_only_flag"].ne("yes")
    ).map(yes_no)
    df["endpoint_sens_qc_strict_public_rwe"] = (
        broad_yes & df["hard_issue_flag"].ne("yes")
    ).map(yes_no)

    # Simple delta helpers for later reporting.
    broad_yes = df["endpoint_main_public_rwe"].eq("yes")
    df["endpoint_main_not_explicit_flag"] = (broad_yes & df["endpoint_sens_explicit_public_rwe"].ne("yes")).map(yes_no)
    df["endpoint_main_nonanalytic_flag"] = (
        broad_yes & df["endpoint_secondary_analytic_public_rwe"].ne("yes")
    ).map(yes_no)
    df["endpoint_main_spontaneous_only_flag"] = (
        broad_yes & df["spontaneous_reports_only_flag"].eq("yes")
    ).map(yes_no)
    df["endpoint_main_hard_issue_flag"] = (
        broad_yes & df["hard_issue_flag"].eq("yes")
    ).map(yes_no)

    df.to_csv(OUT_CSV, index=False)
    pd.DataFrame(count_table_rows(df)).to_csv(COUNTS_CSV, index=False)

    # Audit summary.
    broad_n = int(df["endpoint_main_public_rwe"].eq("yes").sum())
    analytic_n = int(df["endpoint_secondary_analytic_public_rwe"].eq("yes").sum())
    explicit_n = int(df["endpoint_sens_explicit_public_rwe"].eq("yes").sum())
    non_sp_n = int(df["endpoint_sens_non_spontaneous_public_rwe"].eq("yes").sum())
    qc_n = int(df["endpoint_sens_qc_strict_public_rwe"].eq("yes").sum())
    coerced_analytic_n = int(coerced_analytic_without_broad.sum())

    broad_and_analytic = int((df["endpoint_main_public_rwe"].eq("yes") & df["endpoint_secondary_analytic_public_rwe"].eq("yes")).sum())
    broad_and_explicit = int((df["endpoint_main_public_rwe"].eq("yes") & df["endpoint_sens_explicit_public_rwe"].eq("yes")).sum())
    broad_sp_only = int(df["endpoint_main_spontaneous_only_flag"].eq("yes").sum())
    broad_hard_issue = int(df["endpoint_main_hard_issue_flag"].eq("yes").sum())
    broad_nonanalytic = int(df["endpoint_main_nonanalytic_flag"].eq("yes").sum())
    broad_not_explicit = int(df["endpoint_main_not_explicit_flag"].eq("yes").sum())

    provenance_main = Counter(df.loc[df["endpoint_main_public_rwe"] == "yes", "final_label_source"])
    confidence_main = Counter(df.loc[df["endpoint_main_public_rwe"] == "yes", "annotation_confidence"])
    provenance_analytic = Counter(df.loc[df["endpoint_secondary_analytic_public_rwe"] == "yes", "final_label_source"])
    confidence_analytic = Counter(df.loc[df["endpoint_secondary_analytic_public_rwe"] == "yes", "annotation_confidence"])

    lines = [
        "# Endpoint Audit Report",
        "",
        f"- input feature layer: `{IN_CSV}`",
        f"- output endpoint layer: `{OUT_CSV}`",
        f"- output count summary: `{COUNTS_CSV}`",
        f"- total events: `{total_n}`",
        "",
        "## Frozen endpoint family",
        "",
        "- Main endpoint:",
        "  - `endpoint_main_public_rwe` = `rwe_documented_publicly = yes`",
        "- Key secondary endpoint:",
        "  - `endpoint_secondary_analytic_public_rwe` = `analytic_rwe_documented = yes`",
        "- Sensitivity-only endpoints:",
        "  - `endpoint_sens_explicit_public_rwe` = `explicit_public_rwe_any_flag = yes`",
        "  - `endpoint_sens_non_spontaneous_public_rwe` = broad endpoint excluding `spontaneous_reports_only_flag = yes`",
        "  - `endpoint_sens_qc_strict_public_rwe` = broad endpoint excluding `hard_issue_flag = yes`",
        "",
        "## Overall endpoint counts",
        "",
        f"- `endpoint_main_public_rwe = yes`: `{broad_n}` ({pct(broad_n, total_n)})",
        f"- `endpoint_secondary_analytic_public_rwe = yes`: `{analytic_n}` ({pct(analytic_n, total_n)})",
        f"- `endpoint_sens_explicit_public_rwe = yes`: `{explicit_n}` ({pct(explicit_n, total_n)})",
        f"- `endpoint_sens_non_spontaneous_public_rwe = yes`: `{non_sp_n}` ({pct(non_sp_n, total_n)})",
        f"- `endpoint_sens_qc_strict_public_rwe = yes`: `{qc_n}` ({pct(qc_n, total_n)})",
        f"- raw `analytic_rwe_documented = yes` rows coerced off because `rwe_documented_publicly = no`: `{coerced_analytic_n}`",
        "",
        "## Main endpoint decomposition",
        "",
        f"- broad positives that are also analytic positives: `{broad_and_analytic}` ({pct(broad_and_analytic, broad_n)})",
        f"- broad positives that are also explicit positives: `{broad_and_explicit}` ({pct(broad_and_explicit, broad_n)})",
        f"- broad positives that are non-analytic: `{broad_nonanalytic}` ({pct(broad_nonanalytic, broad_n)})",
        f"- broad positives that are not explicit: `{broad_not_explicit}` ({pct(broad_not_explicit, broad_n)})",
        f"- broad positives that are spontaneous-reports-only: `{broad_sp_only}` ({pct(broad_sp_only, broad_n)})",
        f"- broad positives with hard issues: `{broad_hard_issue}` ({pct(broad_hard_issue, broad_n)})",
        "",
        "## Why the sensitivity endpoints matter",
        "",
        f"- excluding spontaneous-reports-only cases reduces the broad endpoint by `{broad_n - non_sp_n}` events",
        f"- excluding hard-issue rows reduces the broad endpoint by `{broad_n - qc_n}` events",
        f"- requiring explicit public RWE reduces the broad endpoint by `{broad_n - explicit_n}` events",
        "",
        "## Provenance among broad positives",
        "",
    ]
    for key, count in sorted(provenance_main.items()):
        lines.append(f"- `{key}`: `{count}` ({pct(count, broad_n)})")
    lines.extend(["", "## Annotation confidence among broad positives", ""])
    for key, count in sorted(confidence_main.items()):
        lines.append(f"- `{key}`: `{count}` ({pct(count, broad_n)})")
    lines.extend(["", "## Provenance among analytic positives", ""])
    for key, count in sorted(provenance_analytic.items()):
        lines.append(f"- `{key}`: `{count}` ({pct(count, analytic_n)})")
    lines.extend(["", "## Annotation confidence among analytic positives", ""])
    for key, count in sorted(confidence_analytic.items()):
        lines.append(f"- `{key}`: `{count}` ({pct(count, analytic_n)})")
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "This narrowed endpoint audit freezes a small paper-facing outcome family without changing the underlying annotation labels.",
            "The main endpoint remains the broad strict codebook label (`rwe_documented_publicly`).",
            "The analytic endpoint remains the key secondary endpoint.",
            "The remaining endpoints are explicitly sensitivity-only and are intended for robustness checks rather than co-equal headline claims.",
        ]
    )
    REPORT_MD.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
