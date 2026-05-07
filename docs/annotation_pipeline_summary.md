# Annotation Pipeline Summary

This document summarizes the complete event-level annotation workflow used to classify FDA SrLC events for public real-world-evidence documentation.

## Objective

The goal was to annotate each event-level FDA Safety-related Labeling Change (SrLC) event for:

- whether public materials explicitly document real-world evidence relevant to the safety label change
- whether analytic real-world evidence is documented
- source type, broad design category, confounding-control documentation, missing-data documentation, sensitivity-analysis documentation, negative-control documentation
- transparency subcomponents and transparency score

The workflow was fully automated. No human gold-standard annotation set or manual event review was performed.

## Unit of Annotation

- One row = one event-level SrLC labeling change
- Event master input: [srlc_events_expanded.csv](<repository-root>/srlc_events_expanded.csv)
- Total events: `10,616`

## Upstream Inputs

### 1. Event registry

The event registry preserved:

- original event metadata from the SrLC export
- one row per event (`event_id`)
- `change_text`
- event header/date/supplement fields
- event-level linked document URLs

Primary file:
- [srlc_events_expanded.csv](<repository-root>/srlc_events_expanded.csv)

### 2. Evidence package

Public linked documents were downloaded and normalized into a many-to-many event-document structure.

Key files:
- [event_document_map.csv](<repository-root>/event_document_map.csv)
- [evidence_documents.csv](<repository-root>/evidence_documents.csv)
- raw/text files under [event_evidence](<repository-root>/event_evidence)

Coverage after cleanup:

- events with at least one downloaded document: `10,448 / 10,616`
- events with no linked docs in source data: `106`

## Annotation Design Freeze

The schema and codebook were frozen before production runs.

Final design files:
- [annotation_codebook_v2.md](<repository-root>/annotation_design/annotation_codebook_v2.md)
- [annotation_output_schema_v2.json](<repository-root>/annotation_design/annotation_output_schema_v2.json)
- [annotation_logic_rules_v2.md](<repository-root>/annotation_design/annotation_logic_rules_v2.md)
- [annotation_design_freeze_v2.json](<repository-root>/annotation_design/annotation_design_freeze_v2.json)

Core labels:

- `rwe_documented_publicly`
- `analytic_rwe_documented`
- `rwe_source_type_primary`
- `rwe_source_type_all`
- `primary_design_category`
- `confounding_control`
- `missing_data_handling_documented`
- `sensitivity_analyses_documented`
- `negative_controls_documented`
- 8 transparency subcomponents and derived `transparency_score`

Auxiliary labels:

- `public_evidence_available`
- `evidence_explicitness_tier`
- `analytic_signal_present`
- `annotation_evidence_strength`
- `rwe_relevance_to_change`

## Packetization and Local Rule Layer

The annotation prompt did not send full evidence documents directly to the model. Instead, each event was converted into a compact annotation packet containing:

- full `change_text`
- event metadata
- linked-document coverage metadata
- selected evidence snippets from downloaded documents
- local heuristic cue summaries

Key packet files:
- [annotation_event_packets_v1.jsonl](<repository-root>/annotation_packets/annotation_event_packets_v1.jsonl)
- [annotation_rule_layer_v2.jsonl](<repository-root>/annotation_runtime/annotation_rule_layer_v2.jsonl)
- [annotation_prompt_render_v2.jsonl](<repository-root>/annotation_runtime/annotation_prompt_render_v2.jsonl)

Purpose of the rule layer:

- not to finalize labels
- but to surface rough signal
- support retrieval and prompt construction
- identify expansion candidates
- pre-flag likely hard cases

## Live Calibration Before Production

Two small live calibration phases were run before full production.

### Initial side-by-side model calibration

Models compared:

- `gpt-5-mini-2025-08-07`
- `gpt-5.4-mini-2026-03-17`

Calibration size:
- `30` events

Decision criteria:

- schema compliance
- evidence grounding
- logical consistency
- conservativeness
- token efficiency

Outcome:

- `gpt-5.4-mini` was more conservative and cleaner on grounding
- it was chosen as the full first-pass model

### v2 schema/prompt recheck

Model:
- `gpt-5.4-mini-2026-03-17`

Recheck size:
- `12` events

Purpose:

- verify `rwe_relevance_to_change`
- verify compact embedded definitions in the prompt
- catch schema/prompt boundary issues before production

Outcome:

- `12/12` parsed cleanly
- one consistency edge case was patched locally in the codebook/prompt/QC logic

## Production Stage 1: Full First Pass

Model:
- `gpt-5.4-mini-2026-03-17`

Settings:
- `reasoning_effort = low`
- Batch API

Input:
- all `10,616` events

Shard structure:
- `8` shards

Artifacts:
- [first_pass_gpt-5.4-mini-low](<repository-root>/annotation_production_v2/first_pass_gpt-5.4-mini-low)

Exact batch wall-clock window:
- `25m 40s`

Token usage:
- input: `28,552,616`
- output: `5,926,008`
- reasoning: `2,195,010`

Initial outcome:

- all `10,616` request IDs returned
- `10,034` rows parsed cleanly
- `582` rows returned `status=incomplete` due to `content_filter`

The dominant failure mode was truncated JSON output during supporting-evidence snippet generation.

## Production Stage 2: Targeted Repair / Hard-Case Review

Rationale:

- repair incomplete outputs
- fix grounding problems
- repair borderline core positives
- avoid rerunning the full corpus

Repair subset size:
- `1,092` events

Subset sources included:

- the `582` content-filter incomplete rows
- rows with missing supporting evidence
- rows with placeholder or invented support doc IDs
- rows with `primary_yes_without_direct_relevance`
- small additional high-priority logic/grounding failures

Model:
- `gpt-5.4-2026-03-05`

Settings:
- `reasoning_effort = low`
- Batch API

Repair prompt changes:

- required short paraphrased evidence snippets
- prohibited placeholder doc IDs
- forced conservative downgrade when linked evidence did not support positive or method-detail labels

Artifacts:
- [repair_retry_gpt-5.4-low](<repository-root>/annotation_production_v2/repair_retry_gpt-5.4-low)

Exact batch wall-clock window:
- `5h 21m 18s`

Token usage:
- input: `2,749,626`
- output: `719,893`
- reasoning: `348,795`

Outcome:

- `1,092 / 1,092` parsed cleanly
- `582` previously missing rows were recovered
- `510` already-parsed first-pass rows were replaced by stronger repaired outputs

Merged repaired table:
- [merged_first_pass_repaired](<repository-root>/annotation_production_v2/merged_first_pass_repaired)

Post-repair QC:

- parsed rows: `10,616`
- parse errors: `0`
- grounding issues: `41`
- hard logic violations: `18`

## Production Stage 3: Narrow Adjudication Pass

Rationale:

- apply a stronger review only to the highest-value remaining hard cases
- reduce false-positive risk in the primary endpoint

Broad caution flag after repair:
- `needs_adjudication = yes` on `1,780` rows

Narrow third-run subset:
- `447` rows

Criteria for `third_run_recommended = yes`:

- `positive_core_label`
- `low_confidence`
- `multiple_doc_conflict`
- `transparency_inconsistency`
- `rule_model_disagreement`

Model:
- `gpt-5.4-2026-03-05`

Settings:
- `reasoning_effort = low`
- Batch API

Artifacts:
- [third_run_adjudication_gpt-5.4-low](<repository-root>/annotation_production_v2/third_run_adjudication_gpt-5.4-low)

Exact batch wall-clock window:
- `19m 31s`

Token usage:
- input: `1,639,942`
- output: `372,447`
- reasoning: `181,826`

Outcome:

- `447 / 447` parsed cleanly
- all `447` adjudication rows changed at least one field

Most frequently changed fields:

- `primary_design_category`: `209`
- `annotation_evidence_strength`: `173`
- `annotation_confidence`: `147`
- `rwe_source_type_primary`: `137`
- `rwe_relevance_to_change`: `114`
- `rwe_documented_publicly`: `108`
- `analytic_rwe_documented`: `73`

## Final Output and Provenance

Final annotation table:
- [first_pass_annotations.csv](<repository-root>/annotation_production_v2/final_adjudicated/parsed/first_pass_annotations.csv)

Final provenance split:

- `first_pass`: `9,108`
- `repair`: `1,061`
- `adjudication`: `447`

Important provenance fields:

- `final_label_source`
- `merge_source`
- `pre_adjudication_label_source`
- `adjudication_applied`
- `first_pass_model`
- `repair_model`
- `adjudication_model`
- `first_pass_prompt_version`
- `repair_prompt_version`
- `adjudication_prompt_version`

## Final QC State

Final QC:

- parsed rows: `10,616 / 10,616`
- parse errors: `0`
- grounding issues: `38`
- hard logic violations: `36`
- logic warnings: `3,735`

The remaining warning burden is mostly soft semantics mismatch, not structural parsing failure.

## Final Label Counts

Primary results:

- `rwe_documented_publicly = yes`: `2,026` (`19.1%`)
- `analytic_rwe_documented = yes`: `1,226` (`11.5%`)

Selected secondary signals:

- `public_evidence_available = yes`: `8,527`
- `rwe_relevance_to_change = direct`: `3,315`
- `explicit_rwe`: `119`
- `explicit_observational_real_world`: `1,346`
- `spontaneous_reports_only`: `1,940`

## Interpretation

The pipeline suggests that:

- publicly visible evidence related to safety label changes is common
- strict event-linked RWE documentation is nontrivial but minority
- analytic RWE documentation is rarer
- deep methodological transparency is uncommon

This makes the dataset suitable for downstream descriptive and sensitivity analyses, with appropriate disclosure that the annotation was produced by a fully automated multi-stage LLM pipeline rather than a human gold-standard review process.
