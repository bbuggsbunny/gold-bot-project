"""
tipler.py
─────────
Ajanlar arasındaki veri sözleşmeleri.

NEDEN DATACLASS
    Önceden her ajan serbest bir `dict` döndürüyordu; hangi anahtarın var
    olduğu hiçbir yerde yazılı değildi. 2026-07-26'da decision_agent,
    technical_agent'ta bulunmayan bir anahtarı okudu; oluşan KeyError
    prompt'un içinde sessizce yutuldu ve bot iki ay boyunca hiç işlem
    açmadı.

    Dataclass ile olmayan bir alan AttributeError verir — bir sözlükte
    sessizce yutulabilen KeyError değil — ve her ajanın ne döndürdüğü
    tek yerde okunur.

HATA YOLU
    Davranış eskisiyle aynı: her tipin `durum` alanı "ok" veya "hata".
    Ajanların hata dönüşleri `.hata(mesaj)` sınıf metoduyla üretilir,
    diğer alanlar güvenli varsayılanlarında kalır.

    Alanların tamamı kw_only — yeni alan eklerken sıralama derdi olmaz
    ve çağrı yerlerinde alan adı zorunlu olduğu için karışma olmaz.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict


# ══════════════════════════════════════════════════════════════════════
# Ortak taban
# ══════════════════════════════════════════════════════════════════════
@dataclass(kw_only=True)
class Rapor:
    """Tüm ajan çıktılarının ortak tabanı."""
    durum: str = "ok"
    mesaj: str = ""

    @property
    def basarili(self) -> bool:
        return self.durum == "ok"

    @classmethod
    def hata(cls, mesaj: str):
        """Ajanın hata dönüşü — alanlar güvenli varsayılanlarında kalır."""
        return cls(durum="hata", mesaj=str(mesaj))

    def sozluk(self) -> dict:
        """Loglama/JSON için düz sözlük."""
        return asdict(self)


# ══════════════════════════════════════════════════════════════════════
# data_agent çıktıları
# ══════════════════════════════════════════════════════════════════════
@dataclass(kw_only=True)
class TeknikVeri(Rapor):
    """Fiyat verisinin iki katmanda da ortak olan alanları."""
    mod: str
    fiyat: float = 0.0
    degisim_pct: float = 0.0
    atr: float = 0.0
    son_5_kapanis: list[float] = field(default_factory=list)


@dataclass(kw_only=True)
class KisaVeri(TeknikVeri):
    """1 dakikalık mum + breakout seviyeleri (kısa vadeli katman)."""
    mod: str = "kisa"
    yuksek: float = 0.0
    dusuk: float = 0.0
    direnc: float = 0.0        # son 20 mumun en yükseği
    destek: float = 0.0        # son 20 mumun en düşüğü
    hacim: float = 0.0
    hacim_ort: float = 0.0
    hacim_teyit: bool = False
    breakout: str = "YOK"      # YUKARI | ASAGI | YOK


@dataclass(kw_only=True)
class UzunVeri(TeknikVeri):
    """15 dakikalık mum + RSI/MACD/BB (uzun vadeli katman)."""
    mod: str = "uzun"
    rsi: float = 50.0
    rsi_yorum: str = "NOTR"    # ASIRI_SATILMIS | ASIRI_ALINMIS | NOTR
    macd: float = 0.0
    macd_sinyal: float = 0.0
    macd_hist: float = 0.0
    ma20: float = 0.0
    ma50: float = 0.0
    bb_ust: float = 0.0
    bb_alt: float = 0.0
    trend: str = "NOTR"        # YUKARI | ASAGI


# ══════════════════════════════════════════════════════════════════════
# Analiz zinciri
# ══════════════════════════════════════════════════════════════════════
@dataclass(kw_only=True)
class TeknikAnaliz(Rapor):
    """technical_agent çıktısı — Claude'un teknik sinyali."""
    mod: str = "uzun"
    sinyal: str = "NOTR"       # GUCLU_AL | ZAYIF_AL | NOTR | ZAYIF_SAT | GUCLU_SAT
    sl: float = 0.0
    tp: float = 0.0
    yorum: str = ""


@dataclass(kw_only=True)
class RiskRaporu(Rapor):
    """risk_agent çıktısı. Hata durumunda onay HAYIR'da kalır."""
    risk: str = "COK_YUKSEK"   # DUSUK | ORTA | YUKSEK | COK_YUKSEK
    onay: str = "HAYIR"        # EVET | HAYIR
    max_pozisyon: float = 0.0
    uyari: str = ""

    @property
    def onayli(self) -> bool:
        return self.onay == "EVET"


@dataclass(kw_only=True)
class Karar(Rapor):
    """
    decision_agent çıktısı — nihai al/sat/bekle.

    Alan adı `eylem`; Claude'a gönderilen JSON'da anahtar hâlâ "karar"
    (prompt değişmedi), yalnızca kod içindeki isim okunabilir olsun diye
    farklı.
    """
    eylem: str = "BEKLE"       # AL | SAT | BEKLE
    guven: int = 0             # 1-10
    stop_loss_pct: float = 0.5
    take_profit_pct: float = 1.0
    gerekce: str = ""

    @property
    def islem_var(self) -> bool:
        return self.eylem in ("AL", "SAT")


@dataclass(kw_only=True)
class EmirSonucu(Rapor):
    """
    order_agent çıktısı.

    durum: ok | bekle | dusuk_guven | hata
    """
    islem: str = ""            # AL | SAT
    fiyat: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    emir_id: int = 0


# ══════════════════════════════════════════════════════════════════════
# Bağlam ajanları (1b adımında ajanlar bu tiplere geçirilecek)
# ══════════════════════════════════════════════════════════════════════
@dataclass(kw_only=True)
class Olay:
    """Ekonomik takvim olayı. Yaklaşan olayda saat_sonra, açıklananda saat_once dolu."""
    isim: str
    etki: int                  # 1-10
    saat_sonra: float | None = None
    saat_once: float | None = None


@dataclass(kw_only=True)
class HaberRaporu(Rapor):
    """news_agent çıktısı."""
    sentiment: str = "NOTR"    # BULLISH | BEARISH | NOTR
    haber_skoru: float = 0.0
    etki: int = 0
    kategori: str = "DIGER"
    ozet: str = ""
    son_haberler: list[dict] = field(default_factory=list)


@dataclass(kw_only=True)
class MakroRaporu(Rapor):
    """macro_agent çıktısı — DXY/VIX/TNX/SP500 birleşik skoru."""
    skor: float = 0.0
    yorum: str = "NOTR"
    dxy_degisim: float = 0.0
    vix_degisim: float = 0.0
    tnx_degisim: float = 0.0
    sp500_degisim: float = 0.0
    detay: dict = field(default_factory=dict)


@dataclass(kw_only=True)
class TakvimRaporu(Rapor):
    """calendar_agent çıktısı."""
    mod: str = "NORMAL"        # NORMAL | DIKKATLI | YUKSEK_RISK
    yaklasan_olaylar: list[Olay] = field(default_factory=list)
    aciklanan_olaylar: list[Olay] = field(default_factory=list)
