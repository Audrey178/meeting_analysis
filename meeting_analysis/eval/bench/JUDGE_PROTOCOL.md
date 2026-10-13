# Giao thức chấm (judge) cho benchmark `eval/bench`

Judge đọc một packet `eval/results/<run>/judge/packets/<packet_id>.md` (transcript + gold + output) và ghi đúng một file
`eval/results/<run>/judge/judgments/<packet_id>.json`. Packet **mù**: không có tên hệ thống, không có phần lộ kiến trúc
(việc bị Verifier loại, chủ đề lỗi). Đừng cố đoán output đến từ hệ thống nào.

Bổ sung cho [`eval/judge_rubric.md`](../judge_rubric.md): rubric đó định nghĩa Likert S1–S4, F1–F8; file này định nghĩa
bảng ghép và nhãn từng item, là nguồn của P/R/F1.

## Nguyên tắc

- Gold được cài sẵn khi viết transcript nên **đầy đủ**: item output không khớp gold nào thì phải giải thích được (trùng,
  bịa, bẫy, không phải việc giao/kết luận) hoặc là `extra_valid` (đúng theo transcript, chỉ là gold gộp/tách khác).
- Ghép theo **nội dung**, không theo câu chữ. Trích dẫn (`ev=`) chỉ để hỗ trợ đọc, không phải điều kiện ghép.
- Một item gold ghép tối đa với một item output chính; item output khác nói lại đúng việc đó là `duplicate`.
- Mọi nhận định phải đọc lại transcript ở lượt liên quan, không dựa vào tiêu đề chủ đề.
- Nhãn item output và `negatives` chấm **độc lập**: item khớp một gold nhưng kéo theo cả nội dung bẫy (vd. kết luận
  đúng kèm vế đã bị đảo lại) vẫn nhãn `ok` (gold ghi `partial`) và bẫy đó ghi `hit <id>`. Nhãn `trap` chỉ dành cho
  item mà nội dung chính là bẫy.

## Định dạng judgment

```json
{
  "packet_id": "3fa2c1d9e0",
  "judge": "claude-opus-5-5",
  "matching": {
    "assignments": {"A1": "match a3", "A2": "partial a4 (thiếu phạm vi 12 lĩnh vực)", "A3": "miss"},
    "decisions":   {"D1": "match d0", "D2": "miss"},
    "key_points":  {"K1": "match", "K2": "partial (thiếu số liệu 4%)", "K3": "miss"},
    "negatives":   {"N1": "avoided", "N2": "hit d2"}
  },
  "output_labels": {
    "assignments": {
      "a0": {"label": "ok", "actor_ok": true, "deadline_ok": true, "note": ""},
      "a1": {"label": "duplicate", "actor_ok": null, "deadline_ok": null, "note": "trùng a3"}
    },
    "decisions": {
      "d0": {"label": "ok", "note": ""},
      "d2": {"label": "trap", "note": "đề xuất của Lan bị gạt (N2)"}
    }
  },
  "scores": {"S1": {"score": 4, "reason": "..."}}
}
```

- `matching.*`: mọi id gold của packet đều phải có mặt. Giá trị bắt đầu bằng `match` / `partial` / `miss`
  (`negatives`: `avoided` / `hit <id output>`), sau đó là id output và lý do ngắn nếu cần.
  `partial` = đúng việc nhưng thiếu/sai một phần nội dung chính (tính 0,5 recall).
- `output_labels.*`: mọi item output (`a0`, `a1`, … / `d0`, …) đều phải có nhãn:

| Nhãn | Nghĩa | Tính đúng cho precision |
|---|---|---|
| `ok` | khớp (match/partial) một item gold | có |
| `extra_valid` | không có trong gold nhưng đúng theo transcript (vd. gold gộp hai việc, output tách) | có |
| `duplicate` | lặp lại item output khác cùng nội dung | không |
| `trap` | rơi vào một `negatives` của gold | không |
| `not_assignment` / `not_decision` | là ý kiến, báo cáo, đề xuất chưa chốt… nhưng không có trong negatives | không |
| `hallucinated` | không có căn cứ trong transcript | không |

- Chỉ với việc giao: `actor_ok` = bên nhận đúng (kể cả suy đúng từ "em/anh"); `deadline_ok` = hạn chót đúng
  (`null` nếu gold và output đều không có hạn). Chỉ chấm hai trường này khi nhãn là `ok`; nhãn khác thì để `null`.
- `scores`: chỉ khi packet ghi `LIKERT: có`, chấm đủ S1–S4, F1–F8 theo `eval/judge_rubric.md`, nhất quán với bảng ghép.
  Packet ghi `LIKERT: không` thì bỏ hẳn khoá `scores`.
