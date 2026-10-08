FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt
COPY . .
RUN useradd --system --uid 10001 --home /app appuser && mkdir -p /app/uploads && chown -R appuser:appuser /app
USER appuser
ENV PORT=8000
EXPOSE ${PORT}
HEALTHCHECK --interval=30s --timeout=6s --start-period=20s --retries=3 CMD ["python", "-c", "import os,urllib.request;urllib.request.urlopen('http://localhost:'+os.environ.get('PORT','8000')+'/health',timeout=4)"]
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers
