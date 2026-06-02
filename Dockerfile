FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV LOG_LEVEL=INFO

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project code
COPY . .

EXPOSE 8000

ENTRYPOINT ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
