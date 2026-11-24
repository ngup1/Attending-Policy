"""Backend for the Bills & Votes page (House roll-call votes, 119th Congress).

Run:
    .venv/bin/uvicorn api:app --reload --port 8000
    then open http://localhost:8000

Every Congress.gov response is cached in .cache/ by CongressClient, so once
prewarm.py has run, the API works offline.

Endpoints:
    GET /api/votes?q=&chamber=house     recent final-passage votes on bills (left list)
    GET /api/votes/{congress}/{session}/{roll}   one vote: bill, summary, totals, every member
"""

import html
import re
from functools import lru_cache

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from congress_demo import ApiError, CongressClient, load_api_key

CONGRESS = 119
RECENT_LIMIT = 25  # bills shown in the "Recent floor votes" list
PREVIEW_WORDS = 50  # summaries longer than this get a "view more" toggle

# Bill types that make law. Simple resolutions (HRES) are mostly rules for
# debate, so they are left out of the demo list.
BILL_LABELS = {"HR": "H.R.", "S": "S.", "HJRES": "H.J.Res.", "SJRES": "S.J.Res."}

# Final-passage questions, as opposed to procedural ones (recommit, table, rules).
PASSAGE_RE = re.compile(r"\bpass|concur|conference report|senate amendment|objections of the president", re.I)
PROCEDURAL_RE = re.compile(r"recommit|table|previous question", re.I)

VOTE_NAMES = {"Yea": "Yea", "Aye": "Yea", "Nay": "Nay", "No": "Nay", "Present": "Present", "Not Voting": "Not voting"}

client = CongressClient(load_api_key())


# --- Data loading -----------------------------------------------------------


def paged(path, key, **params):
    """Fetch every page of a list endpoint."""
    items, offset = [], 0
    while True:
        data = client.get(path, limit=250, offset=offset, **params)
        items += data.get(key, [])
        if not (data.get("pagination") or {}).get("next"):
            return items
        offset += 250


@lru_cache(maxsize=1)
def member_index():
    """bioguide ID -> member info, for district and photo (vote data has neither)."""
    return {m["bioguideId"]: m for m in paged(f"/member/congress/{CONGRESS}", "members", currentMember="false")}


@lru_cache(maxsize=1)
def recent_votes():
    """The latest final-passage vote for each of the most recently voted bills."""
    votes = paged(f"/house-vote/{CONGRESS}", "houseRollCallVotes")
    votes = [v for v in votes if v.get("legislationType") in BILL_LABELS]
    votes.sort(key=lambda v: v["startDate"], reverse=True)

    picked, seen = [], set()
    for v in votes:
        bill_key = (v["legislationType"], v["legislationNumber"])
        if bill_key in seen:
            continue
        detail = vote_detail(CONGRESS, v["sessionNumber"], v["rollCallNumber"])
        question = detail.get("voteQuestion") or ""
        if not PASSAGE_RE.search(question) or PROCEDURAL_RE.search(question):
            continue
        seen.add(bill_key)
        picked.append(vote_summary(detail))
        if len(picked) >= RECENT_LIMIT:
            break
    return picked


def vote_detail(congress, session, roll):
    return client.get(f"/house-vote/{congress}/{session}/{roll}")["houseRollCallVote"]


def bill_detail(congress, bill_type, number):
    return client.get(f"/bill/{congress}/{bill_type.lower()}/{number}")["bill"]


# --- Shaping ----------------------------------------------------------------


def totals(detail):
    t = {"yea": 0, "nay": 0, "present": 0, "not_voting": 0}
    for p in detail.get("votePartyTotal", []):
        t["yea"] += p.get("yeaTotal", 0)
        t["nay"] += p.get("nayTotal", 0)
        t["present"] += p.get("presentTotal", 0)
        t["not_voting"] += p.get("notVotingTotal", 0)
    return t


def vote_summary(detail):
    """The fields shown in the left-hand list."""
    bill_type, number = detail["legislationType"], detail["legislationNumber"]
    bill = bill_detail(detail["congress"], bill_type, number)
    return {
        "id": f"{detail['congress']}-{detail['sessionNumber']}-{detail['rollCallNumber']}",
        "congress": detail["congress"],
        "session": detail["sessionNumber"],
        "roll_call": detail["rollCallNumber"],
        "chamber": "House",
        "date": detail["startDate"],
        "question": detail.get("voteQuestion"),
        "result": detail.get("result"),
        "totals": totals(detail),
        "bill": {
            "id": f"{detail['congress']}-{bill_type.lower()}-{number}",
            "label": f"{BILL_LABELS.get(bill_type, bill_type)} {number}",
            "title": bill.get("title"),
            "policy_area": (bill.get("policyArea") or {}).get("name"),
        },
    }


def clean_summary(raw):
    """Turn CRS summary HTML into paragraphs, dropping the leading bold title line."""
    raw = re.sub(r"^\s*<p>\s*<strong>.*?</strong>\s*</p>", "", raw or "", flags=re.S)
    raw = re.sub(r"<li[^>]*>", "\n• ", raw)
    raw = re.sub(r"</(p|li|ul|ol|h\d)>|<br\s*/?>", "\n", raw)
    text = html.unescape(re.sub(r"<[^>]+>", "", raw)).replace("\xa0", " ")
    return [p for p in (re.sub(r"\s+", " ", line).strip() for line in text.split("\n")) if p]


def summary_for(congress, bill_type, number, vote_date):
    """The CRS summary version closest to (not after) the vote, else the latest one."""
    summaries = client.get(f"/bill/{congress}/{bill_type.lower()}/{number}/summaries").get("summaries", [])
    if not summaries:
        return None
    summaries.sort(key=lambda s: s.get("actionDate", ""))
    before = [s for s in summaries if s.get("actionDate", "") <= vote_date[:10]]
    chosen = (before or summaries)[-1]

    paragraphs = clean_summary(chosen.get("text"))
    words = " ".join(paragraphs).split()
    truncated = len(words) > PREVIEW_WORDS
    return {
        "paragraphs": paragraphs,
        "preview": " ".join(words[:PREVIEW_WORDS]) + ("…" if truncated else ""),
        "word_count": len(words),
        "truncated": truncated,
        "version": chosen.get("actionDesc"),
        "version_date": chosen.get("actionDate"),
        "source": "Congressional Research Service",
    }


def bill_status(bill, vote_result):
    if bill.get("laws"):
        return "Became law"
    action = ((bill.get("latestAction") or {}).get("text") or "").lower()
    if "vetoed" in action:
        return "Vetoed"
    if "presented to president" in action or "cleared for white house" in action:
        return "Sent to President"
    if "passed senate" in action or "passed/agreed to in senate" in action:
        return "Passed Senate"
    return "Passed House" if vote_result == "Passed" else "Failed in House"


def member_row(r, members):
    info = members.get(r["bioguideID"], {})
    return {
        "bioguide_id": r["bioguideID"],
        "name": f"{r['firstName']} {r['lastName']}",
        "first_name": r["firstName"],
        "last_name": r["lastName"],
        "party": r["voteParty"],
        "state": r["voteState"],
        "district": info.get("district"),
        "vote": VOTE_NAMES.get(r["voteCast"], r["voteCast"]),
        "photo_url": (info.get("depiction") or {}).get("imageUrl"),
    }


# --- API --------------------------------------------------------------------

app = FastAPI(title="Attending Policy API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])


def upstream(fn, *args):
    try:
        return fn(*args)
    except ApiError as e:
        if str(e).startswith("HTTP 404"):
            raise HTTPException(status_code=404, detail="Not found")
        raise HTTPException(status_code=502, detail=f"Congress.gov: {e}")
    except KeyError:
        raise HTTPException(status_code=404, detail="Not found")


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/votes")
def list_votes(q: str = "", chamber: str = Query("all", pattern="^(all|house|senate)$")):
    if chamber == "senate":
        return {"results": [], "count": 0, "note": "Senate roll-call votes are not in the Congress.gov API yet."}
    results = upstream(recent_votes)
    if q:
        needle = q.lower().replace(".", "").replace(" ", "")
        results = [
            v for v in results
            if needle in v["bill"]["label"].lower().replace(".", "").replace(" ", "")
            or q.lower() in (v["bill"]["title"] or "").lower()
            or q.lower() in (v["bill"]["policy_area"] or "").lower()
        ]
    return {"results": results, "count": len(results)}


@app.get("/api/votes/{congress}/{session}/{roll}")
def get_vote(congress: int, session: int, roll: int):
    def build():
        detail = vote_detail(congress, session, roll)
        if detail.get("legislationType") not in BILL_LABELS:
            raise HTTPException(status_code=404, detail="This roll call is not a vote on a bill")
        out = vote_summary(detail)
        bill_type, number = detail["legislationType"], detail["legislationNumber"]
        bill = bill_detail(congress, bill_type, number)
        out["bill"].update({
            "status": bill_status(bill, detail.get("result")),
            "latest_action": bill.get("latestAction"),
            "url": detail.get("legislationUrl"),
            "summary": summary_for(congress, bill_type, number, detail["startDate"]),
        })
        out["source_url"] = detail.get("sourceDataURL")
        out["party_totals"] = [
            {
                "party": p["voteParty"],
                "name": (p.get("party") or {}).get("name"),
                "yea": p.get("yeaTotal", 0),
                "nay": p.get("nayTotal", 0),
                "present": p.get("presentTotal", 0),
                "not_voting": p.get("notVotingTotal", 0),
            }
            for p in detail.get("votePartyTotal", [])
            if sum(p.get(k, 0) for k in ("yeaTotal", "nayTotal", "presentTotal", "notVotingTotal"))
        ]
        rows = client.get(f"/house-vote/{congress}/{session}/{roll}/members")["houseRollCallVoteMemberVotes"]["results"]
        members = member_index()
        out["members"] = sorted((member_row(r, members) for r in rows), key=lambda m: (m["last_name"], m["first_name"]))
        return out

    return upstream(build)


# The frontend, served at / (mounted last so /api routes win).
app.mount("/", StaticFiles(directory=Path(__file__).parent / "frontend", html=True), name="frontend")
