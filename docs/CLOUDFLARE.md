# Cloudflare in front of UrbanMine

The edge is a second line of defence, not the first. It stops scanners, caps the
expensive route, and challenges scripted writes. It cannot fix finding 9 in
[`SECURITY.md`](SECURITY.md) — the write routes still have no authentication, and
a rule that hides a route is not a login.

Two things are checked in with this document:

| File | What it is |
|---|---|
| `cloudflare/custom-rules.json` | 4 WAF custom rules, ready to PUT |
| `cloudflare/rate-limit.json` | 1 rate limiting rule for `/api/analyze` |
| `cloudflare/apply.sh` | applies both with the API |

## 0. The prerequisite nobody mentions

**Cloudflare can only proxy a domain you control.** `fullstackproject-app.vercel.app`
belongs to Vercel, so it cannot be added to your zone and there is no Cloudflare
WAF, rate limiting, or bot protection in front of it. Until a domain is pointed at
the deployment, `*.vercel.app` stays as it is and the only protection is what the
app does itself.

So step zero is a domain. Any registrar works; the free Cloudflare plan is enough
for everything below.

## 1. Domain, DNS, and one origin

Keep the shape the app already has: **one public origin**, with `/api/*` rewritten
to the backend by Vercel. That keeps CORS out of the picture and means the WAF
rules below only have one host to reason about.

```
urbanmine.example          → Vercel frontend (proxied through Cloudflare)
  /api/*                   → rewrite → backend alias (never public)
```

1. Add the site in Cloudflare, then change the registrar's nameservers.
2. In Vercel, add `urbanmine.example` to the `fullstackproject` project and follow
   the verification step. Vercel issues the certificate.
3. In Cloudflare DNS, create `CNAME urbanmine → cname.vercel-dns.com`, **Proxy
   status: Proxied** (orange cloud). Grey cloud means no WAF.
4. Optional but better: `api.urbanmine.example` as a second proxied CNAME to the
   backend alias, for direct debugging. If you do this, set
   `ALLOWED_ORIGINS=https://urbanmine.example` on the backend, because the browser
   will now be cross-origin.

Leave the `*.vercel.app` aliases working during the move; drop them afterwards.

Do **not** enable "Cache Everything" for this zone. The JSON API and `/uploads/*`
must not be cached at the edge, and a cache rule that swallows `/api/analyze`
would serve one user's detections to another.

## 2. TLS

SSL/TLS → Overview:

- **Full (strict)** — Vercel presents a valid certificate, so strict works.
- **Always Use HTTPS: On**
- **Minimum TLS Version: 1.2**
- **Opportunistic Encryption: Off**
- HSTS: enable, `max-age` 6 months to start, `includeSubDomains`, and only add
  `preload` once you are certain the domain stays. Cloudflare will not duplicate
  the HSTS header the backend already sends.

## 3. WAF custom rules (Free plan: 5, no regex)

`cloudflare/custom-rules.json` holds four rules. All of them use fields available
on the Free plan and avoid regex, which Free does not support.

| # | Rule | Expression | Action |
|---|---|---|---|
| 1 | Block `?debug=1` | `http.request.uri.query contains "debug=1"` | block |
| 2 | Hide API docs | `http.request.uri.path in {"/docs" "/redoc" "/openapi.json"}` | block |
| 3 | Challenge scripted writes | `http.request.method in {"PATCH" "DELETE"} and not http.user_agent contains "Mozilla/"` | managed_challenge |
| 4 | Block scanner paths | path contains `/.env`, `/.git`, `/wp-admin`, `/wp-login`, `/phpmyadmin`, `/actuator` | block |
| 5 | *(optional, free slot)* | `http.request.body.size gt 4500000` | block |

Rule 1 closes finding 11 without touching the code: `?debug=1` returns internal
detection state, and there is no reason for it to be reachable in production. The
Flutter/React client never sends it; a developer can still use it locally.

Rule 2 keeps FastAPI's Swagger UI off the public internet. If you need it, put
Cloudflare Access in front of the path instead (§6) rather than leaving it open.

Rule 3 is the closest thing to write protection the edge can offer while finding
9 is open: a curl loop gets challenged, a browser does not. It is a speed bump,
not authentication, and it will block legitimate scripted clients — that is the
trade.

Rule 5 is left out of the JSON because `http.request.body.size` is not available
on every plan. Add it in the dashboard if your zone accepts it; the app already
caps the read at 25MB, so this is only about saving origin work.

Apply from the repo:

```bash
export CF_API_TOKEN=...   # Zone → WAF → Edit, Zone → Zone Settings → Read
export CF_ZONE_ID=...
./cloudflare/apply.sh
```

Or paste the same expressions into Security → WAF → Custom rules.

## 4. Rate limiting (Free plan: 1 rule)

Free counts by client IP only, over 10s or 60s, and the expression may only use
the path. That is enough for the one route that costs model time.

`cloudflare/rate-limit.json`:

- expression `(http.request.uri.path eq "/api/analyze")`
- 30 requests per 60s per IP
- block for 60s, with a JSON 429 so the client sees the same shape as the app

This is the shared ceiling the in-memory `SlidingWindow` cannot provide: it
survives a Vercel restart and covers every instance, including all the cold
containers a spike would otherwise spin up. Keep the app-level limit too — it is
the one that still works when traffic does not go through Cloudflare.

If the API rejects `mitigation_timeout`, set the action to `managed_challenge`
or create the rule in the dashboard; Free behaves slightly differently through
the API than through the UI.

## 5. Managed protection on Free

- The **Cloudflare Free Managed Ruleset** is deployed automatically on Free zones.
  Leave it on.
- **Cloudflare Managed Ruleset** and **OWASP Core Ruleset** need Pro (~$25/mo
  per zone). Not required for the demo; worth it before real users.
- **Bot Fight Mode** (Security → Bots): turn it on. It challenges obvious bots
  and costs nothing. If you later see challenges on normal mobile traffic, use
  Super Bot Fight Mode's "likely automated → managed challenge" instead of
  blocking.

## 6. Protecting the docs and the demo data

Cloudflare Access (Zero Trust, free for up to 50 users) is the cheapest way to
put a login in front of paths that should not be public:

1. Zero Trust → Access → Applications → Add → Self-hosted.
2. Domain `urbanmine.example`, path `docs` (and `redoc`, `openapi.json`).
3. Policy: Allow → Emails → your address. One-time PIN, no IdP needed.

The same mechanism can gate the whole site before a demo (`policy: allow, emails:
you@…`) so random visitors cannot delete listings while finding 9 is open.

## 7. Frontend headers

`frontend/vercel.json` now sends, on every HTML/JS/CSS response:

- `Content-Security-Policy-Report-Only`
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy: geolocation=(self), camera=(self), microphone=()`
- `Cross-Origin-Opener-Policy: same-origin`
- `X-Frame-Options: DENY` (and `frame-ancestors 'none'` in the CSP)

The CSP is **report-only on purpose**. Cesium loads `Cesium.js` and its widget CSS
from jsDelivr, spawns workers from `blob:`, draws tiles from
`server.arcgisonline.com` and `*.cesium.com`, and the location picker calls HERE
and Nominatim. One missing origin white-screens the globe, and there is no way to
know which one from a build log.

To promote it:

1. Deploy, open the site with DevTools → Console, upload a photo, open the globe,
   pick a location.
2. Every blocked origin appears as a CSP violation. Add it to the matching
   directive.
3. When the console is quiet, rename the header to `Content-Security-Policy` in
   `frontend/vercel.json` and redeploy.

If Cesium reports an `eval` violation, add `'unsafe-eval'` to `script-src` — older
Cesium builds need it for shader compilation. That weakens the CSP, so self-hosting
Cesium (or SRI from jsDelivr) is the better fix, and it is still open in
`SECURITY.md`.

## 8. Not built here

**Turnstile on `/api/analyze`.** It is the right answer to "one script can burn my
model minutes", but it needs a site key, a widget in `App.jsx`, and a
`siteverify` call in the backend before the photo is read. That is a product
change, not a config change, so it is left as the next step. The rate limit and
the edge cap cover the demo.

## 9. Verify

```bash
# proxied? should answer through Cloudflare, with cf-ray headers
curl -sI https://urbanmine.example | grep -iE 'cf-ray|server|strict-transport'

# headers from Vercel
curl -sI https://urbanmine.example | grep -iE 'content-security-policy|x-content-type|referrer-policy|permissions-policy'

# rule 1: debug off the edge
curl -s -o /dev/null -w '%{http_code}\n' 'https://urbanmine.example/api/analyze?debug=1'   # 403

# rule 2: docs gone
curl -s -o /dev/null -w '%{http_code}\n' https://urbanmine.example/docs                    # 403

# rate limit: 31 uploads in a minute from one IP
for i in $(seq 31); do curl -s -o /dev/null -w '%{http_code} ' -X POST https://urbanmine.example/api/analyze -F file=@test.jpg; done; echo  # last ones 429
```

Then Security → Events: each of those should appear with the rule that stopped it.
If `cf-ray` is missing, the record is not proxied and none of this is running.

## 10. The origin is the weak point

The backend is still reachable at its own `*.vercel.app` alias, and the frontend
`vercel.json` publishes that alias as the rewrite target. Anyone who reads it can
call `https://backend-….vercel.app/docs` directly and skip every rule in §3 and
§4. Those rules protect the domain, not the service.

**Do not "fix" this by turning on Vercel Authentication for the backend project.**
The frontend rewrite is a server-to-server call with no Vercel cookie, so
authentication returns 401 for every user — the site breaks, not the attacker.

The safe sequence, in this order:

1. Deploy the backend at a hostname you control, proxied by Cloudflare
   (`api.urbanmine.example` → Vercel). The WAF then covers the real origin.
2. Change the frontend rewrite to that hostname and deploy. The alias still works
   while you check the site.
3. Only then delete the old alias (`vercel alias rm …`). Until this step the
   bypass exists; the edge limits it, it does not close it.

## 11. Still open

- **No authentication on write routes.** The edge challenge does not change this.
  This is the blocker in `SECURITY.md` before real users.
- **No SRI** on Cesium or the fonts.
- **One rate limit rule** on Free, so only `/api/analyze` is capped at the edge.
  `/api/listings` writes rely on the challenge and the app.
- **Free plan has no OWASP CRS, no regex, no custom log fields.** Pro is the next
  step if this goes past a demo.
