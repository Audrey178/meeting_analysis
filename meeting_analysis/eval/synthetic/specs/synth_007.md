```json meta
{
  "meeting_id": "synth_007",
  "title": "Họp sản phẩm nền tảng luyện thi IELTS - chức năng chấm tự động",
  "meeting_type": "software_project",
  "length_bucket": "S",
  "tags": ["short_meeting", "similar_adjacent_topics"],
  "speakers": {
    "PO": "Chị Ngọc (Quản lý sản phẩm)",
    "ML": "Anh Đạt (Trưởng nhóm AI)",
    "GV": "Cô Hạnh (Chuyên gia học thuật IELTS)",
    "DEV": "Phúc (Kỹ sư phần mềm)"
  }
}
```

## TOPIC | Xây dựng chức năng AI tự động chấm bài viết IELTS Writing | Mô hình chấm Writing lệch trung bình 0.6 band so với giám khảo, hay chấm cao bài dài nhiều từ vựng khó nhưng lạc đề; thống nhất bổ sung kiểm tra bám đề, chỉ hiển thị khoảng band và nhận xét theo 4 tiêu chí.

@PO: Ok mọi người, hôm nay mình họp nhanh về chức năng chấm tự động, có hai phần là Writing và Speaking, mỗi phần khoảng ba mươi phút. Anh Đạt nói phần Writing trước nhé, vì phần này sắp phải phát hành bản beta cho lớp học thử tháng sau.

@ML #k_ml1: Ok. Phần chấm Writing thì mình đang dùng mô hình ngôn ngữ lớn kết hợp với một mô hình hồi quy nhỏ. Bước một là LLM đọc bài và đưa ra nhận xét theo bốn tiêu chí của IELTS là Task Response, Coherence and Cohesion, Lexical Resource, và Grammatical Range and Accuracy. Bước hai là mô hình hồi quy nhận các đặc trưng như số từ, số lỗi ngữ pháp, độ đa dạng từ vựng, cộng với điểm LLM, để ra band cuối cùng. Mình đánh giá trên 1.200 bài có điểm của giám khảo thật do cô Hạnh cung cấp, thì sai số tuyệt đối trung bình là 0.6 band, và khoảng 71% bài lệch không quá 0.5 band. Nhưng mà có một lỗi hệ thống mình thấy rất rõ, là mô hình chấm cao những bài dài, dùng nhiều từ vựng khó, nhưng mà lạc đề hoặc chỉ trả lời một nửa câu hỏi. Có bài Task 2 hỏi về ưu và nhược điểm, học viên chỉ viết ưu điểm, rất hay, từ vựng rất tốt, mô hình cho 7.5, trong khi giám khảo cho 6.0 vì Task Response chỉ được 5.

@GV: Đúng rồi, đây là lỗi kinh điển. Với giám khảo IELTS thì Task Response là cái đầu tiên chúng tôi nhìn. Một bài không trả lời đủ các phần của câu hỏi thì Task Response không thể quá 5, dù ngôn ngữ có tốt đến đâu. Và các em học viên Việt Nam thì rất hay học thuộc các cụm từ hoa mỹ, viết dài, nên nếu hệ thống mà thưởng cho cái đó thì mình đang dạy các em đi sai hướng. Tôi lo nhất là cái này.

@ML: Dạ vâng cô. Nên em đề xuất là thêm một bước kiểm tra bám đề riêng trước khi chấm. Tức là mình cho LLM phân tích đề bài thành các yêu cầu cụ thể, ví dụ đề hỏi ưu điểm, nhược điểm và quan điểm cá nhân thì là ba yêu cầu, rồi kiểm tra bài viết có đáp ứng từng yêu cầu không. Nếu thiếu yêu cầu nào thì áp trần cho Task Response, và band tổng không vượt quá một mức tương ứng. Mình thử nhanh trên 200 bài thì lỗi chấm cao bài lạc đề giảm rõ, sai số trung bình còn khoảng 0.5.

@DEV: Anh Đạt ơi, thêm một bước LLM nữa thì thời gian chấm có tăng nhiều không? Hiện đang khoảng 25 giây một bài, học viên đã kêu là lâu rồi.

@ML: Tăng thêm khoảng 8 đến 10 giây. Nhưng mà mình có thể chạy song song bước kiểm tra bám đề với bước nhận xét ngôn ngữ, thì tổng thời gian chỉ tăng khoảng 3 giây thôi.

@GV: Tôi còn một lo ngại nữa là về cách hiển thị. Nếu mình hiển thị một con số band chính xác, ví dụ 6.5, thì học viên sẽ tin tuyệt đối vào con số đó, trong khi sai số là 0.5 band. Có em được máy chấm 7.0 xong đi thi thật được 6.0 là sẽ phàn nàn trung tâm. Tôi đề nghị chỉ hiển thị một khoảng, ví dụ từ 6.0 đến 6.5, và nhấn mạnh phần nhận xét theo từng tiêu chí, vì cái nhận xét đó mới là cái giúp các em tiến bộ.

@PO: Em đồng ý với cô, về mặt sản phẩm thì cũng an toàn hơn. Nhưng mà bên marketing thì họ muốn có con số cụ thể để quảng cáo là chấm chính xác như giám khảo. Mình phải thống nhất nội bộ.

@PO #d_writing: Thôi, em chốt là thế này. Một là thêm bước kiểm tra bám đề chạy song song như anh Đạt nói, áp trần Task Response khi thiếu yêu cầu. Hai là màn hình kết quả chỉ hiển thị khoảng band, không hiển thị một con số, và nhận xét theo bốn tiêu chí là nội dung chính. Còn marketing thì em sẽ làm việc với họ, không quảng cáo là chính xác như giám khảo.

@ML #a_bamde: Ok, bên anh làm bước kiểm tra bám đề, đánh giá lại trên đủ 1.200 bài, xong trong hai tuần.

@DEV #a_hienthi: Em sửa màn hình kết quả sang hiển thị khoảng band, tuần này em làm được.

@GV #a_bode: Tôi sẽ gửi thêm cho anh Đạt khoảng 300 bài lạc đề có điểm giám khảo để làm tập kiểm tra riêng cho lỗi này, trong tuần sau.

## TOPIC | Xây dựng chức năng AI tự động chấm bài nói IELTS Speaking | Mô hình chấm Speaking dựa trên nhận dạng giọng nói chấm thấp phát âm giọng Việt dù dễ hiểu và bị ảnh hưởng bởi tiếng ồn; thống nhất lùi phát hành Speaking sang quý sau, thu thêm dữ liệu giọng Việt có điểm giám khảo, beta chỉ mở Part 1.

@PO: Rồi, sang Speaking. Phần này thì em biết là đang khó hơn. Anh Đạt nói đi.

@ML #k_ml2: Ừ. Speaking thì pipeline là nhận dạng giọng nói ra văn bản, rồi chấm trên văn bản cho Fluency and Coherence, Lexical Resource, Grammatical Range, còn phát âm thì chấm bằng một mô hình đánh giá phát âm riêng, so với phát âm chuẩn. Mình có 430 bài nói có điểm giám khảo, ít hơn nhiều so với Writing. Sai số trung bình hiện tại là 0.9 band, cao hơn Writing nhiều. Vấn đề lớn nhất là tiêu chí phát âm. Mô hình phát âm của mình được huấn luyện chủ yếu trên giọng bản ngữ, nên nó chấm rất thấp giọng Việt, kể cả những bạn nói rất dễ hiểu, giám khảo cho phát âm 7 mà máy cho 5. Vấn đề thứ hai là nhận dạng giọng nói bị ảnh hưởng nhiều bởi tiếng ồn, học viên thu âm ở nhà, ở quán cà phê, nhận dạng sai thì chấm ngữ pháp, từ vựng cũng sai theo.

@GV: Về phát âm thì tôi nói rõ là tiêu chí phát âm của IELTS không chấm giọng, không yêu cầu giọng Anh hay giọng Mỹ, mà chấm mức độ dễ hiểu và việc sử dụng các đặc điểm phát âm như trọng âm, ngữ điệu, nối âm. Một người nói giọng Việt rõ ràng, dễ hiểu, dùng ngữ điệu tốt thì hoàn toàn được 7 hoặc 8. Nếu máy phạt giọng Việt thì là sai về bản chất tiêu chí, và sẽ làm các em mất tự tin.

@DEV: Về tiếng ồn thì bên em có thể thêm bước kiểm tra chất lượng âm thanh trước khi nộp, nếu tiếng ồn quá cao thì yêu cầu học viên thu lại. Cái này làm không khó.

@ML: Cái đó giúp được phần nhận dạng. Nhưng phần phát âm thì cần dữ liệu. Muốn mô hình không phạt giọng Việt thì phải có ít nhất khoảng 2.000 bài nói giọng Việt có điểm phát âm của giám khảo để tinh chỉnh. Mình mới có 430 bài tổng cộng.

@GV: Trung tâm có thể tổ chức thu âm. Các lớp luyện thi hiện có khoảng 600 học viên, mỗi em làm hai, ba bài thi thử Speaking có giám khảo chấm trong khóa học, mình xin phép các em ghi âm lại là trong khoảng hai tháng có đủ.

@PO #n_speaking_ngay: Em thì em vẫn muốn là beta tháng sau có cả Speaking, vì đối thủ đã có rồi. Hay là mình vẫn phát hành Speaking nhưng tắt điểm phát âm đi?

@ML: Tắt điểm phát âm thì band tổng Speaking không tính được đúng, vì phát âm là một phần tư điểm. Mà hiển thị ba tiêu chí thì học viên sẽ hỏi.

@GV: Tôi không ủng hộ phát hành Speaking khi sai số đang là 0.9 band. Với Writing mình đã phải hiển thị khoảng rồi, Speaking mà lệch gần một band thì không có ý nghĩa gì cả.

@PO #d_speaking: Ok, em nghe mọi người. Em chốt lại là Speaking không phát hành đầy đủ trong beta tháng sau, lùi sang quý sau. Trong beta chỉ mở Part 1 dạng luyện tập, có nhận xét về độ trôi chảy và từ vựng, không hiển thị band và không chấm phát âm. Song song thì thu thập dữ liệu giọng Việt có điểm giám khảo như cô Hạnh nói.

@GV #a_thuam: Tôi sẽ làm kế hoạch thu âm và xin phép học viên, bắt đầu từ lớp tháng 11.

@DEV #a_tiengon: Em làm bước kiểm tra tiếng ồn trước khi nộp và màn hình Part 1 luyện tập, xong trước beta.

@ML #a_phatam: Bên anh chuẩn bị quy trình tinh chỉnh mô hình phát âm, khi có đủ khoảng 1.000 bài đầu tiên thì chạy thử luôn, không đợi đủ 2.000.

@PO: Ok cảm ơn mọi người, em sẽ gửi biên bản sau.

```json gold
{
  "assignments": [
    {"actor": "Anh Đạt (Trưởng nhóm AI)", "actor_aliases": ["anh Đạt", "bên anh"], "task": "Làm bước kiểm tra bám đề, đánh giá lại trên 1.200 bài", "deadline": "2 tuần", "turns": ["d_writing", "a_bamde"]},
    {"actor": "Phúc (Kỹ sư phần mềm)", "actor_aliases": ["em"], "task": "Sửa màn hình kết quả Writing sang hiển thị khoảng band", "deadline": "tuần này", "turns": ["a_hienthi"]},
    {"actor": "Cô Hạnh (Chuyên gia học thuật IELTS)", "actor_aliases": ["tôi"], "task": "Gửi khoảng 300 bài lạc đề có điểm giám khảo làm tập kiểm tra", "deadline": "tuần sau", "turns": ["a_bode"]},
    {"actor": "Chị Ngọc (Quản lý sản phẩm)", "actor_aliases": ["em"], "task": "Làm việc với marketing để không quảng cáo chấm chính xác như giám khảo", "deadline": null, "turns": ["d_writing"]},
    {"actor": "Cô Hạnh (Chuyên gia học thuật IELTS)", "actor_aliases": ["tôi"], "task": "Lập kế hoạch thu âm Speaking giọng Việt có điểm giám khảo, xin phép học viên", "deadline": "bắt đầu từ lớp tháng 11", "turns": ["a_thuam"]},
    {"actor": "Phúc (Kỹ sư phần mềm)", "actor_aliases": ["em"], "task": "Làm bước kiểm tra tiếng ồn trước khi nộp và màn hình luyện tập Speaking Part 1", "deadline": "trước beta", "turns": ["a_tiengon"]},
    {"actor": "Anh Đạt (Trưởng nhóm AI)", "actor_aliases": ["bên anh"], "task": "Chuẩn bị quy trình tinh chỉnh mô hình phát âm, chạy thử khi có khoảng 1.000 bài", "deadline": null, "turns": ["a_phatam"]}
  ],
  "decisions": [
    {"text": "Thêm bước kiểm tra bám đề chạy song song, áp trần Task Response khi thiếu yêu cầu; kết quả Writing chỉ hiển thị khoảng band, nhận xét 4 tiêu chí là nội dung chính", "turns": ["d_writing"]},
    {"text": "Lùi phát hành Speaking đầy đủ sang quý sau; beta chỉ mở Part 1 luyện tập, không hiển thị band, không chấm phát âm; thu thập dữ liệu giọng Việt", "turns": ["d_speaking"]}
  ],
  "negatives": [
    {"type": "hedged_proposal", "text": "Phát hành Speaking trong beta tháng sau với điểm phát âm bị tắt", "turns": ["n_speaking_ngay"]}
  ],
  "key_points": [
    {"speaker": "Anh Đạt (Trưởng nhóm AI)", "point": "Chấm Writing sai số trung bình 0.6 band, chấm cao bài dài nhiều từ vựng khó nhưng lạc đề", "turns": ["k_ml1"]},
    {"speaker": "Anh Đạt (Trưởng nhóm AI)", "point": "Chấm Speaking sai số 0.9 band, mô hình phát âm phạt giọng Việt, nhận dạng bị ảnh hưởng tiếng ồn", "turns": ["k_ml2"]}
  ]
}
```
