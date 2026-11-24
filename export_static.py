#!/usr/bin/env python3
"""Write the API's responses as static JSON for the GitHub Pages snapshot.

    .venv/bin/python prewarm.py         # make sure the cache is current
    .venv/bin/python export_static.py   # writes frontend/data/
    git add frontend/data && git commit && git push   # Pages redeploys on push to main

The frontend reads these files instead of /api when it is served from github.io
(or when the URL has ?static).
"""

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import api

OUT = Path(__file__).parent / "frontend" / "data"


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, separators=(",", ":")))


def main():
    shutil.rmtree(OUT, ignore_errors=True)
    listing = api.list_votes(q="", chamber="all")
    listing["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    write(OUT / "votes.json", listing)
    for v in listing["results"]:
        write(OUT / "votes" / f"{v['id']}.json", api.get_vote(v["congress"], v["session"], v["roll_call"]))
    size = sum(f.stat().st_size for f in OUT.rglob("*.json"))
    print(f"Wrote {len(listing['results'])} votes to {OUT} ({size / 1e6:.1f} MB). {api.client.calls} new API calls.")


if __name__ == "__main__":
    main()
