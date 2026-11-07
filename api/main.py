"""Entry point: loads the weights once at import, which on Lambda happens during init.

Local: uvicorn api.main:app    Lambda: handler = api.main.handler
"""
import time

_t0 = time.perf_counter()

import logging
import os
from pathlib import Path

import torch
from mangum import Mangum

from api.app import create_app
from components.config import WEIGHTS_PATH
from components.inference import get_tokenizer, load_classifier

_t_import = time.perf_counter()

logging.basicConfig(level=logging.INFO)
# The Lambda runtime installs its own root handler, so basicConfig is a no-op there and the
# root level stays at WARNING; set it explicitly so the count/latency lines reach CloudWatch.
logging.getLogger().setLevel(logging.INFO)

threshold = float(os.environ.get("THRESHOLD", "0.8"))
if not 0.0 < threshold < 1.0:
    raise ValueError(f"THRESHOLD must be between 0 and 1, got {threshold}")

weights = Path(os.environ.get("WEIGHTS_PATH", WEIGHTS_PATH))
model, device = load_classifier(weights, device=torch.device("cpu"))
app = create_app(model, get_tokenizer(), device, threshold)
_t_load = time.perf_counter()

# Cold starts on Lambda are dominated by these two steps; threads should match the vCPUs (2 at 3008 MB)
logging.getLogger(__name__).info(
    "init import_s=%.1f load_s=%.1f threads=%d", _t_import - _t0, _t_load - _t_import, torch.get_num_threads()
)

# lifespan="off": Mangum would otherwise run startup/shutdown on every invocation
handler = Mangum(app, lifespan="off")
