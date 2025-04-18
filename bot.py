import os
import time
import datetime
import pytz
import json
import requests
from threading import Thread
from flask import Flask, request, render_template_string
from bs4 import BeautifulSoup
import alpaca_trade_api as tradeapi

# ========================
# RAVEN CONTROL SETUP
# ========================
CONFIG_FILE = "config.json"
DEFAULT_CONFIG = {
    "mode": "aggressive",
    "test_mode": False,
    "use_trend_filter": True,
    "use_reversal_logic": True,
    "use_volume_confirmation": True,
    "rsi_buy_threshold": 45,
    "rsi_sell_threshold": 65,
    "rsi_period": 14,
    "bar_count": 100,
    "max_open_trades": 5,
    "min_trade_spacing_minutes": 10,
    "risk_percent_per_trade": 1.0,
    "profit_target_pct": 5.0,
    "stop_loss_pct": 3.0,
    "dynamic_volatility": True,
    "rebuy_cooldown_minutes": 20,
    "market_direction": "both",
    "trend_sensitivity": 1.0,
    "reversal_aggression": 1.0,
    "volume_threshold": 1.0,
    "paused": False,
    "manual_override": False,
    "custom_symbols": []
}

def load_config():
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w") as f:
            json.dump(DEFAULT_CONFIG, f)
        return DEFAULT_CONFIG.copy()
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)

def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f)

config = load_config()

# ========================
# ALPACA API
# ========================
API_KEY = os.getenv("API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
BASE_URL = os.getenv("BASE_URL")
api = tradeapi.REST(API_KEY, SECRET_KEY, BASE_URL, api_version='v2')

# ========================
# LOGGING + FILES
# ========================
log_file = "trade_log.txt"
portfolio_log = "portfolio_log.txt"
watchlist_file = "watchlist.json"
if not os.path.exists(watchlist_file):
    with open(watchlist_file, "w") as f:
        json.dump([], f)

# ========================
# FLASK SETUP
# ========================
app = Flask(__name__)
@app.route('/')
def dashboard():
    current_config = load_config()
    with open(watchlist_file, "r") as f:
        custom_symbols = json.load(f)

    trades, chart_labels, chart_data = [], [], []

    if os.path.exists(log_file):
        with open(log_file, "r") as f:
            for line in f.readlines()[-100:]:
                parts = line.strip().split(",")
                if len(parts) == 4:
                    trades.append({
                        "time": parts[0],
                        "symbol": parts[1],
                        "type": parts[2],
                        "price": float(parts[3])
                    })

    if os.path.exists(portfolio_log):
        with open(portfolio_log, "r") as f:
            for line in f.readlines()[-100:]:
                t, v = line.strip().split(",")
                chart_labels.append(t)
                chart_data.append(v)

    current_year = datetime.datetime.utcnow().year

    html = f'''
    <!DOCTYPE html><html><head>
    <title>RAVEN Control</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
    body {{
        background-color: #0d0d0d;
        color: #e6e6e6;
        font-family: 'Segoe UI', Tahoma, sans-serif;
        margin: 0;
        padding: 0;
    }}
    .header {{
        text-align: center;
        padding: 30px;
        background: radial-gradient(circle, #2e2e2e, #0d0d0d);
        border-bottom: 1px solid #444;
    }}
    .header img {{
        width: 140px;
        margin-bottom: 10px;
    }}
    .header h1 {{
        margin: 0;
        font-size: 2.5rem;
        color: #ff3c3c;
    }}
    .header h3 {{
        font-weight: 300;
        color: #aaa;
        font-size: 1rem;
        margin-top: 8px;
    }}
    .container {{
        padding: 20px;
        max-width: 1100px;
        margin: auto;
    }}
    .section {{
        background-color: #1a1a1a;
        border: 1px solid #333;
        border-radius: 10px;
        padding: 20px;
        margin-bottom: 25px;
    }}
    input, select, button {{
        background-color: #222;
        color: #f0f0f0;
        border: 1px solid #555;
        padding: 6px;
        margin: 3px;
        border-radius: 5px;
    }}
    .footer {{
        text-align: center;
        font-size: 0.85rem;
        color: #777;
        padding: 10px 0 20px;
    }}
    /* Boot Overlay */
    #raven-boot {{
        position: fixed;
        z-index: 9999;
        top: 0; left: 0; width: 100%; height: 100%;
        background: #0d0d0d;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        animation: fadeOut 4s forwards 3s;
    }}
    #raven-boot img {{
        width: 160px;
        filter: drop-shadow(0 0 6px #ff3c3c);
    }}
    .boot-text {{
        color: #ccc;
        margin-top: 30px;
        font-family: 'Courier New', monospace;
        font-size: 1.2rem;
        text-align: center;
        animation: typing 2.5s steps(30, end), fadeToFinal 1s forwards 3s;
    }}
    @keyframes fadeOut {{
        to {{ opacity: 0; visibility: hidden; display: none; }}
    }}
    </style>
    </head>
    <body>
    <div id="raven-boot">
        <img src="https://raw.githubusercontent.com/YOUR_USERNAME/YOUR_REPO/main/raven_logo.png" alt="RAVEN Logo">
        <div class="boot-text">System Online</div>
    </div>

    <div class="header">
        <img src="https://raw.githubusercontent.com/YOUR_USERNAME/YOUR_REPO/main/raven_logo.png" alt="RAVEN Logo">
        <h1>🦅 RAVEN Control</h1>
        <h3>Risk Assessment & Volatility Execution Node</h3>
    </div>

    <div class="container">
        <div class="section">
            <h2>Strategy Controls</h2>
            <form method="post" action="/update_config">
                <label>Mode:
                    <select name="mode">
                        <option value="aggressive" {'selected' if config["mode"]=="aggressive" else ''}>Aggressive</option>
                        <option value="conservative" {'selected' if config["mode"]=="conservative" else ''}>Conservative</option>
                    </select>
                </label>
                <label>Test Mode:
                    <select name="test_mode">
                        <option value="True" {'selected' if config["test_mode"] else ''}>On</option>
                        <option value="False" {'selected' if not config["test_mode"] else ''}>Off</option>
                    </select>
                </label>
                <label>RSI Buy Threshold:
                    <input name="rsi_buy_threshold" value="{config["rsi_buy_threshold"]}">
                </label>
                <label>RSI Sell Threshold:
                    <input name="rsi_sell_threshold" value="{config["rsi_sell_threshold"]}">
                </label>
                <label>Bar Count:
                    <input name="bar_count" value="{config["bar_count"]}">
                </label>
                <label>Profit Target %%:
                    <input name="profit_target_pct" value="{config["profit_target_pct"]}">
                </label>
                <label>Stop Loss %%:
                    <input name="stop_loss_pct" value="{config["stop_loss_pct"]}">
                </label>
                <label>Risk %% per Trade:
                    <input name="risk_percent_per_trade" value="{config["risk_percent_per_trade"]}">
                </label>
                <br><br><button type="submit">💾 Save</button>
            </form>
        </div>
    '''

    return render_template_string(html, config=current_config, trades=trades, chart_labels=chart_labels, chart_data=chart_data, current_year=current_year)
def update_config_from_form(form_data):
    for key in form_data:
        value = form_data[key]
        if value.lower() in ["true", "false"]:
            value = value.lower() == "true"
        elif "." in value or "e" in value:
            try:
                value = float(value)
            except:
                pass
        elif value.isdigit():
            value = int(value)
        config[key] = value
    save_config(config)

@app.route('/update_config', methods=["POST"])
def update_config():
    update_config_from_form(request.form)
    return dashboard()

@app.route('/add_symbol', methods=["POST"])
def add_symbol():
    symbol = request.form.get("symbol", "").upper()
    if symbol and symbol not in config["custom_symbols"]:
        config["custom_symbols"].append(symbol)
        save_config(config)
    return dashboard()

def get_price_data(symbol, limit=100):
    try:
        bars = api.get_bars(symbol, timeframe="1Min", limit=limit)
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
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calculate_volatility(prices):
    if len(prices) < 2:
        return 0
    returns = [abs(prices[i] - prices[i - 1]) for i in range(1, len(prices))]
    return sum(returns) / len(returns)

def get_trend(prices, sensitivity=1.0):
    if len(prices) < 20:
        return None
    short_ma = sum(prices[-5:]) / 5
    long_ma = sum(prices[-20:]) / 20
    return short_ma - long_ma > sensitivity

def log_trade(symbol, action, price):
    with open(log_file, "a") as f:
        f.write(f"{datetime.datetime.now().isoformat()},{symbol},{action},{price}\n")

def log_portfolio_value():
    try:
        eq = float(api.get_account().equity)
        with open(portfolio_log, "a") as f:
            f.write(f"{datetime.datetime.now().isoformat()},{eq}\n")
    except Exception as e:
        print(f"Portfolio log error: {e}")

def calculate_qty(price, equity, config, volatility):
    risk_amount = (config["risk_percent_per_trade"] / 100) * equity
    if config["dynamic_volatility"] and volatility > 0:
        scaled_risk = max(1, round(risk_amount / (volatility * price)))
    else:
        scaled_risk = max(1, round(risk_amount / price))
    return scaled_risk
def should_trade_symbol(symbol, recent_trades, config):
    now = datetime.datetime.now(pytz.timezone("US/Eastern"))
    cooldown = datetime.timedelta(minutes=config["min_trade_spacing_minutes"])
    for entry in recent_trades:
        if entry["symbol"] == symbol:
            last_time = datetime.datetime.fromisoformat(entry["time"])
            if now - last_time < cooldown:
                return False
    return True

def trade(symbols, config):
    recent_trades = []
    if os.path.exists(log_file):
        with open(log_file, "r") as f:
            for line in f.readlines()[-200:]:
                parts = line.strip().split(",")
                if len(parts) == 4:
                    recent_trades.append({
                        "time": parts[0],
                        "symbol": parts[1],
                        "type": parts[2],
                        "price": float(parts[3])
                    })

    open_positions = api.list_positions()
    held_symbols = [pos.symbol for pos in open_positions]
    equity = float(api.get_account().equity)

    for symbol in symbols:
        if not should_trade_symbol(symbol, recent_trades, config):
            continue

        prices, current_price = get_price_data(symbol, config["bar_count"])
        if not prices or not current_price:
            continue

        rsi = calculate_rsi(prices, config["rsi_period"])
        trend = get_trend(prices, config["trend_sensitivity"]) if config["use_trend_filter"] else True
        volatility = calculate_volatility(prices)
        qty = calculate_qty(current_price, equity, config, volatility)

        if config["market_direction"] == "long" and rsi > config["rsi_sell_threshold"]:
            continue
        if config["market_direction"] == "short" and rsi < config["rsi_buy_threshold"]:
            continue

        try:
            position = api.get_position(symbol)
            is_held = True
            qty_held = int(float(position.qty))
            entry_price = float(position.avg_entry_price)
        except:
            is_held = False
            qty_held = 0
            entry_price = 0

        if not is_held:
            if config["test_mode"]:
                print(f"[TEST] Would BUY {symbol} @ ${current_price}")
                log_trade(symbol, "TEST-BUY", current_price)
                continue

            if rsi and rsi < config["rsi_buy_threshold"] and trend:
                print(f"BUY {symbol} @ {current_price} x {qty}")
                api.submit_order(symbol=symbol, qty=qty, side='buy', type='market', time_in_force='gtc')
                log_trade(symbol, "BUY", current_price)
        else:
            stop_price = entry_price * (1 - config["stop_loss_pct"] / 100)
            target_price = entry_price * (1 + config["profit_target_pct"] / 100)

            if current_price <= stop_price:
                print(f"STOP LOSS {symbol} @ {current_price}")
                api.submit_order(symbol=symbol, qty=qty_held, side='sell', type='market', time_in_force='gtc')
                log_trade(symbol, "STOP", current_price)
            elif current_price >= target_price:
                print(f"PROFIT EXIT {symbol} @ {current_price}")
                api.submit_order(symbol=symbol, qty=qty_held, side='sell', type='market', time_in_force='gtc')
                log_trade(symbol, "SELL", current_price)
def get_top_movers(limit=250):
    url = "https://finviz.com/screener.ashx?v=111&s=ta_topgainers&f=sh_avgvol_o500,sh_price_o5,geo_usa&ft=4"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, headers=headers)
        soup = BeautifulSoup(r.content, "html.parser")
        table = soup.find_all("a", class_="screener-link-primary")
        symbols = [x.text.strip().upper() for x in table if x.text.isalpha()]
        return symbols[:limit]
    except:
        return []

def run_bot():
    print("🧠 RAVEN Control ACTIVE")
    while True:
        live_config = load_config()
        if live_config["paused"]:
            print("⏸ Bot is paused.")
        else:
            all_symbols = get_top_movers() + live_config.get("custom_symbols", [])
            trade(all_symbols, live_config)
            log_portfolio_value()
        time.sleep(30)

if __name__ == "__main__":
    Thread(target=app.run, kwargs={"host": "0.0.0.0", "port": 8080}).start()
    run_bot()
