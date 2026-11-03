# Options connection diagnostics

The EOD workflow now checks sampled historical options chains before simulating
trades: the prior stock session, first test session, and final test session for
each resolved ticker. A passed preflight is **not** a full coverage certificate.
The simulator still requires the selected/held contract on every needed date and
refuses stale marks, trade-bar fallbacks, and midpoint substitutions.

Every run writes these artifacts, including when options access fails:

- `options_request_diagnostics.json`: ticker/date, attempt, HTTP status, safe
  content type, and error category. No response bodies, credentials, or raw
  exception messages are logged.
- `options_preflight.json`: passed, failed, and not-checked sampled dates.
- `quote_provenance.json`: normalized successful snapshot counts and hashes.

401/403 means authentication/access must be checked; 404 means the configured
route was not found; 429 means rate limiting. Transient HTTP/network failures
receive at most three attempts with backoff. Permanent HTTP failures stop at once.
The client explicitly requests JSON and identifies the research application.

This patch does not claim to restore provider service or invent a replacement
endpoint or authentication scheme. The existing OnclickMedia URL/schema remains
unchanged until a supported replacement can be verified. If the provider denies
access or has retired that route, the run will stop with actionable diagnostics
instead of manufacturing a performance result. Verify the provider's current
supported access method before changing the endpoint or adding authentication.

Run the existing **Options backtest - EOD quotes ($2,000)** workflow with the same
historical inputs. No new secrets are required by this diagnostic patch.
Trading rules, allocation, watchlist, and quote-price accounting are unchanged.
Offline transport fixtures test software behavior, not provider coverage or
strategy profitability.

## Patch verification

`python -m unittest -q`: 49 tests passed locally, including HTTP/access failures,
JSON/schema rejection, transient retries, diagnostic redaction, and CLI artifact
persistence after a failed preflight. These are offline software checks.

A separate unauthenticated public probe for SPY on 2025-01-02 returned HTTP 404
from the currently configured route. This observation is environment-specific;
it does not establish the response GitHub Actions will receive. Provider access
is not restored or certified by this patch.
