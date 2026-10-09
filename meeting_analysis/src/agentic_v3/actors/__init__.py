"""Định danh actor của việc giao (người / đơn vị / chưa xác định): đọc danh sách tham dự
(``attendees.py``), tách actor ghép kèm vai trò (``mentions.py``), chấm điểm ứng viên và
nhận lựa chọn của Verifier (``resolution.py``).

Cố ý không re-export: ``schemas.py`` của package import ``actors.attendees``, nên
``actors/__init__.py`` phải nhẹ để không tạo vòng import.
"""
