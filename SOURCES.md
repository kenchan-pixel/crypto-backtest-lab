# Sources & provenance

## 原始八句

研究原始來源為使用者在私人對話提供的五張社交媒體截圖。Public repo **不公開原圖**，只保存已核對的八條文字及固定操作定義，詳見 `PROTOCOL.md`。原圖亦不被用作作者績效或資產證據。

## Binance 真實歷史資料

正式 full run 只接受：

- Binance public data repository / format notes: https://github.com/binance/binance-public-data
- Official public archive host: https://data.binance.vision/
- Spot REST market-data documentation: https://developers.binance.com/en/docs/api-reference/spot-api/market-data-endpoints

下載程式保存每個 archive URL、官方 `.CHECKSUM`、本地 SHA-256、下載狀態及資料品質報告。2025-01-01 起的 Spot archive timestamp 單位變更會逐行辨認。缺價不 forward-fill 成可交易報價。

## Statistical method references

- Holm multiple-testing adjustment: https://stat.ethz.ch/R-manual/R-devel/library/stats/html/p.adjust.html
- Holm (1979), *A Simple Sequentially Rejective Multiple Test Procedure*: https://www.jstor.org/stable/4615733

區塊 bootstrap、成本模型、匹配時段事件及分類門檻屬本研究預先固定設計，並非 Binance 或統計文獻替策略背書。
