"""Independently verify an exported WaferTrust flight recorder.

No simulator, no gateway, no private keys — just the exported files and the
public AgentBridge kernel:

    python verify_export.py audit          # or: maintenance
    python verify_export.py audit /path/to/exported/files
    python verify_export.py audit --operator-key HEX --witness-key HEX

Checks the hash chain from genesis, the Ed25519 checkpoint signature, that the
checkpoint matches the chain head, and that every call-journal record is bound
to a real audit entry. When a witness envelope is present it also verifies the
independent-witness anchor, and when a TSA token is present it verifies the
RFC 3161 time anchor (locally, no network).

Trust roots: pass --operator-key and --witness-key to pin the expected public
keys for genuinely independent verification. Without them the witness check
falls back to the keys carried in the export itself — that is self-consistency
only, not independent pinning, and a WARNING is printed. Exits 0 on PASS, 1 on FAIL.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_AGENTBRIDGE = os.path.join(os.path.dirname(_HERE), "agentbridge")
if _AGENTBRIDGE not in sys.path:
    sys.path.insert(0, _AGENTBRIDGE)

from src.governance import AuditLog  # noqa: E402
import anchor  # noqa: E402
from tsa import TsaClient, TSA_AVAILABLE, TsaError  # noqa: E402


def verify(stem: str, directory: str = _HERE, operator_key: str | None = None,
           witness_key: str | None = None) -> bool:
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

    # Independent-witness anchor (present on anchored exports). Pinned trust roots
    # make this independent verification; without them it is self-consistency only.
    wpath = os.path.join(directory, f"{stem}-witness.json")
    witness_ok = True
    if os.path.exists(wpath):
        with open(wpath, encoding="utf-8") as fh:
            witness = json.load(fh)
        pinned = operator_key is not None and witness_key is not None
        op_hex = operator_key if pinned else checkpoint["public_key_hex"]
        wit_hex = witness_key if pinned else anchor.witness_key_from_did(witness["witness_id"])
        if not pinned:
            print("  WARNING: self-consistency only — trust roots not independently pinned")
        try:
            res = anchor.verify_anchor(records, checkpoint, witness,
                                       operator_key_hex=op_hex, witness_key_hex=wit_hex)
            witness_ok = bool(res.get("verified", False))
            print(f"  independent witness verified: {witness_ok}")
        except Exception as exc:
            witness_ok = False
            print(f"  independent witness verified: False ({exc})")

    # Optional RFC 3161 time anchor. Verification is local cryptography (no network).
    tpath = os.path.join(directory, f"{stem}-tsa-token.der")
    tsa_ok = True
    if os.path.exists(tpath):
        cert_path = os.path.join(_HERE, "tsa", "freetsa.pem")
        if TSA_AVAILABLE and os.path.exists(cert_path):
            with open(tpath, "rb") as fh:
                token = fh.read()
            with open(cert_path, "rb") as fh:
                cert = fh.read()
            digest = anchor.checkpoint_digest(checkpoint).encode("utf-8")
            try:
                tsa_ok = TsaClient("https://freetsa.org/tsr", cert).verify(token, digest)
            except TsaError:
                tsa_ok = False
            print(f"  independently time-anchored (TSA): {tsa_ok}")
        else:
            tsa_ok = False
            print("  independently time-anchored (TSA): token present, not verifiable here "
                  "(rfc3161ng/cert missing)")
    else:
        print("  independently time-anchored (TSA): False (witness-only)")

    ok = chain_ok and sig_ok and head_ok and journal_ok and witness_ok and tsa_ok
    print(f"  RESULT: {'PASS' if ok else 'FAIL'}")
    return ok


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Independently verify an exported WaferTrust flight recorder.")
    parser.add_argument("stem", nargs="?", default="audit",
                        help="export stem, e.g. audit or maintenance (default: audit)")
    parser.add_argument("directory", nargs="?", default=_HERE,
                        help="directory holding the exported files (default: this folder)")
    parser.add_argument("--operator-key", dest="operator_key", default=None,
                        help="pinned operator public key hex (independent trust root)")
    parser.add_argument("--witness-key", dest="witness_key", default=None,
                        help="pinned witness public key hex (independent trust root)")
    args = parser.parse_args()
    sys.exit(0 if verify(args.stem, args.directory,
                         operator_key=args.operator_key, witness_key=args.witness_key) else 1)