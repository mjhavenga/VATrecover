from __future__ import annotations

from datetime import date, timedelta


def subtract_years(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year - years)
    except ValueError:
        return value.replace(year=value.year - years, day=28)


def chunk_date_range(date_from: date, date_to: date, chunk: str = "monthly") -> list[tuple[date, date]]:
    if date_from > date_to:
        raise ValueError("date_from must be on or before date_to.")

    chunk_key = chunk.strip().lower()
    if chunk_key in {"none", "all", "single"}:
        return [(date_from, date_to)]

    ranges: list[tuple[date, date]] = []
    start = date_from
    while start <= date_to:
        if chunk_key in {"monthly", "month"}:
            next_start = _add_months(start.replace(day=1), 1)
        elif chunk_key in {"quarterly", "quarter"}:
            quarter_start_month = ((start.month - 1) // 3) * 3 + 1
            next_start = _add_months(date(start.year, quarter_start_month, 1), 3)
        elif chunk_key in {"yearly", "annual", "year"}:
            next_start = date(start.year + 1, 1, 1)
        else:
            raise ValueError(f"Unsupported chunk size: {chunk}")

        end = min(date_to, next_start - timedelta(days=1))
        ranges.append((start, end))
        start = end + timedelta(days=1)
    return ranges


def _add_months(value: date, months: int) -> date:
    month = value.month - 1 + months
    year = value.year + month // 12
    month = month % 12 + 1
    return date(year, month, 1)
