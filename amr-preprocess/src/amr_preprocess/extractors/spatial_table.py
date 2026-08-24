from __future__ import annotations

import re

import pymupdf

from amr_preprocess.models import BBox, ExtractedTable


def score_rows(rows: list[list[str]]) -> float:
    if not rows or not rows[0]:
        return 0.0
    cells = [c for r in rows for c in r]
    filled = sum(1 for c in cells if c and str(c).strip())
    fill = filled / max(len(cells), 1)
    multi = 0
    for c in cells:
        if not c:
            continue
        nums = re.findall(r"\d[\d,.]{1,}", str(c))
        if len(nums) >= 2 and ("\n" in str(c) or len(nums) >= 3):
            multi += 1
    penalty = min(0.55, (multi / max(len(cells), 1)) * 2.0)
    widths = {len(r) for r in rows}
    ragged = 0.15 if len(widths) > 1 else 0.0
    long_ratio = sum(1 for c in cells if len(str(c)) > 40) / max(len(cells), 1)
    long_pen = min(0.5, long_ratio)
    return round(max(0.0, min(1.0, fill - penalty - ragged - long_pen)), 3)


def extract_spatial_tables(page: pymupdf.Page, page_no: int) -> list[ExtractedTable]:
    words = page.get_text("words")
    tokens = [
        (float(w[0]), float(w[1]), float(w[2]), float(w[3]), str(w[4]).strip())
        for w in words
        if str(w[4]).strip()
    ]
    if len(tokens) < 6:
        return []

    ys = _cluster([t[1] for t in tokens], gap=6)
    lines: list[list[tuple]] = [[] for _ in ys]
    for tok in tokens:
        lines[_nearest(ys, tok[1])].append(tok)
    for line in lines:
        line.sort(key=lambda t: t[0])

    flags = [_is_tabular_line(line) for line in lines]
    run = _longest_true_run(flags)
    if run is None:
        return []
    start, end = run
    region = [ln for ln in lines[start:end] if ln]
    if len(region) < 3:
        return []

    xs = _cluster([t[0] for line in region for t in line], gap=18)
    if len(xs) < 2:
        return []

    grid = [["" for _ in xs] for _ in region]
    for ri, line in enumerate(region):
        for x0, y0, x1, y1, text in line:
            ci = _nearest(xs, x0)
            if grid[ri][ci]:
                grid[ri][ci] = f"{grid[ri][ci]} {text}"
            else:
                grid[ri][ci] = text

    grid = [r for r in grid if any(c.strip() for c in r)]
    if not grid:
        return []
    keep_cols = [i for i in range(len(grid[0])) if any(r[i].strip() for r in grid)]
    grid = [[r[i] for i in keep_cols] for r in grid]
    if len(grid) < 3 or len(grid[0]) < 2:
        return []

    cells = [c for r in grid for c in r]
    long_ratio = sum(1 for c in cells if len(c) > 40) / max(len(cells), 1)
    numeric = sum(1 for c in cells if re.search(r"\d", c))
    if long_ratio > 0.25 or numeric < 3:
        return []

    headers, body = ([grid[0]], grid[1:])
    conf = score_rows(grid)
    xs0 = [t[0] for line in region for t in line]
    ys0 = [t[1] for line in region for t in line]
    xs1 = [t[2] for line in region for t in line]
    ys1 = [t[3] for line in region for t in line]
    return [
        ExtractedTable(
            table_id=f"p{page_no}_spatial0",
            page=page_no,
            headers=headers,
            rows=body,
            extraction_method="spatial",
            confidence=conf,
            bbox=BBox(
                x0=min(xs0),
                y0=min(ys0),
                x1=max(xs1),
                y1=max(ys1),
                page=page_no,
            ),
        )
    ]


def _is_tabular_line(line: list[tuple]) -> bool:
    if len(line) < 2:
        return False
    texts = [t[4] for t in line]
    if any(len(t) > 48 for t in texts):
        return False
    has_num = any(re.search(r"\d", t) for t in texts)
    short = all(len(t) < 24 for t in texts)
    return has_num or (len(line) >= 3 and short)


def _longest_true_run(flags: list[bool]) -> tuple[int, int] | None:
    best: tuple[int, int] | None = None
    start = None
    for i, flag in enumerate(flags + [False]):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            if best is None or (i - start) > (best[1] - best[0]):
                best = (start, i)
            start = None
    if best is None or best[1] - best[0] < 3:
        return None
    return best


def _cluster(values: list[float], gap: float) -> list[float]:
    if not values:
        return []
    ordered = sorted(values)
    groups: list[list[float]] = [[ordered[0]]]
    for v in ordered[1:]:
        if v - groups[-1][-1] <= gap:
            groups[-1].append(v)
        else:
            groups.append([v])
    return [sum(g) / len(g) for g in groups]


def _nearest(centers: list[float], value: float) -> int:
    return min(range(len(centers)), key=lambda i: abs(centers[i] - value))
