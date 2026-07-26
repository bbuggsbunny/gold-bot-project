"""
Feature engineering: 17 yıllık 1dk histdata → 15dk mumlar → features.csv
Çıktı kolonları: rsi, macd_hist, bb_poz, adx, ma_oran, volatilite, hacim_oran, atr, hedef
Hedef: sonraki 16 mum (4 saat) içinde ±%1 harekete göre AL(1) / SAT(-1) / BEKLE(0)
"""
import sys, time
from pathlib import Path
import numpy as np
import pandas as pd

HISTDATA_DIR = Path(__file__).parents[1] / "veri" / "histdata"
OUTPUT_FILE  = Path(__file__).parent / "features.csv"
YILLAR       = range(2009, 2026)

t_baslangic = time.time()


# ── 1. Veri yükleme ──────────────────────────────────────────────────────────

def oku_yil(yil: int) -> pd.DataFrame:
    dosya = HISTDATA_DIR / f"DAT_MT_XAUUSD_M1_{yil}.csv"
    df = pd.read_csv(
        dosya, header=None,
        names=["tarih", "saat", "acilis", "yuksek", "dusuk", "kapanis", "hacim"],
        dtype={"tarih": str, "saat": str,
               "acilis": float, "yuksek": float, "dusuk": float,
               "kapanis": float, "hacim": float},
    )
    df["dt"] = pd.to_datetime(df["tarih"] + " " + df["saat"], format="%Y.%m.%d %H:%M")
    return df.drop(columns=["tarih", "saat"]).set_index("dt")


print("Veri yükleniyor (17 yıl × 1dk mum)...")
parcalar = []
for y in YILLAR:
    parcalar.append(oku_yil(y))
    print(f"  {y} ✓", end="\r", flush=True)

df1m = pd.concat(parcalar).sort_index()
print(f"  1dk mum toplamı : {len(df1m):>10,}")


# ── 2. 15dk resample ─────────────────────────────────────────────────────────

agg = {"acilis": "first", "yuksek": "max", "dusuk": "min",
       "kapanis": "last", "hacim": "sum"}
df = df1m.resample("15min").agg(agg).dropna()
del df1m  # bellek boşalt
print(f"  15dk mum toplamı: {len(df):>10,}")


# ── 3. Özellik hesaplama ─────────────────────────────────────────────────────

c = df["kapanis"]
h = df["yuksek"]
lo = df["dusuk"]

# True Range (ADX ve ATR için ortak)
tr = pd.concat([
    h - lo,
    (h - c.shift()).abs(),
    (lo - c.shift()).abs(),
], axis=1).max(axis=1)

# --- RSI (14) ---
delta = c.diff()
gain  = delta.clip(lower=0).rolling(14).mean()
loss  = (-delta.clip(upper=0)).rolling(14).mean()
df["rsi"] = 100 - (100 / (1 + gain / loss))

# --- MACD histogram ---
ema12         = c.ewm(span=12, adjust=False).mean()
ema26         = c.ewm(span=26, adjust=False).mean()
macd_line     = ema12 - ema26
macd_signal   = macd_line.ewm(span=9, adjust=False).mean()
df["macd_hist"] = macd_line - macd_signal

# --- Bollinger Band pozisyonu: (fiyat − BB_alt) / (BB_üst − BB_alt) ---
ma20  = c.rolling(20).mean()
std20 = c.rolling(20).std()
bb_alt = ma20 - 2 * std20
bb_ust = ma20 + 2 * std20
df["bb_poz"] = (c - bb_alt) / (bb_ust - bb_alt)

# --- ADX (14) — Wilder smoothing, EWM ile vektörize ---
# Wilder smoothing: alpha = 1/n → ewm(alpha=1/14) * 14 = Wilder sum
alpha = 1 / 14
dm_pos = h.diff().clip(lower=0)
dm_neg = (-lo.diff()).clip(lower=0)

tr14   = tr.ewm(alpha=alpha, adjust=False).mean() * 14
dmp14  = dm_pos.ewm(alpha=alpha, adjust=False).mean() * 14
dmn14  = dm_neg.ewm(alpha=alpha, adjust=False).mean() * 14

di_pos = 100 * dmp14 / tr14.replace(0, np.nan)
di_neg = 100 * dmn14 / tr14.replace(0, np.nan)
dx = 100 * (di_pos - di_neg).abs() / (di_pos + di_neg).replace(0, np.nan)
df["adx"] = dx.ewm(alpha=alpha, adjust=False).mean()

# --- MA20/MA50 oranı ---
ma50 = c.rolling(50).mean()
df["ma_oran"] = ma20 / ma50

# --- Volatilite: std/ortalama (son 50 mum) ---
df["volatilite"] = c.rolling(50).std() / c.rolling(50).mean()

# --- ATR (14) ---
df["atr"] = tr.rolling(14).mean()

# --- Son 3 mumun yön sayısı: kaç tanesi yükseliş (kapanış > açılış) ---
yukselis = (df["kapanis"] > df["acilis"]).astype(int)
df["yon_3"] = yukselis.rolling(3).sum()

# --- Son 5 mumun kapanış momentumu: şimdiki / 5 önceki - 1 ---
df["momentum_5"] = c / c.shift(5) - 1

# --- RSI değişim hızı: RSI - RSI.shift(3) ---
df["rsi_hiz"] = df["rsi"] - df["rsi"].shift(3)

# --- Zaman özellikleri (altın London/NY seanslarına duyarlı) ---
df["saat"]    = df.index.hour                      # 0-23
df["gun"]     = df.index.dayofweek                 # 0=Pzt … 4=Cum


# ── 4. Hedef değişken ────────────────────────────────────────────────────────
# 4 saat = 16 mum sonraki kapanış getirisi

gelecek_getiri = c.shift(-16) / c - 1
df["hedef"] = 0
df.loc[gelecek_getiri >=  0.003, "hedef"] =  1   # AL
df.loc[gelecek_getiri <= -0.003, "hedef"] = -1   # SAT


# ── 5. Temizle ve kaydet ─────────────────────────────────────────────────────

kolonlar = ["rsi", "macd_hist", "bb_poz", "adx", "ma_oran",
            "volatilite", "atr", "yon_3", "momentum_5", "rsi_hiz",
            "saat", "gun", "hedef"]
df_final = df[kolonlar].dropna()

OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
df_final.to_csv(OUTPUT_FILE)

# ── 6. Özet rapor ────────────────────────────────────────────────────────────

sure = time.time() - t_baslangic
dagilim = df_final["hedef"].value_counts().sort_index()
toplam  = len(df_final)

print(f"\n{'='*45}")
print(f"  features.csv kaydedildi: {OUTPUT_FILE.name}")
print(f"{'='*45}")
print(f"  Toplam örnek  : {toplam:,}")
print(f"  Kolonlar      : {len(kolonlar)-1} özellik + 1 hedef")
print()
print("  Class dağılımı:")
etiketler = {-1: "SAT  (-1)", 0: "BEKLE (0)", 1: "AL    (1)"}
for k in [-1, 0, 1]:
    v = dagilim.get(k, 0)
    pct = v / toplam * 100
    bar = "█" * int(pct / 2)
    print(f"    {etiketler[k]}: {v:>7,}  ({pct:5.1f}%)  {bar}")
print()
print(f"  Süre: {sure:.1f} saniye")
