from ib_async import Crypto, Forex, Stock


ASSET_TYPE_STOCK = 'STOCK'
ASSET_TYPE_FOREX = 'FOREX'
ASSET_TYPE_CRYPTO = 'CRYPTO'

_ASSET_TYPE_ALIASES = {
    'STK': ASSET_TYPE_STOCK,
    'STOCK': ASSET_TYPE_STOCK,
    'CASH': ASSET_TYPE_FOREX,
    'FX': ASSET_TYPE_FOREX,
    'FOREX': ASSET_TYPE_FOREX,
    'CRYPTO': ASSET_TYPE_CRYPTO,
    'CRYPTOCURRENCY': ASSET_TYPE_CRYPTO,
}


def normalize_asset_type(asset_type: str | None) -> str:
    value = (asset_type or ASSET_TYPE_STOCK).strip().upper()
    return _ASSET_TYPE_ALIASES.get(value, ASSET_TYPE_STOCK)


def sanitize_symbol(symbol: str | None, asset_type: str | None = ASSET_TYPE_STOCK) -> str:
    sym = (symbol or '').strip().upper().replace(' ', '')
    if normalize_asset_type(asset_type) == ASSET_TYPE_FOREX:
        sym = sym.replace('/', '')
    return sym


def create_contract(
    symbol: str,
    asset_type: str | None = ASSET_TYPE_STOCK,
    currency: str | None = None,
):
    asset_type = normalize_asset_type(asset_type)
    symbol = sanitize_symbol(symbol, asset_type)
    currency = sanitize_symbol(currency, ASSET_TYPE_STOCK)

    if asset_type == ASSET_TYPE_FOREX:
        if len(symbol) == 3 and len(currency) == 3:
            symbol = f"{symbol}{currency}"

        if len(symbol) != 6:
            raise ValueError(
                f"Forex symbol must be exactly 6 characters (e.g. 'EURUSD'), "
                f"got {len(symbol)!r} chars: {symbol!r}"
            )
        return Forex(symbol)
    if asset_type == ASSET_TYPE_CRYPTO:
        return Crypto(symbol, currency='USD')
    return Stock(symbol, 'SMART', 'USD')


def get_contract_key(symbol: str, asset_type: str | None = ASSET_TYPE_STOCK) -> str:
    asset_type = normalize_asset_type(asset_type)
    return f"{asset_type}:{sanitize_symbol(symbol, asset_type)}"


def get_cache_symbol(symbol: str, asset_type: str | None = ASSET_TYPE_STOCK) -> str:
    asset_type = normalize_asset_type(asset_type)
    symbol = sanitize_symbol(symbol, asset_type)
    return symbol if asset_type == ASSET_TYPE_STOCK else f"{asset_type}__{symbol}"


def get_history_what_to_show(asset_type: str | None = ASSET_TYPE_STOCK) -> str:
    return 'MIDPOINT' if normalize_asset_type(asset_type) == ASSET_TYPE_FOREX else 'TRADES'


def use_regular_trading_hours(asset_type: str | None = ASSET_TYPE_STOCK) -> bool:
    return normalize_asset_type(asset_type) == ASSET_TYPE_STOCK


def asset_type_from_contract(contract) -> str:
    sec_type = str(getattr(contract, 'secType', '') or '').upper()
    if sec_type in ('CASH', 'FOREX'):
        return ASSET_TYPE_FOREX
    if sec_type == 'CRYPTO':
        return ASSET_TYPE_CRYPTO
    return ASSET_TYPE_STOCK


def get_display_symbol_from_contract(contract) -> str:
    asset_type = asset_type_from_contract(contract)
    symbol = sanitize_symbol(getattr(contract, 'symbol', ''), asset_type)

    if asset_type == ASSET_TYPE_FOREX:
        currency = sanitize_symbol(getattr(contract, 'currency', ''), ASSET_TYPE_STOCK)
        if len(symbol) == 3 and len(currency) == 3:
            return f"{symbol}{currency}"

    return symbol
