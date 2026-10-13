```json meta
{
  "meeting_id": "synth_024",
  "title": "Họp sprint dự án phần mềm quản lý bán hàng đa kênh chuỗi cửa hàng mẹ và bé Bông Sen",
  "meeting_type": "software_project",
  "length_bucket": "M",
  "tags": ["asr_noise", "similar_adjacent_topics"],
  "speakers": {
    "PO": "Chị Thảo (Giám đốc vận hành chuỗi Bông Sen)",
    "PM": "Anh Nghĩa (Quản lý dự án)",
    "BE": "Hiếu (Backend)",
    "FE": "Trang (Frontend)",
    "DA": "Khoa (Phân tích dữ liệu)"
  }
}
```

## TOPIC | Xây dựng chức năng đồng bộ đơn hàng từ các sàn thương mại điện tử | Đồng bộ đơn từ Shopee, Lazada, TikTok Shop đã chạy, trễ trung bình 4 phút; đơn TikTok Shop bị trùng khi sàn gửi lại thông báo; thống nhất chống trùng theo mã đơn sàn và chuyển sang nhận webhook thay vì quét định kỳ 5 phút.

@PM: ờ alo alo mọi người nghe rõ không ạ, ok rồi. thì là hôm nay mình họp sprint mười hai nha, có năm cái mục, đồng bộ đơn hàng từ sàn, đồng bộ tồn kho lên sàn, chương trình khuyến mãi, báo cáo doanh thu cửa hàng, với cả báo cáo hiệu quả khuyến mãi. hiếu nói cái đồng bộ đơn trước đi em.

@BE #k_hieu1: dạ vâng. thì cái đồng bộ đơn hàng từ sàn thì hiện tại mình đã kết nối được ba sàn là sô pi, la da da với tích tốc sóp. cơ chế hiện tại là cứ năm phút thì hệ thống gọi a pi của sàn một lần để lấy đơn mới về, xong tạo đơn trong hệ thống, trừ tồn kho tạm của cái kho tổng, rồi đẩy sang bộ phận đóng gói. tuần vừa rồi đồng bộ khoảng mười một nghìn bốn trăm đơn, độ trễ trung bình từ lúc khách đặt trên sàn đến lúc đơn hiện trong hệ thống là khoảng bốn phút. vấn đề là bên tích tốc sóp thì có khoảng hai phần trăm đơn bị trùng, tức là một đơn tạo ra hai lần, do sàn đấy hay gửi lại cái trạng thái đơn, mà mình đang so trùng theo cái mã nội bộ chứ không phải mã đơn của sàn. có hai lần kho đóng gói đóng hai lần một đơn, gửi đi hai kiện, mất tiền ship với hàng.

@PO: ừ cái này chị biết, tuần trước có một khách ở đà nẵng nhận hai hộp sữa bột, bên chị phải gọi xin lại. thế em sửa thế nào?

@BE: dạ em đề xuất là thứ nhất chống trùng theo cái mã đơn của sàn cộng với mã sàn, tức là cặp đấy là duy nhất, đơn về lần hai thì chỉ cập nhật trạng thái chứ không tạo mới. thứ hai là chuyển sang nhận uép húc, tức là sàn chủ động bắn thông báo khi có đơn, thay vì cứ năm phút mình hỏi một lần, như thế độ trễ còn dưới một phút. sô pi với tích tốc thì có hỗ trợ uép húc, còn la da da thì em đang kiểm tra lại tài liệu.

@FE: em bổ sung là trên màn hình danh sách đơn thì em sẽ thêm cột nguồn đơn với mã đơn sàn, để bộ phận chăm sóc khách tra cứu nhanh, chứ hiện tại phải mở từng đơn mới thấy.

@PO: còn đợt sale mười một mười một thì sao, năm ngoái ngày đấy về một ngày hơn tám nghìn đơn, hệ thống cũ treo luôn.

@BE: dạ với uép húc thì cao điểm mình nhận được khoảng hai trăm đơn một phút, em đã thử tải giả lập năm trăm đơn một phút thì vẫn chạy, có hàng đợi ở giữa nên không sợ mất đơn.

@PM #d_dongdon: rồi vậy chốt mục này: chống trùng theo mã đơn sàn cộng mã sàn, chuyển sang nhận uép húc cho sô pi và tích tốc, la da da thì tạm giữ quét định kỳ nhưng rút xuống hai phút. phải xong trước ngày năm tháng mười một để kịp chạy thử trước mười một mười một.

@BE #a_chongtrung: dạ em làm, chống trùng em đẩy lên trong tuần này luôn, uép húc thì cuối tuần sau.

@FE #a_cotnguon: phần cột nguồn đơn thì em làm luôn trong sprint này ạ.

## TOPIC | Xây dựng chức năng đồng bộ tồn kho lên các sàn thương mại điện tử | Tồn kho trên sàn lệch với kho thực khiến bán vượt 37 đơn trong tuần; thống nhất đẩy tồn kho theo sự kiện khi có biến động, giữ lại tồn kho an toàn 5% cho mỗi sàn và đồng bộ toàn bộ lúc 2 giờ sáng.

@PM: tiếp theo là cái đồng bộ tồn kho, nghe thì giống cái đồng bộ đơn nhưng mà là chiều ngược lại, mình đẩy tồn kho lên sàn. hiếu nói tiếp nhé.

@BE #k_hieu2: dạ. thì đồng bộ tồn kho hiện tại là mỗi ba mươi phút hệ thống đẩy số tồn của tất cả các mã hàng lên ba sàn, khoảng bốn nghìn hai trăm mã. vấn đề là trong ba mươi phút đấy thì cửa hàng vẫn bán, sàn khác vẫn bán, nên số trên sàn bị lệch với kho thực. tuần vừa rồi có ba mươi bảy đơn bị bán vượt, tức là khách đặt rồi mà kho hết hàng, phải hủy đơn, mà sàn thì phạt điểm uy tín shop khi hủy đơn do người bán, sô pi đã cảnh báo shop mình một lần rồi.

@PO #k_thao2: cái này nghiêm trọng hơn cái trùng đơn đấy. shop mà bị sô pi hạ điểm thì mất huy hiệu shop yêu thích, lượt hiển thị giảm hẳn. mà bỉm, sữa là hàng bán chạy, hết hàng nhanh lắm, nhất là mấy mã sữa nhập khẩu.

@BE: dạ em đề xuất đổi sang đẩy theo sự kiện, tức là mã hàng nào có biến động, bán ở cửa hàng, bán trên sàn, nhập kho, trả hàng, thì đẩy ngay mã đấy lên ba sàn, không chờ ba mươi phút. còn mỗi đêm hai giờ sáng thì đồng bộ toàn bộ một lần để sửa các sai lệch nếu có.

@DA: em có xem số liệu thì ba mươi bảy đơn bán vượt thì hai mươi chín đơn là các mã có tồn dưới mười, tức là mã sắp hết. em đề xuất là giữ lại một phần tồn kho an toàn, ví dụ chỉ đẩy lên sàn chín mươi lăm phần trăm số tồn thực, hoặc mã nào còn dưới năm cái thì mỗi sàn chỉ hiện một hai cái thôi.

@PO: giữ năm phần trăm thì được, nhưng mà phần giữ lại đấy để cửa hàng bán chứ đừng để chết hàng.

@FE: trên màn hình quản lý tồn kho em làm thêm cảnh báo lệch tồn, mã nào số trên sàn khác số trong kho quá hai cái thì tô đỏ cho bộ phận kho kiểm tra.

@PM #d_dongton: ok chốt: đẩy tồn kho theo sự kiện khi có biến động, đồng bộ toàn bộ lúc hai giờ sáng hằng đêm, giữ tồn an toàn năm phần trăm cho mỗi sàn, có màn hình cảnh báo lệch tồn.

@BE #a_dongton: em làm cái đẩy theo sự kiện, cái này phức tạp hơn, em cần hai tuần, xong trước ngày tám.

@DA #a_ngaongan: em lập danh sách các mã sắp hết hay bị bán vượt để chị thảo xem lại định mức nhập hàng, thứ năm em gửi.

## TOPIC | Xây dựng chức năng quản lý chương trình khuyến mãi đa kênh | Chức năng tạo khuyến mãi đã hỗ trợ giảm giá, mua X tặng Y, combo; vướng chồng khuyến mãi giữa voucher sàn và khuyến mãi cửa hàng; thống nhất quy tắc không cộng dồn mặc định, cho phép cấu hình ưu tiên; đề xuất tích điểm thành viên dùng chung trên sàn bị gạt.

@PM: mục ba là khuyến mãi, trang trình bày nhé.

@FE #k_trang1: dạ. thì chức năng tạo chương trình khuyến mãi bây giờ đã có ba loại, là giảm giá theo phần trăm hoặc số tiền, mua x tặng y, ví dụ mua hai bịch bỉm tặng một gói khăn ướt, và combo giá cố định. người quản lý chọn kênh áp dụng là cửa hàng, quét mã ở máy pốt, hay trên sàn, chọn thời gian, chọn cửa hàng. nhưng vấn đề là chồng khuyến mãi, ví dụ tuần trước có chương trình giảm mười phần trăm toàn bộ sữa ở cửa hàng, mà khách cầm thêm thẻ thành viên hạng vàng giảm năm phần trăm, rồi máy pốt lại cộng thêm combo, có hóa đơn giảm gần ba mươi phần trăm, dưới giá vốn.

@PO: đúng rồi, mấy cửa hàng quận bảy báo là nhân viên cũng không biết cái nào được cộng cái nào không. chị muốn mặc định là không cộng dồn, khách chỉ được hưởng một khuyến mãi có lợi nhất, trừ thẻ thành viên thì được cộng thêm.

@BE: về kỹ thuật thì em làm được cái bảng quy tắc ưu tiên, mỗi chương trình có một mức ưu tiên và một cờ là có được cộng dồn hay không. máy pốt tính thử tất cả các tổ hợp hợp lệ rồi chọn cái có lợi nhất cho khách. thêm một chặn cứng là tổng giảm không vượt quá giá vốn cộng năm phần trăm.

@FE #n_tichdiem: em có ý là hay mình làm tích điểm thành viên dùng chung, khách mua trên sô pi cũng được cộng điểm vào thẻ thành viên của cửa hàng, như thế khách gắn bó hơn.

@PO #n_tichdiem2: ý thì hay nhưng mà sàn không cho mình lấy số điện thoại khách đâu em, dữ liệu khách trên sàn bị che hết, chính sách của sàn không cho kéo khách ra ngoài. mà làm sai là bị khóa shop. thôi cái này để sau tính, giờ chưa làm.

@PM #d_khuyenmai: chốt: mặc định không cộng dồn khuyến mãi, chỉ áp dụng chương trình có lợi nhất, riêng ưu đãi thẻ thành viên được cộng thêm; có bảng cấu hình ưu tiên và cờ cộng dồn; chặn cứng tổng giảm không thấp hơn giá vốn cộng năm phần trăm.

@BE #a_quytac: phần tính khuyến mãi trên máy pốt em làm.

@FE #a_cauhinh: còn màn hình cấu hình ưu tiên với cờ cộng dồn thì em làm ạ, xong cùng sprint với anh hiếu.

## TOPIC | Xây dựng chức năng báo cáo doanh thu theo cửa hàng | Báo cáo doanh thu theo cửa hàng chạy chậm 40 giây và lệch với kế toán do tính đơn trả hàng khác nhau; thống nhất tách kho dữ liệu báo cáo riêng, doanh thu tính theo ngày giao thành công và trừ hàng trả theo ngày trả.

@PM: mục bốn là báo cáo doanh thu theo cửa hàng, khoa nói nhé.

@DA #k_khoa1: dạ. báo cáo doanh thu theo cửa hàng thì hiện có doanh thu theo ngày, theo tuần, theo tháng cho hai mươi ba cửa hàng và ba kênh sàn, có so sánh cùng kỳ, top mười mã hàng bán chạy theo cửa hàng. vấn đề thứ nhất là chậm, báo cáo tháng chạy mất khoảng bốn mươi giây vì đang truy vấn thẳng vào cơ sở dữ liệu bán hàng, mà giờ cao điểm truy vấn báo cáo còn làm chậm cả máy pốt ở cửa hàng. vấn đề thứ hai là số liệu lệch với bên kế toán, tháng chín báo cáo của mình ra doanh thu cao hơn sổ kế toán khoảng một phẩy hai tỷ. em kiểm tra thì do cách tính khác nhau, mình tính doanh thu theo ngày đặt đơn, còn kế toán ghi nhận theo ngày giao hàng thành công, và hàng trả lại thì mình chưa trừ, còn kế toán trừ theo ngày khách trả.

@PO #k_thao4: cái lệch số này làm chị khổ nhất, họp với ban giám đốc mà mỗi bên một số. phải thống nhất một cách tính, theo kế toán là chuẩn, vì đấy là số đi báo cáo thuế.

@BE: về hiệu năng thì em đề xuất tách một kho dữ liệu báo cáo riêng, mỗi đêm đổ dữ liệu từ cơ sở dữ liệu bán hàng sang, trong ngày thì cập nhật mười lăm phút một lần, báo cáo chỉ truy vấn kho này, không đụng vào cơ sở dữ liệu bán hàng nữa.

@DA: như thế số trong ngày thì trễ mười lăm phút, chị thảo có chấp nhận được không ạ?

@PO: trễ mười lăm phút thì được, chị chỉ cần số cuối ngày chính xác.

@PM #d_doanhthu: chốt: doanh thu trên báo cáo tính theo ngày giao hàng thành công, hàng trả lại trừ theo ngày khách trả, khớp với cách ghi nhận của kế toán; tách kho dữ liệu báo cáo riêng, cập nhật mười lăm phút một lần.

@DA #a_doisoat: em làm lại công thức và đối soát với kế toán số liệu tháng chín, tháng mười, phải khớp thì mới đưa lên, thứ sáu tuần sau em báo cáo.

@BE #a_khodl: tách kho dữ liệu thì em làm sau khi xong đồng bộ tồn kho, khoảng giữa tháng.

## TOPIC | Xây dựng chức năng báo cáo hiệu quả chương trình khuyến mãi | Báo cáo hiệu quả khuyến mãi mới có doanh thu trong thời gian chương trình; thống nhất bổ sung so sánh với giai đoạn trước, chi phí khuyến mãi và lợi nhuận gộp theo từng chương trình; đề xuất dùng mô hình học máy dự báo hiệu quả khuyến mãi để sau.

@PM: mục cuối là báo cáo hiệu quả khuyến mãi, cái này gần giống báo cáo doanh thu nhưng mà nhìn theo chương trình. khoa nói tiếp.

@DA #k_khoa2: dạ. hiện tại báo cáo hiệu quả khuyến mãi mới chỉ có doanh thu và số đơn trong thời gian chạy chương trình, chưa có so sánh, nên nhìn vào thì chương trình nào cũng thấy tăng. em đề xuất bổ sung ba chỉ số. một là doanh thu tăng thêm so với trung bình bốn tuần trước chương trình, cùng nhóm hàng cùng cửa hàng. hai là chi phí khuyến mãi, tức là tổng tiền giảm giá cộng giá vốn hàng tặng. ba là lợi nhuận gộp sau khuyến mãi, để biết chương trình nào thật sự có lãi.

@PO #k_thao5: đúng cái chị cần. tháng trước chương trình mua hai tặng một bỉm, doanh thu tăng bốn mươi phần trăm nhưng chị nghi là lỗ vì hàng tặng toàn là gói to. thêm một cái nữa là chị muốn xem khách mới, tức là bao nhiêu khách lần đầu mua trong chương trình.

@DA: dạ khách mới thì chỉ tính được ở cửa hàng với khách có thẻ thành viên, trên sàn thì không có thông tin khách nên không tính được.

@FE: phần giao diện em làm dạng bảng xếp hạng chương trình theo lợi nhuận gộp, bấm vào thì ra chi tiết theo cửa hàng.

@DA #n_ml: em có thêm ý là sau khi có dữ liệu đủ một năm thì mình có thể làm mô hình học máy dự báo trước hiệu quả của một chương trình, kiểu nhập thông số vào thì ra dự báo doanh thu với lãi lỗ.

@PM #n_ml2: cái đấy để sau nha, giờ dữ liệu chưa đủ, mà sprint đang kín rồi. ghi lại làm ý tưởng giai đoạn hai.

@PM #d_hieuqua: chốt mục này: bổ sung doanh thu tăng thêm so với bốn tuần trước, chi phí khuyến mãi gồm giảm giá và giá vốn hàng tặng, lợi nhuận gộp sau khuyến mãi, số khách mới ở kênh cửa hàng; giao diện bảng xếp hạng theo lợi nhuận gộp.

@DA #a_chiso: em làm định nghĩa chỉ số với câu truy vấn, gửi chị thảo duyệt định nghĩa trước rồi mới làm.

@FE #a_bxh: em làm giao diện sau khi anh khoa chốt định nghĩa.

@PM: ok, thế thôi nha mọi người. chị thảo còn gì không ạ? không, ok cảm ơn cả nhà.

```json gold
{
  "assignments": [
    {"actor": "Hiếu (Backend)", "actor_aliases": ["hiếu", "em"], "task": "Chống trùng đơn theo mã đơn sàn và chuyển sang nhận webhook cho Shopee, TikTok Shop", "deadline": "chống trùng trong tuần này, webhook cuối tuần sau", "turns": ["a_chongtrung"]},
    {"actor": "Trang (Frontend)", "actor_aliases": ["em"], "task": "Thêm cột nguồn đơn và mã đơn sàn trên danh sách đơn", "deadline": "trong sprint này", "turns": ["a_cotnguon"]},
    {"actor": "Hiếu (Backend)", "actor_aliases": ["em"], "task": "Làm đẩy tồn kho theo sự kiện lên các sàn", "deadline": "trước ngày 8", "turns": ["a_dongton"]},
    {"actor": "Khoa (Phân tích dữ liệu)", "actor_aliases": ["em"], "task": "Lập danh sách mã hàng sắp hết, hay bị bán vượt gửi chị Thảo xem định mức nhập", "deadline": "thứ Năm", "turns": ["a_ngaongan"]},
    {"actor": "Hiếu (Backend)", "actor_aliases": ["em", "anh hiếu"], "task": "Làm phần tính khuyến mãi trên máy POS theo quy tắc ưu tiên", "deadline": null, "turns": ["a_quytac"]},
    {"actor": "Trang (Frontend)", "actor_aliases": ["em"], "task": "Làm màn hình cấu hình ưu tiên và cờ cộng dồn khuyến mãi", "deadline": "cùng sprint", "turns": ["a_cauhinh"]},
    {"actor": "Khoa (Phân tích dữ liệu)", "actor_aliases": ["em"], "task": "Làm lại công thức doanh thu và đối soát với kế toán số liệu tháng 9, 10", "deadline": "thứ Sáu tuần sau", "turns": ["a_doisoat"]},
    {"actor": "Hiếu (Backend)", "actor_aliases": ["em"], "task": "Tách kho dữ liệu báo cáo riêng", "deadline": "khoảng giữa tháng", "turns": ["a_khodl"]},
    {"actor": "Khoa (Phân tích dữ liệu)", "actor_aliases": ["em", "anh khoa"], "task": "Làm định nghĩa chỉ số và truy vấn báo cáo hiệu quả khuyến mãi, gửi chị Thảo duyệt", "deadline": null, "turns": ["a_chiso"]},
    {"actor": "Trang (Frontend)", "actor_aliases": ["em"], "task": "Làm giao diện bảng xếp hạng chương trình khuyến mãi", "deadline": "sau khi chốt định nghĩa", "turns": ["a_bxh"]}
  ],
  "decisions": [
    {"text": "Chống trùng đơn theo mã đơn sàn + mã sàn; webhook cho Shopee và TikTok Shop; Lazada quét 2 phút; xong trước 5/11", "turns": ["d_dongdon"]},
    {"text": "Đẩy tồn kho theo sự kiện, đồng bộ toàn bộ lúc 2 giờ sáng, giữ tồn an toàn 5%, có cảnh báo lệch tồn", "turns": ["d_dongton"]},
    {"text": "Mặc định không cộng dồn khuyến mãi (trừ thẻ thành viên); có cấu hình ưu tiên; tổng giảm không thấp hơn giá vốn + 5%", "turns": ["d_khuyenmai"]},
    {"text": "Doanh thu tính theo ngày giao thành công, hàng trả trừ theo ngày trả (khớp kế toán); tách kho dữ liệu báo cáo cập nhật 15 phút", "turns": ["d_doanhthu"]},
    {"text": "Báo cáo hiệu quả khuyến mãi bổ sung doanh thu tăng thêm, chi phí khuyến mãi, lợi nhuận gộp, khách mới kênh cửa hàng", "turns": ["d_hieuqua"]}
  ],
  "negatives": [
    {"type": "hedged_proposal", "text": "Tích điểm thành viên dùng chung cho đơn trên sàn", "turns": ["n_tichdiem", "n_tichdiem2"]},
    {"type": "hedged_proposal", "text": "Mô hình học máy dự báo hiệu quả khuyến mãi", "turns": ["n_ml", "n_ml2"]}
  ],
  "key_points": [
    {"speaker": "Hiếu (Backend)", "point": "Đồng bộ 11.400 đơn/tuần, trễ 4 phút; 2% đơn TikTok Shop bị trùng do so trùng theo mã nội bộ", "turns": ["k_hieu1"]},
    {"speaker": "Hiếu (Backend)", "point": "Đẩy tồn kho 30 phút/lần gây 37 đơn bán vượt, Shopee đã cảnh báo", "turns": ["k_hieu2"]},
    {"speaker": "Chị Thảo (Giám đốc vận hành chuỗi Bông Sen)", "point": "Bán vượt làm hạ điểm uy tín shop, nghiêm trọng hơn trùng đơn", "turns": ["k_thao2"]},
    {"speaker": "Trang (Frontend)", "point": "Chồng khuyến mãi khiến có hóa đơn giảm gần 30%, dưới giá vốn", "turns": ["k_trang1"]},
    {"speaker": "Khoa (Phân tích dữ liệu)", "point": "Báo cáo doanh thu chạy 40 giây, lệch kế toán 1,2 tỷ do khác cách tính ngày và hàng trả", "turns": ["k_khoa1"]},
    {"speaker": "Chị Thảo (Giám đốc vận hành chuỗi Bông Sen)", "point": "Phải thống nhất theo cách tính của kế toán", "turns": ["k_thao4"]},
    {"speaker": "Khoa (Phân tích dữ liệu)", "point": "Báo cáo khuyến mãi cần doanh thu tăng thêm so với 4 tuần trước, chi phí khuyến mãi, lợi nhuận gộp", "turns": ["k_khoa2"]},
    {"speaker": "Chị Thảo (Giám đốc vận hành chuỗi Bông Sen)", "point": "Nghi chương trình mua 2 tặng 1 bỉm lỗ; muốn xem số khách mới", "turns": ["k_thao5"]}
  ]
}
```
