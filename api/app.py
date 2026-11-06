import logging
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from components.config import LABEL_NAMES
from components.inference import phishing_probability
from components.preprocessing import normalize_url

# Hostnames are never logged, only counts and latency (see README "Privacy").
logger = logging.getLogger("phishing_api")

MAX_HOST_LEN = 253  # longest valid DNS name
MAX_BATCH = 32
MAX_BODY_BYTES = 16 * 1024  # a full batch of maximum-length hosts fits


class ClassifyRequest(BaseModel):
    host: str = Field(min_length=1, max_length=MAX_HOST_LEN)


class BatchRequest(BaseModel):
    hosts: list[str] = Field(min_length=1, max_length=MAX_BATCH)


class Classification(BaseModel):
    host: str
    p_phishing: float
    label: str
    threshold: float


class BatchItem(BaseModel):
    host: str
    p_phishing: float | None = None
    label: str | None = None
    error: str | None = None


class BatchResponse(BaseModel):
    threshold: float
    results: list[BatchItem]


def create_app(model, tokenizer, device, threshold=0.8):
    """The model is passed in so tests can use a randomly initialized one."""
    app = FastAPI(title="Phishing hostname classifier", version="1.0.0")

    def score(raw):
        # Only the hostname reaches the model; returning it lets clients cache per host.
        host = normalize_url(raw)
        p = phishing_probability(host, model, tokenizer, device)
        label = LABEL_NAMES[0] if p >= threshold else LABEL_NAMES[1]
        return host, p, label

    # Checks the declared length only, so a chunked body gets past it; Pydantic's length
    # limits still apply, and on Lambda the HTTP API always delivers a complete body.
    @app.middleware("http")
    async def limit_body_size(request: Request, call_next):
        length = request.headers.get("content-length")
        if length is None:
            return await call_next(request)
        # isascii: isdigit() alone accepts "²", which int() then rejects (500)
        if not (length.isascii() and length.isdigit()):
            return JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)
        if int(length) > MAX_BODY_BYTES:
            return JSONResponse({"detail": "Request body too large"}, status_code=413)
        return await call_next(request)

    @app.get("/v1/health")
    def health():
        return {"status": "ok", "threshold": threshold}

    @app.post("/v1/classify", response_model=Classification)
    def classify(req: ClassifyRequest):
        start = time.perf_counter()
        try:
            host, p, label = score(req.host)
        except ValueError:
            raise HTTPException(status_code=422, detail="Input has no hostname")
        logger.info("classify n=1 ms=%.0f", (time.perf_counter() - start) * 1000)
        return Classification(host=host, p_phishing=p, label=label, threshold=threshold)

    @app.post("/v1/classify/batch", response_model=BatchResponse)
    def classify_batch(req: BatchRequest):
        start = time.perf_counter()
        results = []
        for raw in req.hosts:
            # One bad link on a page shouldn't fail the others
            if not raw or len(raw) > MAX_HOST_LEN:
                results.append(BatchItem(host=raw[:MAX_HOST_LEN], error="Invalid host"))
                continue
            try:
                host, p, label = score(raw)
            except ValueError:
                results.append(BatchItem(host=raw, error="Input has no hostname"))
                continue
            results.append(BatchItem(host=host, p_phishing=p, label=label))
        logger.info("classify n=%d ms=%.0f", len(req.hosts), (time.perf_counter() - start) * 1000)
        return BatchResponse(threshold=threshold, results=results)

    return app
