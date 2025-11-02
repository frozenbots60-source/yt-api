# ==============================
# Base image: Python 3.11 slim
# ==============================
FROM python:3.11-slim

# Working directory
WORKDIR /app

# Non-interactive environment
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PORT=5000

# ===================================
# Install system dependencies + Deno
# ===================================
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg \
        build-essential \
        curl \
        ca-certificates \
        git \
        wget && \
    # Install Deno runtime
    curl -fsSL https://deno.land/install.sh | sh && \
    mv /root/.deno/bin/deno /usr/local/bin/deno && \
    # Clean up cache
    rm -rf /var/lib/apt/lists/*

# ============================
# Install Python dependencies
# ============================
COPY requirements.txt /app/
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# ============================
# Copy app source
# ============================
COPY . /app

# ============================
# Expose port (for Flask app)
# ============================
EXPOSE $PORT

# ============================
# Start command (Gunicorn)
# ============================
CMD ["sh", "-c", "gunicorn app:app --worker-class gthread --workers $(( $(nproc) * 2 + 1 )) --threads 4 --timeout 500 --bind 0.0.0.0:$PORT"]
