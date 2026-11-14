"""Independent-witness anchoring over the kernel's external_anchor protocol.

A local signed checkpoint is not an externally anchored checkpoint. This wraps
the kernel's two-party witness envelope: an independent witness key signs a hash
of the whole checkpoint, and verify_anchored_audit detects truncation/fork/rollback.

Honesty: an offline witness on the same host proves the two-party protocol but is
NOT independent custody. Genuine independence requires a separate trust domain
(e.g. the optional TSA time anchor in tsa.py, or an external witness service).
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_AGENTBRIDGE = os.path.join(os.path.dirname(_HERE), "agentbridge")
if _AGENTBRIDGE not in sys.path:
    sys.path.insert(0, _AGENTBRIDGE)

from src.governance import AgentIdentity  # noqa: E402
from src.governance.external_anchor import (  # noqa: E402
    create_witness_statement, verify_anchored_audit, checkpoint_digest,
)

_DID_PREFIX = "did:key:ed25519:"


def witness_key_from_did(witness_id: str) -> str:
    if not witness_id.startswith(_DID_PREFIX):
        raise ValueError("witness_id is not an ed25519 did:key")
    return witness_id[len(_DID_PREFIX):]


def create_witness(checkpoint: dict, witness_identity: AgentIdentity, *,
                   anchor_reference: str) -> dict:
    return create_witness_statement(
        checkpoint, witness_id=witness_identity.did,
        witnessed_at=datetime.now(timezone.utc).isoformat(),
        anchor_reference=anchor_reference, sign=witness_identity.sign)


def verify_anchor(records, checkpoint, witness, *, operator_key_hex,
                  witness_key_hex) -> dict:
    return verify_anchored_audit(records, checkpoint, witness,
                                 checkpoint_key_hex=operator_key_hex,
                                 witness_key_hex=witness_key_hex)