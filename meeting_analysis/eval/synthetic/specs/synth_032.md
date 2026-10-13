```json meta
{
  "meeting_id": "synth_032",
  "title": "Họp rà soát dự án Hệ thống quản lý bãi đỗ xe thông minh thành phố Vĩnh Phước - chuẩn bị thí điểm",
  "meeting_type": "software_project",
  "length_bucket": "L",
  "split": "heldout",
  "tags": ["long", "topic_revisit", "pronoun_actor"],
  "speakers": {
    "PM": "Chị Uyên (Quản lý dự án)",
    "KH": "Anh Thịnh (Phó Giám đốc Trung tâm Quản lý điều hành giao thông)",
    "BE": "Anh Thông (Trưởng nhóm Backend)",
    "AI": "Nhật (Kỹ sư thị giác máy tính)",
    "MB": "Châu (Lập trình di động)",
    "IOT": "Anh Triều (Kỹ sư thiết bị IoT)",
    "QA": "Chị Bích (Trưởng nhóm Kiểm thử)",
    "DO": "Tín (Kỹ sư DevOps)"
  },
  "revisits": {"4": 0}
}
```

## TOPIC | Rà soát chức năng nhận dạng biển số xe tại làn cổng bãi đỗ | Mô hình nhận dạng biển số v2.2 đạt 96,8% ban ngày nhưng chỉ 83,5% ban đêm và 80,2% khi mưa, biển vuông hai dòng 88%; thống nhất dùng ngưỡng confidence 0,85, dưới ngưỡng chuyển nhân viên cổng xác nhận, so khớp mờ tối đa lệch một ký tự; tạm chưa lắp đèn bổ trợ.

@PM: Rồi, mọi người vào đủ rồi thì mình bắt đầu nhé. Hôm nay là buổi rà soát tổng thể cuối cùng trước khi chốt kế hoạch thí điểm ngày 1 tháng 12, có anh Thịnh bên Trung tâm Quản lý điều hành giao thông dự cùng. Em đi lần lượt các hạng mục: nhận dạng biển số ở làn cổng, đặt chỗ trên app, cảm biến lòng đường, thanh toán, dashboard vận hành, kết quả test tải với bảo mật, hạ tầng, cuối cùng là kế hoạch thí điểm và phân công. Nhật mở đầu với nhận dạng biển số nhé.

@AI #k_nhat1: Dạ. Ờ, hiện tại mô hình nhận dạng biển số đang chạy bản v2.2, gồm hai bước, bước một là detect vùng biển số trên khung hình, bước hai là OCR đọc từng ký tự. Em test trên tập 18.400 ảnh chụp thực tế ở 31 làn cổng của 12 bãi thí điểm, lấy trong ba tuần gần đây. Ban ngày thì tỷ lệ đọc đúng toàn bộ biển là 96,8%, cái này ổn. Nhưng mà ban đêm thì tụt xuống 83,5%, trời mưa thì còn 80,2%. Biển vuông hai dòng của ô tô cũng thấp hơn, khoảng 88%, chủ yếu do dòng dưới bị nhầm số 8 với chữ B, số 0 với chữ D. Biển vàng xe kinh doanh vận tải thì không có vấn đề gì, tương đương biển trắng.

@KH: Ban đêm 83% thì nghĩa là cứ sáu xe thì có một xe đọc sai à?

@AI: Dạ gần như vậy anh, nhưng phần lớn là sai một ký tự thôi, chứ không phải là không đọc được gì.

@KH #k_thinh1: Sai một ký tự cũng là sai biển rồi. Bên tôi lo nhất là lúc xe ra, hệ thống đối chiếu biển lúc vào với biển lúc ra để tính tiền, sai một ký tự là không khớp, barie không mở, xe sau xếp hàng. Giờ cao điểm buổi chiều ở bãi Chợ Đình với bãi Quảng trường mà kẹt một làn là ùn ra tận đường lớn đấy. Mà đợt trước bên tôi đi khảo sát thì 9 làn ngoài trời ở 4 bãi lộ thiên đèn đường rất yếu, tôi nghĩ ban đêm sai chủ yếu là ở mấy làn đó.

@BE #k_thong1: Dạ, phần đối chiếu thì bên em có làm so khớp mờ rồi anh, tức là nếu lệch một ký tự mà thời gian vào hợp lý, ảnh xe cùng màu cùng dáng thì vẫn cho khớp. Nhưng cái này em cũng không muốn nới quá, vì nới quá thì dễ bị lợi dụng, kiểu hai xe biển gần giống nhau đổi lượt cho nhau để trốn phí. Em đề xuất dùng luôn cái điểm confidence của mô hình, lượt nào dưới ngưỡng thì không tự mở barie mà đẩy lên màn hình của nhân viên trông cổng, họ nhìn ảnh rồi bấm xác nhận hoặc sửa biển.

@QA: Cho chị hỏi ngưỡng bao nhiêu thì hợp lý? Vì ngưỡng cao quá thì nhân viên phải bấm liên tục, mà ngưỡng thấp quá thì lọt.

@AI #k_nhat2: Dạ em có vẽ đường cong rồi chị. Ở ngưỡng 0,85 thì khoảng 7% lượt xe ban ngày và 21% lượt xe ban đêm phải đẩy lên cho người xác nhận, còn trong số được tự động cho qua thì tỷ lệ đọc sai dưới 0,5%. Lên ngưỡng 0,9 thì đẩy lên nhiều hơn hẳn, ban đêm khoảng 30%, mà tỷ lệ sai chỉ giảm thêm được 0,2%. Thấp hơn 0,85, kiểu 0,8, thì tỷ lệ sai lọt qua tăng lên gần 1,4%, em thấy không đáng.

@KH: 21% ban đêm thì nhân viên bấm cũng được, ban đêm xe ít, một làn chắc vài chục lượt một tiếng.

@QA: Thế màn hình xác nhận đấy nhân viên thao tác mất bao lâu? Chị sợ lúc mưa giờ cao điểm thì vẫn ùn.

@BE: Bên em thiết kế là hiện hai ảnh, ảnh toàn cảnh với ảnh cắt vùng biển, kèm biển hệ thống đọc được, nhân viên bấm một nút là xong, sửa thì gõ lại ký tự sai. Bên em đo thử với 5 người thì trung bình 4 giây một lượt.

@KH: 4 giây thì chấp nhận được. Nhưng mà nhân viên cổng nhiều người lớn tuổi, màn hình phải to, chữ to, nút bấm rõ ràng, đừng bắt họ gõ nhiều, gõ nhiều là họ mở barie cho xong chuyện.

@AI #n_bien: Em có một ý là, ờ, về lâu dài mình có thể chạy mô hình ngay trên thiết bị biên, kiểu đặt một bo Jetson ở từng cổng, thì không phụ thuộc đường truyền về trung tâm, độ trễ cũng thấp hơn. Nhưng mà mỗi cổng thêm tầm 18 triệu tiền thiết bị, 31 làn là hơn năm trăm triệu.

@BE: Cái đó anh nghĩ là để sau thí điểm hẵng tính, giờ đường truyền về trung tâm đang ổn, độ trễ trung bình 600 mili giây một lượt nhận dạng, yêu cầu là dưới 1 giây, vẫn đạt.

@PM #d_nguong: Ok, vậy em chốt mục này: dùng ngưỡng confidence 0,85, dưới ngưỡng thì không tự mở barie mà chuyển lên màn hình nhân viên cổng xác nhận; so khớp mờ chỉ cho phép lệch tối đa một ký tự. Nhận dạng vẫn chạy trên máy chủ trung tâm như hiện tại.

@KH #d_khongden: Còn chuyện đèn thì tạm thời chưa lắp thêm đèn chiếu sáng bổ trợ ở các làn ngoài trời nhé, vì kinh phí thiết bị bên tôi năm nay coi như hết rồi, cứ chỉnh tham số camera trước đã, kiểu tăng thời gian phơi sáng, xem được đến đâu.

@BE #a_xacnhan: Dạ, màn hình xác nhận thủ công cho nhân viên cổng thì bên em làm, xong trong sprint này, tức là ngày 31 tháng 10 có trên staging.

@AI: Còn mô hình thì em đang huấn luyện bản v2.3, có thêm khoảng 3.000 ảnh đêm với ảnh mưa gắn nhãn tuần trước. Đang chạy đánh giá trên tập test, chắc khoảng một tiếng nữa có số, có thì em báo lại luôn trong buổi.

## TOPIC | Xây dựng chức năng đặt trước và giữ chỗ đỗ xe trên ứng dụng di động | App đặt chỗ đã có bản beta nội bộ 46 người dùng; lỗi đặt trùng chỗ cuối do race condition và 38% lượt giữ chỗ miễn phí bỏ không đến; thống nhất giữ chỗ tối đa 20 phút, phí 5.000 đồng trừ vào phí gửi xe, giữ lại 5% chỗ không cho đặt trước, chỉ hỗ trợ Android 9 và iOS 15 trở lên.

@PM: Vâng, có số thì Nhật báo nhé. Sang mục hai, chức năng đặt trước và giữ chỗ trên app. Châu trình bày đi em.

@MB #k_chau1: Dạ. Luồng đặt chỗ thì người dùng mở app, xem bản đồ các bãi gần mình, mỗi bãi hiện số chỗ trống theo thời gian thực, chọn bãi rồi bấm giữ chỗ. Khi giữ chỗ thì hệ thống trừ một chỗ khỏi số chỗ trống công khai, gắn biển số xe đã đăng ký trong tài khoản với lượt giữ chỗ, xe đến cổng thì camera đọc biển khớp là barie mở luôn, không phải lấy vé. Hiện tại bản Android với iOS đều đã xong giao diện, đang chạy beta nội bộ, có 46 người bên công ty với bên Trung tâm dùng thử hai tuần nay. Feedback chính là người dùng không biết mình còn bao nhiêu thời gian giữ chỗ, với lại có mấy trường hợp giữ chỗ xong đến nơi thì bãi báo hết chỗ.

@BE #k_thong2: Cái lỗi đến nơi hết chỗ là do race condition bên em. Khi hai người cùng giữ chỗ cuối cùng ở cùng một bãi trong vòng vài trăm mili giây thì cả hai đều được xác nhận. Em tái hiện được rồi, sẽ chuyển sang khóa theo từng bãi trên Redis, kiểu atomic decrement, hết chỗ là trả lỗi ngay chứ không đọc rồi mới ghi như bây giờ. Ngoài ra em đề xuất mỗi bãi luôn giữ lại 5% số chỗ không cho đặt trước, để khách vãng lai không bị thiệt.

@KH: 5% là hợp lý. Thế giữ chỗ được bao lâu, có mất tiền không?

@MB: Dạ, bản beta đang để giữ 30 phút, miễn phí. Nhưng mà số liệu beta thì có khoảng 38% lượt giữ chỗ người ta không đến, tức là giữ cho chắc rồi bỏ.

@KH #k_thinh2: Thế thì không được. Giữ miễn phí thì người ta giữ cho chắc, giữ hai ba bãi một lúc rồi bỏ, chỗ trống ảo, mà bãi trung tâm giờ cao điểm thì lúc nào cũng kín. Trong quyết định giá dịch vụ trông giữ xe năm nay của thành phố đã có mục phí giữ chỗ trước, tối đa 10.000 đồng một lượt, nên mình áp được luôn, không phải xin thêm ai.

@QA: Chị đề nghị là thời gian giữ ngắn lại, 20 phút thôi, vì số liệu beta thì đa số người dùng đến trong vòng 12 phút sau khi bấm giữ.

@MB #n_dattruoc: Em thì đang nghĩ là, ờ, có lẽ sau này nên cho đặt chỗ trước theo khung giờ, kiểu đặt luôn cho chiều mai, nhiều người đi họp ở khu hành chính tập trung có hỏi cái đó.

@KH: Cái đó để xem đã, đặt trước cả ngày thì phức tạp, chỗ bị khóa lâu, mà lại phải tính chuyện người ta đến muộn. Giờ chưa bàn.

@BE: Em hỏi thêm về phí giữ chỗ, thanh toán bằng gì ạ? Nếu bắt người dùng quét QR mỗi lần giữ chỗ thì mất thêm một bước, tỷ lệ bỏ ngang sẽ cao.

@MB: Dạ em nghĩ là thanh toán qua ví đã liên kết trong app, một chạm là xong, chưa liên kết ví thì mới hiện QR. Bản beta thì chưa có bước này, em ước thêm khoảng ba ngày công.

@QA: Thế trường hợp người dùng đã trả phí giữ chỗ mà đến nơi barie không mở vì camera đọc sai biển thì sao? Người ta mất tiền giữ chỗ mà vẫn phải đứng chờ.

@BE: Thì lượt đó rơi vào luồng xác nhận thủ công như lúc nãy, nhân viên cổng thấy trên màn hình là xe có giữ chỗ, bấm xác nhận là vào, phí giữ chỗ vẫn trừ vào phí gửi bình thường.

@KH: Ừ, miễn là tiền giữ chỗ được trừ vào, không thu hai lần là được.

@PM #d_giucho: Vậy em chốt: giữ chỗ tối đa 20 phút, thu phí giữ chỗ 5.000 đồng, khi xe vào bãi thì trừ vào phí gửi xe; quá 20 phút không đến thì tự hủy và không hoàn phí giữ chỗ. Mỗi bãi giữ lại 5% chỗ không cho đặt trước.

@BE #a_khoabai: Phần khóa theo bãi chống đặt trùng thì em làm, thứ Tư tuần sau có trên staging.

@MB #a_demnguoc: Dạ phần giao diện thì em thêm màn hình thanh toán phí giữ chỗ với đồng hồ đếm ngược thời gian còn lại, trong sprint 14.

@PM #a_nhacgio: Ừ, à còn cái thông báo đẩy nhắc trước năm phút khi sắp hết giờ giữ chỗ nữa, em làm luôn trong sprint đó nhé, còn nút gia hạn thì thôi không cần.

@MB #a_nhacgio_ok: Dạ vâng ạ.

@QA #k_bich1: Chị có một việc nữa. Bản beta trên mấy máy Android 8 đời cũ bị crash khi mở màn bản đồ, khoảng 3% thiết bị trong nhóm beta. Mình có hỗ trợ Android 8 không?

@MB: Dạ hỗ trợ Android 8 thì phải hạ thư viện bản đồ xuống bản cũ, mất khoảng một tuần, mà một số hiệu ứng trên bản đồ phải bỏ.

@KH: Người dân còn dùng Android 8 nhiều không?

@MB: Dạ theo số liệu thống kê chung thì Android 8 trở xuống ở Việt Nam còn khoảng 4% số máy, chủ yếu là máy rất cũ, mà mấy máy đó cũng không chạy mượt bản đồ được.

@PM #d_hdh: Không cần đâu. Chốt chỉ hỗ trợ Android 9 trở lên và iOS 15 trở lên, ghi rõ trên trang mô tả ở kho ứng dụng.

@KH #a_vanban: Về chức năng giữ chỗ có thu phí thì tôi sẽ làm văn bản báo cáo Sở Giao thông vận tải để bên đó nắm, tuần sau tôi gửi.

## TOPIC | Tích hợp cảm biến IoT giám sát trạng thái ô đỗ xe lòng đường | Đã lắp 640 cảm biến từ trường trên 5 tuyến phố, 11% lần báo chiếm chỗ là ảo do xe dừng đón trả khách, 48 cảm biến đoạn Hai Bà Trưng mất gói tin 17%; thống nhất nâng thời gian xác nhận lên 90 giây và lắp thêm 2 gateway LoRa trên cột đèn chiếu sáng.

@PM: Mục ba là cảm biến ô đỗ lòng đường. Anh Triều.

@IOT #k_trieu1: Ừ. Bên anh đã lắp xong 640 cảm biến từ trường ở các ô đỗ lòng đường trên 5 tuyến phố, gồm Lê Lợi, Trần Hưng Đạo, Hai Bà Trưng, Nguyễn Huệ và đường Bờ Hồ. Cảm biến gửi trạng thái qua LoRaWAN về 7 gateway, rồi gateway đẩy lên server qua MQTT. Thời gian từ lúc xe đỗ đến lúc app cập nhật trung bình 25 giây. Có hai vấn đề. Thứ nhất là báo ảo: xe chỉ dừng đón khách 20, 30 giây, hoặc xe máy dừng đè lên vạch, cảm biến vẫn báo có xe. Đếm trong tuần vừa rồi thì khoảng 11% số lần báo chiếm chỗ là ảo. Thứ hai là đoạn cuối phố Hai Bà Trưng có 48 cảm biến mất kết nối thường xuyên, tỷ lệ mất gói tin 17%, vì gateway gần nhất bị tòa nhà mới xây che mất.

@BE: Cái 11% ảo thì bên em lọc được ở server, nhưng mà lọc ngay ở cảm biến thì đỡ tốn pin với băng thông hơn.

@IOT #k_trieu2: Đúng rồi. Firmware cảm biến có tham số thời gian xác nhận, hiện đang để 10 giây. Nếu nâng lên 90 giây thì gần như loại hết các trường hợp dừng đón trả khách, anh chạy thử trên 20 cảm biến phố Lê Lợi ba ngày thì báo ảo còn dưới 1%. Đổi lại thì app cập nhật chậm hơn khoảng một phút rưỡi. Pin thì nhà sản xuất cam kết 5 năm với chu kỳ gửi hiện tại, nâng ngưỡng thì gửi ít bản tin đi, pin còn lâu hơn.

@KH: Chậm một phút rưỡi không sao, người dân quan trọng là đến nơi có chỗ thật, chứ app báo trống mà đến thì có xe là họ chửi.

@QA: Mà anh Triều, cập nhật cấu hình cho 640 cái là phải ra tận nơi từng cái à?

@IOT: Không, cập nhật cấu hình qua downlink LoRa được, nhưng mỗi lần chỉ gửi được ít, phải chia đợt ban đêm, cả lượt mất khoảng 4 đến 5 ngày.

@PM #a_cauhinh: Vậy anh đẩy cấu hình ngưỡng 90 giây cho toàn bộ 640 cảm biến luôn nhé, xong trước thứ Tư tuần sau để còn kịp test cùng app.

@IOT #a_cauhinh_ok: Ừ, được, thứ Tư tuần sau xong.

@BE: Phía server em vẫn giữ bộ lọc 60 giây làm lớp dự phòng, phòng khi có con cảm biến nào cập nhật cấu hình không thành công.

@KH #k_thinh3: Còn đoạn Hai Bà Trưng thì vị trí lắp gateway thêm bên tôi đề nghị gắn lên cột đèn chiếu sáng, nhưng cột đèn là tài sản của Công ty Chiếu sáng công cộng, phải có văn bản đề nghị, có bản vẽ vị trí, họ mới cho. Lần trước 7 gateway cũng mất gần hai tuần mới xin xong.

@IOT: Anh tính cần thêm 2 gateway, một ở ngã tư Hai Bà Trưng giao Lý Thường Kiệt, một ở đầu phố đoạn gần chợ. Thiết bị thì trong kho còn dự phòng 3 cái, không phải mua thêm. Có giấy phép là bên anh lắp trong hai ngày.

@KH #a_vbchieusang: Thế thì tôi làm văn bản gửi bên chiếu sáng ngay trong tuần này, anh Triều gửi tôi bản vẽ vị trí hai cột.

@IOT: Ừ, chiều nay anh gửi.

@KH: Còn chuyện cảm biến bị hỏng thì sao? Ô đỗ lòng đường thì xe tải nặng chạy qua, rồi đợt mưa tháng trước đoạn Trần Hưng Đạo ngập gần nửa mét.

@IOT #k_trieu4: Cảm biến chuẩn IP68, chịu ngập được, chịu tải xe 20 tấn. Từ lúc lắp đến giờ có 6 con hỏng: 4 con bị hỏng khi đơn vị khác đào đường sửa ống nước, 2 con lỗi pin từ nhà sản xuất, đã được đổi bảo hành. Bên anh có bảng theo dõi tình trạng pin với tín hiệu của từng cảm biến, con nào pin dưới 20% hoặc mất tín hiệu quá 6 tiếng là báo về.

@BE: Bảng tình trạng cảm biến đó thì dashboard bên em đã lấy qua API rồi, có hiện trên màn bản đồ, ô nào cảm biến lỗi thì hiện màu xám.

@KH: Thế khi cảm biến lỗi thì ô đó tính là trống hay là có xe?

@IOT: Tính là không xác định, app không cộng vào số chỗ trống, để người dân không đến nhầm.

@QA: Chị lưu ý thêm là khi test end-to-end thì cần có xe thật đỗ, vì giả lập sự kiện thì không kiểm tra được cái ngưỡng 90 giây. Bên chị sẽ mượn hai xe của công ty chạy test trên phố Lê Lợi.

@KH: Còn về sau mở rộng thì mỗi ô cảm biến hết bao nhiêu tiền, anh Triều? Để tôi có số đưa vào đề xuất kế hoạch năm sau.

@IOT: Cảm biến khoảng 2,1 triệu một con, cộng công khoan lắp, trám mặt đường khoảng 600 nghìn nữa. Gateway thì khoảng 18 triệu một cái, phủ được chừng 150 đến 200 ô tùy địa hình, phố nhiều nhà cao tầng thì phủ ít hơn.

@PM #d_cambien: Chốt mục cảm biến: thời gian xác nhận trạng thái nâng lên 90 giây cho toàn bộ cảm biến; lắp thêm 2 gateway LoRa trên cột đèn chiếu sáng đoạn Hai Bà Trưng, dùng thiết bị dự phòng có sẵn; server giữ bộ lọc dự phòng.

## TOPIC | Tích hợp thanh toán không tiền mặt và đối soát phí gửi xe | Ba kênh thanh toán VietQR động, ví điện tử trong app và trừ tự động tài khoản ETC; đối soát thử lệch 0,6% do callback trễ gây trừ tiền hai lần; đề xuất máy thu tiền mặt bị gạt; thống nhất chỉ thanh toán không tiền mặt, đối soát tự động hằng ngày, hoàn tiền trong 3 ngày làm việc.

@PM: Sang thanh toán. Anh Thông.

@BE #k_thong3: Dạ. Thanh toán hiện có ba kênh. Một là quét VietQR động hiện trên màn hình ở cổng ra, hai là thanh toán trong app qua ba ví điện tử đối tác, ba là trừ tự động vào tài khoản giao thông của thu phí không dừng, cái tài khoản ETC mà ô tô dán thẻ ở kính đấy. Kênh ETC thì xe chạy qua là trừ tiền luôn, không phải dừng, nhưng hiện mới tích hợp được trên staging với một nhà cung cấp dịch vụ thu phí, nhà cung cấp còn lại hẹn tháng 11. Đối soát thì bên em chạy thử trên staging hai tuần, 14.300 giao dịch giả lập, lệch 0,6%, hầu hết là do ví đối tác trả callback trễ, giao dịch đã trừ tiền mà hệ thống mình vẫn ghi là chưa thanh toán, barie không mở, khách quét lại lần nữa, thành ra bị trừ hai lần.

@KH: Trừ hai lần là dân phản ánh lên đường dây nóng ngay.

@BE: Dạ, nên em làm thêm hai việc. Một là trước khi tạo QR mới cho cùng một lượt xe thì gọi API truy vấn trạng thái giao dịch cũ, đã thanh toán rồi thì mở barie luôn, không tạo QR mới. Hai là job đối soát tự động chạy lúc 2 giờ sáng hằng ngày, so file của từng ví và ngân hàng với dữ liệu của mình, lệch thì treo giao dịch đó lại, gửi cảnh báo cho bộ phận kế toán của Trung tâm; trường hợp trừ hai lần thì hoàn tiền trong 3 ngày làm việc.

@QA #k_bich2: Chị test kênh ví thì thấy thêm là ví thứ ba chưa có môi trường sandbox ổn định, tuần trước sandbox của họ sập hai ngày liền, nên kịch bản đối soát với ví đó chị mới chạy được khoảng 40%. Hai ví kia thì chạy đủ rồi.

@PM #a_vithu3: Ví thứ ba thì em làm việc trực tiếp với họ, phụ lục hợp đồng cũng chưa ký xong. Em sẽ chốt phụ lục và yêu cầu sandbox ổn định trước ngày 31 tháng 10, không được thì thí điểm chỉ chạy hai ví.

@BE: Hai ví kia thì đã ký phụ lục, phí 0,8% trên mỗi giao dịch, còn VietQR qua ngân hàng thì miễn phí với bên thu.

@KH #n_tienmat: Còn tiền mặt thì sao? Người già nhiều người không có ví điện tử, không biết quét mã. Tôi nghĩ là có nên đặt máy thu tiền mặt tự động ở cổng không, như mấy bãi ở sân bay ấy.

@PM #n_tienmat_giao: Vâng, thế thì anh Thông khảo sát giúp em phương án tích hợp máy thu tiền mặt tự động, xem giá với giao thức kết nối nhé.

@BE: Dạ được, nhưng mà em nói trước là loại máy đó tầm 120 triệu một cái, 31 làn thì...

@KH #n_tienmat_bo: À thôi, thôi khỏi khảo sát. Tôi nhớ ra là chủ trương của thành phố trong đề án này là bãi đỗ không dùng tiền mặt, máy tiền mặt thì vẫn phải có người thu tiền, kiểm quỹ hằng ngày, đi ngược lại. Ai không có ví thì nhân viên cổng hướng dẫn quét QR bằng app ngân hàng là được, ngân hàng nào giờ cũng quét VietQR.

@QA: Thế thì kịch bản test chị bỏ phần tiền mặt ra, tập trung vào ETC. Với kênh ETC chị muốn test trường hợp tài khoản giao thông không đủ số dư, xe ra thì sao?

@BE: Không đủ số dư thì hệ thống tự chuyển sang hiện VietQR ở cổng như xe bình thường, có thông báo lên màn hình là tài khoản ETC không đủ tiền. Cái đó em làm rồi chị.

@KH: Còn phí gửi xe thì tính theo lượt hay theo giờ? Tôi nhớ quyết định giá là theo lượt hai tiếng đầu rồi cộng thêm theo giờ.

@BE #k_thong6: Dạ đúng anh, bên em cấu hình theo đúng quyết định giá: ô tô dưới 9 chỗ 25.000 đồng hai giờ đầu, mỗi giờ tiếp theo 10.000 đồng, qua đêm thì tính theo mức qua đêm. Biểu giá để trong bảng cấu hình, sau này thành phố đổi giá thì bên Trung tâm tự sửa trên dashboard, không phải sửa code.

@QA: Chị test phần tính phí thì thấy chỗ giáp ranh giờ, ví dụ xe gửi đúng 2 giờ 0 phút 30 giây, hệ thống đang làm tròn lên thành 3 giờ. Cái này có đúng không anh Thịnh?

@KH: Bên tôi cho phép 10 phút ân hạn, quá 10 phút mới tính thêm giờ. Cái này có trong quy chế trông giữ xe rồi.

@BE: Dạ vậy là bên em làm sai, sửa thành ân hạn 10 phút, cái này nhỏ.

@PM #d_thanhtoan: Ok, vậy chốt: bãi đỗ chỉ thanh toán không tiền mặt, gồm VietQR động ở cổng, ba ví đối tác trong app và trừ tự động qua tài khoản ETC; không làm máy thu tiền mặt. Đối soát tự động hằng ngày, lệch thì treo giao dịch và cảnh báo kế toán Trung tâm; trừ hai lần thì hoàn tiền trong 3 ngày làm việc. Tính phí theo đúng quyết định giá, có 10 phút ân hạn.

@BE #a_doisoat: Job đối soát với phần truy vấn trạng thái trước khi tạo QR mới, cộng sửa ân hạn 10 phút, thì em làm xong trước ngày 10 tháng 11.

@QA: Có bản đó thì chị chạy lại toàn bộ kịch bản đối soát của cả ba kênh.

@KH: Còn nhà cung cấp ETC thứ hai, nếu tháng 11 họ không kịp thì sao?

@BE: Dạ thì thí điểm chạy với một nhà cung cấp, xe dán thẻ của bên kia thì cổng tự chuyển sang hiện VietQR, không kẹt barie. Theo thống kê bên Trung tâm gửi thì khoảng 63% ô tô trong thành phố dán thẻ của nhà cung cấp đã tích hợp.

## TOPIC | Rà soát chức năng nhận dạng biển số xe tại làn cổng bãi đỗ | Quay lại nhận dạng biển số: bản v2.3 đạt 89,4% ban đêm, 86% khi mưa, nhưng 9 làn ngoài trời vẫn chỉ 78% do thiếu sáng, thử đèn hồng ngoại đạt 94%; thống nhất lắp đèn hồng ngoại cho 9 làn ngoài trời bằng kinh phí dự phòng và chạy v2.3 song song một tuần trước khi thay.

@AI: Chị Uyên ơi, cho em xin quay lại chuyện biển số một chút được không ạ, em có kết quả bản v2.3 rồi.

@PM: Ừ, nói luôn đi, đang nóng.

@AI #k_nhat3: Dạ. Bản v2.3 chạy trên cùng tập test 18.400 ảnh: ban ngày 97,1%, tăng nhẹ thôi; ban đêm lên 89,4%, trời mưa 86,0%; biển vuông hai dòng lên 93%. Nhầm 8 với B giảm hẳn vì em thêm nhiều ảnh biển vuông. Nhưng mà em tách riêng 9 làn ngoài trời ở 4 bãi lộ thiên ra thì ban đêm vẫn chỉ 78%, tức là phần còn lại không phải do mô hình nữa, mà do ảnh quá tối, nhiễu hạt, ký tự bị nhòe, mô hình nào cũng chịu. Còn 22 làn trong hầm với có mái che thì ban đêm đã lên 93%.

@KH: Thế tức là đúng như tôi nói, vấn đề là mấy làn lộ thiên.

@QA: Chị xác nhận thêm là bên chị có chạy độc lập trên 2.000 ảnh do bên chị tự chụp ban đêm, không nằm trong tập huấn luyện, bản v2.3 được 88,7%, khớp với số của Nhật, chênh không đáng kể.

@IOT #k_trieu3: Cái này đúng. Camera ở 9 làn đó là loại có hồng ngoại tích hợp nhưng tầm chiếu chỉ khoảng 10 mét, mà xe dừng ở vạch cách camera 12 đến 14 mét. Chỉnh phơi sáng thì bên anh thử rồi, phơi lâu thì xe đang chạy chậm bị nhòe. Lắp thêm đèn hồng ngoại rời, loại 850 nanomet chuyên cho đọc biển số, thì mỗi làn khoảng 6,5 triệu cả công lắp, 9 làn là gần 59 triệu. Bên anh đã gắn thử một đèn ở làn số 2 bãi Quảng trường hôm thứ Sáu, ban đêm đọc lên 94%.

@KH: Thế thì phải lắp. Lúc nãy tôi bảo chưa lắp đèn nhưng mà với số liệu này thì khác rồi. 59 triệu thì tôi xin trích từ khoản dự phòng của dự án được, không phải chờ kế hoạch năm sau. Mà đèn hồng ngoại đó có làm chói mắt tài xế không?

@IOT: Không anh, ánh sáng 850 nanomet thì mắt người gần như không thấy, chỉ thấy một chấm đỏ mờ ở mặt đèn thôi, không ảnh hưởng gì tài xế.

@QA: Chị hỏi thêm, bản v2.3 có làm chậm đi không? Lúc nãy anh Thông nói độ trễ đang 600 mili giây.

@AI: Dạ chậm hơn một chút, trung bình 640 mili giây một lượt, vẫn dưới mức 1 giây theo yêu cầu. Bộ nhớ GPU thì tăng không đáng kể.

@DO: Em hỏi thêm là máy chủ GPU ở trung tâm dữ liệu hiện mới có một card, chạy hai bản song song thì có đủ không ạ?

@AI: Dạ mô hình v2.3 to hơn khoảng 15%. Hai bản chạy song song thì GPU lên khoảng 70% giờ cao điểm, vẫn đủ, nhưng em nghĩ là bản mới chỉ nên chạy trên staging, lấy luồng ảnh sao chép từ production sang, không đụng vào máy production.

@DO: Cái đó làm được, mirror luồng ảnh ở tầng message queue thôi, production không bị ảnh hưởng gì.

@BE #k_thong4: Anh đề nghị không thay mô hình ngay trên production mà chạy song song, kiểu shadow mode, một tuần trên staging với luồng ảnh thật từ các cổng, so kết quả hai bản từng lượt, ổn thì mới chuyển. Thay mô hình đúng lúc sắp thí điểm mà lỗi thì rất khổ, nhất là lỗi kiểu đọc sai có hệ thống một ký tự nào đó.

@KH: Tôi đồng ý chạy song song. Mà Nhật này, biển số tạm, biển đỏ của xe công vụ với biển xe nước ngoài thì mô hình có đọc được không?

@AI: Dạ biển đỏ với biển xanh thì đọc được, tập test có khoảng 600 ảnh. Biển tạm giấy dán kính thì không đọc được anh, mấy trường hợp đó vẫn phải để nhân viên cổng nhập tay, may là rất ít, trong ba tuần chỉ có 41 lượt.

@QA: Thế thì kịch bản test của chị thêm nhóm biển tạm vào luồng xác nhận thủ công, để chắc là không bị kẹt barie.

@KH: Ngoài ra tôi muốn biết là mấy làn trong hầm, ban đêm đã 93% rồi, thì có cần làm gì thêm không, hay để nguyên?

@AI: Dạ trong hầm thì em nghĩ để nguyên, phần sai còn lại chủ yếu là biển bẩn, biển bị cong vênh hoặc bị che một phần bởi giá chở xe đạp, mấy cái đó đẩy sang nhân viên xác nhận là hợp lý.

@IOT: Trong hầm thì đèn đủ rồi. Chỉ có bãi Bệnh viện tỉnh là camera làn ra bị ngược sáng buổi sáng, nắng chiếu thẳng vào ống kính từ 7 đến 8 giờ, cái đó chỉnh lại góc camera là được, không tốn tiền.

@PM #d_den: Ok, chốt lại phần biển số: lắp đèn hồng ngoại bổ trợ cho 9 làn ngoài trời, kinh phí trích từ dự phòng dự án như anh Thịnh nói. Mô hình v2.3 chạy song song shadow một tuần trên staging, đạt thì thay bản v2.2 trước ngày 20 tháng 11. Ngưỡng 0,85 vẫn giữ nguyên như đã chốt.

@IOT #a_den: Đèn thì bên anh đặt hàng luôn hôm nay, lắp xong cả 9 làn trước ngày 20 tháng 11.

@AI #a_shadow: Em dựng shadow mode từ thứ Hai tuần sau, chạy đủ bảy ngày rồi gửi báo cáo so sánh cho chị Uyên với anh Thông.

## TOPIC | Xây dựng bảng điều khiển vận hành và báo cáo doanh thu cho Trung tâm | Dashboard ba màn bản đồ, làn cổng, báo cáo doanh thu đã xong khoảng 70%, thiếu xuất Excel và phân quyền; đề xuất thống kê hãng xe màu xe bị gạt; thống nhất dữ liệu bản đồ gom 30 giây, phân quyền ba cấp, báo cáo theo mẫu biểu kế toán của Trung tâm.

@PM: Rồi, quay lại thứ tự. Mục tiếp theo là dashboard vận hành cho Trung tâm. Anh Thông nhé, phần này team anh làm.

@BE #k_thong5: Dạ. Dashboard có ba màn chính. Màn bản đồ hiện 12 bãi và 5 tuyến phố, tô màu theo tỷ lệ lấp đầy, cập nhật qua websocket. Màn cổng hiện trạng thái 31 làn, làn nào đang chờ nhân viên xác nhận biển, làn nào barie báo lỗi, làn nào mất kết nối camera. Màn báo cáo doanh thu thì theo bãi, theo kênh thanh toán, theo ngày, theo tháng. Tổng thể đang xong khoảng 70%, phần báo cáo còn thiếu xuất Excel, còn phân quyền thì hiện mới có hai loại tài khoản là quản trị và người xem.

@KH #k_thinh4: Bên tôi cần phân quyền ba cấp: lãnh đạo Trung tâm xem toàn bộ, đội trưởng mỗi khu xem các bãi thuộc khu mình, nhân viên cổng chỉ thấy làn mình đang trực. Báo cáo doanh thu thì phải khớp mẫu biểu kế toán của Trung tâm, vì cuối tháng phải nộp lên Sở Tài chính, sai mẫu là họ trả về, kế toán lại phải ngồi gõ lại bằng tay.

@PM: Mẫu biểu đó bên em chưa có bản chính thức anh ạ, đợt trước mới nhận được bản nháp, nhiều cột chưa rõ cách tính.

@KH #a_maubieu: Thế thì chị gửi tôi danh sách các trường dữ liệu mà hệ thống đang có, tôi chuyển kế toán đối chiếu rồi gửi lại mẫu chuẩn. Chị gửi trước thứ Năm nhé.

@PM #a_maubieu_ok: Dạ vâng anh, thứ Năm em gửi.

@AI #n_hangxe: Em thấy camera cổng đang chụp được cả đầu xe, em có thể thêm một module nhận diện hãng xe với màu xe, đưa lên dashboard thống kê, kiểu bao nhiêu phần trăm là xe hãng nào, màu gì, phục vụ phân tích.

@PM #n_hangxe_giao: Nghe cũng hay, thế Nhật làm thử một bản demo nhỏ nhé.

@KH #n_hangxe_bo: Thôi, cái đó không cần đâu. Trung tâm không dùng số liệu hãng xe màu xe để làm gì cả, mà thu thập thêm dữ liệu về phương tiện cá nhân thì lại phải giải trình về bảo vệ dữ liệu cá nhân. Nhật tập trung vào biển số cho tôi.

@AI: Dạ vâng anh.

@QA #k_bich3: Chị test dashboard thì thấy khi mở cùng lúc khoảng 30 tab màn bản đồ thì websocket bắt đầu rớt kết nối, chưa rõ là do server hay do load balancer. Chị sẽ nói kỹ hơn ở phần test tải.

@KH: Mà dữ liệu trên màn bản đồ thì bao lâu cập nhật một lần?

@BE: Dạ hiện đang đẩy ngay khi có thay đổi, nhưng với 640 cảm biến cộng 31 làn thì giờ cao điểm khoảng 40 sự kiện mỗi giây, máy tính cấu hình yếu ở phòng điều hành của Trung tâm bị giật. Em đề xuất gom lại, 30 giây đẩy một lần, riêng màn cổng thì vẫn đẩy ngay vì nhân viên cần thấy lượt chờ xác nhận.

@KH: 30 giây là được, Trung tâm không cần từng giây. Màn cổng thì đúng là phải ngay.

@MB: Dạ app cũng dùng chung API trạng thái bãi với dashboard, gom 30 giây thì số chỗ trống trên app cũng theo nhịp đó luôn ạ?

@BE: Ừ, app thì 30 giây là quá ổn, người dùng đang lái xe cũng không nhìn liên tục, riêng màn đếm ngược giữ chỗ thì tính ở máy, không phụ thuộc.

@QA: Chị đề nghị thêm cái nhật ký thao tác, nhân viên cổng sửa biển hay mở barie bằng tay thì phải ghi lại ai, lúc nào, vì sau này có tranh chấp về phí là cần.

@BE: Cái đó có rồi chị, mọi thao tác thủ công đều có log, nhưng chưa có màn tra cứu, em thêm vào màn báo cáo.

@KH: Một việc nữa, phòng điều hành bên tôi có màn hình ghép lớn, muốn đưa màn bản đồ lên đó chạy liên tục cả ngày. Có được không?

@BE: Dạ được anh, màn bản đồ có chế độ trình chiếu, tự làm mới phiên, không bị đăng xuất giữa chừng. Chỉ cần máy tính nối màn hình ghép có trình duyệt bản mới.

@QA: Chị thấy màn báo cáo doanh thu tháng mở mất gần 9 giây với dữ liệu giả lập một tháng của 12 bãi. Thí điểm thì còn chịu được, nhưng mở rộng ra 52 bãi thì chắc chậm lắm.

@BE #k_thong7: Dạ cái đó em biết, hiện đang tính trực tiếp từ bảng giao dịch thô. Em sẽ làm bảng tổng hợp theo ngày, chạy job lúc nửa đêm, báo cáo tháng chỉ cộng khoảng 30 dòng mỗi bãi, dự kiến xuống dưới 1 giây. Cái này nằm luôn trong phần hoàn thiện báo cáo.

@PM #d_dashboard: Chốt dashboard: dữ liệu bản đồ gom cập nhật 30 giây một lần, màn cổng đẩy ngay; phân quyền ba cấp như anh Thịnh nói; báo cáo doanh thu theo bãi, kênh, ngày, tháng, xuất Excel theo mẫu biểu kế toán của Trung tâm; có màn tra cứu nhật ký thao tác thủ công. Không làm thống kê hãng xe, màu xe.

@BE #a_dashboard: Bên em hoàn thiện dashboard, gồm phân quyền ba cấp và xuất Excel theo mẫu, trước ngày 15 tháng 11, với điều kiện có mẫu chuẩn trong tháng này.

## TOPIC | Rà soát kết quả kiểm thử tải và kiểm thử bảo mật hệ thống | Test tải gấp ba giờ cao điểm đạt với API vào ra p95 420 mili giây nhưng dịch vụ realtime rớt kết nối ở 4.200 kết nối; pentest phát hiện 2 lỗi cao (IDOR lịch sử đỗ xe, refresh token không hết hạn) và 5 lỗi trung bình; thống nhất sửa lỗi cao trước 5/11, bật autoscaling, test tải lần hai ngày 12/11.

@PM: Sang kết quả test tải và bảo mật. Chị Bích.

@QA #k_bich4: Ừ. Test tải thì chị dùng k6 giả lập giờ cao điểm. Theo số liệu bên Trung tâm thì giờ cao điểm cả 12 bãi khoảng 350 lượt xe vào ra mỗi phút, cộng khoảng 2.000 người dùng app cùng lúc xem bản đồ. Chị test gấp ba, tức là 1.050 lượt mỗi phút và 6.000 người dùng app. API vào ra đạt, p95 là 420 mili giây, không có lỗi. API giữ chỗ cũng đạt. Nhưng mà dịch vụ realtime, cái websocket đẩy trạng thái cho app với dashboard, đến khoảng 4.200 kết nối thì CPU của pod lên 95%, bắt đầu rớt kết nối, đúng cái chị thấy lúc nãy khi mở nhiều tab.

@DO #k_tin1: Dạ, dịch vụ realtime hiện đang chạy cố định 2 pod, em chưa bật autoscaling vì lúc đầu sợ scale ra nhiều pod thì sticky session của websocket bị lỗi, client nhảy pod là mất trạng thái. Giờ có Redis pub/sub làm lớp trung gian rồi thì scale ngang được, em bật HPA tối đa 6 pod, ngưỡng CPU 70%.

@BE: Với lại gom 30 giây như vừa chốt thì tải đẩy giảm đi nhiều, anh nghĩ 6 pod là dư.

@KH: Thế lúc test tải thì luồng ảnh camera có giả lập không, hay chỉ giả lập API thôi?

@QA: Có giả lập luôn anh, chị phát lại ảnh thật của 31 làn với tốc độ gấp ba, nhận dạng vẫn trung bình 700 mili giây một lượt, GPU lên 81%.

@AI: Dạ 81% là với bản v2.2, bản v2.3 to hơn thì chắc lên khoảng 88%, vẫn chịu được nhưng hơi sát, đợt test lần hai mình nên đo lại với bản mới.

@QA #k_bich5: Còn bảo mật thì bên chị thuê ngoài một đơn vị pentest, họ gửi báo cáo hôm thứ Hai: 2 lỗi mức cao, 5 lỗi trung bình, 9 lỗi thấp. Lỗi cao thứ nhất là IDOR ở API lịch sử đỗ xe, đổi ID trong đường dẫn là xem được lịch sử của tài khoản khác, có cả biển số, giờ vào ra, bãi nào. Lỗi cao thứ hai là refresh token của app không hết hạn, đăng xuất rồi mà token cũ vẫn dùng được, không thu hồi được.

@KH: Lịch sử đỗ xe của người khác mà lộ ra là chuyện lớn đấy, đó là dữ liệu vị trí, biết người ta hay đỗ ở đâu giờ nào.

@BE #a_baomat: Dạ, hai lỗi cao em nhận, sửa trong tuần này. IDOR thì em kiểm tra quyền sở hữu ở tầng service cho tất cả endpoint có ID trong đường dẫn, không chỉ riêng API lịch sử. Refresh token thì cho hết hạn sau 30 ngày, thêm danh sách thu hồi khi đăng xuất hoặc đổi mật khẩu.

@PM #a_pentest: Sửa xong thì chị chạy lại toàn bộ kịch bản pentest của hai lỗi cao, rà luôn các endpoint tương tự nhé, trước ngày 5 tháng 11 để còn kịp gửi báo cáo cho anh Thịnh.

@QA #a_pentest_ok: Ừ, được, chị lên lịch luôn.

@KH: Mà dữ liệu biển số với lịch sử đỗ xe trong cơ sở dữ liệu có mã hóa không?

@BE: Dạ ổ đĩa cơ sở dữ liệu thì mã hóa toàn bộ, còn số điện thoại với biển số trong bảng tài khoản thì mã hóa thêm ở cấp trường. Đơn vị pentest cũng không ghi nhận lỗi ở phần này.

@DO #k_tin4: Còn 5 lỗi trung bình thì phần lớn là cấu hình, thiếu mấy security header, load balancer còn bật TLS 1.0 với 1.1, cookie của dashboard thiếu cờ Secure. Phía em xử lý được nhanh, mỗi cái vài tiếng. Có một lỗi trung bình là rate limit API đăng nhập chưa có, cái đó anh Thông với em làm chung.

@BE: Rate limit thì em tính 5 lần sai mật khẩu trong 15 phút là khóa tạm tài khoản 30 phút, còn theo IP thì 100 request một phút cho API đăng nhập.

@QA #n_otp: Chị nghĩ là có lẽ nên thêm OTP khi đăng nhập trên thiết bị mới, vì tài khoản app có liên kết ví, có cả lịch sử vị trí.

@BE: OTP qua SMS thì mỗi tin khoảng 700 đồng, không nhiều, nhưng cần thêm hợp đồng với nhà mạng, chắc không kịp thí điểm.

@KH #k_thinh5: OTP thì để sau thí điểm hẵng tính. Còn theo quy định thì trước khi đưa hệ thống thông tin cấp độ 3 vào vận hành thì phải có báo cáo kiểm tra, đánh giá an toàn thông tin, lỗi mức cao phải khắc phục hết, có kết quả kiểm tra lại. Lỗi trung bình thì có thể kèm kế hoạch khắc phục, nhưng bên tôi muốn sửa luôn trước thí điểm cho sạch.

@BE: Dạ được anh, lỗi trung bình thì trước thí điểm xong hết, còn 9 lỗi thấp thì em xin đưa vào backlog tháng 12.

@QA: Test tải thì sau khi bật autoscaling chị chạy lại lần hai, chị đề xuất ngày 12 tháng 11, lúc đó có cả bản đối soát mới với màn xác nhận thủ công, test chung một lượt cho đỡ tốn công.

@DO: Đợt hai em đề nghị giữ tải đỉnh liên tục 2 tiếng chứ không chỉ 20 phút như lần đầu, để xem có rò rỉ bộ nhớ hay không.

@QA: Ừ, hợp lý, chị sửa kịch bản thành 2 tiếng.

@PM #d_baomat: Chốt: hai lỗi mức cao bắt buộc sửa xong và kiểm thử lại trước ngày 5 tháng 11; 5 lỗi trung bình sửa xong trước thí điểm; 9 lỗi thấp đưa vào backlog tháng 12. Dịch vụ realtime bật autoscaling tối đa 6 pod, test tải lần hai vào ngày 12 tháng 11.

@DO #a_hpa: Em cấu hình autoscaling với xử lý phần TLS, header, cookie trước ngày 12, kịp đợt test tải lần hai.

## TOPIC | Chuẩn bị hạ tầng máy chủ và quy trình triển khai hệ thống | Hệ thống chạy tại trung tâm dữ liệu thành phố trên cụm Kubernetes, thiếu môi trường staging riêng và quyền VPN cho nhà thầu; đề xuất cảnh báo qua Zalo cho trực ban chưa chốt; thống nhất sao lưu hằng ngày giữ 30 ngày, ảnh biển số lưu 90 ngày, deploy production sau 22 giờ và báo trực ban trước một ngày.

@PM: Mục bảy, hạ tầng triển khai. Tín.

@DO #k_tin2: Dạ. Theo hợp đồng thì hệ thống chạy ở trung tâm dữ liệu của thành phố. Bên Trung tâm đã cấp 6 máy ảo, mỗi máy 16 core, 64 GB RAM, em dựng cụm Kubernetes 3 master 3 worker, còn cơ sở dữ liệu PostgreSQL thì chạy riêng trên 2 máy ảo nữa theo kiểu primary với replica. Vấn đề là hiện tại mình mới có một môi trường staging dùng chung cho cả dev lẫn test, nên lúc chị Bích chạy test tải thì cả team không deploy được gì, mà shadow mode của Nhật tuần sau cũng cần môi trường giống production. Thứ hai là bên em chưa có quyền VPN vào trung tâm dữ liệu, mỗi lần deploy phải nhờ cán bộ bên Trung tâm mở kết nối, mất gần nửa ngày.

@KH #k_thinh6: VPN thì bên tôi có quy trình, cấp tối đa 3 tài khoản cho nhà thầu, có ghi log truy cập, hết dự án thì thu hồi. Muốn thêm máy ảo cho staging thứ hai thì trung tâm dữ liệu vẫn còn tài nguyên.

@PM #a_staging2: Ừ, thế thì em dựng thêm một môi trường staging thứ hai, cấu hình giống production, dành riêng cho test tải với shadow mode, xong trước ngày 30 tháng 10 nhé.

@BE: Staging hai thì cần thêm khoảng 3 máy ảo nữa đấy anh Thịnh, cấu hình như máy worker.

@KH #a_vpn: Ừ, tôi cấp luôn 3 máy ảo với 3 tài khoản VPN cùng một lượt, thứ Hai tới là có. Danh sách người dùng VPN thì gửi tôi họ tên, số điện thoại.

@QA: Mà staging hai thì dữ liệu lấy ở đâu? Chị không muốn test trên dữ liệu thật của người dùng beta, có biển số, số điện thoại.

@DO #k_tin3: Dạ, staging hai em sinh dữ liệu giả, biển số ngẫu nhiên theo đúng định dạng, riêng luồng ảnh cho shadow mode thì là ảnh thật nhưng chỉ lưu 7 ngày rồi xóa. Còn về sao lưu thì em đang để PostgreSQL backup full hằng ngày lúc 1 giờ sáng, cộng WAL liên tục để khôi phục được đến từng thời điểm, giữ 30 ngày, bản sao lưu đẩy sang kho lưu trữ ở site dự phòng của thành phố. Ảnh chụp biển số thì lưu 90 ngày rồi tự xóa, theo yêu cầu bên Trung tâm. Deploy thì dùng rolling update, có rollback tự động nếu health check không đạt sau 2 phút.

@QA: Chị đề nghị deploy production chỉ làm ngoài giờ, sau 22 giờ, vì bãi đỗ chạy 24/7 nhưng đêm ít xe nhất, lỡ có lỗi thì ít người bị ảnh hưởng.

@KH: Đồng ý, và mỗi lần deploy phải báo trước cho trực ban Trung tâm ít nhất một ngày, có nội dung thay đổi, để họ biết mà theo dõi.

@DO #k_tin5: Dạ. Về dự phòng thì nếu trung tâm dữ liệu chính gặp sự cố, em ước khôi phục ở site dự phòng mất khoảng 4 tiếng, vì phải dựng lại cụm. Trong thời gian đó thì các cổng chuyển sang chế độ offline, máy tính tại cổng vẫn đọc biển và lưu cục bộ, có mạng lại thì đồng bộ lên.

@KH: 4 tiếng thì chấp nhận được cho giai đoạn thí điểm. Nhưng chế độ offline đó đã test chưa?

@QA: Chị test rồi, rút mạng một cổng 2 tiếng, lúc có mạng lại đồng bộ đủ 214 lượt, không mất lượt nào, nhưng có 3 lượt bị tính phí sai vì đồng hồ máy tính cổng lệch 4 phút so với server.

@DO: Cái đó là do máy cổng chưa trỏ về máy chủ NTP của trung tâm dữ liệu, cấu hình lại là hết.

@BE: Lệch giờ thì ảnh hưởng cả đối soát nữa đấy, cái này phải xử lý trước thí điểm.

@DO #n_zalo: Em có ý là, ờ, có lẽ mình nên đẩy thêm cảnh báo qua Zalo cho trực ban của Trung tâm khi barie lỗi hay mất kết nối camera, ngoài kênh cảnh báo nội bộ của team. Cái này em chưa ước lượng được công, chắc phải tìm hiểu API.

@KH: Để tôi hỏi lại trực ban xem họ có muốn nhận không đã, nhiều cảnh báo quá thì họ cũng tắt đi thôi. Chưa làm vội.

@BE: Còn phần giám sát nội bộ thì anh thấy Grafana với Alertmanager đang ổn rồi, ngưỡng cảnh báo mình chỉnh lại sau test tải lần hai là được.

@KH: Còn log hệ thống thì lưu bao lâu? Theo yêu cầu an toàn thông tin cấp độ 3 thì nhật ký hệ thống phải lưu tối thiểu 3 tháng.

@DO: Dạ hiện log tập trung đang giữ 30 ngày, em nâng lên 6 tháng cho chắc, dung lượng khoảng 400 GB, vẫn đủ chỗ.

@PM #d_hatang: Chốt phần hạ tầng: triển khai tại trung tâm dữ liệu thành phố trên cụm Kubernetes hiện có; sao lưu full hằng ngày, giữ 30 ngày, đẩy sang site dự phòng; ảnh biển số lưu 90 ngày; log hệ thống lưu 6 tháng; deploy production chỉ sau 22 giờ, báo trực ban trước một ngày; dùng rolling update có rollback tự động.

@QA: Chị cần thêm một bản hướng dẫn rollback bằng tay nữa, phòng khi rollback tự động không chạy, để đội trực đêm có cái mà làm theo.

@DO #a_rollback: Dạ cái đó em viết chung vào tài liệu vận hành, chị review giúp em.

## TOPIC | Thống nhất kế hoạch thí điểm tại 12 bãi đỗ và phân công công việc | Thí điểm từ 1/12 trong hai tháng tại 12 bãi và 5 tuyến phố, tuần đầu trực 24/7 tại 4 bãi đông nhất; chốt tiêu chí mở rộng ra các bãi còn lại; phân công tập huấn hai đợt, nộp app lên kho, truyền thông cho người dân và xếp lịch trực.

@PM #k_uyen1: Mục cuối là kế hoạch thí điểm. Em tóm tắt nhé: thí điểm bắt đầu từ 0 giờ ngày 1 tháng 12, kéo dài hai tháng, trên 12 bãi và 5 tuyến phố, tổng khoảng 1.860 chỗ đỗ ô tô. Tuần đầu bên em cử người trực tại chỗ 24/7 ở 4 bãi đông nhất là Chợ Đình, Quảng trường, Bệnh viện tỉnh và Khu hành chính tập trung, các bãi còn lại trực từ 6 giờ đến 22 giờ. Cần tập huấn cho khoảng 60 nhân viên trông giữ xe của Trung tâm. Trước đó app phải được duyệt trên cả hai kho ứng dụng, và người dân phải được thông báo.

@KH #k_thinh7: Dạ, bên tôi có mấy yêu cầu. Một là phải thông báo cho người dân ít nhất một tuần trước, qua báo, đài phát thanh, cổng thông tin thành phố, và có biển hướng dẫn ở từng bãi, có mã QR tải app. Hai là tập huấn phải làm hai đợt, vì nhân viên chia ca, một lúc không gom đủ được. Ba là phải có tiêu chí rõ ràng, đo được, để sau hai tháng quyết định có mở rộng ra 40 bãi còn lại hay không, chứ không phải ngồi cảm tính.

@AI: Về tiêu chí thì phần nhận dạng em đề xuất độ chính xác tự động ban ngày từ 97%, ban đêm từ 92%, tính trên số lượt thực tế trong thời gian thí điểm.

@QA: Chị thêm: tỷ lệ giao dịch lệch đối soát dưới 0,1%, hệ thống sẵn sàng từ 99,5% trở lên.

@KH: Thêm một cái nữa, tỷ lệ khiếu nại dưới 1 trên 1.000 lượt xe. Khiếu nại thì tính cả qua đường dây nóng lẫn trong app.

@BE: Em đề nghị thêm vào tiêu chí thời gian trung bình qua cổng, vì đó là cái người dân cảm nhận rõ nhất. Hiện đo trên staging thì từ lúc xe dừng ở vạch đến lúc barie mở là khoảng 2,1 giây với lượt tự động.

@KH: Ừ, đưa vào, trung bình dưới 5 giây, tính cả lượt phải xác nhận thủ công.

@PM #d_thidiem: Chốt: thí điểm từ ngày 1 tháng 12, kéo dài hai tháng, 12 bãi và 5 tuyến phố; tuần đầu trực 24/7 tại 4 bãi đông nhất. Tiêu chí mở rộng: nhận dạng tự động ban ngày từ 97%, ban đêm từ 92%; lệch đối soát dưới 0,1%; sẵn sàng từ 99,5%; khiếu nại dưới 1 trên 1.000 lượt xe; thời gian qua cổng trung bình dưới 5 giây. Đánh giá vào tuần đầu tháng 2.

@BE: Em hỏi chút, trong hai tháng thí điểm có đóng băng tính năng không chị, hay vẫn đẩy bản sửa lỗi lên?

@PM #a_taphuan: Vẫn đẩy bản sửa lỗi theo đúng quy trình sau 22 giờ, nhưng không thêm tính năng mới. Giờ em phân công nốt. Tập huấn nhân viên trông giữ xe thì em với chị Bích làm, hai đợt vào ngày 24 và 26 tháng 11; em soạn tài liệu hướng dẫn, chị Bích demo trên hệ thống thật.

@QA #a_taphuan_ok: Ừ, chị chuẩn bị bản demo với tài khoản tập huấn riêng, không dùng dữ liệu thật.

@MB #a_kho: Dạ app thì em nộp lên App Store với Google Play trước ngày 20 tháng 11, để còn dư thời gian nếu bị từ chối phải nộp lại. App có thu tiền nên Apple hay hỏi thêm về thanh toán, nhưng phí gửi xe là dịch vụ thực tế nên không phải dùng thanh toán trong ứng dụng của Apple, em chuẩn bị sẵn giải trình.

@KH #a_truyenthong: Thông báo cho người dân thì bên tôi làm, phát hành trên báo, đài, cổng thông tin trước ngày 23 tháng 11. Biển hướng dẫn ở 12 bãi thì Trung tâm in và lắp luôn.

@QA: Chị hỏi về tiếp nhận phản ánh trong thí điểm, người dân gọi đường dây nóng của Trung tâm thì những lỗi liên quan đến hệ thống ai xử lý?

@KH #d_sla: Tổng đài của Trung tâm tiếp nhận, phân loại, cái gì do hệ thống thì chuyển sang nhóm hỗ trợ của nhà thầu qua nhóm chat chung. Yêu cầu phản hồi trong 2 giờ với lỗi làm kẹt barie, 1 ngày làm việc với các lỗi khác.

@BE #a_trucca: Dạ mức phản hồi đó bên em nhận. Lịch trực tuần đầu thì em xếp, 4 bãi đông mỗi bãi có một người tại chỗ, team backend với devops chia ca, có thêm một người on-call từ xa cho các bãi còn lại, gửi lịch trước ngày 25 tháng 11.

@DO: Em bổ sung là trước ngày 1 tháng 12 mình nên chạy tổng duyệt một đêm, kiểu cho cả 12 bãi hoạt động như thật với xe của nhân viên, kiểm tra từ cổng vào, thanh toán đến đối soát sáng hôm sau.

@KH #d_tongduyet: Đồng ý, tổng duyệt đêm 28 tháng 11. Bên tôi huy động 20 xe của cán bộ Trung tâm chạy vòng qua các bãi, mỗi xe dùng một kênh thanh toán khác nhau.

@PM: Ok. Còn ai có gì nữa không ạ? Không thì mình kết thúc ở đây. Cảm ơn anh Thịnh và cả nhà, biên bản em gửi chiều nay.

@KH: Cảm ơn mọi người, còn hơn một tháng nữa thôi, cố gắng nhé.

```json gold
{
  "assignments": [
    {"actor": "Anh Thông (Trưởng nhóm Backend)", "actor_aliases": ["bên em"], "task": "Làm màn hình xác nhận thủ công biển số cho nhân viên cổng khi confidence dưới ngưỡng", "deadline": "ngày 31 tháng 10 (hết sprint này)", "turns": ["a_xacnhan"]},
    {"actor": "Anh Thông (Trưởng nhóm Backend)", "actor_aliases": ["em"], "task": "Làm khóa theo bãi trên Redis chống đặt trùng chỗ cuối", "deadline": "thứ Tư tuần sau", "turns": ["a_khoabai"]},
    {"actor": "Châu (Lập trình di động)", "actor_aliases": ["em"], "task": "Thêm màn hình thanh toán phí giữ chỗ và đồng hồ đếm ngược thời gian giữ chỗ", "deadline": "trong sprint 14", "turns": ["a_demnguoc"]},
    {"actor": "Châu (Lập trình di động)", "actor_aliases": ["em"], "task": "Làm thông báo đẩy nhắc trước 5 phút khi sắp hết giờ giữ chỗ", "deadline": "trong sprint 14", "turns": ["a_nhacgio", "a_nhacgio_ok"]},
    {"actor": "Anh Thịnh (Phó Giám đốc Trung tâm Quản lý điều hành giao thông)", "actor_aliases": ["tôi"], "task": "Làm văn bản báo cáo Sở Giao thông vận tải về chức năng giữ chỗ có thu phí", "deadline": "tuần sau", "turns": ["a_vanban"]},
    {"actor": "Anh Triều (Kỹ sư thiết bị IoT)", "actor_aliases": ["anh"], "task": "Đẩy cấu hình ngưỡng xác nhận 90 giây cho toàn bộ 640 cảm biến", "deadline": "thứ Tư tuần sau", "turns": ["a_cauhinh", "a_cauhinh_ok"]},
    {"actor": "Anh Thịnh (Phó Giám đốc Trung tâm Quản lý điều hành giao thông)", "actor_aliases": ["tôi"], "task": "Làm văn bản gửi Công ty Chiếu sáng công cộng xin lắp 2 gateway trên cột đèn đoạn Hai Bà Trưng", "deadline": "trong tuần này", "turns": ["a_vbchieusang"]},
    {"actor": "Chị Uyên (Quản lý dự án)", "actor_aliases": ["em"], "task": "Chốt phụ lục hợp đồng và sandbox ổn định với ví điện tử thứ ba", "deadline": "trước ngày 31 tháng 10", "turns": ["a_vithu3"]},
    {"actor": "Anh Thông (Trưởng nhóm Backend)", "actor_aliases": ["em"], "task": "Làm job đối soát tự động hằng ngày, truy vấn trạng thái giao dịch trước khi tạo QR mới và sửa tính phí ân hạn 10 phút", "deadline": "trước ngày 10 tháng 11", "turns": ["a_doisoat"]},
    {"actor": "Anh Triều (Kỹ sư thiết bị IoT)", "actor_aliases": ["bên anh"], "task": "Đặt hàng và lắp đèn hồng ngoại cho 9 làn ngoài trời", "deadline": "trước ngày 20 tháng 11", "turns": ["d_den", "a_den"]},
    {"actor": "Nhật (Kỹ sư thị giác máy tính)", "actor_aliases": ["em"], "task": "Chạy mô hình v2.3 song song (shadow mode) một tuần trên staging và gửi báo cáo so sánh", "deadline": "từ thứ Hai tuần sau, chạy đủ bảy ngày", "turns": ["a_shadow"]},
    {"actor": "Chị Uyên (Quản lý dự án)", "actor_aliases": ["chị"], "task": "Gửi anh Thịnh danh sách các trường dữ liệu hệ thống đang có để kế toán đối chiếu mẫu biểu", "deadline": "trước thứ Năm", "turns": ["a_maubieu", "a_maubieu_ok"]},
    {"actor": "Anh Thông (Trưởng nhóm Backend)", "actor_aliases": ["bên em"], "task": "Hoàn thiện dashboard vận hành gồm phân quyền ba cấp và xuất Excel theo mẫu", "deadline": "trước ngày 15 tháng 11", "turns": ["a_dashboard"]},
    {"actor": "Anh Thông (Trưởng nhóm Backend)", "actor_aliases": ["em"], "task": "Sửa 2 lỗi bảo mật mức cao: IDOR các endpoint có ID và refresh token không hết hạn", "deadline": "trong tuần này", "turns": ["a_baomat"]},
    {"actor": "Chị Bích (Trưởng nhóm Kiểm thử)", "actor_aliases": ["chị"], "task": "Chạy lại kịch bản pentest hai lỗi cao và rà các endpoint tương tự", "deadline": "trước ngày 5 tháng 11", "turns": ["a_pentest", "a_pentest_ok"]},
    {"actor": "Tín (Kỹ sư DevOps)", "actor_aliases": ["em"], "task": "Cấu hình autoscaling dịch vụ realtime và xử lý lỗi TLS, header, cookie", "deadline": "trước ngày 12 tháng 11", "turns": ["a_hpa"]},
    {"actor": "Tín (Kỹ sư DevOps)", "actor_aliases": ["em"], "task": "Dựng môi trường staging thứ hai giống production cho test tải và shadow mode", "deadline": "trước ngày 30 tháng 10", "turns": ["a_staging2"]},
    {"actor": "Anh Thịnh (Phó Giám đốc Trung tâm Quản lý điều hành giao thông)", "actor_aliases": ["tôi"], "task": "Cấp thêm 3 máy ảo và 3 tài khoản VPN cho nhà thầu", "deadline": "thứ Hai tới", "turns": ["a_vpn"]},
    {"actor": "Tín (Kỹ sư DevOps)", "actor_aliases": ["em"], "task": "Viết hướng dẫn rollback bằng tay vào tài liệu vận hành, gửi chị Bích review", "deadline": null, "turns": ["a_rollback"]},
    {"actor": "Chị Uyên (Quản lý dự án)", "actor_aliases": ["em"], "task": "Soạn tài liệu hướng dẫn và tập huấn nhân viên trông giữ xe hai đợt", "deadline": "ngày 24 và 26 tháng 11", "turns": ["a_taphuan"]},
    {"actor": "Chị Bích (Trưởng nhóm Kiểm thử)", "actor_aliases": ["chị Bích", "chị"], "task": "Demo trên hệ thống thật trong buổi tập huấn, chuẩn bị tài khoản tập huấn riêng", "deadline": "ngày 24 và 26 tháng 11", "turns": ["a_taphuan", "a_taphuan_ok"]},
    {"actor": "Châu (Lập trình di động)", "actor_aliases": ["em"], "task": "Nộp app lên App Store và Google Play", "deadline": "trước ngày 20 tháng 11", "turns": ["a_kho"]},
    {"actor": "Anh Thịnh (Phó Giám đốc Trung tâm Quản lý điều hành giao thông)", "actor_aliases": ["bên tôi"], "task": "Thông báo thí điểm cho người dân trên báo, đài, cổng thông tin; in và lắp biển hướng dẫn tại 12 bãi", "deadline": "trước ngày 23 tháng 11", "turns": ["a_truyenthong"]},
    {"actor": "Anh Thông (Trưởng nhóm Backend)", "actor_aliases": ["em"], "task": "Xếp lịch trực tuần đầu thí điểm cho 4 bãi đông và on-call từ xa", "deadline": "trước ngày 25 tháng 11", "turns": ["a_trucca"]},
    {"actor": "Anh Thịnh (Phó Giám đốc Trung tâm Quản lý điều hành giao thông)", "actor_aliases": ["bên tôi"], "task": "Huy động 20 xe của cán bộ Trung tâm chạy tổng duyệt qua các bãi, mỗi xe một kênh thanh toán", "deadline": "đêm 28 tháng 11", "turns": ["d_tongduyet"]}
  ],
  "decisions": [
    {"text": "Ngưỡng confidence nhận dạng biển số 0,85; dưới ngưỡng không tự mở barie mà chuyển nhân viên cổng xác nhận; so khớp mờ lệch tối đa một ký tự; nhận dạng chạy trên máy chủ trung tâm", "turns": ["d_nguong"]},
    {"text": "Giữ chỗ tối đa 20 phút, phí giữ chỗ 5.000 đồng trừ vào phí gửi xe, quá hạn tự hủy không hoàn phí; mỗi bãi giữ 5% chỗ không cho đặt trước", "turns": ["d_giucho"]},
    {"text": "App chỉ hỗ trợ Android 9 trở lên và iOS 15 trở lên", "turns": ["d_hdh"]},
    {"text": "Nâng thời gian xác nhận cảm biến lên 90 giây; lắp thêm 2 gateway LoRa trên cột đèn đoạn Hai Bà Trưng bằng thiết bị dự phòng; server giữ bộ lọc dự phòng", "turns": ["d_cambien"]},
    {"text": "Chỉ thanh toán không tiền mặt (VietQR động, ba ví trong app, trừ tự động tài khoản ETC), không làm máy thu tiền mặt; đối soát tự động hằng ngày, lệch thì treo và cảnh báo kế toán; trừ hai lần hoàn tiền trong 3 ngày làm việc; tính phí theo quyết định giá, ân hạn 10 phút", "turns": ["d_thanhtoan"]},
    {"text": "Lắp đèn hồng ngoại bổ trợ cho 9 làn ngoài trời, kinh phí trích từ dự phòng dự án", "turns": ["d_den"]},
    {"text": "Mô hình v2.3 chạy song song shadow một tuần trên staging, đạt thì thay v2.2 trước ngày 20/11; giữ ngưỡng 0,85", "turns": ["d_den"]},
    {"text": "Dashboard: bản đồ gom cập nhật 30 giây, màn cổng đẩy ngay; phân quyền ba cấp; báo cáo doanh thu theo bãi, kênh, ngày, tháng, xuất Excel theo mẫu kế toán; có tra cứu nhật ký thao tác thủ công; không làm thống kê hãng xe, màu xe", "turns": ["d_dashboard"]},
    {"text": "Hai lỗi bảo mật cao sửa và kiểm thử lại trước 5/11; 5 lỗi trung bình sửa trước thí điểm; lỗi thấp vào backlog tháng 12; dịch vụ realtime autoscaling tối đa 6 pod; test tải lần hai ngày 12/11", "turns": ["d_baomat"]},
    {"text": "Triển khai tại trung tâm dữ liệu thành phố trên Kubernetes; sao lưu full hằng ngày giữ 30 ngày, đẩy sang site dự phòng; ảnh biển số lưu 90 ngày; log hệ thống lưu 6 tháng; deploy production sau 22 giờ, báo trực ban trước một ngày; rolling update có rollback tự động", "turns": ["d_hatang"]},
    {"text": "Thí điểm từ 1/12 trong hai tháng tại 12 bãi và 5 tuyến phố, tuần đầu trực 24/7 tại 4 bãi đông nhất; tiêu chí mở rộng: nhận dạng ban ngày ≥97%, ban đêm ≥92%, lệch đối soát <0,1%, sẵn sàng ≥99,5%, khiếu nại <1/1.000 lượt, thời gian qua cổng trung bình <5 giây; đánh giá tuần đầu tháng 2", "turns": ["d_thidiem"]},
    {"text": "Trong thí điểm vẫn đẩy bản sửa lỗi theo quy trình sau 22 giờ nhưng không thêm tính năng mới", "turns": ["a_taphuan"]},
    {"text": "Phản ánh lỗi hệ thống qua tổng đài Trung tâm chuyển nhóm hỗ trợ nhà thầu; phản hồi trong 2 giờ với lỗi kẹt barie, 1 ngày làm việc với lỗi khác", "turns": ["d_sla", "a_trucca"]},
    {"text": "Tổng duyệt toàn hệ thống 12 bãi vào đêm 28/11 với 20 xe của cán bộ Trung tâm", "turns": ["d_tongduyet"]}
  ],
  "negatives": [
    {"type": "superseded_decision", "text": "Tạm chưa lắp đèn chiếu sáng bổ trợ ở các làn ngoài trời, chỉ chỉnh tham số camera (đã đảo lại: lắp đèn hồng ngoại cho 9 làn)", "turns": ["d_khongden"]},
    {"type": "hedged_proposal", "text": "Chạy nhận dạng biển số trên thiết bị biên Jetson ở từng cổng (để sau thí điểm)", "turns": ["n_bien"]},
    {"type": "hedged_proposal", "text": "Cho đặt chỗ trước theo khung giờ, đặt cho ngày hôm sau (chưa bàn)", "turns": ["n_dattruoc"]},
    {"type": "hedged_proposal", "text": "Đẩy cảnh báo barie lỗi, mất kết nối camera qua Zalo cho trực ban Trung tâm (chờ hỏi trực ban, chưa làm)", "turns": ["n_zalo"]},
    {"type": "hedged_proposal", "text": "Thêm OTP khi đăng nhập trên thiết bị mới (để sau thí điểm)", "turns": ["n_otp"]},
    {"type": "rejected_task", "text": "Anh Thông khảo sát phương án tích hợp máy thu tiền mặt tự động tại cổng (bị gạt vì chủ trương không tiền mặt)", "turns": ["n_tienmat_giao", "n_tienmat_bo"]},
    {"type": "rejected_task", "text": "Nhật làm demo module nhận diện hãng xe, màu xe cho dashboard (bị gạt)", "turns": ["n_hangxe_giao", "n_hangxe_bo"]}
  ],
  "key_points": [
    {"speaker": "Nhật (Kỹ sư thị giác máy tính)", "point": "Mô hình v2.2 đọc đúng 96,8% ban ngày, 83,5% ban đêm, 80,2% khi mưa; biển vuông hai dòng 88%", "turns": ["k_nhat1"]},
    {"speaker": "Nhật (Kỹ sư thị giác máy tính)", "point": "Ngưỡng 0,85 đẩy 7% lượt ban ngày và 21% ban đêm cho người xác nhận, sai lọt qua dưới 0,5%", "turns": ["k_nhat2"]},
    {"speaker": "Anh Thịnh (Phó Giám đốc Trung tâm Quản lý điều hành giao thông)", "point": "Sai biển khi xe ra làm barie không mở, gây ùn ở bãi đông giờ cao điểm; 9 làn ngoài trời thiếu sáng", "turns": ["k_thinh1"]},
    {"speaker": "Anh Thông (Trưởng nhóm Backend)", "point": "Đã có so khớp mờ; đề xuất dưới ngưỡng confidence thì chuyển nhân viên cổng xác nhận", "turns": ["k_thong1"]},
    {"speaker": "Châu (Lập trình di động)", "point": "App đặt chỗ có beta nội bộ 46 người; người dùng không biết thời gian giữ chỗ còn lại, có trường hợp đến nơi hết chỗ", "turns": ["k_chau1"]},
    {"speaker": "Anh Thông (Trưởng nhóm Backend)", "point": "Lỗi đặt trùng chỗ cuối do race condition, chuyển sang khóa atomic trên Redis; giữ 5% chỗ cho khách vãng lai", "turns": ["k_thong2"]},
    {"speaker": "Anh Thịnh (Phó Giám đốc Trung tâm Quản lý điều hành giao thông)", "point": "38% giữ chỗ miễn phí bỏ không đến; quyết định giá đã có phí giữ chỗ tối đa 10.000 đồng", "turns": ["k_thinh2"]},
    {"speaker": "Chị Bích (Trưởng nhóm Kiểm thử)", "point": "App crash trên Android 8 (khoảng 3% thiết bị beta)", "turns": ["k_bich1"]},
    {"speaker": "Anh Triều (Kỹ sư thiết bị IoT)", "point": "Đã lắp 640 cảm biến trên 5 tuyến phố; 11% báo chiếm chỗ là ảo; 48 cảm biến đoạn Hai Bà Trưng mất 17% gói tin", "turns": ["k_trieu1"]},
    {"speaker": "Anh Triều (Kỹ sư thiết bị IoT)", "point": "Nâng thời gian xác nhận lên 90 giây giảm báo ảo xuống dưới 1%, app chậm khoảng 1,5 phút, pin lâu hơn", "turns": ["k_trieu2"]},
    {"speaker": "Anh Triều (Kỹ sư thiết bị IoT)", "point": "Cảm biến chuẩn IP68, chịu tải 20 tấn; 6 con hỏng (4 do đào đường, 2 lỗi pin); có theo dõi pin và tín hiệu từng cảm biến", "turns": ["k_trieu4"]},
    {"speaker": "Anh Thịnh (Phó Giám đốc Trung tâm Quản lý điều hành giao thông)", "point": "Lắp gateway trên cột đèn phải có văn bản gửi Công ty Chiếu sáng công cộng", "turns": ["k_thinh3"]},
    {"speaker": "Anh Thông (Trưởng nhóm Backend)", "point": "Ba kênh thanh toán VietQR, ví, ETC; đối soát thử 14.300 giao dịch lệch 0,6% do callback trễ gây trừ hai lần", "turns": ["k_thong3"]},
    {"speaker": "Chị Bích (Trưởng nhóm Kiểm thử)", "point": "Sandbox ví thứ ba không ổn định, kịch bản đối soát mới chạy được 40%", "turns": ["k_bich2"]},
    {"speaker": "Anh Thông (Trưởng nhóm Backend)", "point": "Tính phí theo quyết định giá: 25.000 đồng hai giờ đầu, 10.000 đồng mỗi giờ tiếp theo; biểu giá cấu hình được trên dashboard", "turns": ["k_thong6"]},
    {"speaker": "Anh Thịnh (Phó Giám đốc Trung tâm Quản lý điều hành giao thông)", "point": "Gạt máy thu tiền mặt vì chủ trương bãi đỗ không tiền mặt; người không có ví quét QR bằng app ngân hàng", "turns": ["n_tienmat_bo"]},
    {"speaker": "Nhật (Kỹ sư thị giác máy tính)", "point": "Bản v2.3 đạt 89,4% ban đêm, 86% khi mưa, biển vuông 93%; riêng 9 làn ngoài trời ban đêm vẫn 78% do ảnh quá tối", "turns": ["k_nhat3"]},
    {"speaker": "Anh Triều (Kỹ sư thiết bị IoT)", "point": "Camera 9 làn ngoài trời hồng ngoại chỉ chiếu 10 mét; đèn hồng ngoại rời 6,5 triệu/làn, thử một làn đạt 94%", "turns": ["k_trieu3"]},
    {"speaker": "Anh Thông (Trưởng nhóm Backend)", "point": "Đề nghị chạy v2.3 song song shadow mode một tuần trước khi thay trên production", "turns": ["k_thong4"]},
    {"speaker": "Anh Thông (Trưởng nhóm Backend)", "point": "Dashboard ba màn bản đồ, cổng, báo cáo doanh thu đã xong 70%, thiếu xuất Excel và phân quyền", "turns": ["k_thong5"]},
    {"speaker": "Anh Thông (Trưởng nhóm Backend)", "point": "Báo cáo tháng mở mất 9 giây; sẽ làm bảng tổng hợp theo ngày để xuống dưới 1 giây", "turns": ["k_thong7"]},
    {"speaker": "Anh Thịnh (Phó Giám đốc Trung tâm Quản lý điều hành giao thông)", "point": "Cần phân quyền ba cấp; báo cáo doanh thu phải khớp mẫu biểu kế toán nộp Sở Tài chính", "turns": ["k_thinh4"]},
    {"speaker": "Chị Bích (Trưởng nhóm Kiểm thử)", "point": "Test tải gấp ba giờ cao điểm: API vào ra p95 420 mili giây, dịch vụ realtime rớt kết nối ở khoảng 4.200 kết nối", "turns": ["k_bich4"]},
    {"speaker": "Chị Bích (Trưởng nhóm Kiểm thử)", "point": "Pentest: 2 lỗi cao (IDOR lịch sử đỗ xe, refresh token không hết hạn), 5 trung bình, 9 thấp", "turns": ["k_bich5"]},
    {"speaker": "Tín (Kỹ sư DevOps)", "point": "Dịch vụ realtime cố định 2 pod, có Redis pub/sub nên bật HPA tối đa 6 pod", "turns": ["k_tin1"]},
    {"speaker": "Anh Thịnh (Phó Giám đốc Trung tâm Quản lý điều hành giao thông)", "point": "Hệ thống cấp độ 3 phải khắc phục hết lỗi cao trước khi vận hành; muốn sửa cả lỗi trung bình trước thí điểm", "turns": ["k_thinh5"]},
    {"speaker": "Tín (Kỹ sư DevOps)", "point": "Cụm Kubernetes 6 máy ảo tại trung tâm dữ liệu thành phố; chỉ có một staging dùng chung và chưa có VPN", "turns": ["k_tin2"]},
    {"speaker": "Tín (Kỹ sư DevOps)", "point": "Sao lưu full hằng ngày cộng WAL, giữ 30 ngày; ảnh biển số lưu 90 ngày; rolling update có rollback tự động", "turns": ["k_tin3"]},
    {"speaker": "Tín (Kỹ sư DevOps)", "point": "Khôi phục ở site dự phòng khoảng 4 tiếng; trong lúc đó cổng chạy chế độ offline, lưu cục bộ rồi đồng bộ", "turns": ["k_tin5"]},
    {"speaker": "Anh Thịnh (Phó Giám đốc Trung tâm Quản lý điều hành giao thông)", "point": "Cấp tối đa 3 tài khoản VPN cho nhà thầu, có ghi log, thu hồi khi hết dự án", "turns": ["k_thinh6"]},
    {"speaker": "Chị Uyên (Quản lý dự án)", "point": "Thí điểm từ 1/12 hai tháng, 12 bãi, 1.860 chỗ; trực 24/7 tuần đầu tại 4 bãi đông; tập huấn 60 nhân viên", "turns": ["k_uyen1"]},
    {"speaker": "Anh Thịnh (Phó Giám đốc Trung tâm Quản lý điều hành giao thông)", "point": "Yêu cầu thông báo người dân trước một tuần, tập huấn hai đợt, tiêu chí đo được để quyết định mở rộng ra 40 bãi", "turns": ["k_thinh7"]}
  ]
}
```
