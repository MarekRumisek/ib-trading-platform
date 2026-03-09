"""Standalone IB Order Test Script

Tests if IB Gateway/TWS accepts orders from API.
Use during trading hours for best results.

Usage: python test_order.py
Press Ctrl+C to exit
"""

from ib_async import IB, Stock, MarketOrder
import time
import sys

def test_order():
    ib = IB()
    
    try:
        print("="*60)
        print("🧪 IB ORDER TEST SCRIPT")
        print("="*60)
        
        # Připoj se
        print("\n📡 Connecting to IB Gateway...")
        ib.connect('127.0.0.1', 7497, clientId=999)
        print("✅ Connected successfully!")
        
        # Zkontroluj account
        accounts = ib.managedAccounts()
        if accounts:
            account = accounts[0]
            print(f"✅ Account: {account}")
        else:
            print("❌ No accounts found!")
            return
        
        # Zkontroluj open orders
        open_orders = ib.openOrders()
        print(f"📋 Open orders: {len(open_orders)}")
        
        # Vytvoř jednoduchý market order
        print("\n" + "="*60)
        print("🚀 PLACING TEST ORDER")
        print("="*60)
        
        from contract_utils import create_contract
        contract = create_contract('AAPL', 'STOCK')
        order = MarketOrder('BUY', 1)
        order.transmit = True
        order.outsideRth = True
        
        print("\n📝 Order details:")
        print(f"   Symbol: AAPL")
        print(f"   Action: BUY")
        print(f"   Quantity: 1")
        print(f"   Type: MARKET")
        print(f"   Transmit: True")
        print(f"   OutsideRTH: True")
        
        print("\n🚀 Submitting to IB...")
        trade = ib.placeOrder(contract, order)
        print(f"✅ Order object created")
        print(f"   Order ID: {trade.order.orderId if trade.order else 'N/A'}")
        
        # Sleduj status 15 sekund
        print("\n" + "="*60)
        print("⏳ MONITORING ORDER STATUS (15 seconds)")
        print("="*60 + "\n")
        
        last_status = None
        for i in range(15):
            ib.sleep(1)
            
            current_status = trade.orderStatus.status
            
            # Zobraz změnu statusu
            if current_status != last_status:
                print(f"[{i:2d}s] 📊 Status changed: {last_status or 'None'} → {current_status}")
                last_status = current_status
            else:
                print(f"[{i:2d}s] Status: {current_status}")
            
            # Zkontroluj logy a errory
            if trade.log:
                for entry in trade.log:
                    if entry.message and entry.message.strip():
                        print(f"       💬 Message: {entry.message}")
                    if entry.errorCode and entry.errorCode != 0:
                        print(f"       ❌ Error {entry.errorCode}: {entry.message}")
            
            # Úspěch?
            if current_status in ['Submitted', 'Filled', 'PreSubmitted']:
                print(f"\n🎉 SUCCESS! Order reached: {current_status}")
                break
                
            # Selhání?
            if current_status in ['Cancelled', 'Inactive', 'ApiCancelled']:
                print(f"\n❌ FAILED! Order status: {current_status}")
                break
        
        # Finální report
        print("\n" + "="*60)
        print("📊 FINAL RESULTS")
        print("="*60)
        print(f"Final Status: {trade.orderStatus.status}")
        print(f"Order ID: {trade.order.orderId if trade.order else 'N/A'}")
        print(f"Filled: {trade.orderStatus.filled}")
        print(f"Remaining: {trade.orderStatus.remaining}")
        
        if trade.orderStatus.status == 'PendingSubmit':
            print("\n⚠️  ORDER STUCK IN PENDINGSUBMIT!")
            print("\n🔧 Troubleshooting checklist:")
            print("   1. TWS/Gateway → File → Global Configuration → API → Settings")
            print("   2. ✓ Enable ActiveX and Socket Clients = ON")
            print("   3. ✗ Read-Only API = OFF (most important!)")
            print("   4. Restart TWS/Gateway after changes")
            print("   5. Test during regular trading hours (15:30-22:00 CET)")
            print("   6. Confirm paper trading dialog in TWS if first time")
        
        print("\n" + "="*60)
        print("Press Ctrl+C to exit...")
        print("="*60)
        
        # Drž script živý
        while True:
            ib.sleep(1)
            
    except KeyboardInterrupt:
        print("\n\n👋 Exiting...")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        if ib.isConnected():
            ib.disconnect()
            print("🔌 Disconnected from IB")

if __name__ == "__main__":
    test_order()
