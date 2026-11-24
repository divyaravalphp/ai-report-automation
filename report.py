"""
AI report automation demo.

Pipeline:  CSV  ->  clean & validate  ->  compute KPIs  ->  chart (PNG)
           ->  LLM writes a 3-bullet management summary  ->  HTML report (+ optional email)

Usage:
    python report.py data/sales.csv
    python report.py data/sales.csv --email someone@example.com
    python report.py data/sales.csv --no-ai        # skip the LLM, use a rule-based summary
"""

import argparse
import json
import os
import smtplib
import sys
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # no display needed, works on servers / schedulers
import matplotlib.pyplot as plt
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

REQUIRED_COLUMNS = {"date", "region", "product", "units", "revenue"}
OUTPUT_DIR = Path("output")


# ---------------------------------------------------------------- 1. load + validate
def load_data(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df.columns = [c.strip().lower() for c in df.columns]

    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        sys.exit(f"ERROR: CSV is missing columns: {sorted(missing)}")

    rows_in = len(df)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["units"] = pd.to_numeric(df["units"], errors="coerce")
    df["revenue"] = pd.to_numeric(df["revenue"], errors="coerce")
    df = df.dropna(subset=["date", "revenue"])
    df = df[df["revenue"] >= 0]

    dropped = rows_in - len(df)
    print(f"Loaded {rows_in} rows, dropped {dropped} invalid rows.")
    return df


# ---------------------------------------------------------------- 2. KPIs
def compute_kpis(df: pd.DataFrame) -> dict:
    df = df.copy()
    df["month"] = df["date"].dt.to_period("M").astype(str)

    monthly = df.groupby("month")["revenue"].sum().round(2)
    by_region = df.groupby("region")["revenue"].sum().sort_values(ascending=False).round(2)
    by_product = df.groupby("product")["revenue"].sum().sort_values(ascending=False).round(2)

    # month-over-month change per region (last two months in the data)
    region_month = df.pivot_table(index="month", columns="region", values="revenue", aggfunc="sum")
    mom = {}
    if len(region_month) >= 2:
        prev, last = region_month.iloc[-2], region_month.iloc[-1]
        mom = ((last - prev) / prev * 100).round(1).to_dict()

    return {
        "period": f"{df['date'].min():%d %b %Y} to {df['date'].max():%d %b %Y}",
        "total_revenue": round(float(df["revenue"].sum()), 2),
        "total_units": int(df["units"].sum()),
        "monthly_revenue": monthly.to_dict(),
        "revenue_by_region": by_region.to_dict(),
        "revenue_by_product": by_product.to_dict(),
        "region_mom_change_pct": mom,
    }


# ---------------------------------------------------------------- 3. chart
def make_chart(df: pd.DataFrame, path: Path) -> None:
    df = df.copy()
    df["month"] = df["date"].dt.to_period("M").astype(str)
    pivot = df.pivot_table(index="month", columns="region", values="revenue", aggfunc="sum")

    fig, ax = plt.subplots(figsize=(9, 5))
    pivot.plot(kind="bar", ax=ax, width=0.8)
    ax.set_title("Revenue by region per month")
    ax.set_xlabel("")
    ax.set_ylabel("Revenue")
    ax.yaxis.set_major_formatter(matplotlib.ticker.StrMethodFormatter("{x:,.0f}"))
    ax.spines[["top", "right"]].set_visible(False)
    plt.xticks(rotation=0)
    plt.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------- 4. AI summary
def ai_summary(kpis: dict) -> list[str]:
    """Send only the aggregated KPIs (not raw rows) to the LLM."""
    from openai import OpenAI

    client = OpenAI()  # reads OPENAI_API_KEY from env / .env
    prompt = (
        "You are a business analyst. Using ONLY the KPI data below, write exactly 3 "
        "concise bullet points for a management report: the headline result, the "
        "biggest risk or decline, and one recommended action. Use the actual numbers. "
        'Return JSON: {"bullets": ["...", "...", "..."]}\n\n'
        f"KPIs:\n{json.dumps(kpis, indent=2)}"
    )
    resp = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.2,
    )
    bullets = json.loads(resp.choices[0].message.content)["bullets"]
    return validate_bullets(bullets)


def rule_based_summary(kpis: dict) -> list[str]:
    """Fallback when no API key is set or the AI call fails."""
    top_region = next(iter(kpis["revenue_by_region"]))
    top_product = next(iter(kpis["revenue_by_product"]))
    mom = kpis["region_mom_change_pct"]
    worst = min(mom, key=mom.get) if mom else None
    bullets = [
        f"Total revenue of {kpis['total_revenue']:,.0f} from {kpis['total_units']} units "
        f"({kpis['period']}); {top_region} is the top region and {top_product} the top product.",
    ]
    if worst:
        bullets.append(f"{worst} changed {mom[worst]:+.1f}% month over month, the weakest region.")
        bullets.append(f"Review the {worst} pipeline and pricing before next month's close.")
    return bullets


def validate_bullets(bullets) -> list[str]:
    if not isinstance(bullets, list) or len(bullets) != 3 or not all(isinstance(b, str) and b.strip() for b in bullets):
        raise ValueError(f"AI output failed validation: {bullets!r}")
    return [b.strip() for b in bullets]


# ---------------------------------------------------------------- 5. report + email
def build_html(kpis: dict, bullets: list[str], source: str) -> str:
    items = "".join(f"<li>{b}</li>" for b in bullets)
    rows = "".join(f"<tr><td>{k}</td><td style='text-align:right'>{v:,.0f}</td></tr>"
                   for k, v in kpis["revenue_by_region"].items())
    return f"""<!DOCTYPE html><html><body style="font-family:Arial,sans-serif;max-width:720px;margin:auto">
<h2>Sales performance report</h2>
<p style="color:#666">Period: {kpis['period']} &middot; Generated {datetime.now():%d %b %Y %H:%M} &middot; Source: {source}</p>
<h3>Summary</h3><ul>{items}</ul>
<img src="chart.png" alt="Revenue by region per month" style="width:100%">
<h3>Revenue by region</h3>
<table cellpadding="6" style="border-collapse:collapse">{rows}</table>
</body></html>"""


def send_email(to_addr: str, bullets: list[str], chart: Path, html_path: Path) -> None:
    msg = EmailMessage()
    msg["Subject"] = f"Sales report - {datetime.now():%d %b %Y}"
    msg["From"] = os.environ["SMTP_USER"]
    msg["To"] = to_addr
    msg.set_content("Summary:\n\n" + "\n".join(f"- {b}" for b in bullets))
    msg.add_attachment(chart.read_bytes(), maintype="image", subtype="png", filename="chart.png")
    msg.add_attachment(html_path.read_bytes(), maintype="text", subtype="html", filename="report.html")

    with smtplib.SMTP(os.getenv("SMTP_HOST", "smtp.gmail.com"), int(os.getenv("SMTP_PORT", "587"))) as s:
        s.starttls()
        s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
        s.send_message(msg)
    print(f"Email sent to {to_addr}")


# ---------------------------------------------------------------- main
def main() -> None:
    parser = argparse.ArgumentParser(description="CSV -> AI summary -> chart report")
    parser.add_argument("csv", help="path to the CSV file")
    parser.add_argument("--email", help="send the report to this address")
    parser.add_argument("--no-ai", action="store_true", help="use the rule-based summary")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(exist_ok=True)
    df = load_data(args.csv)
    kpis = compute_kpis(df)
    (OUTPUT_DIR / "kpis.json").write_text(json.dumps(kpis, indent=2))

    chart = OUTPUT_DIR / "chart.png"
    make_chart(df, chart)

    if args.no_ai or not os.getenv("OPENAI_API_KEY"):
        print("Using rule-based summary (no API key or --no-ai).")
        bullets = rule_based_summary(kpis)
    else:
        try:
            bullets = ai_summary(kpis)
            print("AI summary generated.")
        except Exception as e:  # never send a broken report
            print(f"AI step failed ({e}); falling back to rule-based summary.")
            bullets = rule_based_summary(kpis)

    html_path = OUTPUT_DIR / "report.html"
    html_path.write_text(build_html(kpis, bullets, Path(args.csv).name), encoding="utf-8")

    print("\nSummary:")
    for b in bullets:
        print(f"  - {b}")
    print(f"\nSaved: {html_path}, {chart}, {OUTPUT_DIR / 'kpis.json'}")

    if args.email:
        send_email(args.email, bullets, chart, html_path)


if __name__ == "__main__":
    main()
