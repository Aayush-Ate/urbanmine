"""Publish dist/ several times, keep the nicest slug. Anonymous sites expire in 24h."""
import json
import mimetypes
import os
import sys
import urllib.request

DIST = "/Users/aayush/urbanmine/frontend/dist"
BASE = "https://here.now"
CLIENT = {"X-HereNow-Client": "opencode/urbanmine-demo"}
GOOD = ["urban", "mine", "demo", "reclaim", "build", "green", "city", "market",
        "works", "yards", "terra", "brick", "maker", "civic", "loop", "site"]


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={**CLIENT, "content-type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def score(slug):
    s = slug.lower()
    return sum(2 for w in GOOD[:4] if w in s) + sum(1 for w in GOOD[4:] if w in s)


def publish_once():
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
    created = call("POST", "/api/v1/publish", {"files": files})
    slug = created.get("slug") or created.get("site", {}).get("slug")
    uploads = created.get("uploads") or created.get("upload", {}).get("uploads") or []
    version_id = (
        created.get("versionId") or created.get("upload", {}).get("versionId")
        or (uploads[0].get("versionId") if uploads else None)
    )
    by_path = {u.get("path"): u for u in uploads}
    for f in files:
        u = by_path.get(f["path"]) or uploads[files.index(f)]
        req = urllib.request.Request(
            u.get("url"), data=blobs[f["path"]], method="PUT",
            headers={"Content-Type": f["contentType"]},
        )
        with urllib.request.urlopen(req, timeout=120):
            pass
    final = call("POST", f"/api/v1/publish/{slug}/finalize", {"versionId": version_id})
    return final.get("siteUrl"), slug


def main():
    tried = []
    for i in range(6):
        try:
            url, slug = publish_once()
        except Exception as e:
            print(f"attempt {i + 1} failed: {str(e)[:120]}", flush=True)
            continue
        sc = score(slug)
        tried.append((sc, slug, url))
        print(f"attempt {i + 1}: {url} (score {sc})", flush=True)
        if sc >= 3:
            break
    tried.sort(reverse=True)
    print("BEST:", tried[0][2] if tried else None)
    print("ALL:", [t[1] for t in tried])


if __name__ == "__main__":
    main()
