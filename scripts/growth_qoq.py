"""Quarter-on-quarter TTM growth, using unrounded values newest first."""


def qoq_series(ttm):
    return [current / ttm[i + 1] - 1
            if current is not None and i + 1 < len(ttm) and ttm[i + 1] not in (None, 0)
            else None for i, current in enumerate(ttm)]


def qoq_matrix(ttm, columns):
    rows = [row if row is not None else [None] * columns for row in ttm]
    series = [qoq_series([row[c] for row in rows]) for c in range(columns)]
    return [list(row) for row in zip(*series)]
