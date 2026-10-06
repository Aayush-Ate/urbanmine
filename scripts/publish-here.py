"""Publish UrbanMine dist/ to here.now (anonymous, 24h). Prints site + claim URLs."""
import json
import mimetypes
import os
from pathlib import Path
import sys
import urllib.request

DIST = str(Path(__file__).resolve().parent.parent / "frontend" / "dist")
BASE = "https://here.now"
CLIENT = {"X-HereNow-Client": "opencode/urbanmine-demo"}


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={**CLIENT, "content-type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def main():
    files, blobs = [], {}
    for root, _, names in os.walk(DIST):
        for n in names:
            full = os.path.join(root, n)
            rel = os.path.relpath(full, DIST).replace(os.sep, "/")
            with open(full, "rb") as f:
                blobs[rel] = f.read()
            ctype = mimetypes.guess_type(n)[0] or "application/octet-stream"
            if n.endswith(".html"):
                ctype = "text/html; charset=utf-8"
            files.append({"path": rel, "size": len(blobs[rel]), "contentType": ctype})
    print(f"uploading {len(files)} files: {[f['path'] for f in files]}", flush=True)

    update_slug = os.environ.get("UPDATE_SLUG", "")
    if update_slug:
        print(f"updating existing slug: {update_slug}", flush=True)
    try:
        if update_slug:
            created = call("PUT", f"/api/v1/publish/{update_slug}", {"files": files})
        else:
            created = call("POST", "/api/v1/publish", {"files": files})
    except urllib.error.HTTPError as e:
        print(f"UPDATE FAILED: http {e.code} — {e.read().decode()[:300]}")
        sys.exit(2)
    slug = created.get("slug") or created.get("site", {}).get("slug")
    uploads = created.get("uploads") or created.get("upload", {}).get("uploads") or []
    version_id = (
        created.get("versionId") or created.get("upload", {}).get("versionId")
        or (uploads[0].get("versionId") if uploads else None)
    )
    if not slug or not uploads:
        print("UNEXPECTED create response:", json.dumps(created)[:800])
        sys.exit(1)
    by_path = {u.get("path"): u for u in uploads}
    for f in files:
        u = by_path.get(f["path"]) or uploads[files.index(f)]
        url = u.get("url") or u.get("uploadUrl")
        req = urllib.request.Request(
            url, data=blobs[f["path"]], method="PUT",
            headers={"Content-Type": f["contentType"]},
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            r.read()
        print(f"  put {f['path']} -> {r.status}", flush=True)

    final = call("POST", f"/api/v1/publish/{slug}/finalize", {"versionId": version_id})
    print("SITE:", final.get("siteUrl") or final.get("url"))
    print("CLAIM:", final.get("claimUrl") or "(none)")
    print("FULL:", json.dumps(final)[:400])


if __name__ == "__main__":
    main()
