"""Server-side money formatting for anything a model will read.

An LLM given raw minor units will eventually convert them wrong — observed
live: a Rs 16,215.76 settlement gap answered as "Rs 16.22 lakh" (off by 100x).
So every `*_minor` figure that enters a prompt is accompanied by a `*_display`
string formatted here, deterministically, and the prompt instructs the model to
quote the display form verbatim.
"""

from __future__ import annotations

from typing import Any

from app.config import settings


def format_inr(minor: int | float | None) -> str:
    if minor is None:
        return "-"
    rupees = minor / settings.amount_scale
    sign = "-" if rupees < 0 else ""
    r = abs(rupees)
    # Indian grouping: 12,34,56,789.00
    whole = int(r)
    frac = f"{r - whole:.2f}"[2:]
    sw = str(whole)
    if len(sw) > 3:
        head, tail = sw[:-3], sw[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        sw = ",".join(parts + [tail])
    out = f"Rs {sign}{sw}.{frac}"
    if r >= 1e7:
        out += f" ({sign}{r / 1e7:.2f} crore)"
    elif r >= 1e5:
        out += f" ({sign}{r / 1e5:.2f} lakh)"
    return out


def add_display_amounts(obj: Any) -> Any:
    """Recursively pair every `*_minor` value with a `*_display` string."""
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            out[k] = add_display_amounts(v)
            if k.endswith("_minor") and isinstance(v, (int, float)):
                out[k.removesuffix("_minor") + "_display"] = format_inr(v)
        return out
    if isinstance(obj, list):
        return [add_display_amounts(x) for x in obj]
    return obj
