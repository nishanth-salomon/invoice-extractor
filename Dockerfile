FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt .
# reportlab and pytest are only needed for the sample generator and tests; the service needs the rest
RUN pip install -r requirements.txt
COPY src ./src
ENV PYTHONPATH=/app/src INVOICEFLOW_DATA_DIR=/data
RUN useradd -m app && mkdir -p /data && chown app /data
USER app
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health')" || exit 1
CMD ["uvicorn", "invoiceflow.api:app", "--host", "0.0.0.0", "--port", "8000"]
