# ETF Stabilizer Code Appendix

This appendix contains the executable target-weight logic for ETF Stabilizer V1.1.

## Public Role

ETF Stabilizer is not an independent alpha engine. It is a 30% sleeve beside the convertible-bond core.

Default sleeve:

```text
20% CSI300 ETF
20% S&P 500 ETF
40% Treasury ETF
20% Gold ETF
```

If an equity sleeve fails its 12M risk switch, that failed 20% sleeve moves into:

```text
80% Treasury ETF
20% Gold ETF
```

## Files

| File | Role |
|---|---|
| `etf_stabilizer_v1.py` | Target-weight logic, premium gate, portfolio overlay weights |
| `etf_stabilizer_v1_params.json` | Sanitized public parameter and research-summary record |

## Usage Sketch

```python
from etf_stabilizer_v1 import target_weights

weights = target_weights(close_prices, signal_date, nav_prices=nav_prices)
```

The returned weights are ETF-sleeve internal weights. Total portfolio integration is handled separately by the 70% convertible-bond / 30% ETF bridge.

