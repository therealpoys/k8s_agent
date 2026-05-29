FROM python:3.12-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


FROM python:3.12-slim

WORKDIR /app

COPY --from=builder /install /usr/local
COPY agent.py .
COPY src/ src/

# config.yaml wird per ConfigMap unter /app/config.yaml gemountet
ENV CONFIG_PATH=/app/config.yaml
ENV PYTHONUNBUFFERED=1

RUN useradd --no-create-home --uid 1000 agent
USER agent

ENTRYPOINT ["python", "agent.py"]
