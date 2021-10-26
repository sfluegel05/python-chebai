from torch.nn.utils.rnn import pad_sequence
import torch

from chebai.preprocessing.structures import XYData


class Collater:
    def __init__(self, **kwargs):
        pass

    def __call__(self, data):
        raise NotImplementedError


class DefaultCollater(Collater):
    def __call__(self, data):
        x, y = zip(*data)
        return XYData(x, y)


class RaggedCollater(Collater):
    def __call__(self, data):
        x, y = zip(*data)
        return XYData(
            pad_sequence([torch.tensor(a) for a in x], batch_first=True),
            pad_sequence([torch.tensor(a) for a in y], batch_first=True),
            additional_fields=dict(lens=list(map(len, x))),
        )