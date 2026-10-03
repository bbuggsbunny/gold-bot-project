# Altın Trading Botu — XAUUSDT / Binance Futures

Binance Futures üzerinde **XAUUSDT (Altın/Dolar)** işlemi yapan, çok ajanlı otomatik
trading botu. Haber sentimenti, makroekonomik veriler ve ekonomik takvimi Claude AI ile
birleştirip al/sat/bekle kararı üretir.

> ⚠️ **Uyarı:** Bu depo kişisel bir araştırma/öğrenme projesidir. Yatırım tavsiyesi değildir.
> Kaldıraçlı futures işlemi sermayenin tamamını kaybetmeye yol açabilir. `TESTNET=True`
> ile başlayın.

## Mimari

İki katmanlı karar sistemi, tek zamanlayıcı üzerinde:

| Katman | Periyot | Strateji | Kaldıraç |
|--------|---------|----------|----------|
| Kısa vadeli | 1 dk | Breakout (ATR SL×1 / TP×3) | 10x |
| Makro | 15 dk | DXY / VIX / TNX / SP500 skoru | — |
| Takvim | 1 saat | investing.com ekonomik takvim | — |
| Uzun vadeli | 4 saat | Swing (RSI / MACD / BB) | 3x |

### Ajanlar

| Ajan | Dosya | Görevi |
|------|-------|--------|
| data_agent | `agents/data_agent.py` | Binance'den 1m/15m mum verisi çeker |
| technical_agent | `agents/technical_agent.py` | Claude ile teknik sinyal üretir |
| risk_agent | `agents/risk_agent.py` | Claude ile risk değerlendirir |
| decision_agent | `agents/decision_agent.py` | Claude ile nihai al/sat/bekle kararı |
| order_agent | `agents/order_agent.py` | Binance Futures'a emir gönderir |
| news_agent | `agents/news_agent.py` | RSS → FinBERT → (etki ≥ 9 ise Claude) |
| finbert_agent | `agents/finbert_agent.py` | Yerel FinBERT sentiment analizi |
| macro_agent | `agents/macro_agent.py` | Makro skoru |
| calendar_agent | `agents/calendar_agent.py` | Ekonomik takvim |
| telegram_agent | `agents/telegram_agent.py` | Telegram bildirimleri |

Tüm ajanlar `tipler.py` içindeki dataclass sözleşmeleri üzerinden konuşur.

## Kurulum

```bash
git clone <bu-depo>
cd gold-bot-project
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # anahtarlarını .env içine yaz
```

FinBERT ayrı bir ortamda çalışır (`transformers`/`torch` Python 3.14'ü desteklemiyor):

```bash
python3.12 -m venv finbert-env && finbert-env/bin/pip install transformers torch
```

## Çalıştırma

Ağ ve ücret gerektirmeyen uçtan uca duman testi:

```bash
python testler/duman_testi.py
```

Gerçek API'lerle ön kontrol (emir göndermez):

```bash
python testler/canli_kontrol.py
```

Botu başlat:

```bash
python main.py
```

Karar kaydı raporu:

```bash
python testler/rapor.py
```

## Backtest

17 yıllık M1 verisi (2009–2025) üzerinde uzun vadeli strateji:

```bash
python backtest/veri_yukle.py        # histdata CSV'lerini birleştirir
python backtest/histdata_backtest.py
```

Ham veri dosyaları (`backtest/veri/`, ~670 MB) depoya dahil değil —
[histdata.com](https://www.histdata.com) üzerinden indirilir.

## Yapılandırma

Tüm strateji eşikleri, kaldıraçlar ve risk limitleri [config.py](config.py) içinde.
API anahtarları yalnızca `.env` dosyasından okunur, koda gömülmez.

## Belgeler

[PROJE.md](PROJE.md) — mimari, karar günlüğü, açık sorunlar ve geliştirme geçmişi.
