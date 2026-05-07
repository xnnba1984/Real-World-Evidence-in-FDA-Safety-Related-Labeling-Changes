# Public RWE Documentation in FDA Safety-Related Labeling Changes

This repository contains the curated analysis and annotation workflow code for the manuscript on public documentation of real-world evidence (RWE) in FDA Safety-related Labeling Changes (SrLCs).

The repository is intended for transparency and reproducibility review. It includes the main pipeline scripts, annotation design files, annotation prompt templates, and analysis documentation. The public annotated dataset is deposited separately on Zenodo at https://zenodo.org/records/20073057.

## Repository Contents

- `code/`: workflow scripts for event-cohort construction, evidence retrieval, annotation packet generation, analysis-ready table construction, feature engineering, descriptive analyses, models, sensitivity analyses, enrichment analyses, figure rendering, and supplementary table generation.
- `annotation_design/`: annotation codebook, logic rules, output schema, and frozen annotation design metadata.
- `annotation_runtime/`: system and user prompt templates used to generate annotation inputs.
- `docs/`: analysis-ready table dictionaries, annotation pipeline summary, annotation results summary, and endpoint audit report.
- `scripts/`: support scripts, including the Zenodo public-release data packaging script.

## Data

The public annotated dataset should be downloaded from the associated Zenodo record and placed in the expected project structure if reproducing downstream analyses.

This code release does not include:

- API keys or credentials.
- Raw annotation batch/runtime artifacts.
- Individual reviewer workbooks or adjudication worksheets.
- Raw packet text files.
- Large downloaded FDA evidence-document archives.
- Manuscript Word files.
- Local machine paths.

## Reproducibility Notes

The original study workflow had two levels:

1. End-to-end workflow from FDA source exports and linked public evidence documents.
2. Downstream analytic workflow from the final analysis-ready annotation table.

Some end-to-end steps require source files or intermediate annotation outputs that are not included in this code repository because they are large, internal, or not needed for public interpretation. The primary public data release is the Zenodo annotated event-level dataset; this repository documents and provides the code used to construct and analyze that dataset.

## Suggested Run Order

The main workflow scripts are organized approximately as follows:

1. `code/step1_build_srlc_event_cohort_from_export.py`
2. `code/step_g_build_event_evidence_package.py`
3. `code/step_h_build_annotation_packets.py`
4. `code/step_i_prepare_rule_layer_and_prompts.py`
5. `code/step_y_build_analysis_ready_table.py`
6. `code/step_z_build_analysis_feature_layer.py`
7. `code/step_aa_build_strict_endpoint_layer.py`
8. `code/step_ab_build_descriptive_tables.py`
9. `code/step_ae_fit_adjusted_models.py`
10. `code/step_ad_run_sensitivity_analyses.py`
11. `code/step_aj_build_therapeutic_area_enrichment.py`
12. `code/step_ak_build_product_age_enrichment.py`
13. `code/step_al_build_sponsor_manufacturer_enrichment.py`
14. `code/step_am_build_enrichment_synthesis.py`
15. `code/step_af_render_paper_figures.py`
16. `code/step_ao_build_supplement_package.py`

## Environment

The scripts were run with Python 3. The main Python package dependencies are listed in `requirements.txt`.

