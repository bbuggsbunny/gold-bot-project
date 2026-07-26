# ALTIN TRADİNG BOTU — TAM PROJE DOKÜMANTASYONU

> **Son güncelleme:** 26 Temmuz 2026 (rev 4 — git sürüm kontrolü kuruldu)  
> **Platform:** Fedora Linux | Python 3.14.4 (gold-bot venv) + Python 3.12.13 (finbert-env)  
> **Durum:** Testnet aktif — ML modeli geliştirme aşamasında

---

## 1. PROJE AMACI

### Ne yapmak istiyoruz

Binance Futures üzerinde XAUUSDT (Altın/Dolar futures) işlemi yapan, tamamen otomatik, çok ajanlı bir AI trading botu. Sistem anlık haber sentimentini, makroekonomik verileri ve ekonomik takvim bilgisini gerçek zamanlı olarak entegre edip Claude AI ile karar üretiyor.

### Hedef kar/risk oranı

| Parametre | Hedef |
|-----------|-------|
| TP/SL oranı | 2:1 (kısa vadeli ATR×3 / ATR×1) |
| Minimum başarı oranı | %40 (2:1 oran ile kârlı olmak için yeterli) |
| Hedef aylık getiri | >%5 (testnet) |
| Max kabul edilebilir drawdown | %15 |
| API maliyetini karşılamak için min kâr | ~$15/ay |

### Kısa vadeli hedefler (1-2 ay)

- Testnet'te 2 hafta kesintisiz çalıştır, kârlılığını doğrula
- FinBERT etiketi altın için kalibre et
- Günlük P&L takip sistemi kur
- Telegram günlük özet otomasyonu ekle

### Uzun vadeli hedefler (3-6 ay)

- Gerçek paraya geçiş ($100 başlangıç sermayesi)
- Makine öğrenmesi modeli entegrasyonu
- Gerçek tarihsel haber verisi API entegrasyonu
- Portföy çeşitlendirmesi (diğer emtialar)

---

## 2. SİSTEM MİMARİSİ

### Tüm ajanların listesi ve görevleri

| Ajan | Dosya | Görevi |
|------|-------|--------|
| data_agent | `agents/data_agent.py` | Binance'den 1m/15m mum verisi çeker |
| technical_agent | `agents/technical_agent.py` | Claude ile teknik sinyal üretir |
| risk_agent | `agents/risk_agent.py` | Claude ile risk değerlendirir |
| decision_agent | `agents/decision_agent.py` | Claude ile nihai al/sat/bekle kararı |
| order_agent | `agents/order_agent.py` | Binance Futures'a emir gönderir |
| news_agent | `agents/news_agent.py` | RSS → FinBERT → (etki≥9 ise Claude) |
| finbert_agent | `agents/finbert_agent.py` | Yerel FinBERT sentiment analizi |
| macro_agent | `agents/macro_agent.py` | DXY/VIX/TNX/SP500 makro skoru |
| calendar_agent | `agents/calendar_agent.py` | investing.com ekonomik takvim |
| telegram_agent | `agents/telegram_agent.py` | Telegram Bot bildirimleri |
| utils | `agents/utils.py` | Binance zaman senkronizasyonu |

### Ajanlar arası veri akışı

```
[news_agent] ──────────────────────────────────────────┐
  RSS → FinBERT → (kritikse Claude Haiku)               │
  Çıktı: {sentiment, haber_skoru, ozet, son_haberler}   │
                                                         │
[macro_agent] ─────────────────────────────────────────┤
  yfinance (DXY/VIX/TNX/SP500)                          │
  Çıktı: {skor, yorum, dxy/vix/tnx/sp500_degisim}       │
                                                         ▼
[calendar_agent] ──────────────────►  [_baglam_olustur()]
  investing.com POST API                  (main.py)
  Çıktı: {mod, yaklasan, aciklanan}      haberler + makro + takvim
                                          tek dict olarak aşağıya
[data_agent]                              ▼
  Binance 1m/15m mumlar          [technical_agent]
  Çıktı: {fiyat, breakout,   ──►   Claude Sonnet
          RSI, MACD, ATR}          Çıktı: {sinyal, sl, tp, yorum}
                                          ▼
                                   [risk_agent]
                                     Claude Sonnet
                                     Çıktı: {risk, onay, max_poz}
                                          ▼
                                   [decision_agent]
                                     Claude Sonnet
                                     Çıktı: {karar, guven, sl_pct, tp_pct}
                                          ▼
                              guven≥6 ve karar≠BEKLE ise
                                   [order_agent]
                                     Binance Futures
                                     Market + SL + TP emirleri
                                          ▼
                                   [telegram_agent]
                                     Bildirim gönder
```

### İki katmanlı bot yapısı

```
ANA DÖNGÜ (main.py, time.sleep(60)):
┌────────────────────────────────────────────────────────────┐
│ dongu_sayaci % 15 == 0  →  macro_agent güncelle            │
│ dongu_sayaci % 60 == 0  →  calendar_agent güncelle         │
│ dongu_sayaci % 240 == 0 →  UZUN VADELİ DÖNGÜ              │
│                              + haber_guncelle()             │
│ diğer (her dakika)      →  RSS kontrol + KISA VADELİ DÖNGÜ │
└────────────────────────────────────────────────────────────┘

KISA VADELİ DÖNGÜ (kisa_vadeli_dongu):
  Takvim guard → data_agent (1m) → breakout var mı?
    YOK → erken çık (0 Claude çağrısı)
    VAR → technical → risk → decision → order → telegram

UZUN VADELİ DÖNGÜ (uzun_vadeli_dongu, 4 saatte bir):
  Takvim guard → data_agent (15m) → technical → risk → decision → order → telegram
```

### Karar verme akışı adım adım

1. `takvim_mod == YUKSEK_RISK` → **BEKLE** (Claude çağrısı olmaz)
2. `takvim_mod == DIKKATLI` → `min_guven = 8` set edilir
3. `risk_agent` → `onay == HAYIR` → **BEKLE** (Claude çağrısı olmaz)
4. Claude Sonnet prompt'a gönderilir: fiyat + makro + haber + teknik + risk raporları
5. Claude JSON döner: `{karar, guven, stop_loss_pct, take_profit_pct, gerekce}`
6. **Ağırlıklı karar sistemi:**
   - `makro_yon == haber_yon ≠ NOTR` VE `teknik_yon == makro_yon` → `guven += 2`
   - `makro_yon == haber_yon ≠ NOTR` VE `teknik_yon` zıt → karar = BEKLE
7. `guven < min_guven` → karar = BEKLE
8. Karar AL/SAT ise → `order_agent` → Binance emir

---

## 3. DOSYA YAPISI

```
~/gold-bot-project/
├── main.py                     # Ana döngü — 2 katman + 3 bağlam ajan
├── config.py                   # Tüm sabitler, API anahtarları (env'den)
├── .env                        # Gizli anahtarlar (git'e eklenmez)
├── .gitignore                  # ★ Takip dışı: .env, veri/, features.csv, *.pkl, *.png
├── PROJE.md                    # Bu dosya
│
├── agents/
│   ├── __init__.py
│   ├── data_agent.py           # Binance veri çekimi
│   ├── technical_agent.py      # Claude Sonnet teknik analiz
│   ├── risk_agent.py           # Claude Sonnet risk değerlendirme
│   ├── decision_agent.py       # Claude Sonnet nihai karar
│   ├── order_agent.py          # Binance Futures emir gönderimi
│   ├── news_agent.py           # RSS + FinBERT + Claude haber analizi
│   ├── finbert_agent.py        # FinBERT yerel sentiment (Python 3.12)
│   ├── macro_agent.py          # DXY/VIX/TNX/SP500 makro skor
│   ├── calendar_agent.py       # investing.com ekonomik takvim
│   ├── telegram_agent.py       # Telegram Bot bildirimleri
│   └── utils.py                # senkronize_et() zaman senkronu
│
└── backtest/
    ├── __init__.py
    ├── motor.py                 # RSI/MACD/BB kural tabanlı backtest motoru
    │                            #   → calistir(dosya, ...)      : CSV'den backtest + grafik
    │                            #   → calistir_df(df, ...)      : DataFrame'den backtest (grafik yok)
    ├── strateji_breakout.py     # ATR tabanlı breakout backtest
    ├── haber_backtest.py        # 1 saatlik canlı ajan backtesti (5m mumlar)
    ├── haber_uzun_backtest.py   # 30 günlük haber+makro+takvim backtesti (15m)
    ├── histdata_backtest.py     # ★ 17 yıllık M1 histdata backtesti (2009–2025)
    ├── veri_yukle.py            # ★ M1 histdata yükleyici (yukle_yil / yukle_aralik)
    ├── veri_indir.py            # yfinance ile CSV veri indirici
    ├── haber_gecmis.json        # Günlük Claude haber önbelleği (kalıcı)
    ├── haber_uzun_backtest.png  # Son 30 gün backtest grafik çıktısı
    ├── veri/
    │   ├── altin_5m_2026.csv   # 5dk mum: 09.03–18.05.2026, 13.560 satır
    │   ├── altin_15m_2026.csv  # 15dk mum: 09.03–18.05.2026, 4.529 satır
    │   ├── altin_1d_2004.csv   # Günlük mum: 2004'ten günümüze (trend filtresi)
    │   └── histdata/           # ★ MetaTrader M1 ham veri (2009–2025)
    │       ├── DAT_MT_XAUUSD_M1_2009.csv   # 276k satır
    │       ├── ...
    │       └── DAT_MT_XAUUSD_M1_2025.csv   # 354k satır
    ├── ml_veri/                 # ★ ML model geliştirme (2026-05-20'den itibaren)
    │   ├── ozellik_olustur.py  # 17 yıl → 15dk mumlar → features.csv (12 özellik)
    │   ├── model_egit.py       # XGBoost eğitimi; 2009–2022 train, 2023–2025 test
    │   ├── features.csv        # 396.254 satır, 12 özellik + hedef (±0.3% / 4 saat)
    │   └── model.pkl           # Eğitilmiş model + LabelEncoder + özellik listesi + eşik
    └── sonuclar/               # Backtest grafik PNG'leri ve CSV çıktıları
        ├── 17yil_2009_2025_RSI_MACD_BB_3x_kaldirac.png   # ★ 17 yıl grafik
        └── 17yil_2009_2025_islemler_1691_adet.csv        # ★ 17 yıl işlem listesi
```

### Dosyalar arası bağımlılıklar

```
main.py
  → agents/data_agent.py
  → agents/news_agent.py → agents/finbert_agent.py (subprocess)
  → agents/technical_agent.py
  → agents/risk_agent.py
  → agents/decision_agent.py
  → agents/order_agent.py → agents/utils.py
  → agents/macro_agent.py
  → agents/calendar_agent.py
  → agents/telegram_agent.py
  → config.py (tüm ajanlar)
```

---

## 4. AJAN DETAYLARI

### 4.1 data_agent.py

**Görevi:** Binance Futures'tan XAUUSDT fiyat verisi çekmek ve teknik göstergeleri hesaplamak.

**Önemli fonksiyonlar:**
- `hesapla_rsi(close, periyot=14)` — EWM tabanlı RSI
- `hesapla_macd(close)` — EMA(12/26/9) MACD
- `hesapla_bollinger(close, periyot=20, std=2)` — BB bantları
- `kisa_vadeli_veri()` — 1 dakikalık mum (limit=100)
- `uzun_vadeli_veri()` — 15 dakikalık mum (limit=100)
- `get_client()` — Binance client factory

**Girdi:** Yok (config'den Binance bağlantı bilgilerini alır)

**Çıktı kısa:**
```python
{"durum":"ok","mod":"kisa","fiyat":4544.54,"degisim_pct":-0.038,
 "yuksek":4545.0,"dusuk":4543.0,"direnc":4560.0,"destek":4530.0,
 "atr":12.5,"hacim":150.0,"hacim_ort":120.0,"hacim_teyit":True,
 "breakout":"YOK"|"YUKARI"|"ASAGI","son_5_kapanis":[...]}
```

**Çıktı uzun:**
```python
{"durum":"ok","mod":"uzun","fiyat":4544.54,"degisim_pct":-0.038,
 "rsi":44.38,"rsi_yorum":"NOTR","macd":-0.2354,"macd_sinyal":0.3983,
 "macd_hist":-0.6337,"ma20":4539.76,"ma50":4537.70,"bb_ust":4560.0,
 "bb_alt":4520.0,"atr":12.5,"trend":"ASAGI","son_5_kapanis":[...]}
```

**API/Kütüphane:** `python-binance 1.0.36`, testnet=True

**Parametreler:**
- 1m limit=100 mum → son 100 dakika
- 15m limit=100 mum → son 25 saat
- Breakout: `high > direnc AND hacim > hacim_ort × 1.2`
- Direnç/destek: son 20 mumun high/low (son mum hariç)

**Retry/Güvenlik:**
- Her çağrıda `senkronize_et(client)` çalışır
- 3 deneme × 5 saniye bekleme
- 3'te de başarısız → `bildir_hata()` + hata dict döner

**Bilinen sorunlar:** Testnet bazen bağlantı düşürüyor, retry yeterli çözüm.

---

### 4.2 technical_agent.py

**Görevi:** Teknik veriyi analiz edip alım/satım sinyali üretmek.

**Önemli fonksiyonlar:**
- `calistir(teknik: dict) -> dict` — mod'a göre kısa veya uzun analiz

**Girdi:** `teknik` dict (data_agent çıktısı)

**Çıktı:**
```python
{"durum":"ok","mod":"kisa"|"uzun",
 "sinyal":"GUCLU_AL"|"ZAYIF_AL"|"NOTR"|"ZAYIF_SAT"|"GUCLU_SAT",
 "sl":4530.0,"tp":4580.0,"yorum":"tek cümle"}
```

**API:** Claude Sonnet 4.6 (`claude-sonnet-4-6`), max_tokens=150

**Kısa vadeli prompt:** Fiyat, yüksek/düşük, direnç/destek, ATR, hacim, breakout yönü

**Uzun vadeli prompt:** Fiyat, RSI, MACD, BB bantları, MA20/50, trend

**Bilinen sorunlar:** Claude bazen farklı formatta yanıt dönebiliyor, satır parse esnekliği var.

---

### 4.3 risk_agent.py

**Görevi:** İşlemin risk seviyesini değerlendirip onay/red vermek.

**Önemli fonksiyonlar:**
- `calistir(teknik, teknik_analiz, haberler) -> dict`

**Girdi:** teknik dict + teknik_analiz dict + haberler dict

**Çıktı:**
```python
{"durum":"ok","risk":"DUSUK"|"ORTA"|"YUKSEK"|"COK_YUKSEK",
 "onay":"EVET"|"HAYIR","max_pozisyon":0.01,"uyari":"tek cümle"}
```

**API:** Claude Sonnet 4.6, max_tokens=150

**Sistem promptu:** "Sen muhafazakar bir risk yöneticisisin. Şüphede HAYIR dersin."

**Kaldıraç bilgisi prompt'a gömülür:**
- Kısa vadeli mod → `KALDIRAC_KISA = 10`
- Uzun vadeli mod → `KALDIRAC_UZUN = 3`

**Bilinen sorunlar:** Çok muhafazakar davranıp çoğu sinyali engelleyebiliyor. Gerçek para testlerinde eşikler ayarlanabilir.

---

### 4.4 decision_agent.py

**Görevi:** Tüm ajanların raporlarını sentezleyip nihai karar vermek.

**Önemli fonksiyonlar:**
- `calistir(teknik, haberler, teknik_analiz, risk, makro=None, takvim=None) -> dict`
- `_yon(deger, tip)` — sentiment/makro/teknik → BULLISH/BEARISH/NOTR

**Girdi:** Tüm ajan çıktıları + makro dict + takvim dict

**Çıktı:**
```python
{"durum":"ok","karar":"AL"|"SAT"|"BEKLE",
 "guven":7,"stop_loss_pct":0.5,"take_profit_pct":1.0,"gerekce":"..."}
```

**API:** Claude Sonnet 4.6, max_tokens=200

**Karar akışı (öncelik sırasıyla):**
1. `takvim_mod == YUKSEK_RISK` → anında BEKLE
2. `takvim_mod == DIKKATLI` → min_guven=8
3. `risk.onay == HAYIR` → anında BEKLE
4. Claude çağrısı (`[decision_agent] PROMPT/HAM YANIT/PARSE SONUÇ` debug logları)
5. Ağırlıklı sistem:
   - makro+haber+teknik hizalı → `guven+2`
   - makro+haber aynı yön, teknik zıt, `abs(makro_skor) > 6` → `BEKLE, guven=0`
   - makro+haber aynı yön, teknik zıt, `abs(makro_skor) ≤ 6` → sadece gerekçeye not
6. `guven < min_guven` → BEKLE

**Düzeltilen bug (2026-05-20):** `makro_skor` -3 ile -8 arasıyken `makro_mesaj` "Makro nötr" yazıyor ama `_yon()` bunu BEARISH sayıyordu. Breakout AL + hafif BEARISH makro + BEARISH haber → `guven=0` zorla yazılıyordu. Düzeltme: (1) `makro_mesaj` artık ±3/±8 eşiğini doğru yansıtıyor ("Makro hafif BEARISH"), (2) zayıf çelişki artık guven düşürmüyor.

**Parametreler:**
- Normal min_guven: `config.MIN_GUVEN_SKORU = 6`
- Dikkatli min_guven: 8 (hardcoded)
- Max SL: `config.MAX_STOP_LOSS_PCT = 1.0`
- Max TP: `config.MAX_TAKE_PROFIT_PCT = 2.0`

**Bilinen sorunlar:** Claude bazen JSON dışı karakter üretiyor; `replace("```json","")` ile temizleniyor.

---

### 4.5 order_agent.py

**Görevi:** Onaylanan kararı Binance Futures'a iletmek.

**Önemli fonksiyonlar:**
- `calistir(karar, fiyat) -> dict`
- `get_client()` — Binance client factory

**Girdi:** decision_agent çıktısı + anlık fiyat

**Çıktı (başarılı):**
```python
{"durum":"ok","islem":"AL"|"SAT","fiyat":4544.54,
 "stop_loss":4499.09,"take_profit":4635.43,"emir_id":12345}
```

**API:** `python-binance 1.0.36`, testnet=True

**Emir sırası:**
1. `futures_change_leverage(symbol, leverage)` — kaldıraç ayarla (config.LEVERAGE=5)
2. `futures_create_order(MARKET)` — ana emir
3. `futures_create_order(STOP_MARKET)` — stop-loss
4. `futures_create_order(TAKE_PROFIT_MARKET)` — take-profit

**SL/TP hesaplama:**
```
AL: SL = fiyat × (1 - stop_loss_pct/100), TP = fiyat × (1 + take_profit_pct/100)
SAT: SL = fiyat × (1 + stop_loss_pct/100), TP = fiyat × (1 - take_profit_pct/100)
```

**Koşullar:** `karar != BEKLE` VE `guven >= MIN_GUVEN_SKORU(6)` VE retry/senkronize

**Bilinen sorunlar:** Testnet bazen `APIError(-2015)` timestamp hatası; senkronize_et() bunu önlemeli.

---

### 4.6 news_agent.py

**Görevi:** Altınla ilgili haberleri takip etmek, sentiment analizi yapmak.

**Önemli fonksiyonlar:**
- `rss_kontrol() -> list` — Tüm feed'leri tarar, FinBERT/Claude ile analiz eder
- `_etki_tahmini(baslik, ozet) -> int` — Anahtar kelime bazlı etki skoru (1-10)
- `_claude_analiz(baslik, ozet) -> dict` — Claude Haiku ile derin analiz (sadece etki≥9)
- `_zaman_carpani(haber_zamani) -> float` — Haberin yaşına göre ağırlık
- `_agirlikli_skor() -> float` — Son 10 haberin toplam skoru
- `_ozet_sentiment() -> str` — Çoğunluk sentiment
- `calistir() -> dict` — Ana fonksiyon (main.py'dan çağrılır)

**RSS Kaynakları:**
```
https://feeds.reuters.com/reuters/businessNews
https://www.kitco.com/rss/
https://www.gold.org/goldhub/rss
```

**Altın anahtar kelimeleri:** gold, xau, fed, federal reserve, interest rate, inflation, cpi, dollar, altın, faiz

**Yeni akış (FinBERT entegrasyonu sonrası):**
```
RSS haber geldi
  → _etki_tahmini() [ücretsiz, anahtar kelime]
  → finbert_agent.analiz_et() [yerel FinBERT, ücretsiz]
  → etki ≥ 9 ise → _claude_analiz() [Claude Haiku, ücretli]
  → _haber_hafizasi'na ekle (son 10, eskiler düşer)
```

**Zaman çarpanı:** ≤1s=×1.0 | 1-4s=×0.7 | 4-24s=×0.4 | >1g=×0.1

**Etki tahmini eşikleri:**
```
Kritik (→9): fomc, fed rate decision, cpi, nfp, nuclear, war, default
Yüksek (→7): fed, rate hike/cut, inflation, payroll, gdp, recession, yields
Orta (→4): gold, xau, commodity, silver, geopolit, sanction, tariff
Varsayılan: 3
```

**Çıktı:**
```python
{"durum":"ok","sentiment":"BULLISH"|"BEARISH"|"NOTR",
 "haber_skoru":float,"etki":int,"kategori":str,
 "ozet":str,"son_haberler":[...son 3]}
```

**API:** `feedparser 6.0.12`, FinBERT (subprocess), Claude Haiku (sadece etki≥9)

**Bilinen sorunlar:** FinBERT hisse senedi odaklı; "gold surges" → BEARISH etiketleyebilir (altın için ters).

---

### 4.7 finbert_agent.py

**Görevi:** Yerel FinBERT modeliyle finansal metin sentiment analizi.

**Önemli fonksiyonlar:**
- `analiz_et(metin) -> dict` — tek metin
- `toplu_analiz_et(metinler) -> list[dict]` — batch işlem (tek subprocess)
- `ozet_sentiment(sonuclar) -> dict` — güven ağırlıklı toplu sonuç
- `_finbert_subprocess(metinler)` — finbert-env'deki Python'u subprocess ile çağırır
- `_altin_yonu_duzelt(metin, sentiment, guven) -> tuple` — altın piyasası kalibrasyonu; FinBERT'in ters etiketlediği kalıpları (~100 ifade listesi) düzeltir

**Girdi:** Ham metin (RSS başlığı + özet)

**Çıktı (tek metin):**
```python
{"durum":"ok","sentiment":"BULLISH"|"BEARISH"|"NOTR",
 "guven":0.7428,"ham_etiket":"positive"|"negative"|"neutral",
 "ham_sentiment":"BULLISH"|"BEARISH"|"NOTR",
 "duzeltildi": True|False}
```

**Çıktı (ozet_sentiment):**
```python
{"sentiment":"BULLISH","haber_skoru":-6.3,"guven_ort":0.688,
 "bullish_adet":1,"bearish_adet":3,"notr_adet":1}
```

**Model:** `ProsusAI/finbert` (Hugging Face, ~500 MB, yerel)

**Python ortamı:** `~/finbert-env` (Python 3.12.13, torch 2.12, transformers 5.8.1)

**Köprü mekanizması:** gold-bot venv (Python 3.14) ve finbert-env (Python 3.12) uyumsuz;  
`subprocess.run([FINBERT_PYTHON, "-c", kod, json.dumps(metinler)])` ile köprü kuruldu.

**Etiket dönüşümü:**
```
positive → BULLISH | negative → BEARISH | neutral → NOTR
```

**haber_skoru formülü:**
```
net_skor = Σ(BULLISH×güven) - Σ(BEARISH×güven) / toplam_ağırlık
haber_skoru = net_skor × 15   # [-15, +15]
```

**Kalibrasyon mekanizması (`_altin_yonu_duzelt`):**
- ~50 BULLISH ifade: "gold surges", "dollar weakens", "rate cut", "safe haven", "yields fall" vb.
- ~55 BEARISH ifade: "dollar strengthens", "gold falls", "rate hike", "hawkish", "yields rise" vb.
- Kalıp eşleşirse: net puan yönü belirler, güven `0.60 + puan_farkı × 0.10` formülüyle ayarlanır
- Kalıp bulunamazsa: FinBERT sonucu değişmeden iletilir
- Test seti: 22 cümle (10 BULLISH, 10 BEARISH, 2 NOTR) — `python3 agents/finbert_agent.py` ile çalıştır

**Bilinen sorunlar:**
- Her çağrı subprocess açar: tek metin için ~2-3 saniye gecikme
- Kalibrasyonda olmayan nüanslı ifadeler hâlâ yanlış etiketlenebilir

---

### 4.8 macro_agent.py

**Görevi:** DXY, VIX, TNX, SP500 verilerinden altın için makro skor üretmek.

**Önemli fonksiyonlar:**
- `calistir() -> dict` — ana fonksiyon
- `_veri_cek(sembol)` — son 5 günlük yfinance verisi, son 2 kapanış
- `_dxy_skoru`, `_vix_skoru`, `_tnx_skoru`, `_sp500_skoru` — skor formülleri
- `_yorumla(skor)` — toplam skoru yoruma çevirir

**Girdi:** Yok (yfinance'den anlık çeker)

**Çıktı:**
```python
{"durum":"ok","skor":4.5,"yorum":"ZAYIF_BULLISH",
 "dxy_degisim":-0.13,"vix_degisim":0.71,"tnx_degisim":0.0,"sp500_degisim":0.0,
 "detay":{"dxy_puan":2.34,"vix_puan":0.43,"tnx_puan":0.0,"sp500_puan":0.0}}
```

**API/Kütüphane:** `yfinance 1.3.0`

**Semboller:**
```
DXY   : DX-Y.NYB  (Dolar endeksi)
VIX   : ^VIX      (Korku endeksi)
TNX   : ^TNX      (10 yıllık ABD tahvil faizi)
SP500 : ^GSPC     (S&P 500)
```

**Bilinen sorunlar:** yfinance `df["Close"]` MultiIndex döndürebiliyor; `squeeze()` ile çözüldü (haber_uzun_backtest).

---

### 4.9 calendar_agent.py

**Görevi:** ABD ekonomik takvim verilerini çekip işlem riskini belirlemek.

**Önemli fonksiyonlar:**
- `calistir() -> dict` — mod belirler, yaklaşan/geçmiş olayları döner
- `_takvim_cek(date_from, date_to)` — investing.com POST API
- `_etki_skoru(olay_adi)` — anahtar kelime eşlemesi
- `_mod_belirle(yaklasan, aciklanan)` — mod kararı

**Girdi:** Yok (bugün + yarını çeker)

**Çıktı:**
```python
{"durum":"ok","mod":"NORMAL"|"DIKKATLI"|"YUKSEK_RISK",
 "yaklasan_olaylar":[{"isim":"..","etki":10,"saat_sonra":2.5}],
 "aciklanan_olaylar":[...]}
```

**API:** `requests + beautifulsoup4`, investing.com POST

```
POST https://www.investing.com/economic-calendar/Service/getCalendarFilteredData
Parametreler: country[]=5 (ABD), timeZone=55 (UTC)
```

**Etki skoru tablosu:**
```
10: fomc, fed, interest rate decision, federal funds rate
9:  cpi, inflation, consumer price
8:  nfp, non-farm, payroll, gdp
7:  ppi, producer price, pce, unemployment
6:  retail sales, durable goods, ism
5:  trade balance, housing, building permits
```

**Mod kriterleri:**
```
YUKSEK_RISK: etki≥8 VE (≤2 saat kaldı VEYA ≤30dk önce açıklandı)
DIKKATLI:    etki≥7 VE (≤4 saat kaldı VEYA ≤1 saat önce açıklandı)
NORMAL:      diğer tüm durumlar
```

**Hata davranışı:** Her exception'da NORMAL mod döner, bot çalışmaya devam eder.

**Bilinen sorunlar:** investing.com scraping; header değişimi veya bot koruması devreye girerse çalışmaz.

---

### 4.10 telegram_agent.py

**Görevi:** Bot durumu ve işlem bildirimleri göndermek.

**Önemli fonksiyonlar:**
- `_gonder(mesaj)` — ham POST, requests ile
- `bildir_sinyal(yon, fiyat, strateji, guven)` — AL/SAT sinyali
- `bildir_emir(yon, fiyat, miktar, sl, tp)` — emir gönderildi
- `bildir_kapanis(yon, kar_zarar)` — pozisyon kapandı
- `bildir_hata(hata)` — hata uyarısı
- `bildir_durum(mesaj)` — genel durum (başlangıç/durdurma)
- `bildir_ozet(gun_kar_zarar, islem_sayisi, bakiye)` — günlük özet

**API:** Telegram Bot API `https://api.telegram.org/bot{TOKEN}/sendMessage`

**Format:** HTML parse_mode, timeout=10s

**Konfigürasyon:** `TELEGRAM_TOKEN` + `TELEGRAM_CHAT_ID` (.env)

---

### 4.11 utils.py

**Görevi:** Binance ile zaman senkronizasyonu sağlamak.

**Önemli fonksiyonlar:**
- `senkronize_et(client) -> int` — ms cinsinden fark döner

**Mantık:**
```python
fark = |yerel_ms - binance_server_ms|
if fark > 1000:
    subprocess.run(["sudo", "chronyc", "makestep"])
```

**Bilinen sorunlar:** `sudo` gerektiriyor; headless/otomatik başlatmada şifre sorunu.

---

## 5. STRATEJİLER

### Kısa Vadeli (Breakout)

**Tam strateji mantığı:**
1. Son 100 dakikalık 1m mumlardan son 20'sinin high/low'u alınır (son mum hariç)
2. Güncel mumun high > direnc VE hacim > hacim_ort × 1.2 → YUKARI breakout
3. Güncel mumun low < destek VE hacim > hacim_ort × 1.2 → ASAGI breakout
4. Breakout yok → döngü erken sonlanır (0 Claude çağrısı)
5. Breakout var → tam ajan pipeline çalışır

**Parametreler:**

| Parametre | Değer | Kaynak |
|-----------|-------|--------|
| Mum aralığı | 1 dakika | Binance API |
| Lookback penceresi | 20 mum | data_agent.py hardcoded |
| Hacim teyit çarpanı | 1.2× | data_agent.py hardcoded |
| Kaldıraç | 10x | config.KALDIRAC_KISA |
| ATR SL çarpanı | 1.0 | config.ATR_SL_CARPAN |
| ATR TP çarpanı | 3.0 | config.ATR_TP_CARPAN |
| Max SL | %1.0 fiyat bazlı | config.MAX_STOP_LOSS_PCT |
| Max TP | %2.0 fiyat bazlı | config.MAX_TAKE_PROFIT_PCT |
| Miktar | 0.01 oz | config.QUANTITY |

**Backtest sonuçları (haber_backtest.py, 19.05.2026):**
- Test penceresi: son 32 mum (12 test mumu), 5m aralık
- 3 ASAGI breakout tespit edildi, tümü BEKLE
- Neden: Risk ajanı BEARISH sentiment + 10x kaldıraç kombinasyonunu reddetti

**Güçlü yönleri:**
- Yön belirsizliğinde hiç işlem açmaz (breakout yok = 0 maliyet)
- ATR tabanlı dinamik SL/TP volatiliteye uyum sağlar
- Hacim teyidi sahte kırılımları filtreler

**Zayıf yönleri:**
- 10x kaldıraç yüksek risk; risk ajanı çok sık bloke ediyor
- 1 dakikalık mumlar çok gürültülü olabilir
- Takvim YUKSEK_RISK dönemlerinde tamamen durur

---

### Uzun Vadeli (RSI/MACD/BB)

**Tam strateji mantığı:**
1. Son 100 adet 15m mum ile RSI, MACD, BB, MA20, MA50 hesaplanır
2. `uzun_vadeli_dongu()` her 4 saatte bir çalışır
3. Takvim guard + tam ajan pipeline (data → technical → risk → decision → order)
4. RSI yorumu: <30 ASIRI_SATILMIS, >70 ASIRI_ALINMIS

**Parametreler:**

| Parametre | Değer | Kaynak |
|-----------|-------|--------|
| Mum aralığı | 15 dakika | Binance API |
| RSI periyodu | 14 | data_agent.py (EWM tabanlı) |
| MACD | 12/26/9 | data_agent.py |
| Bollinger | 20 periyot, 2σ | data_agent.py |
| MA kısa/uzun | 20/50 | data_agent.py |
| Kaldıraç | 3x | config.KALDIRAC_UZUN |
| RSI aşırı satım | 30 | config.RSI_ASIRI_SATIS |
| RSI aşırı alım | 70 | config.RSI_ASIRI_ALIS |

**Backtest sonuçları (motor.py, altin_15m_2026.csv, 4529 mum):**
- Grafik: `backtest/sonuclar/backtest_uzun_*.png`
- Detaylı sayısal sonuçlar PNG dosyalarında

**Güçlü yönleri:**
- 3x kaldıraç, risk ajanı daha az bloke ediyor
- Makro + haber bağlamıyla güçlü filtre
- 4 saatlik döngü → az işlem → az komisyon

**Zayıf yönleri:**
- 4 saat bekleyince fırsat kaçabilir
- RSI yalnız başına zayıf; MACD + BB birlikte anlamlı
- Claude'un teknik yorumu subjektif

---

### Backtest Motoru (motor.py) — RSI/MACD/BB Puanlama

**Kısa vadeli puanlama (mod="kisa"):**

| Koşul | AL puanı | SAT puanı |
|-------|---------|---------|
| RSI < 35 | +2 | — |
| RSI 35-45 | +1 | — |
| RSI > 65 | — | +2 |
| RSI 55-65 | — | +1 |
| MACD > sinyal | +2 | — |
| MACD < sinyal | — | +2 |
| Fiyat < BB alt | +2 | — |
| Fiyat > BB üst | — | +2 |
| MA20 > MA50 | +1 | — |
| MA20 < MA50 | — | +1 |

**Karar:** al_skor ≥ 5 → AL | sat_skor ≥ 5 → SAT | diğer → BEKLE

**Trend filtresi:** Günlük MA50/MA200 ile büyük trend teyidi (günlük veri: `altin_1d_2004.csv`)

**Trailing stop:** Varsayılan AÇIK; stop_fiyat en iyi fiyatı takip eder

---

### Breakout Stratejisi (strateji_breakout.py)

| Parametre | Değer |
|-----------|-------|
| Kırılım penceresi | 20 mum (shift=1, gelecek sızıntısı yok) |
| Hacim teyidi | hacim > hacim_ort × 1.2 |
| ATR SL çarpanı | 1.5× |
| ATR TP çarpanı | 3.0× |
| Max günlük zarar | $75 |
| Trailing stop | ATR tabanlı, pozisyon lehine hareket ettikçe çeker |
| Trend filtresi | MA50/MA200 günlük teyit |

---

## 6. KARAR MEKANİZMASI

### Skor sistemi nasıl çalışıyor

Her ajan kendi skorunu/kararını üretir. decision_agent bunları makro/haber/teknik yön olarak sınıflandırır ve ağırlıklı bir karar verir.

### Makro skor hesaplama formülü

```python
DXY skoru   = -(değişim% / 0.5) × 9     # sınır [-9, +9]
VIX skoru   = (değişim% / 10) × 6       # sınır [-3, +6]  ↑VIX = altın için iyi
             veya (değişim% / 10) × 3   # sınır [-3, +6]  (negatif tarafta asimetrik)
TNX skoru   = -(değişim% / 2) × 5       # sınır [-5, +5]  ↑faiz = altın için kötü
SP500 skoru = -(değişim% / 1) × 3       # sınır [-3, +4]  ↑borsa = riskten kaçış azalır
             veya -(değişim% / 1) × 4   # (negatif tarafta asimetrik)

Toplam = DXY + VIX + TNX + SP500        # teorik sınır yaklaşık [-20, +24]
```

**Yorumlama:** ≥15 GUCLU_BULLISH | ≥8 BULLISH | ≥3 ZAYIF_BULLISH | >-3 NOTR | >-8 ZAYIF_BEARISH | >-15 BEARISH | diğer GUCLU_BEARISH

### Haber skoru hesaplama formülü

```python
# Etki tahmini (anahtar kelime bazlı):
etki = 9 (kritik: FOMC, CPI, NFP...)
     = 7 (yüksek: Fed, rate, GDP...)
     = 4-5 (orta: gold, xau...)
     = 3 (varsayılan)

# Zaman çarpanı:
carpan = 1.0 (≤1 saat)  | 0.7 (1-4 saat) | 0.4 (4-24 saat) | 0.1 (>1 gün)

# Ağırlıklı etki:
agirlikli_etki = etki × carpan

# Toplam haber skoru:
haber_skoru = Σ(agirlikli_etki for haber in son_10_haber)
```

### FinBERT özet skor (news_agent için yeni)

```python
net_skor = [Σ(BULLISH × güven) - Σ(BEARISH × güven)] / toplam_ağırlık  # [-1, +1]
haber_skoru = net_skor × 15    # [-15, +15]
BULLISH: haber_skoru > 2 | BEARISH: haber_skoru < -2 | NOTR: diğer
```

### Takvim modları ve etkileri

| Mod | Tetikleyici | Etkisi |
|-----|------------|--------|
| YUKSEK_RISK | etki≥8, ≤2s kaldı / ≤30dk önce | Tüm işlemler durur (Claude çağrısı bile olmaz) |
| DIKKATLI | etki≥7, ≤4s kaldı / ≤1s önce | min_guven=8 (normalde 6) |
| NORMAL | diğer | min_guven=6 |

### Güven skoru nasıl hesaplanıyor

1. Claude JSON olarak `guven: 1-10` döner
2. Ağırlıklı sistem uygular:
   - 3 sinyal (makro+haber+teknik) aynı yön → `guven = min(10, guven + 2)`
   - makro+haber aynı yön, teknik zıt, **güçlü** çelişki (`abs(makro_skor) > 6`) → `karar = BEKLE, guven = 0`
   - makro+haber aynı yön, teknik zıt, **zayıf** çelişki (`abs(makro_skor) ≤ 6`) → sadece gerekçeye not eklenir, guven değişmez
3. `guven < min_guven (6 veya 8)` → `karar = BEKLE`

### Risk ajanı karar kriterleri

Prompt: "Muhafazakar risk yöneticisi. Şüphede HAYIR dersin."

Risk ajanı şunlara bakıyor:
- Fiyat yönü + teknik sinyal tutarlılığı
- Haber sentiment (bearish haber + kaldıraç = riskli)
- Kaldıraç seviyesi (10x kısa vadeli çok riskli)
- Max günlük zarar limiti (`MAX_STOP_LOSS_PCT = 1.0`)

`onay == HAYIR` → decision_agent Claude'a sormaz, anında BEKLE döner.

---

## 7. BACKTEST SONUÇLARI

### Test 1: haber_backtest.py — Canlı Ajan Testi

| Parametre | Değer |
|-----------|-------|
| Test tarihi | 19.05.2026 |
| Mum aralığı | 5 dakika |
| Test penceresi | Son 32 mum (12 test, 20 lookback) |
| Makro | Canlı (yfinance) |
| Haber | Canlı (Claude Haiku) |
| Takvim | Canlı (investing.com) |

**Sonuç:** 3 ASAGI breakout tespit edildi.  
**Karar:** Tümü BEKLE  
**Neden:** Risk ajanı engelledi — BEARISH haber sentiment + 10x kaldıraç kombinasyonu

**Önemli gözlem:** BEARISH sentiment döneminde kısa vadeli bot hiç işlem açmıyor. Makro skor ZAYIF_BULLISH iken haber BEARISH → çelişki → BEKLE.

---

### Test 2: haber_uzun_backtest.py — 30 Günlük Backtest

| Parametre | Değer |
|-----------|-------|
| Test tarihi | 19.05.2026 |
| Veri aralığı | 17.04.2026–18.05.2026 |
| Mum aralığı | 15 dakika |
| Toplam mum | 3000 (2940 test + 60 warmup) |
| Test günleri | 31 |
| Sermaye | $1.000 |
| Kaldıraç | 3x |
| SL | %1 (fiyat bazlı) → kaldıraçlı %3 |
| TP | %2 (fiyat bazlı) → kaldıraçlı %6 |
| Min güven | 6 |
| Karar motoru | Kural tabanlı (Claude çağrısı yok) |

**Sonuçlar:**

| Metrik | Değer |
|--------|-------|
| Başlangıç sermayesi | $1.000,00 |
| **Final sermayesi** | **$1.035,38** |
| **Toplam K/Z** | **+$35,38 (%+3.5)** |
| Toplam işlem | 9 |
| Kar | 3 |
| Zarar | 5 |
| Açık (kapanmamış) | 1 |
| **Başarı oranı** | **%37.5** |
| Haber sentiment doğruluğu | %43.3 (13/30 gün) |

**İşlem listesi (son 9 işlem):**

| Tarih | Yön | Giriş | Çıkış | K/Z | Sonuç |
|-------|-----|-------|-------|-----|-------|
| 18.04 22:00 | SAT | 4822.91 | 4726.45 | +60.00 | KAR |
| 24.04 10:30 | SAT | 4684.14 | 4730.98 | -31.80 | ZARAR |
| 24.04 20:30 | AL | 4711.41 | 4664.30 | -30.85 | ZARAR |
| 02.05 01:45 | AL | 4614.62 | 4568.47 | -29.92 | ZARAR |
| 08.05 17:30 | AL | 4722.84 | 4817.30 | +58.05 | KAR |
| 11.05 09:15 | SAT | 4661.40 | 4708.01 | -30.76 | ZARAR |
| 11.05 22:00 | SAT | 4743.51 | 4648.64 | +59.68 | KAR |
| 16.05 23:45 | AL | 4537.58 | 4492.20 | -31.63 | ZARAR |
| 18.05 17:15 | AL | 4557.05 | 4575.78 | +12.61 | AÇIK |

**Önemli gözlemler:**
- %37.5 başarı oranı, 2:1 TP/SL sayesinde yine de kârlı
- Haber sentiment tümü BULLISH (Claude Ağu 2025 sonrasını bilmiyor)
- Sistem yalnızca teknik + makro sinyallerle çalıştı
- Grafik: `backtest/haber_uzun_backtest.png`

---

### Test 3: motor.py + strateji_breakout.py

- Veriler: `altin_5m_2026.csv` (13.560 mum) + `altin_15m_2026.csv` (4.529 mum)
- Grafik çıktıları: `backtest/sonuclar/` klasöründe PNG'ler
- Sayısal sonuçlar: PNG içinde gösteriliyor, ayrı CSV kaydı yok

---

### Test 4: histdata_backtest.py — 17 Yıllık M1 Histdata Backtesti ★

| Parametre | Değer |
|-----------|-------|
| Test tarihi | 20.05.2026 |
| Veri aralığı | 15.03.2009–31.12.2025 |
| Ham veri | M1 (1 dakikalık), ~5.88 milyon satır |
| Backtest verisi | 15 dakikalık (M1→15m yeniden örnekleme) |
| Toplam mum | 396.303 (15dk) |
| Sermaye | $1.000 |
| Kaldıraç | 3x |
| SL | %1.0 (fiyat bazlı) → kaldıraçlı %3 |
| TP | %2.0 (fiyat bazlı) → kaldıraçlı %6 |
| Mod | Uzun vadeli (RSI/MACD/BB) |
| Trailing stop | AÇIK |
| Trend filtresi | MA50/MA200 günlük (histdata'dan türetildi) |
| Karar motoru | Kural tabanlı (Claude çağrısı yok) |
| Süre | ~120 saniye |

**Genel Sonuçlar:**

| Metrik | Değer |
|--------|-------|
| Başlangıç sermayesi | $1.000,00 |
| **Final sermayesi** | **$19.571,27** |
| **Toplam K/Z** | **+$18.571,27 (%+1857)** |
| **CAGR** | **%19,1/yıl** |
| Toplam işlem | 1.691 |
| Kârlı yıl | 10/17 |
| Zararlı yıl | 7/17 |

**Yıllık Sonuçlar:**

| Yıl | Başlangıç | Bitiş | Getiri | İşlem | Başarı | Max DD | Not |
|-----|-----------|-------|--------|-------|--------|--------|-----|
| 2009 | $1.000 | $743 | %-25,6 | 132 | %34,1 | %-32,2 | 2008 krizi ardı |
| 2010 | $744 | $1.710 | %+129,8 | 127 | %44,9 | %-18,8 | |
| 2011 | $1.710 | $3.637 | %+112,7 | 125 | %47,2 | %-34,2 | |
| 2012 | $3.637 | $2.627 | %-27,8 | 90 | %32,2 | %-32,1 | |
| 2013 | $2.627 | $4.659 | %+77,3 | 116 | %40,5 | %-28,2 | |
| 2014 | $4.659 | $3.161 | %-32,1 | 85 | %34,1 | %-37,4 | **En kötü yıl** |
| 2015 | $3.161 | $2.961 | %-6,3 | 104 | %35,6 | %-27,4 | |
| 2016 | $2.961 | $2.807 | %-5,2 | 100 | %41,0 | %-32,7 | |
| 2017 | $2.807 | $1.987 | %-29,2 | 85 | %35,3 | %-39,6 | |
| 2018 | $1.987 | $2.096 | %+5,4 | 61 | %34,4 | %-16,2 | |
| 2019 | $2.096 | $2.646 | %+26,3 | 67 | %40,3 | %-10,4 | |
| 2020 | $2.646 | $5.313 | **%+100,8** | 111 | %44,1 | %-21,7 | **COVID** |
| 2021 | $5.313 | $3.650 | %-31,3 | 93 | %29,0 | **%-41,4** | **En büyük DD** |
| 2022 | $3.650 | $4.315 | %+18,2 | 113 | %37,2 | %-27,4 | |
| 2023 | $4.315 | $4.827 | %+11,9 | 77 | %42,9 | %-22,8 | |
| 2024 | $4.827 | $7.191 | %+49,0 | 94 | %42,6 | %-12,3 | |
| 2025 | $7.191 | $19.571 | **%+172,2** | 111 | %46,8 | %-16,3 | **En iyi yıl** |

**Özel Dönem Analizleri:**

**2009 — 2008 Krizi Ardı:** -%25,6 kayıp. İlk yıl zayıf performans; RSI/MACD 15m mumlarında aşırı gürültülü çalıştı, win rate %34,1. Ancak altın bu dönemde $800→$1.200 yükseldi — trendin büyük bölümü kaçırıldı.

**2020 — COVID:** +%100,8 kazanç. Altının $1.550→$2.067 tarihsel yükselişi mükemmel yakalandı. Güçlü tek yönlü trend + trailing stop kombinasyonu sistemin en güçlü çalıştığı ortam.

**Kritik Gözlem:** Yıllık max drawdown'lar -%10 ile -%41 arasında değişiyor. Hedef -%15 sınırı çoğu yılda aşılıyor. Gerçek paraya geçişte kaldıraç 3x → 2x'e düşürülmesi veya dinamik position sizing eklenmesi önerilir.

**Çıktı dosyaları:**
- `backtest/sonuclar/17yil_2009_2025_RSI_MACD_BB_3x_kaldirac.png`
- `backtest/sonuclar/17yil_2009_2025_islemler_1691_adet.csv`

---

### Test 5: Motor v4 — Dinamik ADX Kaldıraç + Yatay Piyasa Filtresi (%3 eşik)

**Tarih:** 20.05.2026  
**Değişiklikler (motor.py):**
- `hesapla_adx()` fonksiyonu eklendi (14 periyot, Wilder smoothing)
- `gostergeler_ekle()` → `adx` ve `yatay_aralik` kolonları eklendi
- Dinamik kaldıraç: ADX>25 → 3x | ADX 15–25 → 2x | ADX<15 → 1x
- Yatay piyasa filtresi: Son 50 mum (12.5 saat) aralığı <%3 → işlem yok

| Metrik | Değer |
|--------|-------|
| Final | $883 |
| CAGR | **%-0.7** |
| Max DD | %-9.5 |
| Toplam işlem | **46** (17 yılda) |

**Sonuç: BAŞARISIZ.**  
%3 eşiği 15dk timeframe için çok yüksek. 15dk × 50 mum = 12.5 saatlik pencerede altının tipik aralığı medyan %0.84; zamanın sadece **%2.4'ünde** aralık >%3 oluyor. Filtre işlemlerin %97.6'sını bloke etti.

---

### Test 6: Motor v4 — Dinamik ADX Kaldıraç + Yatay Piyasa Filtresi (%1 eşik)

**Tarih:** 20.05.2026  
**Değişiklikler:** Yatay piyasa eşiği %3 → %1'e düşürüldü.

| Parametre | Değer |
|-----------|-------|
| Veri | 396.303 mum (15dk, 2009–2025) |
| Sermaye | $1.000 |
| Kaldıraç | Dinamik ADX (1x/2x/3x) |
| SL | %1.0 \| TP: %2.0 \| Trailing: AÇIK |
| Yatay filtre | 50 mum aralığı <%1 → işlem yok |

**Genel Sonuçlar:**

| Metrik | Orijinal (3x sabit) | Yeni (Dinamik+Filtre) | Hedef |
|--------|---------------------|-----------------------|-------|
| Final | $19.571 | $2.371 | — |
| CAGR | %19.1 | **%5.2** | >%15 ❌ |
| Max DD | -%41 | -%36.1 | <%20 ❌ |
| Toplam işlem | 1.691 | 1.119 | — |

**Yıllık Sonuçlar:**

| Yıl | Başlangıç | Bitiş | Getiri | İşlem | Başarı | Max DD | Not |
|-----|-----------|-------|--------|-------|--------|--------|-----|
| 2009 | $1.000 | $737 | %-26.3 | 104 | %34.6 | %-36.1 | 2008 krizi ardı |
| 2010 | $737 | $1.331 | %+80.6 | 82 | %45.1 | %-9.6 | |
| 2011 | $1.331 | $2.671 | %+100.7 | 90 | %46.7 | %-11.0 | |
| 2012 | $2.671 | $2.162 | %-19.1 | 55 | %30.9 | %-26.2 | |
| 2013 | $2.162 | $3.045 | %+40.8 | 95 | %40.0 | %-15.2 | |
| 2014 | $3.045 | $2.440 | %-19.9 | 50 | %38.0 | %-20.0 | |
| 2015 | $2.440 | $1.981 | %-18.8 | 68 | %30.9 | %-27.3 | |
| 2016 | $1.981 | $1.764 | %-11.0 | 67 | %37.3 | %-25.3 | |
| 2017 | $1.764 | $1.593 | %-9.7 | 32 | %25.0 | %-22.3 | |
| 2018 | $1.593 | $1.556 | %-2.3 | 17 | %29.4 | %-5.8 | |
| 2019 | $1.556 | $1.700 | %+9.2 | 38 | %34.2 | %-8.5 | |
| 2020 | $1.700 | $1.778 | %+4.6 | 78 | %35.9 | %-18.0 | COVID |
| 2021 | $1.778 | $1.400 | %-21.2 | 65 | %29.2 | %-26.9 | |
| 2022 | $1.400 | $1.730 | %+23.6 | 73 | %41.1 | %-20.5 | |
| 2023 | $1.730 | $1.572 | %-9.1 | 49 | %40.8 | %-19.4 | |
| 2024 | $1.572 | $1.616 | %+2.8 | 60 | %41.7 | %-25.2 | |
| 2025 | $1.616 | $2.371 | %+46.7 | 96 | %38.5 | %-13.5 | |

**ADX kaldıraç dağılımı (2019–2020 örnek):**

| Seviye | ADX Aralığı | Zaman Oranı |
|--------|-------------|-------------|
| 3x | ADX > 25 | %42.7 |
| 2x | ADX 15–25 | %41.6 |
| 1x | ADX < 15 | %15.7 |
| Ortalama etkin kaldıraç | — | ~2.3x |

**Neden CAGR düştü:**  
1. Efektif kaldıraç 3x → 2.3x düştü (-%23 getiri etkisi)  
2. %1 filtresi zamanın %61'ini bloke etti → daha az işlem fırsatı  
3. Hedefler karşılanamadı: CAGR %5.2 (hedef >%15) | Max DD -%36.1 (hedef <%20)

**Önemli teknik bulgu:** 15dk timeframe için yatay filtre eşiği optimize edilmeli.  
Öneri: %0.5 (zamanın %18'i bloke) veya günlük veriye uygulama.

**Mevcut durum:** ADX dinamik kaldıraç ve yatay filtre `backtest/motor.py`'de aktif.  
Canlı bota henüz dokunulmadı.

### Test 7: model_egit.py — XGBoost İlk ML Modeli ★

**Tarih:** 20.05.2026  
**Amaç:** Kural tabanlı backtest'i desteklemek / Claude bağımlılığını azaltmak

**Veri:**
| Parametre | Değer |
|-----------|-------|
| Kaynak | `backtest/ml_veri/features.csv` |
| Toplam örnek | 396.254 (15dk mumlar, 2009–2025) |
| Özellik sayısı | 12 (teknik) + 2 (zaman: saat, gün) = 12 toplam |
| Hedef eşiği | ±%0.3 / 16 mum (4 saat) |
| Eğitim | 2009–2022 → 328.335 örnek |
| Test | 2023–2025 → 67.919 örnek |
| Class dağılımı | AL %15.4 / SAT %14.1 / BEKLE %70.5 |

**Model parametreleri:**
```
XGBClassifier(n_estimators=300, max_depth=5, learning_rate=0.05,
              subsample=0.8, colsample_bytree=0.8, min_child_weight=35)
Sınıf ağırlıkları: balanced × 3x BEKLE boost
  → SAT: 2.39  BEKLE: 1.40  AL: 2.25
```

**Sonuçlar (prob eşiği=0.40):**

| Sınıf | Precision | Recall | F1 |
|-------|-----------|--------|----|
| SAT (-1) | 0.279 | 0.094 | 0.141 |
| BEKLE (0) | 0.703 | 0.939 | 0.804 |
| AL (1) | 0.299 | 0.078 | 0.124 |

**Olasılık eşiği analizi:**

| Eşik | SAT Prec | AL Prec | Sinyal % |
|------|----------|---------|----------|
| 0.40 | 0.279 | 0.299 | 9.5% |
| 0.45 | 0.303 | 0.340 | 3.8% |
| 0.50 | 0.346 | **0.360** | 1.4% |

**En önemli 5 özellik:**
1. `saat` (101.3) — altın London/NY seanslarına çok duyarlı
2. `atr` (73.9) — volatilite bağlamı
3. `volatilite` (26.0)
4. `momentum_5` (25.5)
5. `gun` (24.3)

**Durum:** Hedef precision > 0.35 AL için eşik=0.50'de karşılandı (0.360). SAT için yakın (0.346). Canlı bota entegrasyon henüz yapılmadı.

**Sonraki adım:** Canlı bot entegrasyonu — `decision_agent`'a model skoru ek girdi olarak verilecek.

---

## 8. YAPILANDIRMA (CONFIG)

### config.py — Tüm değerler (direkt dosyadan)

```python
# ── API Anahtarları (.env'den) ───────────────────────────────────
ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY")
BINANCE_API_KEY    = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")
TESTNET            = os.getenv("TESTNET", "True") == "True"   # varsayılan: True

# ── İşlem Ayarları ──────────────────────────────────────────────
SYMBOL    = "XAUUSDT"   # Binance Futures altın paritesi
LEVERAGE  = 5           # Genel kaldıraç (order_agent'ta override edilir)
QUANTITY  = 0.01        # Her emirde kaç oz altın

# ── Strateji Eşikleri ────────────────────────────────────────────
MIN_GUVEN_SKORU = 6     # Bu altında karar → emir yok
RSI_ASIRI_SATIS = 30    # RSI < 30 → ASIRI_SATILMIS yorumu
RSI_ASIRI_ALIS  = 70    # RSI > 70 → ASIRI_ALINMIS yorumu

# ── Döngü Ayarı ──────────────────────────────────────────────────
BEKLEME_DAKIKA = 15     # Artık kullanılmıyor; main.py time.sleep(60) kullanır

# ── Risk Yönetimi ─────────────────────────────────────────────────
MAX_STOP_LOSS_PCT   = 1.0   # Maksimum SL: fiyatın %1'i
MAX_TAKE_PROFIT_PCT = 2.0   # Hedef TP: fiyatın %2'i
MAX_GUNLUK_ZARAR    = 75.0  # Günlük max zarar ($) — aşılınca o gün işlem durur

# ── Katman kaldıraçları ───────────────────────────────────────────
KALDIRAC_KISA = 10    # Breakout botu kaldıracı
KALDIRAC_UZUN = 3     # Swing trader kaldıracı

# ── Breakout ATR çarpanları ───────────────────────────────────────
ATR_SL_CARPAN = 1.0   # SL = giriş ± ATR × 1.0
ATR_TP_CARPAN = 3.0   # TP = giriş ± ATR × 3.0
```

### Değiştirince ne etkileniyor

| Değer | Etkisi |
|-------|--------|
| `MIN_GUVEN_SKORU` | Daha az/çok işlem açar; 8+ çok seçici, 4- tehlikeli |
| `KALDIRAC_KISA` | 10x yüksek risk; düşürünce risk ajanı daha çok onaylar |
| `KALDIRAC_UZUN` | 3x makul; artırınca risk ajnaı sıklaşır |
| `ATR_SL_CARPAN` | Küçültünce daha erken durdurulur, büyütünce daha fazla risk |
| `ATR_TP_CARPAN` | Büyütünce TP'ye ulaşması zorlaşır ama kazanç büyür |
| `MAX_STOP_LOSS_PCT` | Claude'un önerdiği SL bu değeri aşamaz |
| `MAX_GUNLUK_ZARAR` | $75 aşılınca o gün tüm işlemler durur; gece 00:00'da sıfırlanır |
| `QUANTITY` | Binance'e gönderilen oz miktarı; 0.01 minimum |
| `TESTNET` | False yapınca GERÇEK PARA kullanılır — dikkat! |

---

## 9. BAĞLANTILAR VE API'LAR

### Anthropic Claude

| Kullanım | Model | max_tokens | Nerede |
|----------|-------|-----------|--------|
| Teknik analiz | claude-sonnet-4-6 | 150 | technical_agent.py |
| Risk değerlendirme | claude-sonnet-4-6 | 150 | risk_agent.py |
| Nihai karar | claude-sonnet-4-6 | 200 | decision_agent.py |
| Kritik haber analizi | claude-haiku-4-5-20251001 | 200 | news_agent.py |
| Backtest haber | claude-haiku-4-5-20251001 | 150 | haber_uzun_backtest.py |

### Binance API

| Ortam | Endpoint | Kullanım |
|-------|----------|---------|
| Testnet | `testnet.binancefuture.com` | Tüm işlemler (şu an) |
| Gerçek | `fapi.binance.com` | `TESTNET=False` yapılınca |

**Kullanılan fonksiyonlar:**
```
futures_klines()          — mum verisi
futures_change_leverage() — kaldıraç ayarı
futures_create_order()    — emir gönderimi (MARKET/STOP_MARKET/TAKE_PROFIT_MARKET)
get_server_time()         — zaman senkronu (utils.py)
```

### Telegram Bot

- `TOKEN`: `.env` dosyasından (`TELEGRAM_TOKEN`)
- `CHAT_ID`: `.env` dosyasından (`TELEGRAM_CHAT_ID`)
- `BASE_URL`: `https://api.telegram.org/bot{TOKEN}`
- **Bildirim türleri:** sinyal, emir, kapanis, hata, durum, ozet

### yfinance

| Sembol | Temsil | Kullanım |
|--------|--------|---------|
| `DX-Y.NYB` | Dolar Endeksi (DXY) | macro_agent |
| `^VIX` | CBOE Volatilite Endeksi | macro_agent |
| `^TNX` | 10 Yıllık ABD Tahvil | macro_agent |
| `^GSPC` | S&P 500 | macro_agent |
| `GC=F` | Altın Futures | veri_indir.py (backtest verisi) |

### RSS Kaynakları

```
https://feeds.reuters.com/reuters/businessNews   — Reuters iş haberleri
https://www.kitco.com/rss/                        — Kitco altın haberleri
https://www.gold.org/goldhub/rss                  — World Gold Council
```

### investing.com

```
POST https://www.investing.com/economic-calendar/Service/getCalendarFilteredData
country[]=5 (ABD), timeZone=55 (UTC), bugün + yarın
```

### FinBERT

```
Model: ProsusAI/finbert (Hugging Face)
Boyut: ~500 MB, yerel disk
Ortam: ~/finbert-env (Python 3.12.13, torch 2.12, transformers 5.8.1)
```

---

## 10. KURULUM VE ÇALIŞTIRMA

### Sanal ortamı aktif etme

```bash
# Ana bot ortamı (Python 3.14.4)
source ~/gold-bot/bin/activate

# FinBERT ortamı (Python 3.12.13) — genellikle manuel kullanma, finbert_agent subprocess halleder
source ~/finbert-env/bin/activate
```

### Botu başlatma

```bash
cd ~/gold-bot-project
source ~/gold-bot/bin/activate
python3 main.py
```

### Backtesti çalıştırma

```bash
source ~/gold-bot/bin/activate && cd ~/gold-bot-project

# 30 günlük haber+makro backtest (ana backtest)
python3 -m backtest.haber_uzun_backtest

# 1 saatlik canlı ajan backtest
python3 -m backtest.haber_backtest

# Kural tabanlı motor backtest
python3 backtest/motor.py

# ATR breakout backtest
python3 backtest/strateji_breakout.py
```

### Bireysel ajan testleri

```bash
python3 agents/data_agent.py        # Binance veri kontrolü
python3 agents/macro_agent.py       # DXY/VIX/TNX/SP500 anlık
python3 agents/calendar_agent.py    # Ekonomik takvim durumu
python3 agents/news_agent.py        # RSS + FinBERT testi
python3 agents/finbert_agent.py     # FinBERT doğrudan test
python3 agents/decision_agent.py    # Karar ajanı test senaryoları
```

### Log dosyasını izleme

```bash
# Gerçek zamanlı izleme (botun çıktısı terminale basılıyor)
python3 -u main.py 2>&1 | tee bot.log

# Log takibi
tail -f bot.log
```

### Git sürüm kontrolü (2026-07-26'dan itibaren)

Depo `~/gold-bot-project` içinde yerel olarak tutuluyor, dal adı `main`. Uzak sunucu (GitHub vb.) **yok** — her şey bu makinede.

```bash
# Son commit'ten beri ne değişti
git diff

# Değişiklikleri kaydet (strateji denemelerinde her testten sonra)
git add -A && git commit -m "motor.py: ADX esigi %1 -> %0.5"

# Bozulan dosyayı son kayıtlı haline döndür
git checkout -- backtest/motor.py

# Geçmişi gör
git log --oneline
```

**Takip edilenler:** `main.py`, `config.py`, `agents/*.py`, `backtest/*.py`, ML scriptleri, `PROJE.md`, `sonuclar/*.csv` → toplam ~516 KB.

**Takip dışı (`.gitignore`):** `.env`, `backtest/veri/` (671 MB), `ml_veri/features.csv` (82 MB), `*.pkl`, `*.png`, `__pycache__/`, `haber_gecmis.json`.

> **Dikkat:** `.gitignore`'da satır sonu yorumu çalışmaz — `backtest/veri/  # 671 MB` yazarsan yorum desenin parçası sayılır ve klasör dışlanmaz. Yorumları ayrı satıra yaz.

**Önemli:** `.env` asla commit edilmemeli. Yeni bir gizli dosya eklersen önce `.gitignore`'a yaz, sonra `git add` çalıştır.

---

### Testnet'ten gerçek paraya geçiş adımları

1. `.env` dosyasında `TESTNET=False` yap
2. `config.py`'de `QUANTITY = 0.01` değerini kontrol et (0.01 oz = ~$45 değer)
3. `LEVERAGE` değerini düşür (10x → 5x kısa vadeli)
4. `MIN_GUVEN_SKORU = 7` veya `8` yap (daha seçici)
5. Gerçek Binance API anahtarı ile `.env` güncelle
6. İlk gün sadece 1-2 işlem izle, emir doğru gidiyor mu kontrol et
7. Binance'de manuel stop-loss koy (bot hatası ihtimaline karşı)

---

## 11. TAMAMLANAN İŞLER

| Tarih | Ne yapıldı | Neden yapıldı | Sonucu |
|-------|------------|---------------|--------|
| 2026-05 (erken) | Temel iskelet: data/technical/risk/decision/order | Projenin temeli | Çalışan bot altyapısı |
| 2026-05 | telegram_agent.py | Uzaktan izleme gerekiyordu | Telefona mesaj gidiyor, test edildi |
| 2026-05 | utils.py — senkronize_et() | Binance zaman hatası (-2015) | chronyc makestep entegre |
| 2026-05 | data + order agent retry | Bağlantı kesilince bot çöküyordu | 3× retry + 5s bekleme + hata bildirimi |
| 2026-05 | macro_agent.py | Haber+teknik yetmiyordu; makro gerekiyordu | DXY/VIX/TNX/SP500 anlık skor |
| 2026-05 | calendar_agent.py | FOMC/CPI günleri kayıp tuttu | YUKSEK_RISK/DIKKATLI mod sistemi |
| 2026-05 | news_agent.py (RSS + hafıza) | Claude tek seferlik çalışıyordu | feedparser, 10 haber hafızası, zaman çarpanı |
| 2026-05 | main.py büyük güncelleme | Tüm ajanları entegre etmek | 2 katman + 3 bağlam, threading.Lock |
| 2026-05 | decision_agent.py güncelleme | Makro/takvim entegrasyonu | YUKSEK_RISK koruması, ağırlıklı karar, min_guven=8 DIKKATLI |
| 2026-05-18 | haber_backtest.py | Canlı veriyle sistem testi | Çalıştı, 3 breakout tespit etti |
| 2026-05-18 | haber_uzun_backtest.py | 30 günlük P&L simülasyonu | %+3.5 kâr, %37.5 başarı |
| 2026-05-19 | Python 3.12 kurulumu | FinBERT için gerekiyordu | Fedora dnf ile kuruldu |
| 2026-05-19 | ~/finbert-env oluşturuldu | torch + transformers Python 3.14 ile çakışıyor | Ayrı venv, Python 3.12.13 |
| 2026-05-19 | finbert_agent.py | Claude maliyet düşürme | Subprocess köprüsü, yerel sentiment |
| 2026-05-19 | news_agent.py — FinBERT entegrasyonu | RSS haberleri artık Claude'a gitmiyor | %80-90 Claude maliyet düşüşü |
| 2026-05-19 | finbert_agent.py — `_altin_yonu_duzelt()` | FinBERT hisse senedi eğitimi yanlış etiketliyordu | ~100 kalıp ifade listesi; otomatik düzeltme |
| 2026-05-19 | main.py — günlük zarar takibi | Canlı botta max günlük zarar sınırı yoktu | `_gunluk_zarar`, `_zarar_ekle()`, gece sıfırlama |
| 2026-05-19 | config.py — `MAX_GUNLUK_ZARAR = 75.0` | Zarar limitini yapılandırılabilir yapmak | main.py ile birlikte çalışıyor |
| 2026-05-19 | PROJE.md oluşturuldu | Projeyi yeni session'da hızlı anlamak | Bu dosya |
| 2026-05-20 | `backtest/veri_yukle.py` oluşturuldu | 17 yıllık M1 histdata yükleyici gerekiyordu | `yukle_yil(yil)` + `yukle_aralik(bas, bit)` fonksiyonları; 15m/1sa/1D örnekleme destekli |
| 2026-05-20 | `backtest/motor.py` — `calistir_df()` eklendi | DataFrame girişli backtest gerekiyordu (CSV okumadan) | Grafik üretmez; `(stats, islem_df, portfoy_df)` döner; `ilerleme=True` ile ilerleme göstergesi |
| 2026-05-20 | `backtest/histdata_backtest.py` oluşturuldu | 2009–2025 arası 17 yıllık tam doğrulama | 396k mum, 1.691 işlem, $1k→$19.5k (+%1857), CAGR %19,1; yıllık rapor + grafik + CSV |
| 2026-05-20 | `decision_agent.py` — güven=0 bug'ı düzeltildi | Breakout AL + hafif BEARISH makro + BEARISH haber → guven zorla 0 oluyordu | `makro_mesaj` eşiği ±3/±8 tutarlı hale getirildi; zayıf çelişki artık BEKLE zorlamıyor; debug `[decision_agent]` logları eklendi |
| 2026-05-20 | `backtest/ml_veri/ozellik_olustur.py` oluşturuldu | 17 yıllık veriyle ML feature engineering | 5.88M 1dk mum → 396.254 adet 15dk özellik satırı; RSI/MACD/BB/ADX/MA oran/volatilite/ATR + 3 yeni özellik (yön_3, momentum_5, rsi_hiz) + saat/gün; 7 saniye |
| 2026-05-20 | `backtest/ml_veri/model_egit.py` oluşturuldu | Claude'a bağımlılık azaltma — ilk ML modeli | XGBoost 300 ağaç; 2009-2022 eğitim / 2023-2025 test; balanced×3x BEKLE ağırlığı; prob eşiği=0.40; en önemli özellik: saat (101.3), atr (73.9) |
| 2026-07-26 | Git sürüm kontrolü kuruldu (`git init -b main`) | Strateji denemeleri (Motor v4 ADX %3 → %1 gibi) arasında geri dönüş/karşılaştırma yoktu; eski kod sürümleri kayboluyordu | Yerel depo, uzak sunucu yok. İlk commit: 28 dosya / 9.598 satır / 516 KB. Git kimliği: Berk \<berkereny@gmail.com\> (global) |
| 2026-07-26 | `.gitignore` oluşturuldu | 757 MB'lık klasörden sadece kodun takip edilmesi ve `.env` sızıntısının engellenmesi | `.env`, `backtest/veri/` (671 MB), `features.csv` (82 MB), `*.pkl`, `*.png`, `__pycache__`, `haber_gecmis.json` takip dışı. Commit öncesi kodda gömülü API anahtarı taraması yapıldı — temiz |

---

## 12. AKTİF SORUNLAR

### ~~Sorun 1: FinBERT altın için ters etiketleyebiliyor~~ — **ÇÖZÜLDÜ** (2026-05-19)

**Tanım:** "Gold surges as dollar weakens" → BEARISH %94.1 döndü (altın için BULLISH olmalıydı).

**Kök neden:** ProsusAI/finbert hisse senedi analizleri için eğitilmiş.

**Uygulanan çözüm:** `finbert_agent._altin_yonu_duzelt()` fonksiyonu eklendi.
- ~50 BULLISH kalıp ("gold surges", "dollar weakens", "rate cut", "safe haven" vb.)
- ~55 BEARISH kalıp ("gold falls", "dollar strengthens", "rate hike", "hawkish" vb.)
- Net puan yönü belirler; güven yeniden hesaplanır
- 22 cümlelik test seti ile doğrulanabilir: `python3 agents/finbert_agent.py`

**Kalan risk:** Listede olmayan nüanslı ifadeler hâlâ yanlış etiketlenebilir; fine-tuned model uzun vadede daha iyi çözüm olur.

---

### Sorun 2: Backtest haber sentiment tümü BULLISH

**Tanım:** 30 günlük backtest'te 31 günün tümü BULLISH → gerçekçi değil.

**Kök neden:** Claude Haiku'nun bilgi kesim tarihi Ağustos 2025. Nisan-Mayıs 2026 olaylarını bilmiyor; genel Fed politikası tahmininden BULLISH üretiyor.

**Denenmiş çözümler:** Prompt değiştirildi ("tahmin üret" ifadesi eklendi) ama hâlâ tümü BULLISH.

**Önerilen çözüm:** Gerçek tarihsel haber API (newsapi.org, GDELT) veya finansal veri sağlayıcısı (Refinitiv, Bloomberg) entegrasyonu.

---

### Sorun 3: BEKLEME_DAKIKA config'de var ama kullanılmıyor

**Tanım:** `config.BEKLEME_DAKIKA = 15` tanımlı ama `main.py` `time.sleep(60)` kullanıyor.

**Kök neden:** main.py yeniden yazıldığında config değeri güncellenmedi.

**Önerilen çözüm:** `config.BEKLEME_DAKIKA` kaldır veya main.py'yı bunu kullansın.

---

### Sorun 4: sudo chronyc headless sistemde çalışmayabilir

**Tanım:** `senkronize_et()` > 1000ms sapma durumunda `sudo chronyc makestep` çalıştırıyor ama sudo şifre istiyor.

**Kök neden:** Headless (şifresiz sudo) konfigüre edilmemiş.

**Önerilen çözüm:** `/etc/sudoers.d/chronyc` dosyasına `Berk ALL=(ALL) NOPASSWD: /usr/bin/chronyc makestep` ekle.

---

### Sorun 5: haber_gecmis.json zamanla eskiyor

**Tanım:** 30 günlük backtest önbelleği kalıcı JSON'a yazılıyor. Farklı tarih aralığı test edilince eski veriler çakışabilir.

**Önerilen çözüm:** Önbellekte tarihe göre key kullanılıyor (zaten var), sadece eski kayıtları silinmesine gerek yok. Yeni tarihler otomatik ekleniyor.

---

## 13. SIRADAKİ ADIMLAR

> **NOT (Claude için):** Bu bölüm yalnızca bilgi amaçlı bir kayıt listesidir.
> Buradaki hiçbir madde otomatik olarak uygulanmaz.
> Kullanıcı açıkça "şunu yap" demeden herhangi bir adım başlatma.

| Öncelik | Ne yapılacak | Neden önemli | Nasıl yapılacak | Zorluk |
|---------|-------------|-------------|----------------|--------|
| ~~1~~ | ~~FinBERT etiketi altın için kalibre et~~ | ~~Yanlış sentiment~~ | **TAMAMLANDI** — `_altin_yonu_duzelt()` eklendi | — |
| ~~3~~ | ~~Günlük P&L kaydı / max günlük zarar takibi~~ | ~~Kârlılığı takip etmek~~ | **TAMAMLANDI** — main.py `_gunluk_zarar` sistemi | — |
| ~~—~~ | ~~17 yıllık histdata backtesti~~ | ~~Uzun vadeli strateji doğrulaması~~ | **TAMAMLANDI** — `histdata_backtest.py`, CAGR %19,1 | — |
| 1 | Canlı testnet döngüsü başlat | Teorik backtest yeterli değil, gerçek Binance davranışını görmek lazım | `python3 main.py` ile 1 hafta çalıştır | Düşük |
| 2 | Günlük P&L Telegram özeti | Kaç işlem, günlük K/Z gece raporu | `bildir_ozet()` çağrısını main.py'ya ekle (gece 00:00 sıfırlama sırasında) | Düşük |
| 3 | Kaldıraç / position sizing iyileştirmesi | 17 yıllık backtest; yıllık max DD -%37–-%41'e kadar çıkıyor, hedef -%15 aşılıyor | `KALDIRAC_UZUN` 3x → 2x veya volatiliteye göre dinamik pozisyon boyutu | Orta |
| 4 | Gerçek tarihsel haber API | 30g backtest haberlerinin gerçek olması | newsapi.org ücretsiz plan (100 req/gün) | Orta |
| 5 | sudo chronyc headless fix | Zaman sapmasında bot manuel müdahale bekliyor | /etc/sudoers.d/chronyc NOPASSWD | Düşük |
| 6 | BEKLEME_DAKIKA config temizliği | Kafa karışıklığı (tanımlı ama kullanılmıyor) | config'den sil | Çok düşük |
| ~~7~~ | ~~Makine öğrenmesi modeli (feature eng + ilk model)~~ | ~~Claude'a bağımlılığı azaltmak~~ | **DEVAM EDİYOR** — `ozellik_olustur.py` + `model_egit.py` tamamlandı; precision AL=0.36 @ eşik=0.50; canlı bot entegrasyonu bekliyor | Yüksek |
| 7a | ML modeli canlı bota entegre et | Gerçek zamanlı sinyal üretimi | `decision_agent`'a `model.pkl` skoru ek girdi olarak ver; eşik=0.45–0.50 | Orta |
| 7b | ML precision > 0.40 hedefi | Daha güvenilir sinyal | RSI divergence, fiyat pattern, orderbook özellikleri ekle veya SMOTE | Yüksek |
| 8 | Gerçek paraya geçiş | Nihai hedef | Testnet'te 2 hafta tutarlı kâr → TESTNET=False | Çok yüksek |

---

## 14. ÖNEMLİ KARARLAR VE NEDENLERİ

### Karar 1: İki ayrı Python ortamı

- **Karar:** gold-bot (Python 3.14) + finbert-env (Python 3.12) ayrı tutuldu
- **Neden:** FinBERT için torch 2.12, Python 3.14 ile uyumsuz
- **Alternatifler:** Sadece Python 3.12 kullanmak (gold-bot kütüphaneleri yeniden kurulurdu), Docker container
- **Sonuç:** subprocess köprüsü temiz çalışıyor; her FinBERT çağrısı ~2-3s gecikme yaratiyor

### Karar 2: FinBERT → Claude sadece etki≥9'da

- **Karar:** RSS haberleri FinBERT'e, sadece kritik haberler Claude'a
- **Neden:** Her haber için Claude Haiku çağrısı maliyetli (~$0.01/çağrı, saatte 10-30 haber)
- **Alternatifler:** Tüm haberler için Claude, tüm haberler için FinBERT
- **Sonuç:** %80-90 Claude maliyet düşüşü, kalite makul

### Karar 3: Breakout yoksa Claude çağrılmaz

- **Karar:** Kısa vadeli döngüde breakout olmadan teknik/risk/karar ajanları çağrılmıyor
- **Neden:** Dakikada birden fazla Claude çağrısı maliyeti dakikada $0.03+
- **Alternatifler:** Her dakika tüm pipeline çalıştır
- **Sonuç:** Çoğu dakika 0 API çağrısı; sadece anlamlı fırsat olduğunda maliyet oluşuyor

### Karar 4: ATR tabanlı dinamik SL/TP (canlı bot)

- **Karar:** Sabit yüzde yerine ATR × çarpan
- **Neden:** Volatilite değişkenliğine göre uyum; sakin piyasada SL çok küçük, hareketli piyasada çok büyük olmamalı
- **Alternatifler:** Sabit %0.5 SL, sabit %1 TP
- **Sonuç:** Backtest'te daha anlamlı SL/TP seviyeleri, daha az erken durdurulma

### Karar 5: threading.Lock ile paylaşılan durum

- **Karar:** Makro/takvim/haber raporları module-level dict + Lock
- **Neden:** Kısa ve uzun vadeli döngüler aynı bağlam verilerini okuyor
- **Alternatifler:** Her döngüde ayrı API çağrısı, queue sistemi
- **Sonuç:** Thread-safe okuma, gereksiz tekrar API çağrısı yok

### Karar 6: TESTNET=True varsayılan

- **Karar:** Kod açılıştan testnet'e bağlanır
- **Neden:** Kod hatası gerçek para kaybettirmesin
- **Sonuç:** Güvenli geliştirme ortamı; gerçeğe geçiş bilinçli adım

---

## 15. BİLİNEN KISITLAMALAR

### Python 3.14 uyumsuzlukları

- `torch` Python 3.14 ile resmi destek yok; FinBERT için Python 3.12 gerekti
- Subprocess köprüsü ~2-3 saniye gecikme ekliyor (her FinBERT çağrısı)
- Gelecekte torch 3.14 desteği gelirse tek ortama geçilebilir

### API limitleri

| Servis | Limit | Aşıldığında |
|--------|-------|------------|
| Binance futures_klines | max limit=1500 mum/istek | 30 gün için 2 istek gerekiyor |
| Claude Haiku | Rate limit yok (ücretli) | Anlık hata, retry yok |
| yfinance | Throttling mümkün | Cache ile azaltılıyor |
| investing.com | Bot koruması olabilir | Exception'da NORMAL mod |

### Backtest kısıtlamaları

- `motor.py` gerçek emir maliyeti (spread, slippage) hesaba katmıyor
- `haber_uzun_backtest.py` tek pozisyon (aynı anda 1 işlem) kısıtlı
- Testnet fiyatları gerçek Binance fiyatlarından farklı olabiliyor
- Tarihsel Claude çağrısı bilgi kesiminden sonrası için anlamsız

### Bilgi kesim tarihi sorunu

- Claude modelleri Ağustos 2025 sonrasını bilmiyor
- Backtest'te Nisan-Mayıs 2026 haberleri gerçekçi üretilemiyor
- Çözüm: Gerçek tarihsel haber API (newsapi.org, GDELT Project)

---

## 16. MALİYET ANALİZİ

### Günlük tahmini API maliyeti

**Kısa vadeli döngü (her dakika, breakout varsa):**
- technical_agent: claude-sonnet-4-6, ~150 token çıktı → ~$0.001/çağrı
- risk_agent: claude-sonnet-4-6, ~150 token → ~$0.001/çağrı
- decision_agent: claude-sonnet-4-6, ~200 token → ~$0.001/çağrı
- Breakout sıklığı: tipik olarak saatte 0-3 kez → günlük 0-72 breakout
- Günlük tahmini (10 breakout × 3 ajan): **~$0.03**

**Uzun vadeli döngü (4 saatte bir = günde 6 kez):**
- 3 ajan × 6 çağrı → **~$0.018/gün**

**Haber analizi:**
- FinBERT: ücretsiz
- Claude Haiku (etki≥9): saatte 0-1 kritik haber → günde 0-24 çağrı → **~$0.01-0.05/gün**

**Toplam günlük:** ~$0.05–$0.10

### Aylık tahmini maliyet

- **Tahmini:** $1.50–$3.00/ay (aktif trading günleri)
- **Düşük trafik:** (hafta sonu, az breakout) $0.50/ay
- **Yoğun trafik:** (yüksek volatilite, çok breakout) $5.00/ay

### FinBERT entegrasyonu öncesi/sonrası

| | Önceki | Sonrası |
|--|-------|--------|
| RSS haber başına | Claude Haiku çağrısı | FinBERT (ücretsiz) |
| Saatlik Claude çağrısı (haberler) | 10-30 çağrı | 0-2 çağrı (sadece kritik) |
| Aylık haber maliyeti | ~$3-9 | ~$0.30-$0.90 |
| **Toplam düşüş** | — | **%80-90** |

### API maliyetini karşılamak için minimum kâr

- Aylık API maliyet: ~$3
- 0.01 oz, tek işlem TP: ~$90 (fiyat ~$4500, %2 TP) → ~$5.40 gerçek kâr (3x kaldıraç)
- Ayda **1 başarılı işlem** yeterli maliyeti karşılamak için

---

## 17. RİSK YÖNETİMİ

### Mevcut risk parametreleri (config.py)

```
MAX_STOP_LOSS_PCT   = 1.0  → maksimum SL: fiyatın %1'i
MAX_TAKE_PROFIT_PCT = 2.0  → hedef TP: fiyatın %2'i
MAX_GUNLUK_ZARAR    = 75.0 → günlük max zarar ($) — aşılınca o gün işlem yok
MIN_GUVEN_SKORU     = 6    → karar güveni bu altında → emir yok
QUANTITY            = 0.01 → 0.01 oz ≈ $45 nominal pozisyon
KALDIRAC_KISA       = 10   → 10× kaldıraç (kısa vadeli)
KALDIRAC_UZUN       = 3    → 3× kaldıraç (uzun vadeli)
```

### Kaldıraç seviyeleri ve gerekçeleri

| Katman | Kaldıraç | Gerekçe |
|--------|---------|--------|
| Kısa vadeli (breakout) | 10x | Kırılım hızlı gelişir, küçük hareket yeterli; fırsat kısa süreli |
| Uzun vadeli (RSI/MACD) | 3x | Trend takibi, pozisyon daha uzun tutulur; 10x risk ajanı çok bloke eder |

**Gerçek para için öneri:** Kısa vadeli 10x → 5x veya 3x'e düşür.

### Günlük max zarar limiti

- `motor.py` ve `strateji_breakout.py`'de: `max_gunluk_zarar = $75` (hardcoded)
- Canlı bot (`main.py`): **günlük zarar takibi MEVCUT** (`_gunluk_zarar`, `_zarar_ekle()`, `_gun_kontrol()`)
  - Her emir açılışında SL zararı potansiyeli `_gunluk_zarar` sayacına eklenir
  - `config.MAX_GUNLUK_ZARAR = 75.0` aşılınca `_gunluk_zarar_durdu = True` → o gün işlem yok
  - Telegram'a uyarı gönderilir
  - Gece 00:00 geçişinde `_gun_kontrol()` ile sıfırlanır

### Stop-loss/take-profit mantığı

**Canlı bot:**
```
SL = fiyat × (1 ± stop_loss_pct/100)   # max %1, Claude'un önerisi sınırlanır
TP = fiyat × (1 ± take_profit_pct/100) # max %2
```
Binance'e `STOP_MARKET` + `TAKE_PROFIT_MARKET` emirleri ayrı ayrı gönderilir.

**Backtest (haber_uzun_backtest.py):**
```
SL = giriş × (1 ± 0.01)  → kaldıraçla portföyün %3'ü
TP = giriş × (1 ± 0.02)  → kaldıraçla portföyün %6'sı
```

### Kod seviyesi güvenlik katmanları

1. `TESTNET=True` varsayılan — yanlışlıkla gerçek para kullanımı engellenir
2. `MIN_GUVEN_SKORU=6` — düşük güven sinyallerinde emir yok
3. Risk ajanı HAYIR → decision'a bile sorulmaz
4. Takvim YUKSEK_RISK → tüm işlemler durdurulur
5. Makro+haber çelişki → BEKLE
6. 3× retry — geçici bağlantı hatası işlemi durdurmaz
7. `MAX_GUNLUK_ZARAR=75.0` — günlük zarar limiti aşılınca o gün işlem yok; Telegram uyarısı

---

## 18. PERFORMANS HEDEFLERİ

| Metrik | Minimum | Hedef | Mevcut (30g backtest) |
|--------|---------|-------|----------------------|
| Başarı oranı | %40 | %50 | %37.5 |
| Aylık getiri | %3 | %8 | %3.5 (30g) |
| Max drawdown | <%20 | <%10 | hesaplanmadı |
| Günlük Claude maliyeti | <$0.50 | <$0.10 | ~$0.05-0.10 (tahmin) |
| Aylık maliyet | <$5 | <$3 | ~$1.5-3 (tahmin) |
| API maliyetini karşılamak için min kâr | $3/ay | $15/ay | — |
| Gerçek paraya geçiş kriteri | 2 hafta + tutarlı testnet kârı | Drawdown <%10 | Henüz başlanmadı |

**Not:** %37.5 başarı oranı, 2:1 TP/SL oranı ile matematiksel olarak kârlı.  
Beklenti değeri: `0.375 × 2 - 0.625 × 1 = 0.125 > 0` → pozitif beklenti var.
