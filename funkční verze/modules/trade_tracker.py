"""TradeTracker – ukládání obchodů do JSON souboru.

Struktura záznamu:
  id           – unikátní string "SYMBOL_timestamp"
  symbol       – ticker
  side         – "BUY" | "SELL"
  qty          – počet kusů (float)
  order_type   – "MARKET" | "LIMIT" | "STOP"
  entry_price  – float (cena zadání / fill price)
  entry_time   – int (Unix timestamp, app-side)
  sl           – float | null  (stop-loss cena)
  tp           – float | null  (take-profit cena)
  note         – string
  exit_price   – float | null
  exit_time    – int | null
  pnl          – float | null  (výsledný P&L)
  status       – "open" | "closed" | "cancelled"

Zápis je atomický (write → .tmp → os.replace) – stejný pattern jako data_store.py.
"""

import json
import os
import threading
import time
from datetime import datetime

_DEFAULT_PATH = os.path.join('data', 'trades.json')

# ----------------------------------------------------------------
# Debug prefix
# ----------------------------------------------------------------
_D = '[TRADE]'


class TradeTracker:
    def __init__(self, filepath: str = _DEFAULT_PATH):
        self.filepath = filepath
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        if not os.path.exists(filepath):
            self._write_atomic([])
        print(f"{_D} TradeTracker init | file={filepath}")

    # --------------------------------------------------
    # Interne helpers
    # --------------------------------------------------
    def _read(self) -> list:
        try:
            with open(self.filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return []

    def _write_atomic(self, data: list):
        tmp = self.filepath + '.tmp'
        try:
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.filepath)
        except Exception:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            raise

    def _make_id(self, symbol: str) -> str:
        return f"{symbol.upper()}_{int(time.time() * 1000)}"

    # --------------------------------------------------
    # Public API
    # --------------------------------------------------
    def open_trade(self,
                   symbol: str,
                   side: str,
                   qty: float,
                   entry_price: float,
                   order_type: str = 'MARKET',
                   sl: float = None,
                   tp: float = None,
                   note: str = '') -> dict:
        """Zaznamenat nový otevřený obchod. Vrátí záznam."""
        trade = {
            'id':           self._make_id(symbol),
            'symbol':       symbol.upper(),
            'side':         side.upper(),
            'qty':          float(qty),
            'order_type':   order_type.upper(),
            'entry_price':  float(entry_price) if entry_price else None,
            'entry_time':   int(time.time()),
            'sl':           float(sl) if sl else None,
            'tp':           float(tp) if tp else None,
            'note':         note,
            'exit_price':   None,
            'exit_time':    None,
            'pnl':          None,
            'status':       'open',
        }

        print(
            f"{_D} OPEN  | id={trade['id']} "
            f"{side.upper()} {qty}x {symbol.upper()} "
            f"@ entry={entry_price} "
            f"SL={sl if sl else 'none'} "
            f"TP={tp if tp else 'none'} "
            f"type={order_type.upper()}"
        )

        with self._lock:
            trades = self._read()
            trades.append(trade)
            self._write_atomic(trades)
            print(f"{_D} OPEN  | uloženo. Celkem open: {sum(1 for t in trades if t['status']=='open')}")

        return trade

    def close_trade(self, trade_id: str, exit_price: float) -> dict | None:
        """Uzavřít obchod podle ID. Vypočítá P&L a nastaví status=closed."""
        print(f"{_D} CLOSE | id={trade_id} exit_price={exit_price}")

        with self._lock:
            trades = self._read()
            for t in trades:
                if t['id'] == trade_id and t['status'] == 'open':
                    t['exit_price'] = float(exit_price)
                    t['exit_time']  = int(time.time())
                    t['status']     = 'closed'
                    if t['entry_price'] is not None:
                        mult = 1 if t['side'] == 'BUY' else -1
                        t['pnl'] = round(
                            mult * (t['exit_price'] - t['entry_price']) * t['qty'], 2
                        )
                    self._write_atomic(trades)
                    print(
                        f"{_D} CLOSE | OK {t['symbol']} "
                        f"entry={t['entry_price']} exit={t['exit_price']} "
                        f"P&L={t['pnl']}"
                    )
                    return t

        print(f"{_D} CLOSE | WARN: trade_id={trade_id} nenalezen nebo není open")
        return None

    def close_all_open(self, exit_prices: dict) -> list:
        """Zavře všechny open trady.
        exit_prices: {symbol: price}, pokud symbol chybí použije entry_price.
        """
        print(f"{_D} CLOSE_ALL | exit_prices={exit_prices}")
        closed = []
        with self._lock:
            trades = self._read()
            open_count = sum(1 for t in trades if t['status'] == 'open')
            print(f"{_D} CLOSE_ALL | Uzaviram {open_count} obchodu")
            for t in trades:
                if t['status'] != 'open':
                    continue
                ep = exit_prices.get(t['symbol'], t['entry_price'] or 0)
                t['exit_price'] = float(ep)
                t['exit_time']  = int(time.time())
                t['status']     = 'closed'
                if t['entry_price'] is not None:
                    mult = 1 if t['side'] == 'BUY' else -1
                    t['pnl'] = round(
                        mult * (t['exit_price'] - t['entry_price']) * t['qty'], 2
                    )
                print(
                    f"{_D} CLOSE_ALL | {t['symbol']} "
                    f"entry={t['entry_price']} exit={t['exit_price']} P&L={t['pnl']}"
                )
                closed.append(t)
            self._write_atomic(trades)
        print(f"{_D} CLOSE_ALL | Hotovo. Uzavreno: {len(closed)}")
        return closed

    def get_open_trades(self) -> list:
        with self._lock:
            result = [t for t in self._read() if t['status'] == 'open']
        print(f"{_D} GET_OPEN | {len(result)} open trade(s): "
              f"{[t['symbol'] + ' ' + t['side'] for t in result]}")
        return result

    def get_all_trades(self) -> list:
        with self._lock:
            return self._read()

    def get_history(self, limit: int = 50) -> list:
        """Vrátí posledních `limit` uzavřených obchodů, od nejnovějšího."""
        with self._lock:
            closed = [t for t in self._read() if t['status'] == 'closed']
        return sorted(closed, key=lambda x: x.get('exit_time', 0), reverse=True)[:limit]

    def get_trade(self, trade_id: str) -> dict | None:
        with self._lock:
            for t in self._read():
                if t['id'] == trade_id:
                    return t
        return None

    def check_sl_tp(self, symbol: str, current_price: float) -> list:
        """Zkontroluje všechny open trady pro symbol a vrátí seznam triggerů.

        Vrátí list slovníků:
          { 'trade': dict, 'trigger': 'SL' | 'TP', 'price': float }

        Volej pravidelně (např. z interval callbacku) a pokud je seznam neprázdný,
        odešli close order a zavři trade v trackeru.
        """
        triggered = []
        sym = symbol.upper()

        with self._lock:
            trades = self._read()

        open_trades = [t for t in trades if t['status'] == 'open' and t['symbol'] == sym]

        print(
            f"{_D} SL/TP CHECK | {sym} cur={current_price:.2f} "
            f"| {len(open_trades)} open trade(s)"
        )

        for t in open_trades:
            sl = t.get('sl')
            tp = t.get('tp')
            side = t.get('side', 'BUY')

            print(
                f"{_D} SL/TP CHECK | id={t['id']} side={side} "
                f"entry={t['entry_price']} SL={sl} TP={tp}"
            )

            # --- SL ---
            if sl:
                # BUY: cena klesla na/pod SL | SELL: cena vzrostla na/nad SL
                sl_hit = (side == 'BUY'  and current_price <= sl) or \
                         (side == 'SELL' and current_price >= sl)
                if sl_hit:
                    print(
                        f"{_D} SL/TP CHECK | *** SL HIT *** "
                        f"{sym} id={t['id']} cur={current_price:.2f} SL={sl}"
                    )
                    triggered.append({'trade': t, 'trigger': 'SL', 'price': current_price})
                    continue  # pokud SL triggeruje, TP uz nekontrolujem

            # --- TP ---
            if tp:
                # BUY: cena vystoupila na/nad TP | SELL: cena klesla na/pod TP
                tp_hit = (side == 'BUY'  and current_price >= tp) or \
                         (side == 'SELL' and current_price <= tp)
                if tp_hit:
                    print(
                        f"{_D} SL/TP CHECK | *** TP HIT *** "
                        f"{sym} id={t['id']} cur={current_price:.2f} TP={tp}"
                    )
                    triggered.append({'trade': t, 'trigger': 'TP', 'price': current_price})

        if not triggered:
            print(f"{_D} SL/TP CHECK | {sym} — zadny trigger")

        return triggered

    def fmt_time(self, ts: int | None) -> str:
        """Unix timestamp → čitelný string HH:MM:SS (dnes) nebo DD.MM HH:MM."""
        if not ts:
            return '–'
        dt = datetime.fromtimestamp(ts)
        if dt.date() == datetime.today().date():
            return dt.strftime('%H:%M:%S')
        return dt.strftime('%d.%m %H:%M')


# Globální instance
trade_tracker = TradeTracker()
