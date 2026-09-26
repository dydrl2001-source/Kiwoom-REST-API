FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi uvicorn "psycopg[binary]" requests telethon
COPY market_radar/ /app/
ENV PYTHONUNBUFFERED=1

# Use the actual image dependency versions for the startup import smoke check.
# Importing the app registers routes/lifespan only; it does not contact a DB or AI.
RUN python -m pip check \
    && python -m py_compile radar_api.py radar_ui_v2.py radar_web_app.py web_research_engine.py \
    && python -c "import radar_web_app; assert radar_web_app.app is not None; print('Radar API import check passed')"
