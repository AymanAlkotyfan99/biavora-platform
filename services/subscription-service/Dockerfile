FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY services/subscription-service/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --default-timeout=600 --retries 25 --progress-bar off --upgrade pip "setuptools<81" wheel && pip install --no-cache-dir --default-timeout=600 --retries 25 --progress-bar off -r /app/requirements.txt

COPY services/subscription-service /app
COPY bi_platform_shared /app/bi_platform_shared

EXPOSE 8008

CMD ["sh", "-c", "python manage.py migrate && python manage.py runserver 0.0.0.0:8008"]

