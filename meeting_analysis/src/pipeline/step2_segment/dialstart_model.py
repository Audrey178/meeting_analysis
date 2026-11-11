"""Kiến trúc mô hình DialSTART (dựa trên BERT), dùng để nạp trọng số đã huấn luyện cho bước chia chủ
đề. Gồm phần chấm độ liền mạch giữa hai đoạn hội thoại, phần biểu diễn chủ đề của từng lượt nói, và
cách tính độ "tụt" của điểm tại mỗi khoảng giữa hai lượt.
"""

import bisect
import warnings
from typing import Optional

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.nn import CrossEntropyLoss
from torch.nn.utils.rnn import pad_sequence
from transformers import BertForNextSentencePrediction
from transformers.modeling_outputs import NextSentencePredictorOutput
from transformers.models.bert.modeling_bert import (
    BertModel,
    BertOnlyNSPHead,
    BertPreTrainedModel,
)


class MarginRankingLoss():
    """Hàm mất mát xếp hạng có lề: phạt khi điểm mẫu dương không cao hơn mẫu âm ít nhất một lề.

    Với từng cặp, mất mát là ``max(0, margin - (điểm dương - điểm âm))``; kết quả là trung bình
    trên mọi cặp.

    Args:
        margin: Khoảng cách tối thiểu mong muốn giữa điểm dương và điểm âm.
    """

    def __init__(self, margin):
        self.margin = margin

    def __call__(self, p_scores, n_scores):
        """Tính mất mát trung bình cho các cặp (điểm dương, điểm âm) cùng vị trí.

        Args:
            p_scores: Tensor điểm của các mẫu dương.
            n_scores: Tensor điểm của các mẫu âm, cùng kích thước với ``p_scores``.

        Returns:
            Tensor vô hướng.
        """
        scores = self.margin - (p_scores - n_scores)
        scores = scores.clamp(min=0)

        return scores.mean()


class SegModel(nn.Module):
    """Mô hình DialSTART chấm độ liền mạch tại khe giữa hai phần hội thoại, gồm hai nhánh BERT.

    Nhánh liền mạch là một BERT dự đoán câu kế tiếp: đọc cặp (ngữ cảnh, lượt kế tiếp) và cho logit
    "liền mạch". Nhánh chủ đề là một BERT mã hoá từng lượt nói thành embedding chủ đề; độ giống
    chủ đề hai bên khe là cosine giữa embedding trung bình hai bên. Điểm cuối cùng của khe là tổng
    hai thành phần này, càng thấp càng dễ là chỗ chuyển chủ đề.

    Khi huấn luyện, mô hình học không cần nhãn ranh giới: lượt kế tiếp thật phải được chấm cao hơn
    lượt lấy ngẫu nhiên, và nhánh chủ đề được học thêm bằng phân đoạn giả (xem ``topic_train``).
    Khi chạy thật chỉ dùng ``infer`` hoặc gọi thẳng hai nhánh.

    Args:
        model_path: Tiền tố đường dẫn ghép trước tên hai backbone; rỗng thì nạp theo tên.
        margin: Lề của hàm mất mát xếp hạng.
        train_split: Số ranh giới giả lấy cho mỗi hội thoại khi phân đoạn giả lúc huấn luyện.
        window_size: Lưu lại làm thuộc tính; khi huấn luyện, cửa sổ thực sự dùng là tham số
            ``window_size`` truyền vào ``forward``.
        topic_model_name: Tên backbone của nhánh chủ đề.
        coheren_model_name: Tên backbone của nhánh liền mạch.
        gradient_checkpointing: Bật gradient checkpointing cho cả hai nhánh để tiết kiệm bộ nhớ
            khi huấn luyện.
    """

    def __init__(self, model_path='', margin=1, train_split=5, window_size=5,
                 topic_model_name='princeton-nlp/sup-simcse-bert-base-uncased',
                 coheren_model_name='bert-base-uncased',
                 gradient_checkpointing=False):
        super(SegModel, self).__init__()
        self.margin = margin
        self.train_split = train_split
        self.window_size = window_size
        self.topic_model = BertModel.from_pretrained(model_path+topic_model_name)
        self.coheren_model = BertForNextSentencePrediction.from_pretrained(model_path+coheren_model_name, num_labels=2,
                                                                   output_attentions=False,
                                                                   output_hidden_states=True)
        if gradient_checkpointing:
            self.topic_model.gradient_checkpointing_enable()
            self.coheren_model.bert.gradient_checkpointing_enable()

        self.topic_loss = nn.CrossEntropyLoss()
        self.score_loss = MarginRankingLoss(self.margin)

    def forward(self, input_data, window_size=None):
        """Tính mất mát huấn luyện cho một batch.

        Mỗi mẫu có một cặp dương (ngữ cảnh, lượt kế tiếp thật) và một cặp âm (ngữ cảnh, lượt lấy từ
        chỗ khác). Điểm mỗi cặp = logit liền mạch + cosine chủ đề giữa ngữ cảnh và lượt đó; mất mát
        xếp hạng có lề buộc cặp dương cao hơn cặp âm. Cộng thêm mất mát của nhánh chủ đề.

        Args:
            input_data: Dict tensor của batch do bộ tiền xử lý dữ liệu huấn luyện tạo ra: các cặp
                cho nhánh liền mạch (chiều thứ hai: 0 là cặp dương, 1 là cặp âm), các câu ngữ cảnh/
                dương/âm cho nhánh chủ đề kèm số câu của từng mẫu, và toàn bộ hội thoại cho
                ``topic_train``.
            window_size: Bán kính cửa sổ (số lượt) quanh lượt neo trong ``topic_train``. Bắt buộc
                truyền khi huấn luyện; giá trị None sẽ gây lỗi.

        Returns:
            Bộ ba (tổng mất mát, mất mát xếp hạng của điểm khe, mất mát của nhánh chủ đề).
        """
        device, topic_loss = input_data['coheren_inputs'].device, torch.tensor(0)
        topic_context_count, topic_pos_count, topic_neg_count = 0, 0, 0
        topic_context_mean, topic_pos_mean, topic_neg_mean = [], [], []
        
        coheren_pos_scores, coheren_pos_feature = self.coheren_model(input_data['coheren_inputs'][:, 0, :],
                                                                    attention_mask=input_data['coheren_mask'][:, 0, :],
                                                                    token_type_ids=input_data['coheren_type'][:, 0, :])
        coheren_neg_scores, coheren_neg_feature = self.coheren_model(input_data['coheren_inputs'][:, 1, :],
                                                                    attention_mask=input_data['coheren_mask'][:, 1, :],
                                                                    token_type_ids=input_data['coheren_type'][:, 1, :])

        batch_size = len(input_data['topic_context_num'])
        topic_context = self.topic_model(input_data['topic_context'], input_data['topic_context_mask'])[1]
        topic_pos = self.topic_model(input_data['topic_pos'], input_data['topic_pos_mask'])[1]
        topic_neg = self.topic_model(input_data['topic_neg'], input_data['topic_neg_mask'])[1]
    
        topic_loss = self.topic_train(input_data, window_size)

        for i, j, z in zip(input_data['topic_context_num'], input_data['topic_pos_num'], input_data['topic_neg_num']):
            topic_context_mean.append(torch.mean(topic_context[topic_context_count:topic_context_count + i], dim=0))
            topic_pos_mean.append(torch.mean(topic_pos[topic_pos_count:topic_pos_count + j], dim=0))
            topic_neg_mean.append(torch.mean(topic_neg[topic_neg_count:topic_neg_count + z], dim=0))
            topic_context_count, topic_pos_count, topic_neg_count = topic_context_count + i, topic_pos_count + j, topic_neg_count + z

        assert len(topic_context_mean) == len(topic_pos_mean) == len(topic_neg_mean) == batch_size

        topic_context_mean, topic_pos_mean = pad_sequence(topic_context_mean, batch_first=True), pad_sequence(topic_pos_mean, batch_first=True)
        topic_neg_mean = pad_sequence(topic_neg_mean, batch_first=True)

        topic_pos_scores = F.cosine_similarity(topic_context_mean, topic_pos_mean, dim=1,
                                            eps=1e-08).to(device)
        topic_neg_scores = F.cosine_similarity(topic_context_mean, topic_neg_mean, dim=1,
                                            eps=1e-08).to(device)

        pos_scores = coheren_pos_scores[0][:, 0] + topic_pos_scores
        neg_scores = coheren_neg_scores[0][:, 0] + topic_neg_scores

        margin_loss = self.score_loss(pos_scores, neg_scores)

        loss = margin_loss.clone() + topic_loss
        return loss, margin_loss, topic_loss

    def infer(self, coheren_input, coheren_mask, coheren_type_id, topic_input=None, topic_mask=None, topic_num=None):
        """Chấm điểm liền mạch cho một batch khe theo cách đánh giá gốc của DialSTART.

        Args:
            coheren_input: Mã token của các cặp (ngữ cảnh, lượt kế tiếp), mỗi khe một hàng.
            coheren_mask: Mặt nạ chú ý tương ứng.
            coheren_type_id: Mã loại đoạn tương ứng (0 cho ngữ cảnh, 1 cho lượt kế tiếp).
            topic_input: Cặp (câu bên trái khe, câu bên phải khe) cho nhánh chủ đề, mọi khe nối liền.
                Thực tế là bắt buộc dù có mặc định None.
            topic_mask: Cặp mặt nạ chú ý tương ứng với ``topic_input``.
            topic_num: Cặp (số câu bên trái, số câu bên phải) của từng khe, để tách lại theo khe.

        Returns:
            Danh sách điểm trong khoảng (0, 1), mỗi khe một điểm; thấp là dễ chuyển chủ đề.
        """
        device = coheren_input.device
        coheren_scores, coheren_feature = self.coheren_model(coheren_input, coheren_mask, coheren_type_id)

        topic_context = self.topic_model(topic_input[0], topic_mask[0])[1]
        topic_cur = self.topic_model(topic_input[1], topic_mask[1])[1]
        topic_context_count = topic_cur_count = 0
        topic_context_mean, topic_cur_mean = [], []

        for i, j in zip(topic_num[0], topic_num[1]):
            topic_context_mean.append(torch.mean(topic_context[topic_context_count:topic_context_count + i], dim=0))
            topic_cur_mean.append(torch.mean(topic_cur[topic_cur_count:topic_cur_count + j], dim=0))
            topic_context_count, topic_cur_count = topic_context_count + i, topic_cur_count + j
        topic_context_mean, topic_cur_mean = pad_sequence(topic_context_mean, batch_first=True), pad_sequence(topic_cur_mean, batch_first=True)
        topic_scores = F.cosine_similarity(topic_context_mean, topic_cur_mean, dim=1, eps=1e-08).to(device)  
        final_scores = coheren_scores[0][:, 0] + topic_scores

        return torch.sigmoid(final_scores).detach().cpu().numpy().tolist()

    def topic_train(self, input_data, window_size):
        """Tính mất mát tương phản cho nhánh chủ đề bằng phân đoạn giả, không cần nhãn ranh giới.

        Với mỗi hội thoại trong batch: mã hoá mọi lượt nói, so cosine giữa hai lượt trước và hai
        lượt sau mỗi khe, lấy ``train_split`` khe có độ tụt lớn nhất làm ranh giới giả. Lượt neo là
        lượt kế tiếp của mẫu. Mẫu dương là các lượt cùng đoạn giả với lượt neo và cách nó không quá
        ``window_size`` lượt; mẫu âm là mọi lượt khác trong cả batch nằm ngoài đoạn đó và ngoài cửa
        sổ đó. Mất mát xếp hạng có lề được tính trên mọi cặp (dương, âm), rồi lấy trung bình theo
        mẫu; mẫu không có lượt dương hoặc ra NaN bị bỏ qua.

        Args:
            input_data: Dict tensor của batch; dùng toàn bộ câu hội thoại đã nối và, cho từng mẫu,
                cặp (số lượt của hội thoại, vị trí lượt neo).
            window_size: Bán kính cửa sổ (số lượt) quanh lượt neo.

        Returns:
            Tensor vô hướng; bằng 0 nếu mọi mẫu đều bị bỏ qua.
        """
        device, batch_size = input_data['coheren_inputs'].device, len(input_data['topic_context_num'])
        topic_all = self.topic_model(input_data['topic_train'], input_data['topic_train_mask'])[1]
        true_segments, segments, neg_utts, seg_num, count, margin_count, topic_loss = [], [], [], [], 0, batch_size, torch.tensor(0).to(device, dtype=torch.float)

        # pseudo-segmentation
        for b in range(batch_size):
            cur_num = input_data['topic_num'][b]
            dial_len, cur_utt = cur_num[0], cur_num[1]
            cur = topic_all[count:count+dial_len]
            assert dial_len > cur_utt

            top_cons, top_curs = [], []
            for i in range(1, dial_len):
                top_con = torch.mean(cur[max(0, i-2): i], dim=0)
                top_cur = torch.mean(cur[i: min(dial_len, i+2)], dim=0)
                top_cons.append(top_con)
                top_curs.append(top_cur)
            
            top_cons, top_curs = pad_sequence(top_cons, batch_first=True), pad_sequence(top_curs, batch_first=True)
            topic_scores = F.cosine_similarity(top_cons, top_curs, dim=1, eps=1e-08).to(device)  
            depth_scores = tet(torch.sigmoid(topic_scores))
            tet_seg = np.argsort(np.array(depth_scores))[-self.train_split:] + 1
            tet_seg = [0] + tet_seg.tolist() + [dial_len]
            tet_seg.sort()

            tet_mid = bisect.bisect(tet_seg, cur_utt)
            tet_mid_seg = (tet_seg[tet_mid-1], tet_seg[tet_mid])
                
            pos_left = max(tet_mid_seg[0], cur_utt - window_size)
            pos_right = min(tet_mid_seg[1], cur_utt + window_size+1)

            neg_left = min(tet_seg[max(0, tet_mid-1)], cur_utt - window_size)
            neg_right = max(tet_seg[tet_mid], cur_utt + window_size+1)

            mid = torch.mean(cur[pos_left:pos_right], dim=0).unsqueeze(0)
            segments.append([[mid], (pos_left, pos_right), count, (neg_left, neg_right)])

            count += dial_len

        # Margin loss
        for b in range(batch_size):
            cur_seg = segments[b]
            mid_left, mid_right = cur_seg[1]
            neg_left, neg_right = cur_seg[3]
            count, cur_num = cur_seg[2], input_data['topic_num'][b]
            dial_len, cur_utt, mid_seg = cur_num[0], cur_num[1], cur_seg[0][0]
            
            neg = torch.cat((topic_all[:count+neg_left], topic_all[count+neg_right:]), dim=0)

            anchor = topic_all[count+cur_utt].unsqueeze(0)
            pos = torch.cat((topic_all[count+mid_left:count+cur_utt], topic_all[count+cur_utt+1:count+mid_right]), dim=0)
            pos_score = F.cosine_similarity(anchor, pos, dim=1)
            
            if pos_score.shape[0] == 0:
                margin_count -= 1
                continue
            
            neg_score = F.cosine_similarity(anchor, neg, dim=1)
            margin_pos = pos_score.unsqueeze(0).repeat(neg_score.shape[0], 1).T.flatten()
            margin_neg = neg_score.repeat(pos_score.shape[0])
            assert margin_pos.shape == margin_neg.shape
            cur_loss = self.score_loss(margin_pos, margin_neg)
            if torch.isnan(cur_loss):
                print('Encounter nan:', pos_score.shape, neg_score.shape)
                margin_count -= 1
                continue
            topic_loss += cur_loss

        # Every sample may be skipped (empty positive window / nan); dividing
        # by zero would turn the whole batch loss into nan.
        if margin_count > 0:
            topic_loss /= margin_count
        return topic_loss


class BertForNextSentencePrediction(BertPreTrainedModel):
    """BERT dự đoán câu kế tiếp, bản sửa để trả thêm vector gộp của câu.

    Giống lớp cùng tên của thư viện ``transformers`` (định nghĩa này che lớp được import ở đầu
    file), chỉ khác: khi trả kết quả dạng đối tượng thì trả cặp (kết quả, vector gộp) để nhánh liền
    mạch dùng được cả logit lẫn đặc trưng. Tên lớp và cấu trúc giữ nguyên để nạp được trọng số.

    Args:
        config: Cấu hình BERT.
    """

    def __init__(self, config):
        super().__init__(config)

        self.bert = BertModel(config)
        self.cls = BertOnlyNSPHead(config)

        # Initialize weights and apply final processing
        self.post_init()

    def forward(
        self,
        input_ids: Optional[torch.Tensor] = None,
        attention_mask: Optional[torch.Tensor] = None,
        token_type_ids: Optional[torch.Tensor] = None,
        position_ids: Optional[torch.Tensor] = None,
        head_mask: Optional[torch.Tensor] = None,
        inputs_embeds: Optional[torch.Tensor] = None,
        labels: Optional[torch.Tensor] = None,
        output_attentions: Optional[bool] = None,
        output_hidden_states: Optional[bool] = None,
        return_dict: Optional[bool] = None,
        return_feature = False,
        **kwargs,
    ):
        """Chạy BERT trên cặp câu và trả logit dự đoán câu kế tiếp.

        Các tham số trùng với lớp gốc của ``transformers``. Logit cột 0 là "câu sau nối tiếp câu
        trước", cột 1 là "không nối tiếp".

        Args:
            input_ids: Mã token của cặp câu.
            attention_mask: Mặt nạ chú ý.
            token_type_ids: Mã loại đoạn (0 cho câu đầu, 1 cho câu sau).
            labels: Nhãn 0/1 để tính mất mát; None thì không tính.
            return_dict: Trả dạng đối tượng hay tuple; None thì theo cấu hình mô hình.
            return_feature: Không được dùng, giữ cho tương thích chữ ký.
            **kwargs: Chỉ nhận ``next_sentence_label`` (tên cũ của ``labels``, sẽ bị bỏ).

        Returns:
            Khi trả dạng đối tượng: cặp (kết quả gồm mất mát, logit, hidden state, attention;
            vector gộp của câu). Khi trả dạng tuple: giống lớp gốc, mất mát (nếu có) đứng đầu.
        """

        if "next_sentence_label" in kwargs:
            warnings.warn(
                "The `next_sentence_label` argument is deprecated and will be removed in a future version, use"
                " `labels` instead.",
                FutureWarning,
            )
            labels = kwargs.pop("next_sentence_label")

        return_dict = return_dict if return_dict is not None else self.config.use_return_dict

        outputs = self.bert(
            input_ids,
            attention_mask=attention_mask,
            token_type_ids=token_type_ids,
            position_ids=position_ids,
            head_mask=head_mask,
            inputs_embeds=inputs_embeds,
            output_attentions=output_attentions,
            output_hidden_states=output_hidden_states,
            return_dict=return_dict,
        )

        pooled_output = outputs[1]

        seq_relationship_scores = self.cls(pooled_output)

        next_sentence_loss = None
        if labels is not None:
            loss_fct = CrossEntropyLoss()
            next_sentence_loss = loss_fct(seq_relationship_scores.view(-1, 2), labels.view(-1))

        if not return_dict:
            output = (seq_relationship_scores,) + outputs[2:]
            return ((next_sentence_loss,) + output) if next_sentence_loss is not None else output

        return NextSentencePredictorOutput(
            loss=next_sentence_loss,
            logits=seq_relationship_scores,
            hidden_states=outputs.hidden_states,
            attentions=outputs.attentions,
        ), pooled_output

def tet(scores):
	"""Tính độ tụt (depth score) của từng khe so với đỉnh gần nhất hai bên, kiểu TextTiling.

	Chỉ dùng khi huấn luyện, để phân đoạn giả trong ``SegModel.topic_train``; tên hàm giữ theo mã
	DialSTART gốc. Phía suy luận dùng hàm ``depth_scores`` với cùng cách tính.

	Nhận được cả tensor (kể cả trên GPU) nhưng chuyển sang list trên CPU trước khi duyệt: đọc từng
	phần tử của tensor GPU buộc đồng bộ thiết bị ở mỗi phép so sánh và làm huấn luyện chậm hẳn.

	Args:
		scores: Điểm của từng khe (tensor hoặc list số thực).

	Returns:
		Danh sách độ tụt, cùng độ dài với ``scores``.
	"""
	if torch.is_tensor(scores):
		scores = scores.detach().float().cpu().tolist()
	output_scores = []
	n = len(scores)
	for i in range(n):
		lflag = rflag = scores[i]
		for r in range(i+1, n):
			if rflag <= scores[r]:
				rflag = scores[r]
			else:
				break
		for l in range(i-1, -1, -1):
			if lflag <= scores[l]:
				lflag = scores[l]
			else:
				break
		output_scores.append(0.5*(lflag+rflag-2*scores[i]))

	return output_scores
