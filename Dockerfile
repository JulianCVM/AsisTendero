FROM python:3.12-slim

# El contenedor es para el harness del reto, el evaluador y el modo desatendido: no publica el visor ni el panel,
# que no tienen usuarios (docs/DESPLIEGUE.md). La llave entra al arrancar (--env-file), nunca en la imagen.
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
COPY evaluation/cases.json evaluation/cases_carluz.json ./evaluation/
RUN pip install --no-cache-dir . \
    && useradd --create-home --uid 10001 asistendero \
    && mkdir -p /app/.local \
    && chown asistendero /app/.local \
    && rm -rf build

# Bases, sesiones y bitácora viven en el volumen: el catálogo ficticio se crea en el primer uso y el inventario real
# solo entra si se monta su base. Nada de eso queda en la imagen.
VOLUME ["/app/.local"]
USER asistendero

ENTRYPOINT ["asistendero-harness"]
