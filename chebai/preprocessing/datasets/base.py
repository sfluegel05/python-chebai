import random
import typing
from typing import List, Union
import os

from torch.utils.data import DataLoader
from lightning.pytorch.core.datamodule import LightningDataModule
import torch
import tqdm
import lightning as pl

from chebai.preprocessing import reader as dr


class XYBaseDataModule(LightningDataModule):
    READER = dr.DataReader

    def __init__(
        self,
        batch_size=1,
        train_split=0.85,
        reader_kwargs=None,
        prediction_kind="test",
        data_limit: typing.Optional[int] = None,
        label_filter: typing.Optional[int] = None,
        balance_after_filter: typing.Optional[float] = None,
        num_workers: int = 1,
        chebi_version: int = 200,
        **kwargs,
    ):
        super().__init__(**kwargs)
        if reader_kwargs is None:
            reader_kwargs = dict()
        self.reader = self.READER(**reader_kwargs)
        self.train_split = train_split
        self.batch_size = batch_size
        self.prediction_kind = prediction_kind
        self.data_limit = data_limit
        self.label_filter = label_filter
        assert (balance_after_filter is not None) or (
            self.label_filter is None
        ), "Filter balancing requires a filter"
        self.balance_after_filter = balance_after_filter
        self.num_workers = num_workers
        self.chebi_version = chebi_version
        os.makedirs(self.raw_dir, exist_ok=True)
        os.makedirs(self.processed_dir, exist_ok=True)

    @property
    def identifier(self):
        return (self.reader.name(),)

    @property
    def full_identifier(self):
        return (self._name, *self.identifier)

    @property
    def processed_dir(self):
        return os.path.join("data", self._name, f'chebi_v{self.chebi_version}', "processed", *self.identifier)

    @property
    def raw_dir(self):
        return os.path.join("data", self._name, f'chebi_v{self.chebi_version}', "raw")

    @property
    def _name(self):
        raise NotImplementedError

    def _filter_labels(self, row):
        row["labels"] = [row["labels"][self.label_filter]]
        return row

    def dataloader(self, kind, **kwargs):
        try:
            # processed_file_names_dict is only implemented for _ChEBIDataExtractor
            filename = self.processed_file_names_dict[kind]
        except NotImplementedError:
            filename = f"{kind}.pt"
        dataset = torch.load(os.path.join(self.processed_dir, filename))
        if self.label_filter is not None:
            original_len = len(dataset)
            dataset = [self._filter_labels(r) for r in dataset]
            positives = [r for r in dataset if r["labels"][0]]
            negatives = [r for r in dataset if not r["labels"][0]]
            if self.balance_after_filter is not None:
                negative_length = min(
                    original_len, int(len(positives) * self.balance_after_filter)
                )
                dataset = positives + negatives[:negative_length]
            else:
                dataset = positives + negatives
            random.shuffle(dataset)
        if self.data_limit is not None:
            dataset = dataset[: self.data_limit]
        return DataLoader(
            dataset,
            collate_fn=self.reader.collater,
            batch_size=self.batch_size,
            **kwargs,
        )

    @staticmethod
    def _load_dict(input_file_path):
        with open(input_file_path, "r") as input_file:
            for row in input_file:
                smiles, labels = row.split("\t")
                yield dict(features=smiles, labels=labels)

    @staticmethod
    def _get_data_size(input_file_path):
        with open(input_file_path, "r") as f:
            return sum(1 for _ in f)

    def _load_data_from_file(self, path):
        lines = self._get_data_size(path)
        print(f"Processing {lines} lines...")
        data = [
            self.reader.to_data(d)
            for d in tqdm.tqdm(self._load_dict(path), total=lines)
            if d["features"] is not None
        ]
        return data

    def train_dataloader(self, *args, **kwargs) -> DataLoader:
        return self.dataloader(
            "train", shuffle=True, num_workers=self.num_workers, **kwargs
        )

    def val_dataloader(self, *args, **kwargs) -> Union[DataLoader, List[DataLoader]]:
        return self.dataloader("validation", shuffle=False, **kwargs)

    def test_dataloader(self, *args, **kwargs) -> Union[DataLoader, List[DataLoader]]:
        return self.dataloader("test", shuffle=False, **kwargs)

    def predict_dataloader(
        self, *args, **kwargs
    ) -> Union[DataLoader, List[DataLoader]]:
        return self.dataloader(self.prediction_kind, shuffle=False, **kwargs)

    def setup(self, **kwargs):
        if any(
            not os.path.isfile(os.path.join(self.processed_dir, f))
            for f in self.processed_file_names
        ):
            self.setup_processed()

    def setup_processed(self):
        raise NotImplementedError

    @property
    def processed_file_names(self):
        raise NotImplementedError

    @property
    def processed_file_names_dict(self) -> dict:
        raise NotImplementedError

    @property
    def raw_file_names_dict(self) -> dict:
        raise NotImplementedError

    @property
    def label_number(self):
        """
        Number of labels
        :return:
        Returns -1 for seq2seq encoding, otherwise the number of labels
        """
        raise NotImplementedError


class MergedDataset(XYBaseDataModule):
    MERGED = []

    @property
    def _name(self):
        return "+".join(s._name for s in self.subsets)

    def __init__(self, batch_size=1, train_split=0.85, reader_kwargs=None, **kwargs):
        if reader_kwargs is None:
            reader_kwargs = [None for _ in self.MERGED]
        self.train_split = train_split
        self.batch_size = batch_size
        self.subsets = [
            s(train_split=train_split, reader_kwargs=kws)
            for s, kws in zip(self.MERGED, reader_kwargs)
        ]
        self.reader = self.subsets[0].reader
        os.makedirs(self.processed_dir, exist_ok=True)
        super(pl.LightningDataModule, self).__init__(**kwargs)

    def prepare_data(self):
        for s in self.subsets:
            s.prepare_data()

    def setup(self, **kwargs):
        for s in self.subsets:
            s.setup(**kwargs)

    def dataloader(self, kind, **kwargs):
        subdatasets = [
            torch.load(os.path.join(s.processed_dir, f"{kind}.pt"))
            for s in self.subsets
        ]
        dataset = [
            self._process_data(i, d)
            for i, (s, lim) in enumerate(zip(subdatasets, self.limits))
            for d in (s if lim is None else s[:lim])
        ]
        return DataLoader(
            dataset,
            collate_fn=self.reader.collater,
            batch_size=self.batch_size,
            **kwargs,
        )

    def train_dataloader(self, *args, **kwargs) -> DataLoader:
        return self.dataloader("train", shuffle=True, **kwargs)

    def val_dataloader(self, *args, **kwargs) -> Union[DataLoader, List[DataLoader]]:
        return self.dataloader("validation", shuffle=False, **kwargs)

    def test_dataloader(self, *args, **kwargs) -> Union[DataLoader, List[DataLoader]]:
        return self.dataloader("test", shuffle=False, **kwargs)

    def _process_data(self, subset_id, data):
        return dict(
            features=data["features"], labels=data["labels"], ident=data["ident"]
        )

    def setup_processed(self):
        pass

    @property
    def processed_file_names(self):
        return ["test.pt", "train.pt", "validation.pt"]

    @property
    def label_number(self):
        return self.subsets[0].label_number

    @property
    def limits(self):
        return None
