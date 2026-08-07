"""
XGBoost Scorer Training Script
───────────────────────────────
Trains an XGBoost regressor to predict 20-day forward returns from
technical, macro, and catalyst features. Saves the model to
backend/model/xgb_scorer.json, which scoring.py loads when ENABLE_ML_MODEL=true.

Usage (from backend/ directory):
    python scripts/train_xgb.py

Requirements: pip install xgboost fredapi pandas numpy scikit-learn ta requests
All are already in requirements.txt.

Feature vector (14 features — must match scoring.py _ml_score):
    rsi_14, macd_bullish, bb_pct, stoch_rsi, ma_cross_bullish,
    volume_anomaly, volatility_20d,
    technical_score, fundamental_score, sentiment_score,
    macro_score, volatility_score, catalyst_score,
    vix

Label: 20-day forward return (regression target, clipped to [-0.5, 0.5]).
       XGBoost output is then normalised to [0, 1] via sigmoid at inference.

Training universe: 30 large-cap US equities across sectors, 3 years of daily data.
"""
import math
import os
import sys
import time
import warnings
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import requests
import ta
import xgboost as xgb
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import train_test_split

warnings.filterwarnings("ignore")

# ── Config ────────────────────────────────────────────────────────────────────

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "model", "xgb_scorer.json")
FRED_API_KEY = os.environ.get("FRED_API_KEY", "")
HISTORY_YEARS = 3
FORWARD_DAYS  = 20   # label = return over next N trading days

UNIVERSE = [
    # Tech
    "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "TSLA", "PLTR", "CRM", "ADBE",
    # Finance
    "JPM", "BAC", "GS", "MS", "V",
    # Healthcare
    "JNJ", "UNH", "PFE", "ABBV",
    # Energy
    "XOM", "CVX",
    # Consumer
    "HD", "MCD", "KO", "PG", "WMT",
    # Industrial / other
    "CAT", "BA", "LMT", "AMD",
]

XGB_PARAMS = {
    "n_estimators":     500,
    "max_depth":        4,
    "learning_rate":    0.05,
    "subsample":        0.8,
    "colsample_bytree": 0.8,
    "min_child_weight": 5,
    "reg_alpha":        0.1,
    "reg_lambda":       1.0,
    "objective":        "reg:squarederror",
    "random_state":     42,
    "n_jobs":           -1,
}

FEATURE_NAMES = [
    "rsi_14", "macd_bullish", "bb_pct", "stoch_rsi", "ma_cross_bullish",
    "volume_anomaly", "volatility_20d",
    "technical_score", "fundamental_score", "sentiment_score",
    "macro_score", "volatility_score", "catalyst_score",
    "vix",
]


# ── Data fetching ─────────────────────────────────────────────────────────────

def fetch_ohlcv(ticker: str, years: int = 3) -> pd.DataFrame:
    """Fetch daily OHLCV via Yahoo Finance v8 API."""
    days = years * 365
    hosts = ["query1.finance.yahoo.com", "query2.finance.yahoo.com"]
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    params = f"?interval=1d&range={days}d"

    for attempt, host in enumerate(hosts):
        if attempt:
            time.sleep(3)
        try:
            url = f"https://{host}/v8/finance/chart/{ticker}{params}"
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            break
        except Exception as e:
            if attempt == len(hosts) - 1:
                raise
            continue

    result = data.get("chart", {}).get("result", [])
    if not result:
        return pd.DataFrame()

    chart = result[0]
    ts    = chart.get("timestamp", [])
    ohlcv = chart.get("indicators", {}).get("quote", [{}])[0]
    adj   = chart.get("indicators", {}).get("adjclose", [{}])[0].get("adjclose", [])

    df = pd.DataFrame({
        "Open":   ohlcv.get("open",   []),
        "High":   ohlcv.get("high",   []),
        "Low":    ohlcv.get("low",    []),
        "Close":  adj if adj else ohlcv.get("close", []),
        "Volume": ohlcv.get("volume", []),
    }, index=pd.to_datetime(ts, unit="s", utc=True))

    return df.dropna(subset=["Close"])


def fetch_fred_series(series_id: str, api_key: str) -> pd.Series:
    """Fetch a FRED series as a daily-frequency Series (forward-filled)."""
    from fredapi import Fred
    fred = Fred(api_key=api_key)
    s = fred.get_series(series_id).dropna()
    # Resample to daily and forward-fill gaps (weekends, holidays)
    s.index = pd.to_datetime(s.index, utc=True)
    return s.resample("D").last().ffill()


def load_macro_series() -> dict[str, pd.Series]:
    """Load historical macro series from FRED. Returns empty dict if no key."""
    if not FRED_API_KEY:
        print("  [warn] FRED_API_KEY not set — macro features will use neutral defaults")
        return {}
    macro = {}
    for name, sid in [("vix", "VIXCLS"), ("t10", "DGS10"), ("t2", "DGS2"), ("cpi", "CPIAUCSL")]:
        try:
            macro[name] = fetch_fred_series(sid, FRED_API_KEY)
            print(f"  [fred] {sid}: {len(macro[name])} observations")
        except Exception as e:
            print(f"  [fred] {sid} failed: {e}")
    return macro


# ── Feature engineering (per bar, same logic as live pipeline) ────────────────

def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def compute_features_for_df(df: pd.DataFrame, macro: dict) -> pd.DataFrame:
    """
    Compute the 14-feature vector for every bar in *df*.
    Returns a DataFrame with columns = FEATURE_NAMES plus 'label'.
    """
    closes  = df["Close"].astype(float)
    highs   = df["High"].astype(float)
    lows    = df["Low"].astype(float)
    volumes = df["Volume"].astype(float)

    rows = []

    # Pre-compute series once (faster than per-row)
    rsi_s       = ta.momentum.RSIIndicator(close=closes, window=14).rsi()
    macd_ind    = ta.trend.MACD(close=closes, window_slow=26, window_fast=12, window_sign=9)
    macd_s      = macd_ind.macd()
    macd_sig_s  = macd_ind.macd_signal()
    bb          = ta.volatility.BollingerBands(close=closes, window=20, window_dev=2)
    bb_pct_s    = bb.bollinger_pband()
    stoch_rsi_s = ta.momentum.StochRSIIndicator(close=closes, window=14, smooth1=3, smooth2=3).stochrsi()
    ma_20_s     = closes.rolling(20).mean()
    ma_50_s     = closes.rolling(50).mean()
    vol_avg_s   = volumes.rolling(20).mean()
    log_ret_s   = np.log(closes / closes.shift(1))

    for i in range(60, len(df) - FORWARD_DAYS):
        idx = df.index[i]

        # Raw indicators
        rsi       = rsi_s.iloc[i]
        macd_v    = macd_s.iloc[i]
        macd_sig  = macd_sig_s.iloc[i]
        bb_pct    = bb_pct_s.iloc[i]
        stoch     = stoch_rsi_s.iloc[i]
        price     = closes.iloc[i]
        ma_20     = ma_20_s.iloc[i]
        ma_50     = ma_50_s.iloc[i]
        vol       = volumes.iloc[i]
        vol_avg   = vol_avg_s.iloc[i]
        log_window = log_ret_s.iloc[max(0, i-19):i+1].dropna()

        if any(pd.isna(v) for v in [rsi, macd_v, macd_sig, bb_pct, stoch, ma_20, ma_50]):
            continue

        # Derived
        macd_bullish    = 1.0 if macd_v > macd_sig else 0.0
        ma_cross_bull   = 1.0 if ma_20 > ma_50 else 0.0
        volume_anomaly  = float(vol / vol_avg) if vol_avg > 0 else 1.0
        volatility_20d  = float(log_window.std() * math.sqrt(252)) if len(log_window) > 1 else 0.3

        # Technical sub-score
        rsi_clamped = _clamp(rsi, 0, 100)
        if rsi_clamped <= 30:   rsi_s_val = 1.0
        elif rsi_clamped >= 70: rsi_s_val = 0.0
        else:                   rsi_s_val = 1.0 - (rsi_clamped - 30) / 40.0
        bb_s = _clamp(1.0 - float(bb_pct))
        stoch_s = _clamp(1.0 - float(stoch))
        technical_score = _clamp(
            (rsi_s_val * 0.25 + macd_bullish * 0.25 + bb_s * 0.20 + stoch_s * 0.15 + ma_cross_bull * 0.15)
        )

        # Volatility sub-score
        if volatility_20d <= 0.15:   volatility_score = 1.0
        elif volatility_20d >= 0.80: volatility_score = 0.0
        else:                        volatility_score = _clamp(1.0 - (volatility_20d - 0.15) / 0.65)

        # Catalyst sub-score: volume spike only — must match catalyst.py inference logic.
        # catalyst.py deliberately uses the same formula. If catalyst.py is updated
        # to multi-component scoring, retrain this model first.
        vol_spike = _clamp((volume_anomaly - 1.0) / 2.0) if volume_anomaly > 1 else 0.0
        catalyst_score = vol_spike

        # Macro from FRED (look up nearest historical value)
        vix_val   = _get_macro_val(macro, "vix",  idx, default=20.0)
        t10_val   = _get_macro_val(macro, "t10",  idx, default=4.0)
        t2_val    = _get_macro_val(macro, "t2",   idx, default=3.5)
        cpi_s_val = _get_cpi_yoy(macro, idx)

        spread = t10_val - t2_val
        if vix_val <= 15:   vix_score = 1.0
        elif vix_val >= 35: vix_score = 0.0
        else:               vix_score = _clamp(1.0 - (vix_val - 15) / 20.0)
        spread_score = _clamp((spread + 0.5) / 1.0)
        if cpi_s_val is None:       cpi_score = 0.5
        elif cpi_s_val <= 2.5:      cpi_score = 1.0
        elif cpi_s_val <= 6.0:      cpi_score = _clamp(1.0 - (cpi_s_val - 2.5) / 3.5)
        else:                        cpi_score = 0.0
        macro_score = _clamp(vix_score * 0.35 + spread_score * 0.35 + cpi_score * 0.30)

        # Forward return label
        future_close = closes.iloc[i + FORWARD_DAYS]
        label = float(np.clip((future_close - price) / price, -0.5, 0.5))

        rows.append({
            "rsi_14":          float(rsi),
            "macd_bullish":    macd_bullish,
            "bb_pct":          float(bb_pct),
            "stoch_rsi":       float(stoch),
            "ma_cross_bullish":ma_cross_bull,
            "volume_anomaly":  volume_anomaly,
            "volatility_20d":  volatility_20d,
            "technical_score": technical_score,
            "fundamental_score": 0.5,   # not available historically
            "sentiment_score": 0.5,     # not available historically
            "macro_score":     macro_score,
            "volatility_score":volatility_score,
            "catalyst_score":  catalyst_score,
            "vix":             vix_val,
            "label":           label,
        })

    return pd.DataFrame(rows)


def _get_macro_val(macro: dict, key: str, idx, default: float) -> float:
    s = macro.get(key)
    if s is None:
        return default
    try:
        idx_tz = idx if idx.tzinfo else idx.tz_localize("UTC")
        past = s[s.index <= idx_tz]
        return float(past.iloc[-1]) if not past.empty else default
    except Exception:
        return default


def _get_cpi_yoy(macro: dict, idx) -> float | None:
    s = macro.get("cpi")
    if s is None:
        return None
    try:
        idx_tz = idx if idx.tzinfo else idx.tz_localize("UTC")
        past = s[s.index <= idx_tz].dropna()
        if len(past) < 13:
            return None
        return float((past.iloc[-1] - past.iloc[-13]) / past.iloc[-13] * 100)
    except Exception:
        return None


# ── Training ──────────────────────────────────────────────────────────────────

def train():
    print(f"\n{'='*60}")
    print(f"XGBoost Scorer Training — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Universe: {len(UNIVERSE)} tickers | History: {HISTORY_YEARS}y | Forward: {FORWARD_DAYS}d")
    print(f"{'='*60}\n")

    print("[1/4] Loading macro series from FRED...")
    macro = load_macro_series()

    print(f"\n[2/4] Fetching OHLCV and computing features for {len(UNIVERSE)} tickers...")
    all_frames = []
    for i, ticker in enumerate(UNIVERSE, 1):
        try:
            df = fetch_ohlcv(ticker, HISTORY_YEARS)
            if len(df) < 100:
                print(f"  [{i:02d}/{len(UNIVERSE)}] {ticker}: skip (only {len(df)} bars)")
                continue
            feat_df = compute_features_for_df(df, macro)
            if feat_df.empty:
                print(f"  [{i:02d}/{len(UNIVERSE)}] {ticker}: skip (no valid feature rows)")
                continue
            all_frames.append(feat_df)
            print(f"  [{i:02d}/{len(UNIVERSE)}] {ticker}: {len(feat_df)} rows")
            time.sleep(0.5)  # gentle rate limiting
        except Exception as e:
            print(f"  [{i:02d}/{len(UNIVERSE)}] {ticker}: ERROR — {e}")

    if not all_frames:
        print("\nNo training data collected. Check network / API access.")
        sys.exit(1)

    data = pd.concat(all_frames, ignore_index=True).dropna()
    print(f"\nTotal rows: {len(data):,}")
    print(f"Label stats: mean={data['label'].mean():.4f}  std={data['label'].std():.4f}")

    X = data[FEATURE_NAMES].values
    y = data["label"].values

    print("\n[3/4] Training XGBoost...")
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    model = xgb.XGBRegressor(**XGB_PARAMS, early_stopping_rounds=30, eval_metric="mae")
    model.fit(
        X_train, y_train,
        eval_set=[(X_test, y_test)],
        verbose=100,
    )

    preds = model.predict(X_test)
    mae   = mean_absolute_error(y_test, preds)
    r2    = r2_score(y_test, preds)
    print(f"\nTest MAE : {mae:.4f}")
    print(f"Test R²  : {r2:.4f}")

    print("\nFeature importances (gain):")
    importances = model.get_booster().get_score(importance_type="gain")
    for fname in FEATURE_NAMES:
        score = importances.get(f"f{FEATURE_NAMES.index(fname)}", 0)
        bar = "█" * int(score / max(importances.values(), default=1) * 30)
        print(f"  {fname:<22} {score:8.1f}  {bar}")

    print(f"\n[4/4] Saving model → {OUTPUT_PATH}")
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    model.save_model(OUTPUT_PATH)
    print(f"Done. Set ENABLE_ML_MODEL=true in .env to activate.\n")


if __name__ == "__main__":
    train()
