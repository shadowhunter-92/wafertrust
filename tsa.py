"""Optional RFC 3161 time anchor over a remote TSA (e.g. FreeTSA).

This is an independent TIME anchor only: a TSA signs a hash of the checkpoint
digest, proving the checkpoint existed at a point in time. It is not custody of
the audit log and not a qualified/audited CA. FreeTSA is a free public service,
not a qualified timestamp authority. Network is touched only when timestamp() is
explicitly called; tests and CI mock RemoteTimestamper, so no network is needed.

rfc3161ng is an optional dependency. When absent, TSA_AVAILABLE is False and
TsaClient raises TsaError; the gateway/verifier degrade to witness-only anchoring.
"""

from __future__ import annotations

try:
    from rfc3161ng import RemoteTimestamper
    TSA_AVAILABLE = True
except ImportError:  # optional dependency
    RemoteTimestamper = None
    TSA_AVAILABLE = False


class TsaError(Exception):
    pass


class TsaClient:
    def __init__(self, url: str, certificate_pem: bytes, hashname: str = "sha256"):
        if not TSA_AVAILABLE:
            raise TsaError("rfc3161ng not installed; TSA anchoring unavailable")
        self.url = url
        self._rt = RemoteTimestamper(url, certificate=certificate_pem, hashname=hashname)

    def timestamp(self, data: bytes) -> bytes:
        """Return the DER-encoded RFC 3161 token over `data` (a digest blob)."""
        try:
            return self._rt.timestamp(data=data)
        except Exception as exc:
            raise TsaError(f"timestamp request failed: {exc}") from exc

    def verify(self, token: bytes, data: bytes) -> bool:
        try:
            return bool(self._rt.check(token, data=data))
        except Exception:
            return False