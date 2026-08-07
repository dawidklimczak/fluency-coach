# Etap 1: model VAD pobierany raz, używany przez backend i przeglądarkę.
FROM python:3.12-slim AS models
RUN python -c "import urllib.request,pathlib; \
p=pathlib.Path('/models/silero_vad.onnx'); p.parent.mkdir(parents=True,exist_ok=True); \
p.write_bytes(urllib.request.urlopen('https://github.com/snakers4/silero-vad/raw/v4.0/files/silero_vad.onnx').read()); \
print('VAD:', p.stat().st_size, 'bajtow')"

# Etap 2: budowa frontendu. Użytkownik końcowy nie potrzebuje Node.
FROM node:20-slim AS web
WORKDIR /build
COPY apps/web/package*.json ./
RUN npm ci
COPY apps/web/ ./
COPY --from=models /models/silero_vad.onnx ./public/models/silero_vad.onnx
RUN npm run build

# Etap 3: aplikacja
FROM python:3.12-slim AS app

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/data \
    WEB_DIST=/app/web \
    SEED_SOURCE=/seed/seed_tasks.json

WORKDIR /app

COPY apps/api/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && python -m spacy download en_core_web_sm

COPY apps/api/app ./app
COPY --from=models /models/silero_vad.onnx ./app/assets/silero_vad.onnx
COPY --from=web /build/dist ./web
# bank zadań startowych; entrypoint kopiuje go do /data przy pierwszym starcie
COPY data/seed_tasks.json /seed/seed_tasks.json
COPY docker-entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# /data to wolumen: baza, nagrania i klucz sesji przeżywają podmianę kontenera
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health')"

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
