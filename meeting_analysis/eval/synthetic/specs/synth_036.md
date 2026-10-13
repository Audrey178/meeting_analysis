```json meta
{
  "meeting_id": "synth_036",
  "title": "Họp sprint 9 dự án phần mềm quản lý chuỗi nhà thuốc Thiện Tâm",
  "meeting_type": "software_project",
  "length_bucket": "M",
  "split": "heldout",
  "tags": ["similar_adjacent_topics", "rejected_task", "hedged_proposal"],
  "speakers": {
    "PM": "Anh Đạt (Quản lý dự án)",
    "PO": "Chị Uyên (Giám đốc vận hành chuỗi nhà thuốc Thiện Tâm)",
    "DS": "Anh Tín (Dược sĩ phụ trách chuyên môn)",
    "BE": "Lộc (Backend)",
    "FE": "Ngân (Frontend)",
    "QA": "Chị Phượng (Kiểm thử)"
  }
}
```

## TOPIC | Kết nối liên thông đơn thuốc điện tử với hệ thống đơn thuốc quốc gia | Đã kết nối xong trên môi trường thử nghiệm nhưng khoảng 3% đơn tra không ra và cổng quốc gia chậm giờ cao điểm; thống nhất không chặn cứng, cho nhập tay mã đơn kèm ảnh đơn giấy, gửi dữ liệu bán theo lô 30 phút và cho bán thuốc thay thế cùng hoạt chất có ghi lý do.

@PM: Rồi, mình bắt đầu họp sprint 9 nhé. Hôm nay có năm nội dung: liên thông đơn thuốc điện tử, hai cái cảnh báo, ứng dụng tích điểm trên Zalo, và cuối cùng là kế hoạch chạy thí điểm. Chị Uyên với anh Tín bên chuỗi cũng dự, có gì góp ý trực tiếp luôn nhé. Lộc nói phần liên thông đơn thuốc trước.

@BE #k_loc1: Dạ. Phần liên thông với hệ thống đơn thuốc quốc gia thì em đã kết nối xong trên môi trường thử nghiệm. Luồng hiện tại là dược sĩ quét mã trên đơn thuốc của bệnh viện, hệ thống gọi sang cổng quốc gia lấy chi tiết đơn về, tự điền danh sách thuốc, liều dùng, số lượng vào màn hình bán. Bán xong thì mình phải gửi lại thông tin bán thuốc theo đơn lên cổng. Em chạy thử với khoảng 1.300 đơn mà chị Uyên gửi từ hai nhà thuốc thì có khoảng 3% đơn tra không ra, chủ yếu là đơn của các phòng khám tư nhỏ, họ chưa đăng ký mã cơ sở trên cổng hoặc in mã sai. Còn một vấn đề nữa là cổng quốc gia hay chậm vào giờ cao điểm buổi sáng, có lúc 15 đến 20 giây mới trả kết quả, dược sĩ đứng chờ thì khách sốt ruột.

@DS: Cái 3% không tra được đó thì ngoài thực tế bên anh vẫn phải bán. Đơn giấy hợp lệ, có chữ ký bác sĩ, có dấu phòng khám thì mình bán bình thường, chỉ là phải lưu đơn lại. Nên phần mềm không được chặn cứng.

@PO: Đúng rồi, chặn là nhân viên quay lại ghi sổ tay ngay, mấy tháng nay chị mới bỏ được sổ tay đấy. Bên chị chỉ cần là có lưu vết đầy đủ, lúc thanh tra Sở Y tế xuống thì xuất ra được trong vài phút.

@BE: Dạ, nên em đề xuất khi tra không được thì cho dược sĩ nhập tay mã đơn, chụp ảnh đơn giấy đính kèm, đơn đó đánh dấu trạng thái chờ đối chiếu. Còn phần gửi dữ liệu bán lên cổng thì không gửi từng đơn ngay lúc bán mà gom lại, cứ 30 phút gửi một lần, lỗi thì tự gửi lại, cuối ngày 23 giờ chạy một lượt rà những đơn chưa gửi được. Như vậy quầy bán không phải chờ cổng.

@QA: Chị hỏi thêm là trường hợp dược sĩ bán thuốc thay thế, ví dụ đơn ghi biệt dược này nhưng nhà thuốc hết, bán thuốc cùng hoạt chất của hãng khác, thì gửi lên cổng thế nào? Lúc chị test thì hệ thống báo lệch đơn và không cho lưu hóa đơn.

@DS #k_tin1: Cái đó theo quy định thì được thay thế cùng hoạt chất, cùng hàm lượng, cùng dạng bào chế, nhưng dược sĩ phải ghi rõ và người mua phải đồng ý. Phần mềm cần cho chọn thuốc thay thế từ danh sách cùng hoạt chất, bắt ghi lý do, và trên dữ liệu gửi cổng thì ghi cả thuốc trong đơn lẫn thuốc thực bán. Còn nhóm thuốc kê đơn nào bắt buộc phải quét đơn thì anh sẽ rà lại theo danh mục mới của Bộ, vì danh mục vừa sửa đổi.

@PM #d_lienthong: Ok, chốt phần này: không chặn cứng khi tra không được, cho nhập tay mã đơn, chụp ảnh đơn giấy, đánh dấu chờ đối chiếu. Dữ liệu bán gửi lên cổng theo lô 30 phút, có tự gửi lại và rà lúc 23 giờ. Cho phép bán thuốc thay thế cùng hoạt chất, cùng hàm lượng, bắt ghi lý do. Lộc làm phía backend phần nhập tay, gửi theo lô và thuốc thay thế, thứ Năm tuần sau xong nhé. Ngân làm màn hình chụp ảnh đơn với chọn thuốc thay thế.

@FE #a_chupdon: Dạ, màn hình chụp đơn với chọn thuốc thay thế em làm song song với Lộc, thứ Năm tuần sau ghép luôn.

@BE #a_lienthong: Dạ được anh, thứ Năm tuần sau em xong.

@DS #a_danhmuc: Danh mục thuốc kê đơn bắt buộc quét đơn thì anh gửi file cho Lộc trước ngày 20.

## TOPIC | Xây dựng chức năng cảnh báo thuốc cận hạn sử dụng | Tháng 9 chuỗi hủy khoảng 47 triệu tiền thuốc hết hạn do cảnh báo 90 ngày quá muộn, thông báo dài bị bỏ qua và quầy không xuất theo hạn dùng; thống nhất cảnh báo ba mức 180/90/30 ngày, bắt buộc gợi ý lô gần hạn nhất ở quầy, khóa bán thuốc dùng dài ngày còn dưới 30 ngày; đề xuất tự động giảm giá thuốc cận hạn để chờ pháp chế.

@PM: Sang hai cái cảnh báo. Cái thứ nhất là cảnh báo cận hạn sử dụng. Ngân trình bày nhé.

@FE #k_ngan1: Dạ. Cảnh báo cận hạn hiện tại thì hệ thống quét theo từng lô thuốc trong kho của mỗi nhà thuốc, lô nào còn dưới 90 ngày là hiện chấm đỏ trên màn hình tồn kho và gửi thông báo vào ứng dụng cho quản lý nhà thuốc. Nhưng chị Uyên có gửi số liệu là tháng 9 cả chuỗi vẫn phải hủy khoảng 47 triệu tiền thuốc hết hạn, nhiều nhất là siro trẻ em với thuốc nhỏ mắt. Em xem lại thì có mấy lý do. Thứ nhất là 90 ngày thì với thuốc bán chậm đã quá muộn, không kịp xoay. Thứ hai là thông báo gửi mỗi ngày một lần, danh sách dài cả trăm dòng, quản lý đọc không hết nên bỏ qua. Thứ ba là ở quầy bán, nhân viên lấy lô nào cũng được, hay lấy hộp mới nhập ở ngoài cùng, lô cũ nằm trong cùng thì cứ thế hết hạn.

@PO #k_uyen1: Chị đi kiểm tra mấy nhà thuốc thì đúng như vậy. Có nhà thuốc số 7 chị thấy ba hộp thuốc nhỏ mắt hết hạn từ tháng trước vẫn nằm trên kệ, may là khách chưa mua. Cái này mà Sở kiểm tra là phạt nặng, có thể bị đình chỉ.

@DS: Về nguyên tắc chuyên môn thì phải xuất theo hạn dùng, hết hạn trước thì xuất trước. Phần mềm nên ép chuyện này ở quầy chứ đừng để nhân viên tự nhớ.

@BE: Dạ phía backend em làm được, khi quét mã vạch sản phẩm thì hệ thống tự gợi ý lô có hạn gần nhất mà còn bán được. Nếu nhân viên chọn lô khác thì bắt nhập lý do. Còn cảnh báo thì em đề xuất chia ba mức, 180 ngày, 90 ngày và 30 ngày. Dưới 30 ngày thì khóa không cho bán nữa với các thuốc dùng dài ngày, vì khách mua về uống cả tháng thì hết hạn giữa chừng.

@DS #k_tin2: Khóa dưới 30 ngày thì anh đồng ý với thuốc dùng dài ngày như thuốc huyết áp, tiểu đường. Còn thuốc dùng ngắn ngày như kháng sinh 5 đến 7 ngày thì vẫn bán được, đừng khóa hết, không thì lại hủy nhiều hơn.

@PO #n_giamgia: Chị có ý thế này, các em xem được không. Hay là thuốc nào còn dưới 60 ngày thì hệ thống tự giảm giá 20% để đẩy hàng, đỡ phải hủy. Chị thấy mấy chuỗi khác cũng làm.

@DS #n_giamgia2: Cái đó chị phải cẩn thận. Thuốc kê đơn thì không được khuyến mại, giảm giá kiểu đó là vướng quy định về khuyến mại thuốc. Thực phẩm chức năng, mỹ phẩm thì có thể được. Chị nên hỏi bên pháp chế trước đã.

@PO: Ừ thôi, cái giảm giá thì để chị hỏi pháp chế đã, chưa làm vội. Các em cứ làm phần cảnh báo trước.

@PM #d_canhan: Vậy chốt cảnh báo cận hạn: ba mức 180, 90 và 30 ngày. Mức 180 ngày thì gom thành bản tóm tắt gửi mỗi tuần một lần, mức 90 và 30 ngày thì gửi hằng ngày, sắp theo giá trị tiền giảm dần để quản lý đọc phần quan trọng trước. Ở quầy bán bắt buộc gợi ý lô có hạn gần nhất, chọn lô khác phải ghi lý do. Thuốc dùng dài ngày còn dưới 30 ngày thì khóa bán. Danh sách nhóm thuốc dùng dài ngày thì anh Tín bổ sung luôn vào file danh mục gửi Lộc. Lộc làm phần gợi ý lô và khóa bán, Ngân làm lại màn hình cảnh báo và bản tóm tắt, chị Phượng test bằng dữ liệu lô thật.

@QA #a_testlo: Chị xin dữ liệu lô thật của hai nhà thuốc từ chị Uyên, dựng bộ test xong trước thứ Tư tuần sau.

@FE #a_canhbao: Dạ em làm màn hình ba mức với bản tóm tắt, cuối sprint này xong.

@BE #a_fefo: Phần gợi ý lô với khóa bán thì em làm sau phần liên thông, chắc sang đầu sprint 10 anh ạ.

@DS #a_daingay: Ừ, danh sách thuốc dùng dài ngày anh gộp chung một file với danh mục kê đơn, vẫn trước ngày 20.

## TOPIC | Xây dựng chức năng cảnh báo tồn kho thuốc dưới định mức và đề xuất nhập hàng | Định mức tối thiểu cố định 20 hộp khiến thuốc bán chạy báo muộn còn thuốc bán chậm báo nhiễu, tháng 9 có 212 lượt khách hỏi mua mà hết hàng; thống nhất định mức động theo bán trung bình 28 ngày, có hệ số mùa vụ, không tính lô đã khóa bán vào tồn khả dụng, mỗi sáng tạo một phiếu đề xuất nhập cho quản lý duyệt.

@PM: Rồi, sang cái cảnh báo thứ hai. Lộc nói nhé.

@BE #k_loc2: Dạ. Cảnh báo tồn kho dưới định mức thì hiện tại mỗi mã thuốc ở mỗi nhà thuốc có một con số định mức tối thiểu, đang để mặc định 20 hộp cho tất cả, quản lý nhà thuốc muốn thì tự sửa. Tồn xuống dưới định mức thì hệ thống bắn cảnh báo. Vấn đề là con số 20 cố định nên thuốc bán chạy như hạ sốt, siro ho thì báo quá muộn, hai ngày là hết sạch; còn thuốc bán chậm thì báo liên tục mà không cần nhập, quản lý bị nhiễu, tuần trước có nhà thuốc nhận hơn 300 cảnh báo trong một ngày. Thống kê tháng 9 thì có 212 lượt khách hỏi mua mà hết hàng, chủ yếu là thuốc hạ sốt và siro ho do đầu mùa cúm.

@PO #k_uyen2: Hết hàng thì chị tiếc nhất, khách sang nhà thuốc bên cạnh là mất luôn khách đó. Chị muốn hệ thống không chỉ báo mà còn đề xuất luôn cần nhập bao nhiêu, quản lý chỉ việc duyệt rồi gửi về kho tổng.

@BE: Dạ, em đề xuất định mức tính động: lấy lượng bán trung bình mỗi ngày trong 28 ngày gần nhất, nhân với số ngày từ lúc đặt đến lúc kho tổng giao hàng, cộng thêm số ngày dự phòng. Kho tổng giao cho nhà thuốc hiện là 2 ngày, dự phòng em để 5 ngày. Tồn xuống dưới con số đó thì tạo đề xuất nhập với số lượng đủ bán 14 ngày.

@DS: Có một điểm liên quan đến cái cảnh báo cận hạn lúc nãy: lô nào đã bị khóa bán vì còn dưới 30 ngày thì không được tính vào tồn khả dụng, không thì hệ thống tưởng còn hàng mà thực ra không bán được.

@QA: Chị thêm là mùa dịch thì bán trung bình 28 ngày sẽ đuổi không kịp. Năm ngoái đầu mùa cúm, lượng bán thuốc hạ sốt tăng gấp ba chỉ trong một tuần.

@PO: Thế thì cho chị một hệ số mùa vụ, bên chị chỉnh tay theo từng nhóm thuốc, ví dụ từ tháng 10 đến tháng 12 thì nhóm hạ sốt nhân 1,5.

@FE: Phía giao diện thì em nghĩ không nên gửi cảnh báo từng mã nữa, mà gom thành một phiếu đề xuất nhập mỗi sáng, quản lý mở ra sửa số lượng rồi bấm duyệt một lần.

@PM #d_tonkho: Ok, chốt cảnh báo tồn kho: bỏ định mức cố định 20 hộp, chuyển sang định mức động theo bán trung bình 28 ngày nhân thời gian giao 2 ngày cộng 5 ngày dự phòng, có hệ số mùa vụ theo nhóm thuốc do bên vận hành cấu hình. Tồn khả dụng không tính lô đã khóa bán. Không gửi cảnh báo từng mã nữa, mỗi sáng 7 giờ tạo một phiếu đề xuất nhập đủ bán 14 ngày cho quản lý nhà thuốc duyệt.

@BE #a_dinhmuc: Công thức định mức động với tạo phiếu đề xuất em làm luôn, xong trước ngày 30 tháng 10.

@PO #a_heso: Bảng hệ số mùa vụ cho từng nhóm thuốc thì chị gửi Lộc thứ Hai tuần sau.

## TOPIC | Xây dựng ứng dụng tích điểm khách hàng trên Zalo Mini App | Mini app đã xong đăng nhập và xem điểm; nhắc lịch uống thuốc tốn phí tin nhắn OA và cần đồng ý của khách; thống nhất đợt này chỉ làm tích điểm, lịch sử mua và nút liên hệ dược sĩ, tích điểm 10.000 đồng một điểm và không tính thuốc kê đơn; đề xuất làm chatbot AI tư vấn thuốc bị gạt.

@PM: Tiếp theo là ứng dụng tích điểm cho khách. Ngân nói.

@FE #k_ngan2: Dạ, phần này theo yêu cầu ban đầu là làm trên Zalo Mini App, khách quét mã QR ở quầy là vào được, không phải cài gì. Chức năng gồm tích điểm theo hóa đơn, xem lịch sử mua thuốc, và nhắc lịch uống thuốc. Em đã làm xong phần đăng nhập bằng số điện thoại Zalo, xem điểm và lịch sử mua. Còn tích điểm thì đang chờ API của Lộc. Vướng nhất là nhắc lịch uống thuốc, vì phải gửi qua tin nhắn Zalo OA, tính phí khoảng 200 đồng mỗi tin. Một khách uống thuốc ngày ba lần trong mười ngày là ba mươi tin, mà chuỗi mình hiện có khoảng 18.000 khách thành viên. Thêm nữa lịch uống thuốc là dữ liệu sức khỏe, phải có khách đồng ý thì mới được lưu.

@PO: Tích điểm thì chị cần nhất, vì chương trình thành viên cũ làm trên thẻ giấy đang loạn lắm. Quy tắc bên chị là 10.000 đồng được 1 điểm, 100 điểm đổi được phiếu giảm 50.000 đồng.

@DS #k_tin3: Anh lưu ý là không được tích điểm cho thuốc kê đơn, vì tích điểm đổi quà cũng là một hình thức khuyến mại. Chỉ tích trên thuốc không kê đơn, thực phẩm chức năng, dụng cụ y tế và mỹ phẩm thôi.

@BE #n_chatbot: Em có ý là nhân tiện làm mini app thì em tích hợp luôn một chatbot AI, khách nhập triệu chứng thì chatbot gợi ý thuốc không kê đơn phù hợp rồi cho đặt giữ hàng ở nhà thuốc gần nhất. Em dùng API mô hình ngôn ngữ có sẵn, chắc khoảng ba tuần là em làm xong.

@DS #n_chatbot2: Cái này anh không đồng ý. Tư vấn chọn thuốc theo triệu chứng là việc của dược sĩ. Máy gợi ý sai một cái, khách đang có thai hay dị ứng uống vào thì chuỗi chịu trách nhiệm. Bên anh không ký duyệt chuyên môn cho cái đó được.

@PM #n_chatbot3: Anh cũng gạt cái chatbot nhé Lộc, không làm. Sprint này còn liên thông với hai cái cảnh báo chưa xong. Khách cần hỏi thì mini app có nút gọi hoặc nhắn trực tiếp cho dược sĩ của nhà thuốc là đủ.

@QA: Còn nhắc lịch uống thuốc thì có làm trong đợt này không anh? Chị cần biết để viết kịch bản test.

@PO: Nhắc uống thuốc thì để đợt sau đi, chị cần tích điểm chạy được trước Tết.

@PM #d_miniapp: Chốt: đợt này mini app chỉ có tích điểm, xem lịch sử mua và nút liên hệ dược sĩ. Tích điểm 10.000 đồng một điểm, chỉ tính trên hàng không kê đơn. Nhắc lịch uống thuốc chuyển sang giai đoạn 2. Ngân hoàn thiện mini app, Lộc làm API tích điểm có loại trừ thuốc kê đơn.

@BE #a_apidiem: Dạ, API tích điểm em làm, có cờ loại trừ theo nhóm thuốc, anh Tín đánh dấu sẵn nhóm kê đơn trong danh mục là được.

@FE #a_miniapp: Mini app em hoàn thiện, ngày 27 em đưa bản thử cho chị Phượng.

## TOPIC | Rà soát kết quả kiểm thử và kế hoạch triển khai thí điểm tại 6 nhà thuốc | Kiểm thử chấp nhận ghi nhận 41 lỗi, còn 23 lỗi mở trong đó 4 lỗi nghiêm trọng; thống nhất thí điểm tại 6 nhà thuốc từ thứ Hai 2/11, chạy song song phần mềm cũ 2 tuần, đóng 4 lỗi nghiêm trọng trước 28/10 và đào tạo nhân viên thứ Bảy 31/10.

@PM: Cuối cùng là kế hoạch thí điểm. Chị Phượng báo tình hình kiểm thử trước nhé.

@QA #k_phuong: Chị chạy kiểm thử chấp nhận với nhóm dược sĩ ở hai nhà thuốc trong tuần vừa rồi, tổng cộng ghi nhận 41 lỗi, đã đóng 18, còn 23 lỗi mở. Trong đó có 4 lỗi nghiêm trọng: in hóa đơn trên máy in nhiệt khổ 58 mi li mét bị cắt mất cột thành tiền; trả hàng không cộng lại tồn kho đúng lô; tính sai tiền thối khi khách trả bằng hai hình thức, nửa tiền mặt nửa chuyển khoản; và mất dữ liệu đơn khi mất mạng giữa chừng. Lỗi mất mạng là nặng nhất, vì nhà thuốc ở ngoại thành mạng hay chập chờn.

@BE: Lỗi mất mạng thì em đang làm chế độ lưu tạm trên máy bán hàng, có mạng lại thì tự đồng bộ. Lỗi trả hàng sai lô là do phần của em, hai ngày là em sửa xong.

@PO #k_uyen3: Bên chị đề xuất thí điểm 6 nhà thuốc, gồm 4 nhà thuốc trong nội thành và 2 nhà thuốc ngoại thành để thử luôn chuyện mạng yếu. Nhân viên ca sáng với ca chiều đều phải được đào tạo, nên buổi đào tạo phải làm vào thứ Bảy, các nhà thuốc xếp người trực thay.

@DS #k_tin4: Anh đề nghị thời gian đầu chạy song song với phần mềm cũ, vì báo cáo Sở Y tế tháng 11 vẫn phải xuất từ phần mềm cũ cho chắc. Chạy song song thì nhân viên nhập hai lần, vất vả, nhưng chỉ hai tuần thôi.

@PM #d_thidiem: Chốt kế hoạch: thí điểm ở 6 nhà thuốc, 4 nội thành và 2 ngoại thành, bắt đầu thứ Hai ngày 2 tháng 11, chạy song song với phần mềm cũ 2 tuần. Bốn lỗi nghiêm trọng phải đóng hết trước ngày 28 tháng 10, không đóng được thì lùi ngày thí điểm. Đào tạo nhân viên vào thứ Bảy ngày 31 tháng 10.

@PO #a_chonnt: Danh sách 6 nhà thuốc với danh sách nhân viên đi đào tạo thì chị chốt, gửi anh Đạt thứ Sáu tuần này.

@DS #a_tailieu: Tài liệu hướng dẫn phần nghiệp vụ dược thì anh soạn, có cả video ngắn cho từng thao tác bán theo đơn, xong trước buổi đào tạo.

@PM: Ok, cảm ơn cả nhà, tuần này nhiều việc, cố lên nhé.

```json gold
{
  "assignments": [
    {"actor": "Lộc (Backend)", "actor_aliases": ["Lộc", "em"], "task": "Làm phía backend liên thông đơn thuốc: nhập tay mã đơn, gửi dữ liệu bán theo lô 30 phút, bán thuốc thay thế", "deadline": "thứ Năm tuần sau", "turns": ["d_lienthong", "a_lienthong"]},
    {"actor": "Ngân (Frontend)", "actor_aliases": ["Ngân", "em"], "task": "Làm màn hình chụp ảnh đơn giấy và chọn thuốc thay thế", "deadline": "thứ Năm tuần sau", "turns": ["d_lienthong", "a_chupdon"]},
    {"actor": "Anh Tín (Dược sĩ phụ trách chuyên môn)", "actor_aliases": ["anh Tín", "anh"], "task": "Gửi Lộc file danh mục thuốc kê đơn bắt buộc quét đơn, gộp cả danh sách thuốc dùng dài ngày", "deadline": "trước ngày 20", "turns": ["a_danhmuc", "d_canhan", "a_daingay"]},
    {"actor": "Chị Phượng (Kiểm thử)", "actor_aliases": ["chị Phượng", "chị"], "task": "Dựng bộ test cảnh báo cận hạn bằng dữ liệu lô thật của hai nhà thuốc", "deadline": "trước thứ Tư tuần sau", "turns": ["d_canhan", "a_testlo"]},
    {"actor": "Ngân (Frontend)", "actor_aliases": ["Ngân", "em"], "task": "Làm lại màn hình cảnh báo cận hạn ba mức và bản tóm tắt", "deadline": "cuối sprint này", "turns": ["d_canhan", "a_canhbao"]},
    {"actor": "Lộc (Backend)", "actor_aliases": ["Lộc", "em"], "task": "Làm gợi ý lô có hạn gần nhất ở quầy và khóa bán thuốc dùng dài ngày dưới 30 ngày", "deadline": "đầu sprint 10", "turns": ["d_canhan", "a_fefo"]},
    {"actor": "Lộc (Backend)", "actor_aliases": ["em"], "task": "Làm công thức định mức tồn kho động và tạo phiếu đề xuất nhập hằng sáng", "deadline": "trước ngày 30/10", "turns": ["a_dinhmuc"]},
    {"actor": "Chị Uyên (Giám đốc vận hành chuỗi nhà thuốc Thiện Tâm)", "actor_aliases": ["chị"], "task": "Gửi Lộc bảng hệ số mùa vụ theo nhóm thuốc", "deadline": "thứ Hai tuần sau", "turns": ["a_heso"]},
    {"actor": "Lộc (Backend)", "actor_aliases": ["Lộc", "em"], "task": "Làm API tích điểm có loại trừ thuốc kê đơn", "deadline": null, "turns": ["d_miniapp", "a_apidiem"]},
    {"actor": "Ngân (Frontend)", "actor_aliases": ["Ngân", "em"], "task": "Hoàn thiện Zalo Mini App tích điểm, đưa bản thử cho chị Phượng", "deadline": "ngày 27", "turns": ["d_miniapp", "a_miniapp"]},
    {"actor": "Chị Uyên (Giám đốc vận hành chuỗi nhà thuốc Thiện Tâm)", "actor_aliases": ["chị"], "task": "Chốt danh sách 6 nhà thuốc thí điểm và nhân viên đi đào tạo, gửi anh Đạt", "deadline": "thứ Sáu tuần này", "turns": ["a_chonnt"]},
    {"actor": "Anh Tín (Dược sĩ phụ trách chuyên môn)", "actor_aliases": ["anh"], "task": "Soạn tài liệu hướng dẫn nghiệp vụ dược kèm video thao tác", "deadline": "trước buổi đào tạo (31/10)", "turns": ["a_tailieu"]}
  ],
  "decisions": [
    {"text": "Không chặn cứng khi tra đơn không được: nhập tay mã đơn, chụp ảnh đơn giấy, đánh dấu chờ đối chiếu; gửi dữ liệu bán lên cổng theo lô 30 phút, tự gửi lại, rà lúc 23 giờ; cho bán thuốc thay thế cùng hoạt chất, cùng hàm lượng, bắt ghi lý do", "turns": ["d_lienthong"]},
    {"text": "Cảnh báo cận hạn ba mức 180/90/30 ngày (180 ngày tóm tắt hằng tuần, 90 và 30 ngày hằng ngày, sắp theo giá trị); bắt buộc gợi ý lô hạn gần nhất ở quầy, chọn lô khác phải ghi lý do; khóa bán thuốc dùng dài ngày còn dưới 30 ngày", "turns": ["d_canhan"]},
    {"text": "Bỏ định mức cố định 20 hộp, dùng định mức động theo bán trung bình 28 ngày × (2 ngày giao + 5 ngày dự phòng) kèm hệ số mùa vụ; không tính lô đã khóa bán vào tồn khả dụng; mỗi sáng 7 giờ tạo một phiếu đề xuất nhập đủ bán 14 ngày cho quản lý duyệt", "turns": ["d_tonkho"]},
    {"text": "Mini app đợt này chỉ gồm tích điểm, lịch sử mua và nút liên hệ dược sĩ; 10.000 đồng một điểm, chỉ tính hàng không kê đơn; nhắc lịch uống thuốc chuyển sang giai đoạn 2", "turns": ["d_miniapp"]},
    {"text": "Thí điểm tại 6 nhà thuốc (4 nội thành, 2 ngoại thành) từ thứ Hai 2/11, chạy song song phần mềm cũ 2 tuần; đóng 4 lỗi nghiêm trọng trước 28/10, không kịp thì lùi; đào tạo nhân viên thứ Bảy 31/10", "turns": ["d_thidiem"]}
  ],
  "negatives": [
    {"type": "hedged_proposal", "text": "Tự động giảm giá 20% thuốc còn dưới 60 ngày hạn dùng (chờ hỏi pháp chế, chưa làm)", "turns": ["n_giamgia", "n_giamgia2"]},
    {"type": "rejected_task", "text": "Lộc tích hợp chatbot AI tư vấn thuốc theo triệu chứng trong mini app", "turns": ["n_chatbot", "n_chatbot2", "n_chatbot3"]}
  ],
  "key_points": [
    {"speaker": "Lộc (Backend)", "point": "Liên thông đơn thuốc đã chạy trên môi trường thử nghiệm; khoảng 3% trong 1.300 đơn tra không ra; cổng quốc gia chậm 15-20 giây giờ cao điểm", "turns": ["k_loc1"]},
    {"speaker": "Anh Tín (Dược sĩ phụ trách chuyên môn)", "point": "Không được chặn cứng đơn giấy hợp lệ; thuốc thay thế phải cùng hoạt chất, hàm lượng, dạng bào chế và ghi rõ", "turns": ["k_tin1"]},
    {"speaker": "Ngân (Frontend)", "point": "Tháng 9 hủy khoảng 47 triệu tiền thuốc hết hạn do cảnh báo 90 ngày quá muộn, thông báo dài bị bỏ qua, quầy không xuất theo hạn dùng", "turns": ["k_ngan1"]},
    {"speaker": "Chị Uyên (Giám đốc vận hành chuỗi nhà thuốc Thiện Tâm)", "point": "Phát hiện thuốc nhỏ mắt hết hạn vẫn trên kệ, rủi ro bị phạt hoặc đình chỉ", "turns": ["k_uyen1"]},
    {"speaker": "Anh Tín (Dược sĩ phụ trách chuyên môn)", "point": "Chỉ khóa bán thuốc dùng dài ngày dưới 30 ngày, không khóa thuốc ngắn ngày; giảm giá thuốc kê đơn vướng quy định khuyến mại", "turns": ["k_tin2", "n_giamgia2"]},
    {"speaker": "Lộc (Backend)", "point": "Định mức cố định 20 hộp gây báo muộn với thuốc bán chạy và hơn 300 cảnh báo/ngày; tháng 9 có 212 lượt khách hỏi mua mà hết hàng", "turns": ["k_loc2"]},
    {"speaker": "Chị Uyên (Giám đốc vận hành chuỗi nhà thuốc Thiện Tâm)", "point": "Muốn hệ thống đề xuất luôn số lượng cần nhập để quản lý duyệt; cần hệ số mùa vụ", "turns": ["k_uyen2"]},
    {"speaker": "Ngân (Frontend)", "point": "Mini app đã xong đăng nhập, xem điểm, lịch sử; nhắc uống thuốc tốn phí tin OA khoảng 200 đồng/tin và cần khách đồng ý", "turns": ["k_ngan2"]},
    {"speaker": "Anh Tín (Dược sĩ phụ trách chuyên môn)", "point": "Không tích điểm cho thuốc kê đơn; không chấp nhận chatbot tư vấn thuốc theo triệu chứng", "turns": ["k_tin3", "n_chatbot2"]},
    {"speaker": "Chị Phượng (Kiểm thử)", "point": "UAT ghi nhận 41 lỗi, còn 23 lỗi mở, 4 lỗi nghiêm trọng, nặng nhất là mất dữ liệu đơn khi mất mạng", "turns": ["k_phuong"]},
    {"speaker": "Chị Uyên (Giám đốc vận hành chuỗi nhà thuốc Thiện Tâm)", "point": "Thí điểm 6 nhà thuốc gồm 4 nội thành, 2 ngoại thành; đào tạo vào thứ Bảy", "turns": ["k_uyen3"]},
    {"speaker": "Anh Tín (Dược sĩ phụ trách chuyên môn)", "point": "Chạy song song với phần mềm cũ 2 tuần vì báo cáo Sở Y tế tháng 11", "turns": ["k_tin4"]}
  ]
}
```
