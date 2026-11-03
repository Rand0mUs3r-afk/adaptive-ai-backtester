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

The connector uses `https://api.onclickmedia.com/options/`, not the API root.
The uploaded GitHub diagnostic confirmed the API root returned HTTP 404. A
separate live check of `/options/` with the same SPY/2024-12-31 parameters reached
the service but returned HTTP 403 with a date-plan-range error. This verifies the
route correction, **not** historical access, usable quotes, or complete coverage.
The JSON-v1 quote schema is still strictly validated; no error response is treated
as market data. The provider's exact recognized plan-range message is recorded
as `provider_error_code: outside_plan_data_range`; other response bodies are never
logged. No guessed authentication, access bypass, or fallback pricing is added.

If this code is returned by GitHub, verify date entitlements with the provider
before rerunning. Keep the requested historical window fixed rather than silently
selecting a different period. Website access is not proof of API entitlement.

When historical access is verified, run the existing **Options backtest - EOD
quotes ($2,000)** workflow with the same historical inputs. No new secrets are
required by this diagnostic patch.
Trading rules, allocation, watchlist, and quote-price accounting are unchanged.
Offline transport fixtures test software behavior, not provider coverage or
strategy profitability.

## Patch verification

`python -m unittest -q`: 49 tests passed locally, including HTTP/access failures,
JSON/schema rejection, transient retries, diagnostic redaction, and CLI artifact
persistence after a failed preflight. These are offline software checks.

A separate unauthenticated public probe for SPY on 2025-01-02 returned HTTP 404
from the old API-root route (before the correction below). This was environment-specific;
it does not establish the response GitHub Actions will receive. Provider access
is not restored or certified by this patch.

## Route correction verification

`python -m unittest -q`: 51 tests passed locally after the route correction,
including URL/query assertions, plan-range classification/redaction, and
non-JSON HTTP error handling. A public `/options/` probe for SPY/2024-12-31
returned HTTP 403 with `Requested date is outside your plan's data range`.
The upload establishes GitHub's old-root 404; the new-route 403 is a separate
environment-specific observation. Do not claim provider access is restored.
