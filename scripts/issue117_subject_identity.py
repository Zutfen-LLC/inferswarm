#!/usr/bin/env python3
"""Issue #117 qualification-subject identity convention.

This module owns the Issue #117 projection from a complete candidate subject
to the execution-equality subject used by the qualification gate. It is not
part of Issue #99 artifact acquisition provenance.
"""
from __future__ import annotations

import hashlib
from typing import Any, Mapping, Sequence

from issue74_methodology import canonical_json_bytes


#: Content identity is enforced by the source catalog, plan, and manifest.
#: Accepted V5 evidence does not retain this #117 machinery-local value.
MACHINERY_LOCAL_SUBJECT_KEYS = ("catalog_content_digest",)


def execution_equality_subject(
        subject: Mapping[str, Any], *,
        machinery_local_subject_keys: Sequence[str] =
        MACHINERY_LOCAL_SUBJECT_KEYS,
) -> dict[str, Any]:
    """Return the execution-equality projection of an Issue #117 subject."""
    local = set(machinery_local_subject_keys)
    return {key: value for key, value in subject.items() if key not in local}


def subject_digest(
        subject: Mapping[str, Any], *,
        machinery_local_subject_keys: Sequence[str] =
        MACHINERY_LOCAL_SUBJECT_KEYS,
) -> str:
    """Return the SHA-256 digest of the execution-equality subject."""
    payload = canonical_json_bytes(execution_equality_subject(
        subject, machinery_local_subject_keys=machinery_local_subject_keys))
    return "sha256:" + hashlib.sha256(payload).hexdigest()
