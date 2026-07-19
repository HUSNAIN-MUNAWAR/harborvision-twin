FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/apps/api
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr libgl1 libglib2.0-0 curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd --create-home --uid 10001 harborvision && chown -R harborvision:harborvision /app
USER harborvision
EXPOSE 8000
HEALTHCHECK --interval=20s --timeout=5s --retries=5 CMD curl -fsS http://localhost:8000/api/v1/health/live || exit 1
CMD ["uvicorn", "harborvision.main:app", "--host", "0.0.0.0", "--port", "8000"]
