#!/bin/bash
# Read-only preflight using the RUNNING worker's environment.
# No Responses calls, no web search, no database writes, no quota changes.
set -eu
cd "$(dirname "$0")"

echo '=== OpenAI authentication check: running web-research-worker ==='
echo 'This checks GET /v1/models only. It does not create a research report.'
echo 'No API key, model list, provider message, or billing details will be printed.'
echo 'If the worker is stopped, do not restart it just for this check; report that state first.'

docker compose exec -T web-research-worker python - <<'PY'
import json
import os
import sys
import requests


def check():
    key = os.getenv('OPENAI_API_KEY', '').strip()
    model = os.getenv('WEB_RESEARCH_MODEL', '').strip()
    print('KEY_PRESENT:', bool(key))
    print('MODEL_CONFIGURED:', bool(model))
    if not key:
        print('RESULT: KEY_MISSING_IN_WORKER')
        return 1
    if (not key.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in key)
            or '...' in key or '"' in key or "'" in key):
        print('RESULT: KEY_FORMAT_PROBLEM')
        print('NEXT: Check the full secret value locally; never paste it into chat.')
        return 1
    try:
        response = requests.get(
            'https://api.openai.com/v1/models',
            headers={'Authorization': 'Bearer ' + key, 'Accept': 'application/json'},
            timeout=(5, 20), allow_redirects=False,
        )
    except requests.Timeout:
        print('RESULT: AUTH_CHECK_TIMEOUT')
        return 1
    except requests.RequestException:
        print('RESULT: AUTH_CHECK_NETWORK_ERROR')
        return 1

    with response:
        print('HTTP_STATUS:', int(response.status_code))
        try:
            data = response.json()
        except ValueError:
            data = {}
        data = data if isinstance(data, dict) else {}
        err = data.get('error')
        err = err if isinstance(err, dict) else {}
        # Only map known values to fixed labels; error.message may echo a secret.
        code, error_type = err.get('code'), err.get('type')
        if response.status_code == 401:
            if code == 'ip_not_authorized' or error_type == 'ip_not_authorized':
                result = 'IP_NOT_AUTHORIZED'
            elif code == 'invalid_api_key' or error_type == 'invalid_api_key':
                result = 'API_KEY_REJECTED'
            else:
                result = 'AUTH_REJECTED_CHECK_KEY_OR_ORG'
            print('RESULT:', result)
            return 1
        if response.status_code == 403:
            print('RESULT: MODELS_ACCESS_DENIED')
            print('NEXT: Check model-list permission and access policy; do not assume the key is invalid.')
            return 1
        if response.status_code == 429:
            print('RESULT: PROVIDER_LIMIT_REACHED')
            return 1
        if response.status_code != 200:
            print('RESULT: AUTH_CHECK_HTTP_ERROR')
            return 1
        rows = data.get('data')
        if data.get('object') != 'list' or not isinstance(rows, list):
            print('RESULT: UNEXPECTED_MODELS_RESPONSE')
            return 1
        visible = bool(model) and any(isinstance(x, dict) and x.get('id') == model for x in rows)
        print('RESULT: MODELS_AUTH_OK')
        print('CONFIGURED_MODEL_VISIBLE:', visible)
        print('NOTE: Responses/web-search permissions, billing, and report success are NOT verified.')
        print('NOTE: Existing research attempts and limits remain unchanged.')
        return 0


try:
    sys.exit(check())
except Exception:
    # Do not print a traceback or exception message that could contain a key/URL.
    print('RESULT: LOCAL_AUTH_CHECK_ERROR')
    sys.exit(1)
PY
