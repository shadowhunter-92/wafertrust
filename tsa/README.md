# Pinned FreeTSA certificate

`freetsa.pem` is the **TSA signing certificate** used to verify RFC 3161 tokens
from the free public timestamp service at `https://freetsa.org/tsr`.

- Source: https://freetsa.org/files/tsa.crt (fetched 2026-11-14)
- Subject: `OU=TSA, O=Free TSA, CN=www.freetsa.org` — "This certificate digitally
  signs documents and time stamp requests made using the freetsa.org online services"
- SHA-256 fingerprint: `32e841a95cc1164101ffde41298ef2fc75c1c4372ef095e88a6bbd47dfb191fc`
- Not after: 2040-02-02

The issuing Root CA (`https://freetsa.org/files/cacert.pem`, `OU=Root CA`) is a
separate certificate; `rfc3161ng` verifies the token signature against the TSA
signing certificate pinned here.

## Honest limits

- FreeTSA is a **free public service, not a qualified/audited timestamp authority**.
  A token proves a hash existed at a point in time per this TSA's clock; it is not
  legal-grade qualified time stamping (e.g. ETSI EN 319 421 / eIDAS).
- This is an independent **time anchor only** — not custody of the audit log and
  not a substitute for an independent witness in a separate trust domain.
- Tests and CI mock the TSA client; this certificate is only needed for live use.