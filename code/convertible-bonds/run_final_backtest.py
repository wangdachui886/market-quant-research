from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cb_pre_live_core import FinalConfig, run_backtest


def main() -> None:
    cfg = FinalConfig()
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    result = run_backtest(cfg)
    result["daily"].to_csv(cfg.output_dir / "final_daily_returns.csv", index=False, encoding="utf-8-sig")
    result["holdings"].to_csv(cfg.output_dir / "final_holdings.csv", index=False, encoding="utf-8-sig")
    result["ranks"].to_csv(cfg.output_dir / "final_rank_audit_raw.csv", index=False, encoding="utf-8-sig")
    (cfg.output_dir / "final_metrics.json").write_text(json.dumps(result["metrics"], ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["metrics"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
