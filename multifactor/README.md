# Multi-factor precursor research

Read PROTOCOL.md and RESULTS.md first. This is offline model/pattern research, not a trading bot. No broker, wallet, live keys, shorts, leverage or schedules.

The full conversation research package includes inputs/, outputs/, Research_Executed.ipynb, the independent replay script and notebook builder. Copy its inputs/ directory to the repository root. Alternatively use the matching actual hourly inputs from official Binance archive run35336304622 before its artifact expires. Never substitute same-named data: data.py checks both exact SHA256 hashes.

From repository root:
```bash
python -m pip install -r multifactor/requirements.txt
python -m pytest -q multifactor/test_research.py
python -m multifactor.study
```

This writes outputs/ and may take several minutes. The computation reuses the previously audited raw-minute data's genuine hourly export and next-minute execution prices. It does not claim to download new Binance archives. Original source URLs and checksum manifests accompany the conversation package. No raw price data or large outputs were committed in this branch.

The fixed three-class target concerns next-day +/-1% moves, not guaranteed trade profits. Every leaf/direction is retained, including counterexamples. The 2025 selection snapshot precedes per-rule 2026 evaluation. History is reused, not an untouched blind test. FOMC numeric statements are a limited policy-environment dataset, not complete cryptocurrency news sentiment.

Actual execution took place in the ChatGPT computational container; no new successful GitHub Actions run is claimed. Tests and independent arithmetic checks are verification of stated scope, not evidence of market alpha. The branch stays unmerged pending review.
