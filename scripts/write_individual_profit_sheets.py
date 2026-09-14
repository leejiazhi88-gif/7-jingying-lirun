#!/usr/bin/env python3
import json
import os
import urllib.parse
from pathlib import Path

from write_quarter_profit import BASE, DEFAULT_WIKI_TOKEN, load_env_file, request, spreadsheet_token, tenant_token

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data" / "individual_profit.json"
SHEETS = {
    "quarter": "mJvCV8",
    "ttm": "O4pM2w",
    "yoy": "xMYegN",
}


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


def matrix(data, field, percentage=False):
    rows = []
    for period_index in range(len(data["periods"])):
        row = []
        for company in data["companies"]:
            value = data["data"][company][field][period_index]
            row.append(value if percentage or value is None else display_number(value))
        rows.append(row)
    return rows


def write_and_verify(token, spreadsheet, sheet_id, values):
    # Feishu limits a single value range to 100 columns. Split the 112 companies
    # into narrower blocks and verify every block independently.
    targets = []
    for offset in range(0, len(values[0]), 80):
        block = [row[offset:offset + 80] for row in values]
        start_col = 2 + offset
        end_col = start_col + len(block[0]) - 1
        target = f"{sheet_id}!{col_name(start_col)}3:{col_name(end_col)}{len(values) + 2}"
        request("PUT", f"{BASE}/sheets/v2/spreadsheets/{spreadsheet}/values", token,
                {"valueRange": {"range": target, "values": block}})
        encoded = urllib.parse.quote(target, safe="!")
        actual = request("GET", f"{BASE}/sheets/v2/spreadsheets/{spreadsheet}/values/{encoded}", token)["data"]["valueRange"].get("values", [])
        if actual != block:
            raise RuntimeError(f"Readback mismatch: {target}")
        targets.append(target)
    return targets


def number_styles(sheet_id, source):
    integer, decimal = [], []
    for r, row in enumerate(source, 3):
        for c, value in enumerate(row, 2):
            if value is None:
                continue
            cell = f"{sheet_id}!{col_name(c)}{r}:{col_name(c)}{r}"
            (decimal if abs(float(value)) < 10 else integer).append(cell)
    result = []
    if integer:
        result.append({"ranges": integer, "style": {"formatter": "0", "thousandSeparator": True}})
    if decimal:
        result.append({"ranges": decimal, "style": {"formatter": ""}})
    return result


def percentage_style(sheet_id, values):
    ranges = []
    for r, row in enumerate(values, 3):
        for c, value in enumerate(row, 2):
            if value is not None:
                ranges.append(f"{sheet_id}!{col_name(c)}{r}:{col_name(c)}{r}")
    return [{"ranges": ranges, "style": {"formatter": "0.00%"}}]


def main():
    load_env_file()
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    token = tenant_token()
    spreadsheet = spreadsheet_token(token, os.environ.get("FEISHU_WIKI_TOKEN", DEFAULT_WIKI_TOKEN))

    quarter = matrix(data, "q")
    ttm = matrix(data, "ttm")
    yoy = matrix(data, "yoy", percentage=True)
    ranges = {
        "quarter": write_and_verify(token, spreadsheet, SHEETS["quarter"], quarter),
        "ttm": write_and_verify(token, spreadsheet, SHEETS["ttm"], ttm),
        "yoy": write_and_verify(token, spreadsheet, SHEETS["yoy"], yoy),
    }
    request("PUT", f"{BASE}/sheets/v2/spreadsheets/{spreadsheet}/styles_batch_update", token,
            {"data": number_styles(SHEETS["quarter"], quarter)})
    request("PUT", f"{BASE}/sheets/v2/spreadsheets/{spreadsheet}/styles_batch_update", token,
            {"data": number_styles(SHEETS["ttm"], ttm)})
    request("PUT", f"{BASE}/sheets/v2/spreadsheets/{spreadsheet}/styles_batch_update", token,
            {"data": percentage_style(SHEETS["yoy"], yoy)})

    counts = {"quarter": sum(v is not None for row in quarter for v in row),
              "ttm": sum(v is not None for row in ttm for v in row),
              "yoy": sum(v is not None for row in yoy for v in row)}
    print(json.dumps({"ranges": ranges, "counts": counts, "all_numeric": True}, ensure_ascii=False))


if __name__ == "__main__":
    main()
