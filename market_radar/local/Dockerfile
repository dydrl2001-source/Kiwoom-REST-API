FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi uvicorn "psycopg[binary]" requests telethon
COPY market_radar/ /app/
ENV PYTHONUNBUFFERED=1

# Use the actual image dependency versions for the startup import smoke check.
# Importing the app registers routes/lifespan only; it does not contact a DB or AI.
RUN python -m pip check \
    && python -m py_compile radar_api.py radar_ui_v2.py radar_web_app.py web_research_engine.py \
        flow_core.py flow_store.py flow_routes.py flow_collector.py flow_chart_feed.py \
        flow_news_feed.py flow_research_worker.py market_theme_feed.py candidate_tracker.py mobile_ui.py \
        evidence_identity.py news_feed.py paper_trade_engine.py paper_feedback_engine.py ai_brokerage_worker.py orderbook_collector.py shadow_execution_engine.py capital_allocation_worker.py \
        ai_brokerage/models.py ai_brokerage/strategy_registry.py ai_brokerage/desks.py \
        ai_brokerage/decision_engine.py ai_brokerage/adapter.py ai_brokerage/analytics.py \
        ai_brokerage/execution_model.py ai_brokerage/capacity.py ai_brokerage/allocation.py \
    && DATABASE_URL="" DASHBOARD_TOKEN="test" python -m unittest discover -s tests -p 'test_sector_board.py' -v \
    && DATABASE_URL="" DASHBOARD_TOKEN="test" python -m unittest discover -s tests -p 'test_mobile_ui.py' -v \
    && DATABASE_URL="" DASHBOARD_TOKEN="test" python -m unittest discover -s tests -p 'test_paper_trade.py' -v \
    && DATABASE_URL="" DASHBOARD_TOKEN="test" python -m unittest discover -s tests -p 'test_paper_feedback.py' -v \
    && DATABASE_URL="" DASHBOARD_TOKEN="test" python -m unittest discover -s tests -p 'test_ai_brokerage.py' -v \
    && DATABASE_URL="" DASHBOARD_TOKEN="test" python -m unittest discover -s tests -p 'test_shadow_execution.py' -v \
    && DATABASE_URL="" DASHBOARD_TOKEN="test" python -m unittest discover -s tests -p 'test_orderbook_collector.py' -v \
    && DATABASE_URL="" DASHBOARD_TOKEN="test" python -m unittest discover -s tests -p 'test_capacity.py' -v \
    && DATABASE_URL="" DASHBOARD_TOKEN="test" python -m unittest discover -s tests -p 'test_allocation.py' -v \
    && python -c "import radar_web_app; assert radar_web_app.app is not None; print('Radar API import check passed')"
