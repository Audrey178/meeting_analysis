"""Load the optional Stage-5 entity-alias dictionary with provenance."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def load_entity_aliases(
    path: str | Path | None,
    *,
    default_path: str | Path | None = None,
) -> tuple[dict[str, object] | None, dict[str, Any]]:
    """Return a decoded alias mapping and reproducible input provenance.

    An explicitly supplied path is required to exist. A missing default is an
    intentional optional-input absence and is represented in the provenance
    instead of silently disappearing from the run record.
    """

    is_explicit = path is not None
    selected = path if is_explicit else default_path
    source = (
        "explicit"
        if is_explicit
        else ("default" if selected is not None else "none")
    )

    if selected is None:
        return None, {
            "status": "absent",
            "source": source,
            "resolved_path": None,
            "content_sha256": None,
        }

    resolved = Path(selected).expanduser().resolve()
    if not resolved.is_file():
        if is_explicit:
            raise FileNotFoundError(
                f"--entity-aliases file does not exist or is not a file: {resolved}"
            )
        return None, {
            "status": "absent",
            "source": source,
            "resolved_path": str(resolved),
            "content_sha256": None,
        }

    raw = resolved.read_bytes()
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid entity alias JSON at {resolved}: {exc}") from exc
    if not isinstance(decoded, dict):
        raise ValueError(
            f"entity alias file must contain a JSON object: {resolved}"
        )

    return decoded, {
        "status": "loaded",
        "source": source,
        "resolved_path": str(resolved),
        "content_sha256": hashlib.sha256(raw).hexdigest(),
    }


__all__ = ["load_entity_aliases"]
