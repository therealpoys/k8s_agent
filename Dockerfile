FROM python:3.13-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


FROM python:3.13-slim

WORKDIR /app

COPY --from=builder /install /usr/local
COPY agent.py .
COPY src/ src/

ENV PYTHONUNBUFFERED=1

RUN useradd --no-create-home --uid 1000 agent
USER agent

ENTRYPOINT ["python", "agent.py"]
