from __future__ import annotations

import argparse
import os
from datetime import date
from datetime import timedelta
from pathlib import Path

from .auth import FileTokenStore, XeroAuthClient, XeroOAuthConfig
from .ai_review import enrich_flags_with_ai, make_ai_review_client
from .config import OrgReviewConfig, load_org_config
from .date_ranges import chunk_date_range, subtract_years
from .exports import export_transaction_pack
from .extraction import XeroAccountingClient
from .io import load_transaction_lines, write_transaction_lines
from .pastel import load_pastel_export
from .profiling import build_profiles
from .reporting import write_reports
from .rules import evaluate_lines


def main() -> None:
    parser = argparse.ArgumentParser(description="VAT input-tax review for Xero client organisations.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    auth_url = subparsers.add_parser("auth-url", help="Print the Xero OAuth authorization URL.")
    _add_oauth_args(auth_url)
    auth_url.add_argument("--state", required=True)

    exchange = subparsers.add_parser("exchange-code", help="Exchange a Xero OAuth code for a local token file.")
    _add_oauth_args(exchange)
    exchange.add_argument("--token-file", required=True)
    exchange.add_argument("--code", required=True)

    tenants = subparsers.add_parser("list-tenants", help="List Xero organisations available to the connection.")
    _add_oauth_args(tenants)
    tenants.add_argument("--token-file", required=True)

    fixture = subparsers.add_parser("run-fixture", help="Run a review from normalized JSON lines.")
    fixture.add_argument("--config", required=True)
    fixture.add_argument("--history-json", required=True)
    fixture.add_argument("--review-json", required=True)
    fixture.add_argument("--output-dir", required=True)
    _add_ai_args(fixture)

    pastel = subparsers.add_parser("run-pastel", help="Run a review from a Sage Pastel CSV/XLSX purchase export.")
    pastel.add_argument("--config", required=True)
    pastel.add_argument("--pastel-file", required=True)
    pastel.add_argument("--history-pastel-file", help="Optional older Pastel export for profile history.")
    pastel.add_argument("--output-dir", required=True)
    _add_ai_args(pastel)

    xero = subparsers.add_parser("run-xero", help="Extract read-only Xero data and run the review.")
    _add_oauth_args(xero)
    xero.add_argument("--token-file", required=True)
    xero.add_argument("--config", required=True)
    xero.add_argument("--date-from", help="Review start date. Defaults to date-to minus config.lookback_years.")
    xero.add_argument("--date-to", help="Review end date. Defaults to today.")
    xero.add_argument("--history-from", help="Optional extra profile-history start date before the review window.")
    xero.add_argument("--output-dir", required=True)
    xero.add_argument("--dump-normalized-json", action="store_true")
    _add_ai_args(xero)

    export_fixture = subparsers.add_parser("export-fixture", help="Export normalized JSON lines as an AI-ready transaction pack.")
    export_fixture.add_argument("--config", required=True)
    export_fixture.add_argument("--review-json", required=True)
    export_fixture.add_argument("--output-dir", required=True)
    export_fixture.add_argument("--formats", default="csv,json,xlsx")

    export_pastel = subparsers.add_parser("export-pastel", help="Export a Pastel CSV/XLSX file as an AI-ready transaction pack.")
    export_pastel.add_argument("--config", required=True)
    export_pastel.add_argument("--pastel-file", required=True)
    export_pastel.add_argument("--output-dir", required=True)
    export_pastel.add_argument("--formats", default="csv,json,xlsx")

    export_xero = subparsers.add_parser("export-xero", help="Headless Xero export using a stored refresh token.")
    _add_oauth_args(export_xero)
    export_xero.add_argument("--token-file", required=True)
    export_xero.add_argument("--config", required=True)
    export_xero.add_argument("--date-from", help="Export start date. Defaults to date-to minus config.lookback_years.")
    export_xero.add_argument("--date-to", help="Export end date. Defaults to today.")
    export_xero.add_argument("--chunk", choices=["monthly", "quarterly", "yearly", "all"], default="monthly")
    export_xero.add_argument("--output-dir", required=True)
    export_xero.add_argument("--formats", default="csv,json,xlsx")

    args = parser.parse_args()
    if args.command == "auth-url":
        client = XeroAuthClient(_oauth_config(args), FileTokenStore(Path(".xero-token-unused.json")))
        print(client.authorization_url(args.state))
    elif args.command == "exchange-code":
        client = XeroAuthClient(_oauth_config(args), FileTokenStore(args.token_file))
        client.exchange_code(args.code)
        print(f"Token saved to {args.token_file}")
    elif args.command == "list-tenants":
        auth_client = XeroAuthClient(_oauth_config(args), FileTokenStore(args.token_file))
        accounting = XeroAccountingClient(auth_client.access_token())
        for connection in accounting.list_connections():
            print(f"{connection.tenant_id}\t{connection.tenant_name or ''}\t{connection.tenant_type or ''}")
    elif args.command == "run-fixture":
        config = load_org_config(args.config)
        history = _assert_single_tenant(load_transaction_lines(args.history_json), config)
        review = _assert_single_tenant(load_transaction_lines(args.review_json), config)
        _run_review(config, history, review, Path(args.output_dir), ai_provider=args.ai_provider if args.ai_review else None)
    elif args.command == "run-pastel":
        config = load_org_config(args.config)
        review = load_pastel_export(args.pastel_file, config).lines
        history = load_pastel_export(args.history_pastel_file, config).lines + review if args.history_pastel_file else review
        _run_review(
            config,
            history,
            review,
            Path(args.output_dir),
            run_range=_infer_run_range(config, review),
            ai_provider=args.ai_provider if args.ai_review else None,
        )
    elif args.command == "export-fixture":
        config = load_org_config(args.config)
        lines = _assert_single_tenant(load_transaction_lines(args.review_json), config)
        paths = _export_lines(config, lines, Path(args.output_dir), _infer_run_range(config, lines), _parse_formats(args.formats))
        _print_export_paths(paths)
    elif args.command == "export-pastel":
        config = load_org_config(args.config)
        lines = load_pastel_export(args.pastel_file, config).lines
        paths = _export_lines(config, lines, Path(args.output_dir), _infer_run_range(config, lines), _parse_formats(args.formats))
        _print_export_paths(paths)
    elif args.command == "export-xero":
        config = load_org_config(args.config)
        date_to = date.fromisoformat(args.date_to) if args.date_to else date.today()
        date_from = date.fromisoformat(args.date_from) if args.date_from else subtract_years(date_to, config.lookback_years)
        auth_client = XeroAuthClient(_oauth_config(args), FileTokenStore(args.token_file))
        accounting = XeroAccountingClient(auth_client.access_token())
        formats = _parse_formats(args.formats)
        for chunk_from, chunk_to in chunk_date_range(date_from, date_to, args.chunk):
            lines = accounting.extract_for_tenant(config.tenant_id, config, chunk_from, chunk_to).lines
            paths = _export_lines(config, lines, Path(args.output_dir), (chunk_from, chunk_to), formats)
            print(f"Exported {len(lines)} lines for {chunk_from.isoformat()} to {chunk_to.isoformat()}")
            _print_export_paths(paths)
    elif args.command == "run-xero":
        config = load_org_config(args.config)
        date_to = date.fromisoformat(args.date_to) if args.date_to else date.today()
        date_from = date.fromisoformat(args.date_from) if args.date_from else _subtract_years(date_to, config.lookback_years)
        history_from = date.fromisoformat(args.history_from) if args.history_from else None
        auth_client = XeroAuthClient(_oauth_config(args), FileTokenStore(args.token_file))
        accounting = XeroAccountingClient(auth_client.access_token())
        review = accounting.extract_for_tenant(config.tenant_id, config, date_from, date_to).lines
        if history_from:
            history_to = date_from - timedelta(days=1)
            history = accounting.extract_for_tenant(config.tenant_id, config, history_from, history_to).lines + review
        else:
            history = review
        output_dir = Path(args.output_dir)
        if args.dump_normalized_json:
            org_dir = output_dir / config.tenant_id
            org_dir.mkdir(parents=True, exist_ok=True)
            write_transaction_lines(org_dir / "history_lines.json", history)
            write_transaction_lines(org_dir / "review_lines.json", review)
        _run_review(
            config,
            history,
            review,
            output_dir,
            run_range=(date_from, date_to),
            ai_provider=args.ai_provider if args.ai_review else None,
        )


def _run_review(
    config: OrgReviewConfig,
    history,
    review,
    output_dir: Path,
    run_range: tuple[date, date] | None = None,
    ai_provider: str | None = None,
) -> None:
    if run_range is None:
        if config.review_range is None:
            raise RuntimeError("Config must include review_date_range when running from fixtures.")
        run_range = (config.review_range.date_from, config.review_range.date_to)

    profiles = build_profiles(history, config)
    flags = evaluate_lines(review, profiles, config)
    ai_reviews = None
    if ai_provider:
        ai_reviews = enrich_flags_with_ai(flags, make_ai_review_client(ai_provider))
    paths = write_reports(flags, config, output_dir, run_range, ai_reviews=ai_reviews)
    print(f"Flagged review items: {len(flags)}")
    print(f"Working paper: {paths.working_paper_xlsx}")
    print(f"Client summary: {paths.client_summary_md}")


def _infer_run_range(config: OrgReviewConfig, lines) -> tuple[date, date]:
    if config.review_range is not None:
        return config.review_range.date_from, config.review_range.date_to
    if not lines:
        today = date.today()
        return subtract_years(today, config.lookback_years), today
    return min(line.transaction_date for line in lines), max(line.transaction_date for line in lines)


def _assert_single_tenant(lines, config: OrgReviewConfig):
    tenant_ids = {line.tenant_id for line in lines}
    if tenant_ids - {config.tenant_id}:
        raise RuntimeError(f"Input contains tenant IDs outside config tenant {config.tenant_id}: {sorted(tenant_ids)}")
    return lines


def _add_oauth_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--client-id", default=os.getenv("XERO_CLIENT_ID"), required=not os.getenv("XERO_CLIENT_ID"))
    parser.add_argument("--client-secret", default=os.getenv("XERO_CLIENT_SECRET"), required=not os.getenv("XERO_CLIENT_SECRET"))
    parser.add_argument("--redirect-uri", default=os.getenv("XERO_REDIRECT_URI"), required=not os.getenv("XERO_REDIRECT_URI"))


def _add_ai_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--ai-review", action="store_true", help="Use an AI provider to add structured reviewer notes to flags.")
    parser.add_argument(
        "--ai-provider",
        choices=["openai", "anthropic"],
        default=os.getenv("VATRECOVER_AI_PROVIDER", "openai"),
        help="AI provider for structured review enrichment.",
    )


def _export_lines(config: OrgReviewConfig, lines, output_dir: Path, run_range: tuple[date, date], formats: set[str]):
    _assert_single_tenant(lines, config)
    return export_transaction_pack(lines, output_dir, config.tenant_id, run_range, formats=formats)


def _parse_formats(value: str) -> set[str]:
    formats = {item.strip().lower() for item in value.split(",") if item.strip()}
    allowed = {"csv", "json", "xlsx"}
    unknown = formats - allowed
    if unknown:
        raise ValueError(f"Unsupported export format(s): {', '.join(sorted(unknown))}")
    return formats or allowed


def _print_export_paths(paths) -> None:
    if paths.csv_path:
        print(f"CSV export: {paths.csv_path}")
    if paths.json_path:
        print(f"JSON export: {paths.json_path}")
    if paths.xlsx_path:
        print(f"Excel export: {paths.xlsx_path}")


def _oauth_config(args) -> XeroOAuthConfig:
    return XeroOAuthConfig(
        client_id=args.client_id,
        client_secret=args.client_secret,
        redirect_uri=args.redirect_uri,
    )


def _subtract_years(value: date, years: int) -> date:
    return subtract_years(value, years)


if __name__ == "__main__":
    main()
