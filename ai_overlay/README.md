# Weekly AI capital-management replay

This is an actual assistant decision pilot: 91 packets were reviewed sequentially in the current conversation, with 1.0/0.5/0 new-entry weights and short evidence-based rationales committed before the following packet was displayed. It is not a coded risk rule being mislabelled an LLM. The ledgers were sealed before this experiment's outcomes were computed.

Important: the assistant had already seen prior project performance and may contain pretrained historical knowledge. Masking dates and absolute prices does not make the test blind or remove hindsight. No independent model API/build/sampling metadata are available. The retained ledgers replay exactly; fresh LLM output is not guaranteed to reproduce the original choices.

## Scope
- Frozen ETH opportunity stream, not a new entry engine or BTC strategy.
- Weekly decision is effective one hour after the information cut; existing positions retain their size and original 24-hour exit.
- Controls: original, simple 30-day-direction full/half size, constant half size, passive ETH/cash.
- No historical news corpus was invented. Archived macro surprise and derivatives vintage/availability limitations remain.
- The 91 review decisions comprise 53 in 2025 and 38 in 2026; they are not 91 independent market experiments.
- Conditional paper trading requires the protocol gates; no live money is authorized.

## Rerun saved decisions
From the complete bundle root:
```
python -m pip install -r ai_overlay/requirements.txt
python -m pytest -q ai_overlay/test_overlay.py
python -m ai_overlay.analyze
python -m ai_overlay.verify
python -m ai_overlay.finalize
```
These commands never regenerate or retrospectively alter an AI decision. `session.init` and `session.record` reject changes after the ledger is locked. The decision-time recorder is retained at `ledger/session_at_decision.py`; later guard-only changes do not change financial logic or recorded responses.

The results notebook replays saved decisions and the accounting; it does not represent fresh autonomous AI calls. The complete bundle carries true hourly inputs, derived historical funding/positioning sources, source/archive hashes, packet mapping, all short rationales, accounting code, tests and outputs. Root `MANIFEST.json` binds each file.

## Expense interpretation
Trading NAV is self-financing. The AI expense scenarios are a separate operating budget: a fixed fraction of each year's initial trading capital is accrued at every review and deducted from daily/terminal reported NAV. The expense is not withdrawn from the trading cash account and does not cause forced sales or resize future positions. These are assumed budgets, not measured invoices. No separately metered API was invoked in this conversation; actual subscription allocation and future deployment expense are unknown.

## Verification scope
14 unit tests; 111 independent packet/account checks: 91 weekly past-price/finished-trade/macro summaries, 16 weighted account/daily NAV reconstructions and 4 inference inputs. The checker does not independently regenerate LLM responses or reimplement every derivative feature/bootstrap, and it uses the same market source. Existing upstream payoff-engine zero-signal defect is not claimed repaired; this overlay has its own zero-signal test and complete schema.
