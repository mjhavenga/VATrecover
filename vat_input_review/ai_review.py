from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol

from .models import ReviewFlag


AI_REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "ai_risk",
        "recommended_action",
        "reviewer_note",
        "evidence_checks",
        "missing_information",
        "claim_readiness",
    ],
    "properties": {
        "ai_risk": {"type": "string", "enum": ["low", "medium", "high"]},
        "recommended_action": {
            "type": "string",
            "enum": ["verify_invoice", "exclude", "claim_candidate", "needs_apportionment_review"],
        },
        "reviewer_note": {"type": "string"},
        "evidence_checks": {"type": "array", "items": {"type": "string"}},
        "missing_information": {"type": "array", "items": {"type": "string"}},
        "claim_readiness": {"type": "integer", "minimum": 0, "maximum": 100},
    },
}


@dataclass(frozen=True)
class AIReview:
    ai_risk: str
    recommended_action: str
    reviewer_note: str
    evidence_checks: list[str]
    missing_information: list[str]
    claim_readiness: int
    model: str
    raw: dict[str, Any] = field(default_factory=dict)


class AIReviewClient(Protocol):
    def review_flag(self, flag: ReviewFlag) -> AIReview:
        """Return a structured AI review for one VAT review flag."""


class DisabledAIReviewClient:
    def review_flag(self, flag: ReviewFlag) -> AIReview:  # pragma: no cover - defensive only.
        raise RuntimeError("AI review is disabled. Set OPENAI_API_KEY and enable --ai-review.")


class OpenAIReviewClient:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is required when AI review is enabled.")
        self.model = model or os.getenv("VATRECOVER_AI_MODEL", "gpt-5.2")
        self.base_url = (base_url or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")

    def review_flag(self, flag: ReviewFlag) -> AIReview:
        import requests

        payload = {
            "model": self.model,
            "input": [
                {
                    "role": "system",
                    "content": (
                        "You are a senior South African VAT input-tax reviewer. "
                        "You review possible under-claimed input VAT items for an accounting practice. "
                        "Do not say an amount is claimable automatically. Every output must support human sign-off."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(_flag_review_packet(flag), ensure_ascii=False),
                },
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "vat_input_ai_review",
                    "strict": True,
                    "schema": AI_REVIEW_SCHEMA,
                }
            },
        }
        response = requests.post(
            f"{self.base_url}/responses",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
        body = response.json()
        parsed = _extract_response_json(body)
        return AIReview(
            ai_risk=str(parsed["ai_risk"]),
            recommended_action=str(parsed["recommended_action"]),
            reviewer_note=str(parsed["reviewer_note"]),
            evidence_checks=list(parsed["evidence_checks"]),
            missing_information=list(parsed["missing_information"]),
            claim_readiness=int(parsed["claim_readiness"]),
            model=self.model,
            raw=body,
        )


class AnthropicReviewClient:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is required when Anthropic AI review is enabled.")
        self.model = model or os.getenv("VATRECOVER_AI_MODEL", "claude-sonnet-4-5")
        self.base_url = (base_url or os.getenv("ANTHROPIC_BASE_URL") or "https://api.anthropic.com/v1").rstrip("/")
        self.version = os.getenv("ANTHROPIC_VERSION", "2023-06-01")

    def review_flag(self, flag: ReviewFlag) -> AIReview:
        import requests

        tool_name = "record_vat_review"
        payload = {
            "model": self.model,
            "max_tokens": 1200,
            "system": (
                "You are a senior South African VAT input-tax reviewer. "
                "You review possible under-claimed input VAT items for an accounting practice. "
                "Do not say an amount is claimable automatically. Every output must support human sign-off."
            ),
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Review this potential VAT under-claim and call the record_vat_review tool with your structured findings.\n\n"
                        + json.dumps(_flag_review_packet(flag), ensure_ascii=False)
                    ),
                }
            ],
            "tools": [
                {
                    "name": tool_name,
                    "description": "Record a structured VAT input-tax AI review for an accountant.",
                    "input_schema": AI_REVIEW_SCHEMA,
                }
            ],
            "tool_choice": {"type": "tool", "name": tool_name},
        }
        response = requests.post(
            f"{self.base_url}/messages",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": self.version,
                "content-type": "application/json",
            },
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
        body = response.json()
        parsed = _extract_anthropic_tool_input(body, tool_name)
        return AIReview(
            ai_risk=str(parsed["ai_risk"]),
            recommended_action=str(parsed["recommended_action"]),
            reviewer_note=str(parsed["reviewer_note"]),
            evidence_checks=list(parsed["evidence_checks"]),
            missing_information=list(parsed["missing_information"]),
            claim_readiness=int(parsed["claim_readiness"]),
            model=self.model,
            raw=body,
        )


def make_ai_review_client(provider: str | None = None) -> AIReviewClient:
    provider_name = (provider or os.getenv("VATRECOVER_AI_PROVIDER") or "openai").strip().lower()
    if provider_name in {"openai", "responses"}:
        return OpenAIReviewClient()
    if provider_name in {"anthropic", "claude", "anthoripix"}:
        return AnthropicReviewClient()
    raise ValueError(f"Unsupported AI review provider: {provider_name}")


def enrich_flags_with_ai(
    flags: list[ReviewFlag],
    client: AIReviewClient,
    limit: int | None = None,
) -> dict[str, AIReview]:
    selected = flags[:limit] if limit is not None else flags
    return {flag.line.line_id: client.review_flag(flag) for flag in selected}


def _flag_review_packet(flag: ReviewFlag) -> dict[str, Any]:
    line = flag.line
    return {
        "instruction": (
            "Review this potential VAT under-claim. Return only structured JSON. "
            "Focus on defensibility, likely legitimate exclusions, missing source evidence, and reviewer sign-off questions."
        ),
        "source_system": line.source_system,
        "tenant_id": line.tenant_id,
        "organisation_name": line.organisation_name,
        "transaction": {
            "type": line.transaction_type,
            "transaction_id": line.transaction_id,
            "line_id": line.line_id,
            "document_number": line.document_number,
            "date": line.transaction_date.isoformat(),
            "vat_period": line.vat_period,
            "description": line.description,
        },
        "supplier": {
            "id": line.supplier_id,
            "name": line.supplier_name,
            "vat_number": line.supplier_vat_number,
        },
        "account": {
            "id": line.account_id,
            "code": line.account_code,
            "name": line.account_name,
        },
        "tax": {
            "tax_type": line.tax_type,
            "net_amount": str(line.net_amount),
            "vat_claimed": str(line.vat_amount),
            "effective_rate": str(line.effective_rate),
            "vat_expected": str(flag.expected_vat),
            "estimated_underclaim": str(flag.estimated_underclaim),
        },
        "rule_engine": {
            "reason_code": flag.reason_code,
            "reason": flag.reason,
            "confidence": str(flag.confidence),
            "evidence": flag.evidence,
        },
        "constraints": [
            "This is a review item, not an automatic VAT claim.",
            "Blocked input VAT, non-VAT vendors, exempt supplies, zero-rated supplies, and apportionment can make a zero claim legitimate.",
            "Recommend source-document checks the reviewer should perform before signing off.",
        ],
    }


def _extract_response_json(body: dict[str, Any]) -> dict[str, Any]:
    if isinstance(body.get("output_parsed"), dict):
        return body["output_parsed"]

    for output in body.get("output", []):
        for content in output.get("content", []):
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                return json.loads(content["text"])

    output_text = body.get("output_text")
    if output_text:
        return json.loads(output_text)

    raise RuntimeError("OpenAI response did not include structured AI review JSON.")


def _extract_anthropic_tool_input(body: dict[str, Any], tool_name: str) -> dict[str, Any]:
    for content in body.get("content", []):
        if content.get("type") == "tool_use" and content.get("name") == tool_name:
            tool_input = content.get("input")
            if isinstance(tool_input, dict):
                return tool_input
    raise RuntimeError("Anthropic response did not include the expected structured VAT review tool call.")


def ai_review_to_report_fields(review: AIReview | None) -> dict[str, Any]:
    if review is None:
        return {
            "ai_risk": "",
            "ai_action": "",
            "ai_claim_readiness": "",
            "ai_reviewer_note": "",
            "ai_evidence_checks": "",
            "ai_missing_information": "",
        }
    return {
        "ai_risk": review.ai_risk,
        "ai_action": review.recommended_action,
        "ai_claim_readiness": Decimal(review.claim_readiness) / Decimal("100"),
        "ai_reviewer_note": review.reviewer_note,
        "ai_evidence_checks": "; ".join(review.evidence_checks),
        "ai_missing_information": "; ".join(review.missing_information),
    }
