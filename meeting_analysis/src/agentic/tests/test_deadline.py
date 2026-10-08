"""Unit test cho luật chuẩn hoá hạn chót ``src.agentic.deadline`` (0 token).

Ngày họp neo: 2026-10-08 (thứ Năm); tuần kết thúc Chủ nhật 2026-10-11.
"""

from __future__ import annotations

import pytest

from src.agentic.deadline import NormalizedDeadline, normalize_deadline

MEETING_DATE = "2026-10-08"


@pytest.mark.parametrize("raw, expected_date, expected_kind", [
    # ngày cụ thể
    ("ngày 15/11", "2026-11-15", "exact"),
    ("15-11-2026", "2026-11-15", "exact"),
    ("15.11.2026", "2026-11-15", "exact"),
    ("ngày 15 tháng 11 năm 2027", "2027-11-15", "exact"),
    ("ngày 5/3", "2027-03-05", "exact"),                    # đã qua so với ngày họp -> năm sau
    ("từ 10/11 đến 15/11", "2026-11-15", "exact"),          # khoảng -> mốc muộn
    # hạn chót trước một ngày
    ("trước ngày 15 tháng 11", "2026-11-15", "before"),
    ("trước 25/11", "2026-11-25", "before"),
    ("chậm nhất 15/11/26", "2026-11-15", "before"),
    ("trước thứ Sáu", "2026-10-09", "before"),
    # cuối kỳ
    ("cuối tháng", "2026-10-31", "end_of_period"),
    ("trước cuối tháng", "2026-10-31", "end_of_period"),
    ("trong tháng 12", "2026-12-31", "end_of_period"),
    ("cuối quý", "2026-12-31", "end_of_period"),
    ("quý IV", "2026-12-31", "end_of_period"),
    ("quý I", "2027-03-31", "end_of_period"),               # quý đã qua -> năm sau
    ("cuối năm", "2026-12-31", "end_of_period"),
    ("cuối tuần", "2026-10-11", "end_of_period"),
    # lệch từ ngày họp
    ("tuần sau", "2026-10-18", "relative"),                 # Chủ nhật tuần kế
    ("trong tuần này", "2026-10-11", "relative"),
    ("tháng sau", "2026-11-30", "relative"),
    ("thứ Sáu tuần sau", "2026-10-16", "relative"),
    ("thứ Hai hoặc thứ Tư tuần sau", "2026-10-14", "relative"),  # "A hoặc B" -> mốc muộn
    ("trong 3 ngày tới", "2026-10-11", "relative"),
    ("hôm nay", "2026-10-08", "relative"),
    ("sang tuần", "2026-10-18", "relative"),
    ("tuần tiếp theo", "2026-10-18", "relative"),
    ("khoảng 3 tuần", "2026-10-29", "relative"),
    ("ba tuần nữa", "2026-10-29", "relative"),
    ("3 tháng tới", "2027-01-08", "relative"),
    ("sang tháng", "2026-11-30", "relative"),
    ("đầu tuần sau", "2026-10-12", "relative"),
    ("giữa tháng sau", "2026-11-20", "relative"),
    ("thứ năm tuần sau", "2026-10-15", "relative"),           # "năm" là thứ, không phải 5 tuần
    # không quy được
    ("31/2", None, "unknown"),
    ("sau POC", None, "unknown"),
    (None, None, "unknown"),
    ("", None, "unknown"),
])
def test_normalize_deadline_rules(raw, expected_date, expected_kind):
    assert normalize_deadline(raw, MEETING_DATE) == NormalizedDeadline(expected_date, expected_kind)


@pytest.mark.parametrize("raw, expected", [
    ("tuần sau", NormalizedDeadline(None, "relative")),
    ("15-11-2026", NormalizedDeadline("2026-11-15", "exact")),   # tự đủ năm, không cần neo
    ("trước ngày 15/11", NormalizedDeadline(None, "before")),
    ("31/2", NormalizedDeadline(None, "unknown")),
])
def test_normalize_deadline_without_meeting_date_keeps_kind(raw, expected):
    assert normalize_deadline(raw, None) == expected
