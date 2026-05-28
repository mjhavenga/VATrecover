# VAT Input-Tax Review for Xero

Python application for an accounting practice to run a read-only VAT input-tax review across multiple Xero organisations. Each run is scoped to one Xero tenant and one review period, with separate per-org output.

## What it does

- Uses Xero OAuth 2.0 Authorization Code flow.
- Lists tenant connections so the practice can select the client organisation.
- Pulls all purchase-side data in the selected review window: ACCPAY invoices, SPEND bank transactions, ACCPAY credit notes, accounts, contacts, tax rates, and organisation settings.
- Normalizes Xero lines into a stable `TransactionLine` model.
- Defaults to a five-year review window and scrutinises every normalized purchase-side line in that window.
- Profiles each client's own account/supplier history instead of hardcoding account codes or supplier names. For a five-year full review, the extracted review corpus is also used as the behavioural baseline; optionally pass `--history-from` to add earlier profile history.
- Flags potential under-claimed input VAT as review items only.
- Suppresses configured blocked input VAT, non-VAT suppliers, exempt/zero-rated accounts, and apportionment accounts.
- Writes an Excel working paper and a client-facing Markdown summary.

## Module structure

- `vat_input_review.models`: normalized transaction-line and review-flag data model.
- `vat_input_review.config`: per-org YAML/JSON config.
- `vat_input_review.auth`: Xero OAuth and local token storage.
- `vat_input_review.extraction`: read-only multi-tenant Accounting API extraction and normalization.
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
