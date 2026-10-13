```json meta
{
  "meeting_id": "synth_017",
  "title": "Họp rà soát sprint dự án Hệ thống thông tin bệnh viện đa khoa tỉnh Quảng Bắc",
  "meeting_type": "software_project",
  "length_bucket": "M",
  "tags": ["many_topics_medium"],
  "speakers": {
    "PM": "Anh Long (Quản lý dự án)",
    "BV": "BS. Hạnh (Phó Giám đốc bệnh viện)",
    "BE": "Quân (Trưởng nhóm Backend)",
    "FE": "Linh (Trưởng nhóm Frontend)",
    "DT": "Chị Yến (Trưởng phòng Công nghệ thông tin bệnh viện)",
    "QA": "Tâm (Kiểm thử)"
  }
}
```

## TOPIC | Xây dựng chức năng đặt lịch khám trực tuyến | Chức năng đặt lịch khám qua ứng dụng đã chạy thử ở 4 chuyên khoa, tỷ lệ bệnh nhân đặt nhưng không đến 23%; thống nhất yêu cầu xác nhận lại trước 24 giờ và tự hủy nếu không xác nhận, mở rộng ra 12 chuyên khoa từ tháng sau.

@PM: Chào bác sĩ Hạnh, chào chị Yến và cả nhóm. Sprint này mình có sáu hạng mục cần rà, em đi lần lượt cho nhanh: đặt lịch khám, bệnh án điện tử, kết nối máy xét nghiệm, thanh toán không tiền mặt, cổng giám định bảo hiểm và cuối cùng là đào tạo người dùng. Linh nói phần đặt lịch khám trước.

@FE #k_linh1: Dạ. Chức năng đặt lịch khám trên ứng dụng di động và trên web đã chạy thử ba tuần ở bốn chuyên khoa là Nội tổng hợp, Tai mũi họng, Da liễu và Sản. Bệnh nhân chọn chuyên khoa, chọn bác sĩ hoặc để hệ thống tự xếp, chọn khung giờ 30 phút, nhận mã đặt lịch, đến bệnh viện quét mã ở ki-ốt là vào thẳng hàng đợi khám không cần lấy số. Ba tuần có khoảng 2.140 lượt đặt. Phản hồi của bệnh nhân nhìn chung tốt, thời gian chờ trung bình của nhóm đặt trước là 18 phút so với 65 phút của nhóm lấy số trực tiếp. Vấn đề lớn nhất là tỷ lệ đặt rồi không đến là 23%, tức là gần một phần tư khung giờ bị bỏ trống, bác sĩ ngồi chờ trong khi ngoài sảnh vẫn đông.

@BV: Con số 23% là cao quá. Các bác sĩ khoa Da liễu đã phản ánh với tôi là buổi sáng thứ Hai có tới 8 ca đặt không đến. Các anh có phương án gì không?

@FE: Dạ, nhóm đề xuất ba việc. Một là 24 giờ trước giờ khám thì gửi tin nhắn và thông báo ứng dụng yêu cầu bệnh nhân bấm xác nhận, nếu đến 6 giờ trước giờ khám vẫn không xác nhận thì hệ thống tự hủy và nhả khung giờ cho người khác. Hai là cho phép đặt quá số khung giờ khoảng 10% ở các khung đầu buổi, giống hãng bay bán vượt chỗ. Ba là bệnh nhân không đến ba lần thì tạm khóa đặt lịch trực tuyến 30 ngày.

@BV #k_hanh1: Cái thứ nhất thì đồng ý. Cái đặt vượt 10% thì tôi không đồng ý, bệnh viện không phải hãng bay, nếu cả mười người đến hết thì bệnh nhân chờ lâu lại phàn nàn là đặt lịch rồi vẫn phải chờ, mất uy tín. Còn khóa 30 ngày thì phải cẩn thận, người cao tuổi nhiều khi con cháu đặt hộ rồi quên, khóa thì họ lại xuống xếp hàng, nhưng tôi thấy có thể khóa được, miễn là có thông báo rõ ràng và tổng đài có thể mở khóa khi bệnh nhân gọi lên giải thích.

@PM #d_datlich: Vậy em chốt: áp dụng xác nhận lại trước 24 giờ và tự hủy nếu đến 6 giờ trước giờ khám chưa xác nhận; không đặt vượt khung giờ; khóa đặt trực tuyến 30 ngày nếu không đến ba lần, tổng đài được quyền mở khóa. Mở rộng ra 12 chuyên khoa từ ngày 1 tháng sau. Linh làm phần xác nhận và tự hủy nhé.

@FE #a_xacnhan: Dạ, em làm trong sprint này, khoảng 5 ngày công, xong trước thứ Sáu tuần sau.

@DT #a_tongdai: Phần quy trình mở khóa ở tổng đài thì phòng tôi soạn hướng dẫn cho tổng đài viên.

## TOPIC | Xây dựng chức năng bệnh án điện tử nội trú | Bệnh án điện tử nội trú đã triển khai ở khoa Nội và khoa Ngoại; bác sĩ phàn nàn nhập liệu chậm; thống nhất thêm mẫu câu, nhập liệu bằng giọng nói để sau, ký số bằng sim ký số thay USB token.

@PM: Hạng mục thứ hai là bệnh án điện tử nội trú. Quân nói nhé.

@BE #k_quan1: Dạ. Bệnh án điện tử nội trú đã chạy chính thức ở khoa Nội tổng hợp và khoa Ngoại chấn thương được hai tháng, khoảng 1.600 bệnh án. Các phần đã có là phiếu khám vào viện, tờ điều trị hằng ngày, phiếu chăm sóc điều dưỡng, chỉ định cận lâm sàng, y lệnh thuốc và tóm tắt ra viện. Bác sĩ ký số từng tờ điều trị bằng USB token. Theo Thông tư 46 của Bộ Y tế thì để bỏ hẳn bệnh án giấy, bệnh viện phải đáp ứng đủ các tiêu chí và tự đánh giá, Sở Y tế công nhận. Hiện mình đang chạy song song cả giấy và điện tử.

@BV #k_hanh2: Tôi nói thẳng là các bác sĩ đang rất mệt vì chạy song song, viết tay một lần rồi lại gõ máy một lần. Bác sĩ khoa Ngoại phản ánh gõ tờ điều trị cho 30 bệnh nhân mất cả buổi sáng. Còn cái USB token thì cứ rút ra cắm vào, quên ở nhà là không ký được, có hôm khoa Nội có hai bác sĩ trực quên token. Phải làm sao cho bác sĩ nhập nhanh hơn.

@FE: Dạ, về nhập liệu nhóm có hai hướng. Một là thêm mẫu câu và bộ mẫu theo bệnh, ví dụ bệnh nhân sau mổ kết hợp xương ngày thứ hai thì có sẵn mẫu diễn biến, bác sĩ chỉ sửa chỗ khác. Hai là sao chép tờ điều trị ngày hôm trước làm nền rồi sửa. Hai việc này khoảng hai tuần.

@QA #n_giongnoi: Em thấy hiện nay có mấy dịch vụ nhận dạng giọng nói tiếng Việt khá tốt, hay mình cho bác sĩ đọc tờ điều trị rồi tự chuyển thành chữ, như thế còn nhanh hơn gõ.

@DT #n_giongnoi2: Nhận dạng giọng nói thì nghe hấp dẫn nhưng thuật ngữ y khoa, tên thuốc, nhiều chỗ bác sĩ đọc tiếng Anh tiếng Pháp lẫn lộn, độ chính xác chưa chắc đã đủ. Mà dữ liệu bệnh án gửi lên dịch vụ đám mây bên ngoài thì phải đánh giá bảo mật. Cái này để nghiên cứu sau, sprint này chưa làm.

@DT: Về ký số thì tôi đề nghị chuyển sang sim ký số hoặc ký số từ xa trên điện thoại, nhà mạng bây giờ đều có dịch vụ, bác sĩ xác nhận bằng mã PIN trên điện thoại, không phải cắm token. Chi phí khoảng 300.000 đồng một bác sĩ một năm.

@BV: Cái đó được. Bệnh viện chi được.

@PM #d_benhan: Em chốt: thêm bộ mẫu câu theo bệnh và chức năng sao chép tờ điều trị ngày trước, làm trong hai sprint tới; chuyển ký số sang ký số từ xa trên điện thoại cho bác sĩ hai khoa đang chạy; nhận dạng giọng nói chưa làm. Quân phụ trách tích hợp ký số từ xa.

@BE #a_kyso: Dạ, em làm việc với nhà cung cấp dịch vụ ký số, tích hợp xong trước cuối tháng.

@DT #a_muasim: Việc mua sim ký số cho khoảng 45 bác sĩ hai khoa thì phòng tôi làm tờ trình mua sắm.

## TOPIC | Kết nối máy xét nghiệm và trả kết quả cận lâm sàng tự động | Đã kết nối 9/14 máy xét nghiệm qua chuẩn HL7; 5 máy đời cũ chưa hỗ trợ; thống nhất mua bộ chuyển đổi cho 3 máy, 2 máy sắp thanh lý vẫn nhập tay; bật cảnh báo giá trị nguy hiểm gửi bác sĩ điều trị.

@PM: Tiếp theo là kết nối máy xét nghiệm. Quân nói tiếp.

@BE #k_quan2: Dạ. Khoa Xét nghiệm có 14 máy, đến nay đã kết nối được 9 máy qua chuẩn HL7 và ASTM, kết quả tự động đổ về hệ thống, bác sĩ xem ngay trên bệnh án, không phải chờ giấy. Thời gian trả kết quả sinh hóa trung bình giảm từ 95 phút xuống còn 52 phút. Còn 5 máy chưa kết nối được, gồm 3 máy huyết học đời 2012 chỉ có cổng nối tiếp RS232 và 2 máy đông máu rất cũ không có cổng xuất dữ liệu. Với 3 máy huyết học thì có thể mua bộ chuyển đổi cổng nối tiếp sang mạng, khoảng 12 triệu một bộ. Với 2 máy đông máu thì không kết nối được.

@DT: 2 máy đông máu đó trong kế hoạch thanh lý năm sau rồi, bệnh viện đang làm hồ sơ mua máy mới. Không nên đầu tư thêm.

@BV #k_hanh3: Tôi muốn bổ sung một yêu cầu rất quan trọng. Khi có kết quả nguy hiểm, ví dụ kali máu trên 6,5 hay dưới 2,5, hay tiểu cầu dưới 20.000, thì hệ thống phải cảnh báo ngay cho bác sĩ điều trị, không chờ bác sĩ mở bệnh án ra xem. Hiện nay khoa Xét nghiệm vẫn phải gọi điện thoại, có khi gọi không được.

@BE: Dạ, kỹ thuật làm được. Mình cấu hình ngưỡng giá trị nguy hiểm cho từng chỉ số, khi có kết quả vượt ngưỡng thì đẩy cảnh báo lên màn hình trạm điều dưỡng của khoa và gửi thông báo ứng dụng cho bác sĩ điều trị, bác sĩ phải bấm xác nhận đã nhận. Nếu sau 15 phút không ai xác nhận thì báo cho trưởng khoa. Nhưng danh sách ngưỡng thì cần khoa Xét nghiệm cung cấp.

@BV #a_nguong: Danh sách ngưỡng giá trị nguy hiểm thì tôi giao khoa Xét nghiệm, bác sĩ Thành trưởng khoa sẽ gửi trong tuần này.

@PM #d_xetnghiem: Em chốt: mua 3 bộ chuyển đổi cho 3 máy huyết học; 2 máy đông máu sắp thanh lý vẫn nhập tay; làm cảnh báo giá trị nguy hiểm có xác nhận và leo thang lên trưởng khoa sau 15 phút.

@DT #a_chuyendoi: Phòng tôi mua 3 bộ chuyển đổi, dự kiến hai tuần có hàng.

@BE #a_canhbao: Còn cảnh báo giá trị nguy hiểm em làm ngay sau khi nhận danh sách ngưỡng, khoảng một tuần.

## TOPIC | Triển khai thanh toán viện phí không tiền mặt | Thanh toán bằng mã QR tại quầy đã chạy, chiếm 31% giao dịch; lỗi đối soát lệch do ngân hàng trả kết quả chậm; thống nhất đối soát tự động theo mã giao dịch và mở thêm thanh toán tạm ứng nội trú qua ứng dụng.

@PM: Hạng mục thứ tư là thanh toán không tiền mặt. Tâm bên kiểm thử theo dõi phần này, Tâm nói nhé.

@QA #k_tam1: Dạ. Thanh toán viện phí bằng mã QR tại quầy thu ngân đã chạy hai tháng, hiện chiếm khoảng 31% số giao dịch ngoại trú. Quy trình là thu ngân in phiếu có mã QR động chứa số tiền và mã hồ sơ, bệnh nhân quét bằng ứng dụng ngân hàng, ngân hàng báo về hệ thống thì phiếu tự chuyển trạng thái đã thanh toán. Vấn đề là có khoảng 1,5% giao dịch bị lệch, tức là bệnh nhân đã chuyển tiền nhưng hệ thống chưa nhận được thông báo của ngân hàng, thu ngân phải bảo bệnh nhân chờ hoặc chụp màn hình, rồi cuối ngày kế toán đối soát bằng tay với sao kê. Tháng trước có 2 trường hợp bệnh nhân bị thu hai lần, một lần chuyển khoản một lần tiền mặt, phải hoàn tiền.

@BE: Nguyên nhân là ngân hàng gửi thông báo qua webhook, khi hệ thống ngân hàng tải cao thì gửi chậm có khi 10 đến 20 phút, có khi mất hẳn. Em đề xuất thêm một tiến trình chủ động hỏi lại ngân hàng theo mã giao dịch sau 2 phút nếu chưa nhận được thông báo, và cuối ngày tự động đối soát toàn bộ với sao kê điện tử của ngân hàng theo mã giao dịch, chỉ những giao dịch lệch mới phải xử lý tay.

@BV: Còn tạm ứng nội trú thì sao? Người nhà bệnh nhân nội trú phải xuống quầy nộp tạm ứng, nhiều khi nửa đêm phải đi tìm cây ATM.

@FE #k_linh2: Dạ, ứng dụng có thể thêm chức năng tạm ứng nội trú, người nhà xem số dư tạm ứng và chi phí đã phát sinh theo ngày, nạp thêm tạm ứng qua mã QR ngay trên ứng dụng. Khoảng hai sprint.

@PM #d_thanhtoan: Em chốt: làm tiến trình hỏi lại ngân hàng sau 2 phút và đối soát tự động cuối ngày theo mã giao dịch; thêm chức năng tạm ứng nội trú qua ứng dụng ở sprint sau nữa. Quân làm phần đối soát.

@BE #a_doisoat: Dạ, phần đối soát tự động em làm trong sprint này.

@QA #a_hoantien: Em rà lại toàn bộ giao dịch tháng trước để xem còn trường hợp thu trùng nào nữa không, gửi kế toán trước thứ Tư.

## TOPIC | Kết nối cổng giám định bảo hiểm y tế | Tỷ lệ hồ sơ bảo hiểm bị từ chối 4,2% chủ yếu do sai mã dịch vụ kỹ thuật và thiếu chứng chỉ hành nghề; thống nhất kiểm tra hồ sơ trước khi đẩy lên cổng và cập nhật danh mục theo bảng mã mới; đề xuất đẩy dữ liệu theo thời gian thực bị gạt.

@PM: Hạng mục thứ năm là cổng giám định bảo hiểm y tế. Chị Yến nói giúp em.

@DT #k_yen: Vâng. Hiện nay hệ thống đẩy dữ liệu khám chữa bệnh lên cổng giám định của Bảo hiểm xã hội theo định dạng XML của Quyết định 4750, mỗi ngày đẩy một lần vào buổi tối. Tháng trước tỷ lệ hồ sơ bị từ chối thanh toán hoặc phải giải trình là 4,2%, tương đương khoảng 380 triệu đồng chưa được thanh toán. Nguyên nhân chính là ba loại: một là mã dịch vụ kỹ thuật không khớp với bảng mã mới Bộ Y tế ban hành từ tháng 7, khoảng 45% lỗi; hai là bác sĩ chỉ định dịch vụ ngoài phạm vi chứng chỉ hành nghề, khoảng 30%; ba là thuốc kê vượt số ngày quy định hoặc không đúng chỉ định trong tờ hướng dẫn, khoảng 25%.

@BE: Về kỹ thuật thì mình có thể thêm bước kiểm tra trước khi đẩy, tức là trước khi gửi hồ sơ, hệ thống tự chạy bộ luật: mã dịch vụ có trong danh mục mới không, bác sĩ chỉ định có chứng chỉ hành nghề phù hợp không, số ngày thuốc có vượt không. Hồ sơ nào lỗi thì hiện cảnh báo cho phòng Kế hoạch tổng hợp sửa trước. Bảng ánh xạ mã cũ sang mã mới thì em cần phòng Kế hoạch tổng hợp xác nhận.

@BV: Kiểm tra lúc đẩy thì muộn rồi, bệnh nhân đã ra viện. Tôi muốn chặn ngay từ lúc bác sĩ chỉ định, bác sĩ không có phạm vi thì không cho chỉ định.

@FE: Dạ, việc chặn khi chỉ định thì làm được với chứng chỉ hành nghề, vì dữ liệu phạm vi hành nghề đã có. Còn kiểm tra thuốc thì bộ luật phức tạp hơn, giai đoạn này mình làm cảnh báo chứ chưa chặn.

@QA #n_realtime: Em có đọc là cổng giám định có hỗ trợ đẩy dữ liệu ngay khi kết thúc lượt khám, hay mình chuyển sang đẩy theo thời gian thực luôn, phát hiện lỗi sớm hơn.

@DT #n_realtime2: Không nên lúc này. Đẩy theo thời gian thực thì hồ sơ chưa hoàn thiện cũng lên, sai sót lại nhiều hơn, mà sửa hồ sơ đã đẩy thì thủ tục rắc rối. Giữ đẩy cuối ngày, làm bước kiểm tra trước đã.

@PM #d_baohiem: Em chốt: cập nhật danh mục theo bảng mã dịch vụ kỹ thuật mới; chặn chỉ định ngoài phạm vi chứng chỉ hành nghề ngay khi bác sĩ chỉ định; thêm bước kiểm tra hồ sơ trước khi đẩy lên cổng giám định; vẫn đẩy dữ liệu cuối ngày.

@DT #a_anhxa: Bảng ánh xạ mã cũ sang mã mới thì tôi làm với phòng Kế hoạch tổng hợp, gửi Quân trước ngày 20.

@BE #a_kiemtra: Bước kiểm tra trước khi đẩy và chặn chỉ định thì em làm luôn sau khi có bảng ánh xạ.

## TOPIC | Thống nhất kế hoạch đào tạo người dùng và lịch sprint tới | Thống nhất đào tạo bệnh án điện tử cho 6 khoa mới theo mô hình người dùng nòng cốt, mỗi khoa 2 bác sĩ và 2 điều dưỡng; lịch triển khai thêm khoa Nhi và khoa Sản từ tháng sau.

@PM #k_long: Hạng mục cuối là đào tạo và lịch sprint tới. Theo kế hoạch, tháng sau mình mở rộng bệnh án điện tử sang khoa Nhi và khoa Sản, rồi quý tới là thêm bốn khoa nữa. Em đề xuất mô hình người dùng nòng cốt: mỗi khoa chọn 2 bác sĩ và 2 điều dưỡng, nhóm dự án đào tạo kỹ cho những người này trong 3 buổi, sau đó họ hướng dẫn lại trong khoa và là đầu mối hỗ trợ. Tuần đầu đi vào chạy thật thì nhóm dự án cử người trực tại khoa ca ngày.

@BV: Tôi đồng ý mô hình này. Nhưng chọn người nòng cốt phải chọn người trẻ, chịu khó, không chọn trưởng khoa vì trưởng khoa bận lắm. Và đào tạo phải sau giờ giao ban sáng, không lấy giờ khám.

@DT: Phòng Công nghệ thông tin cũng sẽ cử 2 người học cùng để sau này bệnh viện tự hỗ trợ được, không phụ thuộc hoàn toàn vào nhà thầu.

@QA: Em đề nghị có bộ tài liệu hướng dẫn ngắn dạng thẻ, mỗi thao tác một trang có ảnh chụp màn hình, dán ở trạm điều dưỡng, vì bác sĩ không có thời gian đọc tài liệu dài.

@PM #d_daotao: Em chốt: đào tạo theo mô hình người dùng nòng cốt, mỗi khoa 2 bác sĩ, 2 điều dưỡng, 3 buổi sau giao ban sáng; phòng Công nghệ thông tin cử 2 người học cùng; tuần đầu chạy thật có người của dự án trực ca ngày; khoa Nhi và khoa Sản bắt đầu từ ngày 1 tháng sau.

@BV #a_danhsach: Danh sách người nòng cốt của khoa Nhi và khoa Sản thì tôi chỉ đạo hai khoa gửi phòng Kế hoạch tổng hợp trước thứ Hai tuần sau.

@QA #a_the: Bộ thẻ hướng dẫn em làm, gửi bác sĩ Hạnh duyệt trước khi in.

@PM #a_lich: Em sẽ lên lịch đào tạo chi tiết và gửi cả nhóm sau khi có danh sách. Cảm ơn mọi người, sprint này nhiều việc, cố gắng nhé.

```json gold
{
  "assignments": [
    {"actor": "Linh (Trưởng nhóm Frontend)", "actor_aliases": ["Linh", "em"], "task": "Làm chức năng xác nhận lại trước 24 giờ và tự hủy lịch khám", "deadline": "trước thứ Sáu tuần sau", "turns": ["a_xacnhan"]},
    {"actor": "Chị Yến (Trưởng phòng Công nghệ thông tin bệnh viện)", "actor_aliases": ["phòng tôi"], "task": "Soạn hướng dẫn mở khóa đặt lịch cho tổng đài viên", "deadline": null, "turns": ["a_tongdai"]},
    {"actor": "Quân (Trưởng nhóm Backend)", "actor_aliases": ["Quân", "em"], "task": "Tích hợp ký số từ xa trên điện thoại cho bệnh án điện tử", "deadline": "trước cuối tháng", "turns": ["a_kyso"]},
    {"actor": "Chị Yến (Trưởng phòng Công nghệ thông tin bệnh viện)", "actor_aliases": ["phòng tôi"], "task": "Làm tờ trình mua sim ký số cho khoảng 45 bác sĩ", "deadline": null, "turns": ["a_muasim"]},
    {"actor": "BS. Thành (Trưởng khoa Xét nghiệm)", "actor_aliases": ["bác sĩ Thành", "khoa Xét nghiệm"], "task": "Gửi danh sách ngưỡng giá trị xét nghiệm nguy hiểm", "deadline": "trong tuần này", "turns": ["a_nguong"]},
    {"actor": "Chị Yến (Trưởng phòng Công nghệ thông tin bệnh viện)", "actor_aliases": ["phòng tôi"], "task": "Mua 3 bộ chuyển đổi cổng nối tiếp cho máy huyết học", "deadline": "khoảng hai tuần", "turns": ["a_chuyendoi"]},
    {"actor": "Quân (Trưởng nhóm Backend)", "actor_aliases": ["em"], "task": "Làm cảnh báo giá trị xét nghiệm nguy hiểm có xác nhận và leo thang", "deadline": "khoảng một tuần sau khi nhận danh sách ngưỡng", "turns": ["a_canhbao"]},
    {"actor": "Quân (Trưởng nhóm Backend)", "actor_aliases": ["Quân", "em"], "task": "Làm hỏi lại ngân hàng và đối soát tự động cuối ngày theo mã giao dịch", "deadline": "trong sprint này", "turns": ["a_doisoat"]},
    {"actor": "Tâm (Kiểm thử)", "actor_aliases": ["em"], "task": "Rà soát giao dịch tháng trước tìm trường hợp thu trùng, gửi kế toán", "deadline": "trước thứ Tư", "turns": ["a_hoantien"]},
    {"actor": "Chị Yến (Trưởng phòng Công nghệ thông tin bệnh viện)", "actor_aliases": ["tôi"], "task": "Làm bảng ánh xạ mã dịch vụ kỹ thuật cũ sang mới với phòng Kế hoạch tổng hợp, gửi Quân", "deadline": "trước ngày 20", "turns": ["a_anhxa"]},
    {"actor": "Quân (Trưởng nhóm Backend)", "actor_aliases": ["em"], "task": "Làm bước kiểm tra hồ sơ trước khi đẩy cổng giám định và chặn chỉ định ngoài phạm vi hành nghề", "deadline": "sau khi có bảng ánh xạ", "turns": ["a_kiemtra"]},
    {"actor": "BS. Hạnh (Phó Giám đốc bệnh viện)", "actor_aliases": ["tôi"], "task": "Chỉ đạo khoa Nhi và khoa Sản gửi danh sách người dùng nòng cốt cho phòng Kế hoạch tổng hợp", "deadline": "trước thứ Hai tuần sau", "turns": ["a_danhsach"]},
    {"actor": "Tâm (Kiểm thử)", "actor_aliases": ["em"], "task": "Làm bộ thẻ hướng dẫn thao tác, gửi bác sĩ Hạnh duyệt", "deadline": null, "turns": ["a_the"]},
    {"actor": "Anh Long (Quản lý dự án)", "actor_aliases": ["em"], "task": "Lên lịch đào tạo chi tiết và gửi cả nhóm", "deadline": "sau khi có danh sách", "turns": ["a_lich"]}
  ],
  "decisions": [
    {"text": "Áp dụng xác nhận lại trước 24 giờ, tự hủy nếu 6 giờ trước giờ khám chưa xác nhận; không đặt vượt khung giờ; khóa đặt trực tuyến 30 ngày nếu không đến 3 lần, tổng đài được mở khóa; mở rộng ra 12 chuyên khoa từ tháng sau", "turns": ["d_datlich"]},
    {"text": "Thêm bộ mẫu câu theo bệnh và sao chép tờ điều trị ngày trước; chuyển ký số sang ký số từ xa trên điện thoại", "turns": ["d_benhan"]},
    {"text": "Mua 3 bộ chuyển đổi cho máy huyết học; 2 máy đông máu sắp thanh lý nhập tay; làm cảnh báo giá trị nguy hiểm có leo thang lên trưởng khoa sau 15 phút", "turns": ["d_xetnghiem"]},
    {"text": "Hỏi lại ngân hàng sau 2 phút và đối soát tự động cuối ngày; thêm tạm ứng nội trú qua ứng dụng ở sprint sau nữa", "turns": ["d_thanhtoan"]},
    {"text": "Cập nhật bảng mã DVKT mới; chặn chỉ định ngoài phạm vi chứng chỉ hành nghề; kiểm tra hồ sơ trước khi đẩy; vẫn đẩy dữ liệu cuối ngày", "turns": ["d_baohiem"]},
    {"text": "Đào tạo theo mô hình người dùng nòng cốt (2 bác sĩ, 2 điều dưỡng mỗi khoa, 3 buổi sau giao ban); khoa Nhi và khoa Sản bắt đầu từ ngày 1 tháng sau", "turns": ["d_daotao"]}
  ],
  "negatives": [
    {"type": "rejected_task", "text": "Cho đặt vượt 10% khung giờ khám đầu buổi", "turns": ["k_hanh1"]},
    {"type": "hedged_proposal", "text": "Nhập tờ điều trị bằng nhận dạng giọng nói", "turns": ["n_giongnoi", "n_giongnoi2"]},
    {"type": "hedged_proposal", "text": "Đẩy dữ liệu lên cổng giám định theo thời gian thực", "turns": ["n_realtime", "n_realtime2"]}
  ],
  "key_points": [
    {"speaker": "Linh (Trưởng nhóm Frontend)", "point": "Đặt lịch chạy thử 4 chuyên khoa, 2.140 lượt, thời gian chờ 18 phút so với 65 phút, nhưng 23% đặt không đến", "turns": ["k_linh1"]},
    {"speaker": "BS. Hạnh (Phó Giám đốc bệnh viện)", "point": "Không đồng ý đặt vượt khung giờ; khóa 30 ngày được nếu tổng đài mở khóa được", "turns": ["k_hanh1"]},
    {"speaker": "Quân (Trưởng nhóm Backend)", "point": "Bệnh án điện tử chạy ở 2 khoa, 1.600 bệnh án, đang chạy song song giấy", "turns": ["k_quan1"]},
    {"speaker": "BS. Hạnh (Phó Giám đốc bệnh viện)", "point": "Bác sĩ quá tải vì chạy song song và quên USB token", "turns": ["k_hanh2"]},
    {"speaker": "Quân (Trưởng nhóm Backend)", "point": "Kết nối 9/14 máy xét nghiệm, thời gian trả kết quả sinh hóa giảm từ 95 xuống 52 phút", "turns": ["k_quan2"]},
    {"speaker": "BS. Hạnh (Phó Giám đốc bệnh viện)", "point": "Yêu cầu cảnh báo ngay cho bác sĩ khi có kết quả xét nghiệm nguy hiểm", "turns": ["k_hanh3"]},
    {"speaker": "Tâm (Kiểm thử)", "point": "Thanh toán QR chiếm 31% giao dịch, 1,5% bị lệch, 2 ca thu trùng", "turns": ["k_tam1"]},
    {"speaker": "Chị Yến (Trưởng phòng Công nghệ thông tin bệnh viện)", "point": "Hồ sơ bảo hiểm bị từ chối 4,2% (khoảng 380 triệu), do sai mã DVKT, ngoài phạm vi hành nghề, thuốc vượt quy định", "turns": ["k_yen"]},
    {"speaker": "Anh Long (Quản lý dự án)", "point": "Đề xuất mô hình người dùng nòng cốt để đào tạo, mở rộng khoa Nhi và Sản tháng sau", "turns": ["k_long"]}
  ]
}
```
