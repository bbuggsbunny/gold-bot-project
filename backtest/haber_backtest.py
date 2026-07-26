"""
backtest/haber_backtest.py
──────────────────────────
Son 1 saatlik 5 dakikalık veriyle canlı ajan entegrasyonu backtesti.
Makro + takvim + haber bağlamıyla her mumda karar verir,
ATR x1 SL / ATR x3 TP ile hipotetik K/Z hesaplar.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from binance.client import Client
from datetime import datetime

import config
from tipler import KisaVeri
from gostergeler import hesapla_rsi, hesapla_macd, hesapla_bollinger
from agents import technical_agent, risk_agent, decision_agent
from agents.macro_agent import calistir as macro_calistir
from agents.calendar_agent import calistir as takvim_calistir
from agents.news_agent import calistir as haber_calistir

# Breakout penceresi için ekstra mum (20 lookback + 12 test = 32)
LOOKBACK   = 20
TEST_MUMLAR = 12   # son 1 saat


# ──────────────────────────────────────────
# Yardımcılar
# ──────────────────────────────────────────
def _veri_cek() -> pd.DataFrame:
    client = Client(
        config.BINANCE_API_KEY,
        config.BINANCE_SECRET_KEY,
        testnet=config.TESTNET,
    )
    mumlar = client.futures_klines(
        symbol=config.SYMBOL,
        interval=Client.KLINE_INTERVAL_5MINUTE,
        limit=LOOKBACK + TEST_MUMLAR,
    )
    df = pd.DataFrame(mumlar, columns=[
        "zaman", "acilis", "yuksek", "dusuk", "kapanis",
        "hacim", "kapanis_zamani", "quote_hacim", "islem_sayisi",
        "taker_al", "taker_sat", "ignore",
    ])
    for s in ["acilis", "yuksek", "dusuk", "kapanis", "hacim"]:
        df[s] = df[s].astype(float)
    df["zaman"] = pd.to_datetime(df["zaman"], unit="ms")
    return df.reset_index(drop=True)


def _teknik_dict(df: pd.DataFrame, idx: int) -> KisaVeri:
    """idx'e kadar (dahil) olan veriyle kısa vadeli teknik veri üretir."""
    pencere = df.iloc[: idx + 1].copy()
    close  = pencere["kapanis"]
    high   = pencere["yuksek"]
    low    = pencere["dusuk"]
    volume = pencere["hacim"]

    atr       = round(float((high - low).rolling(14).mean().iloc[-1]), 2)
    hacim_ort = round(float(volume.rolling(20).mean().iloc[-1]), 2)
    son_hacim = round(float(volume.iloc[-1]), 2)

    # Breakout seviyeleri: son 20 mum (son mum hariç)
    direnc = round(float(high.iloc[:-1].tail(LOOKBACK).max()), 2)
    destek = round(float(low.iloc[:-1].tail(LOOKBACK).min()), 2)

    hacim_teyit = son_hacim > hacim_ort * 1.2
    guncel = round(float(close.iloc[-1]), 2)
    onceki = round(float(close.iloc[-2]), 2)

    if high.iloc[-1] > direnc and hacim_teyit:
        breakout = "YUKARI"
    elif low.iloc[-1] < destek and hacim_teyit:
        breakout = "ASAGI"
    else:
        breakout = "YOK"

    return KisaVeri(
        fiyat=guncel,
        degisim_pct=round((guncel - onceki) / onceki * 100, 3),
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


def _kz_hesapla(df: pd.DataFrame, giris_idx: int, yon: str, atr: float) -> str:
    """Girişten sonraki mumları tarayarak SL/TP'nin hangisine çarpıldığını döndürür."""
    giris_fiyat = df["kapanis"].iloc[giris_idx]
    if yon == "AL":
        sl = round(giris_fiyat - atr * config.ATR_SL_CARPAN, 2)
        tp = round(giris_fiyat + atr * config.ATR_TP_CARPAN, 2)
    else:
        sl = round(giris_fiyat + atr * config.ATR_SL_CARPAN, 2)
        tp = round(giris_fiyat - atr * config.ATR_TP_CARPAN, 2)

    for i in range(giris_idx + 1, len(df)):
        h = df["yuksek"].iloc[i]
        l = df["dusuk"].iloc[i]
        if yon == "AL":
            if l <= sl:
                return f"ZARAR  (SL: {sl} | Giriş: {giris_fiyat:.2f})"
            if h >= tp:
                return f"KAR    (TP: {tp} | Giriş: {giris_fiyat:.2f})"
        else:
            if h >= sl:
                return f"ZARAR  (SL: {sl} | Giriş: {giris_fiyat:.2f})"
            if l <= tp:
                return f"KAR    (TP: {tp} | Giriş: {giris_fiyat:.2f})"

    return f"AÇIK   (Giriş: {giris_fiyat:.2f} | SL: {sl} | TP: {tp})"


# ──────────────────────────────────────────
# Ana backtest
# ──────────────────────────────────────────
def calistir():
    print("\n" + "═" * 60)
    print("  HABER + MAKRO + TAKVİM BACKTEST")
    print(f"  {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")
    print("═" * 60)

    # 1. Canlı veri
    print("\n[1/4] Binance'den 5dk veri çekiliyor...")
    df = _veri_cek()
    print(f"  Toplam mum: {len(df)} | Test penceresi: son {TEST_MUMLAR} mum")
    print(f"  Aralık: {df['zaman'].iloc[0].strftime('%H:%M')} → {df['zaman'].iloc[-1].strftime('%H:%M')}")

    # 2. Bağlam ajanları (bir kez çalışır)
    print("\n[2/4] Bağlam ajanları çalışıyor...")
    makro   = macro_calistir()
    takvim  = takvim_calistir()
    haberler = haber_calistir()

    print(f"  Makro  : {makro.yorum} (skor: {makro.skor:+.1f})")
    print(f"  Takvim : {takvim.mod}")
    print(f"  Haber  : {haberler.sentiment} | {haberler.ozet[:70]}...")

    # 3. Her mum için karar
    print(f"\n[3/4] {TEST_MUMLAR} mum analiz ediliyor...\n")
    print(f"  {'Zaman':<8} {'Fiyat':>8} {'Breakout':<9} {'Karar':<6} {'Güven':>5}  Sonuç")
    print("  " + "─" * 58)

    kararlar = {"AL": 0, "SAT": 0, "BEKLE": 0}
    islemler = []

    # Test mumları: LOOKBACK'ten sonraki 12 mum
    test_baslangic = LOOKBACK
    for i in range(test_baslangic, len(df)):
        teknik = _teknik_dict(df, i)
        zaman_str = df["zaman"].iloc[i].strftime("%H:%M")

        if teknik.breakout == "YOK":
            print(f"  {zaman_str:<8} {teknik.fiyat:>8.2f} {'YOK':<9} {'─':<6} {'─':>5}  (breakout yok)")
            kararlar["BEKLE"] += 1
            continue

        # Breakout var → tam ajan pipeline
        teknik_analiz = technical_agent.calistir(teknik)
        risk          = risk_agent.calistir(teknik, teknik_analiz, haberler)
        karar         = decision_agent.calistir(
            teknik, haberler, teknik_analiz, risk,
            makro=makro, takvim=takvim,
        )

        k      = karar.eylem
        guven  = karar.guven
        kararlar[k] += 1

        if karar.islem_var:
            sonuc = _kz_hesapla(df, i, k, teknik.atr)
            islemler.append({
                "zaman": zaman_str, "yon": k, "guven": guven, "sonuc": sonuc,
                "fiyat": teknik.fiyat, "atr": teknik.atr,
            })
            print(f"  {zaman_str:<8} {teknik.fiyat:>8.2f} {teknik.breakout:<9} {k:<6} {guven:>4}/10  {sonuc}")
        else:
            print(f"  {zaman_str:<8} {teknik.fiyat:>8.2f} {teknik.breakout:<9} {k:<6} {guven:>4}/10  ({karar.gerekce[:45]})")

    # 4. Özet rapor
    print("\n" + "═" * 60)
    print("  ÖZET RAPOR")
    print("═" * 60)
    print(f"\n  Bağlam Durumu:")
    print(f"    Makro Skoru : {makro.skor:+.1f}  →  {makro.yorum}")
    print(f"    Takvim Modu : {takvim.mod}")
    print(f"    Haber       : {haberler.sentiment}  —  {haberler.ozet[:60]}...")

    print(f"\n  Karar Dağılımı ({TEST_MUMLAR} mum):")
    print(f"    AL    : {kararlar['AL']}")
    print(f"    SAT   : {kararlar['SAT']}")
    print(f"    BEKLE : {kararlar['BEKLE']}")

    if islemler:
        kar   = sum(1 for t in islemler if "KAR"   in t["sonuc"])
        zarar = sum(1 for t in islemler if "ZARAR" in t["sonuc"])
        acik  = sum(1 for t in islemler if "AÇIK"  in t["sonuc"])
        print(f"\n  Hipotetik İşlem Sonuçları (ATR×{config.ATR_SL_CARPAN} SL | ATR×{config.ATR_TP_CARPAN} TP):")
        print(f"    Toplam işlem : {len(islemler)}")
        print(f"    Kar          : {kar}")
        print(f"    Zarar        : {zarar}")
        print(f"    Açık         : {acik}")
        if kar + zarar > 0:
            print(f"    Başarı oranı : %{kar / (kar + zarar) * 100:.1f}")
        for t in islemler:
            print(f"\n    [{t['zaman']}] {t['yon']} @ {t['fiyat']:.2f} | ATR:{t['atr']:.2f} | Güven:{t['guven']}")
            print(f"      → {t['sonuc']}")
    else:
        print(f"\n  Hipotetik işlem açılmadı (breakout yok veya tüm kararlar BEKLE).")

    print("\n" + "═" * 60)


if __name__ == "__main__":
    calistir()
