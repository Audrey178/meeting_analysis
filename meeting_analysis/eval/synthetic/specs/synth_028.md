```json meta
{
  "meeting_id": "synth_028",
  "title": "Họp sprint nhóm ứng dụng ví điện tử - chuẩn bị phát hành bản 2.4",
  "meeting_type": "software_project",
  "length_bucket": "S",
  "tags": ["short_meeting", "pronoun_actor"],
  "speakers": {
    "TL": "Anh Kiên (Trưởng nhóm Mobile)",
    "AD": "Quân (Lập trình Android)",
    "IOS": "Thảo (Lập trình iOS)",
    "QA": "Chị Yến (Kiểm thử)",
    "PAY": "Anh Sang (Tích hợp thanh toán)"
  }
}
```

## TOPIC | Sửa lỗi đăng nhập bằng sinh trắc học trên Android | Lỗi đăng nhập vân tay thất bại trên một số máy Samsung Android 14 sau khi người dùng đổi vân tay, chiếm khoảng 4% phiên đăng nhập; thống nhất khi khóa sinh trắc học bị vô hiệu thì tự chuyển về đăng nhập mã PIN và yêu cầu đăng ký lại.

@TL: Rồi, họp nhanh sprint cuối trước khi phát hành 2.4 nhé. Có ba việc, lỗi đăng nhập vân tay trên Android, tích hợp VietQR, và checklist phát hành. Quân nói lỗi vân tay trước.

@AD #k_ad: Dạ. Lỗi này là từ tuần trước bên chăm sóc khách hàng báo lên, người dùng không đăng nhập được bằng vân tay, bấm vào thì ứng dụng báo lỗi rồi văng ra màn hình chính. Em lấy log trên Firebase thì lỗi tập trung ở các máy Samsung chạy Android 14, chiếm khoảng 4% tổng số phiên đăng nhập bằng sinh trắc học trong tuần. Nguyên nhân là khi người dùng thêm hoặc xóa vân tay trong cài đặt máy, thì hệ điều hành tự vô hiệu hóa cái khóa mã hóa mà mình tạo ra lúc bật đăng nhập vân tay, đây là cơ chế bảo mật của Android, đúng thôi. Nhưng mà code của mình không bắt cái ngoại lệ đó, nên ứng dụng bị văng. Trên iOS thì Thảo có kiểm tra rồi, không bị vì bên iOS mình đã xử lý trường hợp này từ trước.

@IOS: Dạ đúng anh, bên iOS khi Face ID hay Touch ID thay đổi thì mình đã tự chuyển về nhập mã PIN rồi hiện thông báo bảo người dùng bật lại sinh trắc học.

@QA: Chị có thử trên ba máy Samsung ở phòng kiểm thử thì tái hiện được trên hai máy, còn một máy Android 13 thì không bị. Chị thấy ngoài cái văng ứng dụng thì còn một vấn đề là sau khi văng, người dùng mở lại vẫn bị văng tiếp, không có đường nào vào được, phải xóa ứng dụng cài lại, mà cài lại thì phải xác thực lại tài khoản bằng giấy tờ tùy thân, rất phiền.

@AD: Dạ em đề xuất xử lý giống iOS, là bắt ngoại lệ khóa bị vô hiệu, xóa khóa cũ, chuyển người dùng về màn hình nhập mã PIN, sau khi đăng nhập bằng PIN thì hiện hộp thoại mời bật lại vân tay. Em ước khoảng hai ngày cả code lẫn tự kiểm tra.

@TL #d_vantay: Ok, chốt xử lý như Quân nói, giống hành vi bên iOS. Quân làm, chị Yến kiểm thử lại trên cả ba máy Samsung và thêm máy Xiaomi nữa cho chắc. Cái này phải có trong bản 2.4.

@AD #a_vantay: Dạ, thứ Tư em đẩy bản sửa.

@QA #a_kiemthu_vt: Ok, thứ Năm chị test xong.

## TOPIC | Tích hợp thanh toán bằng mã VietQR | Tích hợp quét và tạo mã VietQR cơ bản đã xong nhưng đối soát với ngân hàng đối tác còn lệch khi giao dịch bị timeout; thống nhất đưa VietQR vào bản 2.4 dưới dạng bật theo cờ cho 10% người dùng, xử lý timeout bằng truy vấn trạng thái giao dịch.

@TL: Sang VietQR. Anh Sang nói đi.

@PAY #k_pay: Ừ. Phần VietQR thì chức năng quét mã để chuyển tiền và tạo mã nhận tiền đã xong cả hai nền tảng. Kiểm thử trên môi trường thử nghiệm của ngân hàng đối tác thì ổn. Vấn đề còn lại là trường hợp timeout. Khi người dùng quét mã chuyển tiền, mình gửi lệnh sang ngân hàng, nếu sau 30 giây không có phản hồi thì ứng dụng hiện là giao dịch thất bại. Nhưng mà thực tế có khoảng 0,3% trường hợp ngân hàng vẫn xử lý thành công sau đó, tức là tiền đã trừ mà ứng dụng báo thất bại. Người dùng thấy thất bại lại chuyển lần nữa, thành ra chuyển hai lần. Bên đối soát cuối ngày phát hiện lệch, phải hoàn tiền thủ công.

@QA: Cái này nghiêm trọng đấy anh, ví điện tử mà trừ tiền hai lần là lên báo luôn.

@PAY: Đúng. Nên anh đề xuất là khi timeout thì không báo thất bại ngay, mà hiện trạng thái đang xử lý, rồi ứng dụng gọi API truy vấn trạng thái giao dịch của ngân hàng mỗi 10 giây trong tối đa 3 phút, có kết quả thì cập nhật. Trong lúc đang xử lý thì chặn không cho chuyển lại cùng số tiền cho cùng người nhận. API truy vấn thì ngân hàng có sẵn rồi, anh làm khoảng ba ngày.

@IOS: Phía giao diện thì em với Quân phải làm thêm màn hình trạng thái đang xử lý, cái này nhỏ thôi anh.

@TL #d_vietqr: Ok. Nhưng mà với rủi ro như vậy thì anh không muốn mở cho tất cả người dùng ngay. Anh chốt là VietQR có trong bản 2.4 nhưng bật theo cờ tính năng, mở cho 10% người dùng trước, theo dõi một tuần, không có lệch đối soát thì mở rộng. Xử lý timeout theo cách anh Sang nói. Anh Sang làm phần truy vấn trạng thái, còn màn hình đang xử lý thì hai bạn làm mỗi người một nền tảng.

@PAY #a_timeout: Ok, anh làm xong thứ Năm.

## TOPIC | Rà soát checklist và lịch phát hành bản 2.4 lên kho ứng dụng | Thống nhất đóng băng code ngày thứ Sáu, nộp lên App Store và Google Play thứ Hai tuần sau, phát hành dần 20% trong 3 ngày đầu; phân công viết ghi chú phát hành và kịch bản kiểm thử hồi quy.

@TL: Rồi, cuối cùng là lịch phát hành. Anh đề xuất đóng băng code thứ Sáu tuần này, cuối tuần chị Yến chạy hồi quy, thứ Hai nộp lên cả hai kho. Mọi người có kịp không?

@QA #k_qa: Chị thì cần ít nhất hai ngày cho hồi quy vì bản này đụng vào cả đăng nhập lẫn thanh toán, hai luồng nhạy cảm nhất. Chị sẽ làm thứ Bảy và Chủ nhật, nhưng mà cần có kịch bản kiểm thử cho VietQR, hiện chưa có. Với lại bên iOS thì App Store thường duyệt mất một đến hai ngày, nên thứ Hai nộp thì sớm nhất thứ Tư mới lên.

@IOS: Dạ em nghĩ là với Google Play thì mình nên dùng phát hành dần, mở 20% người dùng ba ngày đầu, có lỗi thì dừng được. App Store thì cũng có phát hành theo giai đoạn bảy ngày.

@TL #d_lich: Ok, chốt lịch: đóng băng code thứ Sáu, hồi quy cuối tuần, nộp cả hai kho thứ Hai, Google Play phát hành dần 20% trong ba ngày đầu, App Store dùng phát hành theo giai đoạn. Về kịch bản kiểm thử VietQR thì anh Sang viết giúp chị Yến vì anh hiểu các trường hợp lỗi nhất, gửi trước thứ Sáu.

@PAY #a_kichban: Ok anh viết.

@TL #a_ghichu: Ghi chú phát hành thì phần sửa lỗi vân tay thì bạn nào sửa lỗi đăng nhập lúc nãy viết luôn phần đó nhé, phần VietQR thì anh viết, gửi Thảo tổng hợp rồi đưa lên kho.

@AD #a_ghichu_ok: Dạ vâng, em viết phần đó gửi Thảo.

@IOS #a_tonghop: Dạ em tổng hợp và nộp lên cả hai kho thứ Hai.

@TL: Ok, cảm ơn cả nhà, cố gắng tuần này nhé.

```json gold
{
  "assignments": [
    {"actor": "Quân (Lập trình Android)", "actor_aliases": ["Quân", "em"], "task": "Sửa lỗi đăng nhập vân tay Android: bắt ngoại lệ khóa bị vô hiệu, chuyển về mã PIN, mời bật lại", "deadline": "thứ Tư", "turns": ["d_vantay", "a_vantay"]},
    {"actor": "Chị Yến (Kiểm thử)", "actor_aliases": ["chị Yến", "chị"], "task": "Kiểm thử lại lỗi vân tay trên 3 máy Samsung và máy Xiaomi", "deadline": "thứ Năm", "turns": ["d_vantay", "a_kiemthu_vt"]},
    {"actor": "Anh Sang (Tích hợp thanh toán)", "actor_aliases": ["anh Sang"], "task": "Làm xử lý timeout VietQR bằng truy vấn trạng thái giao dịch và chặn chuyển trùng", "deadline": "thứ Năm", "turns": ["d_vietqr", "a_timeout"]},
    {"actor": "Quân (Lập trình Android)", "actor_aliases": ["hai bạn"], "task": "Làm màn hình trạng thái đang xử lý giao dịch trên Android", "deadline": null, "turns": ["d_vietqr"]},
    {"actor": "Thảo (Lập trình iOS)", "actor_aliases": ["hai bạn"], "task": "Làm màn hình trạng thái đang xử lý giao dịch trên iOS", "deadline": null, "turns": ["d_vietqr"]},
    {"actor": "Anh Sang (Tích hợp thanh toán)", "actor_aliases": ["anh Sang"], "task": "Viết kịch bản kiểm thử VietQR cho chị Yến", "deadline": "trước thứ Sáu", "turns": ["d_lich", "a_kichban"]},
    {"actor": "Quân (Lập trình Android)", "actor_aliases": ["bạn nào sửa lỗi đăng nhập lúc nãy", "em"], "task": "Viết ghi chú phát hành phần sửa lỗi vân tay gửi Thảo", "deadline": null, "turns": ["a_ghichu", "a_ghichu_ok"]},
    {"actor": "Anh Kiên (Trưởng nhóm Mobile)", "actor_aliases": ["anh"], "task": "Viết ghi chú phát hành phần VietQR", "deadline": null, "turns": ["a_ghichu"]},
    {"actor": "Thảo (Lập trình iOS)", "actor_aliases": ["Thảo"], "task": "Tổng hợp ghi chú phát hành và nộp bản 2.4 lên cả hai kho", "deadline": "thứ Hai", "turns": ["a_ghichu", "a_tonghop"]},
    {"actor": "Chị Yến (Kiểm thử)", "actor_aliases": ["chị"], "task": "Chạy kiểm thử hồi quy bản 2.4", "deadline": "thứ Bảy và Chủ nhật", "turns": ["k_qa", "d_lich"]}
  ],
  "decisions": [
    {"text": "Xử lý lỗi vân tay Android giống iOS: khóa bị vô hiệu thì chuyển về mã PIN và mời bật lại; bắt buộc có trong 2.4", "turns": ["d_vantay"]},
    {"text": "VietQR có trong 2.4 nhưng bật theo cờ cho 10% người dùng, theo dõi 1 tuần; timeout xử lý bằng truy vấn trạng thái", "turns": ["d_vietqr"]},
    {"text": "Đóng băng code thứ Sáu, hồi quy cuối tuần, nộp hai kho thứ Hai; Google Play phát hành dần 20% ba ngày đầu, App Store phát hành theo giai đoạn", "turns": ["d_lich"]}
  ],
  "negatives": [],
  "key_points": [
    {"speaker": "Quân (Lập trình Android)", "point": "Lỗi vân tay trên Samsung Android 14 (~4% phiên) do khóa bị vô hiệu khi đổi vân tay mà code không bắt ngoại lệ", "turns": ["k_ad"]},
    {"speaker": "Anh Sang (Tích hợp thanh toán)", "point": "Khoảng 0,3% giao dịch timeout nhưng ngân hàng vẫn xử lý thành công, gây chuyển tiền hai lần", "turns": ["k_pay"]},
    {"speaker": "Chị Yến (Kiểm thử)", "point": "Cần 2 ngày hồi quy và kịch bản kiểm thử VietQR; App Store duyệt 1-2 ngày", "turns": ["k_qa"]}
  ]
}
```
