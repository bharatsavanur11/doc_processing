from amr_preprocess.extractors.figures import classify_image
from amr_preprocess.extractors.spatial_table import score_rows


def test_decorative_logo_gate() -> None:
    assert classify_image(width=64, height=64, page_image_count=1) == "decorative"
    assert classify_image(width=1200, height=700, page_image_count=2) == "data_bearing"
    assert classify_image(width=200, height=200, page_image_count=20) == "decorative"


def test_merged_row_penalty() -> None:
    clean = [["Segment", "FY25"], ["Americas", "25143"]]
    merged = [["Segment", "FY25"], ["Americas", "$16,384 100.0\n3,505 21"]]
    assert score_rows(clean) > score_rows(merged)
