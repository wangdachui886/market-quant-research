from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from pandas.io.stata import StataReader


CSV_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "gbk")
STANDARD_QUARTER_ENDS = {"03-31", "06-30", "09-30", "12-31"}


@dataclass
class MarketAudit:
    market_dir: str
    stock_file_counts: dict[str, int]
    stock_code_set_diffs: dict[str, dict[str, int]]
    stock_latest_date_top: dict[str, list[tuple[str, int]]]
    stock_first_date_minmax: dict[str, list[str]]
    stock_last_date_minmax: dict[str, list[str]]
    daily_file_counts: dict[str, int]
    daily_date_set_diffs: dict[str, dict[str, int]]
    daily_date_minmax: dict[str, list[str]]
    daily_year_counts: dict[str, dict[str, int]]
    daily_header_variants: dict[str, dict[str, int]]
    daily_missing_margin_col_files: dict[str, list[str]]
    recent_daily_gaps: dict[str, list[str]]
    recent_daily_sample: dict[str, Any]
    adjusted_price_null_samples: dict[str, list[dict[str, Any]]]


@dataclass
class FinanceTableAudit:
    path: str
    rows: int
    unique_codes: int
    date_min: str | None
    date_max: str | None
    bad_dates: int
    duplicate_key_rows: int | None
    key_columns: list[str]
    month_day_top: dict[str, int]
    typrep_counts: dict[str, int] | None
    source_counts: dict[str, int] | None
    ifcorrect_counts: dict[str, int] | None
    annodt_min: str | None
    annodt_max: str | None
    annodt_missing: int | None


@dataclass
class FinanceAudit:
    finance_dir: str
    top_level_tables: list[FinanceTableAudit]
    annual_annodt_table: FinanceTableAudit | None
    raw_table_summaries: list[FinanceTableAudit]
    finance_market_code_diffs: dict[str, dict[str, Any]]


def decode_line(raw: bytes) -> str:
    for enc in CSV_ENCODINGS:
        try:
            return raw.decode(enc).strip("\r\n")
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace").strip("\r\n")


def read_last_line(path: Path, block_size: int = 4096) -> str:
    with path.open("rb") as fh:
        fh.seek(0, 2)
        pos = fh.tell()
        data = b""
        while pos > 0:
            read_size = min(block_size, pos)
            pos -= read_size
            fh.seek(pos)
            data = fh.read(read_size) + data
            lines = data.splitlines()
            if len(lines) >= 2 or pos == 0:
                return decode_line(lines[-1]) if lines else ""
    return ""


def read_first_line(path: Path) -> str:
    with path.open("rb") as fh:
        return decode_line(fh.readline())


def parse_csv_line(line: str) -> list[str]:
    return next(csv.reader([line])) if line else []


def normalize_code(value: Any) -> str:
    text = str(value).strip()
    if re.fullmatch(r"\d+(\.0)?", text):
        text = text.split(".")[0]
    return text.zfill(6) if text.isdigit() else text


def find_data_dirs(data_root: Path) -> tuple[Path, Path]:
    dirs = [p for p in data_root.iterdir() if p.is_dir()]
    finance_candidates = [p for p in dirs if p.name.startswith("C17") or list(p.glob("*.dta"))]
    if not finance_candidates:
        raise FileNotFoundError(f"Cannot find finance data directory under {data_root}")
    finance_dir = finance_candidates[0]
    market_candidates = [p for p in dirs if p != finance_dir]
    if not market_candidates:
        raise FileNotFoundError(f"Cannot find market data directory under {data_root}")
    return market_candidates[0], finance_dir


def find_market_roots(market_dir: Path) -> tuple[Path, Path]:
    children = [p for p in market_dir.iterdir() if p.is_dir()]
    stock_root = None
    for child in children:
        for sub in child.iterdir():
            if sub.is_dir() and any(sub.glob("000001_*.csv")):
                stock_root = child
                break
        if stock_root is not None:
            break
    if stock_root is None:
        raise FileNotFoundError("Cannot find per-stock market files")
    daily_roots = [p for p in children if p != stock_root]
    if not daily_roots:
        raise FileNotFoundError("Cannot find per-day market files")
    return stock_root, daily_roots[0]


def csv_header_counts(files: list[Path]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for file in files:
        header = parse_csv_line(read_first_line(file))
        counts[str(len(header))] += 1
    return counts


def audit_market(data_root: Path) -> tuple[MarketAudit, set[str]]:
    market_dir, _ = find_data_dirs(data_root)
    stock_root, daily_root = find_market_roots(market_dir)
    stock_adj_dirs = sorted([p for p in stock_root.iterdir() if p.is_dir()], key=lambda p: p.name)
    daily_adj_dirs = sorted([p for p in daily_root.iterdir() if p.is_dir()], key=lambda p: p.name)

    stock_file_counts: dict[str, int] = {}
    stock_code_sets: dict[str, set[str]] = {}
    stock_latest_date_top: dict[str, list[tuple[str, int]]] = {}
    stock_first_date_minmax: dict[str, list[str]] = {}
    stock_last_date_minmax: dict[str, list[str]] = {}

    for adj_dir in stock_adj_dirs:
        files = sorted(adj_dir.glob("*.csv"))
        codes = {file.name.split("_")[0] for file in files}
        stock_file_counts[adj_dir.name] = len(files)
        stock_code_sets[adj_dir.name] = codes
        first_dates: list[str] = []
        last_dates: list[str] = []
        for file in files:
            first_row = parse_csv_line(read_first_line(file))
            last_row = parse_csv_line(read_last_line(file))
            if len(first_row) > 1 and first_row[0] != "日期":
                first_dates.append(first_row[0])
            elif len(first_row) > 1:
                # Read the first data row only when needed.
                with file.open("rb") as fh:
                    fh.readline()
                    first_data = parse_csv_line(decode_line(fh.readline()))
                    if first_data:
                        first_dates.append(first_data[0])
            if len(last_row) > 1 and last_row[0] != "日期":
                last_dates.append(last_row[0])
        stock_latest_date_top[adj_dir.name] = Counter(last_dates).most_common(10)
        stock_first_date_minmax[adj_dir.name] = [min(first_dates), max(first_dates)] if first_dates else []
        stock_last_date_minmax[adj_dir.name] = [min(last_dates), max(last_dates)] if last_dates else []

    first_stock_name = next(iter(stock_code_sets))
    first_stock_set = stock_code_sets[first_stock_name]
    stock_code_set_diffs = {
        name: {
            "missing_vs_first": len(first_stock_set - codes),
            "extra_vs_first": len(codes - first_stock_set),
        }
        for name, codes in stock_code_sets.items()
    }

    daily_file_counts: dict[str, int] = {}
    daily_date_sets: dict[str, set[str]] = {}
    daily_date_minmax: dict[str, list[str]] = {}
    daily_year_counts: dict[str, dict[str, int]] = {}
    daily_header_variants: dict[str, dict[str, int]] = {}
    daily_missing_margin_col_files: dict[str, list[str]] = {}
    recent_daily_gaps: dict[str, list[str]] = {}

    for adj_dir in daily_adj_dirs:
        files = sorted(adj_dir.glob("*/*.csv"))
        dates = {file.name.split("_")[0] for file in files}
        daily_file_counts[adj_dir.name] = len(files)
        daily_date_sets[adj_dir.name] = dates
        daily_date_minmax[adj_dir.name] = [min(dates), max(dates)] if dates else []
        daily_year_counts[adj_dir.name] = dict(sorted(Counter(date[:4] for date in dates).items()))
        headers = csv_header_counts(files)
        daily_header_variants[adj_dir.name] = dict(headers)
        daily_missing_margin_col_files[adj_dir.name] = [
            file.name for file in files if len(parse_csv_line(read_first_line(file))) == 37
        ]
        recent_2026 = sorted(date for date in dates if date.startswith("2026-"))
        gaps: list[str] = []
        for left, right in zip(recent_2026, recent_2026[1:]):
            if left < "2026-04-01":
                continue
            left_dt = pd.Timestamp(left)
            right_dt = pd.Timestamp(right)
            if (right_dt - left_dt).days > 4:
                gaps.append(f"{left} -> {right}")
        recent_daily_gaps[adj_dir.name] = gaps

    first_daily_name = next(iter(daily_date_sets))
    first_daily_set = daily_date_sets[first_daily_name]
    daily_date_set_diffs = {
        name: {
            "missing_vs_first": len(first_daily_set - dates),
            "extra_vs_first": len(dates - first_daily_set),
        }
        for name, dates in daily_date_sets.items()
    }

    recent_daily_sample: dict[str, Any] = {}
    adjusted_price_null_samples: dict[str, list[dict[str, Any]]] = {}
    for adj_dir in daily_adj_dirs:
        sample_file = next(iter(sorted((adj_dir / "2026").glob("2026-05-14_*.csv"))), None)
        if sample_file is None:
            continue
        df = pd.read_csv(sample_file, encoding="utf-8-sig", dtype=str)
        codes = df["代码"].map(normalize_code)
        recent_daily_sample[adj_dir.name] = {
            "file": str(sample_file.relative_to(data_root)),
            "rows": int(len(df)),
            "unique_codes": int(codes.nunique()),
            "duplicate_codes": int(len(df) - codes.nunique()),
            "columns": int(len(df.columns)),
            "st_counts": df["是否ST"].value_counts(dropna=False).head(10).to_dict()
            if "是否ST" in df.columns
            else {},
            "limit_up_counts": df["是否涨停"].value_counts(dropna=False).head(10).to_dict()
            if "是否涨停" in df.columns
            else {},
        }
        price_cols = [col for col in ["开盘价", "最高价", "最低价", "收盘价", "前收盘价"] if col in df.columns]
        null_rows = df[df[price_cols].isna().any(axis=1)] if price_cols else pd.DataFrame()
        adjusted_price_null_samples[adj_dir.name] = (
            null_rows[["日期", "代码", "名称", "所属行业", "上市时间"] + price_cols]
            .head(10)
            .to_dict(orient="records")
            if len(null_rows)
            else []
        )

    raw_like_dir = next((p for p in daily_adj_dirs if p.name == "不复权"), daily_adj_dirs[0])
    market_codes = {file.name.split("_")[0] for file in (stock_adj_dirs[0]).glob("*.csv")}
    if raw_like_dir.name != stock_adj_dirs[0].name:
        market_codes = {file.name.split("_")[0] for file in stock_adj_dirs[0].glob("*.csv")}

    return (
        MarketAudit(
            market_dir=str(market_dir.relative_to(data_root)),
            stock_file_counts=stock_file_counts,
            stock_code_set_diffs=stock_code_set_diffs,
            stock_latest_date_top=stock_latest_date_top,
            stock_first_date_minmax=stock_first_date_minmax,
            stock_last_date_minmax=stock_last_date_minmax,
            daily_file_counts=daily_file_counts,
            daily_date_set_diffs=daily_date_set_diffs,
            daily_date_minmax=daily_date_minmax,
            daily_year_counts=daily_year_counts,
            daily_header_variants=daily_header_variants,
            daily_missing_margin_col_files=daily_missing_margin_col_files,
            recent_daily_gaps=recent_daily_gaps,
            recent_daily_sample=recent_daily_sample,
            adjusted_price_null_samples=adjusted_price_null_samples,
        ),
        market_codes,
    )


def stata_columns(path: Path) -> list[str]:
    reader = StataReader(str(path))
    return list(reader.variable_labels().keys())


def audit_finance_table(path: Path, data_root: Path) -> FinanceTableAudit:
    cols = stata_columns(path)
    use = [
        col
        for col in [
            "Stkcd",
            "ShortName",
            "Accper",
            "Typrep",
            "Source",
            "IfCorrect",
            "DeclareDate",
            "Annodt",
            "StateType",
        ]
        if col in cols
    ]
    if "Stkcd" not in use or "Accper" not in use:
        raise ValueError(f"Missing Stkcd/Accper in {path}")
    df = pd.read_stata(str(path), columns=use, convert_categoricals=False)
    dates = pd.to_datetime(df["Accper"], errors="coerce")
    month_day = dates.dt.strftime("%m-%d")
    key_cols = [col for col in ["Stkcd", "Accper", "Typrep", "Source", "StateType"] if col in df.columns]
    duplicate_key_rows = int(df.duplicated(key_cols).sum()) if key_cols else None

    annodt_min = annodt_max = None
    annodt_missing = None
    if "Annodt" in df.columns:
        ann_dates = pd.to_datetime(df["Annodt"], errors="coerce")
        annodt_min = str(ann_dates.min().date()) if ann_dates.notna().any() else None
        annodt_max = str(ann_dates.max().date()) if ann_dates.notna().any() else None
        annodt_missing = int(ann_dates.isna().sum())

    def counts(col: str) -> dict[str, int] | None:
        if col not in df.columns:
            return None
        return {str(k): int(v) for k, v in df[col].astype(str).value_counts().head(20).items()}

    return FinanceTableAudit(
        path=str(path.relative_to(data_root)),
        rows=int(len(df)),
        unique_codes=int(df["Stkcd"].map(normalize_code).nunique()),
        date_min=str(dates.min().date()) if dates.notna().any() else None,
        date_max=str(dates.max().date()) if dates.notna().any() else None,
        bad_dates=int(dates.isna().sum()),
        duplicate_key_rows=duplicate_key_rows,
        key_columns=key_cols,
        month_day_top={str(k): int(v) for k, v in month_day.value_counts().head(20).items()},
        typrep_counts=counts("Typrep"),
        source_counts=counts("Source"),
        ifcorrect_counts=counts("IfCorrect"),
        annodt_min=annodt_min,
        annodt_max=annodt_max,
        annodt_missing=annodt_missing,
    )


def audit_finance(data_root: Path, market_codes: set[str]) -> FinanceAudit:
    _, finance_dir = find_data_dirs(data_root)
    top_level_paths = sorted(finance_dir.glob("*.dta"), key=lambda p: p.stat().st_size)
    top_level_tables = [audit_finance_table(path, data_root) for path in top_level_paths]

    raw_root = next((p for p in finance_dir.iterdir() if p.is_dir()), None)
    raw_table_paths = sorted(raw_root.glob("*/*.dta"), key=lambda p: str(p)) if raw_root else []
    raw_table_summaries: list[FinanceTableAudit] = []
    annual_annodt_table: FinanceTableAudit | None = None
    for path in raw_table_paths:
        try:
            summary = audit_finance_table(path, data_root)
        except ValueError:
            continue
        raw_table_summaries.append(summary)
        if path.name == "FAR_Finidx.dta":
            annual_annodt_table = summary

    finance_market_code_diffs: dict[str, dict[str, Any]] = {}
    for path in top_level_paths:
        df = pd.read_stata(str(path), columns=["Stkcd"], convert_categoricals=False)
        finance_codes = set(df["Stkcd"].map(normalize_code))
        finance_market_code_diffs[str(path.relative_to(data_root))] = {
            "finance_codes": len(finance_codes),
            "market_missing_finance_count": len(market_codes - finance_codes),
            "finance_not_market_count": len(finance_codes - market_codes),
            "market_missing_finance_examples": sorted(market_codes - finance_codes)[:30],
            "finance_not_market_examples": sorted(finance_codes - market_codes)[:30],
        }

    return FinanceAudit(
        finance_dir=str(finance_dir.relative_to(data_root)),
        top_level_tables=top_level_tables,
        annual_annodt_table=annual_annodt_table,
        raw_table_summaries=raw_table_summaries,
        finance_market_code_diffs=finance_market_code_diffs,
    )


def render_markdown(audit: dict[str, Any]) -> str:
    market = audit["market"]
    finance = audit["finance"]
    lines: list[str] = []
    lines.append("# Data Audit Summary")
    lines.append("")
    lines.append("## Market Data")
    lines.append("")
    lines.append(f"- Market directory: `{market['market_dir']}`")
    lines.append(f"- Per-stock file counts: `{market['stock_file_counts']}`")
    lines.append(f"- Per-day file counts: `{market['daily_file_counts']}`")
    lines.append(f"- Per-day date ranges: `{market['daily_date_minmax']}`")
    lines.append(f"- Per-stock latest date top: `{market['stock_latest_date_top']}`")
    lines.append(f"- Daily header variants: `{market['daily_header_variants']}`")
    lines.append(f"- Files missing `是否融资融券`: `{market['daily_missing_margin_col_files']}`")
    lines.append(f"- Recent daily gaps: `{market['recent_daily_gaps']}`")
    lines.append("")
    lines.append("Recent daily sample:")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(market["recent_daily_sample"], ensure_ascii=False, indent=2))
    lines.append("```")
    lines.append("")
    lines.append("Adjusted-price null samples:")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(market["adjusted_price_null_samples"], ensure_ascii=False, indent=2))
    lines.append("```")
    lines.append("")
    lines.append("## Finance Data")
    lines.append("")
    lines.append(f"- Finance directory: `{finance['finance_dir']}`")
    lines.append("")
    lines.append("Top-level tables:")
    lines.append("")
    for table in finance["top_level_tables"]:
        lines.append(
            "- `{path}`: rows={rows}, codes={unique_codes}, dates={date_min}..{date_max}, "
            "dup_key={duplicate_key_rows}, month_days={month_day_top}".format(**table)
        )
    lines.append("")
    if finance["annual_annodt_table"]:
        table = finance["annual_annodt_table"]
        lines.append(
            "Annual PIT anchor: `{path}`, Annodt={annodt_min}..{annodt_max}, missing={annodt_missing}".format(
                **table
            )
        )
    else:
        lines.append("Annual PIT anchor: not found.")
    lines.append("")
    lines.append("Finance vs market code diffs:")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(finance["finance_market_code_diffs"], ensure_ascii=False, indent=2))
    lines.append("```")
    lines.append("")
    lines.append("Raw finance table summaries:")
    lines.append("")
    for table in finance["raw_table_summaries"]:
        lines.append(
            "- `{path}`: rows={rows}, codes={unique_codes}, dates={date_min}..{date_max}, "
            "dup_key={duplicate_key_rows}, key={key_columns}, month_days={month_day_top}".format(**table)
        )
    lines.append("")
    lines.append("## Initial Research Data Verdict")
    lines.append("")
    lines.append("- Use per-day unadjusted market files as the primary market port.")
    lines.append("- Do not rely on the last few trading days until the missing dates and column drift are resolved.")
    lines.append("- Use annual finance only when `Annodt` is available for PIT alignment.")
    lines.append("- Treat quarterly finance as observation until a reliable quarterly announcement date is available.")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit raw A-share small-cap data ports.")
    parser.add_argument("--data-root", default="data", help="Path to raw data root.")
    parser.add_argument("--output-dir", default="outputs/data_audit", help="Directory for audit outputs.")
    args = parser.parse_args()

    data_root = Path(args.data_root).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    market_audit, market_codes = audit_market(data_root)
    finance_audit = audit_finance(data_root, market_codes)
    audit = {
        "market": asdict(market_audit),
        "finance": {
            "finance_dir": finance_audit.finance_dir,
            "top_level_tables": [asdict(table) for table in finance_audit.top_level_tables],
            "annual_annodt_table": asdict(finance_audit.annual_annodt_table)
            if finance_audit.annual_annodt_table
            else None,
            "raw_table_summaries": [asdict(table) for table in finance_audit.raw_table_summaries],
            "finance_market_code_diffs": finance_audit.finance_market_code_diffs,
        },
    }

    json_path = output_dir / "data_audit_summary.json"
    md_path = output_dir / "data_audit_summary.md"
    json_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(audit), encoding="utf-8")

    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")


if __name__ == "__main__":
    main()
