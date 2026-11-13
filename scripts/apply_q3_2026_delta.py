#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
PERIOD = "20260930"


def load(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def save(name, value):
    (DATA / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def rolling_four(rows):
    result = []
    for index, row in enumerate(rows):
        if index + 4 > len(rows):
            result.append(None)
            continue
        window = rows[index:index + 4]
        result.append([
            None if any(period_row[column] is None for period_row in window)
            else sum(period_row[column] for period_row in window)
            for column in range(len(row))
        ])
    return result


def yoy_percent(ttm):
    result = []
    for index, row in enumerate(ttm):
        if row is None or index + 4 >= len(ttm) or ttm[index + 4] is None:
            result.append(None)
            continue
        result.append([
            None if previous in (None, 0) or current is None else (current / previous - 1) * 100
            for current, previous in zip(row, ttm[index + 4])
        ])
    return result


def update_industry(delta):
    quarter = load("quarter_profit.json")
    if quarter["periods"][0] != PERIOD:
        quarter["periods"].insert(0, PERIOD)
        quarter["matrix"].insert(0, [delta["industry_profit"][code] for code in quarter["l1s"]])
        quarter["stats"].insert(0, {
            "period": PERIOD,
            "used": 5559,
            "missingPrev": 30,
            "unclassified": 5,
        })
    save("quarter_profit.json", quarter)

    derived = load("derived_sheets.json")
    derived["ttm"] = rolling_four(quarter["matrix"])
    derived["yoy"] = yoy_percent(derived["ttm"])
    derived["latest_financial_period"] = PERIOD
    save("derived_sheets.json", derived)


def update_individual_profit(delta):
    data = load("individual_profit.json")
    if data["periods"][0] != PERIOD:
        data["periods"].insert(0, PERIOD)
        for company in data["companies"]:
            item = data["data"][company]
            item["q"].insert(0, delta["companies"][company]["profit_q3"])
            item["ttm"] = []
            item["yoy"] = []
    for company in data["companies"]:
        item = data["data"][company]
        quarters = item["q"]
        item["ttm"] = [
            sum(quarters[index:index + 4])
            if index + 4 <= len(quarters) and all(value is not None for value in quarters[index:index + 4])
            else None
            for index in range(len(quarters))
        ]
        item["yoy"] = [
            current / item["ttm"][index + 4] - 1
            if current is not None and index + 4 < len(item["ttm"]) and item["ttm"][index + 4] not in (None, 0)
            else None
            for index, current in enumerate(item["ttm"])
        ]
    data["latest_financial_period"] = PERIOD
    save("individual_profit.json", data)


def update_individual_revenue(delta):
    data = load("individual_revenue.json")
    if data["periods"][0] != PERIOD:
        data["periods"].insert(0, PERIOD)
        for company in data["companies"]:
            data["data"][company]["quarter"].insert(0, delta["companies"][company]["revenue_q3"])
    for company in data["companies"]:
        item = data["data"][company]
        quarters = item["quarter"]
        item["ttm"] = [
            sum(quarters[index:index + 4])
            if index + 4 <= len(quarters) and all(value is not None for value in quarters[index:index + 4])
            else None
            for index in range(len(quarters))
        ]
    data["latest_financial_period"] = PERIOD
    save("individual_revenue.json", data)


def main():
    delta = load("q3_2026_delta.json")
    update_industry(delta)
    update_individual_profit(delta)
    update_individual_revenue(delta)
    print(json.dumps({"period": PERIOD, "companies": len(delta["companies"]), "updated": True}))


if __name__ == "__main__":
    main()
