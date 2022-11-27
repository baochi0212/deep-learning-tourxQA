import torch
import torch.nn as nn
from torchcrf import CRF
from .modules import *


class JointLSTM(nn.Module):
    def __init__(self, args, vocab_size, intent_label_lst, slot_label_lst):
        self.args = args
        self.lstm = nn.LSTM(args.hidden_size, args.hidden_size, args.rnn_num_layers, batch_first=True)
        self.intent_classifier = IntentClassifier(args.hidden_size, self.num_intent_labels, args.dropout_rate)
        self.num_intent_labels = len(intent_label_lst)
        self.num_slot_labels = len(slot_label_lst)
        self.slot_classifier = SlotClassifier(
            args.hidden_dim,
            self.num_intent_labels,
            self.num_slot_labels,
            self.args.use_intent_context_concat,
            self.args.use_intent_context_attention,
            self.args.max_seq_len,
            self.args.attention_embedding_size,
            args.dropout_rate,
        )

        if args.use_crf:
            self.crf = CRF(num_tags=self.num_slot_labels, batch_first=True)
    
    def forward(self, x, intent_label_ids, slot_labels_ids):
        #embedding:
        x = self.embedding(x)
        #initialize the hidden states (b x n_layers x h)
        h_0 = torch.zeros(self.args.batch_size, self.args.rnn_num_layers, self.args.hidden_dim)
        c_0 = torch.zeros_like(self.args.batch_size, self.args.rnn_num_layers, self.args.hidden_dim)
        out, (h_n, c_n) = self.lstm(x, (h_0, c_0))

        hidden_state = h_n[:, -1, :]
        intent_logits = self.intent_classifier(hidden_state)

        if self.args.embedding_type == "hard":
            hard_intent_logits = torch.zeros(intent_logits.shape)
            for i, sample in enumerate(intent_logits):
                max_idx = torch.argmax(sample)
                hard_intent_logits[i][max_idx] = 1
            slot_logits = self.slot_classifier(out, hard_intent_logits)
        else:
            slot_logits = self.slot_classifier(out, intent_logits)

        total_loss = 0
        # 1. Intent Softmax
        if intent_label_ids is not None:
            if self.num_intent_labels == 1:
                intent_loss_fct = nn.MSELoss()
                intent_loss = intent_loss_fct(intent_logits.view(-1), intent_label_ids.view(-1))
            else:
                intent_loss_fct = nn.CrossEntropyLoss()
                intent_loss = intent_loss_fct(
                    intent_logits.view(-1, self.num_intent_labels), intent_label_ids.view(-1)
                )
            total_loss += self.args.intent_loss_coef * intent_loss

            # 2. Slot Softmax
            if slot_labels_ids is not None:
                if self.args.use_crf:
                    slot_loss = self.crf(slot_logits, slot_labels_ids, mask=attention_mask.byte(), reduction="mean")
                    slot_loss = -1 * slot_loss  # negative log-likelihood
                else:
                    slot_loss_fct = nn.CrossEntropyLoss(ignore_index=self.args.ignore_index)
                    # Only keep active parts of the loss
                    if attention_mask is not None:
                        active_loss = attention_mask.view(-1) == 1
                        active_logits = slot_logits.view(-1, self.num_slot_labels)[active_loss]
                        active_labels = slot_labels_ids.view(-1)[active_loss]
                        slot_loss = slot_loss_fct(active_logits, active_labels)
                    else:
                        slot_loss = slot_loss_fct(slot_logits.view(-1, self.num_slot_labels), slot_labels_ids.view(-1))
                total_loss += (1 - self.args.intent_loss_coef) * slot_loss

            outputs = ((intent_logits, slot_logits),) + outputs[2:]  # add hidden states and attention if they are here

            outputs = (total_loss,) + outputs

            return outputs  # (loss), logits, (hidden_states), (attentions) # Logits is a tuple of intent and slot logits



