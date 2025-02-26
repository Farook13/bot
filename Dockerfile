# Use an official Python runtime as the base image
FROM python:3.11-slim

# Set working directory inside the container
WORKDIR /app

# Install system dependencies (for pymongo and other libraries)
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the bot code
COPY main.py .

# Set environment variables (optional, can be overridden in docker run or compose)
# These will be overridden by .env or docker-compose if provided
ENV API_ID=""
ENV API_HASH=""
ENV BOT_TOKEN=""
ENV MONGO_URI=""

# Optimize Python runtime
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Run the bot
CMD ["python", "main.py"]
