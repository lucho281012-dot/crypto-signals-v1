import os, json, logging
from pathlib import Path
from datetime import datetime, timezone
import ccxt, pandas as pd, requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("crypto-signals")
SYMBOLS = [s.strip() for s in os.getenv("SYMBOLS","BTC/USDT,ETH/USDT,SOL/USDT").split(",") if s.strip()]
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
MIN_SCORE = int(os.getenv("MIN_SCORE","4"))
ATR_MULT = float(os.getenv("ATR_MULTIPLIER","1.2"))
STATE_PATH = Path("data/state.json")
STATE_PATH.parent.mkdir(exist_ok=True)

def load_state():
    try: return json.loads(STATE_PATH.read_text())
    except Exception: return {"last_candle": {}}

def save_state(state):
    STATE_PATH.write_text(json.dumps(state, indent=2))

def notify(msg):
    r = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={"chat_id":CHAT_ID,"text":msg,"disable_web_page_preview":True}, timeout=20)
    r.raise_for_status()
    if not r.json().get("ok"): raise RuntimeError(r.text)

def frame(ex, symbol, tf):
    rows = ex.fetch_ohlcv(symbol, timeframe=tf, limit=250)
    if len(rows) < 210: raise RuntimeError(f"Datos insuficientes: {symbol} {tf}")
    return pd.DataFrame(rows,columns=["timestamp","open","high","low","close","volume"]).iloc[:-1].copy().reset_index(drop=True)

def ind(df):
    c,h,l,v=df.close,df.high,df.low,df.volume
    df["ema20"]=c.ewm(span=20,adjust=False).mean()
    df["ema200"]=c.ewm(span=200,adjust=False).mean()
    d=c.diff()
    up=d.clip(lower=0).ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    dn=(-d.clip(upper=0)).ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    df["rsi"]=100-100/(1+up/dn.replace(0,1e-12))
    m=c.ewm(span=12,adjust=False).mean()-c.ewm(span=26,adjust=False).mean()
    df["hist"]=m-m.ewm(span=9,adjust=False).mean()
    pc=c.shift(1)
    tr=pd.concat([(h-l),(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1)
    df["atr"]=tr.ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    df["volavg"]=v.rolling(20).mean()
    return df

def analyze(d5,d15):
    z=ind(d5); x,prev= z.iloc[-1],z.iloc[-2]
    y=ind(d15).iloc[-1]
    if pd.isna(x.atr) or pd.isna(x.rsi) or pd.isna(x.volavg) or x.atr<=0 or x.volavg<=0: return None
    long=[x.close>x.ema200,x.close>x.ema20 and x.ema20>prev.ema20,50<=x.rsi<=68,x.hist>0 and x.hist>=prev.hist,x.volume>x.volavg]
    short=[x.close<x.ema200,x.close<x.ema20 and x.ema20<prev.ema20,32<=x.rsi<=50,x.hist<0 and x.hist<=prev.hist,x.volume>x.volavg]
    lc=y.close>y.ema200 and y.ema20>y.ema200
    sc=y.close<y.ema200 and y.ema20<y.ema200
    ls,ss=sum(long),sum(short)
    if ls>=MIN_SCORE and lc and ls>ss: side,score="LONG",ls
    elif ss>=MIN_SCORE and sc and ss>ls: side,score="SHORT",ss
    else: return None
    entry,dist=float(x.close),float(x.atr)*ATR_MULT
    stop,tp1,tp2=(entry-dist,entry+dist,entry+2*dist) if side=="LONG" else (entry+dist,entry-dist,entry-2*dist)
    return dict(side=side,score=score,entry=entry,stop=stop,tp1=tp1,tp2=tp2,rsi=float(x.rsi),vol=float(x.volume/x.volavg),ts=int(d5.iloc[-1].timestamp))

def fmt(x): return f"{x:,.6f}".rstrip("0").rstrip(".")

def main():
    ex=ccxt.binanceusdm({"enableRateLimit":True,"timeout":20000})
    state=load_state()
    for symbol in SYMBOLS:
        try:
            d5=frame(ex,symbol,"5m"); candle=int(d5.iloc[-1].timestamp)
            if state["last_candle"].get(symbol)==candle:
                log.info("%s: vela ya procesada",symbol); continue
            d15=frame(ex,symbol,"15m")
            sig=analyze(d5,d15)
            state["last_candle"][symbol]=candle
            if sig:
                dt=datetime.fromtimestamp(sig["ts"]/1000,timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                icon="🟢" if sig["side"]=="LONG" else "🔴"
                msg=(f"{icon} CRYPTO SIGNALS V1.1\n{symbol} · {sig['side']}\nTemporalidades: 5m + confirmación 15m\n"
                     f"Entrada ref.: {fmt(sig['entry'])}\nStop Loss: {fmt(sig['stop'])}\nTP1 (1R): {fmt(sig['tp1'])}\nTP2 (2R): {fmt(sig['tp2'])}\n"
                     f"Filtros: {sig['score']}/5 · RSI: {sig['rsi']:.1f}\nVolumen/promedio: {sig['vol']:.2f}x\nVela cerrada: {dt}\n"
                     "Alerta informativa; no garantiza resultados. Verifica el precio antes de actuar.")
                notify(msg); log.info("Señal enviada: %s %s",symbol,sig["side"])
            else: log.info("%s: sin señal",symbol)
        except Exception: log.exception("Error con %s",symbol)
    save_state(state)

if __name__=="__main__": main()
