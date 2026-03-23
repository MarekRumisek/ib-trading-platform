"""AI Blueprint - AI Analysis Endpoints

Provides AI-assisted trading analysis:
- Analyze market data
- Generate trade suggestions
- Get AI recommendations
- Historical AI analysis
- AI evaluation of potential entries (/api/ai/evaluate)
- AI position check (/api/ai/check_position)
"""

from flask import Blueprint, jsonify, request
from modules.config_store import config_store
import requests as http_client
import json

ai_bp = Blueprint('ai', __name__, url_prefix='/api')


@ai_bp.route('/ai/analyze', methods=['POST'])
def analyze():
    """Analyze market data and generate insights."""
    data = request.get_json() or {}
    symbol = data.get('symbol')
    candles = data.get('candles', [])
    
    return jsonify({
        'symbol': symbol,
        'candles_count': len(candles),
        'message': 'AI analyze endpoint - implement with openrouter_api'
    })


@ai_bp.route('/ai/suggest', methods=['GET'])
def suggest():
    """Get AI trade suggestion for a symbol."""
    symbol = request.args.get('symbol')
    
    return jsonify({
        'symbol': symbol,
        'suggestion': None,
        'message': 'AI suggest endpoint - implement with openrouter_api'
    })


@ai_bp.route('/ai/history', methods=['GET'])
def history():
    """Get historical AI analysis results."""
    limit = request.args.get('limit', 50, type=int)
    
    return jsonify({
        'analyses': [],
        'limit': limit,
        'message': 'AI history endpoint - implement with openrouter_api'
    })


@ai_bp.route('/ai/evaluate', methods=['POST'])
def ai_evaluate():
    """AI analysis of potential entry."""
    body = request.get_json(silent=True) or {}
    api_key = config_store.get('openrouter_api_key', '')
    model = config_store.get('llm_model', '')

    if not api_key or not model:
        return jsonify({'ok': False, 'error': 'Missing OpenRouter API key or model in Settings'}), 400

    graphs = body.get('graphs', [])
    indicators = body.get('indicators', {})
    account = body.get('account', {})
    strategy = config_store.get('strategy_text', '')
    mm_rules = config_store.get('mm_rules_text', '')

    system_prompt = (
        "You are a professional trading analyst. Analyze the provided market data "
        "and return a JSON object with these exact keys: "
        "recommendation (BUY/SELL/HOLD), order_type (MARKET/LIMIT), "
        "entry_price (number), sl (number), tp (number), quantity (integer), "
        "rr_ratio (string like '1:2.4'), reason (string), annotations (array of objects)."
    )

    user_prompt = f"""Strategy: {strategy}
Money Management: {mm_rules}
Account: Balance=${account.get('net_liquidation', 0)}, Buying Power=${account.get('buying_power', 0)}

Market Data:
"""
    for g in graphs:
        user_prompt += f"\n--- {g.get('symbol')} {g.get('tf')} ({g.get('asset_type')}) ---\n"
        bars = g.get('bars', [])
        for bar in bars[-50:]:
            user_prompt += f"T={bar.get('time')} O={bar.get('open')} H={bar.get('high')} L={bar.get('low')} C={bar.get('close')} V={bar.get('volume')}\n"

    if indicators:
        user_prompt += f"\nIndicators: {indicators}\n"

    user_prompt += "\nProvide your analysis as a valid JSON object."

    try:
        resp = http_client.post(
            'https://openrouter.ai/api/v1/chat/completions',
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
                'HTTP-Referer': 'http://localhost:8050',
                'X-Title': 'IB Trading Platform',
            },
            json={
                'model': model,
                'messages': [
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': user_prompt},
                ],
                'response_format': {'type': 'json_object'},
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data.get('choices', [{}])[0].get('message', {}).get('content', '{}')

        parsed = json.loads(content)
        return jsonify(parsed)

    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@ai_bp.route('/ai/check_position', methods=['POST'])
def ai_check_position():
    """AI review of an open position."""
    body = request.get_json(silent=True) or {}
    api_key = config_store.get('openrouter_api_key', '')
    model = config_store.get('llm_model', '')

    if not api_key or not model:
        return jsonify({'ok': False, 'error': 'Missing OpenRouter API key or model in Settings'}), 400

    graphs = body.get('graphs', [])
    indicators = body.get('indicators', {})
    trade = body.get('trade', {})
    strategy = config_store.get('strategy_text', '')

    system_prompt = (
        "You are a professional trading analyst reviewing an open position. "
        "Return a JSON object with these exact keys: "
        "action (HOLD/MOVE_SL/MOVE_TP/CLOSE), new_sl (number or null), "
        "new_tp (number or null), reason (string)."
    )

    user_prompt = f"""Strategy: {strategy}
Current Position: Entry={trade.get('entry_price')}, SL={trade.get('sl')}, TP={trade.get('tp')}, P&L={trade.get('pnl')}

Market Data:
"""
    for g in graphs:
        user_prompt += f"\n--- {g.get('symbol')} {g.get('tf')} ({g.get('asset_type')}) ---\n"
        bars = g.get('bars', [])
        for bar in bars[-50:]:
            user_prompt += f"T={bar.get('time')} O={bar.get('open')} H={bar.get('high')} L={bar.get('low')} C={bar.get('close')} V={bar.get('volume')}\n"

    if indicators:
        user_prompt += f"\nIndicators: {indicators}\n"

    user_prompt += "\nProvide your analysis as a valid JSON object."

    try:
        resp = http_client.post(
            'https://openrouter.ai/api/v1/chat/completions',
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
                'HTTP-Referer': 'http://localhost:8050',
                'X-Title': 'IB Trading Platform',
            },
            json={
                'model': model,
                'messages': [
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': user_prompt},
                ],
                'response_format': {'type': 'json_object'},
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data.get('choices', [{}])[0].get('message', {}).get('content', '{}')

        parsed = json.loads(content)
        return jsonify(parsed)

    except http_client.exceptions.Timeout:
        return jsonify({'ok': False, 'error': 'openrouter_timeout'}), 504
    except http_client.exceptions.RequestException as e:
        return jsonify({'ok': False, 'error': str(e)}), 502
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@ai_bp.route('/models', methods=['GET'])
def list_models():
    """List available free models from OpenRouter."""
    api_key = config_store.get('openrouter_api_key', '')

    if not api_key:
        return jsonify({'ok': False, 'error': 'api_key_missing'}), 400

    try:
        resp = http_client.get(
            'https://openrouter.ai/api/v1/models',
            headers={
                'Authorization': f'Bearer {api_key}',
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        # Filter free models (pricing.prompt == "0")
        free_models = []
        for model in data.get('data', []):
            pricing = model.get('pricing', {})
            prompt_price = pricing.get('prompt', '0')
            if prompt_price == '0' or prompt_price == 0:
                free_models.append({
                    'id': model.get('id', ''),
                    'name': model.get('name', model.get('id', '')),
                    'context_length': model.get('context_length', 0),
                })

        return jsonify({'ok': True, 'models': free_models})

    except Exception:
        return jsonify({'ok': False, 'error': 'openrouter_error'}), 500
