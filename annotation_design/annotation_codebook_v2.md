# SrLC Event Annotation Codebook v2

Frozen on `2026-03-24` for the event-level RWE annotation pipeline built from:

- [<repository-root>/srlc_events_expanded.csv](<repository-root>/srlc_events_expanded.csv)
- [<repository-root>/event_document_map.csv](<repository-root>/event_document_map.csv)
- [<repository-root>/evidence_documents.csv](<repository-root>/evidence_documents.csv)

This freeze is intended to prevent label drift, prompt drift, and expensive API reruns.

## 1. Unit Of Annotation

- One row equals one `event_id`.
- An `event_id` is one FDA SrLC event, not one drug and not one document.
- Events remain separate even when two supplements have identical or near-identical text.

## 2. Inputs Allowed For Annotation

The annotation pipeline may use only the already collected package.

Primary inputs:
- `change_text`
- `label_section_changed`
- event metadata in `srlc_events_expanded.csv`

Evidence inputs:
- linked document metadata in `event_document_map.csv`
- extracted document text in files referenced by `evidence_documents.csv`
- raw PDF/HTML paths referenced by `evidence_documents.csv`

The production annotation run must not fetch new external sources or browse beyond the current package.

## 3. Evidence Hierarchy

Evidence should be interpreted in this order:

1. `change_text` defines what safety labeling event is being annotated.
2. Linked extracted document text is the main source for RWE-method labels.
3. Raw PDF/HTML is the fallback when extracted text is ambiguous or truncated.
4. Document metadata and URL/domain context are supporting context only.

## 4. Core Design Principles

- The primary endpoint stays strict.
- Auxiliary labels are added to preserve weaker but still useful public-evidence signal.
- Positive labels require explicit support from public materials relevant to the event.
- If public evidence is absent or inaccessible, the core label remains `no`, while auxiliary labels capture evidence limitations.
- Method-detail labels must not be inferred from general domain knowledge or drug familiarity.
- All positive or method-detail outputs must carry supporting document IDs and snippets.

## 5. Output Families

The annotation output contains four families of fields:

1. Core publishable labels
2. Auxiliary signal-preserving labels
3. Transparency subcomponents and score
4. Provenance and workflow fields

## 6. Core Publishable Labels

### 6.1 `rwe_documented_publicly`

Allowed values:
- `yes`
- `no`

Definition:
- `yes` only if the public event materials explicitly document real-world evidence or real-world data use relevant to the safety labeling change.
- `no` if the public materials do not explicitly document such use.

What counts:
- explicit use of RWE/RWD terminology
- explicit description of observational data analysis using claims, EHR, registry, Sentinel, PRISM, BEST, or equivalent real-world sources tied to the event

What does not count:
- label text alone with no evidence-basis discussion
- spontaneous reports alone unless the source is specifically part of a broader documented real-world analytic effort
- generic postmarketing wording without a documented evidence basis

### 6.2 `analytic_rwe_documented`

Allowed values:
- `yes`
- `no`

Definition:
- `yes` only if public materials explicitly document an analytic use of real-world data relevant to the safety event.
- `no` otherwise.

Rule:
- `analytic_rwe_documented = yes` requires `rwe_documented_publicly = yes`.

Exclusion:
- spontaneous-report-only evidence does not qualify as analytic RWE.

### 6.3 `rwe_source_type_primary`

Allowed values:
- `claims`
- `ehr`
- `registry`
- `active_surveillance_network`
- `spontaneous_reports`
- `other`
- `unknown`

Definition:
- The single best primary real-world data source explicitly documented as most central to the event evidence.

### 6.4 `rwe_source_type_all`

Allowed values:
- array of zero or more unique values from:
  - `claims`
  - `ehr`
  - `registry`
  - `active_surveillance_network`
  - `spontaneous_reports`
  - `other`

Definition:
- All distinct real-world source types explicitly documented in public materials.

### 6.5 `primary_design_category`

Allowed values:
- `active_comparator_cohort`
- `cohort_non_active_comparator`
- `case_control`
- `self_controlled_or_case_only`
- `registry_analysis`
- `active_surveillance_network_analysis`
- `descriptive_observational`
- `spontaneous_reporting_analysis`
- `other`
- `unknown`

Definition:
- The single best-fit primary analytic design explicitly documented in public materials.

Guidance:
- Use `active_comparator_cohort` only when both cohort structure and an active comparator are explicit.
- Use `cohort_non_active_comparator` for cohort-style analysis without clear active comparator evidence.
- Use `self_controlled_or_case_only` for SCCS, SCRI, case-crossover, or other self-controlled/case-only designs.
- Use `registry_analysis` when the document centers on a registry analysis but the exact analytic design is not clearer than the registry frame.
- Use `descriptive_observational` when observational evidence is clear but the design is not more specifically stated.
- Use `unknown` only when no design is ascertainable.

### 6.6 `confounding_control`

Allowed values:
- `none_documented`
- `stratification`
- `matching_non_ps`
- `multivariable_regression`
- `propensity_score_matching`
- `propensity_score_weighting`
- `propensity_score_stratification`
- `multiple_methods`
- `other`
- `unknown`

Definition:
- The best-supported primary confounding-control strategy explicitly described in public materials.

Guidance:
- `none_documented` means the materials do not document any confounding-control approach.
- `unknown` is reserved for cases where methods are clearly being described but the confounding approach cannot be classified from available text.

### 6.7 `missing_data_handling_documented`

Allowed values:
- `yes`
- `no`

Definition:
- `yes` only if the public materials explicitly describe missing-data handling, missing-data assumptions, or explicitly state how missingness was handled or judged not to require handling.

### 6.8 `sensitivity_analyses_documented`

Allowed values:
- `yes`
- `no`

Definition:
- `yes` only if sensitivity, secondary, robustness, or alternate-specification analyses are explicitly documented.

### 6.9 `negative_controls_documented`

Allowed values:
- `yes`
- `no`

Definition:
- `yes` only if negative controls, falsification outcomes, falsification exposures, or equivalent bias-detection procedures are explicitly documented.

## 7. Auxiliary Labels

These labels preserve signal without weakening the strict primary endpoint.

### 7.1 `public_evidence_available`

Allowed values:
- `yes`
- `no`

Definition:
- `yes` if the event has at least one usable public document with content relevant to the event evidence basis.
- `no` if there are no usable linked public materials or only inaccessible/empty/error materials.

### 7.2 `evidence_explicitness_tier`

Allowed values:
- `explicit_rwe`
- `explicit_observational_real_world`
- `spontaneous_reports_only`
- `unclear_public_basis`
- `no_public_basis_found`

Definition:
- Captures how explicit the public evidence basis is, even when the strict core RWE label is negative.

Interpretation:
- `explicit_rwe`: explicit RWE/RWD framing
- `explicit_observational_real_world`: observational real-world analysis clearly documented without the exact RWE wording
- `spontaneous_reports_only`: only spontaneous reporting or passive surveillance basis is documented
- `unclear_public_basis`: some public material exists, but the evidence basis remains unclear
- `no_public_basis_found`: no usable public basis was found

Constraint:
- `evidence_explicitness_tier = no_public_basis_found` should coincide with `public_evidence_available = no`.

### 7.3 `analytic_signal_present`

Allowed values:
- `yes`
- `no`

Definition:
- `yes` if public materials indicate any analytic epidemiologic or observational assessment, even if the strict `analytic_rwe_documented` label remains `no`.

### 7.4 `annotation_evidence_strength`

Allowed values:
- `strong`
- `moderate`
- `weak`
- `insufficient`

Definition:
- Overall strength of event-level public evidence supporting the annotation.

Guidance:
- `strong`: clear event-relevant materials with explicit methods or evidence basis
- `moderate`: relevant materials exist with partial but usable evidence details
- `weak`: minimal event-relevant detail, mostly indirect
- `insufficient`: no usable public material for substantive annotation

### 7.5 `rwe_relevance_to_change`

Allowed values:
- `direct`
- `possible_but_not_explicit`
- `unclear`
- `not_apparent`

Definition:
- Captures whether the public evidence appears to bear directly on the specific safety labeling change in the event, rather than merely providing background real-world context.

Interpretation:
- `direct`: the public materials explicitly tie the evidence basis to the safety issue or labeling change addressed by the event
- `possible_but_not_explicit`: the public materials contain potentially relevant real-world evidence, but the connection to the specific safety change is only implied
- `unclear`: public materials are partly relevant, but the relationship to the specific safety change cannot be judged confidently
- `not_apparent`: no usable public evidence appears relevant to the specific safety change

Guidance:
- Use this field to prevent overcalling `rwe_documented_publicly = yes` when snippets mention generic pregnancy registries, postmarketing surveillance, or other background evidence not clearly connected to the event's safety change.
- A strict positive primary label should usually coincide with `rwe_relevance_to_change = direct`.

## 8. Transparency Components

Each component is coded separately. The total `transparency_score` is the sum of these eight yes/no items.

### 8.1 `design_stated`
- `yes` if the study design or analysis frame is explicitly stated.

### 8.2 `population_stated`
- `yes` if the analyzed population, cohort, or patient group is explicitly stated.

### 8.3 `comparator_stated`
- `yes` if a comparator is explicitly stated, or if the materials explicitly state that there was no comparator because the analysis was descriptive or non-comparative.

### 8.4 `effect_measure_stated`
- `yes` if a quantitative effect measure or signal metric is explicitly stated.

### 8.5 `confounding_strategy_stated`
- `yes` if any confounding-control strategy is explicitly stated.

### 8.6 `missing_data_stated`
- `yes` if missing-data handling or missing-data considerations are explicitly addressed.

### 8.7 `sensitivity_analysis_stated`
- `yes` if sensitivity or robustness analyses are explicitly addressed.

### 8.8 `uncertainty_measure_stated`
- `yes` if a confidence interval, credible interval, p-value, standard error, or similar uncertainty measure is explicitly stated.

### 8.9 `transparency_score`

Allowed values:
- integer `0` to `8`

Definition:
- Sum of the eight transparency components above.

Rule:
- The score is derived locally from the eight component fields and must never be directly guessed by the model.

## 9. Provenance And Workflow Fields

### 9.1 `supporting_evidence`

Definition:
- Up to three evidence items that justify the assigned labels.

Each item contains:
- `doc_id`
- `snippet`
- `supports_labels` (array of label names supported by the snippet)

### 9.2 `supporting_doc_ids`

Definition:
- Unique set of document IDs cited by the annotation output.

### 9.3 `annotation_confidence`

Allowed values:
- `high`
- `medium`
- `low`

Definition:
- Model-estimated confidence in the event annotation after considering evidence quality and label certainty.

### 9.4 `needs_adjudication`

Allowed values:
- `yes`
- `no`

Definition:
- `yes` when the event should be sent to a stronger model pass because of weak evidence, internal inconsistency, or ambiguous signal.

### 9.5 `adjudication_reason`

Allowed values:
- `positive_core_label`
- `rule_model_disagreement`
- `low_confidence`
- `multiple_doc_conflict`
- `transparency_inconsistency`
- `insufficient_evidence`
- `none`

## 10. Logical Constraints

The following rules are mandatory:

- `analytic_rwe_documented = yes` requires `rwe_documented_publicly = yes`
- `rwe_documented_publicly = yes` requires `rwe_relevance_to_change = direct`
- `rwe_source_type_primary` must be a member of `rwe_source_type_all` unless `rwe_source_type_all` is empty and primary is `unknown`
- `negative_controls_documented = yes` implies `analytic_signal_present = yes`
- `confounding_control != none_documented` implies `analytic_signal_present = yes`
- `annotation_evidence_strength = insufficient` implies:
  - `public_evidence_available = no`
  - `rwe_documented_publicly = no`
  - `analytic_rwe_documented = no`
- `public_evidence_available = no` implies `rwe_relevance_to_change = not_apparent`
- `transparency_score` must equal the sum of the eight transparency components

## 11. Default Handling Rules

- Do not infer a positive RWE label from drug area, common practice, or outside knowledge.
- Do not infer detailed methods from vague statements like "postmarketing data showed".
- If a document is inaccessible, empty, or irrelevant, do not treat it as supporting evidence.
- If an event has no usable public documents, core labels remain strict and auxiliary labels carry the evidence limitation.

## 12. Freeze Policy

This codebook is the frozen contract for the first production annotation version.

Preventive refinement decisions made before the production run:
- Added `rwe_relevance_to_change` because the calibration surfaced repeated ambiguity between background public evidence and evidence clearly relevant to the event-specific safety change.
- Rejected `public_evidence_basis_type` because it is redundant with `public_evidence_available`, `evidence_explicitness_tier`, and `rwe_source_type_*`.
- Rejected `usable_for_method_extraction` as a model field because it can be derived later from evidence coverage and method-detail outputs.
- Kept `evidence_document_type_primary` out of the paid schema because it can be derived locally from document metadata without another model call.

Permitted before any full API run:
- one final wording cleanup if it does not change field meanings

Not permitted after the first production shard starts:
- changing label definitions
- changing allowed values
- changing logical constraints
- changing the evidence standard for positive labels

Any substantive change after production starts requires a new versioned codebook.
