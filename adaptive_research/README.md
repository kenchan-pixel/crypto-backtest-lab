# Adaptive multifactor research — retrospective experiment

This is a separate research experiment, not an overwrite of the previous payoff model or a live strategy. Monthly training uses earlier observations, a later 90-day calibration block and a 25-hour label purge. The primary 365-day model with a 20% volatility-sizing proxy failed qualification. A predeclared 180-day ETH sensitivity has only descriptive defensive clues; it is not promoted in place of the primary result.

## Replay
The delivered `Crypto_Adaptive_Research_20260921.zip` contains exact market/derivative inputs, input manifest, source, predictions, trades, NAVs, all controls/sensitivities, a report and an executed notebook. It is a local conversation deliverable; this experiment has no claimed new GitHub Actions run or newly published release asset.

ZIP SHA256: `edba5e32d1288bc4485ab69a4066a2c7d8928a9f5b5ba1596047c91f00196064`.

After extracting the full ZIP, work from its root:
```bash
python -m pip install -r adaptive_research/requirements.txt
python -m pytest -q adaptive_research/test_study.py
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m adaptive_research.study
python -m adaptive_research.verify
```

The supplied `Adaptive_Research_Executed.ipynb` reruns the scientific computation and checks when executed from the extracted root. An isolated notebook without the complete inputs is insufficient.

## Provenance
Original derivatives release: `research-derivatives-20260919-52b24ddfb33c-a1`; ZIP SHA256 `034aa3a79ea9451868f862d0796cceb158df956b12c1fe3ccf6901ff3fb43051`. Input boundary minute observations are inherited from the completed BTC and ETH benchmark reviews, not synthesized. The new package verifies 28 input/source files and includes 82 manifest entries. Re-running the study does not fetch new news or market prices.

Protocol committed before computation: `3e304ec547fb64805c56d6c1d6dc12de553f6155`.
Executed main scientific blob: `bfd1c806524becfecff611fcd20cdc0bb338911c`.
Main source SHA256: `e7884bda009056193cc231ac343b59766e8b5d3efaa01346c8f055521cfeffad`.
Executed notebook SHA256: `ac5204be888a2fd616df318b92a139e3d779bba3ef6609b4c363a30b117f4a43`.

Actual verification: 12 unit tests, 61 independent accounting/chronology checks, five executed notebook code cells. The independent verifier does not import the main accounting function. This is not a second independent market download or a reimplementation of scikit-learn.

Historical 2025–2026 data have been used repeatedly; temporal purging does not make this a blind holdout. Hourly/execution-price drawdown does not observe all intraminute extremes. Historical derivative availability remains an assumed delay, not certified original publication vintage. The original payoff zero-signal-schema P2 is not claimed fixed by this new evaluator's separate empty-account tests. No trades, leverage, shorting, merge, new automation or paid data were used.
