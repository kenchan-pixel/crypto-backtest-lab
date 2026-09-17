# Crypto 8 Rules Backtest — Final Summary

Real-data GitHub Actions run: https://github.com/kenchan-pixel/crypto-backtest-lab/actions/runs/35285691712

## Overall verdict

No rule qualified for ✅ preliminary reliable edge under the frozen criteria. R5 failed on both BTC and ETH. The remaining rules are 🟡 evidence insufficient; BTC R7 also failed its frozen implementation.

## Rule verdicts

- R1 🟡 證據不足 — 早上大跌就要買，早上大漲就要賣
- R2 🟡 證據不足 — 下午大漲不追，下午大跌次日買
- R3 🟡 證據不足 — 早上大跌不割，不漲不跌就睡覺
- R4 🟡 證據不足 — 不沖高不賣，不跳水不買，橫盤不交易
- R5 ❌ 無優勢／扣成本後失效 — 買陰不買陽，賣陽不賣陰
- R6 🟡 證據不足 — 逆勢而動，方為英雄
- R7 🟡 證據不足 — 高低盤整，再等一等
- R8 🟡 證據不足 — 高位橫盤再沖高，抓住時機趕緊拋

## OOS primary metrics

|Rule|Symbol|N|Win rate|PF|Net return|Max DD|Status|
|---|---:|---:|---:|---:|---:|---:|---|
|R1|BTCUSDT|2|50.0%|7.29|2.0%|-1.7%|🟡|
|R2|BTCUSDT|0|—|—|0.0%|0.0%|🟡|
|R3|BTCUSDT|3|33.3%|0.42|-19.0%|-54.0%|🟡|
|R4|BTCUSDT|88|45.5%|0.66|-19.1%|-26.3%|🟡|
|R5|BTCUSDT|15,491|7.2%|0.04|-100.0%|-100.0%|❌|
|R6|BTCUSDT|43|48.8%|0.67|-11.4%|-19.9%|🟡|
|R7|BTCUSDT|291|27.1%|0.37|-61.2%|-62.4%|❌|
|R8|BTCUSDT|250|60.0%|0.66|-60.7%|-71.5%|🟡|
|R1|ETHUSDT|3|33.3%|0.99|-0.0%|-4.5%|🟡|
|R2|ETHUSDT|0|—|—|0.0%|0.0%|🟡|
|R3|ETHUSDT|4|75.0%|0.54|-26.8%|-68.7%|🟡|
|R4|ETHUSDT|280|52.1%|0.63|-64.5%|-68.7%|🟡|
|R5|ETHUSDT|15,723|14.0%|0.07|-100.0%|-100.0%|❌|
|R6|ETHUSDT|127|40.9%|0.57|-43.4%|-53.0%|🟡|
|R7|ETHUSDT|173|35.8%|0.92|-5.5%|-17.2%|🟡|
|R8|ETHUSDT|152|61.2%|0.69|-67.3%|-79.8%|🟡|

## Data quality

- BTCUSDT: 3,012,667 / 3,013,920 warmup-inclusive minutes valid (99.95843%); 1,253 missing; 0 invalid OHLCV; 0 conflicting duplicates; 6 legacy non-standard close_time metadata rows audited.
- ETHUSDT: 3,012,667 / 3,013,920 warmup-inclusive minutes valid (99.95843%); 1,253 missing; 0 invalid OHLCV; 0 conflicting duplicates; 6 legacy non-standard close_time metadata rows audited.
- No simulated market data was used as strategy evidence.
- Main cost model: 0.10% fee + 0.05% adverse slippage per side.
- Historical OOS is not a genuinely untouched forward test because the source screenshots were supplied in 2026.

Detailed machine-readable outputs are in the GitHub Actions artifact for the run above.
