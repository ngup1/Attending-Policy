#!/usr/bin/env python3
"""Fetch every response the Bills & Votes demo needs into .cache/.

Run this before a demo. Afterwards the API serves everything from disk and
works with no network.

    .venv/bin/python prewarm.py            # fill the cache
    .venv/bin/python prewarm.py --refresh  # re-download the vote and member lists to pick up new votes
"""

import sys

import api


def main():
    if "--refresh" in sys.argv:
        # Only the list endpoints change over time; individual votes and bills don't.
        api.client.use_cache = False
        api.paged(f"/house-vote/{api.CONGRESS}", "houseRollCallVotes")
        api.paged(f"/member/congress/{api.CONGRESS}", "members", currentMember="false")
        api.client.use_cache = True

    votes = api.recent_votes()
    print(f"{len(votes)} bills in the recent list")
    for v in votes:
        detail = api.get_vote(v["congress"], v["session"], v["roll_call"])
        s = detail["bill"]["summary"]
        words = f"{s['word_count']} words" if s else "no summary"
        print(f"  {v['date'][:10]}  {v['bill']['label']:<14} {len(detail['members'])} members  {words}  {v['bill']['title'][:60]}")
    print(f"Done. {api.client.calls} new API calls this run.")


if __name__ == "__main__":
    main()
