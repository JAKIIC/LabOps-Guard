FROM higress-registry.cn-hangzhou.cr.aliyuncs.com/agentteams/agentteams-copaw-worker@sha256:dcdd9103535cfac247267e0f69661820c801396d58e2c8e0c14eefd40b63b7bc

ARG TORCH_VERSION=2.5.1+cpu
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1

LABEL org.opencontainers.image.title="LabOps PyTorch CPU Runner" \
      org.opencontainers.image.version="0.1.0" \
      io.labops.runner.image="labops/pytorch-cpu-runner:0.1.0" \
      io.labops.runner.python="3.11.15" \
      io.labops.runner.torch="2.5.1+cpu" \
      io.labops.runner.network-runtime="none"

COPY requirements.lock /tmp/requirements.lock
RUN python -m pip install --no-cache-dir \
      --index-url https://download.pytorch.org/whl/cpu \
      --requirement /tmp/requirements.lock \
    && python -m pip check

RUN useradd --create-home --uid 10001 runner
WORKDIR /runner
COPY --chown=runner:runner runner.py /runner/runner.py

USER runner
ENTRYPOINT ["python", "-B", "/runner/runner.py"]
CMD ["--plan", "/input/experiment_plan.json", "--project", "/input/project", "--run", "/input/run", "--output", "/output"]
