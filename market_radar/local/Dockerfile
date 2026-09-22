FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi uvicorn "psycopg[binary]" requests telethon
COPY market_radar/ /app/
ENV PYTHONUNBUFFERED=1
