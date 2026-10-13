```json meta
{
  "meeting_id": "synth_005",
  "title": "Họp rà soát tiến độ dự án Trung tâm giám sát, điều hành đô thị thông minh (IOC) tỉnh Phú Hòa",
  "meeting_type": "software_project",
  "length_bucket": "L",
  "tags": ["long", "similar_adjacent_topics"],
  "speakers": {
    "SO": "Đ/c Hải (Phó Giám đốc Sở Khoa học và Công nghệ)",
    "PM": "Anh Quý (Giám đốc dự án phía nhà thầu)",
    "BA": "Chị Phượng (Trưởng nhóm phân tích nghiệp vụ)",
    "AI": "Anh Kha (Trưởng nhóm AI và thị giác máy tính)",
    "GIS": "Anh Lợi (Trưởng nhóm GIS)",
    "SEC": "Chị Diễm (Kỹ sư an toàn thông tin)",
    "CA": "Đ/c Thiếu tá Bình (Phòng Tham mưu Công an tỉnh)"
  }
}
```

## TOPIC | Xây dựng chức năng tiếp nhận phản ánh hiện trường qua ứng dụng di động | Ứng dụng Phú Hòa-S đã có 38.000 người dùng, tiếp nhận 4.100 phản ánh/tháng; 31% phản ánh bị chuyển sai đơn vị; thống nhất dùng phân loại tự động theo nội dung và vị trí có cán bộ điều phối duyệt, quy định thời hạn xử lý theo nhóm lĩnh vực.

@SO: Chào các anh chị. Hôm nay rà soát toàn bộ các phân hệ của IOC trước khi chuẩn bị nghiệm thu giai đoạn 1. Có chín nội dung, tôi đề nghị đi lần lượt: phản ánh qua ứng dụng, tích hợp tổng đài 1022, camera giao thông, camera an ninh trật tự, bảng điều khiển kinh tế xã hội, bản đồ quy hoạch, bản đồ hạ tầng ngầm, an toàn thông tin, và cuối cùng là kế hoạch nghiệm thu. Anh Quý điều phối giúp.

@PM: Dạ cảm ơn anh Hải. Nội dung đầu tiên là phân hệ phản ánh hiện trường qua ứng dụng di động. Chị Phượng trình bày.

@BA #k_phuong1: Dạ. Ứng dụng Phú Hòa-S đã phát hành trên hai kho ứng dụng được bốn tháng, đến nay có khoảng 38.000 người dùng đăng ký bằng tài khoản định danh điện tử. Người dân chụp ảnh, quay video, chọn lĩnh vực, hệ thống tự lấy vị trí, gửi lên. Trung bình mỗi tháng tiếp nhận khoảng 4.100 phản ánh, nhiều nhất là trật tự đô thị chiếm 34%, hạ tầng giao thông như ổ gà, đèn đường hỏng chiếm 22%, môi trường, rác thải chiếm 19%, còn lại là an ninh trật tự, đất đai, xây dựng. Tỷ lệ phản ánh được xử lý đúng hạn là 71%, thời gian xử lý trung bình là 4,6 ngày. Vấn đề lớn nhất là 31% phản ánh bị chuyển sai đơn vị lần đầu, phải chuyển lại, có phản ánh bị chuyển qua lại ba bốn lần giữa phường và phòng chuyên môn của huyện, mất cả tuần. Nguyên nhân là người dân chọn lĩnh vực không đúng, ví dụ đèn đường hỏng lại chọn môi trường, và cán bộ điều phối ở Trung tâm chỉ có 4 người, không đọc kịp.

@BA: Thứ hai là thời hạn xử lý hiện nay áp chung 5 ngày làm việc cho mọi phản ánh, trong khi có loại cần xử lý ngay như cây đổ chắn đường, nắp cống mất, có loại phức tạp như xây dựng trái phép thì 5 ngày không đủ, phải kiểm tra, lập biên bản. Thứ ba, người dân phàn nàn kết quả trả lời chung chung, kiểu "đã chuyển đơn vị chức năng xử lý", không có ảnh sau xử lý.

@AI #k_kha1: Về chuyển sai đơn vị thì nhóm AI đã thử nghiệm mô hình phân loại tự động dựa trên nội dung văn bản, ảnh và vị trí. Nội dung và ảnh để đoán lĩnh vực, vị trí để đoán địa bàn và cấp quản lý, ví dụ quốc lộ thì thuộc Sở Xây dựng, đường phường thì thuộc phường. Huấn luyện trên khoảng 12.000 phản ánh đã xử lý, độ chính xác đoán đúng đơn vị xử lý là khoảng 86%, so với 69% hiện nay. Nhưng em không khuyến nghị để mô hình tự chuyển hoàn toàn, vì 14% sai vẫn là nhiều. Em đề xuất mô hình gợi ý đơn vị, cán bộ điều phối chỉ cần bấm duyệt hoặc sửa, như vậy mỗi phản ánh mất khoảng 20 giây thay vì 2 phút.

@SO #k_hai1: Tôi đồng ý mô hình gợi ý, cán bộ duyệt. Về thời hạn thì Sở đã có dự thảo quy chế phân nhóm, nhóm khẩn cấp xử lý trong 24 giờ, nhóm thông thường 5 ngày làm việc, nhóm phức tạp 15 ngày. Còn trả lời thì bắt buộc đơn vị phải đính kèm ảnh sau xử lý mới được đóng phản ánh, không có ảnh thì hệ thống không cho đóng.

@SO: Trước khi chốt, tôi muốn hỏi thêm về số liệu. Trong 29% phản ánh không được xử lý đúng hạn thì phân bố theo đơn vị thế nào? Tôi nghe các phường phàn nàn là phản ánh dồn về phường quá nhiều, trong khi phường không có thẩm quyền xử lý nhiều việc, ví dụ đèn đường thuộc Công ty Chiếu sáng, cây xanh thuộc Công ty Công viên cây xanh.

@BA #k_phuong1b: Dạ thưa anh, theo số liệu bốn tháng thì phường, xã chiếm khoảng 58% số phản ánh được giao, nhưng tỷ lệ đúng hạn chỉ 64%. Các doanh nghiệp công ích như chiếu sáng, cây xanh, môi trường đô thị chỉ chiếm khoảng 17% số phản ánh nhưng tỷ lệ đúng hạn lại cao nhất, khoảng 88%, vì họ có đội xử lý sẵn. Các phòng chuyên môn cấp huyện đúng hạn khoảng 70%. Điểm đáng chú ý là khoảng một phần ba phản ánh giao về phường thực chất phải chuyển tiếp cho doanh nghiệp công ích, phường chỉ đóng vai trò trung gian, mỗi lần trung gian thì mất thêm một đến hai ngày. Nếu mô hình gợi ý chuyển thẳng cho doanh nghiệp công ích thì thời gian xử lý trung bình có thể giảm từ 4,6 ngày xuống khoảng 3 ngày.

@AI: Em bổ sung về mô hình. Để chuyển thẳng được cho doanh nghiệp công ích thì cần bảng phân cấp quản lý chi tiết đến từng tuyến đường, từng công viên, từng cột đèn. Hiện tại mô hình học từ lịch sử chuyển, mà lịch sử thì phần lớn là chuyển về phường trước, nên mô hình cũng sẽ có xu hướng đoán là phường. Bọn em đã thử bổ sung lớp dữ liệu tài sản hạ tầng từ phân hệ bản đồ, mỗi cột đèn có mã và đơn vị quản lý, thì với nhóm đèn đường độ chính xác chọn đúng đơn vị lên được khoảng 93%.

@CA: Phía Công an có một lưu ý. Những phản ánh liên quan đến an ninh trật tự, ví dụ tụ tập đánh bạc, đua xe, bán hàng cấm, thì không nên để hiển thị công khai trên bản đồ phản ánh của ứng dụng như hiện nay, vì đối tượng đọc được sẽ biết bị phản ánh và lẩn tránh, còn người phản ánh có thể bị trả thù. Đề nghị nhóm lĩnh vực an ninh trật tự thì chuyển thẳng cho Công an phường, không công khai nội dung, chỉ thông báo kết quả cho người phản ánh.

@SO #k_hai1b: Ý của Công an là đúng. Hiện nay ứng dụng đang công khai toàn bộ phản ánh trên bản đồ để tăng tính minh bạch, nhưng với an ninh trật tự và với những phản ánh có yếu tố tố cáo cá nhân thì phải ẩn.

@BA: Dạ em ghi nhận. Ngoài ra em xin báo cáo thêm về mức độ hài lòng: sau khi đóng phản ánh, ứng dụng cho người dân đánh giá từ 1 đến 5 sao. Điểm trung bình hiện là 3,4. Những phản ánh bị đánh giá 1 sao thì 70% là do trả lời chung chung hoặc người dân thấy hiện trường chưa được xử lý mà phản ánh đã bị đóng. Hiện tại chưa có cơ chế để người dân mở lại phản ánh.

@SO #n_molai: Nếu người dân đánh giá không hài lòng thì có nên cho tự động mở lại phản ánh không? Tôi chưa quyết ngay được, vì có những trường hợp người dân không hài lòng chỉ vì kết quả không như ý, ví dụ đề nghị xử lý nhà hàng xóm xây lấn nhưng kiểm tra thấy đúng phép. Để Trung tâm điều hành nghiên cứu thêm quy trình, giai đoạn này chưa làm tự động mở lại.

@PM #d_phananh: Vậy chốt phân hệ này: một là triển khai mô hình gợi ý đơn vị xử lý, cán bộ điều phối duyệt; hai là cấu hình thời hạn theo ba nhóm khẩn cấp 24 giờ, thông thường 5 ngày, phức tạp 15 ngày theo quy chế của Sở; ba là bắt buộc ảnh sau xử lý mới đóng phản ánh; bốn là phản ánh lĩnh vực an ninh trật tự và phản ánh có yếu tố tố cáo cá nhân thì không công khai trên bản đồ, chuyển thẳng Công an phường; năm là bổ sung lớp tài sản hạ tầng để chuyển thẳng cho doanh nghiệp công ích.

@AI #a_goiy: Em đưa mô hình gợi ý lên môi trường chính thức trong hai tuần, kèm màn hình duyệt cho cán bộ điều phối.

@BA #a_thoihan: Em cấu hình ba nhóm thời hạn và ràng buộc ảnh sau xử lý ngay sau khi Sở ban hành quy chế.

@SO #a_quyche: Quy chế thì Sở trình Ủy ban ban hành trong tháng này.

## TOPIC | Tích hợp tổng đài 1022 vào hệ thống xử lý phản ánh | Tổng đài 1022 tiếp nhận 2.600 cuộc gọi/tháng nhưng điện thoại viên phải nhập lại thủ công vào hệ thống; thống nhất tích hợp tổng đài IP, tự tạo phiếu, ghi âm gắn vào phản ánh, chuyển giọng nói thành văn bản cho điện thoại viên sửa; đề xuất dùng tổng đài ảo trả lời tự động bị gạt.

@PM: Nội dung thứ hai cũng về phản ánh nhưng qua kênh điện thoại, là tích hợp tổng đài 1022. Chị Phượng nói tiếp.

@BA #k_phuong2: Dạ. Tổng đài 1022 của tỉnh hiện có 6 điện thoại viên, trung bình mỗi tháng tiếp nhận khoảng 2.600 cuộc gọi, trong đó khoảng 1.500 cuộc là phản ánh, còn lại là hỏi thủ tục, hỏi thông tin. Tổng đài là hệ thống riêng do Viễn thông tỉnh cung cấp từ năm 2021, không kết nối với IOC, nên điện thoại viên nghe xong phải gõ lại nội dung vào phân hệ phản ánh, trung bình mỗi phản ánh mất khoảng 4 phút nhập liệu. Giờ cao điểm thì bỏ nhỡ cuộc gọi khoảng 18%. Người dân gọi lại hỏi kết quả thì điện thoại viên phải tra cứu thủ công. Ngoài ra phản ánh qua điện thoại và qua ứng dụng về cùng một sự việc thì đang bị trùng, ví dụ một vụ ngập đường có thể có 20 phản ánh.

@PM: Phía nhà thầu đề xuất thay tổng đài cũ bằng tổng đài IP tích hợp thẳng với IOC. Khi có cuộc gọi đến, hệ thống tự nhận số điện thoại, nếu số đó đã có tài khoản thì hiện thông tin người gọi và lịch sử phản ánh, điện thoại viên chỉ cần tạo phiếu, ghi âm cuộc gọi tự động gắn vào phản ánh.

@AI: Thêm nữa là nhóm AI có thể chuyển giọng nói cuộc gọi thành văn bản theo thời gian thực, điện thoại viên chỉ cần sửa lại cho gọn rồi lưu, không phải gõ từ đầu. Độ chính xác nhận dạng tiếng Việt giọng địa phương thì khoảng 85 đến 90%, đủ dùng để làm bản nháp. Về trùng lặp thì có thể gom các phản ánh cùng lĩnh vực trong bán kính 200 mét, trong 24 giờ thành một nhóm, đơn vị xử lý một lần, trả kết quả cho tất cả.

@SO: Ghi âm cuộc gọi thì phải thông báo cho người gọi ở lời chào đầu, đúng quy định về bảo vệ dữ liệu cá nhân. Thời gian lưu ghi âm tối đa 12 tháng.

@BA #n_botauto: Em có ý là thêm tổng đài ảo trả lời tự động bằng trí tuệ nhân tạo cho các câu hỏi thủ tục hành chính, người dân hỏi thì máy trả lời luôn, đỡ cho điện thoại viên.

@SO #n_botauto2: Cái đấy để sau. Trả lời thủ tục mà sai thì người dân đi lại mất công, lại khiếu nại. Giai đoạn này chưa làm trả lời tự động, chỉ dùng chuyển giọng nói thành văn bản hỗ trợ điện thoại viên thôi.

@BA: Em xin bổ sung số liệu về nội dung cuộc gọi. Trong 2.600 cuộc gọi mỗi tháng thì khoảng 1.100 cuộc là hỏi thông tin chứ không phải phản ánh: hỏi thủ tục cấp giấy phép xây dựng, hỏi lịch cắt điện, cắt nước, hỏi giờ làm việc của bộ phận một cửa, hỏi tiến độ hồ sơ. Điện thoại viên đang phải tra cứu trên nhiều hệ thống khác nhau, có khi phải gọi điện cho đơn vị khác hỏi rồi gọi lại cho người dân. Thời gian trung bình một cuộc gọi hỏi thông tin là 5 phút 20 giây.

@PM: Phía nhà thầu đề xuất xây dựng một bộ cơ sở tri thức cho điện thoại viên, gồm các câu hỏi thường gặp về thủ tục, lịch cắt điện nước tự động lấy từ Điện lực và Công ty Cấp nước, tra cứu tiến độ hồ sơ từ hệ thống dịch vụ công. Điện thoại viên gõ từ khóa là ra câu trả lời chuẩn, đọc cho người dân. Đây là công cụ hỗ trợ cho người, không phải máy trả lời tự động.

@SO: Cơ sở tri thức thì được, nhưng nội dung phải do các sở chuyên ngành duyệt, không để nhà thầu tự viết câu trả lời về thủ tục.

@AI #k_kha1b: Em báo cáo thêm kết quả thử nghiệm chuyển giọng nói thành văn bản trên 300 cuộc gọi ghi âm cũ, có sự đồng ý của người dân. Tỷ lệ lỗi từ trung bình là 12%, riêng giọng các xã miền núi phía Tây như Sông Hinh, Sơn Hòa có pha tiếng địa phương thì tỷ lệ lỗi lên khoảng 20%. Tên đường, tên thôn, tên riêng thì sai nhiều nhất, ví dụ "thôn Phú Thứ" thành "thôn phụ thứ". Bọn em sẽ bổ sung từ điển địa danh của tỉnh, khoảng 4.000 tên đường, thôn, khu phố, để mô hình ưu tiên nhận đúng.

@SEC: Về bảo mật ghi âm, em đề nghị tệp ghi âm lưu mã hóa, chỉ điện thoại viên tiếp nhận và cán bộ điều phối được nghe, đơn vị xử lý chỉ xem bản văn bản đã được biên tập, không được tải tệp ghi âm. Sau 12 tháng hệ thống tự xóa, có nhật ký xóa.

@BA: Về gom nhóm phản ánh trùng, em lưu ý trường hợp ngập úng thì bán kính 200 mét có thể quá nhỏ, vì một đợt ngập có thể kéo dài cả cây số đường, nhưng với ổ gà thì 200 mét lại quá lớn, có thể gộp nhầm hai ổ gà khác nhau. Em đề nghị bán kính gom nhóm cấu hình theo từng lĩnh vực.

@PM #d_bankinh: Đồng ý, bán kính để cấu hình theo lĩnh vực, mặc định 200 mét. Còn một vấn đề nữa là giờ trực. Tổng đài 1022 hiện chỉ trực giờ hành chính, ngoài giờ thì chuyển hộp thư thoại. Nhưng các sự cố như cây đổ, ngập nước, mất nắp cống thường xảy ra vào đêm mưa bão.

@SO #a_tructruc: Vấn đề trực 24/7 liên quan đến biên chế điện thoại viên, không giải quyết trong phạm vi dự án được. Trước mắt mùa mưa bão thì Trung tâm điều hành bố trí trực luân phiên ngoài giờ, việc này Sở sẽ báo cáo Ủy ban sau.

@PM #d_1022: Chốt: thay tổng đài cũ bằng tổng đài IP tích hợp IOC, tự nhận diện người gọi, ghi âm gắn vào phản ánh có thông báo ở lời chào, lưu tối đa 12 tháng; chuyển giọng nói thành văn bản làm bản nháp cho điện thoại viên; gom nhóm phản ánh trùng trong 24 giờ, bán kính cấu hình theo lĩnh vực, mặc định 200 mét; xây dựng cơ sở tri thức hỗ trợ điện thoại viên, nội dung do các sở chuyên ngành duyệt.

@PM #a_tongdai: Phần tổng đài IP thì em làm việc với Viễn thông tỉnh về chuyển đổi đầu số 1022, dự kiến chuyển trong tháng 12.

@AI #a_stt: Chuyển giọng nói thành văn bản và gom nhóm trùng thì nhóm em làm, xong cùng lúc với tổng đài.

## TOPIC | Xây dựng chức năng giám sát giao thông bằng camera AI | 120 camera giao thông đã kết nối, nhận diện biển số đạt 94% ban ngày nhưng 71% ban đêm; thống nhất bổ sung đèn hồng ngoại cho 40 camera nút giao trọng điểm, chỉ dùng kết quả AI làm căn cứ phạt nguội sau khi cán bộ CSGT xác nhận.

@PM: Nội dung thứ ba là giám sát giao thông bằng camera AI. Anh Kha.

@AI #k_kha2: Dạ. Phân hệ giám sát giao thông đã kết nối 120 camera tại 46 nút giao trên địa bàn thành phố Tuy Hòa và các tuyến quốc lộ. Các chức năng gồm đếm lưu lượng theo loại phương tiện, phát hiện ùn tắc, phát hiện vi phạm vượt đèn đỏ, đi sai làn, dừng đỗ sai quy định, và nhận diện biển số. Kết quả đánh giá trên tập kiểm thử 20.000 khung hình do Công an gán nhãn thì nhận diện biển số đạt 94% ban ngày nhưng chỉ đạt 71% ban đêm, chủ yếu do đèn pha xe chói và camera đời cũ không có hồng ngoại. Phát hiện vượt đèn đỏ đạt độ chính xác 91%, có khoảng 9% báo nhầm, chủ yếu khi xe cứu thương, xe ưu tiên đi qua, hoặc khi đèn tín hiệu vừa chuyển. Về ùn tắc thì hệ thống phát hiện và cảnh báo trung bình sớm hơn 6 phút so với báo cáo của lực lượng tại chỗ.

@CA #k_binh1: Phía Công an thì chúng tôi đánh giá cao phần phát hiện ùn tắc. Còn phần vi phạm, tôi nói rõ là kết quả của máy chưa được dùng trực tiếp làm căn cứ xử phạt. Theo Luật Trật tự, an toàn giao thông đường bộ và Nghị định về thiết bị nghiệp vụ, hình ảnh từ camera của hệ thống ngoài ngành công an chỉ được dùng làm căn cứ khi được cán bộ cảnh sát giao thông kiểm tra, xác nhận, và camera phải được kiểm định. Đề nghị hệ thống có bước để cán bộ Phòng Cảnh sát giao thông xác nhận từng trường hợp trước khi gửi thông báo phạt nguội.

@SO: Còn camera ban đêm thì các anh xử lý thế nào?

@AI: Dạ có hai cách, thay camera mới có hồng ngoại, khoảng 45 triệu một camera, hoặc lắp đèn hồng ngoại hỗ trợ cho camera hiện có, khoảng 8 triệu một bộ. Em đề xuất lắp đèn hồng ngoại cho 40 camera tại các nút giao trọng điểm có nhiều vi phạm ban đêm, các nút còn lại thì chưa cần.

@SO: Anh Kha cho tôi hỏi thêm, việc đếm lưu lượng và phát hiện ùn tắc đã được dùng vào việc gì chưa, hay mới chỉ hiển thị trên màn hình?

@AI #k_kha2b: Dạ thưa anh, hiện tại có hai ứng dụng thực tế. Thứ nhất là cảnh báo ùn tắc gửi cho tổ cảnh sát giao thông gần nhất qua ứng dụng trên điện thoại, trong tháng vừa rồi có 214 cảnh báo, lực lượng xác nhận đúng 181 cảnh báo. Thứ hai là số liệu lưu lượng theo giờ được Sở Xây dựng dùng để điều chỉnh chu kỳ đèn tín hiệu tại 12 nút giao, ví dụ nút Trần Hưng Đạo - Nguyễn Huệ chu kỳ đèn đỏ hướng Bắc Nam giờ cao điểm sáng giảm từ 90 giây xuống 70 giây, thời gian xếp hàng trung bình giảm khoảng 25%. Bọn em đề xuất giai đoạn sau kết nối trực tiếp với bộ điều khiển đèn tín hiệu để điều chỉnh tự động theo lưu lượng thực, nhưng việc này cần nâng cấp bộ điều khiển, ngoài phạm vi hợp đồng hiện tại.

@CA: Về phát hiện dừng đỗ sai quy định, tôi thấy tỷ lệ báo nhầm khá cao ở khu vực chợ, xe giao hàng dừng một hai phút để bốc dỡ cũng bị bắt. Theo quy định thì dừng xe khác với đỗ xe, dừng tạm thời để bốc dỡ hàng ở nơi không cấm dừng thì không vi phạm. Hệ thống phải phân biệt được thời gian dừng.

@AI: Dạ, hiện tại ngưỡng thời gian bọn em đặt là 60 giây, có thể tăng lên 5 phút đối với các tuyến không có biển cấm dừng, chỉ có biển cấm đỗ. Nhưng như vậy cần dữ liệu biển báo của từng đoạn đường, cái này phải lấy từ Sở Xây dựng, hiện chưa số hóa đầy đủ.

@SEC: Em lưu ý về kiểm định camera. Camera dùng làm căn cứ xử phạt phải là thiết bị được kiểm định, hiệu chuẩn theo quy định của Bộ Khoa học và Công nghệ về phương tiện đo, đặc biệt là camera đo tốc độ. Trong 120 camera thì chỉ có 30 camera tại các nút giao trọng điểm được mua theo dự án của Công an, có giấy kiểm định, còn 90 camera do dự án IOC lắp thì chưa kiểm định.

@CA #k_binh1b: Đúng vậy. Vì thế quan điểm của Công an là giai đoạn này hình ảnh từ 90 camera chưa kiểm định chỉ dùng để phát hiện, sau đó cán bộ đối chiếu với camera đã kiểm định hoặc lập biên bản trực tiếp, chứ không gửi thông báo phạt nguội chỉ dựa vào camera chưa kiểm định. Kinh phí kiểm định thì khoảng 3 triệu một camera một năm, không lớn, nhưng phải có chủ sở hữu thiết bị đứng ra làm.

@SO #n_kiemdinh: Cái này chủ sở hữu là Sở Khoa học và Công nghệ. Kiểm định 90 camera thì tôi thấy nên làm, nhưng kinh phí năm nay đã hết, để tôi xem có đưa được vào dự toán năm sau không, chưa hứa được.

@PM #a_buocsong: Về đèn hồng ngoại, phía nhà thầu lưu ý thêm là đèn hồng ngoại công suất lớn lắp ở nút giao gần khu dân cư thì người dân không nhìn thấy nhưng một số loại camera hành trình của ô tô sẽ bị lóa, nhà thầu sẽ chọn loại bước sóng 940 nanomet để hạn chế ảnh hưởng.

@PM #d_giaothong: Chốt: lắp đèn hồng ngoại hỗ trợ cho 40 camera tại nút giao trọng điểm; thêm bước cán bộ Cảnh sát giao thông xác nhận vi phạm trước khi xuất thông báo phạt nguội; loại trừ xe ưu tiên khi phát hiện vượt đèn đỏ.

@AI #a_hongngoai: Em lập danh sách 40 camera và dự toán đèn hồng ngoại, gửi Sở trong tuần sau.

@CA #a_canbo: Công an tỉnh sẽ cử 3 cán bộ Phòng Cảnh sát giao thông được phân quyền xác nhận trên hệ thống, danh sách gửi Sở trước ngày 20.

## TOPIC | Xây dựng chức năng giám sát an ninh trật tự bằng camera | 85 camera an ninh tại nơi công cộng kết nối IOC; chức năng nhận diện khuôn mặt bị tạm dừng chờ khung pháp lý; thống nhất chỉ dùng phát hiện tụ tập đông người, đánh nhau và bỏ quên vật thể, dữ liệu camera an ninh lưu riêng tại Công an tỉnh.

@PM: Nội dung thứ tư cũng là camera nhưng là camera an ninh trật tự. Anh Kha tiếp tục.

@AI #k_kha3: Dạ. Phân hệ an ninh trật tự kết nối 85 camera đặt tại quảng trường, công viên, bến xe, chợ đầu mối, khu vực bãi biển. Khác với camera giao thông, phân hệ này tập trung vào phát hiện sự việc: tụ tập đông người bất thường, xô xát đánh nhau, người ngã, vật thể bị bỏ lại lâu, xâm nhập khu vực cấm như bãi biển ban đêm có cờ đỏ. Trong thiết kế ban đầu có chức năng nhận diện khuôn mặt để tìm người mất tích, đối tượng truy nã, nhưng chức năng này đang tạm dừng theo chỉ đạo của Sở.

@CA #k_binh2: Công an tỉnh thì có hai yêu cầu. Thứ nhất, camera an ninh trật tự có những vị trí nhạy cảm, dữ liệu hình ảnh không được lưu trên hạ tầng dùng chung của IOC mà phải lưu tại máy chủ của Công an tỉnh, IOC chỉ nhận cảnh báo và hình ảnh trích đoạn khi có sự việc. Thứ hai, về nhận diện khuôn mặt, theo Luật Bảo vệ dữ liệu cá nhân thì dữ liệu sinh trắc học là dữ liệu nhạy cảm, việc thu thập, xử lý ở nơi công cộng cho mục đích an ninh phải do cơ quan công an thực hiện theo quy định riêng, Sở Khoa học và Công nghệ không phải là chủ thể. Chúng tôi đề nghị bỏ chức năng nhận diện khuôn mặt khỏi phạm vi IOC.

@SO: Sở đồng ý. Nhận diện khuôn mặt nếu có thì để Công an tỉnh làm trong hệ thống của ngành.

@SEC: Về kỹ thuật thì nếu lưu tại Công an tỉnh thì cần đường truyền riêng và mã hóa đầu cuối giữa camera và máy chủ của Công an. Luồng cảnh báo sang IOC chỉ gồm loại sự việc, vị trí, thời gian và một ảnh trích đoạn đã làm mờ khuôn mặt người không liên quan.

@AI: Phát hiện tụ tập đông người thì tỉ lệ báo nhầm hiện khoảng 15%, nhất là ở chợ đầu mối buổi sáng, vốn dĩ đông. Bọn em sẽ cấu hình ngưỡng theo khung giờ và theo vị trí.

@SO: Tôi muốn làm rõ thêm ranh giới giữa hai phân hệ camera. Có những camera vừa nhìn được giao thông vừa nhìn được khu vực công cộng, ví dụ camera ở quảng trường 1 tháng 4 vừa nhìn đường Độc Lập vừa nhìn quảng trường. Camera đó thuộc phân hệ nào?

@AI #k_kha3b: Dạ thưa anh, hiện tại có 14 camera như vậy, đang được gắn vào cả hai phân hệ, luồng hình ảnh chia đôi. Theo phương án Công an vừa đề nghị thì luồng hình ảnh gốc của 14 camera này sẽ lưu tại máy chủ Công an, còn phân hệ giao thông của IOC chỉ nhận luồng đã xử lý, tức là số liệu đếm xe, cảnh báo ùn tắc và ảnh biển số khi có vi phạm, không nhận hình ảnh liên tục của khu vực quảng trường.

@CA: Chúng tôi đồng ý cách đó. Ngoài ra đề nghị nhà thầu cung cấp cho Công an danh sách toàn bộ tài khoản đang có quyền xem hình ảnh trực tiếp của 85 camera an ninh, hiện nay tôi được biết có cả kỹ sư của nhà thầu và một số cán bộ của Trung tâm điều hành có quyền xem, cần rà soát lại. Sau khi chuyển giao, chỉ cán bộ Công an và cán bộ trực được Công an đồng ý mới được xem trực tiếp.

@PM #a_quyentam: Hiện có 23 tài khoản có quyền xem trực tiếp, trong đó 9 tài khoản của kỹ sư nhà thầu phục vụ cấu hình và bảo trì. Nhà thầu sẽ chuyển sang cơ chế cấp quyền tạm thời có thời hạn khi bảo trì, có Công an phê duyệt.

@SEC: Em đề nghị bổ sung yêu cầu là toàn bộ thao tác xem lại, trích xuất, tải hình ảnh từ camera an ninh đều phải ghi nhật ký, ai xem, xem camera nào, khoảng thời gian nào, mục đích gì. Nhật ký này không được sửa, xóa, lưu tối thiểu 2 năm.

@AI: Về phát hiện vật thể bỏ quên, tỷ lệ báo nhầm hiện rất cao ở bến xe, khoảng 40%, vì hành khách đặt hành lý xuống đất rồi ngồi chờ lâu. Bọn em đang thử kết hợp điều kiện là vật thể bị bỏ lại và không có người nào ở gần trong bán kính 3 mét trong hơn 5 phút, tỷ lệ báo nhầm giảm còn khoảng 12%. Phát hiện người ngã thì hoạt động tốt hơn, độ chính xác khoảng 88%, hữu ích ở khu vực bãi biển và công viên vào buổi sáng sớm, đã có 2 trường hợp người cao tuổi bị ngã khi tập thể dục được phát hiện và hỗ trợ kịp thời.

@CA #n_bienso: Nhân tiện tôi xin hỏi, phía Công an có nhu cầu tìm kiếm phương tiện theo biển số trên toàn bộ 205 camera, cả giao thông và an ninh, khi có vụ án, ví dụ truy vết xe gây tai nạn bỏ chạy. Hệ thống có làm được không?

@SO #n_bienso2: Việc truy vết theo biển số trên toàn hệ thống thì về kỹ thuật làm được, nhưng đây là xử lý dữ liệu vị trí di chuyển của công dân, cần có quy chế phối hợp giữa Sở và Công an quy định rõ trường hợp nào được tra cứu, ai phê duyệt. Chưa có quy chế thì chưa mở chức năng này. Để hai bên xây dựng quy chế rồi tính.

@PM #d_anninh: Chốt: bỏ chức năng nhận diện khuôn mặt khỏi phạm vi IOC; chỉ giữ phát hiện tụ tập bất thường, xô xát, người ngã, vật thể bỏ quên, xâm nhập khu vực cấm; dữ liệu camera an ninh lưu tại máy chủ Công an tỉnh, IOC chỉ nhận cảnh báo và ảnh trích đoạn đã làm mờ; mọi thao tác xem lại, trích xuất hình ảnh camera an ninh phải ghi nhật ký không sửa xóa được, lưu tối thiểu 2 năm.

@SEC #a_duongtruyen: Em thiết kế phương án đường truyền riêng và mã hóa, gửi Công an tỉnh thẩm định trước cuối tháng.

@AI #a_nguong: Em cấu hình lại ngưỡng tụ tập theo khung giờ và vị trí, chạy thử hai tuần rồi báo cáo tỷ lệ báo nhầm.

## TOPIC | Xây dựng bảng điều khiển chỉ số kinh tế - xã hội cho lãnh đạo tỉnh | Bảng điều khiển có 64 chỉ số nhưng 40% chỉ số phải nhập tay, dữ liệu trễ 1-2 tháng; thống nhất giảm còn 32 chỉ số cốt lõi, ưu tiên kết nối tự động với hệ thống thuế, kho bạc, dịch vụ công, mỗi chỉ số có đơn vị chịu trách nhiệm cập nhật.

@PM: Nội dung thứ năm là bảng điều khiển kinh tế xã hội. Chị Phượng.

@BA #k_phuong3: Dạ. Bảng điều khiển cho lãnh đạo tỉnh hiện có 64 chỉ số thuộc 9 lĩnh vực: tăng trưởng, thu chi ngân sách, đầu tư công, doanh nghiệp, xuất nhập khẩu, du lịch, giáo dục, y tế, cải cách hành chính. Khoảng 38 chỉ số lấy tự động từ các hệ thống như dịch vụ công, quản lý văn bản, kho bạc, còn 26 chỉ số, khoảng 40%, các sở phải nhập tay hằng tháng, nhưng nhiều sở nhập chậm hoặc không nhập, có chỉ số trễ một đến hai tháng, có chỉ số ba tháng không cập nhật. Có lần lãnh đạo Ủy ban mở bảng điều khiển trong cuộc họp thì số liệu giải ngân đầu tư công là của hai tháng trước, rất bị động. Ngoài ra số liệu trên bảng điều khiển và số liệu trong báo cáo của các sở đôi khi không khớp nhau.

@SO #k_hai2: Lãnh đạo Ủy ban đã góp ý với Sở là 64 chỉ số thì nhiều quá, nhìn không hết, mà chỉ số nào cũng có màu xanh đỏ thì không biết cái nào quan trọng. Ý của lãnh đạo là chỉ cần khoảng 30 chỉ số cốt lõi, nhưng phải chính xác và cập nhật. Những chỉ số không cập nhật được thì bỏ ra, còn hơn để số cũ.

@BA: Dạ, nhóm em đã rà soát và đề xuất 32 chỉ số cốt lõi, trong đó 24 chỉ số kết nối tự động được, còn 8 chỉ số phải nhập tay. Với 8 chỉ số này thì mỗi chỉ số giao rõ một đơn vị chịu trách nhiệm, hệ thống tự nhắc trước hạn 3 ngày, quá hạn thì hiện tên đơn vị trên bảng điều khiển.

@PM: Phía nhà thầu đề xuất kết nối thêm với hệ thống quản lý thuế của Cục Thuế để lấy số thu ngân sách theo ngày, và với hệ thống quản lý đầu tư công để lấy số giải ngân theo tuần, hai nguồn này hiện là nhập tay.

@SO: Kết nối với hệ thống thuế thì phải có văn bản của Ủy ban gửi Cục Thuế, Sở sẽ tham mưu.

@SO: Chị Phượng cho tôi biết 32 chỉ số cốt lõi gồm những nhóm nào, để tôi báo cáo lãnh đạo Ủy ban.

@BA #k_phuong3b: Dạ thưa anh, 32 chỉ số chia thành 6 nhóm. Nhóm tăng trưởng và ngân sách có 7 chỉ số: thu ngân sách lũy kế so với dự toán, thu nội địa, thu tiền sử dụng đất, chi đầu tư phát triển, tỷ lệ giải ngân đầu tư công, chỉ số sản xuất công nghiệp và tổng mức bán lẻ. Nhóm doanh nghiệp và đầu tư có 5 chỉ số: số doanh nghiệp thành lập mới, số doanh nghiệp giải thể, số dự án được cấp chủ trương đầu tư, vốn đăng ký, kim ngạch xuất khẩu. Nhóm cải cách hành chính có 6 chỉ số: số hồ sơ tiếp nhận, tỷ lệ hồ sơ trực tuyến, tỷ lệ đúng hạn, số hồ sơ quá hạn theo đơn vị, tỷ lệ văn bản điện tử có ký số, số nhiệm vụ Ủy ban giao quá hạn. Nhóm đô thị gồm 5 chỉ số lấy từ chính IOC: số phản ánh, tỷ lệ xử lý đúng hạn, điểm hài lòng, số cảnh báo ùn tắc và số sự việc an ninh. Nhóm văn hóa xã hội có 6 chỉ số: lượt khách du lịch, doanh thu du lịch, số người tham gia bảo hiểm y tế, số ca bệnh truyền nhiễm, số lao động được giải quyết việc làm, tỷ lệ hộ nghèo theo quý. Nhóm môi trường có 3 chỉ số: chỉ số chất lượng không khí, tỷ lệ thu gom rác, mực nước các hồ chứa lớn.

@SO: Nhóm nhiệm vụ Ủy ban giao quá hạn là chỉ số lãnh đạo rất quan tâm, nhưng các sở sẽ rất nhạy cảm. Hiển thị tên đơn vị quá hạn công khai trên bảng điều khiển trong các cuộc họp có thể gây phản ứng. Tôi đề nghị chỉ hiển thị chi tiết theo đơn vị khi lãnh đạo bấm vào, màn hình chính chỉ hiện tổng số.

@AI: Về mặt kỹ thuật, bọn em có thử nghiệm thêm tính năng dự báo, ví dụ dự báo thu ngân sách cuối năm dựa trên tốc độ thu các tháng, dự báo tỷ lệ giải ngân đến 31 tháng 1. Độ chính xác dự báo thu ngân sách với dữ liệu ba năm gần đây sai số khoảng 4%.

@SO #n_dubao: Dự báo thì thú vị nhưng con số dự báo mà hiện lên trong cuộc họp, rồi thực tế khác đi, thì ai chịu trách nhiệm? Các con số dự báo chính thức là của Sở Tài chính và Chi cục Thống kê. Tính năng dự báo để thử nghiệm nội bộ thôi, chưa đưa lên bảng điều khiển của lãnh đạo.

@BA: Một vấn đề nữa là thời điểm chốt số. Nhiều chỉ số tự động cập nhật hằng ngày, nhưng số báo cáo chính thức của các sở thì chốt vào ngày 20 hằng tháng. Nếu lãnh đạo xem bảng điều khiển ngày 25 rồi so với báo cáo của sở thì sẽ lệch. Em đề xuất mỗi chỉ số ghi rõ thời điểm cập nhật cuối cùng và nguồn dữ liệu ngay bên cạnh con số, để người xem biết số đó là số tạm tính hay số chính thức.

@PM #a_nhan: Phía nhà thầu đồng ý. Giao diện sẽ có nhãn "số tạm tính" và "số chính thức", kèm thời điểm và nguồn.

@PM #d_dashboard: Chốt: giảm bảng điều khiển xuống 32 chỉ số cốt lõi; kết nối tự động với hệ thống thuế và hệ thống quản lý đầu tư công; 8 chỉ số nhập tay giao đơn vị chịu trách nhiệm, nhắc trước hạn 3 ngày; chi tiết đơn vị quá hạn chỉ hiện khi lãnh đạo bấm vào, màn hình chính hiện tổng số; mỗi chỉ số ghi nguồn, thời điểm cập nhật và nhãn số tạm tính hay số chính thức.

@BA #a_danhmuc: Em hoàn thiện danh mục 32 chỉ số kèm đơn vị chịu trách nhiệm và nguồn dữ liệu, gửi Sở trước thứ Sáu.

@SO #a_cucthue: Sở tham mưu Ủy ban văn bản đề nghị Cục Thuế chia sẻ dữ liệu, trong tháng này.

## TOPIC | Xây dựng chức năng bản đồ số quy hoạch đô thị | Đã số hóa 41 đồ án quy hoạch phân khu và chi tiết lên bản đồ số; 7 đồ án có sai lệch ranh giới giữa bản vẽ và quyết định phê duyệt; thống nhất chỉ công khai các đồ án đã được Sở Xây dựng xác nhận, kèm cảnh báo thông tin chỉ có giá trị tham khảo.

@PM: Nội dung thứ sáu là bản đồ số quy hoạch. Anh Lợi.

@GIS #k_loi1: Dạ. Phân hệ bản đồ số quy hoạch đã số hóa và chồng lớp được 41 đồ án quy hoạch phân khu và quy hoạch chi tiết đã phê duyệt của thành phố Tuy Hòa và thị xã Sông Cầu, kèm thông tin chức năng sử dụng đất, mật độ xây dựng, tầng cao tối đa cho từng ô phố. Người dân có thể tra cứu theo số thửa hoặc chạm vào bản đồ để biết thửa đất của mình nằm trong quy hoạch gì. Tuy nhiên khi chồng lớp thì phát hiện 7 đồ án có sai lệch ranh giới giữa bản vẽ CAD do đơn vị tư vấn cung cấp và bản vẽ đã đóng dấu kèm quyết định phê duyệt, có chỗ lệch đến 15 mét, nếu công khai thì có thể dẫn đến khiếu nại. Ngoài ra có 12 đồ án đã điều chỉnh cục bộ nhưng chưa cập nhật nội dung điều chỉnh.

@SO: Bản đồ quy hoạch là thông tin rất nhạy cảm, người dân dựa vào đó để mua bán đất. Nếu sai thì trách nhiệm rất lớn.

@GIS: Dạ, em đề xuất chỉ công khai các đồ án đã được Sở Xây dựng kiểm tra và xác nhận khớp với hồ sơ phê duyệt, các đồ án còn sai lệch thì tạm ẩn. Trên giao diện có cảnh báo thông tin chỉ có giá trị tham khảo, căn cứ pháp lý là hồ sơ quy hoạch được phê duyệt và chứng chỉ quy hoạch do cơ quan có thẩm quyền cung cấp.

@SO: Anh Lợi, hiện người dân tra cứu quy hoạch trên bản đồ số nhiều không?

@GIS #k_loi1b: Dạ, phân hệ tra cứu quy hoạch mới mở thử nghiệm nội bộ cho cán bộ Sở Xây dựng và Phòng Quản lý đô thị thành phố Tuy Hòa dùng khoảng 2 tháng, chưa mở công khai. Trong 2 tháng đó có khoảng 3.400 lượt tra cứu, chủ yếu là cán bộ tra cứu để trả lời đơn thư, cấp giấy phép xây dựng. Cán bộ Phòng Quản lý đô thị phản hồi là thời gian tra cứu thông tin quy hoạch cho một hồ sơ giảm từ khoảng nửa ngày, phải tìm bản vẽ giấy trong kho, xuống còn vài phút. Nhưng cũng chính trong quá trình dùng thử thì cán bộ phát hiện ra 7 đồ án sai lệch nói trên.

@GIS: Em xin nói rõ hơn nguyên nhân sai lệch. Các đồ án cũ lập từ năm 2010 đến 2015 phần lớn dùng hệ tọa độ VN-2000 nhưng kinh tuyến trục khác nhau, có đồ án vẽ trên nền bản đồ địa hình cũ, không khớp với bản đồ địa chính mới đo năm 2019. Khi chuyển đổi và chồng lớp thì lệch từ 3 đến 15 mét. Về kỹ thuật thì có thể hiệu chỉnh bằng cách nắn theo các điểm khống chế như ngã tư đường, công trình cố định, nhưng việc hiệu chỉnh phải do đơn vị tư vấn lập quy hoạch ban đầu hoặc Viện Quy hoạch xác nhận, vì nếu nhóm GIS tự nắn thì không có giá trị pháp lý.

@SEC: Em có câu hỏi về phía người dùng. Nếu mở công khai thì có cho tải xuống dữ liệu không, hay chỉ xem? Nếu cho tải dữ liệu vector thì các trang bất động sản sẽ lấy toàn bộ dữ liệu về rồi khai thác thương mại.

@GIS: Em đề xuất người dân chỉ được xem và tra cứu từng thửa, có thể in phiếu thông tin quy hoạch của thửa đó có ghi chú giá trị tham khảo, không cho tải dữ liệu vector. Còn chia sẻ dữ liệu cho tổ chức, doanh nghiệp thì phải qua đề nghị bằng văn bản và Sở Xây dựng chấp thuận.

@SO #n_giayphep: Tôi đã nghe Sở Xây dựng đặt vấn đề là dùng luôn bản đồ số để cấp chứng chỉ quy hoạch tự động trực tuyến cho người dân, không cần cán bộ. Nhưng tôi thấy bây giờ dữ liệu còn sai lệch thì chưa thể làm được, phải chờ dữ liệu được xác nhận toàn bộ. Ý tưởng này để sau.

@BA: Em bổ sung thêm là nhiều người dân hỏi về thông tin giá đất, kế hoạch sử dụng đất hằng năm, đất nào sắp bị thu hồi. Những lớp này thuộc Sở Nông nghiệp và Môi trường, không phải Sở Xây dựng. Hiện bản đồ chưa có lớp kế hoạch sử dụng đất. Nếu không có thì người dân xem quy hoạch đô thị sẽ chưa đủ thông tin.

@GIS: Đúng vậy, lớp kế hoạch sử dụng đất cấp huyện năm 2026 đã được phê duyệt, Sở Nông nghiệp và Môi trường có dữ liệu số, nhưng chưa có văn bản chia sẻ. Đây là việc cần đưa vào giai đoạn sau.

@PM #d_quyhoach: Chốt: chỉ công khai đồ án đã được Sở Xây dựng xác nhận; 7 đồ án sai lệch tạm ẩn chờ hiệu chỉnh; 12 đồ án điều chỉnh cục bộ phải cập nhật trước khi công khai; có cảnh báo giá trị tham khảo trên giao diện; người dân chỉ xem, tra cứu và in phiếu từng thửa, không cho tải dữ liệu vector.

@GIS #a_danhsachqh: Em gửi danh sách 7 đồ án sai lệch kèm bản chồng lớp cho Sở Xây dựng trong tuần này.

@SO #a_sxd: Sở sẽ có văn bản đề nghị Sở Xây dựng cử đầu mối kiểm tra, xác nhận các đồ án.

## TOPIC | Xây dựng chức năng bản đồ hạ tầng kỹ thuật ngầm | Đã số hóa 380 km cáp viễn thông và 210 km ống cấp nước, nhưng thiếu dữ liệu cao độ và nhiều tuyến cáp ngầm không có hồ sơ hoàn công; thống nhất yêu cầu các doanh nghiệp cung cấp dữ liệu theo chuẩn trước 31/12, bản đồ hạ tầng ngầm chỉ phân quyền cho cơ quan nhà nước và chủ sở hữu công trình.

@PM: Nội dung thứ bảy là bản đồ hạ tầng kỹ thuật ngầm, cũng do nhóm anh Lợi làm.

@GIS #k_loi2: Dạ. Bản đồ hạ tầng ngầm khác bản đồ quy hoạch ở chỗ là dữ liệu hiện trạng các công trình ngầm: cáp điện, cáp viễn thông, ống cấp nước, cống thoát nước, ống gas. Đến nay đã số hóa được khoảng 380 cây số cáp viễn thông của ba nhà mạng, 210 cây số ống cấp nước của công ty cấp nước, và 95 cây số cống thoát nước. Còn cáp điện ngầm của Điện lực thì chưa nhận được dữ liệu. Vấn đề là phần lớn dữ liệu chỉ có vị trí trên mặt bằng, không có cao độ, tức là không biết ống nằm sâu bao nhiêu. Nhiều tuyến cáp viễn thông ngầm hóa từ những năm 2010 không có hồ sơ hoàn công. Tháng trước có vụ thi công cống làm đứt cáp quang trục, mất mạng cả một khu vực 8 tiếng, chính vì không biết cáp nằm ở đâu.

@SO #k_hai3: Theo Nghị định về quản lý không gian xây dựng ngầm thì các chủ sở hữu công trình ngầm có trách nhiệm cung cấp dữ liệu cho cơ quan quản lý nhà nước. Sở sẽ tham mưu Ủy ban có văn bản yêu cầu các doanh nghiệp cung cấp đầy đủ dữ liệu theo chuẩn, có cao độ, trước 31 tháng 12. Doanh nghiệp nào không cung cấp thì không cấp phép đào đường cho các công trình mới.

@SEC: Bản đồ hạ tầng ngầm là dữ liệu liên quan đến an ninh, cáp quang trục, đường ống chính, nếu lộ ra thì có thể bị phá hoại. Em đề nghị không công khai, chỉ phân quyền cho cơ quan nhà nước có chức năng và chủ sở hữu công trình xem phần của mình, có nhật ký truy cập.

@GIS: Dạ đúng, khác với bản đồ quy hoạch là công khai cho dân, bản đồ hạ tầng ngầm là nội bộ.

@SO: Vụ đứt cáp quang trục tháng trước thiệt hại cụ thể thế nào?

@GIS #k_loi2b: Dạ, vụ đó xảy ra khi nhà thầu thi công cống thoát nước trên đường Lê Duẩn dùng máy khoan cắt đường, cắt đứt tuyến cáp quang trục 96 sợi của một nhà mạng chôn ở độ sâu khoảng 0,6 mét, trong khi hồ sơ thiết kế cống không thể hiện có cáp. Khoảng 18.000 thuê bao internet và di động mất kết nối 8 tiếng, trong đó có cả đường truyền của Kho bạc và một số chi nhánh ngân hàng. Nhà mạng ước thiệt hại trực tiếp khoảng 600 triệu, đang yêu cầu nhà thầu bồi thường, nhà thầu thì nói là không được cung cấp thông tin. Cùng tháng đó còn 2 vụ làm vỡ ống cấp nước D200 khi đào đường. Đây chính là lý do cần bản đồ hạ tầng ngầm có cao độ.

@SEC: Em bổ sung về phân quyền. Em đề xuất ba mức. Mức một là cơ quan quản lý nhà nước như Sở Xây dựng, Phòng Quản lý đô thị xem được toàn bộ. Mức hai là chủ sở hữu công trình, ví dụ nhà mạng, chỉ xem và cập nhật dữ liệu công trình của mình, và xem được các công trình khác trong phạm vi 50 mét quanh công trình mình để phối hợp. Mức ba là nhà thầu thi công, khi được cấp phép đào đường thì được cấp quyền tạm thời xem dữ liệu ngầm trong phạm vi tuyến thi công, hết hạn giấy phép thì tự động thu hồi quyền.

@GIS #a_capphep: Mức ba rất quan trọng, vì chính nhà thầu thi công là người cần thông tin nhất để tránh đào trúng. Bọn em sẽ tích hợp với quy trình cấp phép đào đường của Sở Xây dựng: khi có giấy phép thì hệ thống tự gửi tài khoản tạm thời và trích lục bản đồ ngầm của tuyến cho nhà thầu.

@CA: Phía Công an đề nghị lớp cáp quang trục của các cơ quan đảng, nhà nước, lực lượng vũ trang thì không đưa vào bản đồ dùng chung, kể cả mức một, mà quản lý riêng theo chế độ mật.

@SO: Đồng ý, các tuyến cáp chuyên dùng thì quản lý riêng.

@GIS: Về chuẩn dữ liệu, em dự kiến theo Thông tư của Bộ Xây dựng về cơ sở dữ liệu công trình ngầm đô thị, mỗi đối tượng có mã, loại, chủ sở hữu, kích thước, vật liệu, năm xây dựng, tọa độ và cao độ đỉnh, cao độ đáy, độ chính xác tọa độ. Với những tuyến cũ không có hồ sơ hoàn công thì doanh nghiệp có thể dùng thiết bị dò cáp ngầm bằng radar xuyên đất để xác định, chi phí khoảng 2 đến 3 triệu một trăm mét. Ba nhà mạng đã nói là chi phí dò toàn bộ là rất lớn, đề nghị có lộ trình.

@SO #n_lotrinh: Lộ trình thì có thể cho các tuyến cũ thêm thời gian, nhưng tuyến chính, tuyến trục phải xong trước 31 tháng 12. Còn tuyến nhánh cho thêm bao lâu thì để tôi trao đổi với Sở Xây dựng, chưa chốt hôm nay.

@PM #d_hatangngam: Chốt: Ủy ban có văn bản yêu cầu các doanh nghiệp cung cấp dữ liệu công trình ngầm theo chuẩn có cao độ trước 31/12, không cung cấp thì không cấp phép đào đường mới; bản đồ hạ tầng ngầm không công khai, phân quyền ba mức: cơ quan quản lý xem toàn bộ, chủ sở hữu xem công trình mình và phạm vi 50 mét, nhà thầu có giấy phép đào đường được quyền tạm thời theo tuyến; có nhật ký truy cập; cáp chuyên dùng của cơ quan đảng, nhà nước, lực lượng vũ trang quản lý riêng theo chế độ mật.

@GIS #a_chuan: Em soạn chuẩn dữ liệu và mẫu biểu cung cấp dữ liệu ngầm gửi kèm văn bản của Sở, xong trước ngày 25.

@SO #a_vanbanngam: Sở tham mưu văn bản của Ủy ban gửi các doanh nghiệp, trong đó có Điện lực, ngay sau khi có chuẩn dữ liệu.

## TOPIC | Rà soát an toàn thông tin hệ thống IOC trước khi nghiệm thu | Đánh giá cấp độ 3 phát hiện 3 lỗ hổng cao, 11 trung bình; tài khoản quản trị dùng chung và chưa có xác thực hai yếu tố; thống nhất khắc phục toàn bộ lỗ hổng cao trước 15/12, bật xác thực hai yếu tố, kết nối với SOC của tỉnh; đề xuất thuê dịch vụ kiểm thử xâm nhập quốc tế bị gạt.

@PM: Nội dung thứ tám là an toàn thông tin. Chị Diễm.

@SEC #k_diem: Dạ. Hệ thống IOC đã được phê duyệt hồ sơ đề xuất cấp độ 3. Tháng trước Trung tâm Giám sát an toàn không gian mạng của tỉnh đã kiểm tra, đánh giá, phát hiện 3 lỗ hổng mức cao và 11 lỗ hổng mức trung bình. Ba lỗ hổng cao gồm: API của ứng dụng Phú Hòa-S cho phép liệt kê phản ánh của người khác nếu đổi mã số trong đường dẫn; phần mềm quản lý camera dùng phiên bản cũ có lỗ hổng đã công bố; và một máy chủ thử nghiệm vẫn mở ra internet với mật khẩu mặc định. Ngoài ra em thấy tài khoản quản trị của các phân hệ đang dùng chung giữa nhiều kỹ sư nhà thầu, chưa có xác thực hai yếu tố, chưa có nhật ký truy cập tập trung.

@SO: Lỗ hổng liệt kê phản ánh của người khác là rất nghiêm trọng, phản ánh có thông tin cá nhân, có cả phản ánh tố cáo. Phải sửa ngay.

@PM: Lỗi API đó nhóm backend đã sửa hôm qua, chị Diễm kiểm tra lại giúp. Máy chủ thử nghiệm cũng đã tắt.

@SEC #n_pentest: Em có đề xuất là trước khi nghiệm thu thì thuê thêm một đơn vị kiểm thử xâm nhập quốc tế đánh giá độc lập, cho chắc chắn hơn.

@SO #n_pentest2: Không cần thiết và cũng không có kinh phí. Theo quy định thì đánh giá của Trung tâm Giám sát an toàn không gian mạng của tỉnh là đủ điều kiện. Thuê đơn vị nước ngoài truy cập hệ thống có dữ liệu cá nhân của dân lại phát sinh thêm vấn đề.

@SO: Lỗ hổng phần mềm quản lý camera là lỗ hổng gì, có nguy cơ bị khai thác thật không?

@SEC #k_diem2: Dạ thưa anh, đó là lỗ hổng cho phép vượt qua xác thực trên giao diện web quản trị của phần mềm quản lý video, đã được hãng công bố và có bản vá từ năm ngoái, mức điểm nghiêm trọng 9,8 trên 10. Trên thế giới đã có nhiều vụ khai thác lỗ hổng này để chiếm quyền camera, xem trộm hình ảnh hoặc biến camera thành công cụ tấn công từ chối dịch vụ. Hệ thống của mình thì giao diện quản trị không mở trực tiếp ra internet, chỉ truy cập được từ mạng nội bộ của trung tâm dữ liệu, nên nguy cơ thấp hơn, nhưng nếu kẻ tấn công vào được mạng nội bộ qua một điểm khác thì vẫn khai thác được. Bản vá cần nâng cấp phần mềm lên phiên bản mới, phải dừng hệ thống camera khoảng 2 tiếng, nên phải làm vào ban đêm và phối hợp với Công an.

@CA: Công an đồng ý dừng 2 tiếng vào ban đêm, nhưng đề nghị báo trước 3 ngày để bố trí lực lượng tuần tra bù tại các khu vực trọng điểm.

@SEC: Về 11 lỗ hổng trung bình, chủ yếu là cấu hình: chưa bật mã hóa ở một số kết nối nội bộ giữa các dịch vụ, chính sách mật khẩu yếu cho tài khoản cán bộ các phường, chưa giới hạn số lần đăng nhập sai, thông báo lỗi tiết lộ thông tin phiên bản phần mềm, và cookie chưa đặt thuộc tính bảo mật. Phần lớn sửa nhanh, chỉ cần cấu hình lại.

@PM: Phía nhà thầu xin báo cáo thêm là sau khi rà soát lại, ngoài máy chủ thử nghiệm đã tắt thì nhóm phát hiện thêm một kho mã nguồn trên dịch vụ lưu trữ mã nguồn trực tuyến của một kỹ sư cũ có chứa tệp cấu hình với chuỗi kết nối cơ sở dữ liệu thử nghiệm. Kho này đã được xóa và mật khẩu đã được đổi. Dữ liệu thử nghiệm là dữ liệu giả, không có dữ liệu thật của người dân.

@SO #a_baocaosuco: Sự việc này rất nghiêm trọng về mặt quy trình, dù là dữ liệu giả. Nhà thầu phải có báo cáo bằng văn bản về sự việc này gửi Sở, và phải rà soát lại quy định nội bộ về quản lý mã nguồn, không cho phép đưa mã nguồn dự án lên kho công khai.

@SEC #k_diem3: Em đề nghị thêm là sau nghiệm thu, hệ thống phải được giám sát an toàn thông tin liên tục bởi Trung tâm Giám sát của tỉnh, tức là SOC, nhật ký của tường lửa, máy chủ, ứng dụng đều đẩy về SOC. Và mỗi năm phải kiểm tra đánh giá lại ít nhất một lần theo quy định của cấp độ 3.

@PM #d_attt: Chốt: khắc phục toàn bộ 3 lỗ hổng cao trước ngày 15 tháng 12 và có xác nhận của Trung tâm Giám sát; 11 lỗ hổng trung bình khắc phục trước nghiệm thu; bỏ tài khoản quản trị dùng chung, mỗi kỹ sư một tài khoản, bật xác thực hai yếu tố; kết nối nhật ký với SOC của tỉnh.

@SEC #a_kiemtralai: Em kiểm tra lại lỗi API và máy chủ thử nghiệm ngay hôm nay, phần mềm camera em làm việc với hãng để nâng cấp trước ngày 10 tháng 12.

@PM #a_taikhoan: Việc tách tài khoản và bật xác thực hai yếu tố thì phía nhà thầu hoàn thành trong tuần này.

## TOPIC | Thống nhất kế hoạch nghiệm thu giai đoạn 1 và vận hành chính thức IOC | Thống nhất vận hành thử 30 ngày từ 15/12, nghiệm thu giai đoạn 1 cuối tháng 1, khai trương IOC trước Tết; chuyển giao vận hành cho Trung tâm Chuyển đổi số tỉnh, đào tạo 12 cán bộ điều phối; đề xuất lùi khai trương sang sau Tết bị gạt.

@PM #k_quy: Nội dung cuối cùng là kế hoạch nghiệm thu. Phía nhà thầu đề xuất như sau: từ nay đến ngày 15 tháng 12 hoàn thành các nội dung đã chốt hôm nay; từ 15 tháng 12 đến 15 tháng 1 vận hành thử 30 ngày, có biên bản ghi nhận lỗi hằng tuần; nghiệm thu giai đoạn 1 vào cuối tháng 1; khai trương IOC trước Tết Nguyên đán. Song song là chuyển giao vận hành cho Trung tâm Chuyển đổi số của tỉnh, đào tạo 12 cán bộ điều phối và 4 kỹ sư quản trị hệ thống.

@BA #n_luitet: Anh Quý ơi, em thấy tiến độ hơi gấp, nhất là phần tổng đài 1022 và kết nối Cục Thuế phụ thuộc bên ngoài. Hay mình đề xuất lùi khai trương sang sau Tết cho chắc?

@SO #n_luitet2: Không lùi được. Khai trương IOC trước Tết là cam kết của lãnh đạo tỉnh với Bộ, đã có trong kế hoạch chuyển đổi số năm. Những phần phụ thuộc bên ngoài như tổng đài, kết nối thuế thì nếu chưa xong vẫn khai trương với các phân hệ đã sẵn sàng, phần còn lại đưa vào giai đoạn tiếp theo.

@SO #k_hai4: Về chuyển giao, Trung tâm Chuyển đổi số sẽ cử 12 cán bộ điều phối, nhưng hiện mới có 4 người ở Trung tâm điều hành, 8 người còn lại sẽ được điều động từ các sở. Đề nghị nhà thầu đào tạo thực hành trên hệ thống thật trong thời gian vận hành thử, không chỉ đào tạo lý thuyết.

@CA: Phía Công an đề nghị trong thời gian vận hành thử có một cán bộ công an trực tại IOC giờ hành chính để phối hợp xử lý cảnh báo an ninh trật tự và giao thông.

@SO: Anh Quý cho tôi biết rủi ro lớn nhất của tiến độ là gì, phân hệ nào có nguy cơ không kịp?

@PM #k_quy2: Dạ thưa anh, nhà thầu đánh giá có ba rủi ro chính. Rủi ro thứ nhất là tổng đài 1022, việc chuyển đầu số phụ thuộc Viễn thông tỉnh và phải có ý kiến của Cục Viễn thông về chuyển đổi số dịch vụ khẩn cấp, nếu thủ tục chậm thì có thể sang tháng 1 mới chuyển được. Rủi ro thứ hai là kết nối dữ liệu với Cục Thuế, phụ thuộc văn bản đồng ý của Cục Thuế và thời gian tích hợp ít nhất 3 tuần sau khi có đồng ý. Rủi ro thứ ba là kết quả kiểm tra lại an toàn thông tin của Trung tâm Giám sát, nếu phát hiện thêm lỗ hổng mới thì phải sửa tiếp. Các phân hệ còn lại gồm phản ánh qua ứng dụng, camera giao thông, camera an ninh, bản đồ quy hoạch và bảng điều khiển phần nội bộ thì nhà thầu cam kết kịp.

@BA: Em bổ sung về đào tạo. Kinh nghiệm ở các tỉnh khác là cán bộ điều phối luân chuyển nhiều, đào tạo xong vài tháng là chuyển công tác. Em đề xuất ngoài đào tạo trực tiếp thì nhà thầu làm thêm bộ video hướng dẫn ngắn theo từng tình huống, và một môi trường đào tạo riêng có dữ liệu giả để cán bộ mới thực hành mà không ảnh hưởng đến hệ thống thật.

@SO: Ý đó tốt. Môi trường đào tạo thì có trong hợp đồng chưa?

@PM: Dạ trong hợp đồng có hạng mục môi trường thử nghiệm, nhà thầu có thể dùng làm môi trường đào tạo, không phát sinh chi phí.

@CA: Về cán bộ trực, Công an đề nghị làm rõ quy trình khi IOC phát hiện sự việc an ninh trật tự thì cán bộ trực của IOC báo cho ai, qua kênh nào, trong bao lâu. Hiện nay chưa có quy trình phối hợp bằng văn bản, nếu xảy ra sự việc mà chậm báo thì trách nhiệm không rõ.

@SO #k_hai5: Quy trình phối hợp xử lý sự việc giữa Trung tâm điều hành và Công an thì Sở sẽ phối hợp với Công an tỉnh xây dựng, ban hành trước khi vận hành thử. Ngoài ra tôi nhấn mạnh tiêu chí nghiệm thu: không chỉ là chức năng chạy được, mà phải có số liệu vận hành thử 30 ngày, tỷ lệ phản ánh xử lý đúng hạn phải lên trên 80%, thời gian hệ thống hoạt động liên tục đạt trên 99,5%, không còn lỗ hổng mức cao, và cán bộ điều phối tự vận hành được không cần nhà thầu ngồi cạnh.

@PM: Nhà thầu ghi nhận các tiêu chí này, đề nghị Sở đưa vào biên bản để làm căn cứ nghiệm thu.

@PM #d_nghiemthu: Chốt: hoàn thành các nội dung đã thống nhất trước 15/12; vận hành thử 30 ngày từ 15/12; nghiệm thu giai đoạn 1 cuối tháng 1; khai trương trước Tết với các phân hệ đã sẵn sàng, phân hệ chưa xong chuyển giai đoạn sau; đào tạo thực hành 12 cán bộ điều phối và 4 kỹ sư quản trị trong thời gian vận hành thử; Công an cử cán bộ trực tại IOC.

@SO #a_canbo: Sở có văn bản đề nghị các sở cử 8 cán bộ điều phối, trước ngày 10 tháng 12.

@PM #a_daotao: Nhà thầu lập kế hoạch đào tạo thực hành chi tiết, gửi Sở tuần sau.

@CA #a_tructai: Công an tỉnh sẽ cử cán bộ trực tại IOC từ ngày 15 tháng 12.

@SO: Cảm ơn các anh chị. Khối lượng công việc còn nhiều, đề nghị nhà thầu tăng cường nhân lực, Sở sẽ họp kiểm tra hằng tuần vào sáng thứ Hai.

```json gold
{
  "assignments": [
    {"actor": "Anh Kha (Trưởng nhóm AI và thị giác máy tính)", "actor_aliases": ["em"], "task": "Đưa mô hình gợi ý đơn vị xử lý phản ánh lên môi trường chính thức kèm màn hình duyệt", "deadline": "hai tuần", "turns": ["a_goiy"]},
    {"actor": "Chị Phượng (Trưởng nhóm phân tích nghiệp vụ)", "actor_aliases": ["em"], "task": "Cấu hình 3 nhóm thời hạn xử lý và ràng buộc ảnh sau xử lý", "deadline": "sau khi Sở ban hành quy chế", "turns": ["a_thoihan"]},
    {"actor": "Đ/c Hải (Phó Giám đốc Sở Khoa học và Công nghệ)", "actor_aliases": ["Sở"], "task": "Trình UBND ban hành quy chế phân nhóm thời hạn xử lý phản ánh", "deadline": "trong tháng này", "turns": ["a_quyche"]},
    {"actor": "Anh Quý (Giám đốc dự án phía nhà thầu)", "actor_aliases": ["em"], "task": "Làm việc với Viễn thông tỉnh chuyển đổi đầu số 1022 sang tổng đài IP", "deadline": "trong tháng 12", "turns": ["a_tongdai"]},
    {"actor": "Anh Kha (Trưởng nhóm AI và thị giác máy tính)", "actor_aliases": ["nhóm em"], "task": "Làm chuyển giọng nói thành văn bản và gom nhóm phản ánh trùng", "deadline": "cùng lúc với tổng đài", "turns": ["a_stt"]},
    {"actor": "Anh Kha (Trưởng nhóm AI và thị giác máy tính)", "actor_aliases": ["bọn em"], "task": "Bổ sung từ điển khoảng 4.000 địa danh của tỉnh cho mô hình chuyển giọng nói thành văn bản", "deadline": null, "turns": ["k_kha1b"]},
    {"actor": "Trung tâm giám sát, điều hành đô thị thông minh", "actor_aliases": ["Trung tâm điều hành"], "task": "Bố trí trực luân phiên ngoài giờ tổng đài 1022 trong mùa mưa bão", "deadline": "trước mắt, mùa mưa bão", "turns": ["a_tructruc"]},
    {"actor": "Đ/c Hải (Phó Giám đốc Sở Khoa học và Công nghệ)", "actor_aliases": ["Sở"], "task": "Báo cáo UBND về vấn đề biên chế trực tổng đài 24/7", "deadline": "sau", "turns": ["a_tructruc"]},
    {"actor": "Anh Quý (Giám đốc dự án phía nhà thầu)", "actor_aliases": ["nhà thầu"], "task": "Chọn đèn hồng ngoại bước sóng 940 nm để hạn chế lóa camera hành trình", "deadline": null, "turns": ["a_buocsong"]},
    {"actor": "Anh Kha (Trưởng nhóm AI và thị giác máy tính)", "actor_aliases": ["em"], "task": "Lập danh sách 40 camera và dự toán đèn hồng ngoại gửi Sở", "deadline": "tuần sau", "turns": ["a_hongngoai"]},
    {"actor": "Đ/c Thiếu tá Bình (Phòng Tham mưu Công an tỉnh)", "actor_aliases": ["Công an tỉnh"], "task": "Cử 3 cán bộ CSGT được phân quyền xác nhận vi phạm, gửi danh sách cho Sở", "deadline": "trước ngày 20", "turns": ["a_canbo"]},
    {"actor": "Chị Diễm (Kỹ sư an toàn thông tin)", "actor_aliases": ["em"], "task": "Thiết kế phương án đường truyền riêng và mã hóa cho camera an ninh, gửi Công an tỉnh thẩm định", "deadline": "trước cuối tháng", "turns": ["a_duongtruyen"]},
    {"actor": "Anh Quý (Giám đốc dự án phía nhà thầu)", "actor_aliases": ["nhà thầu"], "task": "Chuyển 9 tài khoản xem camera an ninh của kỹ sư nhà thầu sang cấp quyền tạm thời có Công an phê duyệt", "deadline": null, "turns": ["a_quyentam"]},
    {"actor": "Anh Kha (Trưởng nhóm AI và thị giác máy tính)", "actor_aliases": ["em"], "task": "Cấu hình lại ngưỡng phát hiện tụ tập theo khung giờ, vị trí, chạy thử và báo cáo", "deadline": "hai tuần", "turns": ["a_nguong"]},
    {"actor": "Chị Phượng (Trưởng nhóm phân tích nghiệp vụ)", "actor_aliases": ["em"], "task": "Hoàn thiện danh mục 32 chỉ số cốt lõi kèm đơn vị chịu trách nhiệm và nguồn dữ liệu", "deadline": "trước thứ Sáu", "turns": ["a_danhmuc"]},
    {"actor": "Anh Quý (Giám đốc dự án phía nhà thầu)", "actor_aliases": ["phía nhà thầu"], "task": "Thêm nhãn số tạm tính/chính thức, thời điểm và nguồn cho từng chỉ số trên bảng điều khiển", "deadline": null, "turns": ["a_nhan"]},
    {"actor": "Đ/c Hải (Phó Giám đốc Sở Khoa học và Công nghệ)", "actor_aliases": ["Sở"], "task": "Tham mưu văn bản UBND đề nghị Cục Thuế chia sẻ dữ liệu", "deadline": "trong tháng này", "turns": ["a_cucthue"]},
    {"actor": "Anh Lợi (Trưởng nhóm GIS)", "actor_aliases": ["em"], "task": "Gửi danh sách 7 đồ án sai lệch kèm bản chồng lớp cho Sở Xây dựng", "deadline": "trong tuần này", "turns": ["a_danhsachqh"]},
    {"actor": "Đ/c Hải (Phó Giám đốc Sở Khoa học và Công nghệ)", "actor_aliases": ["Sở"], "task": "Có văn bản đề nghị Sở Xây dựng cử đầu mối xác nhận đồ án quy hoạch", "deadline": null, "turns": ["a_sxd"]},
    {"actor": "Anh Lợi (Trưởng nhóm GIS)", "actor_aliases": ["em"], "task": "Soạn chuẩn dữ liệu và mẫu biểu cung cấp dữ liệu công trình ngầm", "deadline": "trước ngày 25", "turns": ["a_chuan"]},
    {"actor": "Anh Lợi (Trưởng nhóm GIS)", "actor_aliases": ["bọn em"], "task": "Tích hợp bản đồ ngầm với quy trình cấp phép đào đường, tự cấp tài khoản tạm thời và trích lục tuyến cho nhà thầu", "deadline": null, "turns": ["a_capphep"]},
    {"actor": "Đ/c Hải (Phó Giám đốc Sở Khoa học và Công nghệ)", "actor_aliases": ["Sở"], "task": "Tham mưu văn bản UBND yêu cầu các doanh nghiệp (kể cả Điện lực) cung cấp dữ liệu ngầm", "deadline": "sau khi có chuẩn dữ liệu", "turns": ["a_vanbanngam"]},
    {"actor": "Chị Diễm (Kỹ sư an toàn thông tin)", "actor_aliases": ["em"], "task": "Kiểm tra lại lỗi API, máy chủ thử nghiệm; làm việc với hãng nâng cấp phần mềm camera", "deadline": "kiểm tra hôm nay, nâng cấp trước ngày 10 tháng 12", "turns": ["a_kiemtralai"]},
    {"actor": "Anh Quý (Giám đốc dự án phía nhà thầu)", "actor_aliases": ["nhà thầu"], "task": "Báo cáo bằng văn bản về sự việc lộ kho mã nguồn và rà soát quy định quản lý mã nguồn", "deadline": null, "turns": ["a_baocaosuco"]},
    {"actor": "Anh Quý (Giám đốc dự án phía nhà thầu)", "actor_aliases": ["phía nhà thầu"], "task": "Tách tài khoản quản trị và bật xác thực hai yếu tố", "deadline": "trong tuần này", "turns": ["a_taikhoan"]},
    {"actor": "Đ/c Hải (Phó Giám đốc Sở Khoa học và Công nghệ)", "actor_aliases": ["Sở"], "task": "Có văn bản đề nghị các sở cử 8 cán bộ điều phối", "deadline": "trước ngày 10 tháng 12", "turns": ["a_canbo"]},
    {"actor": "Anh Quý (Giám đốc dự án phía nhà thầu)", "actor_aliases": ["nhà thầu"], "task": "Lập kế hoạch đào tạo thực hành chi tiết gửi Sở", "deadline": "tuần sau", "turns": ["a_daotao"]},
    {"actor": "Đ/c Hải (Phó Giám đốc Sở Khoa học và Công nghệ)", "actor_aliases": ["Sở"], "task": "Phối hợp Công an tỉnh xây dựng, ban hành quy trình phối hợp xử lý sự việc giữa IOC và Công an", "deadline": "trước khi vận hành thử", "turns": ["k_hai5"]},
    {"actor": "Đ/c Thiếu tá Bình (Phòng Tham mưu Công an tỉnh)", "actor_aliases": ["Công an tỉnh"], "task": "Cử cán bộ trực tại IOC trong thời gian vận hành thử", "deadline": "từ ngày 15 tháng 12", "turns": ["a_tructai"]}
  ],
  "decisions": [
    {"text": "Mô hình gợi ý đơn vị xử lý phản ánh có cán bộ duyệt; thời hạn 3 nhóm 24 giờ/5 ngày/15 ngày; bắt buộc ảnh sau xử lý mới đóng; phản ánh an ninh trật tự và tố cáo cá nhân không công khai trên bản đồ", "turns": ["d_phananh", "k_hai1b"]},
    {"text": "Thay tổng đài cũ bằng tổng đài IP tích hợp IOC, ghi âm có thông báo, lưu tối đa 12 tháng; chuyển giọng nói thành văn bản làm bản nháp; gom phản ánh trùng 24 giờ với bán kính cấu hình theo lĩnh vực (mặc định 200 m); cơ sở tri thức cho điện thoại viên do các sở duyệt", "turns": ["d_1022", "d_bankinh"]},
    {"text": "Lắp đèn hồng ngoại cho 40 camera nút giao trọng điểm; cán bộ CSGT xác nhận vi phạm trước khi phạt nguội; loại trừ xe ưu tiên", "turns": ["d_giaothong"]},
    {"text": "Bỏ nhận diện khuôn mặt khỏi IOC; chỉ phát hiện sự việc; dữ liệu camera an ninh lưu tại Công an tỉnh, IOC chỉ nhận cảnh báo và ảnh đã làm mờ; nhật ký xem, trích xuất lưu tối thiểu 2 năm", "turns": ["d_anninh"]},
    {"text": "Giảm bảng điều khiển còn 32 chỉ số cốt lõi; kết nối tự động hệ thống thuế và đầu tư công; 8 chỉ số nhập tay có đơn vị chịu trách nhiệm; chi tiết đơn vị quá hạn chỉ hiện khi bấm vào; mỗi chỉ số có nguồn, thời điểm và nhãn tạm tính/chính thức", "turns": ["d_dashboard"]},
    {"text": "Chỉ công khai đồ án quy hoạch đã được Sở Xây dựng xác nhận; ẩn 7 đồ án sai lệch; cập nhật 12 đồ án điều chỉnh; có cảnh báo giá trị tham khảo; chỉ xem, tra cứu, in phiếu từng thửa, không cho tải dữ liệu vector", "turns": ["d_quyhoach"]},
    {"text": "Yêu cầu doanh nghiệp cung cấp dữ liệu công trình ngầm có cao độ trước 31/12, không cung cấp thì không cấp phép đào đường; bản đồ ngầm không công khai, phân quyền 3 mức (cơ quan quản lý / chủ sở hữu trong 50 m / nhà thầu có giấy phép tạm thời), có nhật ký; cáp chuyên dùng quản lý riêng theo chế độ mật", "turns": ["d_hatangngam"]},
    {"text": "Khắc phục 3 lỗ hổng cao trước 15/12, 11 lỗ hổng trung bình trước nghiệm thu; bỏ tài khoản dùng chung, bật xác thực hai yếu tố; kết nối SOC tỉnh", "turns": ["d_attt"]},
    {"text": "Vận hành thử 30 ngày từ 15/12; nghiệm thu giai đoạn 1 cuối tháng 1; khai trương trước Tết với phân hệ sẵn sàng; đào tạo thực hành 12 điều phối viên, 4 kỹ sư", "turns": ["d_nghiemthu"]}
  ],
  "negatives": [
    {"type": "hedged_proposal", "text": "Tự động mở lại phản ánh khi người dân đánh giá không hài lòng", "turns": ["n_molai"]},
    {"type": "hedged_proposal", "text": "Tổng đài ảo trả lời tự động câu hỏi thủ tục bằng AI", "turns": ["n_botauto", "n_botauto2"]},
    {"type": "hedged_proposal", "text": "Kiểm định 90 camera do IOC lắp (Sở xem xét đưa vào dự toán năm sau, chưa hứa)", "turns": ["n_kiemdinh"]},
    {"type": "hedged_proposal", "text": "Mở chức năng truy vết phương tiện theo biển số trên toàn bộ camera (chờ quy chế phối hợp)", "turns": ["n_bienso", "n_bienso2"]},
    {"type": "hedged_proposal", "text": "Đưa tính năng dự báo thu ngân sách, giải ngân lên bảng điều khiển lãnh đạo", "turns": ["n_dubao"]},
    {"type": "hedged_proposal", "text": "Cấp chứng chỉ quy hoạch tự động trực tuyến từ bản đồ số", "turns": ["n_giayphep"]},
    {"type": "hedged_proposal", "text": "Thời hạn bổ sung dữ liệu cho tuyến cáp nhánh cũ (chưa chốt)", "turns": ["n_lotrinh"]},
    {"type": "rejected_task", "text": "Chức năng nhận diện khuôn mặt trên camera an ninh trong IOC", "turns": ["k_binh2"]},
    {"type": "hedged_proposal", "text": "Thuê đơn vị kiểm thử xâm nhập quốc tế", "turns": ["n_pentest", "n_pentest2"]},
    {"type": "hedged_proposal", "text": "Lùi khai trương IOC sang sau Tết", "turns": ["n_luitet", "n_luitet2"]}
  ],
  "key_points": [
    {"speaker": "Chị Phượng (Trưởng nhóm phân tích nghiệp vụ)", "point": "Ứng dụng có 38.000 người dùng, 4.100 phản ánh/tháng, 31% chuyển sai đơn vị lần đầu", "turns": ["k_phuong1"]},
    {"speaker": "Anh Kha (Trưởng nhóm AI và thị giác máy tính)", "point": "Mô hình phân loại tự động đúng 86% so với 69% hiện nay, đề xuất gợi ý có người duyệt", "turns": ["k_kha1"]},
    {"speaker": "Đ/c Hải (Phó Giám đốc Sở Khoa học và Công nghệ)", "point": "Thời hạn theo 3 nhóm; bắt buộc ảnh sau xử lý", "turns": ["k_hai1"]},
    {"speaker": "Chị Phượng (Trưởng nhóm phân tích nghiệp vụ)", "point": "Phường nhận 58% phản ánh nhưng đúng hạn chỉ 64%; 1/3 phản ánh về phường phải chuyển tiếp doanh nghiệp công ích", "turns": ["k_phuong1b"]},
    {"speaker": "Anh Kha (Trưởng nhóm AI và thị giác máy tính)", "point": "Chuyển giọng nói thành văn bản lỗi 12%, giọng miền núi 20%, sai nhiều ở địa danh", "turns": ["k_kha1b"]},
    {"speaker": "Chị Phượng (Trưởng nhóm phân tích nghiệp vụ)", "point": "Tổng đài 1022 2.600 cuộc/tháng, nhập lại thủ công 4 phút/phản ánh, nhỡ 18% cuộc gọi giờ cao điểm", "turns": ["k_phuong2"]},
    {"speaker": "Anh Kha (Trưởng nhóm AI và thị giác máy tính)", "point": "120 camera giao thông; nhận diện biển số 94% ngày, 71% đêm; vượt đèn đỏ đúng 91%", "turns": ["k_kha2"]},
    {"speaker": "Đ/c Thiếu tá Bình (Phòng Tham mưu Công an tỉnh)", "point": "Kết quả AI phải được CSGT xác nhận mới làm căn cứ phạt", "turns": ["k_binh1"]},
    {"speaker": "Anh Kha (Trưởng nhóm AI và thị giác máy tính)", "point": "181/214 cảnh báo ùn tắc đúng; số liệu lưu lượng giúp chỉnh chu kỳ đèn 12 nút, giảm 25% thời gian xếp hàng", "turns": ["k_kha2b"]},
    {"speaker": "Đ/c Thiếu tá Bình (Phòng Tham mưu Công an tỉnh)", "point": "90 camera chưa kiểm định chỉ dùng để phát hiện, không làm căn cứ phạt nguội", "turns": ["k_binh1b"]},
    {"speaker": "Anh Kha (Trưởng nhóm AI và thị giác máy tính)", "point": "85 camera an ninh phát hiện tụ tập, xô xát, vật bỏ quên; nhận diện khuôn mặt đang tạm dừng", "turns": ["k_kha3"]},
    {"speaker": "Đ/c Thiếu tá Bình (Phòng Tham mưu Công an tỉnh)", "point": "Dữ liệu camera an ninh phải lưu tại Công an tỉnh; đề nghị bỏ nhận diện khuôn mặt khỏi IOC", "turns": ["k_binh2"]},
    {"speaker": "Chị Phượng (Trưởng nhóm phân tích nghiệp vụ)", "point": "Bảng điều khiển 64 chỉ số, 40% nhập tay, trễ 1-2 tháng", "turns": ["k_phuong3"]},
    {"speaker": "Đ/c Hải (Phó Giám đốc Sở Khoa học và Công nghệ)", "point": "Lãnh đạo chỉ cần khoảng 30 chỉ số cốt lõi chính xác, cập nhật", "turns": ["k_hai2"]},
    {"speaker": "Anh Lợi (Trưởng nhóm GIS)", "point": "Số hóa 41 đồ án quy hoạch; 7 đồ án lệch ranh giới tới 15 m; 12 đồ án chưa cập nhật điều chỉnh", "turns": ["k_loi1"]},
    {"speaker": "Anh Lợi (Trưởng nhóm GIS)", "point": "Số hóa 380 km cáp viễn thông, 210 km ống nước, 95 km cống; thiếu cao độ và hồ sơ hoàn công", "turns": ["k_loi2"]},
    {"speaker": "Đ/c Hải (Phó Giám đốc Sở Khoa học và Công nghệ)", "point": "Doanh nghiệp phải cung cấp dữ liệu ngầm trước 31/12, không thì không cấp phép đào đường", "turns": ["k_hai3"]},
    {"speaker": "Chị Diễm (Kỹ sư an toàn thông tin)", "point": "3 lỗ hổng cao, 11 trung bình; tài khoản quản trị dùng chung, chưa có xác thực hai yếu tố", "turns": ["k_diem"]},
    {"speaker": "Chị Diễm (Kỹ sư an toàn thông tin)", "point": "Lỗ hổng phần mềm camera điểm 9,8, cần nâng cấp dừng hệ thống 2 tiếng ban đêm", "turns": ["k_diem2"]},
    {"speaker": "Anh Quý (Giám đốc dự án phía nhà thầu)", "point": "Rủi ro tiến độ: chuyển đầu số 1022, kết nối Cục Thuế, kết quả kiểm tra lại ATTT", "turns": ["k_quy2"]},
    {"speaker": "Đ/c Hải (Phó Giám đốc Sở Khoa học và Công nghệ)", "point": "Tiêu chí nghiệm thu: đúng hạn trên 80%, hoạt động liên tục trên 99,5%, không còn lỗ hổng cao, cán bộ tự vận hành", "turns": ["k_hai5"]},
    {"speaker": "Anh Quý (Giám đốc dự án phía nhà thầu)", "point": "Đề xuất vận hành thử 30 ngày từ 15/12, nghiệm thu cuối tháng 1, khai trương trước Tết", "turns": ["k_quy"]},
    {"speaker": "Đ/c Hải (Phó Giám đốc Sở Khoa học và Công nghệ)", "point": "Khai trương trước Tết là cam kết; 8/12 cán bộ điều phối điều động từ các sở, cần đào tạo thực hành", "turns": ["k_hai4"]}
  ]
}
```
