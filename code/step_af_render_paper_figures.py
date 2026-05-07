#!/usr/bin/env python3
"""Render publication-ready figures for the SrLC RWE analysis."""

from __future__ import annotations

from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_DIR = REPO_ROOT
ANALYSIS_DIR = BASE_DIR / "analysis_outputs"
FIG_DIR = ANALYSIS_DIR / "figures"
MAIN_DIR = FIG_DIR / "main"
SUPP_DIR = FIG_DIR / "supplement"

FIGURE_SPEC_MD = FIG_DIR / "figure_specifications.md"
FIGURE_REPORT_MD = FIG_DIR / "figure_rendering_report.md"
FIGURE_MANIFEST_CSV = FIG_DIR / "figure_manifest.csv"


COLOR_MAIN = "#184E77"
COLOR_ANALYTIC = "#C65F2C"
COLOR_PUBLIC = "#6C757D"
COLOR_METHOD = "#7A9E2F"
COLOR_LIGHT = "#E9EEF3"
COLOR_GRID = "#D5DCE3"
COLOR_TEXT = "#1F2933"
COLOR_ACCENT = "#3C8DAD"

EXPLICITNESS_COLORS = {
    "no_public_basis_found": "#D9DDE3",
    "unclear_public_basis": "#A9B8C7",
    "spontaneous_reports_only": "#E89B5B",
    "explicit_observational_real_world": "#4F8FB8",
    "explicit_rwe": "#1F4E79",
}

SCORE_COLORS = {
    0: "#DCE1E8",
    1: "#BFD0E0",
    2: "#96B9D5",
    3: "#6B9EC7",
    4: "#4A85B4",
    5: "#336B99",
    6: "#24557C",
    7: "#173D59",
    8: "#0F2740",
}


def set_style() -> None:
    mpl.rcParams.update(
        {
            "font.family": "Arial",
            "font.size": 9,
            "axes.titlesize": 11,
            "axes.labelsize": 9,
            "axes.edgecolor": COLOR_TEXT,
            "axes.linewidth": 0.8,
            "axes.titleweight": "bold",
            "axes.labelcolor": COLOR_TEXT,
            "xtick.color": COLOR_TEXT,
            "ytick.color": COLOR_TEXT,
            "text.color": COLOR_TEXT,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "savefig.facecolor": "white",
            "savefig.bbox": "tight",
            "savefig.pad_inches": 0.05,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )


def ensure_dirs() -> None:
    MAIN_DIR.mkdir(parents=True, exist_ok=True)
    SUPP_DIR.mkdir(parents=True, exist_ok=True)


def panel_label(ax: plt.Axes, label: str) -> None:
    ax.text(
        -0.12,
        1.06,
        label,
        transform=ax.transAxes,
        fontsize=12,
        fontweight="bold",
        va="top",
        ha="left",
    )


def save_figure(fig: plt.Figure, basename: str, panel_set: str, title: str, source_files: list[str]) -> list[dict]:
    out_dir = MAIN_DIR if panel_set == "main" else SUPP_DIR
    png_path = out_dir / f"{basename}.png"
    pdf_path = out_dir / f"{basename}.pdf"
    fig.savefig(png_path, dpi=600)
    fig.savefig(pdf_path)
    plt.close(fig)
    return [
        {
            "figure_set": panel_set,
            "basename": basename,
            "title": title,
            "format": "png",
            "path": str(png_path),
            "source_files": " | ".join(source_files),
        },
        {
            "figure_set": panel_set,
            "basename": basename,
            "title": title,
            "format": "pdf",
            "path": str(pdf_path),
            "source_files": " | ".join(source_files),
        },
    ]


def render_funnel() -> list[dict]:
    df = pd.read_csv(ANALYSIS_DIR / "figure1_funnel.csv").sort_values("stage_order")
    label_map = {
        "all_events": "All safety-labeling events",
        "public_evidence_available": "Public evidence available",
        "main_public_rwe": "Broad public RWE",
        "analytic_public_rwe": "Analytic public RWE",
        "analytic_public_rwe_with_method_detail": "Analytic public RWE\nwith method detail",
    }
    df["stage_label"] = df["stage"].map(label_map)

    fig, ax = plt.subplots(figsize=(7.2, 4.2), constrained_layout=True)
    y = np.arange(len(df))
    colors = [COLOR_PUBLIC, "#587B98", COLOR_MAIN, COLOR_ANALYTIC, COLOR_METHOD]
    ax.barh(y, df["pct_of_total"], color=colors, edgecolor="none", height=0.64)
    ax.set_xlim(0, 100)
    ax.set_yticks(y)
    ax.set_yticklabels(df["stage_label"])
    ax.invert_yaxis()
    ax.set_xlabel("Percent of all events")
    ax.grid(axis="x", color=COLOR_GRID, linewidth=0.7)
    ax.set_axisbelow(True)

    for i, row in df.iterrows():
        yloc = y[list(df.index).index(i)]
        label = f"{int(row['count']):,} ({row['pct_of_total']:.1f}%)"
        if row["pct_of_total"] >= 45:
            ax.text(
                row["pct_of_total"] - 1.2,
                yloc,
                label,
                va="center",
                ha="right",
                fontsize=8.5,
                color="white",
                fontweight="bold",
            )
        else:
            ax.text(min(row["pct_of_total"] + 1.2, 97), yloc, label, va="center", ha="left", fontsize=8.5)
        if row["stage_order"] > 1:
            retain = row["pct_of_previous_stage"]
            ax.text(99.2, yloc, f"{retain:.1f}% of prior", va="center", ha="right", fontsize=8, color=COLOR_TEXT)

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    panel_label(ax, "A")
    return save_figure(
        fig,
        basename="figure_1_documentation_funnel",
        panel_set="main",
        title="Documentation funnel",
        source_files=[str(ANALYSIS_DIR / "figure1_funnel.csv")],
    )


def render_section_severity() -> list[dict]:
    df = pd.read_csv(ANALYSIS_DIR / "figure3_section_severity_counts.csv")
    sec = df[df["dimension"] == "section"].copy()
    sev = df[df["dimension"] == "severity"].copy()

    sec_order = (
        sec[sec["endpoint"] == "endpoint_main_public_rwe"]
        .sort_values("pct_yes", ascending=True)["group"]
        .tolist()
    )
    sev_order = ["tier_1_other_safety_only", "tier_2_contra_or_warnings", "tier_3_boxed_warning"]
    sev_label_map = {
        "tier_1_other_safety_only": "Tier 1: other safety",
        "tier_2_contra_or_warnings": "Tier 2: contraindications/warnings",
        "tier_3_boxed_warning": "Tier 3: boxed warning",
    }

    fig, axes = plt.subplots(1, 2, figsize=(9.0, 4.8), gridspec_kw={"width_ratios": [2.2, 1.2]}, constrained_layout=True)

    for ax, subset, order, title in [
        (axes[0], sec, sec_order, "By label section"),
        (axes[1], sev, sev_order, "By severity tier"),
    ]:
        positions = np.arange(len(order))
        width = 0.34
        main_vals = []
        analytic_vals = []
        labels = []
        for grp in order:
            sub = subset[subset["group"] == grp]
            row_main = sub[sub["endpoint"] == "endpoint_main_public_rwe"].iloc[0]
            row_analytic = sub[sub["endpoint"] == "endpoint_secondary_analytic_public_rwe"].iloc[0]
            main_vals.append(float(row_main["pct_yes"]))
            analytic_vals.append(float(row_analytic["pct_yes"]))
            if subset is sec:
                labels.append(f"{grp}\n(n={int(row_main['denominator']):,})")
            else:
                labels.append(f"{sev_label_map[grp]}\n(n={int(row_main['denominator']):,})")

        ax.barh(positions + width / 2, main_vals, height=width, color=COLOR_MAIN, label="Broad public RWE")
        ax.barh(positions - width / 2, analytic_vals, height=width, color=COLOR_ANALYTIC, label="Analytic public RWE")
        ax.set_yticks(positions)
        ax.set_yticklabels(labels)
        ax.set_xlabel("Prevalence (%)")
        ax.set_title(title)
        ax.grid(axis="x", color=COLOR_GRID, linewidth=0.7)
        ax.set_axisbelow(True)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.set_xlim(0, max(main_vals + analytic_vals) * 1.22)

    axes[0].set_title("By label section")
    axes[1].set_title("By severity tier")
    axes[0].legend(frameon=False, loc="lower right")
    panel_label(axes[0], "A")
    panel_label(axes[1], "B")

    return save_figure(
        fig,
        basename="figure_2_section_severity_prevalence",
        panel_set="main",
        title="Section and severity prevalence",
        source_files=[str(ANALYSIS_DIR / "figure3_section_severity_counts.csv")],
    )


def render_forest() -> list[dict]:
    main_df = pd.read_csv(ANALYSIS_DIR / "model_main_public_rwe.csv")
    analytic_df = pd.read_csv(ANALYSIS_DIR / "model_analytic_public_rwe.csv")

    order = [
        "NDA vs BLA",
        "Boxed Warning present",
        "Contraindications present",
        "Warnings and Precautions present",
        "Adverse Reactions present",
        "Drug Interactions present",
        "Use in Specific Populations present",
        "Calendar year (per 1 year)",
    ]

    def subset(df: pd.DataFrame) -> pd.DataFrame:
        out = df[df["term_label"].isin(order)].copy()
        out["term_label"] = pd.Categorical(out["term_label"], categories=order, ordered=True)
        out = out.sort_values("term_label", ascending=False)
        return out

    main_sub = subset(main_df)
    analytic_sub = subset(analytic_df)

    fig, axes = plt.subplots(1, 2, figsize=(9.2, 5.2), sharex=True, sharey=True, constrained_layout=True)

    for ax, subset_df, color, title in [
        (axes[0], main_sub, COLOR_MAIN, "Broad public RWE"),
        (axes[1], analytic_sub, COLOR_ANALYTIC, "Analytic public RWE"),
    ]:
        y = np.arange(len(subset_df))
        pr = subset_df["prevalence_ratio"].to_numpy()
        low = subset_df["pr_ci_lower"].to_numpy()
        high = subset_df["pr_ci_upper"].to_numpy()
        ax.hlines(y, low, high, color=color, linewidth=2.0)
        ax.scatter(pr, y, color=color, s=34, zorder=3)
        ax.axvline(1.0, color=COLOR_TEXT, linestyle="--", linewidth=1.0)
        ax.set_xscale("log")
        ax.set_xlim(0.45, 4.6)
        ax.set_xticks([0.5, 1.0, 2.0, 4.0])
        ax.get_xaxis().set_major_formatter(mpl.ticker.FormatStrFormatter("%.1f"))
        ax.set_title(title)
        ax.grid(axis="x", color=COLOR_GRID, linewidth=0.7)
        ax.set_axisbelow(True)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.set_xlabel("Prevalence ratio (log scale)")

    axes[0].set_yticks(np.arange(len(main_sub)))
    axes[0].set_yticklabels(main_sub["term_label"].tolist())
    panel_label(axes[0], "A")
    panel_label(axes[1], "B")

    return save_figure(
        fig,
        basename="figure_3_adjusted_forest",
        panel_set="main",
        title="Adjusted model forest plots",
        source_files=[
            str(ANALYSIS_DIR / "model_main_public_rwe.csv"),
            str(ANALYSIS_DIR / "model_analytic_public_rwe.csv"),
        ],
    )


def render_transparency_distribution() -> list[dict]:
    df = pd.read_csv(ANALYSIS_DIR / "figure5_transparency_distribution.csv")
    subset_order = [
        ("all_events", "All events"),
        ("main_public_rwe_positive", "Broad public RWE positive"),
        ("analytic_public_rwe_positive", "Analytic public RWE positive"),
    ]

    fig, axes = plt.subplots(3, 1, figsize=(7.2, 6.8), sharex=True, constrained_layout=True)

    for ax, (subset_key, subset_label) in zip(axes, subset_order):
        sub = df[df["subset"] == subset_key].copy()
        sub["score"] = sub["score"].astype(int)
        sub = sub.sort_values("score")
        colors = [SCORE_COLORS[int(s)] for s in sub["score"]]
        ax.bar(sub["score"], sub["pct"], color=colors, width=0.8, edgecolor="none")
        ax.set_ylabel("Percent")
        ax.set_title(f"{subset_label} (n={int(sub['denominator'].iloc[0]):,})", loc="left")
        ax.grid(axis="y", color=COLOR_GRID, linewidth=0.7)
        ax.set_axisbelow(True)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ge3 = sub.loc[sub["score"] >= 3, "pct"].sum()
        ax.text(0.98, 0.9, f"Score ≥3: {ge3:.1f}%", transform=ax.transAxes, ha="right", va="top", fontsize=8.5)

    axes[-1].set_xlabel("Transparency score")
    axes[-1].set_xticks(range(0, 9))
    panel_label(axes[0], "A")
    panel_label(axes[1], "B")
    panel_label(axes[2], "C")

    return save_figure(
        fig,
        basename="figure_4_transparency_distribution",
        panel_set="main",
        title="Transparency score distributions",
        source_files=[str(ANALYSIS_DIR / "figure5_transparency_distribution.csv")],
    )


def render_annual_trends() -> list[dict]:
    df = pd.read_csv(ANALYSIS_DIR / "figure2_annual_trends.csv")
    top = df[df["series"].isin(["public_evidence_available", "endpoint_main_public_rwe", "endpoint_secondary_analytic_public_rwe"])].copy()
    bottom = df[df["series"].isin(["transparency_score_ge_3", "mean_transparency_score"])].copy()

    label_map = {r["series"]: r["series_label"] for _, r in df[["series", "series_label"]].drop_duplicates().iterrows()}
    label_map.update(
        {
            "endpoint_main_public_rwe": "Broad public RWE",
            "endpoint_secondary_analytic_public_rwe": "Analytic public RWE",
            "endpoint_sens_explicit_public_rwe": "Explicit public RWE",
        }
    )
    color_map = {
        "public_evidence_available": COLOR_PUBLIC,
        "endpoint_main_public_rwe": COLOR_MAIN,
        "endpoint_secondary_analytic_public_rwe": COLOR_ANALYTIC,
        "transparency_score_ge_3": COLOR_ACCENT,
        "mean_transparency_score": COLOR_METHOD,
    }

    fig, axes = plt.subplots(2, 1, figsize=(7.6, 6.6), sharex=True, constrained_layout=False)

    for series in ["public_evidence_available", "endpoint_main_public_rwe", "endpoint_secondary_analytic_public_rwe"]:
        sub = top[top["series"] == series].sort_values("event_year")
        axes[0].plot(sub["event_year"], sub["pct_yes"], marker="o", linewidth=2.0, color=color_map[series], label=label_map[series])
    axes[0].set_ylabel("Percent")
    axes[0].set_title("Documentation prevalence over calendar time")
    axes[0].grid(axis="y", color=COLOR_GRID, linewidth=0.7)
    axes[0].spines["top"].set_visible(False)
    axes[0].spines["right"].set_visible(False)

    trans_ge3 = bottom[bottom["series"] == "transparency_score_ge_3"].sort_values("event_year")
    mean_trans = bottom[bottom["series"] == "mean_transparency_score"].sort_values("event_year")
    axes[1].plot(trans_ge3["event_year"], trans_ge3["pct_yes"], marker="o", linewidth=2.0, color=color_map["transparency_score_ge_3"], label=label_map["transparency_score_ge_3"])
    ax2 = axes[1].twinx()
    ax2.plot(mean_trans["event_year"], mean_trans["pct_yes"], marker="s", linewidth=1.8, linestyle="--", color=color_map["mean_transparency_score"], label=label_map["mean_transparency_score"])
    axes[1].set_ylabel("Percent with score ≥3")
    ax2.set_ylabel("Mean transparency score")
    axes[1].set_title("Transparency over calendar time")
    axes[1].grid(axis="y", color=COLOR_GRID, linewidth=0.7)
    axes[1].spines["top"].set_visible(False)
    axes[1].spines["right"].set_visible(False)
    ax2.spines["top"].set_visible(False)

    handles0, labels0 = axes[0].get_legend_handles_labels()
    handles1, labels1 = axes[1].get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    fig.legend(
        handles0 + handles1 + handles2,
        labels0 + labels1 + labels2,
        frameon=False,
        ncol=3,
        loc="lower center",
        bbox_to_anchor=(0.5, 0.015),
        fontsize=8,
    )

    axes[1].set_xlabel("Calendar year")
    axes[1].set_xticks(sorted(df["event_year"].unique()))
    fig.subplots_adjust(top=0.96, bottom=0.16, hspace=0.34, right=0.90)
    panel_label(axes[0], "A")
    panel_label(axes[1], "B")

    return save_figure(
        fig,
        basename="figure_s1_annual_trends",
        panel_set="supplement",
        title="Annual trends",
        source_files=[str(ANALYSIS_DIR / "figure2_annual_trends.csv")],
    )


def render_explicitness() -> list[dict]:
    df = pd.read_csv(ANALYSIS_DIR / "figure4_explicitness_counts.csv")
    order = [
        "no_public_basis_found",
        "unclear_public_basis",
        "spontaneous_reports_only",
        "explicit_observational_real_world",
        "explicit_rwe",
    ]
    label_map = {
        "no_public_basis_found": "No public basis found",
        "unclear_public_basis": "Unclear public basis",
        "spontaneous_reports_only": "Spontaneous reports only",
        "explicit_observational_real_world": "Explicit observational real-world evidence",
        "explicit_rwe": "Explicit public RWE",
    }
    panel_order = [("overall", "All events"), ("application_type", "Application type")]

    fig, axes = plt.subplots(1, 2, figsize=(9.8, 4.4), constrained_layout=False)

    overall = df[df["panel"] == "overall"].copy()
    overall["evidence_explicitness_tier"] = pd.Categorical(overall["evidence_explicitness_tier"], categories=order, ordered=True)
    overall = overall.sort_values("evidence_explicitness_tier")
    axes[0].barh(
        overall["evidence_explicitness_tier"].map(label_map),
        overall["pct"],
        color=[EXPLICITNESS_COLORS[x] for x in overall["evidence_explicitness_tier"]],
        edgecolor="none",
    )
    axes[0].set_xlabel("Percent")
    axes[0].set_title("All events")
    axes[0].grid(axis="x", color=COLOR_GRID, linewidth=0.7)
    axes[0].set_axisbelow(True)
    axes[0].spines["top"].set_visible(False)
    axes[0].spines["right"].set_visible(False)

    app = df[df["panel"] == "application_type"].copy()
    groups = ["BLA", "NDA"]
    y = np.arange(len(groups))
    left = np.zeros(len(groups))
    for tier in order:
        vals = []
        for grp in groups:
            vals.append(float(app[(app["group"] == grp) & (app["evidence_explicitness_tier"] == tier)]["pct"].iloc[0]))
        axes[1].barh(y, vals, left=left, color=EXPLICITNESS_COLORS[tier], edgecolor="white", linewidth=0.5, label=label_map[tier])
        left += np.array(vals)
    axes[1].set_yticks(y)
    axes[1].set_yticklabels(groups)
    axes[1].set_xlabel("Percent")
    axes[1].set_xlim(0, 100)
    axes[1].set_title("By application type")
    axes[1].grid(axis="x", color=COLOR_GRID, linewidth=0.7)
    axes[1].set_axisbelow(True)
    axes[1].spines["top"].set_visible(False)
    axes[1].spines["right"].set_visible(False)
    axes[1].legend(
        frameon=False,
        fontsize=7.5,
        loc="center left",
        bbox_to_anchor=(1.02, 0.5),
        borderaxespad=0.0,
    )
    fig.subplots_adjust(left=0.12, right=0.80, top=0.92, bottom=0.14, wspace=0.42)
    panel_label(axes[0], "A")
    panel_label(axes[1], "B")

    return save_figure(
        fig,
        basename="figure_s2_explicitness_distribution",
        panel_set="supplement",
        title="Evidence explicitness distribution",
        source_files=[str(ANALYSIS_DIR / "figure4_explicitness_counts.csv")],
    )


def write_spec_and_report(manifest_rows: list[dict]) -> None:
    manifest_df = pd.DataFrame(manifest_rows)
    manifest_df.to_csv(FIGURE_MANIFEST_CSV, index=False)

    spec_lines = [
        "# Figure Specifications",
        "",
        "## Main text figures",
        "",
        "1. `figure_1_documentation_funnel`",
        "   - purpose: show the staged attrition from all events to analytic public RWE with method detail",
        "   - source: `analysis_outputs/figure1_funnel.csv`",
        "",
        "2. `figure_2_section_severity_prevalence`",
        "   - purpose: compare broad public RWE and analytic public RWE prevalence across sections and severity tiers",
        "   - source: `analysis_outputs/figure3_section_severity_counts.csv`",
        "",
        "3. `figure_3_adjusted_forest`",
        "   - purpose: show adjusted prevalence ratios for the broad public RWE and analytic public RWE measures",
        "   - sources: `analysis_outputs/model_main_public_rwe.csv`, `analysis_outputs/model_analytic_public_rwe.csv`",
        "",
        "4. `figure_4_transparency_distribution`",
        "   - purpose: show how transparency scores are distributed overall and among positive-event subsets",
        "   - source: `analysis_outputs/figure5_transparency_distribution.csv`",
        "",
        "## Supplementary figures",
        "",
        "S1. `figure_s1_annual_trends`",
        "   - purpose: annual trends in documentation prevalence and transparency",
        "   - source: `analysis_outputs/figure2_annual_trends.csv`",
        "",
        "S2. `figure_s2_explicitness_distribution`",
        "   - purpose: evidence explicitness overall and by application type",
        "   - source: `analysis_outputs/figure4_explicitness_counts.csv`",
        "",
    ]
    FIGURE_SPEC_MD.write_text("\n".join(spec_lines) + "\n")

    report_lines = [
        "# Figure Rendering Report",
        "",
        f"- output manifest: `{FIGURE_MANIFEST_CSV}`",
        f"- figure spec: `{FIGURE_SPEC_MD}`",
        "",
        "## Rendering notes",
        "",
        "- all figures were rendered from frozen analysis outputs",
        "- both `PNG` and `PDF` versions were saved for each figure",
        "- typography uses a vector-safe publication style with embedded TrueType fonts",
        "- colors were chosen to keep the broad public RWE measure, analytic public RWE measure, public evidence, and documented method detail visually distinct",
        "",
        "## Figure sets",
        "",
        f"- main figures: `{sum(1 for r in manifest_rows if r['figure_set']=='main' and r['format']=='pdf')}`",
        f"- supplementary figures: `{sum(1 for r in manifest_rows if r['figure_set']=='supplement' and r['format']=='pdf')}`",
        "",
    ]
    FIGURE_REPORT_MD.write_text("\n".join(report_lines) + "\n")


def main() -> None:
    set_style()
    ensure_dirs()
    manifest_rows: list[dict] = []
    manifest_rows.extend(render_funnel())
    manifest_rows.extend(render_section_severity())
    manifest_rows.extend(render_forest())
    manifest_rows.extend(render_transparency_distribution())
    manifest_rows.extend(render_annual_trends())
    manifest_rows.extend(render_explicitness())
    write_spec_and_report(manifest_rows)


if __name__ == "__main__":
    main()
