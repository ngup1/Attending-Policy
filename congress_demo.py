#!/usr/bin/env python3
"""Demo of the Congress.gov API's legislation, people, and vote endpoints.

Calls every list, detail, and sub-endpoint for bills, laws, amendments,
summaries, treaties, members, House roll call votes, nominations, and
congresses, and prints each response as a readable summary.

Usage:
    # Put CONGRESS_API_KEY=... in .env (or export it). Free key: https://api.congress.gov/sign-up/
    python3 congress_demo.py               # run every section
    python3 congress_demo.py bill member   # run selected sections
    python3 congress_demo.py --raw vote    # also dump the raw JSON
    python3 congress_demo.py --list        # show section names

Responses are cached in .cache/ so re-running a demo is instant and does not
use up the hourly rate limit. Pass --refresh to ignore the cache.
"""

import argparse
import hashlib
import html
import json
import os
import re
import ssl
import sys
import textwrap
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE_URL = "https://api.congress.gov/v3"
CACHE_DIR = Path(__file__).parent / ".cache"
WIDTH = 100

# Example records used for the detail and sub-endpoint calls. Edit these to
# demo something else.
EXAMPLES = {
    "bill": ("118", "hr", "2882"),  # Further Consolidated Appropriations Act, 2024
    "law": ("118", "pub", "47"),  # Public Law 118-47 (the same bill)
    "amendment": ("117", "samdt", "2137"),
    "summaries": ("118", "hr"),
    "treaty": ("117", "3"),
    "partitioned_treaty": ("114", "13", "A"),
    "member": "P000197",  # Nancy Pelosi
    "state_district": ("CA", "11"),
    "member_congress": "118",
    "vote_congress_session": ("118", "1"),
    "nomination": ("117", "1064"),
    "congress": "118",
}


def load_api_key():
    """Read CONGRESS_API_KEY from the environment, then from .env (name is case-insensitive)."""
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[len("export "):]
            name, sep, value = line.partition("=")
            if sep and name.strip().upper() == "CONGRESS_API_KEY" and not line.startswith("#"):
                os.environ.setdefault("CONGRESS_API_KEY", value.strip().strip("'\""))
    return os.environ.get("CONGRESS_API_KEY")


def ssl_context():
    # python.org builds on macOS ship without root certificates; use certifi's if available.
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


class ApiError(Exception):
    pass


class CongressClient:
    def __init__(self, api_key, use_cache=True):
        self.api_key = api_key
        self.use_cache = use_cache
        self.calls = 0
        self.ssl_context = ssl_context()

    def get(self, path, **params):
        params = {"format": "json", **params}
        query = urllib.parse.urlencode(sorted(params.items()))
        cache_file = CACHE_DIR / (hashlib.sha1(f"{path}?{query}".encode()).hexdigest() + ".json")
        if self.use_cache and cache_file.exists():
            return json.loads(cache_file.read_text())

        url = f"{BASE_URL}{path}?{query}&api_key={urllib.parse.quote(self.api_key)}"
        # Cloudflare rejects the default Python-urllib user agent (error 1010).
        request = urllib.request.Request(url, headers={"User-Agent": "congress-demo/1.0", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=30, context=self.ssl_context) as resp:
                data = json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                raise ApiError("rate limit hit (HTTP 429); set CONGRESS_API_KEY to your own key or wait an hour")
            raise ApiError(f"HTTP {e.code}: {e.read().decode(errors='replace')[:200]}")
        except urllib.error.URLError as e:
            raise ApiError(f"network error: {e.reason}")
        self.calls += 1

        CACHE_DIR.mkdir(exist_ok=True)
        cache_file.write_text(json.dumps(data))
        return data


# --- Formatting -------------------------------------------------------------


def dig(obj, dotted):
    """Read a dotted path like 'latestAction.text' or 'sponsors.0.fullName'."""
    for part in dotted.split("."):
        if isinstance(obj, list):
            obj = obj[int(part)] if part.isdigit() and int(part) < len(obj) else None
        elif isinstance(obj, dict):
            obj = obj.get(part)
        else:
            return None
    return obj


def payload(data):
    """Return (key, value) for the main payload, skipping request/pagination metadata."""
    for key, value in data.items():
        if key not in ("request", "pagination"):
            return key, value
    return None, None


def shorten(value, width):
    text = " ".join(str(value).split())
    return text if len(text) <= width else text[: width - 1] + "…"


def summarize(value):
    """One-line description of any JSON value."""
    if isinstance(value, dict):
        if "count" in value and "url" in value:
            sub = urllib.parse.urlparse(value["url"]).path.replace("/v3", "")
            return f"{value['count']} → {sub}"
        if "name" in value:
            return str(value["name"])
        scalars = [f"{k}={v}" for k, v in value.items() if not isinstance(v, (dict, list)) and k != "url"]
        return ", ".join(scalars) or "{…}"
    if isinstance(value, list):
        if not value:
            return "(none)"
        first = summarize(value[0])
        return first if len(value) == 1 else f"{first}  (+{len(value) - 1} more)"
    return str(value)


def print_record(record):
    """Print a single object as an aligned 'field .... value' block."""
    if not isinstance(record, dict):
        print(f"  {shorten(record, WIDTH - 2)}")
        return
    label_width = min(max((len(k) for k in record), default=0) + 2, 34)
    for key, value in record.items():
        if key == "url" or value in (None, "", [], {}):
            continue
        if isinstance(value, str) and "<" in value:
            value = strip_html(value)
        label = (key + " ").ljust(label_width, ".")
        print(f"  {label} {shorten(summarize(value), WIDTH - label_width - 4)}")


def format_cell(value):
    if value is None:
        return ""
    text = summarize(value)
    # Show ISO timestamps as "YYYY-MM-DD HH:MM", or just the date at midnight UTC.
    if re.match(r"\d{4}-\d{2}-\d{2}T", text):
        text = text[:10] if text[11:16] in ("00:00", "04:00", "05:00") else text[:16].replace("T", " ")
    return shorten(text, 60)


def column_headers(columns):
    """Use each path's last part as its header, adding the parent when two would clash."""
    headers = [c.split(".")[-1] for c in columns]
    for i, column in enumerate(columns):
        if headers.count(headers[i]) > 1:
            parts = [p for p in column.split(".") if not p.isdigit()]
            headers[i] = ".".join(parts[-2:])
    return headers


def print_table(rows, columns, limit):
    """Print a list of objects as a table, using dotted paths for columns."""
    if not rows:
        print("  (no results)")
        return
    if not columns or not any(dig(r, c) not in (None, "") for r in rows for c in columns):
        # Fall back to the first few scalar fields of the first row.
        columns = [k for k, v in rows[0].items() if not isinstance(v, (dict, list)) and k != "url"][:5]

    shown = rows[:limit]
    # Drop columns that are empty for every row shown.
    columns = [c for c in columns if any(dig(r, c) not in (None, "", []) for r in shown)] or columns
    cells = [[format_cell(dig(r, c)) for c in columns] for r in shown]
    headers = column_headers(columns)
    widths = [max(len(h), *(len(row[i]) for row in cells)) for i, h in enumerate(headers)]

    # Shrink the widest column until the table fits the terminal width.
    while sum(widths) + 2 * len(widths) > WIDTH and max(widths) > 12:
        widths[widths.index(max(widths))] -= 1

    def line(values):
        return "  " + "  ".join(shorten(v, w).ljust(w) for v, w in zip(values, widths))

    print(line(headers))
    print("  " + "  ".join("─" * w for w in widths))
    for row in cells:
        print(line(row))
    if len(rows) > limit:
        print(f"  … {len(rows) - limit} more rows in this page")


# --- Demo runner ------------------------------------------------------------


class Demo:
    def __init__(self, client, raw=False, limit=5):
        self.client = client
        self.raw = raw
        self.limit = limit

    def section(self, title):
        print("\n" + "═" * WIDTH)
        print(f" {title.upper()}")
        print("═" * WIDTH)

    def call(self, label, path, columns=None, **params):
        """Fetch an endpoint, print it, and return its payload (or None on error)."""
        print(f"\n▶ {label}\n  GET {path}")
        try:
            data = self.client.get(path, **params)
        except ApiError as e:
            print(f"  ✗ {e}")
            return None

        _, body = payload(data)
        total = dig(data, "pagination.count")
        if total is not None:
            print(f"  {total:,} total results")
        print()

        if isinstance(body, list) and len(body) == 1 and total is None:
            # Some detail endpoints (e.g. /treaty) wrap their single record in a list.
            body = body[0]
            print_record(body)
        elif isinstance(body, list):
            print_table(body, columns, self.limit)
        else:
            print_record(body)

        if self.raw:
            print("\n  Raw JSON:")
            print(textwrap.indent(json.dumps(data, indent=2), "    "))
        return body


def run_bill(d):
    congress, bill_type, number = EXAMPLES["bill"]
    base = f"/bill/{congress}/{bill_type}/{number}"
    cols = ["congress", "type", "number", "title", "latestAction.actionDate", "latestAction.text"]

    d.section("Bills")
    d.call("Most recently updated bills", "/bill", cols, limit=d.limit)
    d.call(f"Bills in the {congress}th Congress", f"/bill/{congress}", cols, limit=d.limit)
    d.call(f"{bill_type.upper()} bills in the {congress}th Congress", f"/bill/{congress}/{bill_type}", cols, limit=d.limit)
    d.call(f"Bill detail: {bill_type.upper()} {number}", base)
    d.call("Actions", f"{base}/actions", ["actionDate", "type", "text"])
    d.call("Amendments", f"{base}/amendments", ["type", "number", "updateDate"])
    d.call("Committees", f"{base}/committees", ["name", "chamber", "activities.0.name", "activities.0.date"])
    d.call("Cosponsors", f"{base}/cosponsors", ["fullName", "party", "state", "sponsorshipDate", "isOriginalCosponsor"])
    d.call("Related bills", f"{base}/relatedbills", ["congress", "type", "number", "title", "relationshipDetails.0.type"])
    subjects = d.call("Subjects", f"{base}/subjects")
    if subjects:
        names = [s["name"] for s in subjects.get("legislativeSubjects", [])]
        print(f"\n  Legislative subjects ({len(names)}):")
        print(textwrap.indent(textwrap.fill(", ".join(names), WIDTH - 4), "    "))
    summaries = d.call("CRS summaries", f"{base}/summaries", ["actionDate", "actionDesc", "versionCode", "updateDate"])
    if summaries:
        print("\n  Latest summary text:")
        text = strip_html(summaries[-1].get("text", ""))
        print(textwrap.indent(textwrap.fill(shorten(text, 800), WIDTH - 4), "    "))
    versions = d.call("Text versions", f"{base}/text", ["date", "type", "formats.0.type", "formats.0.url"])
    d.call("Titles", f"{base}/titles", ["titleType", "title"])
    return versions


def run_law(d):
    congress, law_type, number = EXAMPLES["law"]
    cols = ["congress", "type", "number", "laws.0.number", "title"]

    d.section("Laws")
    d.call(f"Laws enacted in the {congress}th Congress", f"/law/{congress}", cols, limit=d.limit)
    d.call(f"Public laws in the {congress}th Congress", f"/law/{congress}/{law_type}", cols, limit=d.limit)
    d.call(f"Law detail: P.L. {congress}-{number}", f"/law/{congress}/{law_type}/{number}")


def run_amendment(d):
    congress, amdt_type, number = EXAMPLES["amendment"]
    base = f"/amendment/{congress}/{amdt_type}/{number}"
    cols = ["congress", "type", "number", "purpose", "description", "latestAction.text"]

    d.section("Amendments")
    d.call("Most recently updated amendments", "/amendment", cols, limit=d.limit)
    d.call(f"Amendments in the {congress}th Congress", f"/amendment/{congress}", cols, limit=d.limit)
    d.call(f"{amdt_type.upper()}s in the {congress}th Congress", f"/amendment/{congress}/{amdt_type}", cols, limit=d.limit)
    d.call(f"Amendment detail: {amdt_type.upper()} {number}", base)
    d.call("Actions", f"{base}/actions", ["actionDate", "type", "text"])
    d.call("Cosponsors", f"{base}/cosponsors", ["fullName", "party", "state", "sponsorshipDate"])
    d.call("Amendments to this amendment", f"{base}/amendments", ["type", "number", "purpose", "latestAction.text"])
    d.call("Text versions (117th Congress onward)", f"{base}/text", ["date", "type", "formats.0.url"])


def run_summaries(d):
    congress, bill_type = EXAMPLES["summaries"]
    cols = ["bill.type", "bill.number", "actionDate", "actionDesc", "bill.title"]

    d.section("Bill summaries")
    # Without a date range, /summaries only returns summaries published in the last day.
    first_year = 1789 + 2 * (int(congress) - 1)
    span = {"fromDateTime": f"{first_year}-01-01T00:00:00Z", "toDateTime": f"{first_year + 2}-01-03T00:00:00Z"}

    d.call("Summaries published in the last day", "/summaries", cols, limit=d.limit)
    d.call(f"Summaries in the {congress}th Congress", f"/summaries/{congress}", cols, limit=d.limit, **span)
    rows = d.call(f"{bill_type.upper()} summaries in the {congress}th Congress", f"/summaries/{congress}/{bill_type}", cols, limit=d.limit, **span)
    if rows:
        print(f"\n  Example summary ({dig(rows[0], 'bill.type')} {dig(rows[0], 'bill.number')}):")
        print(textwrap.indent(textwrap.fill(shorten(strip_html(rows[0].get("text", "")), 600), WIDTH - 4), "    "))


def run_treaty(d):
    congress, number = EXAMPLES["treaty"]
    p_congress, p_number, suffix = EXAMPLES["partitioned_treaty"]
    cols = ["congressReceived", "number", "suffix", "transmittedDate", "topic"]

    d.section("Treaties")
    d.call("Most recently updated treaties", "/treaty", cols, limit=d.limit)
    d.call(f"Treaties in the {congress}th Congress", f"/treaty/{congress}", cols, limit=d.limit)
    d.call(f"Treaty detail: Treaty Doc. {congress}-{number}", f"/treaty/{congress}/{number}")
    d.call("Actions", f"/treaty/{congress}/{number}/actions", ["actionDate", "type", "text"])
    d.call("Committees", f"/treaty/{congress}/{number}/committees", ["name", "chamber", "activities.0.name", "activities.0.date"])
    d.call(f"Partitioned treaty detail: {p_congress}-{p_number}{suffix}", f"/treaty/{p_congress}/{p_number}/{suffix}")
    d.call("Partitioned treaty actions", f"/treaty/{p_congress}/{p_number}/{suffix}/actions", ["actionDate", "type", "text"])


def run_member(d):
    bioguide = EXAMPLES["member"]
    state, district = EXAMPLES["state_district"]
    congress = EXAMPLES["member_congress"]
    cols = ["name", "partyName", "state", "district", "terms.item.0.chamber", "bioguideId"]
    leg_cols = ["congress", "type", "number", "introducedDate", "title", "policyArea.name"]

    d.section("Members")
    d.call("Members (most recently updated)", "/member", cols, limit=d.limit)
    d.call(f"Members of the {congress}th Congress", f"/member/congress/{congress}", cols, limit=d.limit, currentMember="false")
    d.call(f"Members from {state}", f"/member/{state}", cols, limit=d.limit)
    d.call(f"Members from {state}-{district}", f"/member/{state}/{district}", cols)
    d.call(f"Members from {state}-{district} in the {congress}th Congress", f"/member/congress/{congress}/{state}/{district}", cols)
    member = d.call(f"Member detail: {bioguide}", f"/member/{bioguide}")
    if member and member.get("terms"):
        print("\n  Terms of service:")
        print_table(member["terms"], ["congress", "chamber", "stateCode", "district", "startYear", "endYear"], 100)
    d.call("Sponsored legislation", f"/member/{bioguide}/sponsored-legislation", leg_cols, limit=d.limit)
    d.call("Cosponsored legislation", f"/member/{bioguide}/cosponsored-legislation", leg_cols, limit=d.limit)


def run_vote(d):
    congress, session = EXAMPLES["vote_congress_session"]
    cols = ["rollCallNumber", "startDate", "voteType", "result", "legislationType", "legislationNumber"]

    d.section("House roll call votes (beta)")
    d.call("Most recent House votes", "/house-vote", cols, limit=d.limit)
    d.call(f"House votes in the {congress}th Congress", f"/house-vote/{congress}", cols, limit=d.limit)
    # Pick a vote on legislation from this list for the detail calls.
    votes = d.call(f"House votes in the {congress}th Congress, session {session}", f"/house-vote/{congress}/{session}", cols, limit=50)
    if not votes:
        return
    vote = next((v for v in votes if v.get("legislationNumber")), votes[0])
    number = vote["rollCallNumber"]
    base = f"/house-vote/{congress}/{session}/{number}"

    detail = d.call(f"Vote detail: roll call {number}", base)
    if detail and detail.get("votePartyTotal"):
        print("\n  Totals by party:")
        print_table(detail["votePartyTotal"], ["voteParty", "party.name", "yeaTotal", "nayTotal", "presentTotal", "notVotingTotal"], 10)

    result = d.call("How each member voted", f"{base}/members")
    results = (result or {}).get("results", [])
    if results:
        print("\n  Member votes:")
        print_table(results, ["lastName", "firstName", "voteParty", "voteState", "voteCast"], d.limit * 2)
        tally = {}
        for r in results:
            tally[r.get("voteCast", "?")] = tally.get(r.get("voteCast", "?"), 0) + 1
        print("\n  Tally: " + ", ".join(f"{k}: {v}" for k, v in sorted(tally.items())))


def run_nomination(d):
    congress, number = EXAMPLES["nomination"]
    base = f"/nomination/{congress}/{number}"
    cols = ["citation", "receivedDate", "description", "latestAction.text"]

    d.section("Nominations")
    d.call("Most recent nominations", "/nomination", cols, limit=d.limit)
    d.call(f"Nominations in the {congress}th Congress", f"/nomination/{congress}", cols, limit=d.limit)
    nomination = d.call(f"Nomination detail: PN{number}", base)
    ordinal = dig(nomination, "nominees.0.ordinal") or 1
    d.call(f"Nominees (position {ordinal})", f"{base}/{ordinal}", ["lastName", "firstName", "state", "effectiveDate", "predecessorName"])
    d.call("Actions", f"{base}/actions", ["actionDate", "type", "text"])
    d.call("Committees", f"{base}/committees", ["name", "chamber", "activities.0.name", "activities.0.date"])
    d.call("Printed hearings", f"{base}/hearings", ["chamber", "citation", "date", "jacketNumber"])


def run_congress(d):
    number = EXAMPLES["congress"]
    cols = ["name", "startYear", "endYear"]

    d.section("Congresses and sessions")
    d.call("All congresses", "/congress", cols, limit=d.limit)
    congress = d.call("Current congress", "/congress/current")
    if congress and congress.get("sessions"):
        print("\n  Sessions:")
        print_table(congress["sessions"], ["number", "chamber", "type", "startDate", "endDate"], 20)
    d.call(f"The {number}th Congress", f"/congress/{number}")


def strip_html(text):
    return html.unescape(re.sub(r"<[^>]+>", " ", text or ""))


SECTIONS = {
    "bill": run_bill,
    "law": run_law,
    "amendment": run_amendment,
    "summaries": run_summaries,
    "treaty": run_treaty,
    "member": run_member,
    "vote": run_vote,
    "nomination": run_nomination,
    "congress": run_congress,
}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sections", nargs="*", help=f"sections to run (default: all): {', '.join(SECTIONS)}")
    parser.add_argument("--raw", action="store_true", help="also print the raw JSON for each response")
    parser.add_argument("--limit", type=int, default=5, help="rows to show per list (default: 5)")
    parser.add_argument("--refresh", action="store_true", help="ignore cached responses")
    parser.add_argument("--list", action="store_true", help="list section names and exit")
    args = parser.parse_args()

    if args.list:
        print("\n".join(SECTIONS))
        return

    unknown = [s for s in args.sections if s not in SECTIONS]
    if unknown:
        parser.error(f"unknown section(s): {', '.join(unknown)}; choose from {', '.join(SECTIONS)}")

    api_key = load_api_key()
    if not api_key:
        print("CONGRESS_API_KEY is not set in the environment or .env; using DEMO_KEY, which allows only a handful of calls per hour.", file=sys.stderr)
        print("Get a free key at https://api.congress.gov/sign-up/\n", file=sys.stderr)
        api_key = "DEMO_KEY"

    client = CongressClient(api_key, use_cache=not args.refresh)
    demo = Demo(client, raw=args.raw, limit=args.limit)
    for name in args.sections or SECTIONS:
        SECTIONS[name](demo)

    print(f"\nDone. {client.calls} live API calls (the rest came from {CACHE_DIR.name}/).")


if __name__ == "__main__":
    main()
