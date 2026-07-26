"""
gostergeler.py
──────────────
Teknik gösterge hesaplamalarının tek kaynağı (canlı bot yolu).

Önceden RSI dört ayrı dosyada, üçü farklı formülle yazılmıştı:
  agents/data_agent.py              EWM (Wilder benzeri)
  backtest/motor.py                 EWM — aynı
  backtest/haber_uzun_backtest.py   rolling ortalama — FARKLI
  backtest/ml_veri/ozellik_olustur.py  rolling ortalama — FARKLI

Bu modül canlı yolu (data_agent) tek formüle bağlar. Backtest tarafındaki
kopyalar şimdilik yerinde bırakıldı: formüller birebir aynı olmadığı için
birleştirmek yayınlanmış backtest sonuçlarını değiştirir. Backtest turunda
ele alınacak (PROJE.md Bölüm 12, Sorun 6 ile birlikte).

ATR NOTU
    hesapla_atr() gerçek ATR değil — fiyat boşluklarını (gap) yok sayan
    (high − low) ortalaması. Canlı bot bugüne kadar bunu kullandığı için
    davranış korundu. Gerçek ATR'ye geçiş SL/TP mesafelerini değiştirir,
    bu yüzden ayrı bir karar olarak bekliyor.
"""
import pandas as pd


def hesapla_rsi(close: pd.Series, periyot: int = 14) -> pd.Series:
    """RSI — üstel ağırlıklı (Wilder) kazanç/kayıp ortalamasıyla."""
    delta = close.diff()
    kazan = delta.clip(lower=0).ewm(com=periyot - 1, min_periods=periyot).mean()
    kayip = (-delta.clip(upper=0)).ewm(com=periyot - 1, min_periods=periyot).mean()
    rs    = kazan / kayip.replace(0, float("inf"))
    return 100 - (100 / (1 + rs))


def hesapla_macd(close: pd.Series) -> tuple[pd.Series, pd.Series]:
    """MACD (12/26) ve sinyal çizgisi (9). Dönüş: (macd, sinyal)"""
    ema12  = close.ewm(span=12, adjust=False).mean()
    ema26  = close.ewm(span=26, adjust=False).mean()
    macd   = ema12 - ema26
    sinyal = macd.ewm(span=9, adjust=False).mean()
    return macd, sinyal


def hesapla_bollinger(close: pd.Series, periyot: int = 20,
                      std: float = 2) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Bollinger bantları. Dönüş: (üst, orta, alt)"""
    ort   = close.rolling(periyot).mean()
    sapma = close.rolling(periyot).std()
    return ort + (sapma * std), ort, ort - (sapma * std)


def hesapla_atr(high: pd.Series, low: pd.Series, periyot: int = 14) -> pd.Series:
    """
    Ortalama mum aralığı — (high − low) ortalaması.

    DİKKAT: Bu gerçek ATR değil; True Range fiyat boşluklarını da hesaba
    katar. Canlı botun bugüne kadarki davranışı korunsun diye bu haliyle
    duruyor (modül başlığındaki ATR notuna bakın).
    """
    return (high - low).rolling(periyot).mean()
