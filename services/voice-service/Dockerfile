FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY services/voice-service/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --default-timeout=600 --retries 25 --progress-bar off --upgrade pip "setuptools<81" wheel \
 && pip install --no-cache-dir --default-timeout=600 --retries 25 --progress-bar off -r /app/requirements.txt

COPY services/voice-service /app
COPY shared /app/shared
# CRIT-03/CRIT-04/CRIT-12 shared contracts package (Pydantic v2 contracts,
# permissions, audio validation, predictive detector, HTTP client).
COPY bi_platform_shared /app/bi_platform_shared

EXPOSE 8004

CMD ["sh", "-c", "python manage.py migrate && python manage.py runserver 0.0.0.0:8004"]

