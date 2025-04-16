import alpaca_trade_api as tradeapi
import datetime
import os
import time
import pytz
from flask import Flask, render_template_string
from threading import Thread
import json

# === Load API keys from environment variables ===
import os
API_KEY = os.getenv("API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
BASE_URL = os.getenv("BASE_URL")

app = Flask('')

@app.route('/')
def home():
    trades = []
    positions = []
    chart_labels = []
    chart_data = []

    if os.path.exists("trade_log.txt"):
        with open("trade_log.txt", "r") as f:
            for line in f.readlines():
                parts = line.strip().split(",")
                if len(parts) == 4:
                    trades.append({
                        "time": parts[0],
                        "symbol": parts[1],
                        "type": parts[2].upper(),
                        "price": float(parts[3])
                    })

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

    html = """<html><head><title>Bot Dashboard</title><style>
    body { font-family: Arial; padding: 20px; }
    table { width: 100%%; border-collapse: collapse; margin-bottom: 30px; }
    th, td { border: 1px solid #ccc; padding: 8px; text-align: center; }
    th { background-color: #f2f2f2; }
    </style></head><body>
    <h1>📈 Trading Bot Dashboard</h1>
    <h2>Positions</h2><table><tr><th>Symbol</th><th>Qty</th><th>Avg</th><th>Price</th></tr>
    {% for p in positions %}<tr><td>{{p.symbol}}</td><td>{{p.qty}}</td><td>${{p.avg_entry}}</td><td>${{p.market_price}}</td></tr>{% endfor %}</table>
    <h2>Portfolio Chart</h2><canvas id="portfolioChart" height="80"></canvas>
    <h2>Trade Log</h2><table><tr><th>Time</th><th>Symbol</th><th>Type</th><th>Price</th></tr>
    {% for t in trades[::-1] %}<tr><td>{{t.time}}</td><td>{{t.symbol}}</td><td>{{t.type}}</td><td>${{t.price}}</td></tr>{% endfor %}</table>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script>
    const ctx = document.getElementById('portfolioChart').getContext('2d');
    const portfolioChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: {{ chart_labels|safe }},
            datasets: [{
                label: 'Portfolio ($)',
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

api = tradeapi.REST(API_KEY, SECRET_KEY, BASE_URL, api_version='v2')

with open("symbols.txt", "r") as f:
    symbols = [line.strip().upper() for line in f if line.strip()]

rsi_buy_threshold = 45
rsi_sell_threshold = 65
trailing_stop_pct = 0.03
log_file = "trade_log.txt"

def log_trade(symbol, side, price):
    with open(log_file, "a") as f:
        f.write(f"{datetime.datetime.now().isoformat()},{symbol},{side},{price}\n")

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

def get_price_data(symbol):
    try:
        tz = pytz.timezone("US/Eastern")
        now = datetime.datetime.now(tz)
        market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
        bars = api.get_bars(symbol, timeframe="1Min", start=market_open.isoformat())
        closes = [bar.c for bar in bars]
        volumes = [bar.v for bar in bars]
        if len(closes) > 200:
            closes = closes[-200:]
            volumes = volumes[-200:]
        return closes, volumes, closes[-1] if closes else None
    except:
        return [], [], None
def is_uptrend(closes):
    if len(closes) < 200:
        return False
    ma50 = sum(closes[-50:]) / 50
    ma200 = sum(closes[-200:]) / 200
    return closes[-1] > ma50 > ma200

def breakout_volume_strategy(closes, volumes):
    if len(closes) < 30 or len(volumes) < 20:
        return False
    recent_high = max(closes[-30:])
    breakout = closes[-1] > recent_high
    avg_volume = sum(volumes[-20:]) / 20
    strong_volume = volumes[-1] > 1.5 * avg_volume
    return breakout and strong_volume

def get_last_buy_price(symbol):
    if not os.path.exists(log_file):
        return None
    with open(log_file, "r") as f:
        lines = f.readlines()
    for line in reversed(lines):
        parts = line.strip().split(",")
        if len(parts) == 4 and parts[1] == symbol and parts[2] == "buy":
            return float(parts[3])
    return None

def is_market_open_now():
    now = datetime.datetime.now(pytz.timezone('US/Eastern'))
    return now.weekday() < 5 and datetime.time(9, 30) <= now.time() <= datetime.time(16, 0)

def trade():
    for symbol in symbols:
        try:
            position = api.get_position(symbol)
            has_position = True
        except:
            has_position = False

        closes, volumes, current_price = get_price_data(symbol)
        if not closes or not current_price:
            print(f"⚠️ Skipping {symbol}: not enough data.")
            continue

        rsi = calculate_rsi(closes)
        uptrend = is_uptrend(closes)
        breakout = breakout_volume_strategy(closes, volumes)

        print(f"{symbol}: Price=${current_price:.2f}, RSI={rsi}, Uptrend={uptrend}, Breakout={breakout}")

        if not has_position and (
            (rsi and rsi < rsi_buy_threshold and uptrend) or breakout
        ):
            print(f"✅ BUYING 1 share of {symbol}")
            api.submit_order(
                symbol=symbol,
                qty=1,
                side='buy',
                type='market',
                time_in_force='gtc'
            )
            log_trade(symbol, "buy", current_price)
            with open(f"highs_{symbol}.txt", "w") as f:
                f.write(str(current_price))

        elif has_position:
            last_buy_price = get_last_buy_price(symbol)
            trailing_file = f"highs_{symbol}.txt"

            if os.path.exists(trailing_file):
                with open(trailing_file, "r") as f:
                    try:
                        high = float(f.read().strip())
                    except:
                        high = current_price
            else:
                high = current_price

            if current_price > high:
                high = current_price
                with open(trailing_file, "w") as f:
                    f.write(str(high))

            trailing_triggered = current_price <= (1 - trailing_stop_pct) * high
            rsi_exit = rsi and rsi > rsi_sell_threshold

            if trailing_triggered or rsi_exit:
                print(f"📤 SELLING {symbol} — trailing stop or RSI")
                api.submit_order(
                    symbol=symbol,
                    qty=position.qty,
                    side='sell',
                    type='market',
                    time_in_force='gtc'
                )
                log_trade(symbol, "sell", current_price)
                if os.path.exists(trailing_file):
                    os.remove(trailing_file)
            else:
                print(f"📈 Holding {symbol}")

# === Start Bot ===
if __name__ == "__main__":
    Thread(target=run_web).start()
    print("🌀 Starting 30-sec trading loop...")
    while True:
        if is_market_open_now():
            print("🔄 Market open — checking trades...")
            trade()
            log_portfolio_value()
        else:
            print("🕒 Market closed — sleeping.")
        time.sleep(30)
