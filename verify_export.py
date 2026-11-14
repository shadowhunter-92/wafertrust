"""Independently verify an exported WaferTrust flight recorder.

No simulator, no gateway, no private keys — just the exported files and the
public AgentBridge kernel:

    python verify_export.py audit          # or: maintenance
    python verify_export.py audit /path/to/exported/files

Checks the hash chain from genesis, the Ed25519 checkpoint signature, that the
checkpoint matches the chain head, and that every call-journal record is bound
to a real audit entry. Exits 0 on PASS, 1 on FAIL.
"""

from __future__ import annotations

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_AGENTBRIDGE = os.path.join(os.path.dirname(_HERE), "agentbridge")
if _AGENTBRIDGE not in sys.path:
    sys.path.insert(0, _AGENTBRIDGE)

from src.governance import AuditLog  # noqa: E402


def verify(stem: str, directory: str = _HERE) -> bool:
    with open(os.path.join(directory, f"{stem}-flight-recorder.jsonl"), encoding="utf-8") as fh:
        records = [json.loads(line) for line in fh if line.strip()]
    with open(os.path.join(directory, f"{stem}-checkpoint.json"), encoding="utf-8") as fh:
        checkpoint = json.load(fh)
    with open(os.path.join(directory, f"{stem}-call-journal.jsonl"), encoding="utf-8") as fh:
        journal = [json.loads(line) for line in fh if line.strip()]

    chain_ok = AuditLog.verify_chain(records, require_genesis=True)
    print(f"  hash chain from genesis ({len(records)} entries): {chain_ok}")
    sig_ok = AuditLog.verify_checkpoint(checkpoint)
    print(f"  checkpoint Ed25519 signature: {sig_ok}")
    head_ok = (bool(records)
               and checkpoint["head_hash"] == records[-1]["entry_hash"]
               and checkpoint["seq"] == len(records))
    print(f"  checkpoint matches chain head: {head_ok}")
    by_seq = {r["seq"]: r["entry_hash"] for r in records}
    journal_ok = all(j["seq"] in by_seq and by_seq[j["seq"]] == j["entry_hash"]
                     for j in journal)
    print(f"  journal bound to chain ({len(journal)} calls): {journal_ok}")
    ok = chain_ok and sig_ok and head_ok and journal_ok
    print(f"  RESULT: {'PASS' if ok else 'FAIL'}")
    return ok


if __name__ == "__main__":
    stem = sys.argv[1] if len(sys.argv) > 1 else "audit"
    directory = sys.argv[2] if len(sys.argv) > 2 else _HERE
    sys.exit(0 if verify(stem, directory) else 1)