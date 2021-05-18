from torch import nn
from chem.data import JCIExtendedData, JCIData
import logging
import sys
from chem.models.base import JCIBaseNet

logging.getLogger('pysmiles').setLevel(logging.CRITICAL)


class ChemLSTM(JCIBaseNet):

    def __init__(self, in_d, out_d, num_classes, weights, **kwargs):
        super().__init__(num_classes, weights, **kwargs)
        self.lstm = nn.LSTM(in_d, out_d, batch_first=True)
        self.embedding = nn.Embedding(800, 100)
        self.output = nn.Sequential(nn.Linear(out_d, in_d), nn.ReLU(), nn.Dropout(0.2), nn.Linear(in_d, num_classes))

    def forward(self, data):
        x = data.x
        x = self.embedding(x)
        x = self.lstm(x)[1][0]
        x = self.output(x)
        return x.squeeze(0)
