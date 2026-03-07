# Use official Python slim image for a smaller footprint
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Environment variables to optimize Python performance and Deno pathing
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=5000 \
    PATH="/root/.deno/bin:$PATH"

# Install system dependencies, ffmpeg, and Deno prerequisites
# We combine these into one RUN layer to reduce image size
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg \
        build-essential \
        curl \
        ca-certificates \
        git \
        wget \
        unzip && \
    rm -rf /var/lib/apt/lists/*

# Install Deno runtime and move it to a global bin for easier access
RUN curl -fsSL https://deno.land/install.sh | sh && \
    mv /root/.deno/bin/deno /usr/local/bin/deno

# Copy requirements and install Python dependencies (e.g., yt-dlp, Flask/FastAPI)
COPY requirements.txt /app/
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application source code
COPY . /app

# Expose port for deployment (e.g., Heroku, Render)
EXPOSE $PORT

# Start the application
CMD ["sh", "-c", "python app.py"]
