# Bài báo DiVA (template ACL)

- `diva.tex`: bài báo, tiếng Việt, theo template ACL (`acl.sty`, `acl_natbib.bst` lấy nguyên từ
  [acl-org/acl-style-files](https://github.com/acl-org/acl-style-files)).
- `references.bib`: tài liệu tham khảo.

Biên dịch bằng pdfLaTeX (cần gói `vntex` cho bảng mã T5 tiếng Việt; Overleaf có sẵn):

```bash
latexmk -pdf diva.tex
```

Chế độ hiển thị đặt ở dòng `\usepackage[review]{acl}`: `review` (bản nộp ẩn danh, có số dòng),
`preprint` (có tên tác giả và số trang) hoặc `final` (camera-ready).
