#!/usr/bin/env python3
"""收盘后模型选股器。

数据组合：
- 同花顺行情中心：当日涨幅、量比、换手率；
- 东方财富数据中心：总市值、上市日期、风险警示；
- 东方财富日 K：最近 60 个交易日的强势记录。

默认模型口径：
上市满 1 年；非 ST/退市风险；非北交所/科创板；当日涨幅 > 5%；
量比 1~6；换手率 3%~10%；总市值 < 350 亿元；股价 3~50 元；
最近 60 个交易日内至少一次单日涨幅 > 5%（默认不含当天）。
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

EM_DATACENTER = "https://datacenter-web.eastmoney.com/api/data/v1/get"
EM_KLINE = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
EM_F10 = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
THS_BASE = "https://q.10jqka.com.cn"
THS_PAGE_PATH = "/index/index/board/all/field/zdf/order/desc/page/{page}/ajax/1/"
SH_TZ = timezone(timedelta(hours=8))
QUOTE_FIELDS = "f12,f14,f2,f3,f8,f10,f20,f21,f26,f100,f124"
KLINE_FIELDS1 = "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13"
KLINE_FIELDS2 = "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
ALLOWED_PREFIXES = ("000", "001", "002", "003", "300", "301", "600", "601", "603", "605")
RISK_MARKERS = ("ST", "退")
CSV_FIELDS = [
    "code", "name", "market", "quote_date", "price", "pct_chg", "volume_ratio",
    "turnover", "total_mv_yi", "listing_date", "industry", "up5_count",
    "last_up5_date", "reason",
]

def parse_number(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    text = str(value).strip().replace(",", "")
    if text in {"", "-", "--", "None", "nan"}:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def parse_date(value: object) -> date | None:
    if value is None:
        return None
    text = str(value).strip()[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def fetch_text(url: str, *, headers: dict[str, str] | None = None, retries: int = 3, pause: float = 0.35) -> str:
    request_headers = {
        "Accept": "application/json,text/html,*/*",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
        ),
    }
    if headers:
        request_headers.update(headers)
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            request = Request(url, headers=request_headers)
            with urlopen(request, timeout=25) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                return response.read().decode(charset, errors="replace")
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(pause * attempt)
    raise RuntimeError(f"请求失败: {url}; {last_error}")


def fetch_json(url: str, **kwargs: object) -> dict:
    return json.loads(fetch_text(url, **kwargs))


def fetch_datacenter(
    report_name: str,
    *,
    columns: str = "ALL",
    filter_expr: str | None = None,
    page_size: int = 500,
    sort_columns: str | None = None,
    sort_types: int = -1,
    max_pages: int = 50,
) -> list[dict]:
    rows: list[dict] = []
    total = 0
    for page in range(1, max_pages + 1):
        params = {
            "reportName": report_name,
            "columns": columns,
            "pageNumber": page,
            "pageSize": page_size,
            "source": "WEB",
            "client": "WEB",
        }
        if filter_expr:
            params["filter"] = filter_expr
        if sort_columns:
            params["sortColumns"] = sort_columns
            params["sortTypes"] = sort_types
        payload = fetch_json(f"{EM_DATACENTER}?{urlencode(params)}")
        result = payload.get("result") or {}
        batch = result.get("data") or []
        total = int(result.get("count") or total or 0)
        rows.extend(batch)
        if not batch or len(rows) >= total:
            break
    return rows


def get_node_path(explicit: str | None) -> str:
    if explicit:
        return explicit
    found = shutil.which("node")
    if found:
        return found
    bundled = Path(
        r"C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime"
        r"\dependencies\node\bin\node.exe"
    )
    if bundled.exists():
        return str(bundled)
    raise RuntimeError("未找到 node，需要安装 Node.js 以生成同花顺访问 token。")


def get_hexin_token(node_path: str) -> str:
    bundle = Path(__file__).resolve().parent / "hexin-v.bundle.js"
    if not bundle.exists():
        raise RuntimeError(f"缺少同花顺 token 文件: {bundle}")
    completed = subprocess.run(
        [node_path, str(bundle)],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    token = (completed.stdout or "").strip()
    if completed.returncode != 0 or not token:
        detail = (completed.stderr or "").strip()
        raise RuntimeError(f"同花顺 token 生成失败: {detail or completed.returncode}")
    return token


class ThsTableParser(HTMLParser):
    """只抽取表体中的 <tr><td> 数据。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_body = False
        self.in_row = False
        self.in_cell = False
        self.cell_parts: list[str] = []
        self.row: list[str] = []
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tbody":
            self.in_body = True
        elif self.in_body and tag == "tr":
            self.in_row = True
            self.row = []
        elif self.in_row and tag == "td":
            self.in_cell = True
            self.cell_parts = []

    def handle_data(self, data: str) -> None:
        if self.in_cell:
            self.cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self.in_cell:
            text = html.unescape("".join(self.cell_parts)).strip()
            self.row.append(text)
            self.in_cell = False
        elif tag == "tr" and self.in_row:
            if self.row:
                self.rows.append(self.row)
            self.in_row = False
            self.row = []
        elif tag == "tbody":
            self.in_body = False


def fetch_ths_page(page: int, token: str) -> list[dict]:
    url = THS_BASE + THS_PAGE_PATH.format(page=page)
    text = fetch_text(
        url,
        headers={
            "Referer": f"{THS_BASE}/index/",
            "hexin-v": token,
            "X-Requested-With": "XMLHttpRequest",
        },
    )
    parser = ThsTableParser()
    parser.feed(text)
    rows: list[dict] = []
    for parts in parser.rows:
        if len(parts) < 14:
            continue
        code = str(parts[1]).strip().zfill(6)
        rows.append({
            "code": code,
            "name": str(parts[2]).strip(),
            "price": parse_number(parts[3]),
            "pct_chg": parse_number(parts[4]),
            "turnover": parse_number(parts[7]),
            "volume_ratio": parse_number(parts[8]),
        })
    return rows

def fetch_latest_trade_date() -> date:
    rows = fetch_datacenter(
        "RPT_VALUEANALYSIS_DET",
        columns="TRADE_DATE",
        page_size=1,
        sort_columns="TRADE_DATE",
        sort_types=-1,
        max_pages=1,
    )
    if not rows:
        raise RuntimeError("未能从东方财富获取最新交易日期")
    trade_date = parse_date(rows[0].get("TRADE_DATE"))
    if trade_date is None:
        raise RuntimeError("东方财富交易日期格式异常")
    return trade_date


def fetch_valuation_map(trade_date: date) -> dict[str, dict]:
    rows = fetch_datacenter(
        "RPT_VALUEANALYSIS_DET",
        columns=(
            "SECURITY_CODE,SECURITY_NAME_ABBR,TRADE_DATE,CLOSE_PRICE,CHANGE_RATE,"
            "TOTAL_MARKET_CAP,TOTAL_SHARES,FREE_SHARES_A,TRADE_MARKET,BOARD_NAME"
        ),
        filter_expr=f"(TRADE_DATE='{trade_date.isoformat()}')",
        page_size=500,
        sort_columns="TOTAL_MARKET_CAP",
        sort_types=-1,
    )
    return {
        str(row.get("SECURITY_CODE") or "").zfill(6): row
        for row in rows
        if row.get("SECURITY_CODE")
    }


def fetch_listing_map() -> dict[str, dict]:
    rows = fetch_datacenter(
        "RPTA_APP_IPOAPPLY",
        columns=(
            "SECURITY_CODE,SECURITY_NAME_ABBR,LISTING_DATE,IS_RISKWARNING,"
            "MARKET_TYPE,MARKET_TYPE_NEW,TRADE_MARKET"
        ),
        page_size=500,
        sort_columns="LISTING_DATE",
        sort_types=-1,
    )
    return {
        str(row.get("SECURITY_CODE") or "").zfill(6): row
        for row in rows
        if row.get("SECURITY_CODE")
    }


def is_allowed_code(code: str) -> bool:
    if not code or len(code) != 6 or not code.isdigit():
        return False
    if code.startswith(("688", "689", "920")):
        return False
    return code.startswith(ALLOWED_PREFIXES)


def is_risk_stock(name: str, listing_row: dict | None) -> bool:
    upper_name = name.upper().replace(" ", "")
    if any(marker in upper_name for marker in RISK_MARKERS):
        return True
    if listing_row and str(listing_row.get("IS_RISKWARNING") or "") == "1":
        return True
    market_text = " ".join(
        str((listing_row or {}).get(key) or "")
        for key in ("MARKET_TYPE", "MARKET_TYPE_NEW", "TRADE_MARKET")
    )
    return "风险警示" in market_text or "退市" in market_text


def is_theme_stock_code(code: str) -> bool:
    if not code or len(code) != 6 or not code.isdigit():
        return False
    return not code.startswith(("200", "900"))


def fetch_ths_candidates(
    token: str,
    *,
    threshold: float = 5.0,
    allowed_only: bool = True,
    max_pages: int = 40,
) -> list[dict]:
    candidates: list[dict] = []
    for page in range(1, max_pages + 1):
        page_rows = fetch_ths_page(page, token)
        if not page_rows:
            break
        stop = False
        for row in page_rows:
            pct_chg = row.get("pct_chg")
            if pct_chg is None:
                continue
            if pct_chg <= threshold:
                stop = True
                break
            code = row["code"]
            if allowed_only:
                if is_allowed_code(code):
                    candidates.append(row)
            elif is_theme_stock_code(code):
                candidates.append(row)
        if stop:
            break
        time.sleep(0.15)
    return candidates

def current_filter(
    item: dict,
    *,
    as_of: date,
    valuation_map: dict[str, dict],
    listing_map: dict[str, dict],
) -> tuple[dict | None, str | None]:
    code = item["code"]
    name = item["name"]
    valuation = valuation_map.get(code)
    listing = listing_map.get(code)
    if valuation is None:
        return None, "missing_valuation"
    if listing is None:
        return None, "missing_listing"
    if not is_allowed_code(code):
        return None, "market"
    if is_risk_stock(name, listing):
        return None, "risk"

    price = item.get("price")
    pct_chg = item.get("pct_chg")
    turnover = item.get("turnover")
    volume_ratio = item.get("volume_ratio")
    total_mv = parse_number(valuation.get("TOTAL_MARKET_CAP"))
    listing_date = parse_date(listing.get("LISTING_DATE"))
    if None in {price, pct_chg, turnover, volume_ratio, total_mv, listing_date}:
        return None, "missing"
    if (as_of - listing_date).days <= 365:
        return None, "new"
    if not (pct_chg > 5):
        return None, "pct"
    if not (1 < volume_ratio < 6):
        return None, "volume_ratio"
    if not (3 < turnover < 10):
        return None, "turnover"
    if not (3 < price < 50):
        return None, "price"
    if not (total_mv < 350 * 100_000_000):
        return None, "market_cap"

    return {
        "code": code,
        "name": name,
        "market": "SH" if code.startswith("6") else "SZ",
        "quote_date": as_of.isoformat(),
        "price": price,
        "pct_chg": pct_chg,
        "volume_ratio": volume_ratio,
        "turnover": turnover,
        "total_mv_yi": total_mv / 100_000_000,
        "listing_date": listing_date.isoformat(),
        "industry": str(valuation.get("BOARD_NAME") or listing.get("MARKET_TYPE_NEW") or "-"),
    }, None


def fetch_kline(code: str, reference_date: date, days: int = 200) -> list[dict]:
    """从同花顺读取最近日 K，并用相邻收盘价计算单日涨幅。"""
    prefix = "hs" if code.startswith("6") else "sz"
    url = f"http://d.10jqka.com.cn/v6/line/{prefix}_{code}/01/last.js"
    text = fetch_text(
        url,
        headers={"Referer": f"http://stockpage.10jqka.com.cn/{code}/"},
    )
    match = re.search(r"\((.*)\)\s*;?\s*$", text, re.S)
    if not match:
        return []
    payload = json.loads(match.group(1))
    data_text = payload.get("data") or ""
    bars: list[dict] = []
    previous_close: float | None = None
    for record in str(data_text).split(";"):
        parts = record.split(",")
        if len(parts) < 5:
            continue
        try:
            bar_date = datetime.strptime(parts[0], "%Y%m%d").date()
            close = float(parts[4])
        except (ValueError, TypeError):
            continue
        pct_chg = None
        if previous_close and previous_close > 0:
            pct_chg = (close / previous_close - 1) * 100
        previous_close = close
        if bar_date <= reference_date and pct_chg is not None:
            bars.append({"date": bar_date, "pct_chg": pct_chg})
    return bars

def eastmoney_secucode(code: str) -> str:
    if code.startswith(("600", "601", "603", "605", "688", "689")):
        return f"{code}.SH"
    if code.startswith(("000", "001", "002", "003", "300", "301")):
        return f"{code}.SZ"
    return f"{code}.BJ"


def fetch_stock_boards(code: str) -> list[dict]:
    params = {
        "reportName": "RPT_F10_CORETHEME_BOARDTYPE",
        "columns": "BOARD_CODE,BOARD_NAME,BOARD_TYPE,BOARD_LEVEL,BOARD_RANK,IS_PRECISE",
        "filter": f'(SECUCODE="{eastmoney_secucode(code)}")',
        "pageNumber": 1,
        "pageSize": 200,
        "sortTypes": 1,
        "sortColumns": "BOARD_RANK",
        "source": "HSF10",
        "client": "PC",
    }
    payload = fetch_json(f"{EM_F10}?{urlencode(params)}")
    result = payload.get("result") or {}
    return result.get("data") or []


def load_board_cache(cache_path: Path) -> dict[str, list[dict]]:
    if not cache_path.exists():
        return {}
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_board_cache(cache_path: Path, cache: dict[str, list[dict]]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def run_theme_stats(
    as_of: date,
    *,
    token: str,
    threshold: float,
    workers: int,
    cache_dir: Path,
) -> dict:
    print(f"主题统计：获取涨幅大于 {threshold:g}% 的股票...")
    candidate_rows = fetch_ths_candidates(
        token,
        threshold=threshold,
        allowed_only=False,
        max_pages=60,
    )
    stocks = {row["code"]: row for row in candidate_rows}
    cache_path = cache_dir / "boards.json"
    cache = load_board_cache(cache_path)

    missing_codes = [code for code in stocks if code not in cache]
    if missing_codes:
        print(f"主题统计：查询 {len(missing_codes)} 只股票所属行业和概念...")
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = {pool.submit(fetch_stock_boards, code): code for code in missing_codes}
            for future in as_completed(futures):
                code = futures[future]
                try:
                    cache[code] = future.result()
                except Exception as exc:
                    cache[code] = []
                    print(f"[WARN] {code} 板块概念获取失败: {exc}", file=sys.stderr)
        save_board_cache(cache_path, cache)

    sector_counter: Counter[str] = Counter()
    concept_counter: Counter[str] = Counter()
    detail_rows: list[dict] = []
    for code, stock in sorted(stocks.items(), key=lambda item: item[1].get("pct_chg") or 0, reverse=True):
        rows = cache.get(code) or []
        sectors = sorted({
            str(row.get("BOARD_NAME") or "").strip()
            for row in rows
            if str(row.get("BOARD_TYPE") or "").strip() == "行业"
            and str(row.get("BOARD_LEVEL") or "").strip() == "1"
            and str(row.get("BOARD_NAME") or "").strip()
        })
        concepts = sorted({
            str(row.get("BOARD_NAME") or "").strip()
            for row in rows
            if not str(row.get("BOARD_TYPE") or "").strip()
            and str(row.get("IS_PRECISE") or "") == "1"
            and str(row.get("BOARD_NAME") or "").strip()
        })
        sector_counter.update(sectors)
        concept_counter.update(concepts)
        detail_rows.append({
            "code": code,
            "name": stock.get("name") or "",
            "pct_chg": stock.get("pct_chg"),
            "sectors": sectors,
            "concepts": concepts,
        })

    return {
        "as_of": as_of.isoformat(),
        "threshold": threshold,
        "stock_count": len(stocks),
        "top_sectors": [{"name": name, "count": count} for name, count in sector_counter.most_common(10)],
        "top_concepts": [{"name": name, "count": count} for name, count in concept_counter.most_common(10)],
        "details": detail_rows,
    }


def write_theme_outputs(stats: dict, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    as_of = str(stats["as_of"]).replace("-", "")
    json_path = output_dir / f"theme_stats_{as_of}.json"
    csv_path = output_dir / f"theme_membership_{as_of}.csv"
    md_path = output_dir / f"theme_stats_{as_of}.md"

    json_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["code", "name", "pct_chg", "type", "tag"], extrasaction="ignore")
        writer.writeheader()
        for row in stats["details"]:
            for tag in row["sectors"]:
                writer.writerow({**row, "type": "板块", "tag": tag})
            for tag in row["concepts"]:
                writer.writerow({**row, "type": "概念", "tag": tag})

    lines = [
        f"# 板块概念统计 {stats['as_of']}",
        "",
        f"- 涨幅大于 {stats['threshold']:g}% 的股票数：{stats['stock_count']}",
        "- 计数口径：同一只股票命中同一板块/概念只计 1 次。",
        "",
        "## 行业板块前10",
        "",
        "| 排名 | 板块 | 去重股票数 |",
        "|---:|---|---:|",
    ]
    for index, item in enumerate(stats["top_sectors"], 1):
        lines.append(f"| {index} | {item['name']} | {item['count']} |")
    lines.extend(["", "## 概念前10", "", "| 排名 | 概念 | 去重股票数 |", "|---:|---|---:|"])
    for index, item in enumerate(stats["top_concepts"], 1):
        lines.append(f"| {index} | {item['name']} | {item['count']} |")
    lines.extend(["", "> 概念采用东方财富 F10 精确概念；板块只统计一级行业，不再包含地区板块。", ""])
    md_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"主题JSON: {json_path}")
    print(f"主题CSV : {csv_path}")
    print(f"主题MD  : {md_path}")

def history_filter(item: dict, as_of: date, include_today: bool) -> dict | None:
    bars = fetch_kline(item["code"], as_of)
    bars = [bar for bar in bars if bar["date"] <= as_of]
    if not bars:
        return None
    if include_today:
        window = bars[-60:]
    else:
        if bars[-1]["date"] == as_of:
            bars = bars[:-1]
        window = bars[-59:]
    if len(window) < 50:
        return None
    up5_bars = [bar for bar in window if bar["pct_chg"] is not None and bar["pct_chg"] > 5]
    if not up5_bars:
        return None
    item = dict(item)
    item["up5_count"] = len(up5_bars)
    item["last_up5_date"] = up5_bars[-1]["date"].isoformat()
    item["reason"] = (
        f"涨幅{item['pct_chg']:.2f}% > 5%; "
        f"量比{item['volume_ratio']:.2f}; "
        f"换手{item['turnover']:.2f}%; "
        f"市值{item['total_mv_yi']:.1f}亿; "
        f"60日强势{len(up5_bars)}次"
    )
    return item


def run_screen(as_of: date, include_today: bool, workers: int, token: str) -> tuple[list[dict], dict[str, int]]:
    counters: dict[str, int] = {}
    print("1/4 获取东方财富总市值和上市信息...")
    valuation_map = fetch_valuation_map(as_of)
    listing_map = fetch_listing_map()
    counters["valuation_rows"] = len(valuation_map)
    counters["listing_rows"] = len(listing_map)

    print("2/4 获取同花顺当日涨幅榜...")
    ths_rows = fetch_ths_candidates(token, threshold=5.0, allowed_only=True)
    counters["ths_gt5"] = len(ths_rows)

    print("3/4 执行当日条件过滤...")
    base_items: list[dict] = []
    for item in ths_rows:
        screened, reason = current_filter(
            item,
            as_of=as_of,
            valuation_map=valuation_map,
            listing_map=listing_map,
        )
        if screened is not None:
            base_items.append(screened)
        elif reason:
            counters[reason] = counters.get(reason, 0) + 1
    counters["base_pass"] = len(base_items)

    print(f"4/4 查询 {len(base_items)} 只候选股的 60 日历史...")
    matched: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {
            pool.submit(history_filter, item, as_of, include_today): item
            for item in base_items
        }
        for future in as_completed(futures):
            try:
                result = future.result()
            except Exception as exc:
                item = futures[future]
                counters["history_errors"] = counters.get("history_errors", 0) + 1
                print(f"[WARN] {item['code']} {item['name']} 历史数据失败: {exc}", file=sys.stderr)
                continue
            if result is not None:
                matched.append(result)
    matched.sort(key=lambda row: (row["up5_count"], row["pct_chg"], row["volume_ratio"]), reverse=True)
    counters["final"] = len(matched)
    return matched, counters


def write_outputs(rows: list[dict], output_dir: Path, as_of: date, counters: dict[str, int]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = as_of.strftime("%Y%m%d")
    json_path = output_dir / f"screen_{stem}.json"
    csv_path = output_dir / f"screen_{stem}.csv"
    md_path = output_dir / f"screen_{stem}.md"

    payload = {
        "generated_at": datetime.now(SH_TZ).isoformat(),
        "as_of": as_of.isoformat(),
        "model": "ths_em_eod_v1",
        "counters": counters,
        "results": rows,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    lines = [
        f"# 收盘选股 {stem}",
        "",
        f"- 同花顺涨幅大于5%的候选：{counters.get('ths_gt5', 0)}",
        f"- 当日条件通过：{counters.get('base_pass', 0)}",
        f"- 60日强势条件通过：{len(rows)}",
        f"- 历史数据失败：{counters.get('history_errors', 0)}",
        "",
        "| 代码 | 名称 | 涨幅 | 量比 | 换手 | 总市值(亿) | 价格 | 60日强势 | 最近强势日 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            "| {code} | {name} | {pct_chg:.2f}% | {volume_ratio:.2f} | "
            "{turnover:.2f}% | {total_mv_yi:.1f} | {price:.2f} | {up5_count} | {last_up5_date} |".format(**row)
        )
    if not rows:
        lines.append("| - | - | - | - | - | - | - | - | - |")
    lines.extend([
        "",
        "> 退市风险股按证券名称、交易所风险警示标记过滤；完整退市风险仍需公告和财务数据。",
        "> 结果只是模型命中清单，不构成投资建议。",
        "",
    ])
    md_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"JSON: {json_path}")
    print(f"CSV : {csv_path}")
    print(f"MD  : {md_path}")

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="收盘后模型选股器")
    parser.add_argument("--date", help="参考交易日，格式 YYYY-MM-DD；默认取东方财富最新交易日")
    parser.add_argument("--include-today-in-window", action="store_true", help="60日强势窗口包含当天")
    parser.add_argument("--workers", type=int, default=6, help="历史行情并发数，默认 6")
    parser.add_argument("--node", dest="node_path", help="Node.js 可执行文件路径")
    parser.add_argument("--theme-threshold", type=float, default=6.0, help="板块概念统计的涨幅阈值，默认 6%%")
    parser.add_argument("--skip-theme-stats", action="store_true", help="跳过板块概念统计")
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "cache",
        help="板块概念缓存目录",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "output",
        help="输出目录",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        as_of = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else fetch_latest_trade_date()
        node_path = get_node_path(args.node_path)
        token = get_hexin_token(node_path)
        print(f"参考交易日: {as_of.isoformat()}")

        rows, counters = run_screen(as_of, args.include_today_in_window, args.workers, token)
        write_outputs(rows, args.output_dir, as_of, counters)
        print(f"模型命中数量: {len(rows)}")
        for row in rows:
            print(
                f"{row['code']} {row['name']} | 涨幅 {row['pct_chg']:.2f}% | "
                f"量比 {row['volume_ratio']:.2f} | 换手 {row['turnover']:.2f}% | "
                f"市值 {row['total_mv_yi']:.1f}亿 | 60日强势 {row['up5_count']}次"
            )

        if not args.skip_theme_stats:
            stats = run_theme_stats(
                as_of,
                token=get_hexin_token(node_path),
                threshold=args.theme_threshold,
                workers=args.workers,
                cache_dir=args.cache_dir,
            )
            write_theme_outputs(stats, args.output_dir)
            print("行业板块前10:")
            for item in stats["top_sectors"]:
                print(f"  {item['name']} {item['count']}")
            print("概念前10:")
            for item in stats["top_concepts"]:
                print(f"  {item['name']} {item['count']}")
        return 0
    except KeyboardInterrupt:
        print("已中断", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())