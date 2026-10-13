```json meta
{
  "meeting_id": "synth_014",
  "title": "Họp rà soát tiến độ dự án Cổng dịch vụ công trực tuyến ngành giáo dục tỉnh Hòa Bình Tây",
  "meeting_type": "software_project",
  "length_bucket": "M",
  "tags": ["unknown_speaker", "hedged_proposal"],
  "speakers": {
    "PM": "Chị Thu (Quản lý dự án)",
    "BA": "Anh Khải (Phân tích nghiệp vụ)",
    "BE": "Đức (Trưởng nhóm Backend)",
    "QA": "Hằng (Kiểm thử)",
    "SO": "Thầy Bình (Phó Giám đốc Sở Giáo dục)",
    "UNK": "Người nói không xác định"
  },
  "identity_note": "Các lượt UNK là kỹ sư hạ tầng Hải (được gọi tên ở chủ đề 3) và một người trong nhóm Frontend (chủ đề 2); STT không gán được tên."
}
```

## TOPIC | Xây dựng chức năng nộp hồ sơ tuyển sinh đầu cấp trực tuyến | Chức năng nộp hồ sơ tuyển sinh lớp 1 và lớp 6 đã xong luồng chính; Sở yêu cầu bổ sung xác thực cư trú qua cơ sở dữ liệu dân cư thay cho upload sổ hộ khẩu; thống nhất tích hợp VNeID qua trục liên thông của tỉnh, đề xuất cho phụ huynh chọn nhiều nguyện vọng chưa được chấp nhận.

@PM: Chào cả nhà, chào thầy Bình. Hôm nay mình rà soát bốn hạng mục: tuyển sinh đầu cấp, tra cứu và cấp bản sao văn bằng, hạ tầng và bảo mật trước đợt cao điểm, cuối cùng là thống nhất kế hoạch tháng tới. Em xin mời anh Khải trình bày trước phần tuyển sinh đầu cấp vì cái này thầy Bình quan tâm nhất, tháng sáu là bắt đầu mở cổng rồi.

@BA #k_khai1: Dạ cảm ơn chị Thu, kính thưa thầy Bình. Về chức năng nộp hồ sơ tuyển sinh đầu cấp thì nhóm đã hoàn thành luồng chính cho hai cấp là lớp 1 và lớp 6. Luồng gồm các bước: phụ huynh đăng nhập bằng tài khoản dịch vụ công, khai thông tin học sinh, chọn trường theo tuyến, đính kèm giấy tờ, ký xác nhận và nộp. Sau khi nộp thì hồ sơ đi về hàng đợi của trường, cán bộ trường duyệt hoặc trả lại yêu cầu bổ sung, phụ huynh nhận thông báo qua tin nhắn và qua ứng dụng. Phần phân tuyến thì đang dùng bảng ánh xạ từ tổ dân phố, thôn xóm sang trường, do các Phòng Giáo dục cấp huyện cung cấp, hiện đã có dữ liệu của chín trên mười một huyện, còn hai huyện Lạc Sơn và Kim Bôi chưa gửi bảng tuyến. Ngoài ra thì có chức năng thống kê số hồ sơ theo trường theo ngày để Sở theo dõi.

@BA: Về giấy tờ đính kèm thì hiện tại phụ huynh phải chụp và tải lên giấy khai sinh, sổ hộ khẩu hoặc giấy xác nhận cư trú, và với lớp 6 thì thêm học bạ tiểu học. Nhóm em đã làm phần nén ảnh phía trình duyệt để giảm dung lượng, mỗi ảnh còn khoảng 300 KB, vì năm ngoái hệ thống cũ bị nghẽn chủ yếu do phụ huynh tải ảnh chụp điện thoại 5, 6 MB. Phần kiểm tra trùng hồ sơ thì đang kiểm tra theo mã định danh cá nhân của học sinh, một học sinh chỉ được nộp vào một trường trong một đợt.

@SO #k_binh1: Cảm ơn anh Khải. Tôi có một ý quan trọng. Từ năm nay sổ hộ khẩu giấy không còn giá trị nữa, Bộ Công an đã bỏ sổ hộ khẩu từ năm 2023, nên yêu cầu phụ huynh chụp sổ hộ khẩu là không đúng, mà giấy xác nhận cư trú thì phụ huynh lại phải lên công an phường xin, rất phiền. Năm ngoái hàng nghìn phụ huynh xếp hàng ở công an phường chỉ để xin giấy xác nhận cư trú đi nộp hồ sơ cho con. Chỉ đạo của Ủy ban tỉnh là các thủ tục phải khai thác cơ sở dữ liệu quốc gia về dân cư, không bắt người dân nộp lại giấy tờ mà nhà nước đã có. Vậy hệ thống của mình có lấy được thông tin cư trú tự động không?

@BA: Dạ thưa thầy, về kỹ thuật thì có hai cách. Cách thứ nhất là tích hợp với ứng dụng VNeID, phụ huynh đồng ý chia sẻ thông tin cư trú từ ứng dụng, hệ thống nhận về địa chỉ thường trú, tạm trú. Cách thứ hai là kết nối qua trục liên thông dữ liệu của tỉnh, tức là LGSP, gọi dịch vụ tra cứu thông tin công dân theo mã định danh. Tỉnh đã có kết nối với cơ sở dữ liệu dân cư qua trục này cho cổng dịch vụ công chung rồi, nên mình chỉ cần xin cấp quyền khai thác.

@BE: Em bổ sung phần kỹ thuật. Nếu đi qua trục LGSP thì phía em cần Sở Thông tin và Truyền thông cấp tài khoản kết nối và chứng thư số cho hệ thống. Thời gian làm thủ tục thường mất khoảng hai đến ba tuần. Phần code gọi dịch vụ thì không nhiều, khoảng một tuần, vì mình đã có thư viện kết nối LGSP từ dự án cổng dịch vụ công chung. Nhưng có một điểm cần lưu ý: dữ liệu cư trú trả về là địa chỉ dạng văn bản, ví dụ "thôn Đồng Bến, xã Mông Hóa", mình phải so khớp với bảng tuyến, mà tên thôn xóm sau sáp nhập đơn vị hành chính thì nhiều chỗ không khớp. Em ước tính khoảng 10 đến 15% địa chỉ sẽ không tự khớp được, phải cho cán bộ trường xác nhận tay.

@SO: Tỷ lệ đó chấp nhận được, còn hơn bắt cả trăm phần trăm phụ huynh đi xin giấy.

@PM #d_cutru: Vậy em xin chốt: bỏ yêu cầu tải lên sổ hộ khẩu và giấy xác nhận cư trú, thay bằng tra cứu thông tin cư trú tự động qua trục LGSP của tỉnh theo mã định danh học sinh và phụ huynh; trường hợp địa chỉ không khớp bảng tuyến thì chuyển cán bộ trường xác nhận tay. VNeID mình làm sau, đợt này đi LGSP trước vì đã có sẵn kết nối. Anh Đức chuẩn bị hồ sơ xin cấp quyền khai thác gửi Sở Thông tin và Truyền thông nhé.

@BE #a_lgsp: Dạ, em làm công văn và hồ sơ kỹ thuật, thứ Tư tuần sau gửi chị Thu trình thầy Bình ký để gửi đi.

@SO #a_tuyen: Còn việc hai huyện chưa gửi bảng tuyến thì để tôi. Tôi sẽ gọi trực tiếp hai trưởng phòng Lạc Sơn và Kim Bôi, yêu cầu gửi trước ngày 15 tháng này.

@BA #n_nguyenvong: Thưa thầy, nhân tiện em có một đề xuất là hay mình cho phụ huynh chọn hai hoặc ba nguyện vọng trường, nếu trường thứ nhất đủ chỉ tiêu thì tự chuyển sang nguyện vọng hai, như kiểu xét tuyển đại học. Như vậy đỡ cho phụ huynh phải đi nộp lại.

@SO #n_nguyenvong2: Ý này hay nhưng mà vướng quy chế. Tuyển sinh lớp 1 và lớp 6 công lập theo quy định là tuyển theo tuyến, đúng tuyến thì trường phải nhận, nguyện vọng ngoài tuyến chỉ xét khi còn chỉ tiêu. Cho chọn nhiều nguyện vọng thì phụ huynh sẽ hiểu là được chọn trường, rồi khiếu nại. Để Sở nghiên cứu thêm, có thể áp dụng thí điểm cho lớp 6 ở thành phố năm sau, năm nay thì chưa.

@PM: Vâng, em ghi nhận ý đó vào danh sách để xem xét sau. Hằng bên kiểm thử có ý gì về phần tuyển sinh không?

@QA #k_hang1: Dạ em có hai điểm. Thứ nhất, em đã chạy kiểm thử tải giả lập 5.000 phụ huynh nộp đồng thời thì thời gian phản hồi trung bình là 1,8 giây, nhưng ở bước tải ảnh thì có khoảng 3% yêu cầu bị lỗi hết thời gian chờ. Nhóm backend đã xem và nguyên nhân là kho lưu trữ đối tượng đang cấu hình giới hạn kết nối thấp. Thứ hai, em phát hiện nếu phụ huynh có hai con cùng tuổi, ví dụ sinh đôi, thì hệ thống báo trùng hồ sơ vì đang kiểm tra trùng theo số điện thoại phụ huynh ở một bước phụ. Lỗi này em đã ghi lên hệ thống quản lý lỗi mức độ cao.

@BE #a_sinhdoi: Lỗi sinh đôi em biết rồi, do bước kiểm tra chống spam theo số điện thoại. Em sửa luôn trong sprint này, bỏ kiểm tra theo số điện thoại, chỉ giữ kiểm tra theo mã định danh học sinh.

@PM: Tốt. Phần giới hạn kết nối kho lưu trữ thì mình để sang mục hạ tầng nói luôn. Chuyển sang hạng mục thứ hai.

## TOPIC | Xây dựng chức năng tra cứu và cấp bản sao văn bằng, chứng chỉ trực tuyến | Chức năng tra cứu văn bằng đã có dữ liệu số hóa từ năm 2010; dữ liệu trước 2010 còn thiếu và sai lệch; thống nhất thu phí qua cổng thanh toán quốc gia, trả bản sao điện tử có ký số, chỉ số hóa bổ sung theo yêu cầu thay vì số hóa toàn bộ.

@PM: Hạng mục thứ hai là tra cứu và cấp bản sao văn bằng chứng chỉ. Anh Khải trình bày tiếp nhé.

@BA #k_khai2: Dạ. Chức năng này cho phép người dân tra cứu bằng tốt nghiệp trung học phổ thông, trung học cơ sở và chứng chỉ do Sở cấp, rồi đề nghị cấp bản sao. Hiện nay dữ liệu số hóa đã có từ năm 2010 đến nay, khoảng 412.000 văn bằng tốt nghiệp trung học phổ thông và 530.000 văn bằng trung học cơ sở, do dự án số hóa năm 2022 thực hiện. Người dân tra cứu bằng họ tên, ngày sinh, năm tốt nghiệp và số hiệu văn bằng. Doanh nghiệp, cơ quan tuyển dụng cũng có thể tra cứu xác minh văn bằng nếu được người có văn bằng cấp mã chia sẻ. Luồng cấp bản sao thì người dân nộp đề nghị, thanh toán phí, cán bộ phòng Quản lý chất lượng của Sở duyệt, rồi trả kết quả.

@BA: Vấn đề lớn nhất là dữ liệu trước năm 2010. Sổ gốc cấp bằng từ năm 1990 đến 2009 vẫn là sổ giấy, lưu ở kho của Sở và một phần ở các Phòng Giáo dục huyện. Năm nào cũng có khoảng 3.000 đến 4.000 người đề nghị cấp bản sao văn bằng cũ, chủ yếu để bổ túc hồ sơ xin việc, đi xuất khẩu lao động hoặc làm thủ tục nâng ngạch. Ngoài ra trong dữ liệu đã số hóa thì nhóm kiểm thử thấy có khoảng 0,8% bản ghi sai lệch, như sai dấu tên, sai ngày sinh so với ảnh scan.

@UNK #k_fe: Em bên frontend xin nói thêm về giao diện tra cứu. Bọn em đang làm tra cứu không cần đăng nhập cho trường hợp xác minh nhanh, chỉ hiện họ tên, năm tốt nghiệp, xếp loại và trạng thái văn bằng là còn hiệu lực hay đã thu hồi, không hiện ngày sinh, không hiện số định danh, để tránh lộ thông tin. Còn muốn xem đầy đủ hay đề nghị cấp bản sao thì phải đăng nhập tài khoản định danh điện tử mức hai. Có thêm chế độ tìm gần đúng, tức là gõ không dấu hoặc sai một chữ vẫn ra, để xử lý mấy trường hợp sai dấu.

@SO #k_binh2: Phần tìm gần đúng thì tốt, nhưng phải cẩn thận. Tôi đề nghị tra cứu không đăng nhập thì bắt buộc phải nhập đúng số hiệu văn bằng, không cho tìm theo tên không, nếu không người ta dò được danh sách học sinh của cả một trường. Năm ngoái có trang web tư nhân lấy dữ liệu điểm thi đem bán, Bộ đã nhắc nhở rồi.

@UNK: Dạ vâng, bọn em sẽ bắt buộc số hiệu văn bằng với tra cứu không đăng nhập, có thêm mã xác thực chống máy.

@SO: Còn chuyện dữ liệu cũ thì các anh định xử lý thế nào? Số hóa toàn bộ 20 năm sổ gốc thì kinh phí lớn đấy.

@BA: Dạ, em có làm dự toán sơ bộ. Số hóa toàn bộ sổ gốc từ 1990 đến 2009, ước khoảng 600.000 trang, đơn giá scan và nhập liệu, kiểm tra hai lần khoảng 4.500 đồng một trang, tổng khoảng 2,7 tỷ, thời gian khoảng 8 tháng. Phương án thứ hai là số hóa theo yêu cầu, tức là ai đề nghị cấp bản sao văn bằng cũ thì cán bộ tìm sổ, scan trang đó, nhập dữ liệu vào hệ thống, dần dần dữ liệu sẽ đầy lên. Mỗi năm khoảng 4.000 bản ghi, chi phí không đáng kể, nhưng người dân phải chờ lâu hơn, khoảng 5 ngày làm việc thay vì 1 ngày.

@SO: Năm nay không có kinh phí 2,7 tỷ đâu. Đi theo yêu cầu. Nhưng phải công khai thời hạn 5 ngày để người dân biết.

@QA: Em xin hỏi về thanh toán phí, hiện nay mình đang tích hợp thử với cổng thanh toán của một ngân hàng thương mại, nhưng em thấy quy định mới là dịch vụ công phải thanh toán qua cổng thanh toán quốc gia trên Cổng dịch vụ công quốc gia. Mình có phải đổi không ạ?

@BE: Đúng rồi, phải đổi. Em đã xem tài liệu tích hợp của cổng thanh toán quốc gia, cái này có chuẩn sẵn, mình đã tích hợp ở dự án khác rồi. Cái khó là đối soát, cổng quốc gia trả kết quả đối soát cuối ngày, nên hồ sơ thanh toán sau 16 giờ thì hôm sau mới xác nhận.

@SO #k_binh3: Còn hình thức trả kết quả. Hiện nay người dân vẫn phải đến Sở nhận bản sao giấy hoặc nhận qua bưu điện. Theo Nghị định về văn bằng điện tử thì bản sao điện tử có ký số của cơ quan có thẩm quyền có giá trị như bản sao giấy. Tôi muốn hệ thống trả bản sao điện tử ký số là mặc định, ai cần bản giấy thì đăng ký thêm và trả qua bưu chính công ích.

@PM #d_vanbang: Em xin chốt hạng mục này. Một: tra cứu không đăng nhập bắt buộc nhập số hiệu văn bằng và mã chống máy, chỉ hiện thông tin tối thiểu. Hai: thanh toán phí chuyển sang cổng thanh toán quốc gia. Ba: trả bản sao điện tử có ký số của Sở là mặc định, bản giấy gửi qua bưu chính khi có đăng ký. Bốn: dữ liệu trước năm 2010 số hóa theo yêu cầu, thời hạn trả kết quả với văn bằng cũ là 5 ngày làm việc và được công khai trên cổng.

@PM: Về người làm, anh Đức nhận chuyển cổng thanh toán nhé.

@BE #a_thanhtoan: Dạ, em chuyển sang cổng thanh toán quốc gia, xong trước ngày 30 để kịp kiểm thử.

@SO #a_kyso: Phần chữ ký số của Sở để ký bản sao điện tử thì phòng Quản lý chất lượng làm thủ tục đăng ký chứng thư số tổ chức với Ban Cơ yếu, tôi sẽ giao chị Nga trưởng phòng làm việc này trong tháng.

@QA #a_sailech: Còn 0,8% bản ghi sai lệch thì em lập danh sách đầy đủ kèm ảnh scan để phòng Quản lý chất lượng đối chiếu, tuần sau em gửi.

## TOPIC | Rà soát hạ tầng và bảo mật trước đợt cao điểm tuyển sinh | Rà soát năng lực máy chủ tại trung tâm dữ liệu tỉnh và kết quả đánh giá bảo mật; thống nhất nâng giới hạn kết nối kho lưu trữ, bật tường lửa ứng dụng web, diễn tập chịu tải trước ngày 1/6; đề xuất chuyển lên đám mây thương mại chưa được chấp nhận.

@PM: Hạng mục thứ ba là hạ tầng và bảo mật. Hôm nay anh Hải bên hạ tầng có tham gia qua điện thoại. Anh Hải nói được không anh?

@UNK #k_hai1: Alo, mọi người nghe được không. Vâng, em Hải đây. Về hạ tầng thì hiện hệ thống đang chạy trên trung tâm dữ liệu của tỉnh, gồm sáu máy ảo cho ứng dụng, hai máy ảo cơ sở dữ liệu chạy chủ và dự phòng, và một cụm lưu trữ đối tượng ba nút. Băng thông ra internet của trung tâm dữ liệu dùng chung là 2 Gbps cho toàn bộ hệ thống của tỉnh. Theo số liệu năm ngoái thì cao điểm tuyển sinh là ngày đầu mở cổng, khoảng 8 giờ sáng có khoảng 12.000 người truy cập đồng thời, nên em đề nghị trước đợt cao điểm thì tăng lên mười máy ảo ứng dụng, và nâng giới hạn kết nối của kho lưu trữ đối tượng từ 500 lên 3.000, đúng cái lỗi hết thời gian chờ mà chị Hằng nêu lúc nãy.

@QA: Anh Hải ơi, nếu nâng lên 3.000 kết nối thì em đề nghị chạy lại kiểm thử tải với kịch bản 12.000 người đồng thời, không phải 5.000 như lần trước.

@UNK: Đúng, phải chạy lại. Em cần nhóm kiểm thử phối hợp, chọn ngày cuối tuần để không ảnh hưởng các hệ thống khác của tỉnh trên cùng trung tâm dữ liệu.

@BE #k_duc3: Về bảo mật thì tháng trước Sở Thông tin và Truyền thông đã đánh giá an toàn thông tin cấp độ 3 cho hệ thống. Kết quả có 2 lỗ hổng mức cao và 7 mức trung bình. Hai lỗ hổng mức cao là lộ thông tin phiên bản máy chủ web trong tiêu đề phản hồi và một điểm cuối API xuất danh sách hồ sơ không kiểm tra quyền theo trường, tức là cán bộ trường A có thể gọi API lấy hồ sơ trường B nếu biết mã trường. Lỗi thứ hai là nghiêm trọng, em đã sửa xong và đang chờ Sở Thông tin và Truyền thông kiểm tra lại. Bảy lỗi trung bình thì đã sửa năm, còn hai lỗi liên quan cấu hình mật khẩu và khóa tài khoản sau nhiều lần đăng nhập sai.

@SO: Lỗi lộ hồ sơ giữa các trường là rất nghiêm trọng, hồ sơ tuyển sinh có thông tin trẻ em và gia đình. Tôi yêu cầu sửa xong toàn bộ, kể cả hai lỗi trung bình còn lại, và có xác nhận của Sở Thông tin và Truyền thông trước khi mở cổng. Không có xác nhận thì không mở.

@UNK #k_hai2: Em đề xuất thêm là bật tường lửa ứng dụng web của trung tâm dữ liệu cho hệ thống này. Trung tâm dữ liệu tỉnh có sẵn thiết bị tường lửa ứng dụng nhưng các hệ thống phải đăng ký mới được đưa vào. Năm ngoái hệ thống tuyển sinh cũ bị dò quét và tấn công từ chối dịch vụ nhỏ vào đúng ngày mở cổng.

@BE #n_cloud: Em thì nghĩ là xa hơn thì mình nên tính chuyển hẳn sang đám mây thương mại của một nhà cung cấp trong nước, có tự động co giãn, đỡ phải lo tăng máy ảo bằng tay mỗi mùa tuyển sinh. Chi phí theo giờ, chỉ trả nhiều vào hai tuần cao điểm.

@SO #n_cloud2: Cái này thì không quyết ở đây được. Hệ thống có dữ liệu cá nhân của học sinh, theo chủ trương của tỉnh thì các hệ thống dùng chung phải đặt ở trung tâm dữ liệu tỉnh. Muốn thuê đám mây thì phải có ý kiến của Sở Thông tin và Truyền thông và Ủy ban, mà phải qua thẩm định cấp độ an toàn lại từ đầu. Năm nay cứ ở trung tâm dữ liệu tỉnh đã.

@PM #d_hatang: Vậy em chốt hạ tầng: Một là tăng lên mười máy ảo ứng dụng và nâng giới hạn kết nối kho lưu trữ lên 3.000 trước ngày 20 tháng 5. Hai là đăng ký đưa hệ thống vào tường lửa ứng dụng web của trung tâm dữ liệu. Ba là diễn tập chịu tải với kịch bản 12.000 người đồng thời trước ngày 1 tháng 6. Bốn là sửa toàn bộ lỗ hổng, có biên bản xác nhận của Sở Thông tin và Truyền thông thì mới mở cổng. Anh Hải nhận phần nâng cấp và đăng ký tường lửa được không anh?

@UNK #a_hatang: Được chị, em nhận phần tăng máy ảo, nâng giới hạn kết nối và làm thủ tục đăng ký tường lửa ứng dụng, xong trước ngày 20 tháng 5.

@QA #a_taitest: Em chủ trì kịch bản diễn tập chịu tải, phối hợp với anh Hải, chạy vào thứ Bảy 25 tháng 5.

@BE #a_baomat: Hai lỗi trung bình còn lại em sửa trong tuần này, rồi em gửi đề nghị Sở Thông tin và Truyền thông kiểm tra lại toàn bộ.

## TOPIC | Thống nhất kế hoạch tháng tới và mốc mở cổng tuyển sinh | Thống nhất mốc nghiệm thu nội bộ 25/5, mở cổng tuyển sinh thử nghiệm tại thành phố từ 1/6 và toàn tỉnh từ 10/6; tập huấn cán bộ trường; đề xuất mở cổng sớm một tuần chưa được chấp nhận.

@PM #k_thu: Hạng mục cuối là kế hoạch tháng tới. Em đề xuất mốc như sau. Ngày 20 tháng 5 hoàn thành nâng cấp hạ tầng, ngày 25 tháng 5 nghiệm thu nội bộ kèm diễn tập chịu tải, ngày 28 tháng 5 có biên bản xác nhận bảo mật. Ngày 1 tháng 6 mở cổng thử nghiệm cho các trường ở thành phố, khoảng 60 trường tiểu học và trung học cơ sở, rồi ngày 10 tháng 6 mở toàn tỉnh, sau khi có số liệu chạy thật một tuần. Phần tập huấn cán bộ trường thì làm trực tuyến, chia ba buổi theo cụm huyện.

@SO: Lịch này tôi cơ bản đồng ý. Nhưng năm nay tôi muốn tập huấn không chỉ cán bộ trường mà cả cán bộ Phòng Giáo dục huyện, vì phụ huynh vướng thì gọi lên phòng chứ không gọi lên Sở. Năm ngoái đường dây nóng của Sở quá tải.

@BA #n_mosom: Thưa thầy, em có ý là hay mình mở sớm hơn một tuần, tức là 25 tháng 5 mở thử nghiệm, để có nhiều thời gian sửa lỗi hơn trước khi mở toàn tỉnh.

@SO #n_mosom2: Không được. Ngày 25 tháng 5 các trường còn đang tổng kết năm học, cán bộ trường không có thời gian duyệt hồ sơ. Với lại kế hoạch tuyển sinh của Ủy ban đã ban hành mốc từ ngày 1 tháng 6, mình không tự đổi được. Cứ theo 1 tháng 6.

@QA: Em đề nghị thêm, trong tuần thử nghiệm ở thành phố, nhóm kiểm thử trực tại Sở hai người để ghi nhận lỗi trực tiếp từ cán bộ.

@PM: Đồng ý. Còn tài liệu hướng dẫn phụ huynh, video hướng dẫn thì ai làm? Năm ngoái mình làm muộn quá.

@SO: Phần truyền thông đến phụ huynh thì để Sở phối hợp với Đài Phát thanh - Truyền hình tỉnh và các trường gửi qua nhóm Zalo phụ huynh. Nhưng nội dung video thì nhóm dự án phải làm, vì các anh chị hiểu hệ thống.

@BA #a_video: Dạ, em làm kịch bản và quay video hướng dẫn nộp hồ sơ, tài liệu hỏi đáp, gửi Sở duyệt trước ngày 25 tháng 5.

@PM #d_lich: Vậy em chốt kế hoạch: nghiệm thu nội bộ ngày 25 tháng 5; mở cổng thử nghiệm cho các trường ở thành phố từ ngày 1 tháng 6; mở toàn tỉnh từ ngày 10 tháng 6. Tập huấn trực tuyến ba buổi cho cả cán bộ trường và cán bộ Phòng Giáo dục huyện. Nhóm kiểm thử trực tại Sở hai người trong tuần thử nghiệm.

@PM #a_taphuan: Phần tập huấn em sẽ tự lên lịch và gửi giấy mời qua Sở trước ngày 15 tháng 5. Ai có ý gì nữa không ạ?

@UNK: Bên hạ tầng không có gì thêm chị.

@SO: Cảm ơn mọi người. Năm nay là năm đầu tiên làm tuyển sinh trực tuyến có liên thông dữ liệu dân cư, Ủy ban rất quan tâm, các anh chị cố gắng.

```json gold
{
  "assignments": [
    {"actor": "Đức (Trưởng nhóm Backend)", "actor_aliases": ["anh Đức", "em"], "task": "Chuẩn bị công văn và hồ sơ kỹ thuật xin cấp quyền khai thác dữ liệu dân cư qua trục LGSP", "deadline": "thứ Tư tuần sau", "turns": ["a_lgsp"]},
    {"actor": "Thầy Bình (Phó Giám đốc Sở Giáo dục)", "actor_aliases": ["tôi"], "task": "Gọi trưởng phòng Giáo dục Lạc Sơn và Kim Bôi yêu cầu gửi bảng tuyến", "deadline": "trước ngày 15 tháng này", "turns": ["a_tuyen"]},
    {"actor": "Đức (Trưởng nhóm Backend)", "actor_aliases": ["em"], "task": "Sửa lỗi báo trùng hồ sơ trẻ sinh đôi, bỏ kiểm tra theo số điện thoại", "deadline": "trong sprint này", "turns": ["a_sinhdoi"]},
    {"actor": "Đức (Trưởng nhóm Backend)", "actor_aliases": ["anh Đức", "em"], "task": "Chuyển thanh toán phí sang cổng thanh toán quốc gia", "deadline": "trước ngày 30", "turns": ["a_thanhtoan"]},
    {"actor": "Chị Nga (Trưởng phòng Quản lý chất lượng)", "actor_aliases": ["chị Nga", "phòng Quản lý chất lượng"], "task": "Làm thủ tục đăng ký chứng thư số tổ chức với Ban Cơ yếu để ký bản sao điện tử", "deadline": "trong tháng", "turns": ["a_kyso"]},
    {"actor": "Hằng (Kiểm thử)", "actor_aliases": ["em"], "task": "Lập danh sách 0,8% bản ghi văn bằng sai lệch kèm ảnh scan gửi phòng Quản lý chất lượng", "deadline": "tuần sau", "turns": ["a_sailech"]},
    {"actor": "Hải (Hạ tầng)", "actor_aliases": ["anh Hải", "em", "Người nói không xác định"], "task": "Tăng lên 10 máy ảo, nâng giới hạn kết nối kho lưu trữ lên 3.000, đăng ký tường lửa ứng dụng web", "deadline": "trước ngày 20 tháng 5", "turns": ["a_hatang"]},
    {"actor": "Hằng (Kiểm thử)", "actor_aliases": ["em"], "task": "Chủ trì diễn tập chịu tải kịch bản 12.000 người đồng thời", "deadline": "thứ Bảy 25 tháng 5", "turns": ["a_taitest"]},
    {"actor": "Đức (Trưởng nhóm Backend)", "actor_aliases": ["em"], "task": "Sửa 2 lỗ hổng trung bình còn lại và đề nghị Sở TT&TT kiểm tra lại", "deadline": "trong tuần này", "turns": ["a_baomat"]},
    {"actor": "Anh Khải (Phân tích nghiệp vụ)", "actor_aliases": ["em"], "task": "Làm kịch bản, quay video hướng dẫn nộp hồ sơ và tài liệu hỏi đáp gửi Sở duyệt", "deadline": "trước ngày 25 tháng 5", "turns": ["a_video"]},
    {"actor": "Chị Thu (Quản lý dự án)", "actor_aliases": ["em"], "task": "Lên lịch tập huấn và gửi giấy mời qua Sở", "deadline": "trước ngày 15 tháng 5", "turns": ["a_taphuan"]}
  ],
  "decisions": [
    {"text": "Bỏ yêu cầu tải lên sổ hộ khẩu/giấy xác nhận cư trú, thay bằng tra cứu cư trú tự động qua trục LGSP; địa chỉ không khớp tuyến thì cán bộ trường xác nhận tay; VNeID làm sau", "turns": ["d_cutru"]},
    {"text": "Tra cứu văn bằng không đăng nhập bắt buộc số hiệu văn bằng và mã chống máy; thanh toán qua cổng thanh toán quốc gia; trả bản sao điện tử ký số là mặc định; dữ liệu trước 2010 số hóa theo yêu cầu, thời hạn 5 ngày làm việc", "turns": ["d_vanbang"]},
    {"text": "Nâng cấp hạ tầng (10 máy ảo, 3.000 kết nối), đăng ký tường lửa ứng dụng web, diễn tập chịu tải trước 1/6, chỉ mở cổng khi có xác nhận bảo mật của Sở TT&TT", "turns": ["d_hatang"]},
    {"text": "Nghiệm thu nội bộ 25/5; mở cổng thử nghiệm tại thành phố từ 1/6, toàn tỉnh từ 10/6; tập huấn cả cán bộ trường và Phòng Giáo dục huyện", "turns": ["d_lich"]}
  ],
  "negatives": [
    {"type": "hedged_proposal", "text": "Cho phụ huynh chọn nhiều nguyện vọng trường (Sở nghiên cứu thêm, có thể thí điểm năm sau)", "turns": ["n_nguyenvong", "n_nguyenvong2"]},
    {"type": "hedged_proposal", "text": "Chuyển hệ thống lên đám mây thương mại có tự động co giãn", "turns": ["n_cloud", "n_cloud2"]},
    {"type": "hedged_proposal", "text": "Mở cổng thử nghiệm sớm từ 25/5", "turns": ["n_mosom", "n_mosom2"]}
  ],
  "key_points": [
    {"speaker": "Anh Khải (Phân tích nghiệp vụ)", "point": "Đã xong luồng nộp hồ sơ lớp 1 và lớp 6; còn 2 huyện chưa gửi bảng tuyến", "turns": ["k_khai1"]},
    {"speaker": "Thầy Bình (Phó Giám đốc Sở Giáo dục)", "point": "Không được bắt phụ huynh nộp sổ hộ khẩu/giấy xác nhận cư trú, phải khai thác CSDL dân cư", "turns": ["k_binh1"]},
    {"speaker": "Hằng (Kiểm thử)", "point": "Kiểm thử tải 5.000 người: 3% lỗi hết thời gian khi tải ảnh; lỗi báo trùng hồ sơ trẻ sinh đôi", "turns": ["k_hang1"]},
    {"speaker": "Anh Khải (Phân tích nghiệp vụ)", "point": "Dữ liệu văn bằng số hóa từ 2010; sổ gốc 1990-2009 còn giấy, 0,8% bản ghi sai lệch; số hóa toàn bộ tốn khoảng 2,7 tỷ", "turns": ["k_khai2"]},
    {"speaker": "Thầy Bình (Phó Giám đốc Sở Giáo dục)", "point": "Tra cứu không đăng nhập phải bắt buộc số hiệu văn bằng; bản sao điện tử ký số là mặc định", "turns": ["k_binh2", "k_binh3"]},
    {"speaker": "Hải (Hạ tầng)", "point": "Cao điểm khoảng 12.000 người đồng thời; cần tăng lên 10 máy ảo, nâng giới hạn kết nối lưu trữ lên 3.000, bật tường lửa ứng dụng web", "turns": ["k_hai1", "k_hai2"]},
    {"speaker": "Đức (Trưởng nhóm Backend)", "point": "Đánh giá an toàn thông tin có 2 lỗ hổng cao (trong đó lộ hồ sơ giữa các trường, đã sửa) và 7 trung bình", "turns": ["k_duc3"]},
    {"speaker": "Chị Thu (Quản lý dự án)", "point": "Đề xuất mốc nghiệm thu 25/5, mở thử nghiệm 1/6 tại thành phố, toàn tỉnh 10/6", "turns": ["k_thu"]}
  ]
}
```
