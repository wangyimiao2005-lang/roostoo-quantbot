# Taker flow source audit

Official Binance Futures `/fapi/v1/klines`, 1h. Field 10 is taker-buy quote volume; total quote is field 7, so taker-sell quote = total - taker-buy. Imbalance = (buy-sell)/total. These are completed exchange bars; signal uses t, execution t+1.
