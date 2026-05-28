# VATrecover Transaction Exporter

Python application for an accounting practice to connect to accounting systems, extract purchase-side transactions, and export AI-ready transaction packs. It keeps each client organisation isolated and never writes back to the accounting system.

## What it does

- Uses Xero OAuth 2.0 with offline refresh tokens, so exports can run headlessly after one-time consent.
- Lists tenant connections so the practice can select the client organisation.
- Pulls purchase-side data in the selected window: ACCPAY invoices, SPEND bank transactions, ACCPAY credit notes, accounts, contacts, tax rates, and organisation settings.
- Normalizes lines into a stable `TransactionLine` model across Xero, Sage Accounting, and Pastel exports.
- Defaults to a five-year export window and supports monthly, quarterly, yearly, or single-file chunking for high-volume clients.
- Exports AI-ready CSV, JSON, and XLSX transaction packs.
- Imports Sage Pastel/Sage 50 purchase exports in CSV/XLSX form.
- Keeps the VAT review/rule engine as an optional later workflow, not the main purpose.
- Flags potential under-claimed input VAT as review items only.
- Suppresses configured blocked input VAT, non-VAT suppliers, exempt/zero-rated accounts, and apportionment accounts.
- Writes an Excel working paper and a client-facing Markdown summary.

## Module structure

- `vat_input_review.models`: normalized transaction-line and review-flag data model.
- `vat_input_review.config`: per-org YAML/JSON config.
- `vat_input_review.auth`: Xero OAuth and local token storage.
- `vat_input_review.extraction`: read-only multi-tenant Accounting API extraction and normalization.
- `vat_input_review.exports`: AI-ready CSV/JSON/XLSX transaction pack export.
- `vat_input_review.profiling`: adaptive historical profiles by account, supplier, and account/supplier pair.
- `vat_input_review.rules`: deterministic review-item rules with confidence and audit evidence.
- `vat_input_review.reporting`: Excel working paper and client summary.
- `vat_input_review.cli`: command-line runner.

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Render deploy

This repository includes `render.yaml` so Render deploys it as a Python service instead of guessing another runtime.

- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn vat_input_review.web:app --bind 0.0.0.0:$PORT`
- Health check: `/health`

The Render web service opens a clean ERP-style review workbench with Xero, Sage Accounting, and Pastel source-system controls. VAT reviews are still executed through the backend/CLI workflow until credentials, storage, and user access controls are configured for production.

## Sage Accounting integration

The `vat_input_review.sage` module adds the connector structure for Sage Business Cloud Accounting:

- OAuth 2.0 authorization and token refresh.
- Business selection through Sage's business identifier.
- Read-only extraction skeleton for contacts, ledger accounts, purchase invoices, and purchase credit notes.
- Normalization into the same `TransactionLine` model used by Xero and Pastel.

## Run tests

```powershell
python -m unittest
```

## Xero workflow

1. Create a Xero app with a redirect URI.
2. Generate the authorization URL:

```powershell
python -m vat_input_review.cli auth-url --client-id $env:XERO_CLIENT_ID --client-secret $env:XERO_CLIENT_SECRET --redirect-uri $env:XERO_REDIRECT_URI --state practice-review
```

3. Exchange the returned code:

```powershell
python -m vat_input_review.cli exchange-code --token-file .xero-token.json --code "<code>" --client-id $env:XERO_CLIENT_ID --client-secret $env:XERO_CLIENT_SECRET --redirect-uri $env:XERO_REDIRECT_URI
```

4. List available Xero organisations:

```powershell
python -m vat_input_review.cli list-tenants --token-file .xero-token.json --client-id $env:XERO_CLIENT_ID --client-secret $env:XERO_CLIENT_SECRET --redirect-uri $env:XERO_REDIRECT_URI
```

5. Configure the selected tenant in `examples/org_config.yml`, then run a five-year review ending today:

```powershell
python -m vat_input_review.cli run-xero --config examples/org_config.yml --token-file .xero-token.json --output-dir outputs --dump-normalized-json --client-id $env:XERO_CLIENT_ID --client-secret $env:XERO_CLIENT_SECRET --redirect-uri $env:XERO_REDIRECT_URI
```

To run a specific VAT period, pass `--date-from` and `--date-to`. To enrich the profile baseline with data before the review window, also pass `--history-from`.

## Headless transaction export

After the one-time Xero consent flow has created `.xero-token.json`, exports can run without a user login. For high-volume clients, use monthly chunks:

```powershell
python -m vat_input_review.cli export-xero --config examples/org_config.json --token-file .xero-token.json --output-dir outputs --chunk monthly --formats csv,json,xlsx --client-id $env:XERO_CLIENT_ID --client-secret $env:XERO_CLIENT_SECRET --redirect-uri $env:XERO_REDIRECT_URI
```

Each chunk writes separate files under `outputs/<tenant_id>/`, for example:

- `transactions_for_ai_review_2026-01-01_to_2026-01-31.csv`
- `transactions_for_ai_review_2026-01-01_to_2026-01-31.json`
- `transactions_for_ai_review_2026-01-01_to_2026-01-31.xlsx`

The JSON export is best for direct AI ingestion. The CSV/XLSX exports are useful for manual upload, filtering, or accountant review.

## Output

For each tenant, output is written under `outputs/<tenant_id>/`:

- `vat_input_review_working_paper_<date_range>.xlsx`
- `vat_input_review_client_summary_<date_range>.md`

The Excel working paper includes transaction ID, line ID, source document number, supplier, account, net, VAT claimed, VAT expected, estimated under-claim, reason code, confidence, audit trail, and a `Reviewed Y/N` sign-off column.

## Fixture workflow

Use normalized JSON lines for offline development or tests. If dependencies are not installed yet, use the JSON config; YAML config requires `PyYAML`.

```powershell
python -m vat_input_review.cli run-fixture --config examples/org_config.json --history-json examples\history_lines.json --review-json examples\review_lines.json --output-dir outputs
```

No rule-engine tests call the live Xero API.

To export fixture transactions without applying VAT rules:

```powershell
python -m vat_input_review.cli export-fixture --config examples/org_config.json --review-json examples\review_lines.json --output-dir outputs
```

## Sage Pastel / Sage 50 file workflow

Export the Pastel purchase transaction review data to CSV or XLSX with columns such as date, supplier, VAT number, GL account, tax/VAT code, net amount, VAT amount, gross amount, and document reference. Then run:

```powershell
python -m vat_input_review.cli run-pastel --config examples/org_config.json --pastel-file examples\pastel_purchase_export.csv --output-dir outputs
```

To export Pastel transactions for AI review without applying VAT rules:

```powershell
python -m vat_input_review.cli export-pastel --config examples/org_config.json --pastel-file examples\pastel_purchase_export.csv --output-dir outputs
```

Native Pastel database or backup files are intentionally not parsed directly yet; export to CSV/XLSX first so the review remains transparent and defensible.

## AI review enrichment

The deterministic rule engine remains the source of review flags. AI is optional and adds structured reviewer notes, evidence checks, missing-information prompts, risk level, and claim-readiness scoring. It never turns a review item into an automatic claim.

OpenAI:

```powershell
$env:OPENAI_API_KEY = "<your key>"
$env:VATRECOVER_AI_PROVIDER = "openai"
python -m vat_input_review.cli run-fixture --config examples/org_config.json --history-json examples\history_lines.json --review-json examples\review_lines.json --output-dir outputs --ai-review --ai-provider openai
```

Anthropic/Claude:

```powershell
$env:ANTHROPIC_API_KEY = "<your key>"
$env:VATRECOVER_AI_PROVIDER = "anthropic"
$env:VATRECOVER_AI_MODEL = "claude-sonnet-4-5"
python -m vat_input_review.cli run-fixture --config examples/org_config.json --history-json examples\history_lines.json --review-json examples\review_lines.json --output-dir outputs --ai-review --ai-provider anthropic
```

AI review output is written into additional working-paper columns: AI Risk, AI Action, AI Claim Readiness, AI Reviewer Note, AI Evidence Checks, and AI Missing Information.
