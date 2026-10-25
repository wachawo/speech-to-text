# GPU image based on CUDA + cuDNN. The defaults build the main image: CUDA 13.0 with torch
# 2.10.0+cu130, for current cards and the GB10. docker-compose-p40.yml overrides the five CUDA
# build args for Pascal cards such as the Tesla P40 (sm_61): CUDA 13 and the cu128/cu130 torch
# builds dropped sm_50-sm_61, and the cu126 build still carries sm_60 kernels, which run on sm_61.
# The five go together: the base image, its cuBLAS package, the torch build for that CUDA, and
# the kernels the build must carry.
ARG CUDA_IMAGE=nvidia/cuda:13.0.3-cudnn-runtime-ubuntu24.04
FROM ${CUDA_IMAGE}

# ffmpeg is required by pydub; libsndfile1 is required by soundfile.
# The cuBLAS package provides the cuBLAS / cuBLASLt runtime that torch calls into
# (cublasLtMatmul*). The `-runtime` base image does not include it by default -
# without it the first matmul on CUDA fails with `CUBLAS_STATUS_NOT_INITIALIZED`.
# It must match the CUDA of the base image: libcublas-13-0 for 13.0, libcublas-12-6 for 12.6.
ARG CUBLAS_PACKAGE=libcublas-13-0
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        python3-venv \
        ffmpeg \
        build-essential \
        libsndfile1 \
        ${CUBLAS_PACKAGE} \
    && rm -rf /var/lib/apt/lists/*

# uv: fast Python package installer (https://github.com/astral-sh/uv).
# Pinned, not :latest - when the tag moved, every layer after this one missed the cache and
# the build re-downloaded torch and the CUDA wheels (20 minutes on the deployment host).
COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /uvx /usr/local/bin/

WORKDIR /opt

ENV PATH="/opt/venv/bin:${PATH}"
ENV UV_LINK_MODE=copy

RUN uv venv /opt/venv --python python3

# The CUDA wheels run to about 2.5 GB, and on a slow link uv's default 30 s read timeout has
# failed a build here partway through them.
ENV UV_HTTP_TIMEOUT=300

# PyTorch in a layer of its own, ahead of requirements.txt. When both were one RUN after the
# COPY, editing a comment in requirements.txt threw away the cached CUDA wheels and sent the
# next build back to the network for all of them.
ARG TORCH_VERSION=2.10.0
ARG TORCH_CUDA=cu130
RUN uv pip install --no-cache \
        --extra-index-url https://download.pytorch.org/whl/${TORCH_CUDA} \
        torch==${TORCH_VERSION}+${TORCH_CUDA} torchaudio==${TORCH_VERSION}+${TORCH_CUDA}

COPY requirements.txt constraints.txt /opt/
RUN uv pip install --no-cache -r requirements.txt -c constraints.txt

# Parakeet is opt-in at build time too: `--build-arg PARAKEET=true`. It and the diarizer share
# one transformers release, which carries both architectures; the assertions below check it.
ARG PARAKEET=false
COPY requirements-parakeet.txt /opt/requirements-parakeet.txt
RUN if [ "$PARAKEET" = "true" ]; then uv pip install --no-cache -r requirements-parakeet.txt -c constraints.txt; fi

# Speaker diarization is opt-in at build time: `--build-arg DIARIZE=true`. Off, the image is
# what it was before diarization existed.
ARG DIARIZE=false
COPY requirements-diarize.txt /opt/requirements-diarize.txt
RUN if [ "$DIARIZE" = "true" ]; then uv pip install --no-cache -r requirements-diarize.txt -c constraints.txt; fi

# The torch wheel above is a CUDA build chosen on purpose, and the resolutions that follow it
# are unconstrained: anything depending on torch can replace it, and the failure surfaces much
# later as cuBLAS and cuDNN errors that read like a driver problem. Fail the build instead.
RUN python3 -c "import torch; v = torch.__version__; assert '+${TORCH_CUDA}' in v, f'torch was replaced by {v}'"

# The build must carry kernels for the target card; any one of TORCH_ARCHES will do. NVIDIA GB10
# (DGX Spark) is sm_121 and the cu130 build carries no sm_121 kernels: it runs on the sm_120 ones
# and the compute_120 PTX. A Tesla P40 is sm_61 and runs on the sm_60 kernels of the cu126 build.
# Checked from the compiled flags, because get_arch_list() reads empty without a GPU at build
# time. A torch that drops them all would build fine and fail on the first CUDA call.
ARG TORCH_ARCHES="sm_121 sm_120 compute_120"
RUN python3 -c "import torch; flags = torch._C._cuda_getArchFlags().split(); wanted = '${TORCH_ARCHES}'.split(); \
assert any(arch in flags for arch in wanted), f'no kernels for {wanted}: {flags}'"
RUN if [ "$DIARIZE" = "true" ]; then \
        python3 -c "from transformers.models.auto.configuration_auto import CONFIG_MAPPING_NAMES; \
assert 'nemotron3_diarization' in CONFIG_MAPPING_NAMES, 'this transformers build does not carry the diarization model'"; \
    fi
RUN if [ "$PARAKEET" = "true" ]; then \
        python3 -c "from transformers import AutoModelForTDT; import transformers; \
assert 'parakeet_tdt' in transformers.models.auto.configuration_auto.CONFIG_MAPPING_NAMES, \
'this transformers build does not carry the parakeet model'"; \
    fi

# The stt user is created with --no-create-home and only the bind-mounted dirs are chowned,
# so anything HuggingFace writes outside them fails. cache_dir covers the snapshot; HF_HOME
# covers the rest, including the Xet chunk cache.
ENV HF_HOME=/opt/models/hf

COPY stt_server.py stt_client.py gu.py /opt/
COPY libs /opt/libs
RUN mkdir -p /opt/models /opt/logs /opt/recs

# The server may run as a host uid (STT_UID) that owns nothing in the image and whose $HOME is
# /root. numba, which librosa uses, caches its compiled functions next to the package or under
# $HOME and refuses to import without somewhere to write ("cannot cache function ... no locator
# available"), which took the diarizer down; everything else that caches goes under XDG too.
ENV NUMBA_CACHE_DIR=/tmp/numba XDG_CACHE_HOME=/tmp/cache

RUN useradd --no-create-home --shell /bin/false stt
RUN chown -R stt:stt /opt

# Start as root: the entrypoint chowns the bind-mounted dirs (the build-time
# chown above cannot reach host-owned mounts) and drops privileges to stt.
COPY entrypoint.sh /opt/entrypoint.sh
RUN chmod +x /opt/entrypoint.sh
ENTRYPOINT ["/opt/entrypoint.sh"]

EXPOSE 5051
CMD ["python3", "stt_server.py"]
