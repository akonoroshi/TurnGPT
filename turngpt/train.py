from argparse import ArgumentParser
from os import makedirs
from os.path import join
from pytorch_lightning.loggers import WandbLogger
from pytorch_lightning.callbacks import ModelCheckpoint, EarlyStopping

import pytorch_lightning as pl

from datasets_turntaking.dialog_text_dm_rev2 import ConversationalDM2  # put the old conversationldm
from datasets_turntaking.dialog_text_dm import ConversationalDM
from turngpt.model import TurnGPT, TurnGPTWandbCallbacks

import os
os.environ["TOKENIZERS_PARALLELISM"] = "true"

PROJECT = "TurnGPT"
SAVE_DIR = "runs/TurnGPT"


def default_logger_callbacks(name, args, callbacks):
    makedirs(SAVE_DIR, exist_ok=True)
    logger = WandbLogger(
        save_dir=SAVE_DIR,
        project=PROJECT,
        name=name + args.name_info,
        log_model=False,
        id=args.id,
        resume=args.resume
    )

    # logger.watch(model)

    id_hash = logger.experiment.path.split("/")[-1]
    ch_path = join(logger.save_dir, logger.name + "_" + id_hash)
    callbacks.append(
        ModelCheckpoint(
            dirpath=ch_path,
            filename="{epoch}_{val_loss:.4f}",
            save_top_k=2,
            mode="min",
            monitor="val_loss",
        )
    )

    print(f"Early stopping (patience={args.patience})")
    early_stop_callback = EarlyStopping(
        monitor="val_loss",
        patience=args.patience,
        strict=True,  # crash if "monitor" is not found in val metrics
        verbose=True,
    )
    callbacks.append(early_stop_callback)
    return logger, callbacks


def train():
    parser = ArgumentParser()
    parser = TurnGPT.add_model_specific_args(parser)
    parser = ConversationalDM2.add_data_specific_args(parser)
    parser = pl.Trainer.add_argparse_args(parser)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--name_info", type=str, default="")
    parser.add_argument("--early_stopping", action="store_true")
    parser.add_argument("--patience", default=10, type=int)
    parser.add_argument("--load_from_checkpoint", action='store_true')
    parser.add_argument("--resume", default=None)
    parser.add_argument("--id", default=None)
    args = parser.parse_args()

    print("Datasets: ", args.datasets)

    pl.seed_everything(args.seed)

    # Model
    print("Loading Model...")
    ckpt_path = None
    if args.load_from_checkpoint:
        model = TurnGPT.load_from_checkpoint(args.pretrained_model_name_or_path)
        ckpt_path = args.pretrained_model_name_or_path
    else:
        model = TurnGPT(
            pretrained_model_name_or_path=args.pretrained_model_name_or_path,
            trp_projection_steps=args.trp_projection_steps,
            trp_projection_type=args.trp_projection_type,
            weight_loss=args.weight_loss,
            weight_eos_token=args.weight_eos_token,
            weight_regular_token=args.weight_regular_token,
            learning_rate=args.learning_rate,
            dropout=args.dropout,
            pretrained=args.pretrained,
            no_train_first_n=args.no_train_first_n,
            omit_dialog_states=args.omit_dialog_states,
            weight_decay=args.weight_decay,
            num_speakers=args.num_speakers,
            use_closeup=args.use_closeup,
            use_corner=args.use_corner,
        )
        model.init_tokenizer()  # required for fresh model (saved on checkpoint)
        model.initialize_special_embeddings()  # required for fresh model (also performed in on_load_checkpoint)
    model.print_parameters()

    # DataModule
    if args.num_speakers == 2:
        dm = ConversationalDM(
            datasets=args.datasets,
            tokenizer=model.tokenizer,
            batch_size=args.batch_size,
            max_length=args.max_length,
            num_workers=args.num_workers,
            pin_memory=args.pin_memory,
            savepath=args.savepath,
            overwrite=args.overwrite,
            load_from_cache_file=args.load_from_cache_file,
            num_proc=args.num_proc,
        )

    else:
        dm = ConversationalDM2(
            datasets=args.datasets,
            tokenizer=model.tokenizer,
            batch_size=args.batch_size,
            max_length=args.max_length,
            num_workers=args.num_workers,
            pin_memory=args.pin_memory,
            savepath=args.savepath,
            overwrite=args.overwrite,
            load_from_cache_file=args.load_from_cache_file,
            num_proc=args.num_proc,
            tensorpath=args.tensorpath,
        )

    dm.prepare_data()

    logger = None
    callbacks = None

    # this should be handled automatically with pytorch_lightning?
    if not args.fast_dev_run:
        callbacks = [TurnGPTWandbCallbacks()]
        logger, callbacks = default_logger_callbacks(
            name=model.run_name, args=args, callbacks=callbacks
        )

    # Trainer
    trainer = pl.Trainer.from_argparse_args(
        args=args,
        logger=logger,
        callbacks=callbacks,
    )

    trainer.fit(model, datamodule=dm, ckpt_path=ckpt_path)


if __name__ == "__main__":
    train()
