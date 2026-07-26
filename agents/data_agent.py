# agents/data_agent.py
# ─────────────────────────────────────────────
# Veri Ajanı: Binance'den fiyat verisi çeker.
# Kısa vadeli: 1 dakikalık mum + breakout seviyeleri
# Uzun vadeli: 15 dakikalık mum + RSI/MACD/BB
# ─────────────────────────────────────────────

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import pandas as pd
from binance.client import Client
import config
from tipler import KisaVeri, UzunVeri
from agents.utils import senkronize_et
from agents.telegram_agent import bildir_hata


def get_client():
    return Client(
        config.BINANCE_API_KEY,
        config.BINANCE_SECRET_KEY,
        testnet=config.TESTNET
    )


def hesapla_rsi(close, periyot=14):
    delta = close.diff()
    kazan = delta.clip(lower=0).ewm(com=periyot-1, min_periods=periyot).mean()
    kayip = (-delta.clip(upper=0)).ewm(com=periyot-1, min_periods=periyot).mean()
    rs    = kazan / kayip.replace(0, float('inf'))
    return 100 - (100 / (1 + rs))

def hesapla_macd(close):
    ema12  = close.ewm(span=12, adjust=False).mean()
    ema26  = close.ewm(span=26, adjust=False).mean()
    macd   = ema12 - ema26
    sinyal = macd.ewm(span=9, adjust=False).mean()
    return macd, sinyal

def hesapla_bollinger(close, periyot=20, std=2):
    ort   = close.rolling(periyot).mean()
    sapma = close.rolling(periyot).std()
    return ort + (sapma * std), ort, ort - (sapma * std)


def kisa_vadeli_veri() -> KisaVeri:
    """
    Kısa vadeli bot için 1 dakikalık mum verisi.
    Breakout stratejisi için:
    - Son 20 mumun direnç/destek seviyeleri
    - ATR (dinamik SL/TP için)
    - Hacim analizi
    """
    client = get_client()
    senkronize_et(client)

    son_hata = None
    for deneme in range(1, 4):
        try:
            mumlar = client.futures_klines(
                symbol=config.SYMBOL,
                interval=Client.KLINE_INTERVAL_1MINUTE,
                limit=100
            )
            df = pd.DataFrame(mumlar, columns=[
                "zaman","acilis","yuksek","dusuk","kapanis",
                "hacim","kapanis_zamani","quote_hacim","islem_sayisi",
                "taker_al","taker_sat","ignore"
            ])
            for s in ["acilis","yuksek","dusuk","kapanis","hacim"]:
                df[s] = df[s].astype(float)

            close  = df["kapanis"]
            high   = df["yuksek"]
            low    = df["dusuk"]
            volume = df["hacim"]

            guncel = round(float(close.iloc[-1]), 2)
            onceki = round(float(close.iloc[-2]), 2)
            degisim = round(((guncel - onceki) / onceki) * 100, 3)

            atr = round(float((high - low).rolling(14).mean().iloc[-1]), 2)

            hacim_ort = round(float(volume.rolling(20).mean().iloc[-1]), 2)
            son_hacim = round(float(volume.iloc[-1]), 2)

            direnc = round(float(high.iloc[:-1].tail(20).max()), 2)
            destek = round(float(low.iloc[:-1].tail(20).min()), 2)

            hacim_teyit = son_hacim > hacim_ort * 1.2

            if df["yuksek"].iloc[-1] > direnc and hacim_teyit:
                breakout = "YUKARI"
            elif df["dusuk"].iloc[-1] < destek and hacim_teyit:
                breakout = "ASAGI"
            else:
                breakout = "YOK"

            return KisaVeri(
                fiyat=guncel,
                degisim_pct=degisim,
                yuksek=round(float(high.iloc[-1]), 2),
                dusuk=round(float(low.iloc[-1]), 2),
                direnc=direnc,
                destek=destek,
                atr=atr,
                hacim=son_hacim,
                hacim_ort=hacim_ort,
                hacim_teyit=hacim_teyit,
                breakout=breakout,
                son_5_kapanis=[round(x, 2) for x in close.tail(5).tolist()],
            )

        except Exception as e:
            son_hata = e
            print(f"[Retry {deneme}/3] kisa_vadeli_veri: {e}")
            if deneme < 3:
                time.sleep(5)

    bildir_hata(f"data_agent kısa veri alınamadı (3 deneme): {son_hata}")
    return KisaVeri.hata(son_hata)


def uzun_vadeli_veri() -> UzunVeri:
    """
    Uzun vadeli bot için 15 dakikalık mum verisi.
    RSI + MACD + Bollinger stratejisi.
    """
    client = get_client()
    senkronize_et(client)

    son_hata = None
    for deneme in range(1, 4):
        try:
            mumlar = client.futures_klines(
                symbol=config.SYMBOL,
                interval=Client.KLINE_INTERVAL_15MINUTE,
                limit=100
            )
            df = pd.DataFrame(mumlar, columns=[
                "zaman","acilis","yuksek","dusuk","kapanis",
                "hacim","kapanis_zamani","quote_hacim","islem_sayisi",
                "taker_al","taker_sat","ignore"
            ])
            for s in ["acilis","yuksek","dusuk","kapanis","hacim"]:
                df[s] = df[s].astype(float)

            close = df["kapanis"]
            guncel = round(float(close.iloc[-1]), 2)
            onceki = round(float(close.iloc[-2]), 2)
            degisim = round(((guncel - onceki) / onceki) * 100, 3)

            rsi = hesapla_rsi(close)
            macd, sinyal = hesapla_macd(close)
            bb_ust, bb_ort, bb_alt = hesapla_bollinger(close)
            ma20 = close.rolling(20).mean().iloc[-1]
            ma50 = close.rolling(50).mean().iloc[-1]
            atr  = (df["yuksek"] - df["dusuk"]).rolling(14).mean().iloc[-1]

            rsi_son = round(float(rsi.iloc[-1]), 2)
            if rsi_son < config.RSI_ASIRI_SATIS:
                rsi_yorum = "ASIRI_SATILMIS"
            elif rsi_son > config.RSI_ASIRI_ALIS:
                rsi_yorum = "ASIRI_ALINMIS"
            else:
                rsi_yorum = "NOTR"

            return UzunVeri(
                fiyat=guncel,
                degisim_pct=degisim,
                rsi=rsi_son,
                rsi_yorum=rsi_yorum,
                macd=round(float(macd.iloc[-1]), 4),
                macd_sinyal=round(float(sinyal.iloc[-1]), 4),
                macd_hist=round(float((macd - sinyal).iloc[-1]), 4),
                ma20=round(float(ma20), 2),
                ma50=round(float(ma50), 2),
                bb_ust=round(float(bb_ust.iloc[-1]), 2),
                bb_alt=round(float(bb_alt.iloc[-1]), 2),
                atr=round(float(atr), 2),
                trend="YUKARI" if ma20 > ma50 else "ASAGI",
                son_5_kapanis=[round(x, 2) for x in close.tail(5).tolist()],
            )

        except Exception as e:
            son_hata = e
            print(f"[Retry {deneme}/3] uzun_vadeli_veri: {e}")
            if deneme < 3:
                time.sleep(5)

    bildir_hata(f"data_agent uzun veri alınamadı (3 deneme): {son_hata}")
    return UzunVeri.hata(son_hata)


# Geriye uyumluluk için eski fonksiyon
def calistir() -> UzunVeri:
    return uzun_vadeli_veri()


if __name__ == "__main__":
    import json
    print("=== KISA VADELİ VERİ (1m) ===")
    print(json.dumps(kisa_vadeli_veri().sozluk(), indent=2, ensure_ascii=False))

    print("\n=== UZUN VADELİ VERİ (15m) ===")
    print(json.dumps(uzun_vadeli_veri().sozluk(), indent=2, ensure_ascii=False))
