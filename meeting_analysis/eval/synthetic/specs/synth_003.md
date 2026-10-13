```json meta
{
  "meeting_id": "synth_003",
  "title": "Họp nội bộ dự án triển khai hệ thống quản lý kho WMS - Công ty logistics",
  "meeting_type": "stt_diarized",
  "length_bucket": "S",
  "tags": ["short_meeting", "asr_noise", "pronoun_actor", "diarized_labels"],
  "speakers": {
    "S0": "SPEAKER_00",
    "S1": "SPEAKER_01",
    "S2": "SPEAKER_02",
    "S3": "SPEAKER_03",
    "S4": "SPEAKER_04"
  },
  "identity_note": "SPEAKER_00 = anh Việt (trưởng dự án), SPEAKER_01 = chị Hằng (quản lý kho Bình Dương), SPEAKER_02 = Toàn (lập trình viên WMS), SPEAKER_03 = Khoa (tích hợp hệ thống), SPEAKER_04 = Dung (đào tạo và quy trình)"
}
```

## TOPIC | Xử lý lỗi lệch tồn kho sau go-live kho Bình Dương | Sau hai tuần vận hành WMS ở kho Bình Dương, tồn kho trên hệ thống lệch với thực tế khoảng 3% mã hàng do đồng bộ hai chiều với ERP bị trùng giao dịch khi mất mạng; thống nhất tạm dừng đồng bộ chiều ERP sang WMS, thêm khóa chống trùng và kiểm kê lại toàn kho.

@S0: Rồi alo alo mọi người nghe rõ không. Ok. Thế thì hôm nay là mình họp cái tuần thứ hai sau khi go live cái kho Bin Dương nhé. Anh muốn là mình nói cái vụ lệch tồn trước vì là cái này là cái nóng nhất, hôm qua bên kinh doanh họ gọi anh ba lần rồi. Chị Hằng nói qua tình hình ở kho đi chị.

@S1: À ừ thì là bên chị thì thế này. Từ hôm thứ hai tuần trước đến giờ là bên chị phát hiện là cái số tồn trên hệ thống với cái số thực tế ngoài kệ nó bị lệch. Không phải là lệch hết đâu, mà là chị cho mấy bạn đi đếm thử mấy dãy A với dãy C thì là khoảng, chị ước là khoảng ba phần trăm cái mã hàng là bị lệch. Có mã thì hệ thống ghi là có hai mươi thùng mà ngoài kệ có mười, có mã thì ngược lại. Cái nguy hiểm là bên bán hàng họ nhìn cái tồn trên hệ thống họ chốt đơn cho khách, xong bên chị ra lấy thì không có hàng. Tuần vừa rồi là có mười bảy đơn bị như vậy rồi, phải gọi xin lỗi khách, có một khách lớn là bên chuỗi siêu thị họ phàn nàn ghê lắm. Rồi mấy bạn nhân viên kho thì bắt đầu là không tin cái hệ thống nữa, lại quay ra ghi sổ tay, cái này chị thấy là rất là nguy hiểm vì mình bỏ bao nhiêu công ra để chuyển sang hệ thống mới.

@S0: Toàn em đã tìm ra nguyên nhân chưa?

@S2: Dạ rồi anh, em với anh Khoa ngồi soi log cả ngày hôm qua. Thì nguyên nhân là như này anh. Cái WMS của mình nó đồng bộ hai chiều với cái ê rờ pê, chiều từ WMS sang ê rờ pê là cái phiếu xuất nhập, còn chiều từ ê rờ pê về WMS là cái đơn hàng với cái điều chỉnh tồn do kế toán làm. Cái kho Bin Dương thì cái mạng wifi ở khu dãy C nó rất là chập chờn, các máy quét cầm tay nó mất kết nối liên tục. Khi mà mất kết nối thì cái máy quét nó lưu tạm giao dịch ở trong máy, có mạng lại thì nó gửi lại. Nhưng mà có trường hợp là cái giao dịch đã lên server rồi nhưng mà cái phản hồi về máy thì bị mất, thế là máy nó tưởng là chưa gửi, nó gửi lại lần nữa. Thế là một lần xuất hàng bị ghi thành hai lần. Em đếm trong log thì có khoảng hai trăm bốn mươi giao dịch bị trùng như vậy trong hai tuần.

@S3: Với lại anh Việt ơi còn một cái nữa là cái chiều ngược lại. Bên kế toán họ vẫn đang làm cái điều chỉnh tồn ở trên ê rờ pê theo thói quen cũ, tức là cuối ngày họ nhìn cái phiếu giấy họ điều chỉnh. Mà cái điều chỉnh đó nó lại đồng bộ về WMS, trong khi WMS đã ghi nhận cái giao dịch đó từ máy quét rồi. Thế là lại bị cộng hai lần theo kiểu khác. Cho nên nó mới lệch cả hai chiều, có mã thừa có mã thiếu.

@S0: Hừm. Thế giờ xử lý thế nào? Toàn đề xuất đi.

@S2 #k_toan: Dạ em đề xuất là ba việc anh. Một là cái máy quét thì em phải thêm cái khóa chống trùng, tức là mỗi giao dịch nó sinh ra một cái mã duy nhất ngay trên máy, server nhận được mã nào rồi thì bỏ qua, không ghi lần hai, cái này gọi là cái ai đem pô ten sì ấy anh. Cái này em làm khoảng ba ngày. Hai là trong thời gian chờ thì mình tạm tắt cái chiều đồng bộ từ ê rờ pê về WMS với các loại điều chỉnh tồn, chỉ giữ đơn hàng thôi, để kế toán không làm lệch thêm. Ba là sau khi sửa xong thì phải kiểm kê lại toàn bộ kho một lần để đưa số về đúng, chứ giờ sửa code thì số cũ nó vẫn sai.

@S1: Kiểm kê toàn kho thì bên chị phải dừng xuất nhập ít nhất là một ngày đấy, kho mình hơn bốn nghìn vị trí kệ. Mà tuần này là cao điểm cuối tháng.

@S0 #d_tamdung: Thế này. Anh chốt là tạm dừng cái đồng bộ điều chỉnh tồn từ ê rờ pê về WMS ngay từ chiều nay, chỉ giữ đồng bộ đơn hàng. Cái khóa chống trùng thì làm luôn. Còn kiểm kê toàn kho thì không làm tuần này, dời sang chủ nhật tuần sau, làm ngày chủ nhật để không ảnh hưởng xuất hàng. Chị Hằng thu xếp người giúp anh nhé.

@S1: Ừ chủ nhật thì được, chị sẽ xếp ca, nhưng mà phải có tiền làm thêm giờ cho anh em đấy nhé.

@S0: Được, cái đó anh trình giám đốc. À còn cái wifi dãy C thì sao, cái đó mới là gốc mà.

@S3: Dạ cái wifi thì em hỏi bên hạ tầng rồi, họ bảo là phải lắp thêm hai cái access point ở cuối dãy C, nhưng mà họ đang báo giá, chưa biết bao giờ lắp. Cái này em nghĩ là cần có người đôn đốc chứ không là để đấy lâu lắm.

@S0 #n_wifi: Ừ cái wifi thì đúng là phải có ai theo dõi, để anh xem sau. Thôi mình sang phần tích hợp vận tải.

## TOPIC | Tích hợp WMS với hệ thống vận tải và các đối tác giao hàng | Khoa báo cáo tích hợp API với hệ thống TMS nội bộ đã xong nhưng tích hợp với ba đối tác giao hàng mới xong một; đối tác thứ hai đổi phiên bản API, đối tác thứ ba chỉ nhận file Excel; thống nhất ưu tiên đối tác chiếm 60% sản lượng và tạm dùng xuất file cho đối tác nhỏ.

@S0: Khoa nói phần tích hợp đi em.

@S3 #k_khoa: Dạ. Phần tích hợp thì có hai mảng anh. Mảng thứ nhất là WMS với cái TMS, cái hệ thống điều xe nội bộ của mình, cái này thì xong rồi anh, khi mà kho đóng gói xong một đơn thì WMS nó đẩy sang TMS cái thông tin kiện hàng, cân nặng, kích thước, TMS nó tự ghép chuyến. Chạy hai tuần nay ổn, chưa thấy lỗi gì lớn. Mảng thứ hai là với các bên giao hàng bên ngoài, mình đang làm với ba bên. Bên thứ nhất là bên Giao Nhanh thì xong rồi, đơn nào giao ngoại tỉnh thì WMS tự tạo vận đơn bên họ, in tem luôn. Bên thứ hai là bên Tốc Hành, thì hôm tuần trước họ đổi sang API phiên bản ba mà không báo trước, cái phiên bản hai mình đang dùng thì họ tắt vào cuối tháng này, nên là em phải viết lại gần như toàn bộ phần kết nối. Bên thứ ba là một công ty nhỏ ở miền Tây, họ không có API gì cả, họ chỉ nhận file Excel qua email thôi.

@S0: Thế sản lượng mỗi bên bao nhiêu? Anh nhớ là Tốc Hành là bên lớn nhất đúng không.

@S1: Đúng rồi anh, Tốc Hành là chiếm khoảng sáu mươi phần trăm đơn ngoại tỉnh của kho chị, Giao Nhanh khoảng ba mươi, còn cái bên miền Tây thì chỉ khoảng mười phần trăm, chủ yếu là đi các tỉnh đồng bằng.

@S3: Thế thì em nghĩ là phải ưu tiên Tốc Hành trước anh. Cuối tháng này họ tắt phiên bản hai là mình mất sáu mươi phần trăm đơn không tạo được vận đơn tự động, mấy bạn kho lại phải lên trang web của họ gõ tay từng đơn. Em ước viết lại mất khoảng tám ngày làm việc, tức là phải bắt đầu ngay thì mới kịp.

@S2: Anh Khoa ơi, cái phiên bản ba của Tốc Hành em có đọc qua tài liệu, nó có cái webhook báo trạng thái giao hàng, cái này hay đấy, mình không phải gọi hỏi trạng thái liên tục như bây giờ nữa. Nhưng mà nó yêu cầu mình phải có cái địa chỉ công khai có https để họ gọi về, mà server WMS của mình đang nằm trong mạng nội bộ.

@S3: Ừ đúng, cái đó thì phải nhờ bên hạ tầng mở một cái cổng qua cái reverse proxy. Hay là giai đoạn này mình chưa dùng webhook, vẫn gọi hỏi trạng thái mỗi mười lăm phút như cũ, cho nhanh.

@S0 #d_tochanh: Ừ, anh chốt thế này. Ưu tiên số một là chuyển kết nối Tốc Hành sang phiên bản ba, phải xong trước ngày hai mươi tám để kịp trước khi họ tắt bản cũ. Giai đoạn này chưa làm webhook, vẫn gọi hỏi trạng thái định kỳ, webhook để sau. Còn cái bên miền Tây thì không làm API, WMS chỉ cần có nút xuất file Excel đúng mẫu của họ, bạn kho gửi email thủ công, mười phần trăm thì chấp nhận được.

@S1: Cái mẫu Excel của bên miền Tây thì chị có, chị gửi cho Khoa.

@S3: Dạ vâng chị gửi em. Anh Việt, thế còn cái việc xuất file Excel đấy thì ai làm ạ, vì em thì em dồn hết cho Tốc Hành rồi.

@S0 #a_excel: Cái nút xuất file đấy thì đơn giản, để Toàn làm, sau khi xong cái khóa chống trùng. Toàn ok không?

@S2 #a_excel_ok: Dạ ok anh, cái này em làm một ngày là xong.

## TOPIC | Đào tạo nhân viên kho và chuẩn hóa quy trình kiểm kê trên WMS | Dung báo cáo mới đào tạo được khoảng 70% nhân viên kho, ca đêm chưa được đào tạo và nhiều người vẫn ghi sổ tay; thống nhất đào tạo bổ sung cho ca đêm, ban hành quy trình kiểm kê chu kỳ theo nhóm hàng ABC thay cho kiểm kê toàn kho hằng tháng.

@S0: Rồi, sang phần đào tạo với quy trình. Dung ơi em nói đi.

@S4 #k_dung: Dạ vâng. Em báo cáo là về đào tạo thì kho Bin Dương có tổng cộng tám mươi hai nhân viên, chia ba ca. Đến giờ em đã đào tạo được năm mươi tám bạn, tức là khoảng bảy mươi phần trăm. Hai ca ngày thì gần như đủ rồi, nhưng mà ca đêm thì mới đào tạo được có năm bạn, vì là giờ đào tạo của em là giờ hành chính, ca đêm các bạn đi làm từ mười giờ tối thì ban ngày các bạn ngủ, không ai lên học. Mà cái lỗi thao tác nhiều nhất lại là ở ca đêm, em xem log thì là quét nhầm vị trí kệ, quét mã thùng thay vì quét mã sản phẩm, hoặc là lấy hàng xong không bấm xác nhận.

@S1: Đúng rồi đấy anh Việt, ca đêm là ca nhập hàng nhiều nhất, xe container về toàn đêm, mà các bạn ấy thì chưa quen máy, nhiều bạn lớn tuổi, nhìn cái màn hình nhỏ không quen. Chị nghĩ cái lệch tồn cũng có một phần là từ đây chứ không phải chỉ do mạng.

@S0: Thế Dung tính đào tạo ca đêm thế nào?

@S4: Dạ em nghĩ là em phải lên kho ca đêm để đào tạo tại chỗ, kiểu là cầm tay chỉ việc luôn trong ca, chứ gọi lên phòng học thì không được. Em tính là làm ba đêm, mỗi đêm khoảng mười bạn. Nhưng mà em cũng cần có chị Hằng cử một bạn tổ trưởng ca đêm làm cùng, để sau này bạn ấy kèm lại các bạn mới.

@S1: Ừ được, chị cử bạn Thắng tổ trưởng ca đêm, bạn ấy nhanh nhẹn, dùng máy quen rồi.

@S4: Dạ em cảm ơn chị. Còn một việc nữa em muốn xin ý kiến anh Việt là về quy trình kiểm kê. Hiện nay theo quy trình cũ thì kho làm kiểm kê toàn bộ vào cuối mỗi tháng, dừng kho cả ngày. Nhưng mà WMS thì nó hỗ trợ kiểm kê chu kỳ, tức là mỗi ngày đếm một ít, chia hàng thành nhóm A B C theo giá trị với tần suất xuất. Nhóm A là hàng giá trị cao, xuất nhiều thì đếm hằng tuần, nhóm B thì hằng tháng, nhóm C thì mỗi quý. Làm như vậy thì không phải dừng kho, mà sai lệch cũng phát hiện sớm hơn.

@S1: Chị thì chị ủng hộ cái này, vì cái dừng kho cuối tháng là cực kỳ khổ, mà khách hàng họ cũng không thích. Nhưng mà cái việc phân nhóm A B C thì ai làm, chị không có số liệu giá trị hàng.

@S2: Cái đó thì em chạy được từ dữ liệu ê rờ pê chị ạ, có giá vốn với số lần xuất trong sáu tháng rồi, em chạy ra danh sách phân nhóm.

@S0 #d_kiemke: Được. Anh chốt là chuyển sang kiểm kê chu kỳ theo nhóm A B C, bỏ kiểm kê toàn kho hằng tháng, áp dụng từ tháng sau, sau khi mình đã làm cái lần kiểm kê toàn kho chủ nhật tuần sau để đưa số về đúng. Dung soạn cái quy trình kiểm kê chu kỳ, trình anh ký ban hành.

@S4 #a_quytrinh: Dạ vâng, em soạn xong trong tuần này gửi anh.

@S0 #a_dem: Còn đào tạo ca đêm thì em làm luôn ba đêm đó trong tuần sau nhé, cùng với bạn Thắng. Toàn thì chạy cái danh sách phân nhóm A B C gửi cho Dung với chị Hằng.

@S2 #a_abc: Dạ vâng anh, em chạy xong trước thứ tư.

## TOPIC | Kế hoạch mở rộng triển khai WMS sang kho Long An | Thảo luận thời điểm go-live kho Long An; ban đầu định go-live 1/12 nhưng sau khi cân nhắc các lỗi còn tồn ở Bình Dương, thống nhất lùi sang 15/1 và chỉ go-live khi tỷ lệ lệch tồn Bình Dương dưới 0.5% trong hai tuần liên tiếp.

@S0: Rồi, phần cuối là cái Long An. Theo kế hoạch ban đầu thì là mình go live kho Long An vào ngày mùng một tháng mười hai. Giám đốc thì vẫn muốn giữ ngày đó. Mọi người thấy sao?

@S3: Về kỹ thuật thì kho Long An nó dùng chung cái server WMS với Bin Dương, chỉ cần khai báo thêm kho, vị trí kệ, người dùng thôi, cái phần đấy thì nhanh. Cái lo nhất là tích hợp, vì Long An có thêm một đối tác giao hàng nữa là bên Hỏa Tốc Miền Nam mà mình chưa làm bao giờ.

@S1: Chị thì chị nói thật là chị hơi lo. Bin Dương hai tuần mà còn đang lệch tồn thế này, giờ mà Long An lại go live ngày mùng một thì cả đội dự án sẽ bị chia đôi, Bin Dương không ai lo. Mà kho Long An là kho hàng lạnh, hàng thực phẩm, có hạn sử dụng, cái phần quản lý lô với hạn dùng mình chưa test kỹ.

@S0 #n_1_12: Ừ, thế này, anh vẫn nghiêng về giữ ngày mùng một vì là đã báo cáo lên rồi, nhưng mà phải có điều kiện.

@S4: Anh Việt, ngày mùng một thì em không kịp đào tạo cho Long An đâu ạ, Long An có sáu mươi người, mà em đang còn nợ ca đêm Bin Dương.

@S2: Với lại phần quản lý hạn dùng thì em mới code xong phần xuất theo hạn dùng trước, cái phần cảnh báo hàng sắp hết hạn thì chưa làm, mà kho lạnh thì cái này là bắt buộc anh ạ.

@S0 #d_longan: Ừ. Vậy thì thôi, anh đổi lại. Không go live Long An ngày mùng một nữa, lùi sang ngày mười lăm tháng một năm sau. Và có điều kiện là chỉ go live khi tỷ lệ lệch tồn ở Bin Dương dưới không phẩy năm phần trăm trong hai tuần liên tiếp. Anh sẽ tự báo cáo giám đốc về việc lùi lịch này.

@S1: Ừ như thế thì chị yên tâm hơn.

@S0 #a_hsd: Toàn thì làm cho xong cái phần cảnh báo hàng sắp hết hạn trước khi go live Long An. Còn cái đối tác Hỏa Tốc Miền Nam thì Khoa làm sau khi xong Tốc Hành, tháng mười hai làm.

@S3 #a_hoatoc: Dạ vâng anh.

@S0 #a_baocao: Rồi, còn anh thì anh sẽ làm việc với giám đốc về lùi lịch Long An với cái tiền làm thêm giờ chủ nhật cho kho, trong tuần này. Thôi hôm nay đến đây, cảm ơn mọi người.

```json gold
{
  "assignments": [
    {"actor": "Toàn", "actor_aliases": ["SPEAKER_02", "Toàn", "em"], "task": "Thêm khóa chống trùng giao dịch (idempotency) cho máy quét", "deadline": "khoảng 3 ngày", "turns": ["k_toan", "d_tamdung"]},
    {"actor": "Chị Hằng", "actor_aliases": ["SPEAKER_01", "chị Hằng"], "task": "Thu xếp người kiểm kê toàn kho vào chủ nhật tuần sau", "deadline": "chủ nhật tuần sau", "turns": ["d_tamdung"]},
    {"actor": "Toàn", "actor_aliases": ["SPEAKER_02", "Toàn"], "task": "Làm nút xuất file Excel theo mẫu cho đối tác giao hàng miền Tây", "deadline": "sau khi xong khóa chống trùng, 1 ngày", "turns": ["a_excel", "a_excel_ok"]},
    {"actor": "Khoa", "actor_aliases": ["SPEAKER_03", "Khoa"], "task": "Chuyển kết nối Tốc Hành sang API phiên bản 3", "deadline": "trước ngày 28", "turns": ["d_tochanh"]},
    {"actor": "Chị Hằng", "actor_aliases": ["SPEAKER_01"], "task": "Gửi mẫu Excel của đối tác miền Tây cho Khoa", "deadline": null, "turns": ["d_tochanh"]},
    {"actor": "Dung", "actor_aliases": ["SPEAKER_04", "Dung", "em"], "task": "Soạn quy trình kiểm kê chu kỳ theo nhóm ABC trình ký ban hành", "deadline": "trong tuần này", "turns": ["d_kiemke", "a_quytrinh"]},
    {"actor": "Dung", "actor_aliases": ["SPEAKER_04", "em"], "task": "Đào tạo tại chỗ ca đêm kho Bình Dương trong 3 đêm cùng tổ trưởng Thắng", "deadline": "tuần sau", "turns": ["a_dem"]},
    {"actor": "Toàn", "actor_aliases": ["SPEAKER_02"], "task": "Chạy danh sách phân nhóm hàng ABC gửi Dung và chị Hằng", "deadline": "trước thứ Tư", "turns": ["a_dem", "a_abc"]},
    {"actor": "Toàn", "actor_aliases": ["SPEAKER_02"], "task": "Hoàn thành chức năng cảnh báo hàng sắp hết hạn trước go-live Long An", "deadline": "trước 15/1", "turns": ["a_hsd"]},
    {"actor": "Khoa", "actor_aliases": ["SPEAKER_03"], "task": "Tích hợp đối tác Hỏa Tốc Miền Nam sau khi xong Tốc Hành", "deadline": "tháng 12", "turns": ["a_hsd", "a_hoatoc"]},
    {"actor": "Anh Việt", "actor_aliases": ["SPEAKER_00", "anh"], "task": "Làm việc với giám đốc về lùi lịch Long An và tiền làm thêm giờ chủ nhật", "deadline": "trong tuần này", "turns": ["a_baocao"]}
  ],
  "decisions": [
    {"text": "Tạm dừng đồng bộ điều chỉnh tồn từ ERP về WMS từ chiều nay, chỉ giữ đồng bộ đơn hàng; làm khóa chống trùng; kiểm kê toàn kho dời sang chủ nhật tuần sau", "turns": ["d_tamdung"]},
    {"text": "Ưu tiên chuyển kết nối Tốc Hành sang API v3 trước ngày 28, chưa làm webhook; đối tác miền Tây dùng xuất file Excel gửi email thủ công", "turns": ["d_tochanh"]},
    {"text": "Chuyển sang kiểm kê chu kỳ theo nhóm ABC, bỏ kiểm kê toàn kho hằng tháng, áp dụng từ tháng sau", "turns": ["d_kiemke"]},
    {"text": "Lùi go-live kho Long An sang 15/1, chỉ go-live khi lệch tồn Bình Dương dưới 0.5% trong hai tuần liên tiếp", "turns": ["d_longan"]}
  ],
  "negatives": [
    {"type": "unassigned_task", "text": "Đôn đốc bên hạ tầng lắp thêm access point wifi dãy C", "turns": ["n_wifi"]},
    {"type": "superseded_decision", "text": "Giữ ngày go-live Long An 1/12 có điều kiện", "turns": ["n_1_12"]}
  ],
  "key_points": [
    {"speaker": "SPEAKER_02", "point": "Nguyên nhân lệch tồn: máy quét gửi lại giao dịch khi mất phản hồi do wifi dãy C, khoảng 240 giao dịch bị trùng", "turns": ["k_toan"]},
    {"speaker": "SPEAKER_03", "point": "Tích hợp TMS xong; Giao Nhanh xong; Tốc Hành đổi API v3 phải viết lại; đối tác miền Tây chỉ nhận Excel", "turns": ["k_khoa"]},
    {"speaker": "SPEAKER_04", "point": "Đã đào tạo 58/82 nhân viên, ca đêm mới 5 người, lỗi thao tác tập trung ở ca đêm", "turns": ["k_dung"]}
  ]
}
```
