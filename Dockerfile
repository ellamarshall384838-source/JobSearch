FROM python:3.11-slim

WORKDIR /app

# System deps (weasyprint needs these; skip if you don't need PDF generation)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 libpangoft2-1.0-0 libgdk-pixbuf2.0-0 libffi-dev \
    libcairo2 fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
# Install without playwright browsers (cloud mode disables LinkedIn automation)
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir playwright || true

# App source
COPY . .

# Cloud mode: session-only storage, no LinkedIn automation
ENV DEPLOY_MODE=cloud
ENV PYTHONUNBUFFERED=1

EXPOSE 8501

HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health || exit 1

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
