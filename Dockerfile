# ==============================================================================
#  ⚡ Telegram Web QR Session Engine — Render, Cloud & Production Dockerfile
# ==============================================================================
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DOCKER_CONTAINER=true \
    PORT=8000 \
    HOST=0.0.0.0

# Install minimal system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Set up non-root user (UID 1000) for security & Hugging Face / Render compatibility
RUN useradd -m -u 1000 user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

WORKDIR /home/user/app

# Install Python requirements
COPY --chown=user:user requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r requirements.txt

# Copy application files with full ownership
COPY --chown=user:user . .

# Ensure storage directories exist with write permissions (just like Telegram-Self)
RUN mkdir -p /home/user/app/sessions /home/user/app/logs \
    && chown -R user:user /home/user/app \
    && chmod -R 777 /home/user/app

USER user

EXPOSE 8000

CMD ["python", "web_qr/server.py"]
