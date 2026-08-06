# NSE Stock Strategy Backtest Report

**Generated:** 2026-07-20 16:19  
**Universe:** 501 NSE stocks (ohlcv_cache.db)  
**In-sample:** 2024-07-18 → 2025-07-17 | **Out-of-sample:** 2025-07-18 → today  
**Transaction costs:** 0.1% + 0.05% slippage per side = 0.30% round-trip  
**Note:** *Total Return %* = sequential compounding across all trades. Profit factor capped at 99.0 when no losing trades.  

---
## Disclaimer

> **Educational only — not financial advice.** Past backtest results do not guarantee future performance.

---
## Strategy Rules

### V1_RSI14_EMA200_3D `[baseline]`
- **Description:** RSI(14)<30 + Close>EMA200 → hold 3 days or RSI>60
- RSI period: 14 | Entry RSI < 30 | Exit RSI > 60
- Trend filter: Close > EMA(200)
- Max hold: 3 bars

### V3_RSI2_EMA200_3D `[baseline]`
- **Description:** RSI(2)<5 + Close>EMA200 → hold 3 days (mirrors S4V2 signal)
- RSI period: 2 | Entry RSI < 5 | Exit RSI > 70
- Trend filter: Close > EMA(200)
- Max hold: 3 bars

### V4_RSI14_DEEP_5D `[baseline]`
- **Description:** RSI(14)<25 (deeply oversold, no trend filter) → hold 5 days
- RSI period: 14 | Entry RSI < 25 | Exit RSI > 55
- Max hold: 5 bars

### V5_RSI14_ADX_5D `[NEW]`
- **Description:** RSI(14)<25 + ADX>20 → hold 5 days (V4 + trending market filter)
- RSI period: 14 | Entry RSI < 25 | Exit RSI > 55
- ADX filter: ADX(14) > 20 (trending market only)
- Max hold: 5 bars

### V6_RSI14_BB_5D `[NEW]`
- **Description:** RSI(14)<30 + BB_pos<25% + EMA200 → 5D hold or +3% profit target
- RSI period: 14 | Entry RSI < 30 | Exit RSI > 60
- Trend filter: Close > EMA(200)
- Bollinger filter: BB_pos < 25.0% (below lower BB zone)
- Profit target: +3.0% (exit early to lock in gain)
- Max hold: 5 bars

### V7_RSI2_ADX_3D `[NEW]`
- **Description:** RSI(2)<5 + EMA200 + ADX>15 → 3D hold or +4% profit target (S4V2 + ADX)
- RSI period: 2 | Entry RSI < 5 | Exit RSI > 70
- Trend filter: Close > EMA(200)
- ADX filter: ADX(14) > 15 (trending market only)
- Profit target: +4.0% (exit early to lock in gain)
- Max hold: 3 bars

### V8_TRIPLE_RSI_5D `[NEW]`
- **Description:** RSI(14)<35 + RSI(2)<5 + EMA200 + ADX>20 → 5D hold or +5% (S_CTRIO-inspired)
- RSI period: 14 | Entry RSI < 35 | Exit RSI > 60
- Secondary RSI(2) confirmation: RSI2 < 5
- Trend filter: Close > EMA(200)
- ADX filter: ADX(14) > 20 (trending market only)
- Profit target: +5.0% (exit early to lock in gain)
- Max hold: 5 bars

---
## In-Sample Results

| Strategy | Trades | Win Rate | Avg Net % | Total Return % | Max DD % | Profit Factor | Trades/yr |
|---|---|---|---|---|---|---|---|
| V1_RSI14_EMA200_3D | 2 | 50.0% | 0.502% | 0.36% | 0.0% | 1.13 | 0.0 |
| V3_RSI2_EMA200_3D | 295 | 56.9% | 0.024% | -3.37% | -37.9% | 1.02 | 0.6 |
| V4_RSI14_DEEP_5D | 610 | 57.4% | 1.473% | 261058.52% | -42.54% | 2.04 | 1.3 |
| V5_RSI14_ADX_5D | 545 | 54.9% | 1.342% | 54724.71% | -44.83% | 1.89 | 1.2 |
| V6_RSI14_BB_5D | 2 | 50.0% | -0.203% | -0.71% | 0.0% | 0.93 | 0.0 |
| V7_RSI2_ADX_3D | 270 | 56.7% | -0.012% | -12.03% | -38.62% | 0.99 | 0.6 |
| V8_TRIPLE_RSI_5D | 2 | 50.0% | 0.603% | 1.01% | 0.0% | 1.31 | 0.0 |

## Out-of-Sample Results (Survival Test)

| Strategy | Trades | Win Rate | Avg Net % | Total Return % | Max DD % | Profit Factor | Survived? |
|---|---|---|---|---|---|---|---|
| V1_RSI14_EMA200_3D | 1 | 0.0% | -3.547% | -3.55% | 0.0% | 0.0 | ❌ No |
| V3_RSI2_EMA200_3D | 336 | 59.2% | 0.328% | 159.54% | -20.26% | 1.34 | ❌ No |
| V4_RSI14_DEEP_5D | 746 | 49.3% | 0.345% | 440.2% | -63.48% | 1.21 | ✅ Yes |
| V5_RSI14_ADX_5D | 560 | 45.4% | 0.086% | -19.31% | -74.95% | 1.05 | ✅ Yes |
| V6_RSI14_BB_5D | 1 | 0.0% | -3.013% | -3.01% | 0.0% | 0.0 | ❌ No |
| V7_RSI2_ADX_3D | 305 | 59.3% | 0.305% | 122.73% | -25.76% | 1.31 | ❌ No |
| V8_TRIPLE_RSI_5D | 20 | 35.0% | -0.073% | -3.37% | -24.65% | 0.96 | ❌ No |

---
## Accuracy Improvement vs V4 Baseline

| Strategy | IS Win Rate | OOS Win Rate | IS Profit Factor | OOS PF | Delta vs V4 |
|---|---|---|---|---|---|
| V1_RSI14_EMA200_3D | 50.0% | 0.0% | 1.13 | 0.0 | IS WR -7.4pp, IS PF -0.9, OOS WR -49.3pp vs V4 |
| V3_RSI2_EMA200_3D | 56.9% | 59.2% | 1.02 | 1.34 | IS WR -0.5pp, IS PF -1.0, OOS WR +9.9pp vs V4 |
| V4_RSI14_DEEP_5D | 57.4% | 49.3% | 2.04 | 1.21 | IS WR +0.0pp, IS PF +0.0, OOS WR +0.0pp vs V4 |
| V5_RSI14_ADX_5D | 54.9% | 45.4% | 1.89 | 1.05 | IS WR -2.5pp, IS PF -0.2, OOS WR -3.9pp vs V4 |
| V6_RSI14_BB_5D | 50.0% | 0.0% | 0.93 | 0.0 | IS WR -7.4pp, IS PF -1.1, OOS WR -49.3pp vs V4 |
| V7_RSI2_ADX_3D | 56.7% | 59.3% | 0.99 | 1.31 | IS WR -0.7pp, IS PF -1.1, OOS WR +10.0pp vs V4 |
| V8_TRIPLE_RSI_5D | 50.0% | 35.0% | 1.31 | 0.96 | IS WR -7.4pp, IS PF -0.7, OOS WR -14.3pp vs V4 |

---
## Filter Criteria

- Minimum total IS trades: ≥ 50
- Minimum IS profit factor: ≥ 1.1
- Minimum IS win rate: ≥ 50.0%
- Minimum OOS trades: ≥ 10
- Minimum OOS profit factor: ≥ 1.0

---
## Strategy Filter Results

### ❌ V1_RSI14_EMA200_3D — ELIMINATED
Reasons: too few IS trades (2); too few OOS trades (1).

### ❌ V3_RSI2_EMA200_3D — ELIMINATED
Reasons: IS PF too low (1.02).

### ✅ V4_RSI14_DEEP_5D — SURVIVED
Passed all filters. IS WR 57.4% / PF 2.04, OOS PF 1.21.

### ✅ V5_RSI14_ADX_5D — SURVIVED
Passed all filters. IS WR 54.9% / PF 1.89, OOS PF 1.05.

### ❌ V6_RSI14_BB_5D — ELIMINATED
Reasons: too few IS trades (2); IS PF too low (0.93); too few OOS trades (1).

### ❌ V7_RSI2_ADX_3D — ELIMINATED
Reasons: IS PF too low (0.99).

### ❌ V8_TRIPLE_RSI_5D — ELIMINATED
Reasons: too few IS trades (2); OOS PF < 1 (0.96).

---
## Top 20 Stocks per Surviving Strategy

### V4_RSI14_DEEP_5D
| Ticker | Trades | Win Rate | Profit Factor | Total Return % |
|---|---|---|---|---|
| ADANIENT.NS | 2 | 100.0% | 99.0 | 13.81% |
| ADANIGREEN.NS | 2 | 100.0% | 99.0 | 35.38% |
| AUBANK.NS | 3 | 100.0% | 99.0 | 5.77% |
| AXISBANK.NS | 2 | 100.0% | 99.0 | 4.48% |
| BALRAMCHIN.NS | 2 | 100.0% | 99.0 | 15.91% |
| BANDHANBNK.NS | 2 | 100.0% | 99.0 | 3.57% |
| BANKINDIA.NS | 2 | 100.0% | 99.0 | 8.01% |
| BHARATFORG.NS | 2 | 100.0% | 99.0 | 4.12% |
| BHEL.NS | 3 | 100.0% | 99.0 | 13.98% |
| CASTROLIND.NS | 2 | 100.0% | 99.0 | 3.34% |
| COHANCE.NS | 3 | 100.0% | 99.0 | 15.38% |
| CRAFTSMAN.NS | 3 | 100.0% | 99.0 | 18.91% |
| ENDURANCE.NS | 2 | 100.0% | 99.0 | 7.94% |
| GMDCLTD.NS | 3 | 100.0% | 99.0 | 17.63% |
| GODREJPROP.NS | 2 | 100.0% | 99.0 | 15.26% |
| HINDALCO.NS | 2 | 100.0% | 99.0 | 7.79% |
| HINDUNILVR.NS | 3 | 100.0% | 99.0 | 2.85% |
| HINDZINC.NS | 2 | 100.0% | 99.0 | 7.01% |
| INFY.NS | 2 | 100.0% | 99.0 | 1.38% |
| INGERRAND.NS | 2 | 100.0% | 99.0 | 6.25% |

### V5_RSI14_ADX_5D
| Ticker | Trades | Win Rate | Profit Factor | Total Return % |
|---|---|---|---|---|
| ACC.NS | 2 | 100.0% | 99.0 | 9.63% |
| ADANIENT.NS | 2 | 100.0% | 99.0 | 13.81% |
| ADANIGREEN.NS | 2 | 100.0% | 99.0 | 35.38% |
| AUBANK.NS | 3 | 100.0% | 99.0 | 5.77% |
| BALRAMCHIN.NS | 2 | 100.0% | 99.0 | 15.91% |
| BANDHANBNK.NS | 2 | 100.0% | 99.0 | 3.57% |
| BANKINDIA.NS | 2 | 100.0% | 99.0 | 8.01% |
| BHARATFORG.NS | 2 | 100.0% | 99.0 | 4.12% |
| BHEL.NS | 3 | 100.0% | 99.0 | 13.98% |
| CASTROLIND.NS | 2 | 100.0% | 99.0 | 3.34% |
| COHANCE.NS | 3 | 100.0% | 99.0 | 15.38% |
| CRAFTSMAN.NS | 3 | 100.0% | 99.0 | 18.91% |
| ELGIEQUIP.NS | 2 | 100.0% | 99.0 | 5.78% |
| GODREJPROP.NS | 2 | 100.0% | 99.0 | 15.26% |
| HINDALCO.NS | 2 | 100.0% | 99.0 | 7.79% |
| HINDUNILVR.NS | 2 | 100.0% | 99.0 | 2.1% |
| INFY.NS | 2 | 100.0% | 99.0 | 1.38% |
| INGERRAND.NS | 2 | 100.0% | 99.0 | 6.25% |
| INOXWIND.NS | 2 | 100.0% | 99.0 | 10.7% |
| IOC.NS | 3 | 100.0% | 99.0 | 9.05% |

---
## Known Limitations

1. **No Open price** — entry is next bar's Close (slight look-ahead vs true next-open execution).
2. **Survivorship bias** — universe is today's top-N NSE stocks by market cap; delisted stocks excluded.
3. **Single position** — one trade at a time per stock; no portfolio-level correlation management.
4. **Limited data** — ~500 trading days per stock means limited statistical confidence.
5. **EMA200 warm-up** — strategies with EMA200 filter skip stocks with < 200 bars.
6. **No gap risk** — overnight gaps from corporate events are not modelled separately.

---
## Next Steps

1. Forward-test surviving strategies on paper trades via Flask watchlist UI.
2. Wire V8_TRIPLE_RSI_5D into `trial_run.py` as a new confirmed S-signal.
3. Extend data to 5+ years for higher statistical confidence on low-frequency strategies.
4. Add VIX<18 filter (Mode B) — backtested 71% win rate when VIX below 18.

---

> *Educational only — not financial advice. Backtested/paper analysis only.*