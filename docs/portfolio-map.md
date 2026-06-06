# Portfolio Map

This page describes the whole research portfolio. Individual strategy logic maps live inside each project page.

## Role Map

| Role | Line | Public Interpretation |
|---|---|---|
| Flagship research line | Convertible Bonds | Most mature line; evidence chain from market fit to sealed pre-live candidate |
| Flagship research line | Crypto Spot Long-Only | Public-data line showing high-volatility market selection, baseline testing, robustness, and failure rules |
| Candidate | Smart DCA | Accumulation framework under observation; documented but not treated as a finished public code appendix |
| Supporting line | ETF Stabilizer | Allocation and drawdown-control sleeve; not positioned as standalone alpha |
| Portfolio bridge | CB + ETF | Portfolio construction evidence connecting the convertible-bond core and ETF stabilizer |
| Archive / pre-research | A-share Small-cap and failed modules | Evidence of triage discipline and explicit non-promotion decisions |

## Public Logic

```mermaid
flowchart LR
    A["Market Fit and Personal Capital Boundary"] --> B["Baseline Return Source"]
    B --> C["Costs, Execution, and Robustness"]
    C --> D{"Decision"}
    D --> E["Promote / Pre-live Candidate"]
    D --> F["Candidate / Observation"]
    D --> G["Archive / Do Not Promote"]

    E --> CB["Convertible Bonds"]
    E --> CR["Crypto Spot Long-Only"]
    F --> SD["Smart DCA"]
    F --> ETF["ETF Stabilizer"]
    G --> AS["A-share Small-cap Archive"]
    G --> FAIL["Failed Crypto and CB Defense Modules"]
```

## Reading Boundaries

- Convertible Bonds and Crypto are the two flagship public research lines.
- ETF is a supporting stabilizer line and portfolio-construction evidence.
- CB + ETF Bridge is only the bridge between the convertible-bond core and ETF sleeve.
- Smart DCA is a candidate accumulation framework, not an equal-strength flagship line.
- Archives are part of the work, because they show what was tested and deliberately not promoted.
