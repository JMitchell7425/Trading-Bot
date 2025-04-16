import os
import time
import datetime
import pytz
import requests
from bs4 import BeautifulSoup
import alpaca_trade_api as tradeapi
from flask import Flask, render_template_string
from threading import Thread

# === Mode: aggressive or conservative ===
MODE = "aggressive"

# === Load API keys from Render environment ===
API_KEY = os.getenv("API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
BASE_URL = os.getenv("BASE_URL")

PUSHOVER_USER_KEY = os.getenv("PUSHOVER_USER_KEY")
PUSHOVER_API_TOKEN = os.getenv("PUSHOVER_API_TOKEN")

# === Bot config ===
rsi_buy_threshold = 45
rsi_sell_threshold = 65
trailing_stop_pct = 0.03

# === Alpaca API setup ===
api = tradeapi.REST(API_KEY, SECRET_KEY, BASE_URL, api_version='v2')

# === Get dynamic top tickers from Finviz ===
def get_top_movers(limit=100):
    print("🔍 Fetching top movers from Finviz...")
    url = "https://finviz.com/screener.ashx?v=111&s=ta_topgainers&f=sh_avgvol_o500,sh_price_o5,geo_usa&ft=4"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, headers=headers)
        soup = BeautifulSoup(r.content, "html.parser")
        table = soup.find_all("a", class_="screener-link-primary")
        symbols = [x.text.strip().upper() for x in table if x.text.isalpha()]
        return symbols[:limit]
    except Exception as e:
        print(f"⚠️ Failed to fetch symbols: {e}")
        return []

symbols = get_top_movers(limit=100)

# === Flask dashboard ===
app = Flask('')

@app.route('/')
def home():
    trades, positions, chart_labels, chart_data = [], [], [], []

    if os.path.exists("trade_log.txt"):
        with open("trade_log.txt", "r") as f:
            for line in f.readlines():
                parts = line.strip().split(",")
                if len(parts) == 4:
                    trades.append({"time": parts[0], "symbol": parts[1], "type": parts[2], "price": float(parts[3])})

    if os.path.exists("portfolio_log.txt"):
        with open("portfolio_log.txt", "r") as f:
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
    body { font-family: Arial; padding: 20px; } table { width: 100%%; border-collapse: collapse; margin-bottom: 30px; }
    th, td { border: 1px solid #ccc; padding: 8px; text-align: center; } th { background-color: #f2f2f2; }
    </style></head><body><h1>🔥 Aggressive Bot Dashboard</h1>
    <h2>Positions</h2><table><tr><th>Symbol</th><th>Qty</th><th>Avg</th><th>Price</th></tr>
    {% for p in positions %}<tr><td>{{p.symbol}}</td><td>{{p.qty}}</td><td>${{p.avg_entry}}</td><td>${{p.market_price}}</td></tr>{% endfor %}</table>
    <h2>Portfolio</h2><canvas id="chart" height="80"></canvas>
    <h2>Trades</h2><table><tr><th>Time</th><th>Symbol</th><th>Type</th><th>Price</th></tr>
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

# === Utilities ===
def send_push(title, message):
    try:
        payload = {
            "token": PUSHOVER_API_TOKEN,
            "user": PUSHOVER_USER_KEY,
            "title": title,
            "message": message
        }
        requests.post("https://api.pushover.net/1/messages.json", data=payload)
    except Exception as e:
        print(f"Push failed: {e}")

def log_trade(symbol, side, price):
    with open("trade_log.txt", "a") as f:
        f.write(f"{datetime.datetime.now().isoformat()},{symbol},{side},{price}\n")
    send_push("Trade Executed", f"{side.upper()} {symbol} @ ${price:.2f}")

def log_portfolio_value():
    try:
        equity = float(api.get_account().equity)
        timestamp = datetime.datetime.now().isoformat()
        with open("portfolio_log.txt", "a") as f:
            f.write(f"{timestamp},{equity}\n")
    except:
        pass

def calculate_rsi(prices, period=14):
    if len(prices) < period + 1:
        return None
    gains = []
    losses = []
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

def is_market_open_now():
    now = datetime.datetime.now(pytz.timezone('US/Eastern'))
    return now.weekday() < 5 and datetime.time(9, 30) <= now.time() <= datetime.time(16, 0)

def get_price_data(symbol, limit=100):
    try:
        bars = api.get_bars(symbol, timeframe="5Min", limit=limit)
        closes = [bar.c for bar in bars]
        return closes, closes[-1] if closes else None
    except:
        return [], None

def trade():
    for symbol in symbols:
        closes, current_price = get_price_data(symbol)
        if not closes or len(closes) < 50 or not current_price:
            print(f"⏭ Skipping {symbol} — not enough data.")
            continue

        rsi = calculate_rsi(closes)
        avg_entry = None
        try:
            pos = api.get_position(symbol)
            qty = int(float(pos.qty))
            avg_entry = float(pos.avg_entry_price)
            side = "long" if qty > 0 else "short"
        except:
            qty = 0
            side = None

        if MODE == "conservative":
            if not qty and rsi < rsi_buy_threshold:
                api.submit_order(symbol=symbol, qty=1, side='buy', type='market', time_in_force='gtc')
                log_trade(symbol, "buy", current_price)
            elif qty and rsi > rsi_sell_threshold:
                api.submit_order(symbol=symbol, qty=abs(qty), side='sell', type='market', time_in_force='gtc')
                log_trade(symbol, "sell", current_price)

        if MODE == "aggressive":
            if not qty:
                if rsi and rsi < rsi_buy_threshold:
                    api.submit_order(symbol=symbol, qty=1, side='buy', type='market', time_in_force='gtc')
                    log_trade(symbol, "buy", current_price)
                elif rsi and rsi > 75:
                    api.submit_order(symbol=symbol, qty=1, side='sell', type='market', time_in_force='gtc')
                    log_trade(symbol, "short", current_price)
            elif qty:
                stop_price = avg_entry * (1 + trailing_stop_pct if side == "long" else 1 - trailing_stop_pct)
                exit_condition = (side == "long" and current_price < stop_price) or (side == "short" and current_price > stop_price)
                if exit_condition:
                    action = 'sell' if side == "long" else 'buy'
                    api.submit_order(symbol=symbol, qty=abs(qty), side=action, type='market', time_in_force='gtc')
                    log_trade(symbol, "exit", current_price)

def run_bot():
    print(f"🚦 MODE: {MODE.upper()}")
    while True:
        if is_market_open_now():
            trade()
            log_portfolio_value()
        else:
            print("Market closed — sleeping.")
        time.sleep(30)

if __name__ == "__main__":
    Thread(target=run_web).start()
    run_bot()
