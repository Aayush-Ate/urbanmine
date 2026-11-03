"""A per-client limit for the expensive route.

In memory and per instance on purpose: it stops one browser from queueing
twenty analyses, which is what a demo needs. A restart forgets the counts and
several instances each keep their own, so this is a speed bump, not a firewall.
The real ceiling for a launch is a shared store (Redis) or a gateway rule.
"""
import threading
import time


class SlidingWindow:
    """Allow `limit` calls per key inside `window_s` seconds."""

    def __init__(self, limit, window_s):
        self.limit = max(1, int(limit))
        self.window_s = float(window_s)
        self._hits = {}
        self._lock = threading.Lock()

    def allow(self, key):
        now = time.monotonic()
        with self._lock:
            hits = [t for t in self._hits.get(key, []) if now - t < self.window_s]
            allowed = len(hits) < self.limit
            if allowed:
                hits.append(now)
            self._hits[key] = hits
            # keys that went quiet are dropped, so the dict cannot grow forever
            if len(self._hits) > 2048:
                self._hits = {
                    k: v for k, v in self._hits.items()
                    if v and now - v[-1] < self.window_s
                }
            return allowed
