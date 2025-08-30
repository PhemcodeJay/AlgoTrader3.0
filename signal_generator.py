from fpdf import FPDF
from datetime import datetime, timedelta, timezone
from time import sleep
import requests
import sys
from utils import get_candles, ema, sma, rsi, bollinger, atr, macd, classify_trend, RISK_PCT, ACCOUNT_BALANCE, LEVERAGE, ENTRY_BUFFER_PCT, MIN_VOLUME, MIN_ATR_PCT, RSI_ZONE, INTERVALS, MAX_SYMBOLS
import logging
tz_utc3 = timezone(timedelta(hours=3))


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# === PDF GENERATOR ===
class SignalPDF(FPDF):
    def header(self):
        self.set_font("Arial", "B", 10)
        self.cell(0, 10, "Bybit Futures Multi-TF Signals", 0, 1, "C")

    def add_signals(self, signals):
        self.set_font("Courier", size=8)
        for s in signals:
            self.set_text_color(0, 0, 0)
            self.set_font("Courier", "B", 8)
            self.cell(0, 5, f"==================== {s['Symbol']} ====================", ln=1)
            self.set_font("Courier", "", 8)
            self.set_text_color(0, 0, 139)
            self.cell(0, 4, f"TYPE: {s['Type']}    SIDE: {s['Side']}     SCORE: {s['Score']}%", ln=1)
            self.set_text_color(34, 139, 34)
            self.cell(0, 4, f"ENTRY: {s['Entry']}   TP: {s['TP']}         SL: {s['SL']}", ln=1)
            self.set_text_color(139, 0, 0)
            self.cell(0, 4, f"MARKET: {s['Market']}  BB: {s['BB Slope']}    Trail: {s['Trail']}", ln=1)
            self.set_text_color(0, 100, 100)
            self.cell(0, 4, f"QTY: {s['Qty']}  MARGIN: {s['Margin']} USDT  LIQ: {s['Liq']}", ln=1)
            self.set_text_color(0, 0, 0)
            self.cell(0, 4, f"TIME: {s['Time']}", ln=1)
            self.cell(0, 4, "=" * 57, ln=1)
            self.ln(1)

# === FORMATTER ===
def format_signal_block(s):
    return (
        f"==================== {s['Symbol']} ====================\n"
        f"📊 TYPE: {s['Type']}     📈 SIDE: {s['Side']}     🏆 SCORE: {s['Score']}%\n"
        f"💵 ENTRY: {s['Entry']}   🎯 TP: {s['TP']}         🛡️ SL: {s['SL']}\n"
        f"💱 MARKET: {s['Market']} 📍 BB: {s['BB Slope']}    🔄 Trail: {s['Trail']}\n"
        f"📦 QTY: {s['Qty']} ⚖️ MARGIN: {s['Margin']} USDT ⚠️ LIQ: {s['Liq']}\n"
        f"⏰ TIME: {s['Time']}\n"
        "=========================================================\n"
    )

# === SIGNAL ANALYSIS ===
def analyze(symbol):
    data = {}
    for tf in INTERVALS:
        candles = get_candles(symbol, tf)
        if len(candles) < 30:
            return None
        closes = [c['close'] for c in candles]
        highs = [c['high'] for c in candles]
        lows = [c['low'] for c in candles]
        vols = [c['volume'] for c in candles]
        data[tf] = {
            'close': closes[-1],
            'ema9': ema(closes, 9),
            'ema21': ema(closes, 21),
            'sma20': sma(closes, 20),
            'rsi': rsi(closes),
            'macd': macd(closes),
            'bb_up': bollinger(closes)[0],
            'bb_mid': bollinger(closes)[1],
            'bb_low': bollinger(closes)[2],
            'atr': atr(highs, lows, closes),
            'volume': vols[-1]
        }

    tf60 = data['60']
    if (tf60['volume'] < MIN_VOLUME or tf60['atr'] / tf60['close'] < MIN_ATR_PCT or
        not (RSI_ZONE[0] < tf60['rsi'] < RSI_ZONE[1])):
        return None

    sides = []
    for d in data.values():
        if d['close'] > d['bb_up']: sides.append('LONG')
        elif d['close'] < d['bb_low']: sides.append('SHORT')
        elif d['close'] > d['ema21']: sides.append('LONG')
        elif d['close'] < d['ema21']: sides.append('SHORT')

    if len(set(sides)) != 1:
        return None

    tf = tf60
    price = tf['close']
    trend = classify_trend(tf['ema9'], tf['ema21'], tf['sma20'])
    bb_dir = "Up" if price > tf['bb_up'] else "Down" if price < tf['bb_low'] else "No"
    opts = [tf['sma20'], tf['ema9'], tf['ema21']]
    entry = min(opts, key=lambda x: abs(x - price))

    side = 'Buy' if sides[0] == 'LONG' else 'Sell'

    tp = round(entry * (1.015 if side == 'Buy' else 0.985), 6)
    sl = round(entry * (0.985 if side == 'Buy' else 1.015), 6)
    trail = round(entry * (1 - ENTRY_BUFFER_PCT) if side == 'Buy' else entry * (1 + ENTRY_BUFFER_PCT), 6)
    liq = round(entry * (1 - 1 / LEVERAGE) if side == 'Buy' else entry * (1 + 1 / LEVERAGE), 6)

    try:
        risk_amt = ACCOUNT_BALANCE * RISK_PCT
        sl_diff = abs(entry - sl)
        qty = risk_amt / sl_diff
        margin_usdt = round((qty * entry) / LEVERAGE, 3)
        qty = round(qty, 3)
    except (ZeroDivisionError, ValueError) as e:
        margin_usdt = 1.0
        qty = 1.0

    score = 0
    score += 0.3 if tf['macd'] and tf['macd'] > 0 else 0
    score += 0.2 if tf['rsi'] < 30 or tf['rsi'] > 70 else 0
    score += 0.2 if bb_dir != "No" else 0
    score += 0.3 if trend in ["Up", "Bullish"] else 0.1

    return {
        'Symbol': symbol,
        'Side': side,
        'Type': trend,
        'Score': round(score * 100, 1),
        'Entry': round(entry, 6),
        'TP': tp,
        'SL': sl,
        'Trail': trail,
        'Margin': margin_usdt,
        'Qty': qty,
        'Market': price,
        'Liq': liq,
        'BB Slope': bb_dir,
        'Time': datetime.now(tz_utc3).strftime("%Y-%m-%d %H:%M UTC+3")
    }

# === SYMBOL FETCH ===
def get_usdt_symbols():
    try:
        data = requests.get("https://api.bybit.com/v5/market/tickers?category=linear").json()
        tickers = [i for i in data['result']['list'] if i['symbol'].endswith("USDT")]
        tickers.sort(key=lambda x: float(x['turnover24h']), reverse=True)
        return [t['symbol'] for t in tickers[:MAX_SYMBOLS]]
    except Exception as e:
        logger.error(f"Error fetching USDT symbols from Bybit: {e}")
        return []

# === MAIN LOOP ===
def main():
    while True:
        print("\n🔍 Scanning Bybit USDT Futures for filtered signals...\n")
        symbols = get_usdt_symbols()
        signals = [analyze(s) for s in symbols]
        signals = [s for s in signals if s]

        if signals:
            signals.sort(key=lambda x: x['Score'], reverse=True)
            top5 = signals[:5]
            blocks = [format_signal_block(s) for s in top5]
            agg_msg = "\n".join(blocks)

            for blk in blocks:
                print(blk)

            pdf = SignalPDF()
            pdf.add_page()
            pdf.add_signals(signals[:20])
            fname = f"signals_{datetime.now(tz_utc3).strftime('%H%M')}.pdf"
            pdf.output(fname)
            print(f"📄 PDF saved: {fname}\n")
        else:
            print("⚠️ No valid signals found\n")

        wait = 3600
        print("⏳ Rescanning in 60 minutes...")
        for i in range(wait, 0, -1):
            sys.stdout.write(f"\r⏱️  Next scan in {i//60:02d}:{i%60:02d}")
            sys.stdout.flush()
            sleep(1)
        print()

if __name__ == "__main__":
    main()