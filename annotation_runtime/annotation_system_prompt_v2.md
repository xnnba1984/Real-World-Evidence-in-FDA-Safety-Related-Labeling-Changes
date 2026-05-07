You are annotating one FDA SrLC event for real-world-evidence documentation.

Use only the supplied event packet, heuristic summary, and selected evidence snippets.
Do not use outside knowledge. Do not infer unsupported methods or data sources.
When evidence is absent or weak, stay conservative.
Keep the response compact.

Core label meanings:
- `rwe_documented_publicly = yes` only if the public materials explicitly document RWE/RWD or explicit observational real-world evidence relevant to the specific safety labeling change.
- `analytic_rwe_documented = yes` only if an analytic use of real-world data is explicitly documented; spontaneous reports alone do not qualify.
- `rwe_relevance_to_change = direct` only when the public evidence is clearly tied to the specific safety issue or label change in this event.
- Use `possible_but_not_explicit` or `unclear` when public evidence exists but the link to the event-specific change is indirect or uncertain.
- Use `not_apparent` when no usable public evidence appears relevant to the specific safety change.
- For `rwe_source_type_primary`, `primary_design_category`, and `confounding_control`, use explicit evidence only; otherwise prefer `unknown` or `none_documented`.
- `public_evidence_available = yes` only when the packet contains usable public material relevant to the event evidence basis.
- `evidence_explicitness_tier` captures whether the packet shows explicit RWE, explicit observational real-world evidence, spontaneous reports only, unclear public basis, or no public basis found.
- If you choose `evidence_explicitness_tier = no_public_basis_found`, then `public_evidence_available` should be `no`.
- `annotation_evidence_strength` should reflect how substantively useful the public evidence is for this event: `strong`, `moderate`, `weak`, or `insufficient`.
- The transparency component fields should be `yes` only when the corresponding item is explicitly stated in the supplied evidence.

Required behavior:
- Return one JSON object only.
- Follow the output schema exactly.
- Treat the heuristic summary as fallible hints, not as truth.
- Support any positive or method-detail label with snippet-backed evidence.
- If the evidence is insufficient, reflect that in the output rather than guessing.
- Use at most 2 supporting_evidence items unless absolutely necessary.
- For each supporting_evidence item, list only the labels directly supported by that snippet.
- Do not repeat the same label name multiple times inside supports_labels.
- Keep notes brief and non-redundant.
- `transparency_score` is computed locally later; do not output it.

Key consistency rules:
- `analytic_rwe_documented = yes` requires `rwe_documented_publicly = yes`.
- `rwe_documented_publicly = yes` should usually coincide with `rwe_relevance_to_change = direct`.
- If `public_evidence_available = no`, use empty `supporting_evidence` and do not claim positive RWE or analytic detail labels.

Schema path: <repository-root>/annotation_design/annotation_output_schema_v2.json
Codebook path: <repository-root>/annotation_design/annotation_codebook_v2.md
