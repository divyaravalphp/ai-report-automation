# AI Report Automation

A small Python pipeline that turns a raw CSV into a management-ready report:

```
CSV → clean & validate → KPIs → chart (PNG) → LLM 3-bullet summary → HTML report → (optional) email
```

## Why it's built this way
- **Only aggregated KPIs go to the LLM**, not raw rows: cheaper, faster and keeps customer-level data private.
- **AI output is validated** (exactly 3 non-empty bullets, JSON mode). If the API fails or returns junk, it falls back to a rule-based summary, so a broken report is never sent.
- **Low temperature (0.2)** and "use only the data below" in the prompt reduce made-up numbers.
- Runs headless, so it can be scheduled (Windows Task Scheduler, cron, or an n8n "Execute Command" node).

## Setup
```bash
python -m venv venv
venv\Scripts\activate          # Windows  (source venv/bin/activate on Mac/Linux)
pip install -r requirements.txt
copy .env.example .env         # then add your OPENAI_API_KEY
```

## Run
```bash
python report.py data/sales.csv            # AI summary (needs OPENAI_API_KEY)
python report.py data/sales.csv --no-ai    # rule-based summary, no API key needed
python report.py data/sales.csv --email you@example.com   # needs SMTP settings in .env
```

Outputs go to `output/`: `report.html`, `chart.png`, `kpis.json`.

## CSV format
`date, region, product, units, revenue` (sample in `data/sales.csv`).

## Next steps
- Export to PowerPoint with `python-pptx` (chart + bullets on a slide).
- Pull data from Google Sheets via API instead of CSV.
- Schedule weekly and post to Slack/Teams.
