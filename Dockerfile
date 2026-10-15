FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
COPY evaluation ./evaluation
RUN pip install --no-cache-dir .
RUN python -m asistendero.seed

ENTRYPOINT ["asistendero"]
