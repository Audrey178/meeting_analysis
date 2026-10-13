```json meta
{
  "meeting_id": "synth_040",
  "title": "Họp nhanh nhóm phát triển ứng dụng đặt suất ăn ca Bếp Xanh - chuẩn bị bản 1.6",
  "meeting_type": "software_project",
  "length_bucket": "S",
  "split": "heldout",
  "tags": ["short_meeting", "hedged_proposal", "unassigned_task"],
  "speakers": {
    "TL": "Anh Tường (Trưởng nhóm kỹ thuật)",
    "PO": "Chị Xuân (Product Owner)",
    "BE": "Định (Backend)",
    "MB": "Ly (Lập trình Mobile)",
    "QA": "Chị Sương (Kiểm thử)"
  }
}
```

## TOPIC | Sửa lỗi trùng suất ăn khi công nhân đổi ca | Khi công nhân đổi ca sau giờ chốt, hệ thống giữ suất ca cũ và tạo thêm suất ca mới, bếp nhà máy may Hòa Lợi nấu dư khoảng 140 suất mỗi tuần; thống nhất tự hủy suất ca cũ khi đổi ca và khóa đổi ca sau giờ chốt suất; đề xuất rút giờ chốt xuống 2 tiếng chưa được chấp nhận.

@TL: Rồi, họp nhanh khoảng hai mươi phút thôi nhé. Có ba việc: lỗi trùng suất khi đổi ca, chức năng đánh giá món ăn, và lịch phát hành bản 1.6. Định nói lỗi trùng suất trước đi.

@BE #k_dinh1: Dạ. Lỗi này bếp ở nhà máy may Hòa Lợi báo lên từ tuần trước. Khi công nhân đổi ca, ví dụ từ ca hai sang ca ba, thì app tạo một suất mới cho ca ba nhưng không hủy suất ca hai, nếu việc đổi ca diễn ra sau giờ chốt suất. Trước giờ chốt thì không sao vì lúc chốt hệ thống có chạy dọn trùng. Em kiểm tra log ba tuần thì trung bình mỗi tuần dư khoảng 140 suất, toàn bộ là ở Hòa Lợi, vì bên đó tổ trưởng hay đổi ca cho công nhân sát giờ.

@PO: 140 suất một tuần là gần ba triệu tiền nguyên liệu bỏ đi đấy, bên bếp kêu dữ lắm.

@TL: Khoan, 140 suất đó là tính cả suất công nhân nghỉ phép mà không hủy, hay chỉ riêng đổi ca?

@BE: Chỉ riêng đổi ca anh ạ. Suất nghỉ phép không hủy thì còn khoảng 60 suất một tuần nữa, nhưng cái đó là do công nhân quên hủy, không phải lỗi hệ thống.

@PO: Cái nghỉ phép là chuyện khác, hôm nay mình không bàn.

@BE: Dạ. Em đề xuất là khi đổi ca thì giao dịch đổi ca hủy luôn suất ca cũ trong cùng một transaction, không đợi job dọn trùng. Còn nếu đổi sau giờ chốt suất của ca mới, tức là bếp đã lên số lượng rồi, thì app khóa không cho đổi, hiện thông báo bảo tổ trưởng liên hệ trực tiếp bếp.

@QA: Chị hỏi chút, giờ chốt suất hiện đang là trước mỗi ca 4 tiếng đúng không?

@BE: Dạ đúng chị, ca một 6 giờ sáng thì chốt 2 giờ sáng, cứ thế.

@PO #n_chot2h: Chị thì đang nghĩ là, ừm, có lẽ mình nên rút giờ chốt xuống còn trước 2 tiếng thôi, cho công nhân với tổ trưởng linh hoạt hơn, đổi ca sát giờ cũng không bị khóa.

@TL: Cái đó phải hỏi bên bếp đã chị ạ, 2 tiếng thì bếp có kịp sơ chế không em không chắc. Mình cứ sửa lỗi theo giờ chốt hiện tại trước.

@PO: Ừ, để chị hỏi thử, chưa đổi vội.

@TL #d_doica: Ok, chốt: đổi ca thì hủy suất ca cũ ngay trong cùng transaction; đổi sau giờ chốt suất của ca mới thì khóa, hiện hướng dẫn liên hệ bếp. Giờ chốt vẫn giữ trước ca 4 tiếng.

@BE #a_doica: Em sửa xong trước thứ Năm, có kèm script dọn mấy suất trùng còn treo trong tuần này.

@QA #a_test_doica: Thứ Năm có bản thì chị test luôn mấy kịch bản đổi ca trước và sau giờ chốt, cả đổi ca qua đêm.

@MB: Phía app thì khi bị khóa đổi ca em hiện popup có số điện thoại bếp trực của từng nhà máy. Cái số đó em lấy từ cấu hình hay để cứng ạ?

@BE: Lấy từ cấu hình đi, bảng nhà máy có sẵn cột số điện thoại bếp rồi, có điều Hòa Lợi chưa nhập.

@PO #a_sobep: Số bếp trực Hòa Lợi chị có, lát họp xong chị nhập vào luôn.

## TOPIC | Xây dựng chức năng đánh giá món ăn sau bữa trên ứng dụng | Bản thử đánh giá 5 sao chỉ có 6% công nhân dùng; thống nhất đổi sang thang ba mức với biểu tượng, nhắc đánh giá 30 phút sau bữa, báo cáo tuần gửi bếp trưởng; đề xuất thưởng điểm cho người đánh giá chưa được chấp nhận.

@TL: Sang mục hai, đánh giá món ăn. Ly.

@MB #k_ly1: Dạ. Bản thử đánh giá món ăn em bật ở hai nhà máy được ba tuần, cho công nhân chấm 5 sao từng món sau bữa. Kết quả là chỉ khoảng 6% công nhân đánh giá, mà phần lớn đánh giá đều là 3 sao, nhìn vào chẳng biết món nào ngon món nào dở. Em hỏi nhanh mấy anh chị công nhân thì họ bảo nghỉ giữa ca có 30 phút, ăn xong là đi luôn, không có thời gian chấm từng món.

@PO #k_xuan1: Bên bếp thì vẫn rất cần số liệu này, vì hợp đồng với nhà máy có điều khoản về mức độ hài lòng, quý nào dưới 70% là bị trừ tiền. Hiện giờ họ phải phát phiếu giấy, rất mất công.

@MB: Em đề xuất đổi sang ba mức thôi: ngon, tạm được, không ngon, dùng biểu tượng mặt cười, chấm cả bữa chứ không chấm từng món, ai muốn thì mới bấm vào chấm chi tiết. App gửi thông báo nhắc 30 phút sau khi kết thúc bữa, lúc đó công nhân đã về chuyền, có thể mở điện thoại lúc nghỉ.

@QA: Chị thấy nhắc 30 phút thì nhiều nhà máy cấm dùng điện thoại trên chuyền đấy. Có khi nên để cuối ca.

@MB: Dạ cái đó em cho cấu hình theo từng nhà máy được, mặc định 30 phút, nhà máy nào cấm thì đặt cuối ca.

@PO: Thế còn báo cáo cho bếp thì sao? Bếp trưởng không mở trang quản trị đâu, họ chỉ đọc email hoặc Zalo thôi.

@BE: Thì mình gửi email tổng hợp hằng tuần, có tỷ lệ hài lòng theo bữa, theo món, với ba món bị chê nhiều nhất. Zalo thì phải đăng ký tài khoản Zalo OA, thủ tục lâu.

@QA: Ừ email trước đi, chị thấy bếp trưởng ở Hòa Lợi với nhà máy giày Phước An đều dùng email cả.

@TL #n_diem: Anh có ý này, hay là mình thưởng điểm tích lũy cho người đánh giá, đủ điểm thì đổi được món tráng miệng hay hộp sữa, chắc tỷ lệ đánh giá sẽ lên.

@PO: Cái đó thì phải xin ngân sách bên kinh doanh, mà phải xem có bị đánh giá bừa để lấy điểm không. Để sau, giờ chưa làm.

@TL #d_danhgia: Ok, chốt đánh giá ba mức bằng biểu tượng, chấm theo bữa, chi tiết từng món là tùy chọn; nhắc đánh giá mặc định 30 phút sau bữa, cấu hình được theo nhà máy. Báo cáo tổng hợp gửi bếp trưởng mỗi sáng thứ Hai.

@MB #a_danhgia: Dạ phần app em làm, đưa vào bản 1.6 luôn.

@BE #a_baocao: Còn báo cáo tuần gửi bếp trưởng thì em làm job tổng hợp, gửi email lúc 7 giờ sáng thứ Hai, xong trong tuần sau.

## TOPIC | Rà soát kế hoạch phát hành bản 1.6 | Thống nhất phát hành bản 1.6 thứ Ba tuần sau, mở trước cho nhà máy may Hòa Lợi rồi mới mở cho hai nhà máy còn lại; việc cập nhật tài liệu API cho nhà máy điện tử Tân Phú và rà soát tài khoản quản trị của nhà máy đã thanh lý hợp đồng chưa có người nhận.

@TL: Cuối cùng là lịch phát hành. Anh định là thứ Ba tuần sau đẩy bản 1.6. Chị Sương thấy kịp không?

@QA #k_suong1: Nếu thứ Năm có bản sửa đổi ca thì chị test hồi quy thứ Sáu với thứ Hai được. Nhưng chị đề nghị không mở cho cả ba nhà máy một lúc, vì lỗi đổi ca chỉ tái hiện rõ ở Hòa Lợi, nên mở cho Hòa Lợi trước, chạy hai ngày ổn rồi mới mở cho hai nhà máy kia.

@PO: Chị đồng ý, Hòa Lợi cũng là nơi đang kêu nhiều nhất, sửa cho họ trước thì tốt.

@BE: Em đề nghị phần khóa đổi ca để sau cờ tính năng, có vấn đề gì thì tắt cờ là về hành vi cũ, không phải rút bản.

@TL #d_phathanh: Ừ, ý Định hợp lý, phần khóa đổi ca để sau cờ tính năng. Chốt phát hành bản 1.6 thứ Ba tuần sau, mở cho Hòa Lợi trước, sau hai ngày không có lỗi nghiêm trọng thì mở cho hai nhà máy còn lại. Ly lo phần đẩy bản lên kho ứng dụng nhé.

@MB #a_kho: Dạ, em nộp lên hai kho từ thứ Hai để kịp duyệt.

@BE #k_dinh2: À, có một việc nữa anh ơi. Bên nhà máy điện tử Tân Phú đang tích hợp hệ thống chấm công của họ với API đăng ký suất ăn, mà tài liệu API mình gửi họ là bản 1.3, từ đó đến giờ đổi mấy endpoint rồi, họ gọi sai suốt. Cần có người cập nhật lại tài liệu cho bản 1.6.

@TL #n_tailieu: Ừ, cái đó cần làm, nhưng tuần này ai cũng kín việc rồi. Để đấy đã, tuần sau xem ai rảnh thì làm.

@QA #n_taikhoan: Chị cũng nhắc lại là nhà máy bao bì Minh Long thanh lý hợp đồng từ tháng trước, mà tài khoản quản trị của họ trên hệ thống vẫn còn hoạt động, ba tài khoản. Cái này về bảo mật thì phải có người rà và khóa đi.

@PO: Đúng là phải làm, nhưng chị không rõ quyền khóa tài khoản đối tác là bên mình hay bên vận hành nữa.

@MB: Em nhớ là tuần trước vẫn có người đăng nhập bằng một tài khoản bên Minh Long vào xem báo cáo suất ăn đấy ạ, em thấy trong log.

@TL: Ừ, cái đó cũng ghi lại, để anh hỏi xem quy trình bên vận hành thế nào rồi tính. Thôi, hôm nay đến đây, cảm ơn mọi người.

```json gold
{
  "assignments": [
    {"actor": "Định (Backend)", "actor_aliases": ["em"], "task": "Sửa lỗi trùng suất khi đổi ca: hủy suất ca cũ trong cùng transaction, khóa đổi sau giờ chốt; kèm script dọn suất trùng còn treo", "deadline": "trước thứ Năm", "turns": ["d_doica", "a_doica"]},
    {"actor": "Chị Sương (Kiểm thử)", "actor_aliases": ["chị"], "task": "Test các kịch bản đổi ca trước và sau giờ chốt, cả đổi ca qua đêm", "deadline": "thứ Năm", "turns": ["a_test_doica"]},
    {"actor": "Chị Xuân (Product Owner)", "actor_aliases": ["chị"], "task": "Nhập số điện thoại bếp trực Hòa Lợi vào cấu hình nhà máy", "deadline": "sau buổi họp", "turns": ["a_sobep"]},
    {"actor": "Ly (Lập trình Mobile)", "actor_aliases": ["em"], "task": "Làm chức năng đánh giá món ăn ba mức trên app, đưa vào bản 1.6", "deadline": "bản 1.6", "turns": ["d_danhgia", "a_danhgia"]},
    {"actor": "Định (Backend)", "actor_aliases": ["em"], "task": "Làm job tổng hợp đánh giá, gửi email báo cáo cho bếp trưởng 7 giờ sáng thứ Hai", "deadline": "trong tuần sau", "turns": ["a_baocao"]},
    {"actor": "Chị Sương (Kiểm thử)", "actor_aliases": ["chị"], "task": "Test hồi quy bản 1.6", "deadline": "thứ Sáu và thứ Hai", "turns": ["k_suong1"]},
    {"actor": "Ly (Lập trình Mobile)", "actor_aliases": ["Ly", "em"], "task": "Nộp bản 1.6 lên hai kho ứng dụng", "deadline": "từ thứ Hai", "turns": ["d_phathanh", "a_kho"]}
  ],
  "decisions": [
    {"text": "Đổi ca thì hủy suất ca cũ ngay trong cùng transaction; đổi sau giờ chốt suất của ca mới thì khóa và hướng dẫn liên hệ bếp; giờ chốt giữ trước ca 4 tiếng", "turns": ["d_doica"]},
    {"text": "Đánh giá món ăn ba mức bằng biểu tượng, chấm theo bữa, chi tiết từng món tùy chọn; nhắc mặc định 30 phút sau bữa, cấu hình theo nhà máy; báo cáo gửi bếp trưởng sáng thứ Hai", "turns": ["d_danhgia"]},
    {"text": "Phần khóa đổi ca đặt sau cờ tính năng; phát hành bản 1.6 thứ Ba tuần sau, mở cho nhà máy Hòa Lợi trước, sau hai ngày không lỗi nghiêm trọng mới mở cho hai nhà máy còn lại", "turns": ["d_phathanh"]}
  ],
  "negatives": [
    {"type": "hedged_proposal", "text": "Rút giờ chốt suất xuống trước ca 2 tiếng (chờ hỏi bếp, chưa đổi)", "turns": ["n_chot2h"]},
    {"type": "hedged_proposal", "text": "Thưởng điểm tích lũy cho công nhân đánh giá món ăn (để sau, chưa làm)", "turns": ["n_diem"]},
    {"type": "unassigned_task", "text": "Cập nhật tài liệu API đăng ký suất ăn bản 1.6 cho nhà máy điện tử Tân Phú", "turns": ["k_dinh2", "n_tailieu"]},
    {"type": "unassigned_task", "text": "Rà soát và khóa 3 tài khoản quản trị của nhà máy bao bì Minh Long đã thanh lý hợp đồng", "turns": ["n_taikhoan"]}
  ],
  "key_points": [
    {"speaker": "Định (Backend)", "point": "Đổi ca sau giờ chốt không hủy suất ca cũ, dư khoảng 140 suất mỗi tuần ở nhà máy Hòa Lợi", "turns": ["k_dinh1"]},
    {"speaker": "Ly (Lập trình Mobile)", "point": "Bản thử đánh giá 5 sao chỉ 6% công nhân dùng, phần lớn chấm 3 sao; đề xuất ba mức, chấm theo bữa", "turns": ["k_ly1"]},
    {"speaker": "Chị Xuân (Product Owner)", "point": "Hợp đồng có điều khoản hài lòng dưới 70% bị trừ tiền; bếp đang phải phát phiếu giấy", "turns": ["k_xuan1"]},
    {"speaker": "Chị Sương (Kiểm thử)", "point": "Test hồi quy thứ Sáu và thứ Hai; đề nghị mở cho Hòa Lợi trước", "turns": ["k_suong1"]},
    {"speaker": "Định (Backend)", "point": "Nhà máy Tân Phú dùng tài liệu API bản 1.3 đã cũ nên gọi sai", "turns": ["k_dinh2"]}
  ]
}
```
