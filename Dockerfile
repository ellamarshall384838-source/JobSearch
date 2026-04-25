FROM python:3.12-slim-bookworm

WORKDIR /app

# System deps for CJK fonts + Playwright Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-noto-cjk fonts-liberation \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libdbus-1-3 libxkbcommon0 \
    libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libasound2 libx11-xcb1 libxss1 \
    libpangocairo-1.0-0 curl \
    && rm -rf /var/lib/apt/lists/*

# Python deps + Playwright browser
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install chromium

# App source (gitignore keeps secrets/outputs out)
COPY . .

# Cloud mode: each visitor gets session-isolated storage
ENV DEPLOY_MODE=cloud
ENV PYTHONUNBUFFERED=1

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s \
    CMD curl --fail http://localhost:8501/_stcore/health || exit 1

CMD ["streamlit", "run", "app.py", \
     "--server.port=8501", "--server.address=0.0.0.0", \
     "--server.headless=true"]
