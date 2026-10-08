# Research: áp dụng topic segmentation cho hội thoại (biên bản họp STT tiếng Việt)

Cập nhật 28/09/2026. Quy trình `ai-engineer-workflow`: đây là đầu ra **Bước 1 (Brainstorm) + Bước 2 (Research)**.
Chưa có plan và chưa có code mới. Mục tiêu cấp module giữ như `007_dialtreeseg/REPORT.md` §1: tối đa 10 chủ đề,
chỉ gồm các đoạn liền mạch, và cùng một cấu hình chạy được cho transcript dài từ 5k đến 260k ký tự.

## 1. Đang đứng ở đâu (tóm tắt từ các thí nghiệm đã có)

| Thí nghiệm | Kết quả chính |
|---|---|
| `treeseg_turn_level` (Quốc hội, 47 phiên) | ≥49.5% lượt nói của đại biểu chứa nhiều topic (chặn dưới), nên cắt theo lượt sẽ luôn bỏ sót ranh giới nằm trong lượt |
| `005_embedding_benchmark` (12 cuộc họp) | TreeSeg theo câu đạt F1 0.26–0.37, không vượt được mốc chia đều 0.346 |
| `006_dialstart` (`model_vn3`) | Pk trên tập val **tổng hợp** là 0.011, nhưng trên gold thật là 0.485 và cắt quá vụn |
| `007_dialtreeseg` (đã chốt) | Pk 0.224, F1@5k 0.486, 8/9 phiên đạt \|ΔK\| ≤ 2. vdt_trang không bao giờ bị cắt |
| M5 LLM (gemma-4-26B) chia trên tóm tắt cụm | Kém DialTreeSeg (Pk 0.48–0.56) và cắt quá vụn ngay ở phiên chỉ có 1 topic |
| DialTreeSeg + LLM refine / merge | Refine ±2 cải thiện nhẹ (Pk 0.241). Merge gộp phiên ghép (K gold 11) về còn **1 đoạn** ở cả 2 lần chạy, không dùng được |

**Bốn nút thắt đã ghi nhận:**

- **N1. Tín hiệu:** bge-m3 không phân biệt được "đổi module" với "đổi tiểu mục trong cùng module". Đây là nút thắt chính, còn tiêu chí dừng thì không phải.
- **N2. Cuộc họp ngắn, lượt dài:** 32 lượt nhưng 25k ký tự, nên kiểm định hoán vị không bao giờ bác bỏ được giả thuyết "không có cấu trúc".
- **N3. Khoảng cách giữa dữ liệu train và dữ liệu thật:** DialSTART học trên hội thoại tổng hợp ghép nối gần như hoàn hảo, nhưng trên dữ liệu thật thì hỏng.
- **N4. Đánh giá:** chỉ có 2 cuộc họp và 9 ranh giới gold, do một người gán. Chênh 1 ranh giới đã làm F1 lệch khoảng 0.14.

## 2. Bản đồ tài liệu, tổ chức theo trục vấn đề

### 2.1 Tín hiệu ranh giới (liên quan N1)

| Họ phương pháp | Đại diện | Ghi chú với bài toán của mình |
|---|---|---|
| Độ tương đồng từ vựng / embedding | TextTiling, BERTSeg, TreeSeg ([arXiv:2407.12028](https://arxiv.org/pdf/2407.12028)) | Đã thử. Họ này bắt được mọi sự thay đổi ngữ nghĩa ở mọi cấp, không có khái niệm "cấp module" |
| Coherence cặp lượt | DialSTART ([arXiv:2106.06719](https://arxiv.org/abs/2106.06719)), khung hợp nhất supervised + unsupervised theo cặp lượt ([NAACL 2025](https://aclanthology.org/2025.naacl-long.252/)) | Đã thử DialSTART. Chất lượng phụ thuộc hoàn toàn vào dữ liệu train (N3) |
| Ranh giới **có hướng** | CobSeg ([arXiv:2605.30668](https://arxiv.org/html/2605.30668)): tách hai head riêng cho **kết thúc chủ đề** và **mở đầu chủ đề**, đánh trọng số token ở mép lượt, dùng CRF | Tín hiệu mở đầu chủ đề chính là câu chủ tọa chuyển mục. Paper cũng ghi nhận lợi ích lớn nhất rơi vào dữ liệu có cue từ vựng rõ |
| LLM suy luận theo từng lượt | Def-DTS ([Findings ACL 2025](https://aclanthology.org/2025.findings-acl.1066/)): LLM lấy ngữ cảnh hai chiều → **phân loại ý định lượt nói** → suy luận có chuyển chủ đề hay không | Giảm lỗi loại 2 (bỏ sót). Trên DialSeg711 đạt Pk 1.5, tốt hơn mọi encoder. Chi phí là 1 lần gọi LLM cho mỗi lượt |
| LLM sinh mục lục (ToC) | Multi-level ToC ([Interspeech 2025, arXiv:2601.02128](https://arxiv.org/abs/2601.02128)): LLM sinh outline nhiều tầng (tiêu đề và chỉ số câu), LoRA thắng zero-shot rõ rệt, thêm đặc trưng khoảng lặng (pause) thì tốt hơn nữa | Zero-shot có khoảng cách lớn so với fine-tune, khớp với kết quả M5 của mình |

### 2.2 Độ mịn và số đoạn (liên quan N1, N2)

- TreeSeg tạo cây phân cấp, nhưng khi cắt cây thì vẫn cần biết K hoặc một ngưỡng.
- "When F1 Fails" ([arXiv:2512.17083](https://arxiv.org/abs/2512.17083)) chạy trên 8 dataset và thấy **quét ngưỡng làm W-F1 thay đổi nhiều hơn cả việc đổi phương pháp**. Họ coi bài toán là *chọn độ mịn*, không phải tìm một tập ranh giới đúng duy nhất, và đề xuất báo cáo kèm mật độ ranh giới, purity và coverage.
  - Điều này giải thích vì sao tiêu chí `ratio` và kiểm định hoán vị ở M2 đều không ổn định.
  - Nó cũng cho thấy cần định nghĩa "cấp module" bằng một tín hiệu ngoài embedding (xem H1 và H2 ở §3).
- Kernel change-point detection cho văn bản ([arXiv:2510.03437](https://arxiv.org/pdf/2510.03437)) **đã bị rút bài** vì lỗi chứng minh, không dùng làm căn cứ.

### 2.3 Nguồn giám sát (liên quan N3)

- Các dataset kiểu ghép nối như DialSeg711 và Doc2Dial dễ: supervised đạt Pk khoảng 1.0 trên DialSeg711 (CobSeg). `model_vn3` với val Pk 0.011 cho thấy đúng hiện tượng này. Dữ liệu ghép từ **các văn bản không liên quan** chỉ dạy model phát hiện cú nhảy miền. Nó không dạy được chuyện đổi module khi cả cuộc họp cùng một dự án, cùng từ vựng và cùng người nói.
- Pipeline pseudo-label của CobSeg gồm: khởi tạo bằng NSP+TeT, LLM gán nhãn và tóm tắt từng đoạn, rồi dựng lại hội thoại có kiểm soát độ dài. Nhờ đó VHF giảm từ Pk 25.4 (DialSTART) xuống 10.6. Paper cũng cảnh báo chất lượng phụ thuộc vào ranh giới pseudo.
- Dữ liệu tiếng Việt công khai cho dialogue topic segmentation hầu như chưa có. VSMRC ([arXiv:2506.15978](https://arxiv.org/abs/2506.15978)) là segmentation văn bản Wikipedia, không phải hội thoại. Nguồn gold thật lớn nhất mình đang có là **47 phiên Quốc hội** (`web_crawl/outputs/Quốc hội khoá XIII`), nhưng độ mịn theo vấn đề của từng đại biểu, không phải module.

### 2.4 Đánh giá (liên quan N4)

- W-F1 kèm purity/coverage và mật độ ranh giới ([arXiv:2512.17083](https://arxiv.org/abs/2512.17083)) khớp với cách repo đang làm: F1@2k/5k tính theo ký tự, cộng ΔK.
- Nên bổ sung **purity/coverage theo ký tự** thay cho B của segeval, vì B đang ra 0 với mọi phương pháp.
- Metric nhiều tầng của bài ToC có ích nếu mình chuyển sang dạng cây hai tầng (module ⊃ tiểu mục).

## 3. Brainstorm: các hướng, gắn với nút thắt

| # | Hướng | Giải quyết | Tiền lệ | Chi phí | Rủi ro chính |
|---|---|---|---|---|---|
| **H1** | **Cue chuyển mục làm tín hiệu cấp module.** Dùng `src/utils/cues.py` (đã có mẫu "tiếp theo", "chuyển sang", "thứ hai"... nhưng **chưa được dùng trong DialTreeSeg**) và/hoặc cho LLM phân loại ý định lượt nói theo kiểu Def-DTS: mở mục / kết mục / thủ tục / nội dung. Điểm "mở đầu chủ đề" được cộng vào objective như depth_z, hoặc làm bộ lọc ứng viên | N1, N2 | CobSeg (head mở đầu chủ đề), Def-DTS (phân loại ý định) | Thấp: regex ≈ 0, LLM ≈ 1 lần gọi mỗi cụm | Cue cũng xuất hiện khi đổi tiểu mục ("thứ hai là...") → cần phân biệt câu mở mục của chủ tọa với phép liệt kê của người trình bày |
| **H2** | **Cây hai tầng rõ ràng.** DialTreeSeg/TreeSeg cắt mịn thành các lá. LLM gán cho mỗi lá một **tên module chuẩn hoá** (thực thể chức năng/đề án), sau đó chỉ gộp các lá **kề nhau** cùng module | N1, N2 (cấp module do nhãn định nghĩa, không do embedding) | ToC nhiều tầng, TreeSeg | Trung bình | Merge ở M5 từng sụp về 1 đoạn. Cần gộp một cách tất định dựa trên nhãn, không để LLM tự quyết định gộp. Không được biến thành gộp các đoạn không kề nhau (flow stage07b đã bị từ chối) |
| **H3** | **Dữ liệu train sát thật hơn cho DialSTART.** (a) Ghép hard-negative: nối các đoạn **cùng miền/cùng dự án** thay vì văn bản ngẫu nhiên. (b) Pseudo-label kiểu CobSeg: LLM gán ranh giới trên transcript thật chưa có nhãn, rồi retrain | N3 | CobSeg pseudo-label, skill `vn-meeting-dialogue-synth` | Cao (sinh dữ liệu và train trên GPU) | Pseudo-label kém sẽ khuếch đại lỗi. Vẫn cần gold thật để kiểm chứng |
| **H4** | **LLM sinh ToC toàn cục** (outline module → tiểu mục kèm chỉ số lượt), sau đó LoRA trên pseudo-label hoặc gold | N1, N2 | Interspeech 2025 | Cao | Zero-shot đã kém ở M5. LoRA cần dữ liệu mà hiện chưa có |
| **H5** | **Tín hiệu âm thanh** (khoảng lặng, đổi người nói kèm khoảng lặng dài) | N2 | ToC + pause | Thấp nếu có timestamp thật | Transcript chuyển từ docx dùng timing tổng hợp, nên chỉ áp dụng được cho bản ghi thật |
| **H6** | **Mở rộng gold và sửa metric** (thêm 2–3 biên bản 3–6 module, purity/coverage theo ký tự) | N4 | "When F1 Fails" | Công gán nhãn | Không có hướng này thì không phân biệt được cải tiến H1–H5 với nhiễu |

Các hướng đã loại qua research: KCPD (bài bị rút), thêm tiêu chí dừng thuần thống kê (M2 đã cho thấy tiêu chí dừng không phải nút thắt), và zero-shot LLM chia thẳng (M5 cùng tài liệu đều cho thấy khoảng cách lớn).

## 4. Khuyến nghị cho bước Plan

Thứ tự theo rủi ro và chi phí. Mỗi bước kiểm chứng được độc lập.

1. **H6 trước tiên, ít nhất gold thêm 2 biên bản.** Với 9 ranh giới, mọi kết luận ở H1/H2 đều nằm trong vùng nhiễu. Dùng lại convention gold của `007_dialtreeseg/gold/`.
2. **H1 (regex cue, sau đó LLM phân loại ý định):** kiểm chứng rẻ nhất cho N1.
   - Kiểm tra đầu tiên, chưa cần code thuật toán: tại 9 ranh giới gold và tại các lần cắt thừa của DialTreeSeg (ví dụ G2 bị cắt đôi ở lượt 385), lượt mở đầu có khớp cue không. Nếu cue phân biệt được hai nhóm này thì mới tích hợp.
   - Đồng thời xem riêng ranh giới lượt 3 của vdt_trang (N2).
3. **H2**, nếu H1 chưa đủ: gộp tất định các lá kề nhau có cùng nhãn module. Tận dụng tóm tắt cụm đã có trong `boundary_refiner.py`.
4. **H3 để sau:** chỉ làm khi H1/H2 cho thấy tín hiệu học được đáng đầu tư. Dùng skill `vn-meeting-dialogue-synth` với chế độ ghép cùng miền.

**Tiêu chí thành công đề xuất** (cần chốt ở Plan, trước khi chạy):

- Không tệ hơn DialTreeSeg ở \|ΔK\| ≤ 2 trên mọi phiên.
- Pk và F1@5k tốt hơn DialTreeSeg trên **gold mở rộng**, không chỉ trên 2 cuộc họp cũ.
- vdt_trang@100% ra 2–4 đoạn.

## 5. Câu hỏi mở (cần người dùng quyết)

- Có thể gán gold thêm biên bản nào (3–6 module)? Ai gán, và có cần người thứ hai để đo độ đồng thuận không?
- H2 dùng nhãn module do LLM sinh ở tầng segmentation. Việc này có xung đột với phân tách trách nhiệm Stage 6/7 (Stage 6 không đặt tên đoạn) không, hay nhãn chỉ dùng nội bộ để gộp rồi bỏ đi?
- Có bản ghi âm với timestamp thật để thử H5 không?

## Nguồn

- [TreeSeg, arXiv:2407.12028](https://arxiv.org/pdf/2407.12028)
- [DialSTART / utterance-pair coherence, arXiv:2106.06719](https://arxiv.org/abs/2106.06719)
- [Unified supervised/unsupervised DTS via utterance pairs, NAACL 2025](https://aclanthology.org/2025.naacl-long.252/)
- [CobSeg, arXiv:2605.30668](https://arxiv.org/html/2605.30668)
- [Def-DTS, Findings ACL 2025](https://aclanthology.org/2025.findings-acl.1066/)
- [Multi-level ToC transcript segmentation, arXiv:2601.02128](https://arxiv.org/abs/2601.02128)
- [When F1 Fails, arXiv:2512.17083](https://arxiv.org/abs/2512.17083)
- [KCPD text segmentation (withdrawn), arXiv:2510.03437](https://arxiv.org/pdf/2510.03437)
- [VSMRC Vietnamese text segmentation, arXiv:2506.15978](https://arxiv.org/abs/2506.15978)
