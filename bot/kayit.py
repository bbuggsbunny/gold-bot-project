"""
bot/kayit.py
────────────
Kalıcı karar ve işlem kaydı.

Neden var: bot her şeyi stdout'a basıyordu. Bir haftalık testnet koşusunun
sonunda "kaç sinyal üretildi, hangi güven skorlarıyla, kaçı emre dönüştü"
sorusu cevapsız kalıyordu. Bu aynı zamanda pozisyon boyutu kararı için
(PROJE.md Bölüm 12, Sorun 6/7) ihtiyaç duyulan veri.

Her analiz döngüsü bir satır yazar — breakout bulunamayıp erken çıkanlar
dahil. `asama` sütunu döngünün nereye kadar gittiğini söyler:

    veri_hatasi   — fiyat verisi alınamadı
    zarar_limiti  — günlük zarar limiti dolu, işlem yok
    takvim_bloke  — YUKSEK_RISK takvim modu
    breakout_yok  — kısa katman, kırılım yok (Claude'a gidilmedi)
    karar         — tam zincir çalıştı, emir açılmadı
    emir          — emir gönderildi
"""
import csv
import json
from datetime import date, datetime
from pathlib import Path

KAYIT_DIR   = Path(__file__).resolve().parents[1] / "kayitlar"
KARAR_CSV   = KAYIT_DIR / "kararlar.csv"
DURUM_JSON  = KAYIT_DIR / "gunluk_durum.json"

SUTUNLAR = [
    "zaman", "katman", "asama", "fiyat",
    "sinyal", "risk", "onay", "karar", "guven",
    "emir_durum", "sl", "tp", "kaldirac", "gerekce",
]


class Kayitci:
    """Kararları CSV'ye ekler, gün sonu istatistiğini üretir."""

    def __init__(self, csv_yolu: Path = KARAR_CSV, durum_yolu: Path = DURUM_JSON):
        self.csv_yolu  = Path(csv_yolu)
        self.durum_yolu = Path(durum_yolu)
        self.csv_yolu.parent.mkdir(parents=True, exist_ok=True)
        if not self.csv_yolu.exists():
            with self.csv_yolu.open("w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(SUTUNLAR)

    # ── Yazma ────────────────────────────────────────────────────
    def yaz(self, katman: str, asama: str, fiyat: float = 0.0,
            sinyal: str = "", risk: str = "", onay: str = "",
            karar: str = "", guven: int = 0, emir_durum: str = "",
            sl: float = 0.0, tp: float = 0.0, kaldirac: int = 0,
            gerekce: str = "") -> None:
        satir = {
            "zaman": datetime.now().isoformat(timespec="seconds"),
            "katman": katman, "asama": asama, "fiyat": fiyat,
            "sinyal": sinyal, "risk": risk, "onay": onay,
            "karar": karar, "guven": guven, "emir_durum": emir_durum,
            "sl": sl, "tp": tp, "kaldirac": kaldirac,
            "gerekce": (gerekce or "").replace("\n", " ")[:200],
        }
        try:
            with self.csv_yolu.open("a", newline="", encoding="utf-8") as f:
                csv.DictWriter(f, fieldnames=SUTUNLAR).writerow(satir)
        except Exception as e:
            # Kayıt tutamamak botu durdurmamalı
            print(f"  [KAYIT] ⚠️  Yazılamadı: {e}")

    # ── Okuma ────────────────────────────────────────────────────
    def gun_istatistigi(self, gun: date) -> dict:
        """Verilen günün özet sayıları."""
        onek = gun.isoformat()
        istatistik = {
            "dongu": 0, "karar_asamasi": 0, "emir": 0,
            "al": 0, "sat": 0, "bekle": 0,
            "breakout_yok": 0, "guven_toplam": 0,
        }
        try:
            with self.csv_yolu.open(newline="", encoding="utf-8") as f:
                for satir in csv.DictReader(f):
                    if not satir.get("zaman", "").startswith(onek):
                        continue
                    istatistik["dongu"] += 1
                    asama = satir.get("asama", "")
                    if asama == "breakout_yok":
                        istatistik["breakout_yok"] += 1
                    if asama in ("karar", "emir"):
                        istatistik["karar_asamasi"] += 1
                        istatistik["guven_toplam"] += int(satir.get("guven") or 0)
                        karar = satir.get("karar", "")
                        if karar == "AL":
                            istatistik["al"] += 1
                        elif karar == "SAT":
                            istatistik["sat"] += 1
                        else:
                            istatistik["bekle"] += 1
                    if asama == "emir":
                        istatistik["emir"] += 1
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"  [KAYIT] ⚠️  Okunamadı: {e}")

        n = istatistik["karar_asamasi"]
        istatistik["ort_guven"] = (istatistik["guven_toplam"] / n) if n else 0.0
        return istatistik

    # ── Gün sonu bakiye takibi ───────────────────────────────────
    def onceki_bakiye(self) -> float | None:
        try:
            return json.loads(self.durum_yolu.read_text(encoding="utf-8")).get("bakiye")
        except Exception:
            return None

    def bakiye_kaydet(self, bakiye: float) -> None:
        try:
            self.durum_yolu.write_text(
                json.dumps({"bakiye": bakiye,
                            "guncelleme": datetime.now().isoformat(timespec="seconds")},
                           ensure_ascii=False),
                encoding="utf-8")
        except Exception as e:
            print(f"  [KAYIT] ⚠️  Bakiye kaydedilemedi: {e}")
