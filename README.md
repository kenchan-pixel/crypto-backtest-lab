# Crypto Backtest Lab — 8句交易法實證

以 Binance **現貨 BTCUSDT / ETHUSDT、1-minute K-line、香港時間 2021-01-01 至 2026-09-14**，驗證八句交易法是否有可重現統計優勢。

## 研究原則

- 真實 Binance 官方歷史資料；不以模擬行情冒充回測。
- 原句先凍結成明確規則，結果差亦不改參數追盈利。
- 計入手續費與滑價，分 IS / Validation / OOS。
- 逐條策略測試，另有 baseline / control、早晚時段效應、sensitivity、Holm multiple-testing correction。
- 「賣」只代表退出已有現貨持倉，**不偷換成開空倉**。
- 原始社交媒體截圖不放入 public repo；八條原文與研究假設已記錄於 `PROTOCOL.md`。

## 八條原文

1. 早上大跌就要買，早上大漲就要賣
2. 下午大漲不追，下午大跌次日買
3. 早上大跌不割，不漲不跌就睡覺
4. 不沖高不賣，不跳水不買，橫盤不交易
5. 買陰不買陽，賣陽不賣陰
6. 逆勢而動，方為英雄
7. 高低盤整，再等一等
8. 高位橫盤再沖高，抓住時機趕緊拋

## 自動回測

`.github/workflows/full-backtest.yml` 使用 standard `ubuntu-latest` runner：

1. 跑單元測試與 look-ahead / timing checks。
2. 由 `data.binance.vision` 下載官方 Spot 1m ZIP。
3. 驗官方 `.CHECKSUM`，檢查時間戳、缺失、重複、OHLCV。
4. 執行八條策略、controls、OOS、敏感度與統計檢驗。
5. 只上載結果、交易紀錄、圖表及 executed notebook 做 7 日 artifact；**不永久保存大型原始 K-line ZIP**。

完整成功必須由 `execution_status.json` 顯示：

```json
{"full_backtest_executed": true}
```

否則任何部分數字都不當成完整研究結論。

## 本機重跑

```bash
python -m pip install -r requirements.txt
python -m pytest -q
python -m lab --full
```

詳細固定規格、成本、OOS、控制、多重比較及判定門檻見 [`PROTOCOL.md`](PROTOCOL.md)。
