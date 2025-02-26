FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y gcc && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .
COPY not_subscribed.jpg .
COPY admin_welcome.jpg .
COPY user_welcome.jpg .
ENV API_ID=""
ENV API_HASH=""
ENV BOT_TOKEN=""
ENV MONGO_URI=""
ENV ADMIN_IDS=""
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
CMD ["python", "main.py"]