import os
from torch import nn
import torch
from sklearn.metrics import f1_score
import pytorch_lightning as pl
from pytorch_lightning import loggers as pl_loggers
from pytorch_lightning.callbacks import ModelCheckpoint, EarlyStopping
from pytorch_lightning.metrics import F1
from pytorch_lightning.metrics import MeanSquaredError
import logging
import sys

logging.getLogger('pysmiles').setLevel(logging.CRITICAL)


class JCIBaseNet(pl.LightningModule):

    def __init__(self, num_classes, weights, threshold=0.3):
        super().__init__()
        self.loss = nn.BCEWithLogitsLoss(weight=weights)
        self.f1 = F1(num_classes, threshold=threshold)
        self.mse = MeanSquaredError()

    def _execute(self, batch, batch_idx):
        pred = self(batch)
        labels = batch.y.float()
        loss = self.loss(pred, labels)
        f1 = self.f1(target=labels.int(), preds=torch.sigmoid(pred))
        mse = self.mse(labels, torch.sigmoid(pred))
        return loss, f1, mse

    def training_step(self, *args, **kwargs):
        loss, f1, mse = self._execute(*args, **kwargs)
        self.log('train_loss', loss.detach().item(), on_step=False, on_epoch=True, prog_bar=True, logger=True)
        self.log('train_f1', f1.item(), on_step=False, on_epoch=True, prog_bar=True, logger=True)
        self.log('train_mse', mse.item(), on_step=False, on_epoch=True,
                 prog_bar=True, logger=True)
        return loss

    def validation_step(self, *args, **kwargs):
        with torch.no_grad():
            loss, f1, mse = self._execute(*args, **kwargs)
            self.log('val_loss', loss.detach().item(), on_step=False, on_epoch=True, prog_bar=True, logger=True)
            self.log('val_f1', f1.item(), on_step=False, on_epoch=True, prog_bar=True, logger=True)
            self.log('val_mse', mse.item(), on_step=False, on_epoch=True,
                     prog_bar=True, logger=True)
            return loss

    def forward(self, x):
        raise NotImplementedError

    def configure_optimizers(self):
        optimizer = torch.optim.Adam(self.parameters())
        return optimizer

    @classmethod
    def run(cls, data, name, model_args: list = None, model_kwargs: dict = None):
        if model_args is None:
            model_args = []
        if model_kwargs is None:
            model_kwargs = {}
        data.prepare_data()
        data.setup()
        train_data = data.train_dataloader()
        val_data = data.val_dataloader()
        if torch.cuda.is_available():
            trainer_kwargs = dict(gpus=-1, accelerator="ddp")
        else:
            trainer_kwargs = dict(gpus=0)

        tb_logger = pl_loggers.CSVLogger('logs/', name=name)
        checkpoint_callback = ModelCheckpoint(
            dirpath=os.path.join(tb_logger.log_dir, "checkpoints"),
            filename="{epoch}-{step}-{val_loss:.7f}",
            save_top_k=5,
            save_last=True,
            verbose=True,
            monitor='val_loss',
            mode='min'
        )
        # Calculate weights per class
        weights = torch.sum(torch.cat([data.y for data in train_data]),dim=0)
        weights = (2*torch.max(weights)-weights)/torch.max(weights)
        net = cls(*model_args, weights=weights, **model_kwargs)
        es = EarlyStopping(monitor='val_loss', patience=10, min_delta=0.00,
           verbose=False,
        )

        trainer = pl.Trainer(logger=tb_logger, min_epochs=100, callbacks=[checkpoint_callback, es], replace_sampler_ddp=False, **trainer_kwargs)
        trainer.fit(net, train_data, val_dataloaders=val_data)