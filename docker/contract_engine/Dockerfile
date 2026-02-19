FROM python:3.12-slim

WORKDIR /app

COPY docker/contract_engine/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/shared/ src/shared/
COPY src/contract_engine/ src/contract_engine/
COPY src/__init__.py src/__init__.py

RUN mkdir -p /data && \
    adduser --disabled-password --no-create-home appuser && \
    chown -R appuser:appuser /app /data

USER appuser

EXPOSE 8000

CMD ["uvicorn", "src.contract_engine.main:app", "--host", "0.0.0.0", "--port", "8000"]
