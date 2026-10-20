FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY contracts/build ./contracts/build

RUN useradd --create-home appuser
USER appuser

EXPOSE 8000
# Render (and most hosts) pass the port in $PORT. --proxy-headers makes rate limiting see the real visitor IP.
CMD ["sh", "-c", "uvicorn app.main:app_factory --factory --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
