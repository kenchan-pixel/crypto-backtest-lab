# Derivatives incremental-information research

Research only; no live orders, leverage or short positions. Original experiments remain unchanged.

For durable reproduction, use the complete ZIP in the GitHub prerelease named `research-derivatives-20260919-<commit>-a<attempt>`. It contains exact inputs, source, all outputs, an executed notebook and `MANIFEST.json`. Verify every hash before re-running. The source Actions inputs may expire; the release ZIP is the intended persistent evidence, not those transient artifacts.

From the extracted bundle root:
```bash
python -m pip install -r derivatives/requirements.txt
python -m pytest -q derivatives/test_increment.py multifactor/test_research.py
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m derivatives.study
python -m derivatives.verify
```

The `derivatives.ci_run` entrypoint wraps the same scientific computation and corrects the execution-location envelope for GitHub Actions. No statistical rule or parameter differs. Notebook success and SHA-256 are set only after actual execution. Bootstrap regression tests cover zero/positive lift, limited support, matching eligibility and Holm. `verify.py` independently reconstructs scores/labels, selected rules and spot accounts, not all features or bootstrap mathematics.

Source: official Binance archive CHECKSUMs plus 42 September funding observations per coin from the connected Binance funding-history read tool. Historical API access from the runner returned 451; the independently connected public read route succeeded. Supplemental fields are explicitly stored in `supplement.py`; local hashes are not official archive checksums. The timestamp parser retains millisecond jitter and accepts ISO8601 subsecond variation. No parameter was changed to improve results.

Archive snapshots do not certify original first-publication or vintage. One-hour data delay and six-hour stress are assumptions, not proof of latency. News probes were rate-limited and ETF requests blocked; neither was encoded as absent news/flow. Neither source is part of the fitted models.
