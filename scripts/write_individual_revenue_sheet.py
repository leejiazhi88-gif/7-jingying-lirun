#!/usr/bin/env python3
import json
import os
import urllib.parse
from pathlib import Path

from write_quarter_profit import BASE, DEFAULT_WIKI_TOKEN, load_env_file, request, spreadsheet_token, tenant_token

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data" / "individual_revenue.json"
SHEET_ID = "E9yBZl"


def col_name(index):
    out = []
    while index:
        index, rem = divmod(index - 1, 26)
        out.append(chr(65 + rem))
    return "".join(reversed(out))


def display_number(value):
    if value is None:
        return None
    return round(float(value), 1) if abs(float(value)) < 10 else value


def revenue_matrix(data):
    return [
        [display_number(data["data"][company]["ttm"][period_index]) for company in data["companies"]]
        for period_index in range(len(data["periods"]))
    ]


def write_and_verify(token, spreadsheet, values):
    targets = []
    for offset in range(0, len(values[0]), 80):
        block = [row[offset:offset + 80] for row in values]
        start_col = 2 + offset
        end_col = start_col + len(block[0]) - 1
        target = f"{SHEET_ID}!{col_name(start_col)}3:{col_name(end_col)}{len(values) + 2}"
        request("PUT", f"{BASE}/sheets/v2/spreadsheets/{spreadsheet}/values", token,
                {"valueRange": {"range": target, "values": block}})
        encoded = urllib.parse.quote(target, safe="!")
        actual = request("GET", f"{BASE}/sheets/v2/spreadsheets/{spreadsheet}/values/{encoded}", token)["data"]["valueRange"].get("values", [])
        if actual != block:
            raise RuntimeError(f"Readback mismatch: {target}")
        targets.append(target)
    return targets


def number_styles(values):
    integer, decimal = [], []
    for row_index, row in enumerate(values, 3):
        for column_index, value in enumerate(row, 2):
            if value is None:
                continue
            cell = f"{SHEET_ID}!{col_name(column_index)}{row_index}:{col_name(column_index)}{row_index}"
            (decimal if abs(float(value)) < 10 else integer).append(cell)
    styles = []
    if integer:
        styles.append({"ranges": integer, "style": {"formatter": "0", "thousandSeparator": True}})
    if decimal:
        styles.append({"ranges": decimal, "style": {"formatter": ""}})
    return styles


def main():
    load_env_file()
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    token = tenant_token()
    spreadsheet = spreadsheet_token(token, os.environ.get("FEISHU_WIKI_TOKEN", DEFAULT_WIKI_TOKEN))
    values = revenue_matrix(data)

    request("PUT", f"{BASE}/sheets/v2/spreadsheets/{spreadsheet}/values", token,
            {"valueRange": {"range": f"{SHEET_ID}!A1:A1", "values": [["年TTM营收（亿）"]]}})
    labels = [[f"{period[2:4]}年Q{((int(period[4:6]) - 1) // 3) + 1}"] for period in data["periods"]]
    request("PUT", f"{BASE}/sheets/v2/spreadsheets/{spreadsheet}/values", token,
            {"valueRange": {"range": f"{SHEET_ID}!A3:A{len(labels) + 2}", "values": labels}})
    targets = write_and_verify(token, spreadsheet, values)
    request("PUT", f"{BASE}/sheets/v2/spreadsheets/{spreadsheet}/styles_batch_update", token,
            {"data": number_styles(values)})

    populated = [value for row in values for value in row if value is not None]
    if not all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in populated):
        raise RuntimeError("Non-numeric populated value found")
    print(json.dumps({"sheet": SHEET_ID, "ranges": targets, "rows": len(values),
                      "companies": len(values[0]), "numeric_cells": len(populated),
                      "all_numeric": True}, ensure_ascii=False))


if __name__ == "__main__":
    main()
