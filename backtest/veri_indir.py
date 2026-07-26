# backtest/veri_indir.py
# ─────────────────────────────────────────────
# Yahoo Finance'den altın verisi indirir ve
# diske kaydeder. Bir kez çalıştır, sonra
# hep diskten okur — internet bağlantısı gerekmez.
# ─────────────────────────────────────────────

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yfinance as yf
import pandas as pd
from datetime import datetime

VERI_KLASOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "veri")


def indir(aralik="1h", baslangic="2019-01-01", bitis=None):
    """
    Altın verisini indir ve kaydet.

    aralik: 1m, 5m, 15m, 1h, 4h, 1d
    baslangic: YYYY-MM-DD formatında
    bitis: None ise bugün

    NOT: Yahoo Finance 1 saatlik veriyi max 2 yıl verir.
    Günlük veri için 20 yıla kadar gidebilir.
    """
    os.makedirs(VERI_KLASOR, exist_ok=True)

    if bitis is None:
        bitis = datetime.now().strftime("%Y-%m-%d")

    print(f"İndiriliyor: GC=F | {aralik} | {baslangic} → {bitis}")

    # GC=F = Altın futures (Yahoo Finance sembolü)
    ticker = yf.Ticker("GC=F")
    df = ticker.history(
        start=baslangic,
        end=bitis,
        interval=aralik
    )

    if df.empty:
        print("HATA: Veri gelmedi. Tarih aralığını kontrol et.")
        return None

    # Sütun isimlerini küçük harfe çevir
    df.columns = [c.lower() for c in df.columns]
    df.index.name = "tarih"

    # Dosya adı
    dosya = os.path.join(VERI_KLASOR, f"altin_{aralik}_{baslangic[:4]}.csv")
    df.to_csv(dosya)

    print(f"Kaydedildi: {dosya}")
    print(f"Toplam mum: {len(df)}")
    print(f"İlk tarih : {df.index[0]}")
    print(f"Son tarih : {df.index[-1]}")
    print(f"Fiyat aralığı: ${df['low'].min():.2f} - ${df['high'].max():.2f}")

    return df


def yukle(aralik="1h", yil="2023"):
    """Daha önce kaydedilmiş veriyi diskten yükle"""
    dosya = os.path.join(VERI_KLASOR, f"altin_{aralik}_{yil}.csv")

    if not os.path.exists(dosya):
        print(f"Dosya bulunamadı: {dosya}")
        print("Önce veri_indir.indir() çalıştır.")
        return None

    df = pd.read_csv(dosya, index_col="tarih", parse_dates=True)
    print(f"Yüklendi: {dosya} ({len(df)} mum)")
    return df


if __name__ == "__main__":
    print("=== VERİ İNDİRME ===\n")

    # 1 saatlik veri — son 2 yıl (Yahoo Finance limiti)
    print("1. Saatlik veri (kısa vadeli backtest için):")
    df_1h = indir(aralik="1h", baslangic="2023-01-01")

    print("\n2. Günlük veri (uzun vadeli backtest için):")
    df_1d = indir(aralik="1d", baslangic="2004-01-01")

    if df_1h is not None and df_1d is not None:
        print("\n✓ Tüm veriler indirildi. Backtest'e hazır.")


def indir_saatlik():
    """Son 720 günlük saatlik veriyi indir"""
    os.makedirs(VERI_KLASOR, exist_ok=True)
    print("Saatlik veri indiriliyor (son 720 gün)...")
    ticker = yf.Ticker("GC=F")
    df = ticker.history(period="720d", interval="1h")
    if df.empty:
        print("HATA: Veri gelmedi.")
        return None
    df.columns = [c.lower() for c in df.columns]
    df.index.name = "tarih"
    dosya = os.path.join(VERI_KLASOR, "altin_1h_2024.csv")
    df.to_csv(dosya)
    print(f"Kaydedildi: {dosya}")
    print(f"Toplam mum: {len(df)}")
    print(f"İlk tarih : {df.index[0]}")
    print(f"Son tarih : {df.index[-1]}")
    return df
