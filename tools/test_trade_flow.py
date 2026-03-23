#!/usr/bin/env python3.11
# -*- coding: utf-8 -*-
"""Test script for IB Trading Platform - Trade Flow Test"""
import requests
import json
import time
import sys

BASE_URL = "http://localhost:8050"

def test_live_price():
    """Test 1: Live price"""
    print("=" * 60)
    print("TEST 1: ZIVA CENA")
    print("=" * 60)
    
    # Test 1a: GET /api/tick/AAPL
    print("\n1a) GET /api/tick/AAPL")
    try:
        r = requests.get(f"{BASE_URL}/api/tick/AAPL", timeout=10)
        print(f"   Status: {r.status_code}")
        print(f"   Raw text: {r.text[:500] if r.text else 'EMPTY'}")
        if r.text and r.text.strip():
            data = r.json()
            print(f"   Response: {json.dumps(data, indent=4)}")
            if data.get('price') and float(data.get('price', 0)) > 0:
                print("   [OK] REALNA CENA - neni 0.0")
            else:
                print("   [WARN] CENA JE 0.0 NEBO CHYBI")
        else:
            print("   [WARN] Empty response")
    except Exception as e:
        print(f"   [ERROR] {e}")
    
    # Test 1b: GET /api/account/info
    print("\n1b) GET /api/account/info")
    try:
        r = requests.get(f"{BASE_URL}/api/account/info", timeout=10)
        print(f"   Status: {r.status_code}")
        print(f"   Raw text: {r.text[:500] if r.text else 'EMPTY'}")
        if r.text and r.text.strip():
            data = r.json()
            print(f"   Response: {json.dumps(data, indent=4)}")
            if data.get('account_id') == 'DUH374767':
                print("   [OK] SPRAVNY UCTEU: DUH374767")
            else:
                print(f"   [WARN] UCTEU: {data.get('account_id')}")
            if data.get('net_liquidation') and float(data.get('net_liquidation', 0)) > 0:
                print("   [OK] NET LIQUIDATION NENI NULA")
            else:
                print("   [WARN] NET LIQUIDATION JE 0 NEBO CHYBI")
    except Exception as e:
        print(f"   [ERROR] {e}")
    
    return True


def test_place_order():
    """Test 2: Place order"""
    print("\n" + "=" * 60)
    print("TEST 2: ZADANI PRIKAZU")
    print("=" * 60)
    
    print("\n2) POST /api/orders")
    payload = {
        'symbol': 'AAPL',
        'asset_type': 'STOCK',
        'exchange': 'SMART',
        'action': 'BUY',
        'quantity': 1,
        'order_type': 'MARKET',
        'sl': None,
        'tp': None,
        'note': 'test_faze3'
    }
    print(f"   Payload: {json.dumps(payload, indent=4)}")
    
    try:
        r = requests.post(f"{BASE_URL}/api/orders", json=payload, timeout=30)
        print(f"   Status: {r.status_code}")
        print(f"   Raw text: {r.text[:1000] if r.text else 'EMPTY'}")
        
        if r.text and r.text.strip():
            data = r.json()
            print(f"   Response: {json.dumps(data, indent=4)}")
            
            if data.get('ok') is True:
                print("   [OK] PRIKAZ USPESNE ZADAN")
                if data.get('fill_price'):
                    print(f"   [OK] FILL PRICE: {data.get('fill_price')}")
                if data.get('message'):
                    print(f"   [OK] MESSAGE: {data.get('message')}")
                return data
            else:
                print(f"   [FAIL] PRIKAZ SELHAL: {data.get('message', 'Unknown error')}")
                return None
        else:
            print("   [WARN] Empty response")
            return None
    except Exception as e:
        print(f"   [ERROR] {e}")
        return None


def test_verify_trade():
    """Test 3: Verify trade"""
    print("\n" + "=" * 60)
    print("TEST 3: OVERENI ZAZNAMU OBCHODU")
    print("=" * 60)
    
    # Test 3a: GET /api/trades/open
    print("\n3a) GET /api/trades/open")
    try:
        r = requests.get(f"{BASE_URL}/api/trades/open", timeout=10)
        print(f"   Status: {r.status_code}")
        print(f"   Raw text: {r.text[:1000] if r.text else 'EMPTY'}")
        
        if r.text and r.text.strip():
            data = r.json()
            print(f"   Response: {json.dumps(data, indent=4)}")
            
            trades = data.get('trades', [])
            aapl_trade = [t for t in trades if t.get('symbol') == 'AAPL']
            if aapl_trade:
                print("   [OK] NALEZEN AAPL OBCHOD V OTEVRENYCH")
                return trades
            else:
                print("   [WARN] AAPL OBCHOD NENALEZEN")
        return []
    except Exception as e:
        print(f"   [ERROR] {e}")
        return []
    
    # Test 3b: GET /api/positions (if exists)
    print("\n3b) GET /api/positions")
    try:
        r = requests.get(f"{BASE_URL}/api/positions", timeout=10)
        print(f"   Status: {r.status_code}")
        if r.status_code == 200 and r.text:
            data = r.json()
            print(f"   Response: {json.dumps(data, indent=4)}")
        else:
            print("   (endpoint may not exist)")
    except Exception as e:
        print(f"   [ERROR] {e}")
    
    # Test 3c: Check trades.json file
    print("\n3c) trades.json file")
    try:
        with open("data/trades.json", "r", encoding="utf-8") as f:
            trades_data = json.load(f)
        print(f"   trades.json content:")
        print(f"   {json.dumps(trades_data, indent=4)}")
        
        # Find our test trade
        for trade in trades_data.get('trades', []):
            if trade.get('note') == 'test_faze3':
                print("   [OK] NALEZEN TESTOVACI OBCHOD V trades.json")
                return True
        print("   [WARN] TESTOVACI OBCHOD V trades.json NENALEZEN")
        return False
    except Exception as e:
        print(f"   [ERROR] {e}")
        return False


def test_close_position(trade_id):
    """Test 4: Close position"""
    print("\n" + "=" * 60)
    print(f"TEST 4: ZAVRENI POZICE (trade_id: {trade_id})")
    print("=" * 60)
    
    print(f"\n4) POST /api/trades/close/{trade_id}")
    try:
        r = requests.post(f"{BASE_URL}/api/trades/close/{trade_id}", timeout=30)
        print(f"   Status: {r.status_code}")
        print(f"   Raw text: {r.text[:1000] if r.text else 'EMPTY'}")
        
        if r.text and r.text.strip():
            data = r.json()
            print(f"   Response: {json.dumps(data, indent=4)}")
            
            if data.get('ok') is True:
                print("   [OK] POZICE USPESNE ZAVRENA")
                return data
            else:
                print(f"   [FAIL] ZAVRENI SELHALO: {data.get('message', 'Unknown error')}")
                return None
    except Exception as e:
        print(f"   [ERROR] {e}")
        return None


def test_trade_history():
    """Test 5: Verify trade history"""
    print("\n" + "=" * 60)
    print("TEST 5: TRADE HISTORY")
    print("=" * 60)
    
    print("\n5) GET /api/trades/history")
    try:
        r = requests.get(f"{BASE_URL}/api/trades/history", timeout=10)
        print(f"   Status: {r.status_code}")
        print(f"   Raw text: {r.text[:1000] if r.text else 'EMPTY'}")
        
        if r.text and r.text.strip():
            data = r.json()
            print(f"   Response: {json.dumps(data, indent=4)}")
            
            trades = data.get('trades', [])
            
            # Find our closed test trade
            for trade in trades:
                if trade.get('note') == 'test_faze3':
                    print("   [OK] NALEZEN UZAVRENY OBCHOD V HISTORII")
                    if trade.get('exit_price'):
                        print(f"   [OK] EXIT PRICE: {trade.get('exit_price')}")
                    if trade.get('exit_time'):
                        print(f"   [OK] EXIT TIME: {trade.get('exit_time')}")
                    if trade.get('pnl') is not None:
                        print(f"   [OK] P&L: {trade.get('pnl')}")
                    return trade
            
            print("   [WARN] UZAVRENY OBCHOD V HISTORII NENALEZEN")
        return None
    except Exception as e:
        print(f"   [ERROR] {e}")
        return None


if __name__ == "__main__":
    # Test 1
    test_live_price()
    
    # Wait for market data to settle
    time.sleep(2)
    
    # Test 2 - place order
    order_result = test_place_order()
    
    if order_result and order_result.get('ok'):
        # Wait for order to fill (paper trading needs time)
        print("\n[WAIT] Cekam 10s na vyplneni prikazu...")
        time.sleep(10)
        
        # Test 3 - verify trade
        test_verify_trade()
        
        # Test 4 - close position
        trade_id = None
        try:
            r = requests.get(f"{BASE_URL}/api/trades/open", timeout=10)
            if r.text and r.text.strip():
                data = r.json()
                trades = data.get('trades', [])
                aapl_trades = [t for t in trades if t.get('symbol') == 'AAPL']
                if aapl_trades:
                    trade_id = aapl_trades[0].get('id')
                    print(f"\n[INFO] Nalezen trade_id: {trade_id}")
        except Exception as e:
            print(f"\n[ERROR] Nelze nacist open trades: {e}")
        
        if trade_id:
            test_close_position(trade_id)
            
            # Wait for close to process
            print("\n[WAIT] Cekam 5s na zpracovani zavreni...")
            time.sleep(5)
            
            # Test 5 - verify history
            test_trade_history()
        else:
            print("\n[WARN] Nelze zavrit pozici - trade_id nenalezen")
    else:
        print("\n[WARN] Test 2 selhal - preskakuji Testy 3-5")
    
    print("\n" + "=" * 60)
    print("KONEC TESTU")
    print("=" * 60)
