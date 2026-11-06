"""Entry point: loads the weights once at import, which on Lambda happens during init.

Local: uvicorn api.main:app    Lambda: handler = api.main.handler
"""
import logging
import os
from pathlib import Path

import torch
from mangum import Mangum

from api.app import create_app
from components.config import WEIGHTS_PATH
from components.inference import get_tokenizer, load_classifier

logging.basicConfig(level=logging.INFO)

threshold = float(os.environ.get("THRESHOLD", "0.8"))
if not 0.0 < threshold < 1.0:
    raise ValueError(f"THRESHOLD must be between 0 and 1, got {threshold}")

weights = Path(os.environ.get("WEIGHTS_PATH", WEIGHTS_PATH))
model, device = load_classifier(weights, device=torch.device("cpu"))
app = create_app(model, get_tokenizer(), device, threshold)

# lifespan="off": Mangum would otherwise run startup/shutdown on every invocation
handler = Mangum(app, lifespan="off")
