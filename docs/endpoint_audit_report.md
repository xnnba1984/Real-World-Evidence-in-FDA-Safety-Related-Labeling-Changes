# Endpoint Audit Report

- input feature layer: `<repository-root>/analysis_ready/srlc_analysis_feature_layer.csv`
- output endpoint layer: `<repository-root>/analysis_ready/srlc_analysis_endpoint_layer.csv`
- output count summary: `<repository-root>/analysis_ready/endpoint_audit_counts.csv`
- total events: `10616`

## Frozen endpoint family

- Main endpoint:
  - `endpoint_main_public_rwe` = `rwe_documented_publicly = yes`
- Key secondary endpoint:
  - `endpoint_secondary_analytic_public_rwe` = `analytic_rwe_documented = yes`
- Sensitivity-only endpoints:
  - `endpoint_sens_explicit_public_rwe` = `explicit_public_rwe_any_flag = yes`
  - `endpoint_sens_non_spontaneous_public_rwe` = broad endpoint excluding `spontaneous_reports_only_flag = yes`
  - `endpoint_sens_qc_strict_public_rwe` = broad endpoint excluding `hard_issue_flag = yes`

## Overall endpoint counts

- `endpoint_main_public_rwe = yes`: `2026` (19.08%)
- `endpoint_secondary_analytic_public_rwe = yes`: `1205` (11.35%)
- `endpoint_sens_explicit_public_rwe = yes`: `1465` (13.80%)
- `endpoint_sens_non_spontaneous_public_rwe = yes`: `1413` (13.31%)
- `endpoint_sens_qc_strict_public_rwe = yes`: `2007` (18.91%)
- raw `analytic_rwe_documented = yes` rows coerced off because `rwe_documented_publicly = no`: `21`

## Main endpoint decomposition

- broad positives that are also analytic positives: `1205` (59.48%)
- broad positives that are also explicit positives: `1401` (69.15%)
- broad positives that are non-analytic: `821` (40.52%)
- broad positives that are not explicit: `625` (30.85%)
- broad positives that are spontaneous-reports-only: `613` (30.26%)
- broad positives with hard issues: `19` (0.94%)

## Why the sensitivity endpoints matter

- excluding spontaneous-reports-only cases reduces the broad endpoint by `613` events
- excluding hard-issue rows reduces the broad endpoint by `19` events
- requiring explicit public RWE reduces the broad endpoint by `561` events

## Provenance among broad positives

- `adjudication`: `287` (14.17%)
- `first_pass`: `1312` (64.76%)
- `repair`: `427` (21.08%)

## Annotation confidence among broad positives

- `high`: `785` (38.75%)
- `low`: `26` (1.28%)
- `medium`: `1215` (59.97%)

## Provenance among analytic positives

- `adjudication`: `174` (14.44%)
- `first_pass`: `1015` (84.23%)
- `repair`: `16` (1.33%)

## Annotation confidence among analytic positives

- `high`: `481` (39.92%)
- `low`: `14` (1.16%)
- `medium`: `710` (58.92%)

## Interpretation

This narrowed endpoint audit freezes a small paper-facing outcome family without changing the underlying annotation labels.
The main endpoint remains the broad strict codebook label (`rwe_documented_publicly`).
The analytic endpoint remains the key secondary endpoint.
The remaining endpoints are explicitly sensitivity-only and are intended for robustness checks rather than co-equal headline claims.
