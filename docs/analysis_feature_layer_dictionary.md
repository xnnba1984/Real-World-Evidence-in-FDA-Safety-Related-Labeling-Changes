# Analysis Feature Layer Dictionary

This table extends the base analysis-ready table:
- [<repository-root>/analysis_ready/srlc_annotation_analysis_ready.csv](<repository-root>/analysis_ready/srlc_annotation_analysis_ready.csv)

It preserves all original columns and adds derived fields for downstream descriptive analyses, sensitivity analyses, and modeling.

## Time variables

- `event_year`: calendar year from `event_date_iso`
- `event_month`: calendar month number from `event_date_iso`
- `event_quarter`: quarter label `Q1`-`Q4`
- `year_trend_window_flag`: `yes` for `2016-2025`, `no` otherwise. This is for trend-specific analyses only and is not the default cohort restriction.

## Section normalization

Derived from `label_section_changed`:

- `section_boxed_warning`
- `section_contraindications`
- `section_warnings_precautions`
- `section_adverse_reactions`
- `section_drug_interactions`
- `section_use_in_specific_populations`
- `section_patient_labeling`
- `section_other_safety`

Additional helpers:

- `normalized_section_signature`: pipe-delimited ordered section signature
- `section_count`: number of changed normalized section groups, including patient labeling and `Other`
- `safety_section_count`: number of changed safety sections excluding patient labeling
- `primary_section_group`: highest-priority normalized section group present in the event

## Severity variables

- `severity_tier`: integer severity proxy
  - `3` if boxed warning
  - `2` if contraindications or warnings/precautions without boxed warning
  - `1` otherwise
- `severity_tier_label`: descriptive label for the severity tier

## Funnel / method variables

- `method_detail_score`: count of documented method-detail components:
  - confounding control documented
  - missing-data handling documented
  - sensitivity analyses documented
  - negative controls documented
- `any_method_detail_flag`: `yes` if `method_detail_score > 0`
- `public_documentation_funnel_stage`:
  - `no_public_evidence`
  - `public_evidence_no_rwe`
  - `documented_rwe_nonanalytic`
  - `documented_analytic_rwe`
  - `documented_analytic_rwe_with_method_detail`

## Document coverage variables

- `doc_coverage_band`:
  - `no_linked_docs`
  - `linked_no_download`
  - `downloaded_no_extracted`
  - `extracted_1`
  - `extracted_2_plus`

## QC / issue burden variables

- `issue_burden_score`: simple sum of remaining logic violations, logic warnings, and grounding issues
- `issue_burden_band`: `0`, `1`, `2_3`, `4_plus`

## Duplicate-cluster sensitivity variables

- `change_text_signature`: 16-character SHA1 prefix of normalized `change_text`
- `event_cluster_id_sensitivity`: cluster key based on application number, date, supplement number, normalized section signature, and `change_text` signature
- `event_cluster_size_sensitivity`: number of events sharing the sensitivity cluster key
