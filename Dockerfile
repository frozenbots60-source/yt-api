# Use official Python slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Avoid prompts
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PORT=5000

# Install ffmpeg + system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg \
        build-essential \
        curl \
        ca-certificates \
        git \
        wget && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt /app/
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# Copy app source
COPY . /app

# Expose port for Heroku
EXPOSE $PORT

# Gunicorn full power command
CMD ["sh", "-c", "gunicorn app:app --worker-class gthread --workers $(( $(nproc) * 2 + 1 )) --threads 4 --timeout 500 --bind 0.0.0.0:$PORT"]
