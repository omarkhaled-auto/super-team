FROM python:3.12-slim

WORKDIR /app

COPY docker/codebase_intelligence/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download ChromaDB embedding model at build time (as root)
RUN python -c "from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import ONNXMiniLM_L6_V2; ONNXMiniLM_L6_V2().validate()" || \
    python -c "from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2; ONNXMiniLM_L6_V2()" || true

COPY src/shared/ src/shared/
COPY src/codebase_intelligence/ src/codebase_intelligence/
COPY src/__init__.py src/__init__.py

RUN mkdir -p /data /home/appuser/.cache && \
    adduser --disabled-password --no-create-home appuser && \
    chown -R appuser:appuser /app /data /home/appuser

USER appuser

EXPOSE 8000

CMD ["uvicorn", "src.codebase_intelligence.main:app", "--host", "0.0.0.0", "--port", "8000"]
