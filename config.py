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
QUANTITY  = 0.01        # Her emirde kaç gram altın (küçük tut!)
# Kaldıraç katmana göre seçilir → aşağıdaki KALDIRAC_KISA / KALDIRAC_UZUN

# ── Claude Modelleri ────────────────────────
# 2026-07-26: claude-sonnet-4-6 → claude-sonnet-5
MODEL_ANALIZ = "claude-sonnet-5"              # teknik / risk / karar ajanları
MODEL_HABER  = "claude-haiku-4-5-20251001"    # haber analizi (ucuz, yüksek hacim)

# ── Strateji Eşikleri ───────────────────────
MIN_GUVEN_SKORU = 6     # Claude bu skorun altında karar verirse emir gitmiyor
RSI_ASIRI_SATIS = 30    # RSI bu değerin altına düşerse "ucuz" sinyali
RSI_ASIRI_ALIS  = 70    # RSI bu değerin üstüne çıkarsa "pahalı" sinyali

# ── Döngü Ayarı ─────────────────────────────
# Döngü periyotları bot/dongu.py:zamanlayici() içinde sabit:
#   1 dk kısa vadeli | 15 dk makro | 60 dk takvim | 240 dk uzun vadeli
# (BEKLEME_DAKIKA sabiti 2026-07-26'da kaldırıldı — tanımlıydı ama
#  hiçbir yerde okunmuyordu.)

# ── Risk Yönetimi ────────────────────────────
MAX_STOP_LOSS_PCT    = 1.0   # Maksimum zarar: pozisyonun %1'i
MAX_TAKE_PROFIT_PCT  = 2.0   # Hedef kâr: pozisyonun %2'si
MAX_GUNLUK_ZARAR     = 75.0  # Günlük max zarar ($) — aşılınca o gün işlem durur

# Katman kaldıraçları — order_agent'a katmana göre iletilir
KALDIRAC_KISA  = 10   # Breakout botu (1 dk döngü)
KALDIRAC_UZUN  = 3    # Swing trader botu (4 saat döngü)

# Breakout ATR çarpanları
ATR_SL_CARPAN  = 1.0
ATR_TP_CARPAN  = 3.0
