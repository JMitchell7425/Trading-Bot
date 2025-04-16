import os
import time
import datetime
import pytz
import requests
from threading import Thread
from flask import Flask, render_template_string
from bs4 import BeautifulSoup
import alpaca_trade_api as tradeapi

MODE = "aggressive"  # or "conservative"
TEST_MODE = True  # Set to True to simulate a test trade

API_KEY = os.getenv("API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
BASE_URL = os.getenv("BASE_URL")

api = tradeapi.REST(API_KEY, SECRET_KEY, BASE_URL, api_version='v2')

rsi_buy_threshold = 45
rsi_sell_threshold = 65
trailing_stop_pct = 0.03
log_file = "trade_log.txt"
portfolio_log = "portfolio_log.txt"

app = Flask('')

@app.route('/')
def home():
    trades, positions, chart_labels, chart_data = [], [], [], []
    if os.path.exists(log_file):
        with open(log_file, "r") as f:
            for line in f:
                parts = line.strip().split(",")
                if len(parts) == 4:
                    trades.append({
                        "time": parts[0],
                        "symbol": parts[1],
                        "type": parts[2].upper(),
                        "price": float(parts[3])
                    })

    if os.path.exists(portfolio_log):
        with open(portfolio_log, "r") as f:
            for line in f.readlines()[-100:]:
                t, v = line.strip().split(",")
                chart_labels.append(t)
                chart_data.append(v)

    try:
        raw_positions = api.list_positions()
        for p in raw_positions:
            positions.append({
                "symbol": p.symbol,
                "qty": p.qty,
                "avg_entry": p.avg_entry_price,
                "market_price": p.current_price
            })
    except:
        pass

    html = """<html><head><title>Aggressive Bot</title><style>
    body { font-family: Arial; padding: 20px; }
    table { width: 100%%; border-collapse: collapse; margin-bottom: 30px; }
    th, td { border: 1px solid #ccc; padding: 8px; text-align: center; }
    th { background-color: #f2f2f2; }</style></head>
    <body><h1>🔥 Aggressive Trading Bot Dashboard</h1>
    <h2>Positions</h2><table><tr><th>Symbol</th><th>Qty</th><th>Avg</th><th>Current</th></tr>
    {% for p in positions %}<tr><td>{{p.symbol}}</td><td>{{p.qty}}</td><td>${{p.avg_entry}}</td><td>${{p.market_price}}</td></tr>{% endfor %}</table>
    <h2>Portfolio</h2><canvas id="chart" height="80"></canvas>
    <h2>Trade History</h2><table><tr><th>Time</th><th>Symbol</th><th>Type</th><th>Price</th></tr>
    {% for t in trades[::-1] %}<tr><td>{{t.time}}</td><td>{{t.symbol}}</td><td>{{t.type}}</td><td>${{t.price}}</td></tr>{% endfor %}</table>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script>
    const ctx = document.getElementById('chart').getContext('2d');
    new Chart(ctx, {
        type: 'line',
        data: {
            labels: {{ chart_labels|safe }},
            datasets: [{
                label: 'Equity ($)',
                data: {{ chart_data|safe }},
                borderColor: 'green',
                fill: false,
                tension: 0.2
            }]
        }
    });
    </script></body></html>"""
    return render_template_string(html, trades=trades, positions=positions, chart_labels=chart_labels, chart_data=chart_data)

def run_web():
    app.run(host='0.0.0.0', port=8080)

def get_top_movers(limit=250):
    print("🔍 Fetching top movers from Finviz...")
    url = "https://finviz.com/screener.ashx?v=111&s=ta_topgainers&f=sh_avgvol_o500,sh_price_o5,geo_usa&ft=4"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, headers=headers)
        soup = BeautifulSoup(r.content, "html.parser")
        table = soup.find_all("a", class_="screener-link-primary")
        symbols = [x.text.strip().upper() for x in table if x.text.isalpha()]
        print(f"✅ Retrieved {len(symbols[:limit])} symbols: {symbols[:limit]}")
        return symbols[:limit]
    except Exception as e:
        print(f"⚠️ Failed to fetch tickers: {e}")
        return []
def get_price_data(symbol, limit=100):
    try:
        bars = api.get_bars(symbol, timeframe="5Min", limit=limit)
        closes = [bar.c for bar in bars]
        return closes, closes[-1] if closes else None
    except:
        return [], None

def calculate_rsi(prices, period=14):
    if len(prices) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(prices)):
        delta = prices[i] - prices[i - 1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(prices)):
        delta = prices[i] - prices[i - 1]
        gain = max(delta, 0)
        loss = max(-delta, 0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def log_trade(symbol, side, price):
    with open(log_file, "a") as f:
        f.write(f"{datetime.datetime.now().isoformat()},{symbol},{side},{price}\n")

def log_portfolio_value():
    try:
        eq = float(api.get_account().equity)
        with open(portfolio_log, "a") as f:
            f.write(f"{datetime.datetime.now().isoformat()},{eq}\n")
    except:
        pass

def is_market_open_now():
    now = datetime.datetime.now(pytz.timezone('US/Eastern'))
    return now.weekday() < 5 and datetime.time(9, 30) <= now.time() <= datetime.time(16, 0)

def trade(symbols):
    for symbol in symbols:
        print(f"— Checking {symbol}...")
        closes, current_price = get_price_data(symbol)
        if not closes or not current_price:
            print(f"⚠️ Skipping {symbol}: No price data.")
            continue

        rsi = calculate_rsi(closes)

        try:
            position = api.get_position(symbol)
            qty = int(float(position.qty))
            side = "long" if qty > 0 else "short"
        except:
            position = None
            qty = 0
            side = None

        print(f"🔍 {symbol}: Price=${current_price:.2f}, RSI={rsi}, Position={position is not None}, Mode={MODE}")

        if not position and TEST_MODE:
            print(f"🧪 TEST_MODE ON: Simulating BUY for {symbol}")
            try:
                api.submit_order(symbol=symbol, qty=1, side='buy', type='market', time_in_force='gtc')
                log_trade(symbol, "TEST-BUY", current_price)
                print(f"✅ Test trade submitted for {symbol} at ${current_price}")
            except Exception as e:
                print(f"❌ Error placing test trade: {e}")
            return

        if MODE == "conservative":
            if not position and rsi and rsi < rsi_buy_threshold:
                api.submit_order(symbol=symbol, qty=1, side='buy', type='market', time_in_force='gtc')
                log_trade(symbol, "buy", current_price)
            elif position and rsi and rsi > rsi_sell_threshold:
                api.submit_order(symbol=symbol, qty=abs(qty), side='sell', type='market', time_in_force='gtc')
                log_trade(symbol, "sell", current_price)

        elif MODE == "aggressive":
            if not position:
                if rsi and rsi < rsi_buy_threshold:
                    api.submit_order(symbol=symbol, qty=1, side='buy', type='market', time_in_force='gtc')
                    log_trade(symbol, "buy", current_price)
                elif rsi and rsi > 75:
                    api.submit_order(symbol=symbol, qty=1, side='sell', type='market', time_in_force='gtc')
                    log_trade(symbol, "short", current_price)
            elif position:
                stop_price = float(position.avg_entry_price) * (1 + trailing_stop_pct if side == "long" else 1 - trailing_stop_pct)
                trigger = (side == "long" and current_price < stop_price) or (side == "short" and current_price > stop_price)
                if trigger:
                    action = "sell" if side == "long" else "buy"
                    api.submit_order(symbol=symbol, qty=abs(qty), side=action, type='market', time_in_force='gtc')
                    log_trade(symbol, "exit", current_price)

def run_bot():
    print(f"🧠 Bot running in {MODE.upper()} mode | TEST_MODE = {TEST_MODE}")
    while True:
        if is_market_open_now():
            print("🔄 Market open — scanning...")
            symbols = get_top_movers(limit=250)
            trade(symbols)
            log_portfolio_value()
        else:
            print("⏳ Market closed. Sleeping...")
        time.sleep(30)

if __name__ == "__main__":
    Thread(target=run_web).start()
    run_bot()

