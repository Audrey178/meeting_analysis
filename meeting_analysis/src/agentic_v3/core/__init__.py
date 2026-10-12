"""Phần lõi v3 chép từ ``src.agentic`` (v1) để v3 không còn phụ thuộc package v1.

Gồm kiểu candidate (``schemas``), luật chuẩn hoá hạn (``deadline``), bộ chấm lượt nói
(``turn_act``), các hàm luật dùng chung (``_shared``) và ba agent trích xuất + phần dùng
lại của debate/judge (``nodes``). Sửa ở đây không ảnh hưởng pipeline v1 và ngược lại.
"""
