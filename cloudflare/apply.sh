#!/usr/bin/env bash
# Apply UrbanMine's Cloudflare rules. Idempotent: each phase entry point is
# replaced, so running it twice leaves the same rules rather than stacking them.
#
#   export CF_API_TOKEN=...   # Zone.WAF Edit + Zone.Zone Read
#   export CF_ZONE_ID=...
#   ./cloudflare/apply.sh
#
# Needs: curl, python3. No jq.
set -euo pipefail

: "${CF_API_TOKEN:?set CF_API_TOKEN (Zone.WAF Edit)}"
: "${CF_ZONE_ID:?set CF_ZONE_ID (zone overview, right column)}"

here="$(cd "$(dirname "$0")" && pwd)"
base="https://api.cloudflare.com/client/v4/zones/${CF_ZONE_ID}/rulesets/phases"

apply() {
  local phase="$1" file="$2"
  printf '→ %s  (%s)\n' "$phase" "$file"
  curl -sS -X PUT "${base}/${phase}/entrypoint" \
    -H "Authorization: Bearer ${CF_API_TOKEN}" \
    -H "Content-Type: application/json" \
    --data-binary "@${here}/${file}" \
  | python3 -c '
import json, sys
r = json.load(sys.stdin)
if r.get("success"):
    rules = (r.get("result") or {}).get("rules") or []
    print(f"   ok — {len(rules)} rule(s) live")
else:
    print("   failed:")
    for e in r.get("errors") or [{"message": "no errors array"}]:
        print(f"     {e.get('code')}: {e.get('message')}")
    sys.exit(1)
'
}

apply http_request_firewall_custom custom-rules.json
apply http_ratelimit rate-limit.json

echo
echo "Check: Security → Events in the dashboard, or"
echo "  curl -sI https://<your-domain>/ | grep -i cf-ray"
