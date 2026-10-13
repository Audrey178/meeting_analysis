```json meta
{
  "meeting_id": "synth_001",
  "title": "Họp rà soát dự án Hệ thống tiếp nhận và xử lý kiến nghị cử tri - giai đoạn 1",
  "meeting_type": "software_project",
  "length_bucket": "S",
  "tags": ["short_meeting", "pronoun_actor", "dense_actions_closing", "rejected_task", "hedged_proposal"],
  "speakers": {
    "PM": "Anh Tuấn (Giám đốc dự án)",
    "BA": "Chị Mai (Phân tích nghiệp vụ)",
    "BE": "Nam (Lập trình Backend)",
    "AI": "Hiếu (Kỹ sư AI)",
    "FE": "Linh (Lập trình Frontend)",
    "KH": "Anh Phong (Văn phòng Đoàn ĐBQH tỉnh)"
  }
}
```

## TOPIC | Rà soát tiến độ chung và phạm vi giai đoạn 1 của dự án | PM tổng hợp tiến độ (khoảng 55%, chậm 2 tuần do chờ dữ liệu mẫu), khách hàng yêu cầu giữ mốc demo 15/12; thống nhất giữ phạm vi 3 chức năng chính và bỏ ứng dụng di động khỏi giai đoạn 1.

@PM: Rồi, mọi người vào đủ chưa nhỉ, anh Phong bên Văn phòng Đoàn cũng vào rồi đúng không ạ. Hôm nay mình họp rà soát giai đoạn 1 của hệ thống kiến nghị cử tri. Em xin phép nói qua tiến độ chung trước, sau đó mình đi từng chức năng, cuối buổi thì chốt kế hoạch với phân công. Về tổng thể thì đến hôm nay mình đạt khoảng 55% khối lượng của giai đoạn 1, so với kế hoạch thì đang chậm khoảng hai tuần. Nguyên nhân chính là cái bộ dữ liệu kiến nghị mẫu của các kỳ họp trước thì mình nhận muộn, đến tuần trước mới có đủ khoảng 8.400 kiến nghị đã được phân loại, nên phần AI bị lùi lại. Phần backend với cơ sở dữ liệu thì cơ bản xong khung rồi, phần giao diện thì mới được khoảng một nửa.

@KH: Anh Tuấn cho anh hỏi là cái mốc demo cho Thường trực Đoàn ngày 15 tháng 12 thì có giữ được không? Vì bên anh đã báo cáo lên rồi, cái mốc này là không lùi được đâu, lãnh đạo Đoàn muốn xem trước kỳ họp tiếp xúc cử tri đầu năm.

@PM: Dạ, cái mốc 15/12 thì bên em vẫn cam kết giữ anh ạ. Nhưng mà để giữ được thì em nghĩ là mình phải chốt lại phạm vi cho gọn. Chị Mai nói qua giúp em cái phạm vi hiện tại nhé.

@BA: Dạ vâng. Theo hợp đồng và biên bản khảo sát thì giai đoạn 1 gồm ba chức năng chính. Một là tiếp nhận kiến nghị từ nhiều kênh, gồm nhập tay từ biên bản tiếp xúc cử tri, cổng thông tin và hòm thư điện tử, rồi AI tự động phân loại theo lĩnh vực và chuyển cho cơ quan có thẩm quyền. Hai là cổng tra cứu cho cử tri, để người dân tra xem kiến nghị của mình đang ở bước nào. Ba là theo dõi và đánh giá chất lượng câu trả lời của các cơ quan. Ngoài ra thì trong buổi khảo sát lần hai, bên anh Phong có nêu thêm mong muốn có ứng dụng di động cho đại biểu để đại biểu ghi kiến nghị ngay tại buổi tiếp xúc. Cái này hiện chưa có trong hợp đồng.

@KH: Ừ, cái ứng dụng di động thì là mong muốn của một số đại biểu thôi, nếu không kịp thì anh nghĩ cũng không bắt buộc ở giai đoạn này.

@FE #n_mobile: Dạ anh Tuấn, em thì em nghĩ cái app di động nếu làm bằng Flutter thì cũng dùng lại được khá nhiều API của web, em ước khoảng ba tuần là có bản cơ bản, hay là mình vẫn làm song song ạ?

@PM #d_phamvi: Thôi, cái này Linh ơi, anh nghĩ là không làm. Ba tuần của em lúc này là rất quý, phần giao diện web còn đang một nửa. Anh chốt là giai đoạn 1 giữ đúng ba chức năng chính như chị Mai vừa nói, ứng dụng di động thì đưa sang giai đoạn 2, bên em sẽ làm phụ lục đề xuất riêng gửi anh Phong. Anh Phong thấy được không ạ?

@KH: Được, anh đồng ý. Miễn là 15/12 có cái để demo được đầy đủ ba cái chức năng kia.

## TOPIC | Xây dựng chức năng AI tự động phân loại kiến nghị theo lĩnh vực | Hiếu báo cáo mô hình phân loại PhoBERT đạt F1 khoảng 0.81 trên 18 lĩnh vực, yếu ở các lĩnh vực đất đai-môi trường; thống nhất gộp nhãn còn 12 lĩnh vực và dùng ngưỡng tin cậy 0.7 để chuyển chuyên viên duyệt.

@PM: Rồi, mình đi vào từng phần. Phần phân loại tự động trước nhé, Hiếu báo cáo đi em.

@AI #k_ai1: Dạ vâng. Em đang làm cái mô hình phân loại kiến nghị theo lĩnh vực. Dữ liệu là 8.400 kiến nghị bên anh Phong gửi, em chia 80 10 10 để train, validation với test. Hiện em đang fine-tune PhoBERT base, trên tập test thì F1 macro đạt khoảng 0.81 trên 18 lĩnh vực. Nhưng mà nhìn chi tiết thì có mấy lĩnh vực rất kém. Cụ thể là đất đai với tài nguyên môi trường thì bị nhầm với nhau rất nhiều, F1 chỉ khoảng 0.6, vì một kiến nghị về thu hồi đất làm bãi rác thì nó vừa là đất đai vừa là môi trường. Rồi cái lĩnh vực chính sách xã hội với lao động việc làm cũng nhầm. Còn mấy lĩnh vực như giao thông, y tế, giáo dục thì tốt, trên 0.9.

@BA: Hiếu ơi, cái 18 lĩnh vực này là theo cái danh mục cũ của Văn phòng Đoàn đúng không? Chị nhớ là trong buổi khảo sát, anh Phong có nói là từ năm nay bên đó đã gộp lại thành 12 lĩnh vực theo cái cơ cấu các ban mới rồi.

@KH: Đúng rồi, từ kỳ họp này thì bên anh dùng 12 lĩnh vực thôi, đất đai với môi trường là chung một lĩnh vực, chính sách xã hội với lao động cũng gộp rồi. Chị Mai để anh gửi lại cái danh mục mới.

@AI: Dạ, nếu gộp như vậy thì rất tốt anh ạ, vì chính mấy cặp hay nhầm nhất lại là mấy cặp được gộp. Em ước là gộp xong thì F1 có thể lên khoảng 0.87, 0.88. Em chỉ cần map lại nhãn, train lại mất khoảng hai ngày thôi.

@PM #d_12linhvuc: Ok, vậy chốt là chuyển sang 12 lĩnh vực theo danh mục mới của Văn phòng Đoàn. Thế còn cái trường hợp mô hình không chắc chắn thì mình xử lý thế nào Hiếu?

@AI #k_ai2: Dạ, em đề xuất là mình đặt một cái ngưỡng độ tin cậy. Nếu xác suất của nhãn cao nhất dưới ngưỡng thì hệ thống không tự chuyển mà đưa vào hàng chờ cho chuyên viên duyệt tay. Em thử trên tập validation thì ngưỡng 0.7 thì khoảng 82% kiến nghị được tự động chuyển, và trong số tự động đó thì độ chính xác khoảng 96%. Còn 18% còn lại chuyên viên duyệt.

@KH: Mười tám phần trăm thì bên anh duyệt được, trước giờ bên anh duyệt tay 100% mà. Nhưng mà anh muốn là chuyên viên sửa nhãn thì cái hệ thống phải ghi lại để sau này mô hình học lại được.

@AI #n_llm: Dạ cái đó thì có ạ, em sẽ lưu lại nhãn chuyên viên sửa. À anh Tuấn, em cũng có một cái ý là về lâu dài thì mình có thể thử dùng một cái mô hình ngôn ngữ lớn tự host, kiểu Qwen hay Llama bản tiếng Việt, để phân loại luôn cả những kiến nghị có nhiều lĩnh vực, vì PhoBERT thì chỉ cho một nhãn. Nhưng cái này em cũng chưa thử, cần GPU mạnh hơn, nên em chỉ nêu vậy thôi.

@PM #d_nguong: Cái LLM thì để sau em ạ, giai đoạn này mình không có GPU cho cái đó. Chốt phần này là dùng PhoBERT, 12 lĩnh vực, ngưỡng 0.7, dưới ngưỡng thì vào hàng chờ chuyên viên, và có ghi log nhãn sửa để train lại.

@BE: Anh Tuấn, về phía backend thì em cần Hiếu chốt cái định dạng API trả về, em đang để là trả về nhãn với độ tin cậy, nếu Hiếu muốn trả về top 3 thì em sửa cái schema luôn.

@AI: Trả về top 3 đi Nam, để giao diện duyệt của chuyên viên hiện được gợi ý thứ hai thứ ba, chuyên viên chọn cho nhanh.

## TOPIC | Xây dựng chức năng tra cứu và theo dõi trạng thái kiến nghị cho cử tri | Linh demo cổng tra cứu bằng mã kiến nghị; khách hàng yêu cầu tra cứu bằng số điện thoại có OTP và ẩn thông tin cá nhân; thống nhất thêm tra cứu theo số điện thoại với OTP qua SMS brandname của tỉnh.

@PM: Rồi, sang phần cổng tra cứu cho cử tri. Linh chia sẻ màn hình đi em.

@FE #k_fe: Dạ, mọi người nhìn thấy màn hình em chưa ạ. Đây là cái trang tra cứu công khai. Hiện tại cử tri nhập cái mã kiến nghị, mã này in trên cái phiếu tiếp nhận, thì hệ thống hiện ra các bước: đã tiếp nhận, đã phân loại, đã chuyển cơ quan nào, cơ quan đã trả lời chưa, và nội dung trả lời. Em làm giao diện responsive để xem trên điện thoại cũng được. Phần timeline thì em lấy từ cái bảng lịch sử trạng thái bên Nam. Hiện em đang dùng dữ liệu giả, chưa nối API thật.

@KH: Giao diện thì ổn đấy. Nhưng mà anh nói thật là cái mã kiến nghị thì người dân không ai giữ đâu. Ở các buổi tiếp xúc cử tri thì đại biểu ghi kiến nghị, người dân về có ai được cầm phiếu gì đâu. Người dân chỉ nhớ số điện thoại của mình thôi. Cho nên là phải tra được bằng số điện thoại.

@BA: Dạ đúng ạ, cái này trong biên bản khảo sát lần hai có ghi nhưng mà bọn em chưa đưa vào đặc tả, lỗi bên em. Nhưng mà anh Phong ơi, nếu tra bằng số điện thoại thì có vấn đề là ai biết số điện thoại của người khác cũng tra được, lộ thông tin người kiến nghị.

@BE: Cái đó thì mình phải có OTP chị ạ. Nhập số điện thoại, hệ thống gửi mã OTP về số đó, nhập đúng mới xem được. Nhưng mà gửi SMS thì mình phải có dịch vụ SMS brandname, cái này tốn tiền theo tin nhắn.

@KH: Tỉnh có sẵn SMS brandname dùng chung rồi, cái của Trung tâm phục vụ hành chính công đấy, bên anh có thể xin dùng chung, không mất tiền.

@PM #d_otp: Vậy thì tốt quá. Chốt là thêm tra cứu bằng số điện thoại có xác thực OTP, dùng SMS brandname dùng chung của tỉnh. Tra bằng mã kiến nghị vẫn giữ. Còn một cái nữa là trên trang công khai thì nội dung kiến nghị có hiện tên với địa chỉ người kiến nghị không anh Phong?

@KH #k_kh: Không, tuyệt đối không hiện. Kể cả khi tra bằng OTP thì cũng chỉ hiện nội dung kiến nghị và nội dung trả lời thôi, không hiện họ tên, địa chỉ, vì có nhiều kiến nghị là tố cáo cán bộ địa phương, lộ ra là phiền.

@FE: Dạ vâng, em sẽ ẩn hết các trường thông tin cá nhân. Anh Tuấn ơi, phần OTP thì em làm giao diện được, nhưng phần tích hợp SMS thì chắc là Nam phải làm bên backend.

@BE: Ừ phần tích hợp SMS với sinh OTP thì để anh, nhưng mà anh cần cái tài liệu API của SMS brandname bên tỉnh, chứ hiện anh chưa có.

## TOPIC | Xây dựng chức năng AI tự động đánh giá câu trả lời kiến nghị | Hiếu đề xuất chấm câu trả lời của cơ quan theo 3 tiêu chí; khách hàng yêu cầu AI chỉ gợi ý, chuyên viên quyết định; thống nhất bản đầu dùng luật và mô hình tương đồng, AI chỉ đánh dấu câu trả lời chưa đạt để chuyên viên xem.

@PM: Rồi, phần cuối trước khi chốt là phần đánh giá câu trả lời. Phần này thì hiện đang chậm nhất. Hiếu nói tiếp đi em.

@AI #k_ai3: Dạ. Cái chức năng này thì mục tiêu là khi cơ quan có thẩm quyền gửi câu trả lời, hệ thống tự đánh giá xem câu trả lời đó có đạt không. Em đang đề xuất chấm theo ba tiêu chí. Một là trả lời có đúng trọng tâm câu hỏi của cử tri không. Hai là có nêu rõ hướng giải quyết và thời hạn cụ thể không, hay chỉ trả lời chung chung kiểu là sẽ xem xét. Ba là có dẫn căn cứ pháp lý không. Về kỹ thuật thì tiêu chí một em dùng mô hình tương đồng ngữ nghĩa giữa kiến nghị và câu trả lời, tiêu chí hai với ba thì dùng luật, bắt các mẫu câu như là thời hạn, ngày tháng, số hiệu văn bản. Nhưng mà hiện em chưa có dữ liệu có nhãn đánh giá nào cả, nên chưa đo được độ chính xác.

@KH: Anh thì anh muốn nói rõ cái này. Việc đánh giá câu trả lời của một cơ quan nhà nước là việc rất nhạy cảm. Nếu cái máy nói câu trả lời của Sở này là không đạt, rồi cái đó hiện lên báo cáo gửi Thường trực, thì là có chuyện. Cho nên là AI chỉ được gợi ý thôi, còn chuyên viên là người quyết định đạt hay không đạt.

@AI: Dạ vâng, em hiểu ạ. Vậy thì em đổi cách thể hiện, là AI không chấm đạt hay không đạt nữa, mà chỉ đánh dấu những câu trả lời có dấu hiệu chưa đạt, kèm lý do, ví dụ là không có thời hạn cụ thể, để chuyên viên xem trước.

@BA: Chị thấy như thế hợp lý hơn. Mà Hiếu ơi, về dữ liệu có nhãn, thì bên anh Phong có cái báo cáo giám sát kết quả giải quyết kiến nghị hằng năm đấy, trong đó chuyên viên đã đánh giá từng câu trả lời là đạt hay chưa đạt rồi. Có thể lấy làm dữ liệu được không anh Phong?

@KH: Có, báo cáo giám sát ba năm gần đây, mỗi năm khoảng một nghìn rưỡi câu trả lời có đánh giá. Nhưng mà nó ở dạng file Word, phải có người bóc ra.

@PM #d_danhgia: Ok. Vậy chốt hướng cho phần này. Bản đầu tiên cho demo 15/12 thì dùng tương đồng ngữ nghĩa kết hợp luật như Hiếu nói, và chỉ đánh dấu câu trả lời có dấu hiệu chưa đạt kèm lý do, không đưa ra kết luận đạt hay không đạt, chuyên viên là người quyết định. Dữ liệu báo cáo giám sát thì dùng để đo và cải tiến sau demo.

@AI: Dạ vâng anh.

## TOPIC | Thống nhất kế hoạch triển khai và phân công đến mốc demo 15/12 | PM chốt kế hoạch và phân công việc cho từng người đến mốc demo 15/12, gồm cập nhật danh mục lĩnh vực, train lại mô hình, tích hợp OTP, bóc tách dữ liệu báo cáo giám sát và chuẩn bị kịch bản demo.

@PM: Rồi, giờ mình chốt phân công nhé, mọi người ghi lại giúp anh. Anh đọc lần lượt.

@PM #a_danhmuc: Đầu tiên là anh Phong gửi giúp bên em cái danh mục 12 lĩnh vực mới, với tài liệu API của cái SMS brandname dùng chung của tỉnh. Anh Phong gửi giúp em trong tuần này được không ạ?

@KH #a_danhmuc_ok: Được, thứ Sáu này anh gửi cả hai.

@PM #a_train: Hiếu thì có danh mục rồi thì map lại nhãn sang 12 lĩnh vực, train lại mô hình phân loại, sửa API trả về top 3 kèm độ tin cậy, xong trước ngày 25 tháng 11.

@AI: Dạ vâng.

@PM #a_otp: Nam làm phần tích hợp SMS brandname và sinh OTP, và API tra cứu theo số điện thoại. Cái này thì phụ thuộc tài liệu của anh Phong, nên em tính là xong trong vòng một tuần sau khi nhận tài liệu nhé.

@BE: Dạ ok anh.

@PM #a_fe: Linh thì nối cổng tra cứu với API thật, thêm màn hình nhập số điện thoại và OTP, ẩn hết các trường thông tin cá nhân như anh Phong nói. Deadline là ngày 1 tháng 12 để còn kiểm thử.

@FE: Dạ vâng anh.

@PM #a_boc: Còn cái việc bóc dữ liệu từ báo cáo giám sát ra thành dữ liệu có nhãn cho phần đánh giá câu trả lời, thì bạn làm phân loại lúc nãy nhận luôn nhé, vì em ấy hiểu dữ liệu nhất. Không cần gấp, sau demo cũng được, nhưng trước Tết thì phải xong.

@AI #a_boc_ok: Dạ, em nhận ạ. Em sẽ viết script bóc tự động từ file Word, chỗ nào lỗi thì em sửa tay.

@PM #a_demo: Chị Mai thì cập nhật lại đặc tả cho phần tra cứu theo số điện thoại với cái phần đánh giá câu trả lời theo hướng chỉ gợi ý, và soạn kịch bản demo cho Thường trực, gửi anh Phong duyệt trước ngày 10 tháng 12.

@BA: Dạ vâng, chị ghi rồi.

@PM #a_phuluc: Còn anh thì anh làm cái phụ lục đề xuất ứng dụng di động cho giai đoạn 2 gửi anh Phong, trong tháng 12. Vậy thôi, còn ai có vấn đề gì không? Không thì mình kết thúc, cảm ơn anh Phong và cả nhà.

```json gold
{
  "assignments": [
    {"actor": "Anh Phong (Văn phòng Đoàn ĐBQH tỉnh)", "actor_aliases": ["anh Phong"], "task": "Gửi danh mục 12 lĩnh vực mới và tài liệu API SMS brandname dùng chung của tỉnh", "deadline": "thứ Sáu tuần này", "turns": ["a_danhmuc", "a_danhmuc_ok"]},
    {"actor": "Hiếu (Kỹ sư AI)", "actor_aliases": ["Hiếu"], "task": "Map nhãn sang 12 lĩnh vực, train lại mô hình phân loại, sửa API trả về top 3 kèm độ tin cậy", "deadline": "trước 25/11", "turns": ["a_train"]},
    {"actor": "Nam (Lập trình Backend)", "actor_aliases": ["Nam"], "task": "Tích hợp SMS brandname, sinh OTP và API tra cứu theo số điện thoại", "deadline": "1 tuần sau khi nhận tài liệu API SMS", "turns": ["a_otp"]},
    {"actor": "Linh (Lập trình Frontend)", "actor_aliases": ["Linh"], "task": "Nối cổng tra cứu với API thật, thêm màn hình số điện thoại và OTP, ẩn trường thông tin cá nhân", "deadline": "1/12", "turns": ["a_fe"]},
    {"actor": "Hiếu (Kỹ sư AI)", "actor_aliases": ["bạn làm phân loại lúc nãy", "em ấy", "em"], "task": "Bóc tách dữ liệu báo cáo giám sát thành dữ liệu có nhãn cho chức năng đánh giá câu trả lời", "deadline": "trước Tết", "turns": ["a_boc", "a_boc_ok"]},
    {"actor": "Chị Mai (Phân tích nghiệp vụ)", "actor_aliases": ["chị Mai"], "task": "Cập nhật đặc tả tra cứu theo số điện thoại và đánh giá câu trả lời theo hướng gợi ý; soạn kịch bản demo gửi khách hàng duyệt", "deadline": "trước 10/12", "turns": ["a_demo"]},
    {"actor": "Anh Tuấn (Giám đốc dự án)", "actor_aliases": ["anh"], "task": "Làm phụ lục đề xuất ứng dụng di động cho giai đoạn 2 gửi khách hàng", "deadline": "trong tháng 12", "turns": ["a_phuluc"]}
  ],
  "decisions": [
    {"text": "Giai đoạn 1 giữ đúng 3 chức năng chính; ứng dụng di động chuyển sang giai đoạn 2; giữ mốc demo 15/12", "turns": ["d_phamvi"]},
    {"text": "Chuyển mô hình phân loại sang 12 lĩnh vực theo danh mục mới", "turns": ["d_12linhvuc"]},
    {"text": "Dùng PhoBERT, ngưỡng tin cậy 0.7, dưới ngưỡng vào hàng chờ chuyên viên duyệt, ghi log nhãn sửa để train lại", "turns": ["d_nguong"]},
    {"text": "Thêm tra cứu bằng số điện thoại có OTP dùng SMS brandname dùng chung của tỉnh, vẫn giữ tra theo mã kiến nghị", "turns": ["d_otp"]},
    {"text": "Chức năng đánh giá câu trả lời bản đầu dùng tương đồng ngữ nghĩa + luật, chỉ đánh dấu câu trả lời có dấu hiệu chưa đạt kèm lý do, chuyên viên quyết định", "turns": ["d_danhgia"]}
  ],
  "negatives": [
    {"type": "rejected_task", "text": "Linh làm ứng dụng di động bằng Flutter song song trong giai đoạn 1", "turns": ["n_mobile"]},
    {"type": "hedged_proposal", "text": "Dùng mô hình ngôn ngữ lớn tự host (Qwen/Llama) để phân loại đa nhãn", "turns": ["n_llm"]}
  ],
  "key_points": [
    {"speaker": "Hiếu (Kỹ sư AI)", "point": "Mô hình PhoBERT đạt F1 macro ~0.81 trên 18 lĩnh vực, yếu ở đất đai và môi trường (~0.6)", "turns": ["k_ai1"]},
    {"speaker": "Hiếu (Kỹ sư AI)", "point": "Ngưỡng tin cậy 0.7: ~82% tự động chuyển với độ chính xác ~96%", "turns": ["k_ai2"]},
    {"speaker": "Linh (Lập trình Frontend)", "point": "Demo cổng tra cứu theo mã kiến nghị với timeline trạng thái, đang dùng dữ liệu giả", "turns": ["k_fe"]},
    {"speaker": "Anh Phong (Văn phòng Đoàn ĐBQH tỉnh)", "point": "Không hiển thị họ tên, địa chỉ người kiến nghị trên trang tra cứu", "turns": ["k_kh"]},
    {"speaker": "Hiếu (Kỹ sư AI)", "point": "Đề xuất chấm câu trả lời theo 3 tiêu chí: đúng trọng tâm, có hướng giải quyết và thời hạn, có căn cứ pháp lý", "turns": ["k_ai3"]}
  ]
}
```
