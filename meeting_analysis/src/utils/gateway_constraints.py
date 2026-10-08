"""Structured Outputs gateway constraints measured against the meeting-
analysis LLM gateway (plan_stage_7_8.md §2.7). These are NOT general JSON
Schema advice -- they are specific, measured failure modes of this
project's structured-generation path, and the constants here exist so a
schema-building test can assert against them by name instead of a magic
string re-typed at each call site.

Measured on transcript "bien-ban-vdt-trang-v1":
  - TOPIC_SEG_000005: a string property WITH ``maxLength`` made the
    gateway's guided decoder cut a token mid-character, emitting "Thành phố
    Hồ志明" and then newlines until a 45s timeout. The identical request
    WITHOUT ``maxLength`` answered in 1.4s. Segment 1's "quốc际" is the same
    corruption surviving into a response that happened to terminate.
  - TOPIC_SEG_000009: a ``{"type": "number"}`` property made the guided
    decoder emit digits without terminating on some inputs -- 0.9s without
    the property, 90s with it (bounding via minimum/maximum/multipleOf
    included in that measurement).

Only ``maxLength`` and the bare numeric ``type`` were measured directly;
``minLength``/``pattern`` and ``minimum``/``maximum``/``multipleOf`` are
included as a precaution against the SAME guided-decoder-cutting-mid-token
mechanism, not as independently measured failures -- see the TIP-008
completion report's DEVIATIONS.

Practical rule: enforce length/range limits in Python AFTER generation
(truncate, validate, reject), never as maxLength/minLength/pattern/minimum/
maximum/multipleOf in a Structured Outputs JSON Schema sent to this gateway,
and never declare a numeric-typed property in such a schema.
"""

from __future__ import annotations

FORBIDDEN_STRING_SCHEMA_KEYS = frozenset({"maxLength", "minLength", "pattern"})
FORBIDDEN_NUMERIC_SCHEMA_KEYS = frozenset({"minimum", "maximum", "multipleOf"})
FORBIDDEN_NUMERIC_TYPES = frozenset({"number", "integer"})

__all__ = [
    "FORBIDDEN_NUMERIC_SCHEMA_KEYS",
    "FORBIDDEN_NUMERIC_TYPES",
    "FORBIDDEN_STRING_SCHEMA_KEYS",
]
