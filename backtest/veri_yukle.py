"""
backtest/veri_yukle.py
──────────────────────
XAUUSD M1 Histdata yükleyici.
MetaTrader format: YYYY.MM.DD,HH:MM,open,high,low,close,volume (başlık satırı yok)
"""
import os
from typing import Optional

import pandas as pd

HISTDATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "veri", "histdata")
_SUTUNLAR = ["_tarih", "_saat", "open", "high", "low", "close", "volume"]


def yukle_yil(yil: int, zaman_aralik: Optional[str] = "15min") -> pd.DataFrame:
    """
    Belirtilen yılın M1 histdata CSV'sini yükle ve isteğe bağlı yeniden örnekle.

    Parameters
    ----------
    yil          : 2009..2025
    zaman_aralik : '1min', '15min', '1h', '1D', veya None (1dk ham)

    Returns
    -------
    pd.DataFrame — datetime index, sütunlar: open/high/low/close/volume
    """
    dosya = os.path.join(HISTDATA_DIR, f"DAT_MT_XAUUSD_M1_{yil}.csv")
    if not os.path.exists(dosya):
        raise FileNotFoundError(f"Dosya bulunamadı: {dosya}")

    df = pd.read_csv(
        dosya,
        header=None,
        names=_SUTUNLAR,
        dtype={
            "_tarih": str, "_saat": str,
            "open": float, "high": float, "low": float,
            "close": float, "volume": float,
        },
    )

    df.index = pd.to_datetime(
        df["_tarih"] + " " + df["_saat"], format="%Y.%m.%d %H:%M"
    )
    df.index.name = "tarih"
    df = df.drop(columns=["_tarih", "_saat"]).sort_index()

    if zaman_aralik and zaman_aralik != "1min":
        df = (
            df.resample(zaman_aralik)
            .agg({"open": "first", "high": "max", "low": "min",
                  "close": "last", "volume": "sum"})
            .dropna(subset=["close"])
        )

    return df


def yukle_aralik(
    baslangic: int = 2009,
    bitis: int = 2025,
    zaman_aralik: Optional[str] = "15min",
    sessiz: bool = False,
) -> pd.DataFrame:
    """
    Belirtilen yıl aralığındaki tüm dosyaları birleştirip tek DataFrame döner.
    Yıl yıl yükleyerek belleği verimli kullanır.

    Returns
    -------
    pd.DataFrame — datetime index, sütunlar: open/high/low/close/volume
    """
    parcalar = []
    for yil in range(baslangic, bitis + 1):
        try:
            df_yil = yukle_yil(yil, zaman_aralik)
            parcalar.append(df_yil)
            if not sessiz:
                aralik_str = zaman_aralik or "1dk"
                print(f"  {yil}: {len(df_yil):>7,} mum [{aralik_str}] "
                      f"| {df_yil.index[0].date()} → {df_yil.index[-1].date()}")
        except FileNotFoundError as e:
            if not sessiz:
                print(f"  {yil}: ATLAIDI — {e}")

    if not parcalar:
        raise ValueError("Hiç veri yüklenemedi — histdata dizinini kontrol et.")

    return pd.concat(parcalar).sort_index()


if __name__ == "__main__":
    print("Veri yükleme testi (15dk örnekleme):")
    for test_yil in [2009, 2015, 2020, 2025]:
        try:
            df = yukle_yil(test_yil)
            print(f"  {test_yil}: {len(df):>7,} mum | "
                  f"{df.index[0].date()} → {df.index[-1].date()} | "
                  f"Fiyat aralığı: ${df['close'].min():.0f}–${df['close'].max():.0f}")
        except FileNotFoundError as e:
            print(f"  {test_yil}: {e}")
