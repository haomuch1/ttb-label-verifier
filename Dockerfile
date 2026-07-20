FROM python:3.12-slim

# poppler-utils: pdf2image page rendering; tesseract-ocr: locating the
# "AFFIX COMPLETE SET OF LABELS BELOW" anchor for two-region extraction
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/
COPY static/ static/

EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
