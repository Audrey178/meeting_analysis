```json meta
{
  "meeting_id": "synth_010",
  "title": "Họp tiến độ dự án Hệ thống quản lý học tập LMS - Trường Đại học Kỹ thuật Miền Trung",
  "meeting_type": "software_project",
  "length_bucket": "M",
  "tags": ["topic_revisit", "rejected_task"],
  "revisits": {"3": 0},
  "speakers": {
    "PM": "Anh Trung (Quản lý dự án)",
    "KH": "TS. Hoàng (Phó Trưởng phòng Đào tạo)",
    "IT": "Anh Cường (Trung tâm CNTT nhà trường)",
    "BE": "Vũ (Trưởng nhóm Backend)",
    "FE": "Hà (Lập trình Frontend)",
    "QA": "Chị Oanh (Kiểm thử)"
  }
}
```

## TOPIC | Tích hợp đăng nhập một lần SSO với hệ thống quản lý đào tạo | Tích hợp SSO qua Keycloak với hệ thống đào tạo đã chạy nhưng khoảng 1.300 sinh viên khóa cũ không đăng nhập được do mã sinh viên trùng định dạng; thống nhất chuẩn hóa mã theo tiền tố khóa và chạy đồng bộ lại.

@PM: Chào thầy Hoàng, chào anh Cường và cả nhóm. Hôm nay họp tiến độ tháng, em đề nghị đi lần lượt: đăng nhập một lần, thi trực tuyến, báo cáo học tập, cuối cùng là kế hoạch học kỳ hai. Vũ báo cáo phần SSO trước nhé.

@BE #k_be1: Dạ. Phần đăng nhập một lần thì mình dùng Keycloak làm máy chủ xác thực, kết nối với cơ sở dữ liệu người dùng của hệ thống quản lý đào tạo của trường qua giao thức LDAP mà anh Cường cung cấp. Sinh viên, giảng viên đăng nhập một lần bằng tài khoản trường là vào được LMS, thư điện tử và cổng đào tạo luôn. Đến tuần trước thì đã chạy thử với khoảng 4.200 sinh viên khóa 2023 và 2024, và 380 giảng viên, đăng nhập ổn định, thời gian xác thực trung bình dưới một giây. Nhưng khi đồng bộ thêm các khóa cũ từ 2019 đến 2022 thì phát sinh lỗi, khoảng 1.300 sinh viên không đăng nhập được. Nguyên nhân là mã sinh viên các khóa trước 2021 được cấp theo định dạng cũ chỉ có bảy chữ số, và có hơn 200 trường hợp trùng mã với sinh viên hệ vừa làm vừa học, hai người khác nhau cùng một mã. Keycloak coi mã sinh viên là định danh duy nhất nên khi đồng bộ thì bản ghi sau đè bản ghi trước, thành ra sinh viên này đăng nhập lại vào tài khoản của sinh viên kia. Nhóm em đã phải tắt đồng bộ các khóa cũ ngay khi phát hiện.

@IT: Chuyện trùng mã thì bên tôi biết từ lâu, vì hệ vừa làm vừa học trước đây do trung tâm liên kết quản lý riêng, cấp mã riêng, sau này mới gộp dữ liệu về một hệ thống. Trong hệ thống quản lý đào tạo thì hai loại sinh viên này phân biệt bằng trường hệ đào tạo, nhưng cái mã hiển thị thì trùng. Việc sửa mã trên hệ thống quản lý đào tạo thì không làm được, vì mã sinh viên đã in trên thẻ, trên bảng điểm, trên văn bằng của những người đã tốt nghiệp.

@BE: Dạ vâng, nên em đề xuất là không sửa mã gốc, mà trong Keycloak mình dùng một định danh chuẩn hóa, ghép tiền tố hệ đào tạo và khóa vào trước mã sinh viên, ví dụ chính quy khóa 2020 là CQ20 cộng mã, vừa làm vừa học là VL20 cộng mã. Sinh viên vẫn đăng nhập bằng mã cũ, hệ thống sẽ hỏi thêm hệ đào tạo nếu mã đó bị trùng. Như vậy thì không đụng gì đến dữ liệu gốc.

@KH: Tôi thấy phương án này được. Nhưng tôi lưu ý là sinh viên khóa cũ nhiều em đang học lại, học cải thiện, và đặc biệt là khoảng 600 em khóa 2020 đang làm đồ án tốt nghiệp, học kỳ sau phải nộp đồ án trên LMS. Nếu các em không đăng nhập được thì rất phiền. Việc này phải xong trước khi bắt đầu học kỳ hai.

@QA: Chị bổ sung là khi chạy đồng bộ lại thì phải kiểm thử kỹ những tài khoản đã bị đè, vì có thể trong thời gian chạy thử đã có sinh viên đăng nhập nhầm vào tài khoản người khác và nộp bài, hoặc xem điểm. Chị đề nghị là rà soát log đăng nhập của khoảng 200 mã trùng trong hai tuần chạy thử, xem có trường hợp nào đã truy cập nhầm không, nếu có thì phải báo cáo nhà trường.

@BE: Dạ em xin nói rõ thêm về cách chạy đồng bộ lại để thầy Hoàng và anh Cường yên tâm. Bước một là em xuất toàn bộ danh sách sinh viên từ LDAP, gồm mã, họ tên, ngày sinh, hệ đào tạo, khóa, rồi chạy một đoạn kiểm tra tìm tất cả các mã xuất hiện nhiều hơn một lần. Theo số liệu sơ bộ thì có 214 mã bị trùng, liên quan 431 sinh viên, vì có vài mã trùng ba người. Bước hai là em sinh định danh chuẩn hóa cho toàn bộ sinh viên, không chỉ những người bị trùng, để sau này quy tắc thống nhất, sinh viên chính quy khóa 2021 trở về sau thì mã đã có tiền tố khóa sẵn nên định danh gần như giữ nguyên. Bước ba là xóa các bản ghi bị đè trong Keycloak và nhập lại theo định danh mới. Bước bốn là với các sinh viên bị trùng mã, lần đăng nhập đầu tiên hệ thống sẽ hiện màn hình chọn hệ đào tạo, chọn xong thì lưu lại, lần sau không hỏi nữa. Toàn bộ quá trình em sẽ chạy trên môi trường thử nghiệm trước, chị Oanh kiểm tra ngẫu nhiên khoảng một trăm tài khoản, đạt thì mới chạy trên môi trường thật, và chạy vào ban đêm để không ảnh hưởng người dùng. Thời gian chạy thật thì ước khoảng hai tiếng cho toàn bộ khoảng 18.000 tài khoản sinh viên các khóa. Về rủi ro thì nếu có sinh viên nào đã được giảng viên thêm vào lớp học phần trên LMS bằng tài khoản cũ bị đè, thì sau khi đồng bộ lại em phải ánh xạ lại tư cách thành viên lớp, bài nộp và điểm sang tài khoản mới, cái này em đã tính vào thời gian.

@IT: Tôi đề nghị thêm là trước khi chạy trên môi trường thật thì phải sao lưu toàn bộ cơ sở dữ liệu Keycloak và LMS, và bên dự án gửi cho tôi kịch bản khôi phục nếu có sự cố, vì đây là thao tác trên dữ liệu người dùng của toàn trường. Ngoài ra thì bên Trung tâm dữ liệu cũng cần biết trước lịch chạy để theo dõi tải máy chủ LDAP, vì xuất toàn bộ danh sách sẽ tạo tải khá lớn.

@PM #d_sso: Ok, chốt phương án định danh chuẩn hóa có tiền tố hệ và khóa như Vũ đề xuất, không sửa mã gốc. Vũ làm và chạy đồng bộ lại các khóa 2019 đến 2022, xong trước ngày 10 tháng 12. Chị Oanh rà soát log đăng nhập của các mã trùng trong thời gian chạy thử, có gì báo em để em báo thầy Hoàng.

@BE #a_sso: Dạ vâng anh.

@QA #a_log: Ok, trong tuần này chị rà xong.

## TOPIC | Xây dựng chức năng thi trực tuyến có giám sát | Chức năng thi trực tuyến trắc nghiệm đã chạy thử với 3 học phần; đề xuất tích hợp nhận diện khuôn mặt giám sát thi bị gạt do vướng quy định bảo vệ dữ liệu cá nhân và chi phí; thống nhất dùng trình duyệt khóa, xáo trộn câu hỏi và giám sát qua camera trực tiếp của giám thị.

@PM: Rồi, phần thi trực tuyến. Hà báo cáo đi em.

@FE #k_fe: Dạ. Chức năng thi trực tuyến thì hiện đã có đầy đủ cho hình thức trắc nghiệm, giảng viên tạo ngân hàng câu hỏi, cấu hình đề thi ngẫu nhiên theo ma trận độ khó, thời gian làm bài, số lần làm. Sinh viên làm bài trên trình duyệt, hết giờ thì tự nộp. Tháng vừa rồi đã chạy thử giữa kỳ cho ba học phần là Toán cao cấp, Vật lý đại cương và Tin học cơ sở, tổng cộng khoảng 2.100 lượt thi. Hệ thống chịu tải tốt, lúc cao điểm có khoảng 900 sinh viên thi đồng thời, thời gian phản hồi vẫn dưới hai giây. Lỗi thì có một số trường hợp sinh viên bị mất mạng giữa chừng, khi vào lại thì bài làm vẫn được lưu nhưng đồng hồ vẫn chạy, có em mất năm phút. Cái này em đã sửa cho phép giám thị cộng thêm thời gian cho từng sinh viên. Vấn đề lớn nhất mà các thầy cô phản ánh là gian lận. Kết quả thi giữa kỳ Toán cao cấp trực tuyến cao hơn hẳn so với thi giấy các năm trước, điểm trung bình cao hơn khoảng 1,8 điểm, các thầy nghi là sinh viên tra cứu, hỏi nhau qua điện thoại.

@KH: Đúng vậy, hội đồng khoa học của khoa Cơ bản đã có ý kiến là nếu không giải quyết được gian lận thì khoa không đồng ý thi cuối kỳ trực tuyến. Tôi cũng xin nói rõ là mục tiêu của nhà trường trong năm nay là chỉ thi trực tuyến giữa kỳ và các học phần tự chọn, còn thi cuối kỳ các học phần bắt buộc thì vẫn thi tập trung tại phòng máy.

@BE #n_faceid: Anh Trung, em có tìm hiểu một giải pháp là tích hợp nhận diện khuôn mặt để giám sát thi. Tức là trong khi thi thì webcam của sinh viên liên tục chụp ảnh, hệ thống so khớp với ảnh thẻ sinh viên, phát hiện người khác làm bài hộ, phát hiện sinh viên nhìn ra ngoài màn hình quá lâu, hoặc có người thứ hai xuất hiện. Có mấy dịch vụ nước ngoài cung cấp sẵn, tính phí theo lượt thi, khoảng 1 đến 2 đô la một lượt. Nhóm em có thể tích hợp trong khoảng sáu tuần.

@IT: Tôi thì tôi rất băn khoăn về cái này. Thứ nhất là ảnh khuôn mặt là dữ liệu sinh trắc học, theo Nghị định 13 và Luật Bảo vệ dữ liệu cá nhân thì là dữ liệu cá nhân nhạy cảm, phải có sự đồng ý rõ ràng của từng sinh viên, và nếu gửi ra dịch vụ nước ngoài thì còn phải làm hồ sơ đánh giá tác động chuyển dữ liệu ra nước ngoài nộp Bộ Công an. Thủ tục này rất phức tạp. Thứ hai là chi phí, mỗi học kỳ trường có khoảng 60.000 lượt thi, nếu một đô la một lượt thì đã hơn một tỷ rưỡi một năm, trường không có kinh phí này. Thứ ba là nhiều sinh viên ở nông thôn không có máy tính có webcam, làm bài bằng điện thoại.

@KH: Tôi đồng ý với anh Cường. Nhà trường sẽ không dùng nhận diện khuôn mặt trong năm nay.

@FE #n_batthuong: Dạ em bổ sung thêm là trong số các cách chống gian lận mà không cần camera, thì trên hệ thống hiện đã ghi lại khá nhiều dữ liệu có ích mà các thầy cô chưa dùng. Ví dụ là thời gian làm từng câu, số lần chuyển ra khỏi cửa sổ thi, thời điểm nộp bài, địa chỉ mạng. Khi em xem lại dữ liệu bài thi Toán cao cấp giữa kỳ thì thấy có những nhóm sinh viên nộp bài cách nhau chỉ vài giây, cùng địa chỉ mạng, và chọn sai giống hệt nhau ở những câu khó, rất có khả năng là làm chung. Có khoảng 70 trường hợp như vậy. Nếu mình làm một báo cáo bất thường sau mỗi kỳ thi, liệt kê các trường hợp nghi vấn cho giám thị và giảng viên xem xét, thì cũng có tác dụng răn đe, và không vướng vấn đề dữ liệu cá nhân nhạy cảm như ảnh khuôn mặt. Tuy vậy thì báo cáo này chỉ để tham khảo, không thể dùng làm căn cứ xử lý kỷ luật nếu không có bằng chứng khác.

@KH: Tôi thấy dữ liệu đó có giá trị. Việc xử lý vi phạm thì theo quy chế phải có biên bản của giám thị, nên báo cáo bất thường chỉ là để giám thị chú ý hơn. Nhưng trước mắt tôi muốn tập trung vào các biện pháp phòng ngừa đã, còn báo cáo bất thường thì để học kỳ sau tính.

@PM #d_thi: Ok, vậy bỏ phương án nhận diện khuôn mặt, nhóm mình không làm. Thay vào đó em chốt ba biện pháp làm được ngay. Một là bắt buộc dùng chế độ trình duyệt khóa khi thi, không cho mở tab khác, không cho sao chép dán, thoát ra là ghi nhận. Hai là mỗi sinh viên một đề riêng, xáo trộn cả thứ tự câu hỏi lẫn thứ tự đáp án. Ba là với thi giữa kỳ quan trọng thì chia phòng thi ảo, mỗi phòng tối đa 40 sinh viên có một giám thị giám sát qua camera trực tiếp bằng Google Meet như các trường khác đang làm. Hà làm trình duyệt khóa và xáo trộn đáp án, xong trước ngày 20 tháng 12.

@FE #a_thi: Dạ, em làm được anh.

@KH #a_quyche: Phòng Đào tạo sẽ ban hành quy chế thi trực tuyến giữa kỳ có quy định về giám sát qua camera và xử lý vi phạm, tôi phụ trách, trước khi bắt đầu học kỳ hai.

## TOPIC | Xây dựng chức năng báo cáo tiến độ học tập cho giảng viên và cố vấn học tập | Bảng điều khiển báo cáo đã có các chỉ số truy cập, nộp bài, điểm thành phần; thầy Hoàng yêu cầu thêm cảnh báo sớm sinh viên có nguy cơ trượt; thống nhất cảnh báo theo luật (vắng 3 buổi, không nộp 2 bài, điểm giữa kỳ dưới 4) gửi cố vấn học tập hằng tuần.

@PM: Tiếp theo là phần báo cáo học tập. Hà với Vũ cùng làm phần này, Hà trình bày giao diện nhé.

@FE #k_fe2: Dạ. Bảng điều khiển cho giảng viên hiện có các chỉ số cho từng lớp học phần: số sinh viên truy cập theo tuần, thời gian xem bài giảng video, tỷ lệ nộp bài tập đúng hạn, điểm các bài kiểm tra thành phần, và danh sách sinh viên chưa từng truy cập. Giảng viên có thể lọc theo nhóm, xuất ra Excel. Với cố vấn học tập thì có một bảng tổng hợp theo lớp sinh hoạt, xem được tình hình của từng sinh viên trên tất cả các học phần đang học. Dữ liệu cập nhật mỗi đêm. Hiện đã mở cho khoảng 40 giảng viên dùng thử, phản hồi chung là giao diện dễ dùng, nhưng nhiều thầy cô nói là có nhiều số liệu quá mà không biết nên làm gì với nó.

@KH #k_kh: Đúng vậy, và đây là cái tôi muốn nói. Mục tiêu của nhà trường khi làm LMS không phải để có thêm biểu đồ, mà để giảm tỷ lệ sinh viên bị cảnh báo học vụ và thôi học. Năm học vừa rồi trường có hơn 900 sinh viên bị cảnh báo học vụ, gần 300 em bị buộc thôi học, phần lớn là năm nhất và năm hai. Khi xem lại thì hầu hết các em đó đều có dấu hiệu từ rất sớm, vắng học nhiều, không nộp bài, nhưng cố vấn học tập thì không biết cho đến khi có điểm cuối kỳ thì đã muộn. Tôi muốn hệ thống phải có cảnh báo sớm, tự động báo cho cố vấn học tập những em có nguy cơ, để cố vấn gọi các em lên nói chuyện kịp thời.

@BE: Dạ về kỹ thuật thì có hai cách thầy ạ. Cách thứ nhất là dùng luật, ví dụ vắng quá ba buổi, không nộp quá hai bài tập liên tiếp, điểm giữa kỳ dưới 4, thì đánh dấu là có nguy cơ. Cách thứ hai là huấn luyện một mô hình dự đoán từ dữ liệu các năm trước, cho ra xác suất trượt của từng sinh viên. Cách thứ hai thì có thể chính xác hơn, nhưng cần dữ liệu lịch sử đầy đủ, mà LMS mới chạy được một học kỳ, dữ liệu hành vi học tập các năm trước thì không có, chỉ có điểm. Em nghĩ là trước mắt làm theo luật, dễ giải thích cho cố vấn học tập, sau hai ba học kỳ có dữ liệu thì mới làm mô hình.

@IT: Tôi đồng ý với Vũ. Với lại dùng luật thì cố vấn học tập hiểu ngay vì sao em này bị cảnh báo, còn mô hình mà nói xác suất bảy mươi phần trăm thì các thầy cô sẽ hỏi là tại sao, mình không trả lời được.

@QA: Chị lưu ý về dữ liệu điểm danh. Hiện nay điểm danh thì mỗi giảng viên làm một kiểu, có thầy điểm danh trên giấy, có thầy dùng ứng dụng riêng, chỉ khoảng một phần ba giảng viên điểm danh trên LMS. Nếu luật dựa vào số buổi vắng mà dữ liệu điểm danh không đầy đủ thì cảnh báo sẽ sai, em nào học lớp thầy điểm danh giấy thì không bao giờ bị cảnh báo vắng.

@KH: Việc điểm danh trên LMS thì Phòng Đào tạo sẽ yêu cầu bắt buộc từ học kỳ hai, tôi sẽ đưa vào văn bản hướng dẫn. Còn cảnh báo thì gửi cho cố vấn học tập hằng tuần, qua thư điện tử và thông báo trên LMS, kèm danh sách và lý do cảnh báo của từng em.

@KH: Tôi nói thêm về quy trình để bên dự án hiểu. Hiện nay mỗi lớp sinh hoạt có một cố vấn học tập, là giảng viên kiêm nhiệm, phụ trách khoảng 60 đến 80 sinh viên. Cố vấn học tập thì rất bận, nên nếu hệ thống gửi một danh sách quá dài hoặc cảnh báo quá nhiều thì các thầy cô sẽ bỏ qua. Theo kinh nghiệm của Phòng Đào tạo khi làm thủ công ở học kỳ trước, mỗi tuần mỗi lớp chỉ nên có khoảng ba đến năm em bị cảnh báo thì cố vấn mới xử lý được. Vì vậy ba tiêu chí của Vũ nêu thì tôi thấy hợp lý, nhưng cần theo dõi xem thực tế mỗi tuần ra bao nhiêu em, nếu quá nhiều thì điều chỉnh ngưỡng. Ngoài ra thì khi cố vấn đã gặp và trao đổi với sinh viên rồi thì phải có chỗ để ghi lại kết quả trao đổi, để tuần sau nếu em đó tiếp tục bị cảnh báo thì cố vấn biết là đã gặp rồi, và Phòng Đào tạo cũng có số liệu để đánh giá hiệu quả của hoạt động cố vấn. Hiện nay việc này làm trên sổ tay, cuối kỳ không tổng hợp được.

@FE: Dạ màn hình danh sách cảnh báo em sẽ có thêm cột trạng thái xử lý và ô ghi chú kết quả trao đổi cho cố vấn, cái này đơn giản thôi thầy.

@PM #d_canhbao: Ok, em chốt là làm cảnh báo sớm theo luật với ba tiêu chí: vắng từ ba buổi trở lên trong một học phần, không nộp hai bài tập liên tiếp, điểm giữa kỳ dưới 4. Gửi danh sách cho cố vấn học tập hằng tuần vào sáng thứ Hai qua thư điện tử và LMS, có ghi lý do. Chưa làm mô hình dự đoán trong năm nay. Vũ làm phần luật và gửi thông báo, Hà làm màn hình danh sách cảnh báo cho cố vấn, xong trước học kỳ hai.

@BE #a_canhbao: Dạ vâng.

@FE #a_manhinh: Dạ em làm luôn sau phần trình duyệt khóa.

@KH #a_diemdanh: Phòng Đào tạo sẽ có văn bản yêu cầu giảng viên điểm danh trên LMS bắt buộc từ học kỳ hai.

## TOPIC | Tích hợp đăng nhập một lần SSO với hệ thống quản lý đào tạo | Quay lại SSO: anh Cường báo lịch bảo trì máy chủ LDAP của trường trùng tuần thi, và yêu cầu bật xác thực hai yếu tố cho giảng viên; thống nhất lùi bảo trì LDAP, bật xác thực hai yếu tố cho tài khoản giảng viên và quản trị từ học kỳ hai.

@IT: Anh Trung ơi, trước khi sang kế hoạch học kỳ hai, tôi xin quay lại phần đăng nhập một lần một chút, vì tôi vừa nhận được lịch của Trung tâm dữ liệu. Máy chủ LDAP của trường có lịch bảo trì nâng cấp hệ điều hành vào tuần từ 15 đến 19 tháng 12, dự kiến dừng dịch vụ khoảng hai ngày. Mà theo như Vũ nói thì Keycloak đang xác thực trực tiếp với LDAP, tức là LDAP dừng thì toàn bộ sinh viên không đăng nhập được LMS. Tuần đó lại đúng là tuần thi giữa kỳ trực tuyến của một số học phần tự chọn.

@BE #k_be2: Dạ đúng anh, hiện tại Keycloak mỗi lần xác thực đều hỏi LDAP, không có bộ nhớ đệm. Có một cách là cấu hình Keycloak lưu bản sao thông tin người dùng và mật khẩu đã băm từ LDAP vào cơ sở dữ liệu của nó, khi LDAP không kết nối được thì vẫn xác thực được từ bản sao. Nhưng như vậy thì nếu có sinh viên đổi mật khẩu trong thời gian đó sẽ không đồng bộ, và về bảo mật thì mình đang giữ thêm một bản mật khẩu, anh Cường có đồng ý không?

@IT: Về nguyên tắc thì tôi không muốn có thêm một nơi lưu mật khẩu. Tôi nghĩ đơn giản nhất là tôi đề nghị Trung tâm dữ liệu lùi lịch bảo trì LDAP sang tuần sau thi, tức là sau ngày 22 tháng 12, cái này tôi làm được. Còn một việc nữa là về bảo mật, Ban Giám hiệu vừa có chỉ đạo là tất cả tài khoản có quyền nhập điểm và quản trị phải bật xác thực hai yếu tố, vì năm ngoái có một vụ lộ mật khẩu giảng viên và bị sửa điểm. Mà trên LMS thì giảng viên nhập điểm thành phần, nên cũng phải áp dụng.

@BE: Keycloak có sẵn xác thực hai yếu tố bằng ứng dụng OTP như Google Authenticator anh ạ, chỉ cần bật theo nhóm người dùng. Em có thể bật cho nhóm giảng viên và nhóm quản trị, còn sinh viên thì không bắt buộc.

@KH: Giảng viên lớn tuổi thì sẽ có một số thầy cô gặp khó khăn với ứng dụng OTP, cần có hướng dẫn và hỗ trợ.

@IT: Tôi nói thêm về vụ lộ mật khẩu năm ngoái để mọi người hiểu vì sao Ban Giám hiệu yêu cầu gấp. Năm ngoái có một giảng viên dùng chung mật khẩu tài khoản trường với một trang web bên ngoài, trang đó bị lộ dữ liệu, kẻ xấu lấy mật khẩu đăng nhập vào hệ thống quản lý đào tạo và sửa điểm của 14 sinh viên một học phần, đến khi giảng viên phát hiện thì đã gần một tháng. Nhà trường phải hủy kết quả, tổ chức thi lại, và có đơn vị công an vào làm việc. Từ đó Ban Giám hiệu yêu cầu tất cả tài khoản có quyền sửa dữ liệu điểm phải có xác thực hai yếu tố. Hệ thống quản lý đào tạo thì đã bật từ học kỳ trước, bây giờ đến lượt LMS vì LMS cũng có quyền nhập điểm thành phần và đồng bộ sang. Tỷ lệ giảng viên đã cài ứng dụng OTP cho hệ thống quản lý đào tạo hiện khoảng 85%, nên phần lớn thầy cô đã quen rồi, chỉ cần thêm một tài khoản nữa vào ứng dụng.

@PM #d_2fa: Ok, chốt hai việc. Một là không cấu hình lưu bản sao mật khẩu, anh Cường đề nghị Trung tâm dữ liệu lùi bảo trì LDAP sang sau ngày 22 tháng 12. Hai là bật xác thực hai yếu tố bắt buộc cho tài khoản giảng viên và quản trị trên Keycloak từ học kỳ hai, sinh viên không bắt buộc. Vũ cấu hình, Hà làm trang hướng dẫn cài ứng dụng OTP có hình ảnh từng bước.

@IT #a_ldap: Tôi sẽ làm việc với Trung tâm dữ liệu ngay trong tuần này.

@BE #a_2fa: Dạ em cấu hình, bật thử cho nhóm quản trị trước.

@FE #a_huongdan: Dạ em làm trang hướng dẫn.

## TOPIC | Thống nhất kế hoạch triển khai LMS cho học kỳ hai | Thống nhất mở LMS cho toàn bộ học phần đại cương và học phần của 3 khoa thí điểm từ học kỳ hai; tập huấn giảng viên trong tháng 1; nghiệm thu giai đoạn 1 vào cuối tháng 2.

@PM: Phần cuối là kế hoạch học kỳ hai. Thầy Hoàng cho bên em biết phạm vi nhà trường muốn triển khai ạ.

@KH #k_kh2: Kế hoạch của nhà trường là học kỳ hai sẽ triển khai LMS cho toàn bộ các học phần đại cương, khoảng 180 lớp học phần, và toàn bộ học phần của ba khoa thí điểm là Công nghệ thông tin, Điện tử viễn thông và Kinh tế, khoảng 320 lớp học phần nữa. Tổng cộng khoảng 500 lớp học phần, 12.000 sinh viên và 260 giảng viên. Các khoa khác thì học kỳ sau nữa. Yêu cầu là mỗi lớp học phần phải có đề cương, bài giảng và ít nhất các bài tập được đưa lên LMS, giảng viên nhập điểm thành phần trên LMS và đồng bộ sang hệ thống quản lý đào tạo.

@QA: Với quy mô 12.000 sinh viên thì chị đề nghị trước khi mở phải có một đợt kiểm thử hiệu năng mô phỏng khoảng 3.000 người dùng đồng thời, vì đầu học kỳ sinh viên đăng nhập dồn dập để xem thời khóa biểu và tài liệu. Đợt thi giữa kỳ vừa rồi mới có 900 người đồng thời.

@IT: Về hạ tầng thì hiện LMS chạy trên hai máy chủ ảo tại Trung tâm dữ liệu của trường. Nếu cần thêm tài nguyên thì phải có đề xuất sớm, vì cấp phát máy chủ mới mất khoảng hai tuần.

@BE: Dạ em ước với 3.000 người dùng đồng thời thì cần thêm một máy chủ ứng dụng nữa và tăng bộ nhớ cho máy chủ cơ sở dữ liệu. Em sẽ gửi anh Cường thông số cụ thể sau khi chạy kiểm thử hiệu năng thử trên môi trường hiện tại.

@KH: Về tập huấn thì Phòng Đào tạo sẽ tổ chức tập huấn cho 260 giảng viên trong tháng 1, chia theo khoa, mỗi buổi nửa ngày. Tôi đề nghị bên dự án cử người hướng dẫn và chuẩn bị tài liệu, video hướng dẫn ngắn cho từng chức năng chính.

@FE #n_chuyenma: Dạ về nội dung bài giảng thì em báo cáo thêm là hiện nay nhiều thầy cô gửi video bài giảng dung lượng rất lớn, có video một tiếng mà nặng gần 4 gigabyte, tải lên rất lâu và sinh viên xem bằng điện thoại thì tốn dung lượng mạng. Hệ thống có chức năng tự động chuyển mã video sang nhiều độ phân giải, nhưng quá trình chuyển mã chạy trên chính máy chủ ứng dụng nên khi nhiều thầy cô tải lên cùng lúc thì máy chủ bị chậm. Nếu học kỳ hai có 260 giảng viên tải bài giảng vào tuần đầu thì em lo là sẽ ảnh hưởng đến sinh viên đang dùng. Em nghĩ là trong thông số máy chủ gửi anh Cường thì nên tính thêm một máy chủ chuyển mã riêng, hoặc khuyến nghị thầy cô tải video lên trước học kỳ một tuần để rải tải.

@KH #a_taivideo: Việc tải bài giảng trước thì Phòng Đào tạo sẽ đưa vào yêu cầu, hạn cuối là một tuần trước khi bắt đầu học kỳ.

@PM #d_hk2: Ok, em chốt kế hoạch. Học kỳ hai mở LMS cho khoảng 500 lớp học phần gồm đại cương và ba khoa thí điểm như thầy Hoàng nói. Trước khi mở phải kiểm thử hiệu năng mô phỏng 3.000 người dùng đồng thời. Tập huấn giảng viên trong tháng 1. Nghiệm thu giai đoạn 1 vào cuối tháng 2 sau khi học kỳ hai chạy ổn định được ba tuần. Phân công như sau: chị Oanh làm kịch bản và chạy kiểm thử hiệu năng trước ngày 5 tháng 1. Vũ gửi thông số máy chủ cho anh Cường trước ngày 15 tháng 12 để anh Cường đề xuất cấp phát. Hà làm bộ video hướng dẫn ngắn cho giảng viên, khoảng mười video, xong trước ngày 10 tháng 1. Em thì em làm kế hoạch nghiệm thu gửi thầy Hoàng trong tháng 12.

@QA #a_hieunang: Ok chị làm.

@BE #a_thongso: Dạ em gửi anh Cường.

@IT #a_capphat: Nhận được thông số thì tôi làm đề xuất cấp phát luôn.

@FE #a_video: Dạ em làm video.

@KH #a_taphuan: Phòng Đào tạo lên lịch tập huấn gửi các khoa trước ngày 20 tháng 12. Cảm ơn anh Trung và cả nhóm.

@PM: Dạ cảm ơn thầy, cảm ơn mọi người.

```json gold
{
  "assignments": [
    {"actor": "Vũ (Trưởng nhóm Backend)", "actor_aliases": ["Vũ"], "task": "Làm định danh chuẩn hóa có tiền tố hệ và khóa trong Keycloak, chạy đồng bộ lại các khóa 2019-2022", "deadline": "trước 10/12", "turns": ["d_sso", "a_sso"]},
    {"actor": "Chị Oanh (Kiểm thử)", "actor_aliases": ["chị Oanh"], "task": "Rà soát log đăng nhập của các mã sinh viên trùng trong thời gian chạy thử", "deadline": "trong tuần này", "turns": ["d_sso", "a_log"]},
    {"actor": "Hà (Lập trình Frontend)", "actor_aliases": ["Hà"], "task": "Làm chế độ trình duyệt khóa và xáo trộn thứ tự câu hỏi, đáp án khi thi", "deadline": "trước 20/12", "turns": ["d_thi", "a_thi"]},
    {"actor": "TS. Hoàng (Phó Trưởng phòng Đào tạo)", "actor_aliases": ["Phòng Đào tạo", "tôi"], "task": "Ban hành quy chế thi trực tuyến giữa kỳ có giám sát qua camera và xử lý vi phạm", "deadline": "trước học kỳ hai", "turns": ["a_quyche"]},
    {"actor": "Vũ (Trưởng nhóm Backend)", "actor_aliases": ["Vũ"], "task": "Làm luật cảnh báo sớm và gửi thông báo cho cố vấn học tập", "deadline": "trước học kỳ hai", "turns": ["d_canhbao", "a_canhbao"]},
    {"actor": "Hà (Lập trình Frontend)", "actor_aliases": ["Hà"], "task": "Làm màn hình danh sách cảnh báo cho cố vấn học tập", "deadline": "trước học kỳ hai", "turns": ["d_canhbao", "a_manhinh"]},
    {"actor": "TS. Hoàng (Phó Trưởng phòng Đào tạo)", "actor_aliases": ["Phòng Đào tạo"], "task": "Ra văn bản yêu cầu giảng viên điểm danh trên LMS bắt buộc", "deadline": "từ học kỳ hai", "turns": ["a_diemdanh"]},
    {"actor": "Anh Cường (Trung tâm CNTT nhà trường)", "actor_aliases": ["anh Cường", "tôi"], "task": "Đề nghị Trung tâm dữ liệu lùi bảo trì LDAP sang sau 22/12", "deadline": "trong tuần này", "turns": ["d_2fa", "a_ldap"]},
    {"actor": "Vũ (Trưởng nhóm Backend)", "actor_aliases": ["Vũ", "em"], "task": "Cấu hình xác thực hai yếu tố bắt buộc cho giảng viên và quản trị trên Keycloak", "deadline": "từ học kỳ hai", "turns": ["d_2fa", "a_2fa"]},
    {"actor": "Hà (Lập trình Frontend)", "actor_aliases": ["Hà"], "task": "Làm trang hướng dẫn cài ứng dụng OTP", "deadline": null, "turns": ["d_2fa", "a_huongdan"]},
    {"actor": "Chị Oanh (Kiểm thử)", "actor_aliases": ["chị Oanh"], "task": "Làm kịch bản và chạy kiểm thử hiệu năng 3.000 người dùng đồng thời", "deadline": "trước 5/1", "turns": ["d_hk2", "a_hieunang"]},
    {"actor": "Vũ (Trưởng nhóm Backend)", "actor_aliases": ["Vũ"], "task": "Gửi thông số máy chủ cho anh Cường", "deadline": "trước 15/12", "turns": ["d_hk2", "a_thongso"]},
    {"actor": "Anh Cường (Trung tâm CNTT nhà trường)", "actor_aliases": ["anh Cường"], "task": "Làm đề xuất cấp phát máy chủ", "deadline": "khi nhận thông số", "turns": ["d_hk2", "a_capphat"]},
    {"actor": "Hà (Lập trình Frontend)", "actor_aliases": ["Hà"], "task": "Làm bộ khoảng 10 video hướng dẫn ngắn cho giảng viên", "deadline": "trước 10/1", "turns": ["d_hk2", "a_video"]},
    {"actor": "Anh Trung (Quản lý dự án)", "actor_aliases": ["em"], "task": "Làm kế hoạch nghiệm thu gửi thầy Hoàng", "deadline": "trong tháng 12", "turns": ["d_hk2"]},
    {"actor": "TS. Hoàng (Phó Trưởng phòng Đào tạo)", "actor_aliases": ["Phòng Đào tạo"], "task": "Đưa vào yêu cầu giảng viên tải bài giảng lên LMS chậm nhất một tuần trước học kỳ", "deadline": "một tuần trước học kỳ hai", "turns": ["a_taivideo"]},
    {"actor": "TS. Hoàng (Phó Trưởng phòng Đào tạo)", "actor_aliases": ["Phòng Đào tạo"], "task": "Lên lịch tập huấn giảng viên gửi các khoa", "deadline": "trước 20/12", "turns": ["a_taphuan"]}
  ],
  "decisions": [
    {"text": "Dùng định danh chuẩn hóa có tiền tố hệ đào tạo và khóa trong Keycloak, không sửa mã sinh viên gốc", "turns": ["d_sso"]},
    {"text": "Không dùng nhận diện khuôn mặt; dùng trình duyệt khóa, đề riêng xáo trộn câu hỏi/đáp án, phòng thi ảo ≤40 sinh viên có giám thị qua camera", "turns": ["d_thi"]},
    {"text": "Cảnh báo sớm theo luật (vắng ≥3 buổi, không nộp 2 bài liên tiếp, giữa kỳ <4), gửi cố vấn học tập sáng thứ Hai hằng tuần; chưa làm mô hình dự đoán", "turns": ["d_canhbao"]},
    {"text": "Không lưu bản sao mật khẩu trong Keycloak, lùi bảo trì LDAP; bật xác thực hai yếu tố bắt buộc cho giảng viên và quản trị từ học kỳ hai", "turns": ["d_2fa"]},
    {"text": "Học kỳ hai mở LMS cho khoảng 500 lớp học phần (đại cương + 3 khoa thí điểm), kiểm thử hiệu năng 3.000 người dùng trước khi mở, tập huấn tháng 1, nghiệm thu giai đoạn 1 cuối tháng 2", "turns": ["d_hk2"]}
  ],
  "negatives": [
    {"type": "rejected_task", "text": "Tích hợp nhận diện khuôn mặt giám sát thi bằng dịch vụ nước ngoài (khoảng 6 tuần)", "turns": ["n_faceid"]},
    {"type": "hedged_proposal", "text": "Làm báo cáo bất thường sau mỗi kỳ thi dựa trên dữ liệu hành vi làm bài (để học kỳ sau)", "turns": ["n_batthuong"]},
    {"type": "hedged_proposal", "text": "Thêm máy chủ chuyển mã video riêng", "turns": ["n_chuyenma"]}
  ],
  "key_points": [
    {"speaker": "Vũ (Trưởng nhóm Backend)", "point": "SSO Keycloak-LDAP chạy ổn với 4.200 sinh viên và 380 giảng viên, nhưng ~1.300 sinh viên khóa cũ lỗi do hơn 200 mã trùng với hệ vừa làm vừa học", "turns": ["k_be1"]},
    {"speaker": "Hà (Lập trình Frontend)", "point": "Thi thử trực tuyến 3 học phần, 2.100 lượt, 900 người đồng thời; điểm Toán cao hơn thi giấy ~1,8 điểm, nghi gian lận", "turns": ["k_fe"]},
    {"speaker": "TS. Hoàng (Phó Trưởng phòng Đào tạo)", "point": "Năm qua hơn 900 sinh viên bị cảnh báo học vụ, gần 300 thôi học; cần cảnh báo sớm cho cố vấn học tập", "turns": ["k_kh"]},
    {"speaker": "Vũ (Trưởng nhóm Backend)", "point": "Keycloak xác thực trực tiếp với LDAP không có bộ đệm, LDAP dừng thì không ai đăng nhập được", "turns": ["k_be2"]},
    {"speaker": "TS. Hoàng (Phó Trưởng phòng Đào tạo)", "point": "Học kỳ hai triển khai ~500 lớp học phần, 12.000 sinh viên, 260 giảng viên", "turns": ["k_kh2"]}
  ]
}
```
