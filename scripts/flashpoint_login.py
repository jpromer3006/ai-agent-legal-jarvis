"""Sign in to Flashpoint.AI in the browser and save the token for JARVIS.

    python scripts/flashpoint_login.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.flashpoint import FlashpointClient, oauth_login  # noqa: E402

print("Opening your browser. Sign in with the account you used at app.flashpoint.ai …")
print(oauth_login())
fp = FlashpointClient()
r = fp.call("demographics", {"location": "11235"}, use_cache=False)
print("Test call:", "OK" if r.ok else "FAILED", r.source, r.text[:300])
