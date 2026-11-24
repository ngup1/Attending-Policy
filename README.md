# Attending-Policy

https://github.com/LibraryOfCongress/api.congress.gov/

https://www.senate.gov/general/common/generic/XML_Availability.htm

## Running the demo backend

```sh
uv venv .venv && uv pip install -p .venv/bin/python -r requirements.txt
echo "CONGRESS_API_KEY=your-key" > .env        # free key: https://api.congress.gov/sign-up/
.venv/bin/python prewarm.py                    # cache everything the demo needs (run before presenting)
.venv/bin/uvicorn api:app --reload --port 8000   # then open http://localhost:8000
```

- `GET /api/votes?q=&chamber=all|house|senate`: recent final-passage House votes on bills
- `GET /api/votes/{congress}/{session}/{roll}`: one vote, with the bill, its CRS summary, totals by party, and every member's vote

Interactive docs: http://localhost:8000/docs
