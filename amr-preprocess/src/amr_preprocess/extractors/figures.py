from __future__ import annotations

import re

from amr_preprocess.models import FigureAsset, FigureLink, TextBlock


def classify_image(
    *,
    width: int,
    height: int,
    page_image_count: int,
) -> str:
    """Heuristic gate: decorative logos/photos vs data-bearing charts."""
    if width < 80 or height < 80:
        return "decorative"
    aspect = width / max(height, 1)
    if page_image_count >= 12:
        return "decorative"
    if 0.6 <= aspect <= 1.8 and width < 400 and height < 400:
        return "decorative"
    if width >= 400 and height >= 220:
        return "data_bearing"
    return "unknown"


def link_figures(figures: list[FigureAsset], blocks: list[TextBlock]) -> list[FigureLink]:
    links: list[FigureLink] = []
    captions = [b for b in blocks if b.type == "caption" or _is_caption(b.text)]
    for fig in figures:
        if fig.kind == "decorative":
            continue
        nearby = [
            b.block_id
            for b in captions
            if fig.page is not None and b.page == fig.page
        ]
        if not nearby and fig.page is not None:
            nearby = [
                b.block_id
                for b in blocks
                if b.page == fig.page and _mentions_figure(b.text)
            ]
        if nearby:
            fig.caption = next(
                (b.text for b in blocks if b.block_id == nearby[0]), None
            )
            links.append(
                FigureLink(
                    figure_id=fig.figure_id,
                    block_ids=nearby[:3],
                    reason="same-page caption or figure reference",
                )
            )
    return links


def _is_caption(text: str) -> bool:
    return bool(re.match(r"^\s*(figure|fig\.|chart|table|exhibit)\s+\d+", text, re.I))


def _mentions_figure(text: str) -> bool:
    return bool(re.search(r"\b(figure|fig\.|chart)\s+\d+", text, re.I))
