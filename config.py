# config.py
# ─────────────────────────────────────────────
# Botun tüm ayarları burada. Değiştirmek istediğin
# bir şey varsa sadece bu dosyaya gel.
# ─────────────────────────────────────────────

import os
from dotenv import load_dotenv

# .env dosyasını oku ve ortam değişkenlerine yükle
load_dotenv()

# ── API Anahtarları ──────────────────────────
ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY")
BINANCE_API_KEY    = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")
TESTNET            = os.getenv("TESTNET", "True") == "True"

# ── İşlem Ayarları ──────────────────────────
SYMBOL    = "XAUUSDT"   # Altın/Dolar paritesi
LEVERAGE  = 5           # Kaldıraç: 5x (100$ ile 500$'lık pozisyon)
QUANTITY  = 0.01        # Her emirde kaç gram altın (küçük tut!)

# ── Strateji Eşikleri ───────────────────────
MIN_GUVEN_SKORU = 6     # Claude bu skorun altında karar verirse emir gitmiyor
RSI_ASIRI_SATIS = 30    # RSI bu değerin altına düşerse "ucuz" sinyali
RSI_ASIRI_ALIS  = 70    # RSI bu değerin üstüne çıkarsa "pahalı" sinyali

# ── Döngü Ayarı ─────────────────────────────
BEKLEME_DAKIKA = 15     # Bot kaç dakikada bir analiz yapsın

# ── Risk Yönetimi ────────────────────────────
MAX_STOP_LOSS_PCT    = 1.0   # Maksimum zarar: pozisyonun %1'i
MAX_TAKE_PROFIT_PCT  = 2.0   # Hedef kâr: pozisyonun %2'si
MAX_GUNLUK_ZARAR     = 75.0  # Günlük max zarar ($) — aşılınca o gün işlem durur

# Kısa vadeli bot ayarları
KALDIRAC_KISA  = 10   # Breakout botu
KALDIRAC_UZUN  = 3    # Swing trader botu

# Breakout ATR çarpanları
ATR_SL_CARPAN  = 1.0
ATR_TP_CARPAN  = 3.0
