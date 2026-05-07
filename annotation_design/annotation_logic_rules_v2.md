# SrLC Annotation Logic Rules v2

Frozen on `2026-03-24`.

This file contains the deterministic checks that must pass after model output and before any event is accepted into the final annotation table.

## 1. Core Logical Rules

1. `analytic_rwe_documented = yes` requires `rwe_documented_publicly = yes`.
2. `rwe_documented_publicly = yes` requires `rwe_relevance_to_change = direct`.
3. `negative_controls_documented = yes` requires `analytic_signal_present = yes`.
4. `confounding_control` may not be one of:
   - `stratification`
   - `matching_non_ps`
   - `multivariable_regression`
   - `propensity_score_matching`
   - `propensity_score_weighting`
   - `propensity_score_stratification`
   - `multiple_methods`
   unless `analytic_signal_present = yes`.
5. `annotation_evidence_strength = insufficient` requires:
   - `public_evidence_available = no`
   - `rwe_documented_publicly = no`
   - `analytic_rwe_documented = no`
6. `public_evidence_available = no` requires `rwe_relevance_to_change = not_apparent`.
7. `evidence_explicitness_tier = no_public_basis_found` requires `public_evidence_available = no`.
8. `rwe_source_type_primary = unknown` is allowed only when `rwe_source_type_all` is empty.
9. If `rwe_source_type_all` is non-empty, `rwe_source_type_primary` must appear in that set.

## 2. Transparency Rules

1. `transparency_score` is not model-supplied.
2. It is computed locally as:

   `design_stated`
   `+ population_stated`
   `+ comparator_stated`
   `+ effect_measure_stated`
   `+ confounding_strategy_stated`
   `+ missing_data_stated`
   `+ sensitivity_analysis_stated`
   `+ uncertainty_measure_stated`

3. Each component is converted from:
   - `yes` -> `1`
   - `no` -> `0`

## 3. Evidence Grounding Rules

1. Any event with one or more of the following must have at least one `supporting_evidence` item:
   - `rwe_documented_publicly = yes`
   - `analytic_rwe_documented = yes`
   - `missing_data_handling_documented = yes`
   - `sensitivity_analyses_documented = yes`
   - `negative_controls_documented = yes`
   - any transparency component = `yes`
2. Every `supporting_evidence.doc_id` must exist in `evidence_documents.csv`.
3. Every `supporting_evidence.doc_id` must be linked to the same `event_id` through `event_document_map.csv`.
4. If `public_evidence_available = no`, `supporting_evidence` must be empty.

## 4. Adjudication Triggers

Set `needs_adjudication = yes` if any of the following are true:

1. `rwe_documented_publicly = yes`
2. `annotation_confidence = low`
3. `annotation_evidence_strength = weak`
4. there is disagreement between rule-layer cues and model output
5. the event has multiple linked docs with inconsistent signals
6. transparency components imply a nonzero score but evidence support is thin

If none of the above are true, set:
- `needs_adjudication = no`
- `adjudication_reason = none`

## 5. Conservative Resolution Policy

If any required rule fails:

1. do not accept the row into the final annotation table
2. flag the row for rerun or adjudication
3. do not rerun the full corpus
4. rerun only the affected subset keyed by:
   - `event_id`
   - codebook version
   - prompt version
   - retrieval-packet hash

## 6. Versioning Rule

These checks apply only to codebook version `v2`.

Any later change to:
- label definitions
- allowed values
- logical rules
- evidence requirements

requires a new versioned rule file and a new prompt/schema version.
