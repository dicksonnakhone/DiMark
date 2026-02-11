from __future__ import annotations

from decimal import Decimal
from typing import Any


def _to_decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def split_allocations(
    allocations: dict[str, Decimal], variant_shares: dict[str, Decimal]
) -> dict[str, dict[str, Decimal]]:
    result: dict[str, dict[str, Decimal]] = {name: {} for name in variant_shares}
    for channel, amount in allocations.items():
        channel_total = _to_decimal(amount)
        split = {
            variant: _quantize(channel_total * share)
            for variant, share in variant_shares.items()
        }
        remainder = channel_total - sum(split.values())
        if split:
            largest_variant = max(split.items(), key=lambda item: (item[1], item[0]))[0]
            split[largest_variant] = _quantize(split[largest_variant] + remainder)
        for variant, value in split.items():
            result[variant][channel] = value
    return result
