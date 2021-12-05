from tempfile import TemporaryDirectory
import logging
import random

from torch import nn
from torch.nn.utils.rnn import pack_padded_sequence, pad_packed_sequence
from transformers import (
    ElectraConfig,
    ElectraForMultipleChoice,
    ElectraForPreTraining,
    ElectraModel,
    PretrainedConfig,
)
import torch

from chebai.models.base import JCIBaseNet

logging.getLogger("pysmiles").setLevel(logging.CRITICAL)


class ElectraPre(JCIBaseNet):
    NAME = "ElectraPre"

    def __init__(self, **kwargs):
        super().__init__(**kwargs, p=0.2)
        self._p = 0.2
        self.config = ElectraConfig(**kwargs["config"])
        self.electra = ElectraForPreTraining(self.config)

    def _get_data_and_labels(self, batch, batch_idx):
        batch_labels = []
        batch_data = []
        for row in batch.x:
            vocabular = set(row)
            labels = []
            data = []
            for t in list(row):
                l = 0
                if not all(x == t for x in vocabular) and random.random() < self._p:
                    l = 1
                    t0 = t
                    while t0 == t:
                        # this takes the list of all tokens by desing
                        # it ensures that the probability distribution is roughly
                        # the same as in the original string.
                        t0 = random.choice(row)
                    t = t0
                data.append(t)
                labels.append(l)
            batch_data.append(data)
            batch_labels.append(labels)

        return torch.tensor(batch_data).to(self.device), torch.tensor(batch_labels).to(
            self.device
        )

    def forward(self, data):
        x = data
        x = self.electra(x)
        return x.logits


class Electra(JCIBaseNet):
    NAME = "Electra"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.config = ElectraConfig(**kwargs["config"], output_attentions=True)

        if "pretrained_checkpoint" in kwargs:
            elpre = ElectraPre.load_from_checkpoint(kwargs["pretrained_checkpoint"])
            with TemporaryDirectory() as td:
                elpre.electra.save_pretrained(td)
                self.electra = ElectraModel.from_pretrained(td, config=self.config)
                in_d = elpre.config.hidden_size
        else:
            self.electra = ElectraModel(config=self.config)
            in_d = self.config.hidden_size

        self.output = nn.Sequential(
            nn.Linear(in_d, in_d),
            nn.ReLU(),
            nn.Linear(in_d, in_d),
            nn.ReLU(),
            nn.Linear(in_d, in_d),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(in_d, 500),
        )

    def forward(self, data):
        electra = self.electra(data.x)
        d = torch.sum(electra.last_hidden_state, dim=1)
        return self.output(d)
