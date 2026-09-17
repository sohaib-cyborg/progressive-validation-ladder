# Sandbox image for executing untrusted tool code (CLAUDE.md §7, DECISIONS.md).
# Build:  docker build -t toolvalidator-sandbox:py3.12 toolvalidator/sandbox
# Base pinned by digest (python:3.12-slim, pulled 2026-09-17) for reproducibility.
FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea

# numpy: 1.6% of RunBugRun Python entries import it; 1.26.4 is the oldest release
# supporting Python 3.12 (closest to the CodeNet submission era).
# mutmut + pytest: mutation arm A runs inside the sandbox, never on the host.
RUN pip install --no-cache-dir numpy==1.26.4 mutmut==3.8.0 pytest==9.1.1

USER 65534:65534
