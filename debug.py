import sys
import argparse
import time
import ib_gateway

def print_result(success, message, data=None):
    status = "✅ SUCCESS" if success else "❌ ERROR"
    print(f"\n{status}: {message}")
    if data:
        import json
        print(json.dumps(data, indent=2, default=str))
    print("-" * 40)

def cmd_candles(symbol, timeframe, count):
    print(f"Fetching {count} candles for {symbol} ({timeframe})...")
    if not ib_gateway.connect():
        print_result(False, "Failed to connect to IB")
        return
    
    try:
        bars = ib_gateway.get_candles(symbol, timeframe, count=count)
        if bars:
            print_result(True, f"Fetched {len(bars)} candles", {
                "first": bars[0],
                "last": bars[-1]
            })
        else:
            print_result(False, "No candles returned")
    except Exception as e:
        print_result(False, f"Exception: {e}")
    finally:
        ib_gateway.disconnect()

def cmd_buy(symbol, qty):
    print(f"Placing BUY MARKET order for {qty} {symbol}...")
    if not ib_gateway.connect():
        print_result(False, "Failed to connect to IB")
        return
    
    try:
        result = ib_gateway.place_order(symbol, 'BUY', qty, 'MARKET')
        if result and result.get('status') in ['Submitted', 'Filled', 'PreSubmitted']:
            print_result(True, f"Order placed successfully. Status: {result.get('status')}", result)
        else:
            print_result(False, "Order placement failed or stuck", result)
    except Exception as e:
        print_result(False, f"Exception: {e}")
    finally:
        # Wait a bit for order to process before disconnecting
        time.sleep(2)
        ib_gateway.disconnect()

def cmd_sell(symbol, qty):
    print(f"Placing SELL MARKET order for {qty} {symbol}...")
    if not ib_gateway.connect():
        print_result(False, "Failed to connect to IB")
        return
    
    try:
        result = ib_gateway.place_order(symbol, 'SELL', qty, 'MARKET')
        if result and result.get('status') in ['Submitted', 'Filled', 'PreSubmitted']:
            print_result(True, f"Order placed successfully. Status: {result.get('status')}", result)
        else:
            print_result(False, "Order placement failed or stuck", result)
    except Exception as e:
        print_result(False, f"Exception: {e}")
    finally:
        time.sleep(2)
        ib_gateway.disconnect()

def cmd_status():
    print("Fetching account status and positions...")
    if not ib_gateway.connect():
        print_result(False, "Failed to connect to IB")
        return
    
    try:
        account_info = ib_gateway.get_account_info()
        positions = ib_gateway.get_positions()
        
        print_result(True, "Account Status", {
            "account": account_info,
            "positions": positions
        })
    except Exception as e:
        print_result(False, f"Exception: {e}")
    finally:
        ib_gateway.disconnect()

def main():
    parser = argparse.ArgumentParser(description="IB Trading Platform Diagnostic Tool")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # Candles command
    parser_candles = subparsers.add_parser("candles", help="Fetch historical candles")
    parser_candles.add_argument("--symbol", default="AAPL", help="Symbol to fetch (default: AAPL)")
    parser_candles.add_argument("--tf", default="5 mins", help="Timeframe (default: '5 mins')")
    parser_candles.add_argument("--count", type=int, default=60, help="Number of candles (default: 60)")
    
    # Buy command
    parser_buy = subparsers.add_parser("buy", help="Place a test BUY MARKET order")
    parser_buy.add_argument("--symbol", default="AAPL", help="Symbol to buy (default: AAPL)")
    parser_buy.add_argument("--qty", type=int, default=1, help="Quantity to buy (default: 1)")
    
    # Sell command
    parser_sell = subparsers.add_parser("sell", help="Place a test SELL MARKET order")
    parser_sell.add_argument("--symbol", default="AAPL", help="Symbol to sell (default: AAPL)")
    parser_sell.add_argument("--qty", type=int, default=1, help="Quantity to sell (default: 1)")
    
    # Status command
    parser_status = subparsers.add_parser("status", help="Check account status and open positions")
    
    args = parser.parse_args()
    
    if args.command == "candles":
        cmd_candles(args.symbol, args.tf, args.count)
    elif args.command == "buy":
        cmd_buy(args.symbol, args.qty)
    elif args.command == "sell":
        cmd_sell(args.symbol, args.qty)
    elif args.command == "status":
        cmd_status()
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
