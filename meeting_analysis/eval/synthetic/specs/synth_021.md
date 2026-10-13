```json meta
{
  "meeting_id": "synth_021",
  "title": "Họp rà soát dự án ứng dụng ngân hàng số cho hệ thống Quỹ tín dụng nhân dân liên kết miền Trung",
  "meeting_type": "software_project",
  "length_bucket": "L",
  "tags": ["topic_revisit", "dense_actions_closing", "long"],
  "speakers": {
    "GD": "Ông Trí (Phó Tổng giám đốc phụ trách công nghệ)",
    "PM": "Chị Hiền (Quản lý dự án)",
    "BE": "Anh Lâm (Kiến trúc sư hệ thống)",
    "MB": "Vy (Trưởng nhóm Mobile)",
    "QA": "Anh Toản (Trưởng nhóm Kiểm thử)",
    "RR": "Chị Mỹ (Trưởng phòng Quản lý rủi ro và Tuân thủ)",
    "NV": "Anh Đông (Trưởng phòng Nghiệp vụ tín dụng)"
  },
  "revisits": {"3": 0}
}
```

## TOPIC | Xây dựng chức năng mở tài khoản thanh toán trực tuyến bằng eKYC | eKYC đối chiếu chip CCCD và sinh trắc khuôn mặt đạt tỷ lệ thành công 81%, thất bại chủ yếu do điện thoại không có NFC và người lớn tuổi; thống nhất cho phép hoàn tất tại quầy giao dịch khi eKYC thất bại, hạn mức giao dịch thấp cho tài khoản mở trực tuyến.

@GD: Chào cả nhà. Còn sáu tuần nữa là đến mốc ra mắt, hôm nay rà soát kỹ. Có tám mục: mở tài khoản eKYC, chuyển tiền nhanh, vay tiêu dùng trực tuyến, thông báo số dư và chống lừa đảo, kiểm thử hiệu năng, hồ sơ xin Ngân hàng Nhà nước, và cuối cùng là phân công trước ra mắt. Chị Hiền điều phối.

@PM: Vâng anh. Mục đầu tiên là mở tài khoản trực tuyến bằng eKYC. Vy trình bày.

@MB #k_vy1: Dạ. Luồng mở tài khoản trên ứng dụng gồm: khách nhập số điện thoại, xác thực mã OTP, đọc chip căn cước công dân qua NFC, chụp ảnh khuôn mặt có kiểm tra người thật, hệ thống so khớp khuôn mặt với ảnh trong chip và đối chiếu với cơ sở dữ liệu quốc gia về dân cư qua dịch vụ của Bộ Công an, sau đó khách ký điều khoản và có tài khoản. Chạy thử nội bộ và thử nghiệm với 1.200 khách hàng thật ở 8 quỹ tín dụng, tỷ lệ hoàn tất thành công là 81%. Trong 19% thất bại thì khoảng 9% là do điện thoại không có NFC, chủ yếu điện thoại đời cũ giá rẻ, 6% là người trên 60 tuổi thao tác chụp khuôn mặt không đạt, đưa điện thoại không đúng góc, 4% là lỗi kết nối với dịch vụ đối chiếu dân cư.

@RR #k_my1: Về tuân thủ thì theo Thông tư của Ngân hàng Nhà nước về mở tài khoản thanh toán bằng phương thức điện tử, tài khoản mở hoàn toàn trực tuyến mà không gặp mặt thì tổng hạn mức giao dịch ghi nợ không quá 100 triệu đồng một tháng. Ngoài ra bắt buộc đối chiếu sinh trắc học với dữ liệu chip căn cước, không được dùng ảnh chụp giấy tờ thay thế. Như vậy khách không có điện thoại NFC thì không thể mở hoàn toàn trực tuyến được.

@NV: Khách hàng của quỹ tín dụng phần lớn là nông dân, người lớn tuổi, nhiều người dùng điện thoại cũ. Nếu bắt buộc NFC thì mất khoảng một phần ba khách hàng tiềm năng.

@MB: Em đề xuất khi eKYC thất bại thì ứng dụng cho khách lưu hồ sơ đã khai, đặt lịch đến quỹ tín dụng gần nhất, nhân viên quỹ dùng thiết bị đọc chip tại quầy để hoàn tất, không phải khai lại từ đầu.

@GD: Vy cho anh hỏi, trong 81% thành công thì thời gian trung bình để khách hoàn tất mở tài khoản là bao lâu, và khách bỏ dở ở bước nào nhiều nhất?

@MB #k_vy3: Dạ thời gian trung bình là 6 phút 40 giây, nhanh nhất khoảng 3 phút. Bước bỏ dở nhiều nhất là bước đọc chip NFC, khoảng 11% khách đến bước đó thì thoát ra, vì phải áp lưng căn cước vào đúng vị trí ăng ten NFC của điện thoại, mỗi dòng máy một vị trí khác nhau, nhiều khách thử vài lần không được là bỏ. Bọn em đã thêm hình động hướng dẫn vị trí áp thẻ theo từng dòng máy phổ biến, thử nghiệm tuần trước thì tỷ lệ bỏ ở bước này giảm từ 11% xuống 7%. Bước thứ hai là chụp khuôn mặt có kiểm tra người thật, ứng dụng yêu cầu khách quay đầu sang trái, sang phải, chớp mắt, người lớn tuổi làm không đúng nhịp nên hệ thống từ chối.

@NV: Phòng nghiệp vụ có ý kiến từ các quỹ thí điểm. Nhiều thành viên quỹ là nông dân lớn tuổi, họ không tự mở tài khoản trên điện thoại được mà nhờ con cháu làm hộ. Có trường hợp con cháu dùng điện thoại của mình mở tài khoản cho bố mẹ, như vậy thiết bị đăng ký là của con, sau này bố mẹ dùng điện thoại khác thì lại phải xác thực lại.

@RR #k_my6: Đây là rủi ro tuân thủ. Theo quy định, tài khoản thanh toán của cá nhân phải do chính chủ mở và sử dụng, sinh trắc khuôn mặt phải là của chính chủ tài khoản. Nếu con cháu cầm điện thoại thao tác hộ nhưng khuôn mặt chụp là của bố mẹ thì vẫn hợp lệ, nhưng thiết bị đăng ký thì nên là thiết bị chủ tài khoản sẽ sử dụng. Đặc biệt phải ngăn chặn tình trạng mở tài khoản hộ, mua bán tài khoản, vì đây là nguồn chính của tài khoản lừa đảo. Ứng dụng phải giới hạn mỗi thiết bị chỉ đăng ký tối đa một tài khoản chính chủ.

@MB #a_thietbi: Dạ hiện tại ứng dụng chưa giới hạn số tài khoản trên một thiết bị. Bọn em sẽ bổ sung ràng buộc này.

@QA: Bên kiểm thử cũng phát hiện một lỗi là nếu khách dùng ảnh chụp màn hình khuôn mặt người khác đưa trước camera thì bộ kiểm tra người thật của nhà cung cấp hiện tại vẫn cho qua trong khoảng 3 trên 50 lần thử. Đây là lỗ hổng nghiêm trọng, có thể bị lợi dụng để mở tài khoản giả.

@BE: Đó cũng là một lý do nên xem xét lại nhà cung cấp. Các giải pháp kiểm tra người thật đạt chuẩn quốc tế thì tỷ lệ chấp nhận nhầm phải dưới 1 trên 1.000.

@GD #d_nguoithat: Lỗi đó phải ghi vào biên bản đánh giá nhà cung cấp. Tạm thời giữ luồng hiện tại cho thử nghiệm nội bộ, nhưng không được mở cho khách thật cho đến khi khắc phục.

@NV: Phòng nghiệp vụ muốn hỏi thêm về hoàn tất tại quầy. Hiện tại 8 quỹ thí điểm thì có 5 quỹ đã có thiết bị đọc chip căn cước, 3 quỹ chưa có. Mỗi thiết bị khoảng 4 triệu. Ngoài ra giao dịch viên các quỹ cũng cần được hướng dẫn quy trình hoàn tất hồ sơ dở dang từ ứng dụng, vì đây là quy trình mới, khác với mở tài khoản tại quầy truyền thống.

@PM: Thiết bị đọc chip cho 3 quỹ thì nằm trong danh mục mua sắm của dự án, đã có kinh phí. Phần hướng dẫn giao dịch viên sẽ đưa vào chương trình đào tạo tuần đầu tháng 1.

@RR: Phòng rủi ro lưu ý thêm về lưu trữ hồ sơ. Theo quy định, hồ sơ mở tài khoản điện tử gồm dữ liệu chip, ảnh khuôn mặt, nhật ký các bước xác thực phải được lưu trữ tối thiểu 10 năm kể từ khi đóng tài khoản, phục vụ thanh tra và điều tra khi có tranh chấp. Dung lượng ước tính khoảng 3 megabyte một hồ sơ, với 180.000 khách thì khoảng 540 gigabyte, không lớn, nhưng phải mã hóa và có sao lưu tại trung tâm dữ liệu dự phòng.

@BE: Phần lưu trữ đã thiết kế theo yêu cầu đó, dữ liệu sinh trắc được mã hóa bằng khóa riêng lưu trong thiết bị bảo mật phần cứng, không ai trong nhóm kỹ thuật đọc được ảnh gốc nếu không có quyết định của lãnh đạo.

@PM #d_ekyc1: Chốt mục này: giữ luồng eKYC đọc chip và sinh trắc khuôn mặt như hiện tại; khi thất bại thì cho lưu hồ sơ và hoàn tất tại quầy bằng thiết bị đọc chip của quỹ; tài khoản mở hoàn toàn trực tuyến áp hạn mức 100 triệu một tháng theo quy định. Nhà cung cấp eKYC hiện tại tiếp tục dùng.

@MB #a_luuhoso: Em làm chức năng lưu hồ sơ dở dang và đặt lịch tại quầy, hai tuần.

## TOPIC | Xây dựng chức năng chuyển tiền nhanh liên ngân hàng qua Napas 247 | Chuyển tiền nhanh qua Napas đã chạy trên môi trường thử, thời gian xử lý 3,2 giây; lỗi treo giao dịch khi Napas trả kết quả chậm; thống nhất cơ chế tra soát tự động và hoàn tiền trong 15 phút, hiển thị tên người nhận trước khi xác nhận.

@PM: Mục hai là chuyển tiền nhanh. Anh Lâm.

@BE #k_lam1: Dạ. Chức năng chuyển tiền nhanh liên ngân hàng qua Napas 247 đã kết nối xong trên môi trường thử nghiệm của Napas, thời gian xử lý trung bình từ lúc khách bấm xác nhận đến lúc có kết quả là 3,2 giây. Hỗ trợ chuyển theo số tài khoản, số thẻ và mã QR theo chuẩn VietQR. Vấn đề là có khoảng 0,4% giao dịch bị treo, tức là đã trừ tiền khách nhưng Napas chưa trả kết quả trong thời gian chờ 30 giây, trạng thái không rõ. Hiện tại các giao dịch này phải chờ đối soát cuối ngày mới biết thành công hay thất bại, khách thấy mất tiền thì gọi tổng đài.

@QA: Bên kiểm thử thấy thêm là khi khách nhập số tài khoản người nhận, ứng dụng chưa hiển thị tên chủ tài khoản trước khi xác nhận, chuyển nhầm là rất khó đòi lại.

@RR: Hiển thị tên người nhận là bắt buộc, vừa để tránh nhầm vừa để khách cảnh giác với tài khoản lừa đảo.

@NV: Về phí chuyển tiền, phòng nghiệp vụ đề nghị miễn phí chuyển tiền nhanh liên ngân hàng cho giao dịch dưới 500.000 đồng, vì khách nông thôn chủ yếu chuyển số tiền nhỏ, các ngân hàng thương mại đều đã miễn phí, mình thu phí thì khách không dùng. Napas thu của mình khoảng 1.100 đồng một giao dịch.

@GD: Tôi đồng ý miễn phí toàn bộ chuyển tiền trong năm đầu để thu hút khách, chi phí Napas mình chịu, đánh giá lại sau một năm. Chị Hiền ghi vào biểu phí.

@QA: Bên kiểm thử cũng phát hiện khi quét mã QR của một số ví điện tử thì ứng dụng không đọc được, vì ví đó dùng định dạng QR riêng, không theo chuẩn VietQR. Em nghĩ mình chỉ hỗ trợ chuẩn VietQR là đủ, nhưng phải báo lỗi rõ ràng cho khách thay vì treo màn hình.

@BE: Em đề xuất thêm tiến trình tra soát tự động, giao dịch treo quá 60 giây thì hệ thống tự gửi yêu cầu tra soát sang Napas, nếu xác định thất bại thì hoàn tiền vào tài khoản khách trong vòng 15 phút, có thông báo cho khách.

@RR: Phòng rủi ro có thêm yêu cầu về hạn mức chuyển tiền. Theo quy định của Ngân hàng Nhà nước, giao dịch chuyển tiền trên 10 triệu đồng một lần hoặc tổng trên 20 triệu đồng một ngày phải xác thực sinh trắc khuôn mặt. Ngoài ra hệ thống quỹ nên đặt hạn mức chuyển tiền tối đa một ngày cho khách cá nhân là 200 triệu đồng, khách muốn tăng hạn mức thì phải đến quầy đăng ký. Khách hàng của quỹ chủ yếu giao dịch nhỏ, hạn mức cao chỉ làm tăng rủi ro khi bị chiếm tài khoản.

@NV: Phòng nghiệp vụ thấy 200 triệu là phù hợp với khách cá nhân. Nhưng với các hộ kinh doanh, thương lái nông sản là thành viên quỹ thì mùa vụ họ chuyển tiền thanh toán vài trăm triệu một ngày là bình thường, phải có cách cho họ đăng ký hạn mức cao hơn mà không phải đến quầy nhiều lần.

@RR #d_hanmuc: Với hộ kinh doanh thì đăng ký một lần tại quầy, có hồ sơ chứng minh hoạt động kinh doanh, hạn mức tối đa 1 tỷ một ngày, không phải đăng ký lại mỗi lần.

@BE #k_lam2: Về kỹ thuật kết nối Napas, em báo cáo thêm là Napas yêu cầu trước khi lên môi trường chính thức thì phải chạy qua bộ kiểm thử chứng nhận gồm khoảng 140 kịch bản, bao gồm cả các kịch bản lỗi như hết thời gian chờ, trùng giao dịch, hoàn tiền. Hiện bọn em đã chạy đạt 118 kịch bản, còn 22 kịch bản liên quan đến tra soát và hoàn trả chưa đạt, chính là phần tra soát tự động vừa nói. Sau khi đạt đủ thì Napas cần khoảng 2 tuần để thẩm định và cấp chứng nhận. Như vậy phần này là đường găng của tiến độ.

@GD #a_napascert: Nếu 2 tuần thẩm định thì phải xong toàn bộ kịch bản trước ngày 20 tháng 12 mới kịp ra mắt 15 tháng 1. Lâm ưu tiên phần này.

@QA #a_napasqa: Bên kiểm thử sẽ chạy song song các kịch bản chứng nhận Napas trên môi trường thử để phát hiện lỗi sớm, không đợi Napas chạy.

@NV: Về miễn phí chuyển tiền, phòng nghiệp vụ đã tính chi phí Napas năm đầu khoảng 2,6 tỷ nếu đạt mục tiêu 180.000 khách hàng hoạt động, mỗi khách khoảng 12 giao dịch liên ngân hàng một tháng.

@MB: Về giao diện chuyển tiền, bọn em đã làm khảo sát nhanh với 30 thành viên quỹ lớn tuổi ở quỹ thí điểm Hòa Vang. Nhiều người không quen nhập số tài khoản dài, hay nhập nhầm. Bọn em đề xuất thêm chức năng danh bạ người nhận, lưu những người hay chuyển, và quét mã QR là cách chính. Ngoài ra cỡ chữ mặc định trên ứng dụng tăng lên, có chế độ chữ to cho người cao tuổi.

@NV: Phòng nghiệp vụ ủng hộ. Người nông dân hay chuyển tiền cho con đi học, trả tiền phân bón cho đại lý, đều là người quen, danh bạ là rất tiện. Cũng nên có chức năng chuyển tiền định kỳ, ví dụ mỗi tháng tự chuyển tiền học cho con vào ngày mùng 5.

@RR #n_dinhky: Chuyển tiền định kỳ thì cần khách xác thực một lần khi đăng ký lệnh, sau đó hệ thống tự động thực hiện, nhưng phải gửi thông báo trước 1 ngày để khách có thể hủy nếu cần. Đây là chức năng nên để giai đoạn 2, giai đoạn 1 tập trung các chức năng cốt lõi.

@QA #n_dongbang: Bên kiểm thử đề nghị mọi thay đổi giao diện chuyển tiền phải chốt trước ngày 15 tháng 12, sau đó đóng băng tính năng để kiểm thử hồi quy và chuẩn bị nộp kho ứng dụng, không thêm tính năng mới nữa.

@PM #d_napas: Chốt: hiển thị tên chủ tài khoản người nhận trước khi xác nhận; giao dịch treo quá 60 giây tự động tra soát, thất bại thì hoàn tiền trong 15 phút và thông báo cho khách; miễn phí toàn bộ chuyển tiền trong năm đầu; chỉ hỗ trợ mã QR chuẩn VietQR, mã không hợp lệ thì báo lỗi rõ ràng.

@BE #a_trasoat: Em làm tiến trình tra soát tự động, xong trong sprint này.

@MB #a_tennguoinhan: Phần hiển thị tên người nhận trên ứng dụng em làm luôn, ba ngày.

## TOPIC | Xây dựng chức năng vay tiêu dùng trực tuyến cho thành viên quỹ | Vay tiêu dùng trực tuyến tối đa 50 triệu cho thành viên có lịch sử tín dụng; mô hình chấm điểm dùng dữ liệu nội bộ, tỷ lệ phê duyệt tự động 42%; thống nhất giới hạn vay trực tuyến cho thành viên trên 12 tháng, cán bộ tín dụng duyệt hồ sơ trên 20 triệu; đề xuất dùng dữ liệu mạng xã hội để chấm điểm bị gạt.

@PM: Mục ba là vay tiêu dùng trực tuyến. Anh Đông.

@NV #k_dong: Dạ. Chức năng vay tiêu dùng trực tuyến cho phép thành viên quỹ đăng ký vay không có tài sản bảo đảm, tối đa 50 triệu đồng, thời hạn tối đa 24 tháng, giải ngân thẳng vào tài khoản thanh toán. Mô hình chấm điểm tín dụng hiện tại dùng dữ liệu nội bộ của quỹ: thời gian làm thành viên, lịch sử vay trả, số dư tiền gửi, cộng với điểm tín dụng từ Trung tâm Thông tin tín dụng quốc gia. Chạy thử trên 3.000 hồ sơ cũ thì tỷ lệ được phê duyệt tự động là 42%, từ chối tự động 21%, còn lại 37% chuyển cán bộ tín dụng xem xét.

@RR #k_my2: Phòng rủi ro đề nghị thận trọng. Quỹ tín dụng hoạt động theo nguyên tắc chủ yếu cho vay thành viên, nợ xấu vay tiêu dùng không bảo đảm thường cao. Đề nghị chỉ cho thành viên đã tham gia trên 12 tháng được vay trực tuyến, và khoản trên 20 triệu thì phải có cán bộ tín dụng gọi điện xác minh và duyệt, không phê duyệt tự động.

@MB #n_mxh: Em có đọc là một số công ty tài chính dùng dữ liệu mạng xã hội, danh bạ điện thoại để chấm điểm tín dụng, tỷ lệ duyệt cao hơn, hay mình thử thêm nguồn này.

@RR #n_mxh2: Không được. Thu thập danh bạ, dữ liệu mạng xã hội để chấm điểm là vi phạm Luật Bảo vệ dữ liệu cá nhân nếu không có sự đồng ý rõ ràng cho từng mục đích, và đã có nhiều công ty bị xử lý vì dùng danh bạ đòi nợ. Ngân hàng Nhà nước cũng đang siết. Không dùng.

@GD: Anh Đông cho biết thêm, nợ xấu vay tiêu dùng hiện nay của hệ thống quỹ thế nào, để mình có cơ sở so sánh?

@NV #k_dong2: Dạ, dư nợ cho vay tiêu dùng không có tài sản bảo đảm của toàn hệ thống quỹ liên kết hiện khoảng 1.240 tỷ, tỷ lệ nợ xấu khoảng 2,8%, cao hơn tỷ lệ nợ xấu chung của các quỹ khoảng 1,4%. Nợ xấu chủ yếu rơi vào khách vay để tiêu dùng mua sắm, sửa nhà, còn vay phục vụ sản xuất nông nghiệp thì nợ xấu thấp hơn. Khi chuyển sang vay trực tuyến, kinh nghiệm của các công ty tài chính là nợ xấu ban đầu thường cao hơn kênh truyền thống khoảng 1,5 đến 2 lần, vì không có cán bộ tín dụng gặp trực tiếp, đánh giá được hoàn cảnh khách.

@RR: Vì vậy phòng rủi ro đề nghị giai đoạn thí điểm đặt hạn mức tổng dư nợ vay trực tuyến của toàn hệ thống tối đa 50 tỷ, theo dõi nợ xấu theo từng tháng, nếu tỷ lệ quá hạn trên 30 ngày vượt 5% thì tạm dừng giải ngân mới để rà soát mô hình chấm điểm.

@BE: Về kỹ thuật thì mô hình chấm điểm hiện tại là mô hình hồi quy logistic với 18 biến, đơn giản, dễ giải thích. Bọn em chọn mô hình đơn giản thay vì học máy phức tạp vì theo yêu cầu của Ngân hàng Nhà nước, tổ chức tín dụng phải giải thích được lý do từ chối cho vay khi khách hỏi. Mỗi hồ sơ bị từ chối đều có ba lý do chính hiển thị cho cán bộ tín dụng.

@QA: Bên kiểm thử đã thử các trường hợp biên, ví dụ khách vừa trả hết một khoản vay cũ hôm trước, hôm sau đăng ký vay mới, thì dữ liệu Trung tâm Thông tin tín dụng chưa cập nhật, hệ thống vẫn thấy dư nợ cũ, chấm điểm thấp. Cần có cơ chế cho cán bộ cập nhật thủ công trong trường hợp này.

@NV: Thêm một vấn đề là lãi suất. Lãi suất vay tiêu dùng trực tuyến dự kiến 13% một năm, bằng với vay tiêu dùng tại quầy. Phòng nghiệp vụ không đề xuất lãi suất cao hơn vì quỹ tín dụng hoạt động không vì mục tiêu lợi nhuận tối đa, phải hỗ trợ thành viên.

@RR #n_laisuat: Phòng rủi ro thì thấy vay trực tuyến rủi ro cao hơn nên lãi suất có thể cao hơn khoảng 1 đến 2 điểm phần trăm để bù rủi ro. Nhưng việc này cần Hội đồng quản trị quyết, không quyết ở đây được.

@GD #d_thidiemvay: Lãi suất thì để Hội đồng quản trị quyết định, giai đoạn thí điểm tạm áp dụng như vay tại quầy.

@NV: Phòng nghiệp vụ xin cung cấp thêm số liệu nhu cầu. Theo khảo sát 1.500 thành viên ở 8 quỹ thí điểm, khoảng 38% có nhu cầu vay tiêu dùng nhỏ dưới 30 triệu trong năm tới, chủ yếu để mua sắm thiết bị gia đình, chi phí học tập cho con, chữa bệnh. Hiện nay nhiều thành viên phải vay qua các ứng dụng cho vay của công ty tài chính với lãi suất thực tế lên đến 30 đến 40% một năm, có người vay qua ứng dụng cho vay không phép, bị đòi nợ khủng bố. Nếu quỹ cung cấp được khoản vay nhỏ nhanh với lãi suất 13% thì đây là hỗ trợ rất thiết thực cho thành viên, đúng tôn chỉ của quỹ tín dụng nhân dân.

@RR: Phòng rủi ro hiểu ý nghĩa xã hội, nhưng chính vì khách hàng mục tiêu là người đang vay các ứng dụng lãi cao nên rủi ro nợ xấu cũng cao hơn, có thể họ dùng khoản vay của quỹ để đảo nợ. Mô hình chấm điểm có biến dư nợ tại các tổ chức khác từ dữ liệu Trung tâm Thông tin tín dụng, khách đang có nhiều khoản vay tiêu dùng cùng lúc sẽ bị chấm điểm thấp.

@MB: Về luồng vay trên ứng dụng, bọn em thiết kế khách chọn số tiền, thời hạn, ứng dụng hiện ngay số tiền trả hằng tháng ước tính, tổng lãi phải trả, sau đó khách nộp đơn, đọc và ký hợp đồng tín dụng điện tử bằng mã OTP và sinh trắc khuôn mặt. Kết quả phê duyệt tự động trong khoảng 5 phút, giải ngân ngay vào tài khoản.

@RR: Hợp đồng tín dụng điện tử phải hiển thị đầy đủ các điều khoản quan trọng như lãi suất, phí phạt trả chậm, quyền trả nợ trước hạn ở dạng tóm tắt dễ đọc trước khi ký, không được chỉ để đường dẫn đến văn bản dài. Theo quy định về bảo vệ quyền lợi người tiêu dùng tài chính, khách phải được xác nhận đã đọc từng điều khoản chính.

@NV: Thêm một vấn đề là thu nợ. Với vay tại quầy thì cán bộ tín dụng đến nhà đôn đốc khi chậm trả. Với vay trực tuyến, phòng nghiệp vụ đề nghị ứng dụng tự nhắc trước 3 ngày đến hạn, hỗ trợ trích nợ tự động từ tài khoản thanh toán, khách quá hạn 10 ngày thì cán bộ tín dụng của quỹ nơi khách là thành viên mới gọi điện, không thuê đơn vị đòi nợ bên ngoài.

@RR #d_thuno: Phòng rủi ro đồng ý không thuê đơn vị đòi nợ bên ngoài, vì đây là rủi ro uy tín và pháp lý lớn.

@PM #d_vay: Chốt: vay trực tuyến chỉ cho thành viên trên 12 tháng; khoản đến 20 triệu được phê duyệt tự động nếu đạt điểm, trên 20 triệu thì cán bộ tín dụng xác minh và duyệt; mô hình chấm điểm chỉ dùng dữ liệu nội bộ và Trung tâm Thông tin tín dụng.

@NV #a_quytrinh: Phòng nghiệp vụ soạn quy trình duyệt vay trực tuyến cho cán bộ tín dụng các quỹ, gửi chị Mỹ thẩm định trước ngày 20.

## TOPIC | Xây dựng chức năng mở tài khoản thanh toán trực tuyến bằng eKYC | Quay lại eKYC: nhà cung cấp eKYC thông báo tăng phí 60% và chưa đạt kiểm định của Bộ Công an về đối chiếu sinh trắc; thống nhất đổi sang dùng dịch vụ xác thực qua ứng dụng VNeID kết hợp nhà cung cấp eKYC mới đã được kiểm định.

@RR #k_my3: Chị Hiền ơi, cho chị quay lại mục eKYC một chút. Trong lúc họp chị vừa nhận email của bên pháp chế. Nhà cung cấp eKYC hiện tại vừa gửi thông báo tăng phí từ 3.000 đồng lên 4.800 đồng mỗi lượt xác thực từ tháng sau, tăng 60%. Quan trọng hơn là theo danh sách Bộ Công an công bố tuần trước, nhà cung cấp này chưa có tên trong danh sách các đơn vị được kết nối chính thức dịch vụ xác thực sinh trắc với cơ sở dữ liệu dân cư, họ đang kết nối qua một đơn vị trung gian. Theo quy định mới thì từ đầu năm sau các tổ chức tín dụng chỉ được dùng đơn vị đã được kết nối chính thức.

@BE: Như vậy là không dùng tiếp được. Phương án thay thế thì có hai. Một là tích hợp xác thực qua ứng dụng VNeID, khách xác thực trên VNeID rồi chia sẻ thông tin định danh về ứng dụng ngân hàng, cách này miễn phí và được Ngân hàng Nhà nước khuyến khích. Hai là chuyển sang một nhà cung cấp eKYC khác đã có tên trong danh sách chính thức. Em đề nghị kết hợp cả hai: VNeID là luồng chính, nhà cung cấp mới là luồng dự phòng cho khách chưa kích hoạt VNeID mức 2.

@MB: Tích hợp VNeID thì em ước tính khoảng ba tuần, vì phải đăng ký với Trung tâm dữ liệu quốc gia về dân cư và làm theo bộ tài liệu tích hợp của họ.

@GD: Ba tuần thì sát với mốc ra mắt, nhưng phải làm. Không thể ra mắt với nhà cung cấp không đủ điều kiện.

@GD: Chị Mỹ cho biết thêm, nếu chuyển sang VNeID thì có vấn đề gì về pháp lý hay hợp đồng với nhà cung cấp cũ không?

@RR #k_my7: Dạ, hợp đồng với nhà cung cấp eKYC hiện tại là hợp đồng dịch vụ theo lượt, có điều khoản chấm dứt trước hạn với thông báo trước 30 ngày, không có phạt nếu bên cung cấp vi phạm điều kiện pháp lý. Việc họ chưa đủ điều kiện kết nối chính thức là căn cứ để chấm dứt mà không phải bồi thường. Về VNeID, quỹ cần ký thỏa thuận kết nối với Trung tâm dữ liệu quốc gia về dân cư thuộc Bộ Công an, phải đáp ứng yêu cầu bảo mật như hệ thống đạt cấp độ 3 trở lên, có đầu mối kỹ thuật, có quy trình bảo vệ dữ liệu. Thời gian phê duyệt hồ sơ khoảng 15 đến 20 ngày làm việc nếu hồ sơ đầy đủ.

@MB: Luồng VNeID trên ứng dụng thì khách bấm "xác thực bằng VNeID", ứng dụng chuyển sang ứng dụng VNeID, khách nhập mã PIN VNeID và xác nhận chia sẻ thông tin, sau đó quay lại ứng dụng ngân hàng, rồi chụp khuôn mặt để đối chiếu. Nhanh hơn luồng đọc chip, trung bình khoảng 2 phút. Nhưng điều kiện là khách phải đã có tài khoản định danh điện tử mức 2 và nhớ mã PIN. Theo số liệu của Bộ Công an thì ở các tỉnh miền Trung tỷ lệ kích hoạt mức 2 khoảng 70% người trưởng thành, ở nông thôn thấp hơn.

@NV: Nhiều người dân quên mã PIN VNeID, phải ra công an xã để đặt lại. Phòng nghiệp vụ đề nghị khi khách không xác thực được VNeID thì ứng dụng tự chuyển sang luồng dự phòng đọc chip, không bắt khách quay lại từ đầu.

@BE: Đúng vậy, thiết kế là chuỗi ba bước dự phòng: VNeID trước, không được thì đọc chip qua nhà cung cấp mới, không được nữa thì lưu hồ sơ hoàn tất tại quầy.

@QA: Bên kiểm thử cần tài khoản VNeID thử nghiệm từ Trung tâm dữ liệu dân cư để kiểm thử, vì không thể dùng tài khoản thật của nhân viên. Thường mất khoảng một tuần sau khi ký thỏa thuận mới được cấp.

@GD #d_vneid_fallback: Như vậy tiến độ VNeID rất sát. Nếu đến ngày 5 tháng 1 VNeID chưa sẵn sàng thì ra mắt với luồng nhà cung cấp mới làm luồng chính, VNeID bổ sung sau.

@NV: Phòng nghiệp vụ xin hỏi chi phí nhà cung cấp eKYC mới thế nào, có cao hơn nhà cung cấp cũ không?

@RR: Theo báo giá sơ bộ qua điện thoại thì hai nhà cung cấp trong danh sách chính thức đều chào khoảng 3.500 đến 4.000 đồng một lượt, cao hơn mức cũ 3.000 nhưng thấp hơn mức 4.800 mà nhà cung cấp cũ định tăng. Nếu VNeID là luồng chính, miễn phí, thì luồng dự phòng chỉ chiếm khoảng 30% số lượt, tổng chi phí eKYC năm đầu ước giảm khoảng 40% so với phương án cũ.

@MB: Em lưu ý là tích hợp nhà cung cấp mới cũng mất khoảng 1 tuần, vì bộ thư viện của mỗi nhà cung cấp khác nhau. Như vậy trong 3 tuần tới nhóm mobile phải làm song song VNeID và nhà cung cấp mới, nhóm cần thêm 1 lập trình viên iOS.

@PM #a_ios: Em sẽ điều động thêm 1 lập trình viên iOS từ dự án khác sang trong 4 tuần.

@GD: Đồng ý điều động. Tiến độ phần eKYC là ưu tiên số một của dự án lúc này.

@PM #d_ekyc2: Vậy em điều chỉnh lại kết luận ở mục eKYC: không tiếp tục dùng nhà cung cấp eKYC hiện tại. Luồng chính là xác thực qua VNeID, luồng dự phòng là nhà cung cấp eKYC mới có tên trong danh sách chính thức của Bộ Công an. Các nội dung khác như hoàn tất tại quầy và hạn mức 100 triệu giữ nguyên.

@BE #a_vneid: Em làm hồ sơ đăng ký tích hợp VNeID với Trung tâm dữ liệu dân cư ngay tuần này.

@RR #a_ncc: Chị làm việc với hai nhà cung cấp có tên trong danh sách, có báo giá và đánh giá trong 5 ngày.

## TOPIC | Xây dựng chức năng thông báo biến động số dư và cảnh báo chống lừa đảo | Thông báo biến động số dư qua ứng dụng đã chạy, tin nhắn SMS tốn 1,1 tỷ/năm; thống nhất miễn phí thông báo qua ứng dụng, SMS thu phí theo đăng ký; bổ sung cảnh báo khi chuyển tiền đến tài khoản nằm trong danh sách nghi ngờ lừa đảo và giới hạn chuyển tiền trên thiết bị mới.

@PM: Mục năm là thông báo số dư và chống lừa đảo. Vy.

@MB #k_vy2: Dạ. Thông báo biến động số dư qua thông báo đẩy trên ứng dụng đã chạy, độ trễ dưới 2 giây. Hiện tại khách vẫn nhận song song tin nhắn SMS, với khoảng 180.000 khách và trung bình 12 giao dịch một tháng thì chi phí SMS khoảng 1,1 tỷ đồng một năm. Về chống lừa đảo, ứng dụng đã có xác thực sinh trắc khuôn mặt với giao dịch trên 10 triệu theo Quyết định 2345 của Ngân hàng Nhà nước. Nhưng chưa có cảnh báo khi khách chuyển tiền đến tài khoản bị nghi ngờ lừa đảo.

@RR #k_my4: Ngân hàng Nhà nước đã có hệ thống SIMO chia sẻ danh sách tài khoản nghi ngờ gian lận giữa các tổ chức tín dụng. Ứng dụng phải kết nối để khi khách chuyển đến tài khoản trong danh sách thì hiện cảnh báo rõ ràng, khách phải xác nhận lần hai. Thêm nữa, khi khách đăng nhập trên thiết bị mới thì 24 giờ đầu giới hạn chuyển tiền tối đa 10 triệu, vì nhiều vụ lừa đảo là kẻ gian chiếm tài khoản rồi đăng nhập trên máy khác.

@NV: Về SMS, khách nông thôn nhiều người vẫn quen SMS, nếu cắt hẳn thì họ phản ứng.

@QA: Em xin nói thêm về các kiểu lừa đảo mà tổng đài thử nghiệm ghi nhận. Trong tháng thử nghiệm có 7 khách gọi lên báo bị gọi điện giả danh nhân viên quỹ, yêu cầu cài ứng dụng giả để "nâng cấp tài khoản", may là chưa ai mất tiền. Em đề nghị ứng dụng có thêm chức năng phát hiện ứng dụng điều khiển màn hình từ xa đang chạy trên điện thoại, nếu có thì chặn giao dịch, vì kẻ gian hay dùng loại ứng dụng đó để thao tác thay khách.

@BE: Cái này các ngân hàng lớn đã làm, có thư viện bảo vệ ứng dụng phát hiện được ứng dụng truy cập trợ năng và điều khiển từ xa. Chi phí bản quyền khoảng 400 triệu một năm.

@GD: Chi phí đó đáng. Đưa vào.

@RR: Kèm theo là trên ứng dụng phải có mục cảnh báo các thủ đoạn lừa đảo mới, cập nhật hằng tháng, và nút gọi nhanh tổng đài khóa tài khoản khẩn cấp.

@NV #k_dong3: Phòng nghiệp vụ xin báo cáo số liệu về lừa đảo từ các quỹ thí điểm. Trong 3 tháng qua, các quỹ ghi nhận 23 vụ thành viên bị lừa chuyển tiền qua các ngân hàng khác, tổng số tiền khoảng 1,7 tỷ. Thủ đoạn phổ biến nhất là giả danh cán bộ quỹ gọi điện thông báo được giải ngân khoản vay ưu đãi, yêu cầu nộp phí hồ sơ trước. Thứ hai là giả danh cơ quan thuế, bảo hiểm xã hội yêu cầu cài ứng dụng. Người bị lừa chủ yếu là người trên 55 tuổi.

@RR: Với thủ đoạn giả danh cán bộ quỹ, ứng dụng cần có mục thông báo chính thức, mọi thông báo về khoản vay đều phải xuất hiện trong ứng dụng, khách được tuyên truyền là nếu không thấy trong ứng dụng thì là lừa đảo. Ngoài ra số tổng đài của quỹ phải đăng ký tên định danh với nhà mạng, để khi gọi đến hiện tên "Quỹ tín dụng" thay vì số lạ.

@MB #a_canhbaocuocgoi: Bọn em có thể thêm chức năng hiện cảnh báo toàn màn hình khi khách đang trong cuộc gọi điện thoại mà mở ứng dụng để chuyển tiền, nhắc khách cẩn thận nếu đang được người lạ hướng dẫn chuyển tiền. Android cho phép phát hiện trạng thái cuộc gọi, iOS thì hạn chế hơn.

@QA: Bên kiểm thử đã kiểm thử thông báo đẩy trên 40 dòng điện thoại phổ biến, có khoảng 6 dòng máy giá rẻ của Trung Quốc mặc định chặn ứng dụng chạy nền để tiết kiệm pin, nên không nhận được thông báo biến động số dư khi ứng dụng đóng. Khách sẽ phàn nàn là không nhận được thông báo.

@MB: Với các dòng máy này, ứng dụng sẽ hiển thị hướng dẫn khách tắt chế độ tối ưu pin cho ứng dụng ngay lần đầu cài đặt. Và đây cũng là lý do giữ SMS cho khách đăng ký.

@GD: Về SMS, chị Hiền tính giúp mức phí bao nhiêu là hợp lý.

@PM #n_phisms: Các ngân hàng thương mại thu khoảng 8.000 đến 11.000 đồng một tháng cho dịch vụ SMS. Em đề xuất quỹ thu 8.000 đồng một tháng, khách trên 60 tuổi miễn phí như đã chốt. Với khoảng 40% khách tiếp tục đăng ký SMS thì doanh thu bù được khoảng 70% chi phí SMS.

@RR: Về thư viện phát hiện ứng dụng điều khiển từ xa, phòng rủi ro đề nghị khi phát hiện thì không chỉ chặn giao dịch mà còn phải ghi nhận sự kiện về hệ thống giám sát gian lận, nếu cùng một tài khoản có nhiều sự kiện như vậy trong thời gian ngắn thì tự động tạm khóa và tổng đài gọi xác minh với khách.

@BE #a_luatgianlan: Hệ thống giám sát gian lận giai đoạn 1 hiện chỉ có các luật cơ bản: giao dịch giá trị lớn bất thường so với lịch sử của khách, nhiều giao dịch liên tiếp đến các tài khoản mới, đăng nhập từ vị trí địa lý bất thường. Thêm luật về sự kiện điều khiển từ xa thì đơn giản, khoảng 2 ngày.

@NV: Phòng nghiệp vụ đề nghị nút khóa tài khoản khẩn cấp trên ứng dụng phải đặt ngay ở màn hình đăng nhập, khách chưa cần đăng nhập vẫn bấm được, vì khi bị lừa thì khách thường hoảng, kẻ gian có thể đã đổi mật khẩu.

@MB #a_nutkhoa: Dạ được, nút khóa khẩn cấp ở màn hình đăng nhập, yêu cầu nhập số điện thoại và số căn cước để xác nhận, sau đó tài khoản bị khóa giao dịch ghi nợ ngay, muốn mở lại phải đến quầy.

@PM #d_thongbao: Chốt: thông báo qua ứng dụng miễn phí; SMS chuyển sang thu phí theo đăng ký của khách, khách trên 60 tuổi miễn phí SMS; kết nối hệ thống SIMO cảnh báo tài khoản nghi ngờ, bắt buộc xác nhận lần hai; thiết bị mới giới hạn chuyển tối đa 10 triệu trong 24 giờ đầu; tích hợp thư viện phát hiện ứng dụng điều khiển từ xa và chặn giao dịch; thêm mục cảnh báo thủ đoạn lừa đảo và nút khóa tài khoản khẩn cấp.

@BE #a_simo: Em làm kết nối SIMO, cần chị Mỹ hỗ trợ thủ tục đăng ký với Ngân hàng Nhà nước.

@MB #a_thietbimoi: Giới hạn thiết bị mới và màn hình cảnh báo em làm trong sprint này.

## TOPIC | Rà soát kết quả kiểm thử hiệu năng và chịu tải hệ thống | Kiểm thử tải 2.000 giao dịch/giây đạt, nhưng máy chủ cơ sở dữ liệu lõi lên 92% CPU; thống nhất tách cơ sở dữ liệu đọc, bổ sung bộ nhớ đệm và kiểm thử lại với 3.000 giao dịch/giây trước ra mắt.

@PM: Mục sáu là hiệu năng. Anh Toản.

@QA #k_toan: Dạ. Nhóm kiểm thử đã chạy kiểm thử chịu tải với kịch bản 2.000 giao dịch mỗi giây, mô phỏng giờ cao điểm ngày trả lương, gồm đăng nhập, xem số dư, chuyển tiền nội bộ và liên ngân hàng. Kết quả thời gian phản hồi phần trăm thứ 95 là 1,4 giây, đạt yêu cầu dưới 2 giây, tỷ lệ lỗi 0,02%. Tuy nhiên máy chủ cơ sở dữ liệu lõi lên đến 92% CPU, tức là gần như không còn dư địa. Nếu lượng khách tăng hoặc có đợt khuyến mãi thì sẽ quá tải.

@BE: Nguyên nhân là truy vấn xem số dư và lịch sử giao dịch chiếm khoảng 70% tải, đều đi vào cơ sở dữ liệu lõi. Em đề xuất tách một bản sao cơ sở dữ liệu chỉ đọc cho các truy vấn xem lịch sử, thêm bộ nhớ đệm cho số dư, như vậy tải cơ sở dữ liệu lõi giảm khoảng một nửa.

@QA: Ngoài ra kiểm thử độ bền chạy liên tục 12 tiếng thì phát hiện bộ nhớ của dịch vụ thông báo đẩy tăng dần, sau khoảng 9 tiếng thì dịch vụ khởi động lại, mất khoảng 40 giây thông báo. Có vẻ là rò rỉ bộ nhớ.

@MB: Dịch vụ thông báo đẩy là bên em viết, em sẽ kiểm tra lại, có thể do không đóng kết nối tới máy chủ thông báo của Apple khi thiết bị gỡ ứng dụng.

@BE: Bên hạ tầng cũng sẽ cấu hình tự động mở rộng thêm phiên bản dịch vụ khi tải cao, để một phiên bản khởi động lại thì phiên bản khác vẫn chạy.

@GD: Tôi muốn kiểm thử lại với mức 3.000 giao dịch mỗi giây, dư 50% so với dự báo cao điểm, trước khi ra mắt.

@GD: Anh Toản cho biết kịch bản 2.000 giao dịch mỗi giây dựa trên giả định nào?

@QA #k_toan2: Dạ thưa anh, kịch bản dựa trên số liệu giao dịch tại quầy và qua SMS banking cũ của hệ thống quỹ. Hiện tại cao điểm là ngày mùng 5 đến mùng 10 hằng tháng khi các doanh nghiệp, cơ quan trả lương và các hộ trả nợ vay, khoảng 9 giờ đến 11 giờ sáng. Với mục tiêu 180.000 khách hàng hoạt động năm đầu, giả định 15% khách đăng nhập trong cùng một giờ cao điểm, mỗi phiên trung bình 6 thao tác, thì đỉnh khoảng 1.300 giao dịch mỗi giây. Kịch bản 2.000 là đã cộng hệ số an toàn 1,5. Anh Trí yêu cầu 3.000 là hệ số an toàn khoảng 2,3, phù hợp nếu có đợt khuyến mãi hoặc tăng trưởng khách nhanh.

@BE: Em bổ sung về hạ tầng. Hiện hệ thống chạy trên 2 máy chủ cơ sở dữ liệu lõi cấu hình chủ - dự phòng, 12 máy chủ ứng dụng tại trung tâm dữ liệu chính ở Quy Nhơn. Tách cơ sở dữ liệu đọc thì cần thêm 2 máy chủ, khoảng 900 triệu, đã có trong dự toán dự phòng của dự án. Bộ nhớ đệm thì dùng phần mềm mã nguồn mở, không mất phí bản quyền.

@RR: Phòng rủi ro lưu ý là dữ liệu số dư trong bộ nhớ đệm phải nhất quán với cơ sở dữ liệu lõi. Nếu khách thấy số dư cũ trong bộ nhớ đệm rồi chuyển tiền vượt số dư thực thì sao?

@BE: Dạ bộ nhớ đệm chỉ dùng cho hiển thị số dư khi xem. Khi khách thực hiện giao dịch chuyển tiền thì hệ thống luôn kiểm tra số dư trực tiếp từ cơ sở dữ liệu lõi trong cùng giao dịch, khóa số dư, không dùng bộ nhớ đệm. Khi có giao dịch thì bộ nhớ đệm bị xóa và cập nhật lại ngay.

@QA #a_amsodu: Bên kiểm thử sẽ bổ sung kịch bản kiểm tra tính nhất quán này, cho hai giao dịch chuyển tiền đồng thời trên cùng một tài khoản để đảm bảo không bị âm số dư.

@GD: Cái này rất quan trọng, lỗi âm số dư là lỗi nghiêm trọng nhất của hệ thống ngân hàng.

@GD: Ngoài cơ sở dữ liệu thì còn điểm nghẽn nào khác không, ví dụ kết nối Napas hay dịch vụ xác thực sinh trắc?

@QA: Dạ có, khi chạy 2.000 giao dịch mỗi giây thì dịch vụ xác thực sinh trắc khuôn mặt cho giao dịch trên 10 triệu bắt đầu chậm, thời gian phản hồi lên khoảng 3 giây ở mức 150 yêu cầu xác thực mỗi giây. Nhưng trong thực tế chỉ khoảng 5% giao dịch trên 10 triệu nên không đáng lo. Kết nối Napas thì giới hạn bởi Napas cấp cho quỹ khoảng 300 giao dịch mỗi giây, đủ dùng cho năm đầu.

@BE: Em đề xuất thêm là cấu hình tự động mở rộng máy chủ ứng dụng theo tải, hiện tại hạ tầng ảo hóa ở trung tâm dữ liệu cho phép thêm máy chủ ứng dụng trong khoảng 5 phút khi tải vượt 70%.

@RR #n_giamsat: Phòng rủi ro đề nghị có bảng giám sát hiệu năng theo thời gian thực cho đội vận hành, cảnh báo qua tin nhắn khi thời gian phản hồi vượt 2 giây hoặc tỷ lệ lỗi vượt 0,5%, có người trực 24/7 trong tháng đầu sau ra mắt.

@PM #d_hieunang: Chốt: tách cơ sở dữ liệu chỉ đọc cho truy vấn lịch sử, thêm bộ nhớ đệm số dư, kiểm thử lại với 3.000 giao dịch mỗi giây; CPU cơ sở dữ liệu lõi phải dưới 70% mới đạt.

@BE #a_tachdb: Em làm tách cơ sở dữ liệu đọc và bộ nhớ đệm trong hai tuần.

@QA #a_testlai: Bên em chạy lại kiểm thử ngay sau khi anh Lâm xong, dự kiến tuần thứ ba.

@MB #a_romem: Lỗi rò rỉ bộ nhớ dịch vụ thông báo em sửa trong tuần này, gửi anh Toản chạy lại kiểm thử độ bền.

## TOPIC | Chuẩn bị hồ sơ đề nghị Ngân hàng Nhà nước chấp thuận triển khai dịch vụ ngân hàng số | Hồ sơ gửi Ngân hàng Nhà nước còn thiếu báo cáo đánh giá an toàn thông tin cấp độ 4 và phương án dự phòng thảm họa; thống nhất thuê đơn vị được cấp phép đánh giá, hoàn thiện hồ sơ trước 15/12.

@PM: Mục bảy, hồ sơ gửi Ngân hàng Nhà nước. Chị Mỹ.

@RR #k_my5: Dạ. Để triển khai dịch vụ mở tài khoản trực tuyến và cho vay trực tuyến thì hệ thống quỹ phải có văn bản báo cáo Ngân hàng Nhà nước chi nhánh khu vực, kèm hồ sơ chứng minh đáp ứng các yêu cầu về an toàn hệ thống. Hiện hồ sơ còn thiếu hai thứ quan trọng: báo cáo đánh giá an toàn thông tin hệ thống cấp độ 4 do đơn vị độc lập được cấp phép thực hiện, và phương án dự phòng thảm họa có diễn tập chuyển đổi sang trung tâm dữ liệu dự phòng. Nếu không có hai thứ này thì không ra mắt được.

@BE: Trung tâm dữ liệu dự phòng thì đã có ở Đà Nẵng, nhưng chưa diễn tập chuyển đổi lần nào.

@GD: Phải diễn tập thật, có biên bản, thời gian khôi phục phải dưới 4 giờ theo cam kết.

@BE: Diễn tập thật thì phải chuyển toàn bộ lưu lượng sang Đà Nẵng trong khoảng 2 đến 3 tiếng, em đề nghị làm vào đêm thứ Bảy, thông báo trước cho các quỹ, và chỉ làm trên môi trường thử nghiệm trước ứng dụng ra mắt, vì lúc đó chưa có khách thật.

@RR: Hồ sơ cũng cần quy chế quản lý rủi ro công nghệ thông tin được Hội đồng quản trị phê duyệt, và danh sách nhân sự chủ chốt vận hành hệ thống có chứng chỉ phù hợp. Quy chế thì phòng chị đã soạn, cần trình Hội đồng quản trị phiên họp ngày 10 tháng 12.

@GD: Tôi sẽ đưa vào chương trình phiên họp Hội đồng quản trị ngày 10. Chị Mỹ gửi dự thảo cho thư ký Hội đồng trước ngày 5.

@RR #a_quyche: Vâng, chị gửi trước ngày 5 tháng 12.

@GD: Chị Mỹ, đơn vị đánh giá cấp độ 4 thì mình đã có danh sách chưa, chi phí và thời gian bao lâu?

@RR #k_my8: Dạ, theo danh sách các tổ chức được Bộ Công an và Bộ Khoa học và Công nghệ cấp phép dịch vụ kiểm tra, đánh giá an toàn thông tin, chị đã liên hệ ba đơn vị. Báo giá khoảng 350 đến 500 triệu cho phạm vi ứng dụng di động, hệ thống lõi, kết nối Napas và hạ tầng. Thời gian đánh giá khoảng 3 tuần, bao gồm kiểm thử xâm nhập, rà soát cấu hình, đánh giá quy trình. Nếu phát hiện lỗ hổng thì phải khắc phục và đánh giá lại, thêm khoảng 1 tuần. Như vậy nếu ký hợp đồng trong tuần này thì khoảng ngày 10 đến 12 tháng 12 có báo cáo, vừa kịp hạn 15 tháng 12.

@BE: Về diễn tập dự phòng, em báo cáo là trung tâm dữ liệu dự phòng ở Đà Nẵng hiện đồng bộ dữ liệu từ trung tâm chính với độ trễ khoảng 30 giây. Như vậy nếu trung tâm chính sự cố hoàn toàn thì có thể mất tối đa 30 giây giao dịch, các giao dịch này sẽ được đối soát lại với Napas. Cam kết là thời gian khôi phục dưới 4 giờ, lượng dữ liệu mất tối đa 5 phút.

@QA: Em đề nghị kịch bản diễn tập phải có cả trường hợp chuyển về, tức là sau khi chạy ở Đà Nẵng thì chuyển ngược lại Quy Nhơn, vì nhiều tổ chức diễn tập chỉ chuyển đi mà không chuyển về, đến khi sự cố thật thì kẹt ở trung tâm dự phòng.

@NV: Phòng nghiệp vụ cần biết trong thời gian diễn tập thì các quỹ có giao dịch tại quầy được không, vì hệ thống lõi cũng phục vụ giao dịch tại quầy.

@BE: Diễn tập vào đêm thứ Bảy từ 22 giờ đến 4 giờ sáng, các quỹ không mở cửa, chỉ ảnh hưởng đến dịch vụ ATM và SMS banking, sẽ có thông báo trước cho khách 3 ngày.

@RR: Phòng rủi ro xin nói thêm về nội dung hồ sơ. Ngoài đánh giá an toàn thông tin và phương án dự phòng thảm họa, hồ sơ còn gồm: quy trình nội bộ về mở tài khoản điện tử, quy trình cho vay trực tuyến, quy định về quản lý rủi ro gian lận, phương án bảo vệ dữ liệu cá nhân khách hàng đã đánh giá tác động theo Nghị định về bảo vệ dữ liệu cá nhân, hợp đồng với các bên cung cấp dịch vụ như nhà cung cấp eKYC, Napas, nhà mạng gửi SMS. Phòng đã hoàn thành khoảng 70% bộ hồ sơ, phần còn thiếu chủ yếu là những phần phụ thuộc kết quả kỹ thuật.

@BE: Báo cáo đánh giá tác động xử lý dữ liệu cá nhân thì cũng phải gửi Cục An ninh mạng và phòng chống tội phạm sử dụng công nghệ cao của Bộ Công an trong vòng 60 ngày kể từ khi bắt đầu xử lý dữ liệu, nhóm kỹ thuật đã phối hợp với phòng rủi ro chuẩn bị phần mô tả kỹ thuật.

@NV: Phòng nghiệp vụ xin hỏi thêm, hồ sơ gửi Ngân hàng Nhà nước có cần ý kiến của các quỹ thành viên không, vì về pháp lý mỗi quỹ tín dụng là một pháp nhân riêng?

@RR: Đúng vậy, đây là điểm phức tạp. Ứng dụng là của Ngân hàng Hợp tác xã làm đầu mối liên kết cung cấp dịch vụ cho các quỹ, nhưng tài khoản thanh toán của khách mở tại từng quỹ. Hồ sơ phải có thỏa thuận cung cấp dịch vụ giữa đơn vị đầu mối và từng quỹ tham gia, có nghị quyết của Hội đồng quản trị từng quỹ đồng ý tham gia. 8 quỹ thí điểm đã có nghị quyết, các quỹ mở rộng sau thì phải bổ sung.

@GD: Như vậy khi mở rộng ra các quỹ khác thì mỗi quỹ phải có nghị quyết. Anh Đông lưu ý khi lên kế hoạch mở rộng.

@NV #a_mauNQ: Dạ vâng, phòng nghiệp vụ sẽ chuẩn bị mẫu nghị quyết và thỏa thuận để các quỹ mở rộng làm sẵn.

@PM #d_hoso: Chốt: thuê đơn vị được cấp phép đánh giá an toàn thông tin cấp độ 4; diễn tập chuyển đổi sang trung tâm dữ liệu dự phòng có biên bản, thời gian khôi phục dưới 4 giờ; hoàn thiện hồ sơ gửi Ngân hàng Nhà nước trước ngày 15 tháng 12.

## TOPIC | Thống nhất phân công công việc trước ngày ra mắt ứng dụng ngân hàng số | Chốt phân công cuối: 10 đầu việc cho các trưởng nhóm với hạn cụ thể trước ngày ra mắt 15/1; ra mắt chính thức vẫn giữ 15/1, thí điểm 8 quỹ trước.

@PM #k_hien: Mục cuối, em đọc lại phân công để mọi người xác nhận, nhanh nhé. Ra mắt chính thức vẫn giữ ngày 15 tháng 1, thí điểm 8 quỹ trước rồi mở rộng.

@QA: Em xin báo cáo nhanh tình trạng lỗi trước khi đọc phân công. Hiện còn 47 lỗi mở, trong đó 3 lỗi mức nghiêm trọng gồm lỗi kiểm tra người thật, lỗi treo giao dịch Napas, lỗi rò rỉ bộ nhớ dịch vụ thông báo, đều đã có người xử lý như đã báo cáo ở các mục trước; 14 lỗi mức cao chủ yếu là lỗi hiển thị trên một số dòng máy và lỗi xử lý mất kết nối mạng giữa chừng; còn lại 30 lỗi mức trung bình và thấp. Tiêu chí ra mắt của bên kiểm thử là không còn lỗi nghiêm trọng và mức cao, lỗi trung bình không quá 10.

@MB #a_loicao: 14 lỗi mức cao thì phần lớn thuộc nhóm mobile, bọn em ước tính xử lý xong trong 2 tuần nếu có thêm lập trình viên iOS như chị Hiền vừa nói.

@NV: Phòng nghiệp vụ xin nhắc là tháng 1 cũng là thời điểm cận Tết, giao dịch chuyển tiền tăng mạnh, người lao động ở xa gửi tiền về quê. Nếu ra mắt ngày 15 tháng 1 thì chỉ 2 tuần sau là cao điểm Tết, hệ thống phải chịu tải lớn ngay từ đầu, đội vận hành phải chuẩn bị kỹ.

@GD #d_tieuchi: Trước khi đọc phân công, tôi nhắc lại tiêu chí để được ra mắt ngày 15 tháng 1: một là có chứng nhận của Napas; hai là có báo cáo đánh giá an toàn thông tin cấp độ 4 không còn lỗ hổng mức cao; ba là kiểm thử tải 3.000 giao dịch mỗi giây đạt; bốn là đã nộp hồ sơ Ngân hàng Nhà nước và không có ý kiến phản đối; năm là eKYC dùng nhà cung cấp hoặc VNeID đủ điều kiện pháp lý. Thiếu một trong năm tiêu chí thì lùi ra mắt, không có ngoại lệ.

@RR: Phòng rủi ro thống nhất năm tiêu chí này, đề nghị ghi vào biên bản.

@PM #a_c1: Một, đánh giá an toàn thông tin cấp độ 4: chị Mỹ ký hợp đồng với đơn vị đánh giá trong tuần này.

@RR: Chị nhận.

@PM #a_c2: Hai, diễn tập dự phòng thảm họa: anh Lâm chủ trì, làm vào cuối tuần ngày 6 tháng 12.

@BE: Anh nhận.

@PM #a_c3: Ba, hồ sơ gửi Ngân hàng Nhà nước: em tổng hợp, gửi anh Trí ký trước ngày 15 tháng 12.

@PM #a_c4: Bốn, tài liệu hướng dẫn khách hàng và video mở tài khoản: Vy làm, xong trước ngày 1 tháng 1.

@MB: Em nhận ạ.

@PM #a_c5: Năm, đào tạo giao dịch viên 8 quỹ thí điểm: anh Đông tổ chức, hai buổi trực tuyến tuần đầu tháng 1.

@NV: Anh nhận.

@PM #a_c6: Sáu, kịch bản kiểm thử chấp nhận người dùng với 8 quỹ: anh Toản chuẩn bị, chạy từ ngày 20 tháng 12.

@QA: Anh nhận.

@PM #a_c7: Bảy, quy trình xử lý khiếu nại giao dịch treo và lừa đảo cho tổng đài: chị Mỹ ban hành trước ngày 5 tháng 1.

@RR: Nhận.

@PM #a_c8: Tám, nộp ứng dụng lên kho ứng dụng Apple và Google để duyệt: Vy nộp trước ngày 28 tháng 12 để kịp duyệt.

@MB: Vâng.

@PM #a_c9: Chín, phương án truyền thông ra mắt: em làm với phòng truyền thông, trình anh Trí trước ngày 20 tháng 12.

@GD #a_c10: Mười, tôi sẽ trực tiếp làm việc với Ngân hàng Nhà nước chi nhánh khu vực về lịch ra mắt sau khi nộp hồ sơ.

@PM: Vậy là đủ mười đầu việc. Em sẽ gửi biên bản và bảng theo dõi trong chiều nay. Cảm ơn mọi người.

```json gold
{
  "assignments": [
    {"actor": "Vy (Trưởng nhóm Mobile)", "actor_aliases": ["Vy", "em"], "task": "Làm chức năng lưu hồ sơ eKYC dở dang và đặt lịch hoàn tất tại quầy", "deadline": "hai tuần", "turns": ["a_luuhoso"]},
    {"actor": "Vy (Trưởng nhóm Mobile)", "actor_aliases": ["bọn em"], "task": "Bổ sung ràng buộc mỗi thiết bị chỉ đăng ký một tài khoản", "deadline": null, "turns": ["a_thietbi"]},
    {"actor": "Chị Mỹ (Trưởng phòng Quản lý rủi ro và Tuân thủ)", "actor_aliases": [], "task": "Ghi lỗi kiểm tra người thật vào biên bản đánh giá nhà cung cấp eKYC", "deadline": null, "turns": ["d_nguoithat"]},
    {"actor": "Anh Lâm (Kiến trúc sư hệ thống)", "actor_aliases": ["Lâm"], "task": "Hoàn thành toàn bộ kịch bản chứng nhận Napas", "deadline": "trước ngày 20 tháng 12", "turns": ["a_napascert"]},
    {"actor": "Anh Toản (Trưởng nhóm Kiểm thử)", "actor_aliases": ["bên kiểm thử"], "task": "Chạy song song các kịch bản chứng nhận Napas trên môi trường thử", "deadline": null, "turns": ["a_napasqa"]},
    {"actor": "Vy (Trưởng nhóm Mobile)", "actor_aliases": ["bọn em"], "task": "Hiện cảnh báo toàn màn hình khi khách mở ứng dụng chuyển tiền trong lúc đang có cuộc gọi; hướng dẫn tắt tối ưu pin", "deadline": null, "turns": ["a_canhbaocuocgoi"]},
    {"actor": "Anh Toản (Trưởng nhóm Kiểm thử)", "actor_aliases": ["bên kiểm thử"], "task": "Bổ sung kịch bản kiểm thử hai giao dịch đồng thời, không âm số dư", "deadline": null, "turns": ["a_amsodu"]},
    {"actor": "Chị Hiền (Quản lý dự án)", "actor_aliases": ["em"], "task": "Điều động thêm 1 lập trình viên iOS từ dự án khác trong 4 tuần", "deadline": null, "turns": ["a_ios"]},
    {"actor": "Vy (Trưởng nhóm Mobile)", "actor_aliases": [], "task": "Đặt nút khóa tài khoản khẩn cấp ở màn hình đăng nhập", "deadline": null, "turns": ["a_nutkhoa"]},
    {"actor": "Anh Lâm (Kiến trúc sư hệ thống)", "actor_aliases": [], "task": "Thêm luật giám sát gian lận cho sự kiện điều khiển từ xa", "deadline": "khoảng 2 ngày", "turns": ["a_luatgianlan"]},
    {"actor": "Anh Đông (Trưởng phòng Nghiệp vụ tín dụng)", "actor_aliases": ["phòng nghiệp vụ"], "task": "Chuẩn bị mẫu nghị quyết và thỏa thuận cho các quỹ mở rộng", "deadline": null, "turns": ["a_mauNQ"]},
    {"actor": "Vy (Trưởng nhóm Mobile)", "actor_aliases": ["bọn em"], "task": "Xử lý 14 lỗi mức cao của ứng dụng di động", "deadline": "2 tuần", "turns": ["a_loicao"]},
    {"actor": "Anh Lâm (Kiến trúc sư hệ thống)", "actor_aliases": ["em"], "task": "Làm tiến trình tra soát tự động giao dịch treo Napas", "deadline": "trong sprint này", "turns": ["a_trasoat"]},
    {"actor": "Vy (Trưởng nhóm Mobile)", "actor_aliases": ["em"], "task": "Hiển thị tên người nhận trước khi xác nhận chuyển tiền", "deadline": "ba ngày", "turns": ["a_tennguoinhan"]},
    {"actor": "Anh Đông (Trưởng phòng Nghiệp vụ tín dụng)", "actor_aliases": ["Phòng nghiệp vụ"], "task": "Soạn quy trình duyệt vay trực tuyến cho cán bộ tín dụng, gửi chị Mỹ thẩm định", "deadline": "trước ngày 20", "turns": ["a_quytrinh"]},
    {"actor": "Anh Lâm (Kiến trúc sư hệ thống)", "actor_aliases": ["em"], "task": "Làm hồ sơ đăng ký tích hợp VNeID với Trung tâm dữ liệu dân cư", "deadline": "tuần này", "turns": ["a_vneid"]},
    {"actor": "Chị Mỹ (Trưởng phòng Quản lý rủi ro và Tuân thủ)", "actor_aliases": ["chị"], "task": "Làm việc với 2 nhà cung cấp eKYC có tên trong danh sách chính thức, có báo giá và đánh giá", "deadline": "5 ngày", "turns": ["a_ncc"]},
    {"actor": "Anh Lâm (Kiến trúc sư hệ thống)", "actor_aliases": ["em"], "task": "Làm kết nối hệ thống SIMO", "deadline": null, "turns": ["a_simo"]},
    {"actor": "Vy (Trưởng nhóm Mobile)", "actor_aliases": ["em"], "task": "Làm giới hạn chuyển tiền trên thiết bị mới và màn hình cảnh báo", "deadline": "trong sprint này", "turns": ["a_thietbimoi"]},
    {"actor": "Anh Lâm (Kiến trúc sư hệ thống)", "actor_aliases": ["em"], "task": "Tách cơ sở dữ liệu chỉ đọc và thêm bộ nhớ đệm số dư", "deadline": "hai tuần", "turns": ["a_tachdb"]},
    {"actor": "Anh Toản (Trưởng nhóm Kiểm thử)", "actor_aliases": ["bên em"], "task": "Chạy lại kiểm thử tải 3.000 giao dịch/giây", "deadline": "tuần thứ ba", "turns": ["a_testlai"]},
    {"actor": "Vy (Trưởng nhóm Mobile)", "actor_aliases": ["em"], "task": "Sửa lỗi rò rỉ bộ nhớ dịch vụ thông báo đẩy, gửi anh Toản kiểm thử lại", "deadline": "trong tuần này", "turns": ["a_romem"]},
    {"actor": "Chị Mỹ (Trưởng phòng Quản lý rủi ro và Tuân thủ)", "actor_aliases": ["chị"], "task": "Gửi dự thảo quy chế quản lý rủi ro CNTT cho thư ký Hội đồng quản trị", "deadline": "trước ngày 5 tháng 12", "turns": ["a_quyche"]},
    {"actor": "Chị Mỹ (Trưởng phòng Quản lý rủi ro và Tuân thủ)", "actor_aliases": ["chị Mỹ", "chị"], "task": "Ký hợp đồng với đơn vị đánh giá an toàn thông tin cấp độ 4", "deadline": "trong tuần này", "turns": ["a_c1"]},
    {"actor": "Anh Lâm (Kiến trúc sư hệ thống)", "actor_aliases": ["anh Lâm", "anh"], "task": "Chủ trì diễn tập dự phòng thảm họa", "deadline": "cuối tuần ngày 6 tháng 12", "turns": ["a_c2"]},
    {"actor": "Chị Hiền (Quản lý dự án)", "actor_aliases": ["em"], "task": "Tổng hợp hồ sơ gửi Ngân hàng Nhà nước, trình anh Trí ký", "deadline": "trước ngày 15 tháng 12", "turns": ["a_c3"]},
    {"actor": "Vy (Trưởng nhóm Mobile)", "actor_aliases": ["Vy"], "task": "Làm tài liệu hướng dẫn khách hàng và video mở tài khoản", "deadline": "trước ngày 1 tháng 1", "turns": ["a_c4"]},
    {"actor": "Anh Đông (Trưởng phòng Nghiệp vụ tín dụng)", "actor_aliases": ["anh Đông", "anh"], "task": "Đào tạo giao dịch viên 8 quỹ thí điểm, hai buổi trực tuyến", "deadline": "tuần đầu tháng 1", "turns": ["a_c5"]},
    {"actor": "Anh Toản (Trưởng nhóm Kiểm thử)", "actor_aliases": ["anh Toản", "anh"], "task": "Chuẩn bị kịch bản kiểm thử chấp nhận người dùng với 8 quỹ", "deadline": "chạy từ ngày 20 tháng 12", "turns": ["a_c6"]},
    {"actor": "Chị Mỹ (Trưởng phòng Quản lý rủi ro và Tuân thủ)", "actor_aliases": ["chị Mỹ"], "task": "Ban hành quy trình xử lý khiếu nại giao dịch treo và lừa đảo cho tổng đài", "deadline": "trước ngày 5 tháng 1", "turns": ["a_c7"]},
    {"actor": "Vy (Trưởng nhóm Mobile)", "actor_aliases": ["Vy"], "task": "Nộp ứng dụng lên Apple App Store và Google Play để duyệt", "deadline": "trước ngày 28 tháng 12", "turns": ["a_c8"]},
    {"actor": "Chị Hiền (Quản lý dự án)", "actor_aliases": ["em"], "task": "Làm phương án truyền thông ra mắt với phòng truyền thông, trình anh Trí", "deadline": "trước ngày 20 tháng 12", "turns": ["a_c9"]},
    {"actor": "Ông Trí (Phó Tổng giám đốc phụ trách công nghệ)", "actor_aliases": ["tôi"], "task": "Làm việc với Ngân hàng Nhà nước chi nhánh khu vực về lịch ra mắt", "deadline": "sau khi nộp hồ sơ", "turns": ["a_c10"]}
  ],
  "decisions": [
    {"text": "eKYC thất bại thì lưu hồ sơ và hoàn tất tại quầy bằng thiết bị đọc chip; tài khoản mở hoàn toàn trực tuyến hạn mức 100 triệu/tháng", "turns": ["d_ekyc1"]},
    {"text": "Hiển thị tên người nhận trước khi xác nhận; giao dịch treo quá 60 giây tự tra soát, thất bại hoàn tiền trong 15 phút; miễn phí chuyển tiền năm đầu; chỉ hỗ trợ QR chuẩn VietQR, báo lỗi rõ ràng", "turns": ["d_napas"]},
    {"text": "Vay trực tuyến chỉ cho thành viên trên 12 tháng; đến 20 triệu duyệt tự động, trên 20 triệu cán bộ tín dụng xác minh; chỉ dùng dữ liệu nội bộ và CIC", "turns": ["d_vay"]},
    {"text": "Không tiếp tục dùng nhà cung cấp eKYC hiện tại; luồng chính xác thực qua VNeID, dự phòng là nhà cung cấp mới có tên trong danh sách chính thức của Bộ Công an", "turns": ["d_ekyc2"]},
    {"text": "Thông báo qua ứng dụng miễn phí; SMS thu phí theo đăng ký (miễn phí cho khách trên 60 tuổi); kết nối SIMO cảnh báo tài khoản nghi ngờ; thiết bị mới giới hạn 10 triệu trong 24 giờ đầu; tích hợp phát hiện ứng dụng điều khiển từ xa; mục cảnh báo lừa đảo và nút khóa tài khoản khẩn cấp", "turns": ["d_thongbao"]},
    {"text": "Tách cơ sở dữ liệu chỉ đọc, thêm bộ nhớ đệm, kiểm thử lại 3.000 giao dịch/giây, CPU cơ sở dữ liệu lõi dưới 70%", "turns": ["d_hieunang"]},
    {"text": "Thuê đơn vị đánh giá an toàn thông tin cấp độ 4; diễn tập dự phòng thảm họa, khôi phục dưới 4 giờ; nộp hồ sơ NHNN trước 15/12", "turns": ["d_hoso"]},
    {"text": "Giữ ngày ra mắt chính thức 15/1, thí điểm 8 quỹ trước", "turns": ["k_hien"]},
    {"text": "Ra mắt chỉ khi đủ 5 tiêu chí: chứng nhận Napas, đánh giá ATTT cấp độ 4 không còn lỗ hổng cao, kiểm thử tải 3.000 giao dịch/giây đạt, đã nộp hồ sơ NHNN, eKYC đủ điều kiện pháp lý; thiếu thì lùi ra mắt", "turns": ["d_tieuchi"]},
    {"text": "Vay trực tuyến: nhắc trước 3 ngày, trích nợ tự động, quá hạn 10 ngày cán bộ quỹ gọi điện; không thuê đơn vị đòi nợ bên ngoài", "turns": ["d_thuno"]},
    {"text": "Không mở eKYC luồng hiện tại cho khách thật cho đến khi khắc phục lỗi kiểm tra người thật", "turns": ["d_nguoithat"]},
    {"text": "Mỗi thiết bị chỉ đăng ký tối đa một tài khoản chính chủ", "turns": ["k_my6"]},
    {"text": "Hạn mức chuyển tiền cá nhân 200 triệu/ngày; hộ kinh doanh đăng ký một lần tại quầy, tối đa 1 tỷ/ngày", "turns": ["d_hanmuc"]},
    {"text": "Thí điểm vay trực tuyến tổng dư nợ tối đa 50 tỷ; quá hạn trên 30 ngày vượt 5% thì tạm dừng giải ngân mới; lãi suất tạm như vay tại quầy, Hội đồng quản trị quyết định sau", "turns": ["d_thidiemvay"]},
    {"text": "Nếu đến 5/1 VNeID chưa sẵn sàng thì ra mắt với nhà cung cấp eKYC mới làm luồng chính", "turns": ["d_vneid_fallback"]}
  ],
  "negatives": [
    {"type": "superseded_decision", "text": "Tiếp tục dùng nhà cung cấp eKYC hiện tại (đã đổi sang VNeID + nhà cung cấp mới)", "turns": ["d_ekyc1"]},
    {"type": "hedged_proposal", "text": "Chuyển tiền định kỳ (để giai đoạn 2)", "turns": ["n_dinhky"]},
    {"type": "hedged_proposal", "text": "Đóng băng tính năng giao diện chuyển tiền từ 15/12 (kiểm thử đề nghị)", "turns": ["n_dongbang"]},
    {"type": "hedged_proposal", "text": "Bảng giám sát hiệu năng thời gian thực và trực 24/7 tháng đầu (đề nghị, chưa chốt)", "turns": ["n_giamsat"]},
    {"type": "hedged_proposal", "text": "Thu phí SMS 8.000 đồng/tháng (đề xuất, chưa chốt mức)", "turns": ["n_phisms"]},
    {"type": "hedged_proposal", "text": "Lãi suất vay trực tuyến cao hơn vay tại quầy 1-2 điểm % (chờ Hội đồng quản trị)", "turns": ["n_laisuat"]},
    {"type": "hedged_proposal", "text": "Dùng dữ liệu mạng xã hội, danh bạ để chấm điểm tín dụng", "turns": ["n_mxh", "n_mxh2"]}
  ],
  "key_points": [
    {"speaker": "Vy (Trưởng nhóm Mobile)", "point": "eKYC thử nghiệm 1.200 khách đạt 81%; thất bại do điện thoại không NFC, người lớn tuổi, lỗi kết nối", "turns": ["k_vy1"]},
    {"speaker": "Chị Mỹ (Trưởng phòng Quản lý rủi ro và Tuân thủ)", "point": "Tài khoản mở trực tuyến hạn mức 100 triệu/tháng; bắt buộc đối chiếu sinh trắc với chip", "turns": ["k_my1"]},
    {"speaker": "Vy (Trưởng nhóm Mobile)", "point": "Mở tài khoản trung bình 6 phút 40 giây; 11% bỏ ở bước đọc chip NFC", "turns": ["k_vy3"]},
    {"speaker": "Chị Mỹ (Trưởng phòng Quản lý rủi ro và Tuân thủ)", "point": "Phải chống mở tài khoản hộ, mua bán tài khoản; mỗi thiết bị một tài khoản chính chủ", "turns": ["k_my6"]},
    {"speaker": "Anh Lâm (Kiến trúc sư hệ thống)", "point": "Đã đạt 118/140 kịch bản chứng nhận Napas, Napas cần 2 tuần thẩm định", "turns": ["k_lam2"]},
    {"speaker": "Anh Đông (Trưởng phòng Nghiệp vụ tín dụng)", "point": "Nợ xấu vay tiêu dùng không bảo đảm 2,8%; vay trực tuyến thường cao hơn 1,5-2 lần", "turns": ["k_dong2"]},
    {"speaker": "Chị Mỹ (Trưởng phòng Quản lý rủi ro và Tuân thủ)", "point": "Chấm dứt hợp đồng eKYC cũ không phải bồi thường; kết nối VNeID mất 15-20 ngày làm việc", "turns": ["k_my7"]},
    {"speaker": "Anh Đông (Trưởng phòng Nghiệp vụ tín dụng)", "point": "23 vụ thành viên bị lừa khoảng 1,7 tỷ, chủ yếu giả danh cán bộ quỹ", "turns": ["k_dong3"]},
    {"speaker": "Anh Toản (Trưởng nhóm Kiểm thử)", "point": "Đỉnh dự báo khoảng 1.300 giao dịch/giây; 2.000 là hệ số an toàn 1,5", "turns": ["k_toan2"]},
    {"speaker": "Chị Mỹ (Trưởng phòng Quản lý rủi ro và Tuân thủ)", "point": "Đánh giá cấp độ 4 khoảng 350-500 triệu, 3 tuần, kịp hạn nếu ký trong tuần", "turns": ["k_my8"]},
    {"speaker": "Anh Lâm (Kiến trúc sư hệ thống)", "point": "Chuyển tiền Napas 3,2 giây; 0,4% giao dịch bị treo chờ đối soát cuối ngày", "turns": ["k_lam1"]},
    {"speaker": "Anh Đông (Trưởng phòng Nghiệp vụ tín dụng)", "point": "Vay trực tuyến tối đa 50 triệu; chấm điểm duyệt tự động 42%, từ chối 21%", "turns": ["k_dong"]},
    {"speaker": "Chị Mỹ (Trưởng phòng Quản lý rủi ro và Tuân thủ)", "point": "Chỉ cho thành viên trên 12 tháng; khoản trên 20 triệu phải cán bộ duyệt", "turns": ["k_my2"]},
    {"speaker": "Chị Mỹ (Trưởng phòng Quản lý rủi ro và Tuân thủ)", "point": "Nhà cung cấp eKYC tăng phí 60% và chưa có tên trong danh sách kết nối chính thức của Bộ Công an", "turns": ["k_my3"]},
    {"speaker": "Vy (Trưởng nhóm Mobile)", "point": "Thông báo đẩy dưới 2 giây; SMS tốn 1,1 tỷ/năm; chưa có cảnh báo tài khoản lừa đảo", "turns": ["k_vy2"]},
    {"speaker": "Chị Mỹ (Trưởng phòng Quản lý rủi ro và Tuân thủ)", "point": "Kết nối SIMO cảnh báo tài khoản nghi ngờ; giới hạn chuyển tiền trên thiết bị mới", "turns": ["k_my4"]},
    {"speaker": "Anh Toản (Trưởng nhóm Kiểm thử)", "point": "Kiểm thử 2.000 giao dịch/giây đạt 1,4 giây nhưng CPU cơ sở dữ liệu lõi 92%", "turns": ["k_toan"]},
    {"speaker": "Chị Mỹ (Trưởng phòng Quản lý rủi ro và Tuân thủ)", "point": "Hồ sơ NHNN thiếu đánh giá ATTT cấp độ 4 và phương án dự phòng thảm họa", "turns": ["k_my5"]}
  ]
}
```
