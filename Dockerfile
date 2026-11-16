FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    OAR_CONFIG=/app/config.toml OAR_DATA_DIR=/data

WORKDIR /app
COPY pyproject.toml ./
COPY oar ./oar
RUN pip install . && useradd --uid 1000 --create-home oar && mkdir /data && chown oar /data
COPY config.example.toml /app/config.toml

USER oar
VOLUME ["/data"]
ENTRYPOINT ["oar"]
CMD ["run"]
