FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml requirements.lock ./
RUN pip install --no-cache-dir -c requirements.lock .
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "18080", "--proxy-headers", "--forwarded-allow-ips=*", "--log-config", "/app/logging.ini"]
