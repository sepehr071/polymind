# DLP smart-scan eval corpus

Labeled scenario database for measuring **category accuracy** of
`DLPDetector.llm_classify` against the self-hosted Ollama backend.

Local laptops do **not** reach Ollama (`DLP_LLM_BASE_URL` is blank in dev).
Run the eval on a host that can reach your Ollama server.

## Gold-label rules (presence detection)

| Gold | When |
|---|---|
| `public` | No sensitive **value** in the text — including messages that only *discuss* secrets/PII/projects |
| `confidential` | Contact PII, employee names, or internal hostnames **present as values** |
| `restricted` | Secrets, financial account numbers, passwords, or actual internal **codename strings** present |

Examples:

| Text | Gold |
|---|---|
| `My email is a@b.com` | confidential |
| `How should I store API keys?` | public |
| `password is hunter2` | restricted |
| `Don't leak the codename` (no value) | public |
| `Codename Nightfall ships Q3` | restricted |

## Corpus format

`corpus.jsonl` — one JSON object per line:

```json
{
  "id": "en-restricted-aws-01",
  "lang": "en",
  "gold_category": "restricted",
  "tags": ["value_present", "secret", "aws"],
  "text": "rotate AKIAIOSFODNN7EXAMPLE before Friday",
  "notes": "AWS access key ID present"
}
```

Use **synthetic** secrets only (AWS EXAMPLE keys, Luhn test cards, `@example.com`).

### Scenario families

| Family | Tags | What it tests |
|---|---|---|
| Clean / topic-only public | `clean`, `topic_only` | No false positives on chit-chat or “about secrets” without values |
| Classic secrets | `secret`, `financial` | Keys, cards, passwords, IBAN |
| **Semantic business** | `semantic` | Named customers, salaries, deal terms, M&A — not just API keys |
| **Custom guidance** | `guidance` + optional `guidance_prompt` | Workspace policy codenames/aliases/phrases must be flagged when present, ignored when absent |

### Why custom guidance used to fail

The base prompt previously forced `public` whenever the model could not quote a `spans[]` substring. Semantic / policy cases often have soft boundaries, so the model returned public and **ignored workspace guidance**. Production prompt now treats WORKSPACE POLICY as authoritative and allows non-public + empty spans (enforce-mode can still confirm).

## Offline validation (CI / laptop)

```powershell
cd backend
./.venv-uv/Scripts/python.exe -m pytest tests/eval/test_dlp_smart_scan_corpus.py -p no:randomly -v
```

## Live accuracy run

```bash
# From the backend root, with DLP_LLM_BASE_URL set:
set -a && source /path/to/.env && set +a
export DLP_LLM_TIMEOUT=60   # chat uses 8s fail-open; eval should wait

python scripts/eval_dlp_smart_scan.py \
  --corpus eval/dlp_smart_scan/corpus.jsonl \
  --out ../reports/run-$(date +%Y%m%d).json
```

Headline line looks like:

```text
Smart-scan category accuracy: 87.5% (N=112, model=qwen3.6:35b)
```

Reports land under repo-root `reports/` (gitignored).

### Readable HTML report

```powershell
cd backend
./.venv-uv/Scripts/python.exe eval/dlp_smart_scan/build_report_html.py `
  --report ../reports/run-20260711-semantic-guidance.json `
  --out ../reports/dlp-smart-scan-report.html
```

Open `reports/dlp-smart-scan-report.html` in a browser (self-contained; no server). **RTL Persian**, plain-language labels for non-technical readers. Tabs: خلاصه نتایج · قوانین اختصاصی · اشتباه‌ها · همه نمونه‌ها.

Corpus size after hard expansion: **~250+** rows (semantic hard, custom-guidance hard, adversarial). Re-run the eval to refresh accuracy for the full set, then rebuild the HTML from the new JSON.

## Adding rows

1. Pick `id` = `{lang}-{category}-{family}-{nn}` unique.
2. Tag with `value_present` or `topic_only` when relevant; use `semantic` / `guidance` as needed.
3. For custom-policy rows, set `guidance_prompt` and tag `guidance`.
4. Keep `text` ≥ 6 chars (shorter texts skip smart-scan entirely).
5. Re-run the corpus unit test.
