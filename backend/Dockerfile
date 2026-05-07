FROM python:3.11-slim

WORKDIR /app

# Install CPU-only torch first so sentence-transformers doesn't pull CUDA drivers
RUN pip install --no-cache-dir torch --extra-index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p vault chroma_db data

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
