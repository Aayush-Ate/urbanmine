# Security note

A review of the HTTP surface, the request shapes, the file handling and the
client, done 3 November 2026 against `main`. It lists what was wrong, what was
changed, and what is knowingly still open. Nothing here is a substitute for an
independent audit before real users put real money through it.

## Method

1. Read every route in `backend/app/main.py` and every shape in `schemas.py`.
2. Followed each user-controlled string to where it is used: a filename, a
   filesystem unlink, a price, a coordinate, a stored URL.
3. Checked what is tracked in git (secrets), and what the browser is allowed to
   load.
4. Pinned each fix with a test in `backend/tests/test_security.py`, so a later
   change that reopens one fails the suite.

## Findings

| # | Severity | Finding | Status |
|---|---|---|---|
| 1 | High | CORS was `allow_origins=["*"]` **with** `allow_credentials=True`. That combination is rejected by browsers and, where it is accepted, lets any site call the API with the user's cookies. | **Fixed** |
| 2 | High | `image_url` / `thumb_url` were free-form strings. `DELETE /api/listings/{id}` took the last path segment of that string and passed it to an unlink, so a caller could aim a filesystem path from JSON. | **Fixed** |
| 3 | Medium | `await file.read()` buffered the entire request body before the 25MB check, so the limit was on memory after the fact, not on the read. | **Fixed** |
| 4 | Medium | No limit on `/api/analyze`, the one route that costs model time or money. One browser could queue dozens. | **Fixed** |
| 5 | Medium | No security headers: an upload opened directly by a browser could be MIME-sniffed, the API could be framed. | **Fixed** |
| 6 | Medium | Request validation was loose: negative quantity, negative price, latitude 500, any string as a condition, any string as a request status. | **Fixed** |
| 7 | Low | `bbox` could be inverted or outside the frame; the browser crops listing photos with those numbers, so the wrong object was shown. | **Fixed** |
| 8 | Low | An oversized/invalid upload returned 200 with an `error` field rather than 4xx. | **Kept** — the UI reads the field, and the test suite pins the shape; changing it would break the client contract for no security gain. |
| 9 | High | `DELETE /api/listings/{id}` and `PATCH` on listings and requests have **no authentication**. Anyone who can reach the URL can delete inventory. | **Open, accepted for the demo** |
| 10 | Medium | Third-party scripts load without integrity hashes: Cesium from jsDelivr, fonts from Google Fonts. A compromised CDN could run code in the page. | **Open** |
| 11 | Low | `?debug=1` on analyze returns internal detection state. No secrets, but it is an unbounded surface. | **Open** |
| 12 | Info | Dependency ranges are `>=`, not pinned, so builds pick up new releases unreviewed. | **Open** |

## What changed

**CORS (`backend/app/main.py`).** Credentials off, methods and headers pinned to
what the app uses, `ALLOWED_ORIGINS` now configurable. Default stays `*` because
a phone on the LAN and a Cloudflare tunnel are real demo paths; set it to the
frontend origin when the backend is public.

**Uploads (`backend/app/main.py`).** The declared content type is checked against
`{image/jpeg, image/png, image/webp}` *before* the body is read, the read is
capped at `MAX_UPLOAD_BYTES + 1`, and Pillow still verifies the bytes are a real
image. Limits: `MAX_UPLOAD_MB` (default 25), `ANALYZE_PER_MINUTE` (default 20).

**Rate limit (`backend/app/core/ratelimit.py`).** A small in-memory sliding
window, per client, 20 analyses a minute. It is a speed bump on one instance, not
a firewall: a restart forgets the counts, and two instances count separately.

**Request shapes (`backend/app/schemas.py`).** Quantity, price, latitude,
longitude, string lengths and ratios are bounded; condition, listing status and
request status are closed sets; `image_url` and `thumb_url` must match
`^/uploads/[A-Za-z0-9]{1,40}\.jpg$`; a bbox must be four numbers inside the frame
with positive area or it becomes `None`.

**File handling (`backend/app/storage/store.py`).** `delete_image()` re-checks the
name it is given (no separators, no leading dot) instead of trusting its caller.
Two locks, because one of them is the one that runs.

**Headers (`backend/app/main.py`).** `X-Content-Type-Options: nosniff`,
`Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`, a narrow
`Permissions-Policy`, and HSTS only when the request actually arrived over TLS.

## Verified in this review

- Only `backend/.env.example` and `frontend/.env.example` are tracked; the real
  `.env` files are ignored (`git check-ignore` confirms). No key is in git.
- The frontend has no `dangerouslySetInnerHTML`, no `eval`, and stores no token
  in `localStorage`. User text is rendered through React, which escapes it.
- Photos are generated names only (`uuid4().hex[:10] + ".jpg"`); a request can
  never choose one.
- Every fix above has a test; the suite is 76 tests and runs without network or
  model downloads.

## Not verified here

- `pip-audit` / `npm audit` against live advisory databases: not run in this
  pass, so the dependency claim is "ranges are unpinned", not "no known CVEs".
- Penetration testing, or anything against the deployed instance.
- Multi-instance behaviour: the rate limit and the JSONB store are both
  single-writer designs and are documented as such, not tested under load.

## Before a real launch

1. **Authentication.** Sessions or signed tokens on the write routes; listings
   owned by the contractor who created them. This is the blocker.
2. **Shared rate limiting.** Redis (or the host's gateway) so the limit survives
   a restart and covers every instance.
3. **SRI or self-hosting** for Cesium and the fonts; a Content-Security-Policy on
   the frontend.
4. **Pinned dependencies** and an audit in CI.
5. **Object storage** for photos with signed URLs once volume grows, so the API
   is not the image server.
6. **Real tables** before more than one writer exists — a data-integrity issue
   that becomes a security issue the moment two contractors share a site.
