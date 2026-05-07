# Analysis-Ready Table Dictionary

Core source columns come from the event master `srlc_events_expanded.csv` and preserve event identity, drug metadata, label section, and `change_text`.

## Recommended analysis columns

- `strict_primary_cohort`: `yes` when `rwe_documented_publicly = yes`.
- `analytic_cohort`: `yes` when `analytic_rwe_documented = yes`.
- `direct_relevance_flag`: `yes` when `rwe_relevance_to_change = direct`.
- `explicit_public_rwe_any_flag`: `yes` when `evidence_explicitness_tier` is `explicit_rwe` or `explicit_observational_real_world`.
- `spontaneous_reports_only_flag`: `yes` when the public basis is spontaneous reports only.
- `method_detail_any_documented_flag`: `yes` if any confounding, missing-data, sensitivity, or negative-control method detail is documented.
- `source_group_collapsed`: analysis-friendly collapse of the primary source label.
- `design_group_collapsed`: analysis-friendly collapse of the design label.
- `transparency_score_band`: `0`, `1_2`, `3_4`, or `5_plus`.
- `has_downloaded_doc` / `has_extracted_doc`: event-level evidence availability flags from the downloaded evidence package.
- `hard_issue_flag`: `yes` when a residual hard logic violation or grounding issue remains after adjudication.
- `remaining_logic_violation_types`, `remaining_logic_warning_types`, `remaining_grounding_issue_types`: pipe-delimited QC issue categories for sensitivity analyses.
- `final_label_source`: where the current final labels came from: `first_pass`, `repair`, or `adjudication`.
- `adjudication_applied`: `yes` if the event was reviewed in the third-run adjudication pass.

## Recommended sensitivity exclusions

- Exclude `hard_issue_flag = yes` for a strict sensitivity analysis.
- Stratify by `final_label_source` to show how much the repair/adjudication stages changed results.
- Restrict to `has_extracted_doc = yes` if you want an evidence-availability sensitivity cohort.
