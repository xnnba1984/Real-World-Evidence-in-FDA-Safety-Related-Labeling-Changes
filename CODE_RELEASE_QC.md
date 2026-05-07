# GitHub Code Release QC

Date: 2026-05-07

## Folder

- Release folder: `<repository-root>/github_code_release`
- Total files: `35`
- Pipeline scripts in `code/`: `16`
- Support scripts in `scripts/`: `1`
- Manifest: `CODE_RELEASE_MANIFEST.csv`

## Included Content

- Curated workflow scripts for cohort construction, evidence retrieval, annotation packet preparation, analysis-ready table construction, feature engineering, endpoint construction, descriptive analysis, modeling, sensitivity analysis, enrichment analysis, figure rendering, supplementary package generation, and Zenodo release packaging.
- Annotation design files, output schema, logic rules, system prompt, and user prompt template.
- Analysis documentation and annotation-summary documentation.
- README, requirements file, gitignore, release notes, license notice, and checksum manifest.

## Excluded Content

- API keys and credentials.
- Raw annotation production/runtime outputs.
- Individual reviewer workbooks.
- Adjudication worksheets.
- Packet Markdown or JSONL artifacts.
- Large downloaded FDA evidence-document archives.
- Raw evidence document tables.
- Manuscript Word files and private manuscript-review artifacts.

## QC Checks

- Python syntax check: passed for all copied `.py` files.
- JSON validity check: passed for all copied `.json` files.
- Local absolute path scan: no local user-home paths remain.
- Sensitive-file/string scan: no API key file, OpenAI API key variable, `sk-` key pattern, reviewer workbook, or adjudication workbook reference detected.
- Generated `__pycache__` folders from syntax testing were removed before final manifest generation.

## Notes

- Local absolute paths in copied release files were replaced with repository-relative roots or `<repository-root>` placeholders.
- No final open-source license has been selected. Choose a license before making the GitHub repository public.
