import alpaca_trade_api as tradeapi
import datetime
import time
import pytz
import os
import requests
from bs4 import BeautifulSoup

def get_top_movers(limit=100):
    print("🔍 Fetching top movers from Finviz...")
    url = "https://finviz.com/screener.ashx?v=111&s=ta_topgainers&f=sh_avgvol_o500,sh_price_o5,geo_usa&ft=4"
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        r = requests.get(url, headers=headers)
        soup = BeautifulSoup(r.content, "html.parser")
        table = soup.find_all("a", class_="screener-link-primary")
        symbols = [x.text.strip().upper() for x in table if x.text.isalpha()]
        top = symbols[:limit]
        print(f"✅ Retrieved {len(top)} symbols.")
        return top
    except Exception as e:
        print(f"⚠️ Failed to fetch tickers: {e}")
        return []

MODE = "aggressive"  # Change to "conservative" to switch strategies

# Load Alpaca keys from environment
API_KEY = os.getenv("API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
BASE_URL = os.getenv("BASE_URL")

api = tradeapi.REST(API_KEY, SECRET_KEY, BASE_URL, api_version='v2')

# Load symbols from file
with open("symbols.txt", "r") as f:
    symbols = [line.strip().upper() for line in f if line.strip()]

rsi_buy_threshold = 45
rsi_sell_threshold = 65
trailing_stop_pct = 0.03  # Default trailing stop % (can be adjusted dynamically)

def is_market_open_now():
    now = datetime.datetime.now(pytz.timezone('US/Eastern'))
    return now.weekday() < 5 and datetime.time(9, 30) <= now.time() <= datetime.time(16, 0)

def get_price_data(symbol, limit=100):
    try:
        bars = api.get_bars(symbol, timeframe="5Min", limit=limit)
        closes = [bar.c for bar in bars]
        highs = [bar.h for bar in bars]
        lows = [bar.l for bar in bars]
        volumes = [bar.v for bar in bars]
        return closes, highs, lows, volumes
    except:
        return [], [], [], []

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
def is_uptrend(closes):
    if len(closes) < 100:
        return False
    ma20 = sum(closes[-20:]) / 20
    ma50 = sum(closes[-50:]) / 50
    return closes[-1] > ma20 > ma50

def is_downtrend(closes):
    if len(closes) < 100:
        return False
    ma20 = sum(closes[-20:]) / 20
    ma50 = sum(closes[-50:]) / 50
    return closes[-1] < ma20 < ma50

def trade():
    for symbol in symbols:
        closes, highs, lows, volumes = get_price_data(symbol)
        if not closes or len(closes) < 50:
            print(f"Skipping {symbol}: insufficient data")
            continue

        current_price = closes[-1]
        rsi = calculate_rsi(closes)
        uptrend = is_uptrend(closes)
        downtrend = is_downtrend(closes)

        print(f"{symbol}: Price=${current_price:.2f}, RSI={rsi}, Uptrend={uptrend}, Downtrend={downtrend}")

        try:
            position = api.get_position(symbol)
            qty = int(float(position.qty))
            side = "long" if float(qty) > 0 else "short"
        except:
            position = None
            qty = 0
            side = None

        # === Conservative Mode ===
        if MODE == "conservative":
            if not position and uptrend and rsi < rsi_buy_threshold:
                print(f"✅ BUYING 1 share of {symbol} (Conservative)")
                api.submit_order(symbol=symbol, qty=1, side='buy', type='market', time_in_force='gtc')

            elif position:
                if rsi and rsi > rsi_sell_threshold:
                    print(f"📤 SELLING {symbol} (Conservative)")
                    api.submit_order(symbol=symbol, qty=abs(qty), side='sell', type='market', time_in_force='gtc')

        # === Aggressive Mode ===
        if MODE == "aggressive":
            if not position:
                if uptrend and rsi < rsi_buy_threshold:
                    print(f"📈 LONG ENTRY: {symbol}")
                    api.submit_order(symbol=symbol, qty=1, side='buy', type='market', time_in_force='gtc')
                elif downtrend and rsi > 75:
                    print(f"📉 SHORT ENTRY: {symbol}")
                    api.submit_order(symbol=symbol, qty=1, side='sell', type='market', time_in_force='gtc')  # Short

            elif position:
                stop_price = float(position.avg_entry_price) * (1 + trailing_stop_pct if side == "long" else 1 - trailing_stop_pct)
                trigger_sell = (
                    (side == "long" and current_price < stop_price) or
                    (side == "short" and current_price > stop_price)
                )

                if trigger_sell:
                    print(f"🔁 EXITING {symbol} — trailing stop hit")
                    action = 'sell' if side == 'long' else 'buy'
                    api.submit_order(symbol=symbol, qty=abs(qty), side=action, type='market', time_in_force='gtc')

def run_bot():
    print(f"🧠 Mode: {MODE.upper()} — Bot starting...")
    while True:
        if is_market_open_now():
            print("🔄 Checking trades...")
            trade()
        else:
            print("🕒 Market closed. Sleeping...")
        time.sleep(30)

if __name__ == "__main__":
    run_bot()
