# Portfolio Bridge

![Portfolio bridge](../../assets/portfolio-bridge/portfolio_bridge.svg)

## One-line Thesis

Convertible bonds carry the return engine. ETF makes the curve easier to hold.

可转债承担收益引擎，ETF 让资金曲线更可持有。

## Why This Page Exists

The three public hubs have different roles:

- Crypto shows high-volatility market structure, Web3 market understanding, and strategy triage.
- Convertible bonds show low-frequency quant research, sample cleaning, execution assumptions, cost, robustness, and archive discipline.
- ETF shows portfolio-level thinking: not only searching for return, but asking whether the capital curve can be held.

Together, they make the portfolio stronger than any single strategy.

## Combined Portfolio

| Module | Role | CAGR | MDD | Calmar |
|---|---|---:|---:|---:|
| Convertible bond `top12_keep37` | Main return engine | 18.60% | -18.76% | 0.99 |
| ETF Stabilizer | Allocation and drawdown-control sleeve | 6.91% | -10.59% | 0.65 |
| 70% CB + 30% ETF Stabilizer | Combined portfolio | 15.49% | -10.77% | 1.44 |

The bridge is not a performance trick. It makes the trade-off visible: some CAGR is exchanged for a much lower drawdown and a higher Calmar ratio.

## Monitoring Focus

| Layer | Monitor |
|---|---|
| Convertible bonds | Credit events, strong-call data, liquidity, rank drift |
| ETF sleeve | Monthly signal state, cross-border premium, Treasury/Gold exposure |
| Combined portfolio | Drawdown overlap, correlation, recovery speed, execution cost |

## Code And Evidence Anchors

- [Convertible Bonds Code](../../code/convertible-bonds/README.md)
- [ETF Stabilizer Code](../../code/etf-stabilizer/README.md)
- Public evidence index: [Evidence Index](../../docs/evidence-index.md)
- Notion bridge: Convertible Bond Core + ETF Stabilizer
