# Isolated local embedding service

## Model and build provenance

The worker uses FastEmbed 0.7.4 and the CPU ONNX export of
[BAAI/bge-small-en-v1.5](https://huggingface.co/BAAI/bge-small-en-v1.5). The original model card
declares an MIT license. The exact export is
[`qdrant/bge-small-en-v1.5-onnx-q`](https://huggingface.co/qdrant/bge-small-en-v1.5-onnx-q)
at commit `aa8f8b060edb00e03bfdd08813a2949946c8ba55`. The pinned ONNX file is 66,465,124
bytes; the seven downloaded model files total about 67.4 MB. Python dependencies and image layers
add more disk use. The service needs a CPU supported by the locked ONNX Runtime wheel; local
verification used Windows x86-64, Python 3.12.9. The container targets Linux x86-64 and has not
yet been executed on this host. Two ONNX threads and at most two concurrent inference calls are
configured per worker process. This is a resource bound, not a measured throughput claim.

`scripts/prefetch_embedding_model.py` downloads only seven required files from the pinned revision
and writes a SHA-256 manifest. The Compose image runs this during its build. At startup, the service
verifies every file and the declared model/revision before loading the ONNX session. FastEmbed gets
`specific_model_path` and `local_files_only=True`; the running container also sets
`HF_HUB_OFFLINE=1`. It cannot silently fetch a newer model. A missing, modified, or incorrectly
labeled directory leaves `/readyz` at 503. `/healthz` remains 200 while the process is serving.
The model and tokenizer files are build artifacts, not committed source files.

## HTTP contract and ownership

`POST /embed` accepts `{"texts":["..."]}` on the internal worker service. A batch contains 1–16
nonblank strings, at most 2,048 characters each and 8,192 characters total. Unknown fields, empty
text, and oversized work return 422. A successful result carries the model name, exact export
revision, dimension 384, `normalized=true`, and one unit-length vector per input in order. Empty,
nonfinite, incorrectly sized, or non-unit vectors are rejected. The vector tolerance is `1e-4` for
unit norm; repeated real-model inference is tested within `1e-5` per component on one host.

FastAPI lifespan loads one model session in a worker thread. Request inference also runs in a
thread, so ONNX CPU work does not block the service event loop. A semaphore admits two concurrent
inferences by default; a saturated worker returns `embedding_busy` after 50 ms rather than forming
an unbounded queue. The request has a 15-second inference deadline. Cancellation or timeout does
not forcibly terminate an ONNX call: the call retains its permit until its thread finishes, and a
completion callback releases the permit. This prevents oversubscription after abandoned requests.
Shutdown waits up to 15 seconds for pending calls. A permanently stuck native call still requires
process termination; Python cannot safely kill one running thread.

`EmbeddingClient` is a typed, pooled HTTPX client intended for the gateway's future lifespan. It
configures connect/read/write/pool timeouts of 1/20/2/1 seconds and at most eight connections. It
rejects transport failures or incompatible model, revision, dimension, count, and normalization
metadata as `EmbeddingUnavailable`. Cancellation propagates. It is **not connected to the gateway**
in this slice. No prompt or vector is written to metrics or logs by this service. The worker has no
public authentication boundary: keep its network private; Compose publishes its port only on host
loopback for local testing. A future deployment must restrict service-to-service access.

## Local and Compose commands

From the repository worktree, with locked embedding dependencies installed:

```powershell
uv sync --locked --all-groups
uv run python scripts/prefetch_embedding_model.py 'C:\path\to\local\model'
$env:SWITCHBOARD_EMBEDDING_MODEL_DIR = 'C:\path\to\local\model'
uv run uvicorn switchboard.embedding_service:create_app --factory --host 127.0.0.1 --port 8003
```

In another shell, send synthetic text:

```powershell
Invoke-RestMethod http://127.0.0.1:8003/readyz
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8003/embed -ContentType application/json -Body '{"texts":["What is a queue?"]}'
```

For Compose, set the development tenant digest as documented in the README, then run:

```powershell
docker compose --profile embedding -f deploy/compose.yaml up --build --wait --wait-timeout 240
docker compose --profile embedding -f deploy/compose.yaml down --timeout 15
```

The embedding service uses a separate image and the `embedding` profile. Normal gateway Compose
behavior remains unchanged. The gateway does not depend on worker readiness yet. A cold image build
downloads the locked Python dependencies and pinned model; startup verifies the files and loads the
ONNX session. If readiness stays 503, check the worker startup log for a model load error and verify
the pinned files and manifest. The service deliberately does not expose prompt text in an error.
