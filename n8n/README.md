# n8n version of the AI report

The same pipeline as `report.py`, built as a no-code n8n workflow:

```
Manual / every Monday 9 AM → Fetch CSV (GitHub) → Compute KPIs → Gemini AI summary
→ Validate AI output (fallback if it fails) → Build HTML report → Email (optional)
```

## What it adds over the first Python version
- **Partial-month check:** flags when the last month is incomplete, so month-over-month drops aren't misread.
- **Clearer prompt:** says there is no currency and that region and product totals cover the whole period, which fixes two mistakes the AI made in the Python run.
- **Currency check:** warns if the AI still adds a currency symbol.
- **Keeps running if the AI fails:** the AI node is set to continue on error, and the validation node falls back to a rule-based summary.

## Import
1. Open n8n: n8n Cloud (free trial) or `npx n8n` locally.
2. Go to **Workflows → Import from File** and choose `ai-weekly-report.workflow.json`.
3. In **AI summary (Gemini)**, create a **Header Auth** credential:
   - Name: `Authorization`
   - Value: `Bearer YOUR_GEMINI_KEY`
4. Click **Execute workflow**.
5. Optional: set up SMTP on **Email report**, then enable that node.
