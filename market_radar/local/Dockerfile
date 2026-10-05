FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi uvicorn "psycopg[binary]" requests telethon websockets httpx
COPY market_radar/ /app/
ENV PYTHONUNBUFFERED=1

# Use the actual image dependency versions for the startup import smoke check.
# Importing the app registers routes/lifespan only; it does not contact a DB or AI.
RUN python -m pip check \
    && python -m py_compile radar_api.py radar_ui_v2.py radar_web_app.py web_research_engine.py \
        flow_core.py flow_store.py flow_routes.py flow_collector.py kiwoom_feed.py flow_chart_feed.py \
        flow_news_feed.py flow_research_worker.py market_theme_feed.py candidate_tracker.py mobile_ui.py \
        evidence_identity.py news_feed.py paper_trade_engine.py paper_feedback_engine.py \
        market_os_rule_engine.py market_os_learning.py market_os_store.py market_os_routes.py \
        market_os_live_validation.py market_os_shadow.py market_os_dossier.py market_os_ruleset.py market_os_release.py market_os_full_release.py market_os_control.py market_os_execution.py market_os_budget.py market_os_risk.py market_os_packet.py market_os_naver.py market_os_daily.py market_os_readonly.py market_os_readonly_app.py kiwoom_realtime_0b.py \
    && DATABASE_URL="" DASHBOARD_TOKEN="test" python -m unittest discover -s tests -p 'test_sector_board.py' -v \
    && DATABASE_URL="" DASHBOARD_TOKEN="test" python -m unittest discover -s tests -p 'test_mobile_ui.py' -v \
    && DATABASE_URL="" DASHBOARD_TOKEN="test" python -m unittest discover -s tests -p 'test_paper_trade.py' -v \
    && DATABASE_URL="" DASHBOARD_TOKEN="test" python -m unittest discover -s tests -p 'test_paper_feedback.py' -v \
    && python -c "import radar_web_app; assert radar_web_app.app is not None; print('Radar API import check passed')"
