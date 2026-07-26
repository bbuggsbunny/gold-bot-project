#!/usr/bin/env python3
"""
testler/rapor.py
────────────────
kayitlar/kararlar.csv'yi okuyup okunabilir özet basar.

Botun o an çalışıyor olmasına gerek yok — kayıt dosyası her koşuda
birikiyor, bu betik istediğin zaman geçmişe bakar.

Kullanım:
    python3 testler/rapor.py               # tüm günler + genel toplam
    python3 testler/rapor.py 2026-07-27    # tek gün, ayrıntılı
    python3 testler/rapor.py --kararlar    # sadece AL/SAT kararlarını listele
"""
import csv
import sys
import os
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.kayit import KARAR_CSV

CIZGI = "─" * 74

ASAMA_ETIKET = {
    "veri_hatasi":  "veri hatası",
    "zarar_limiti": "zarar limiti",
    "takvim_bloke": "takvim bloke",
    "breakout_yok": "breakout yok",
    "karar":        "karar verildi",
    "emir":         "EMİR",
}


def satirlari_oku(yol=KARAR_CSV) -> list[dict]:
    if not os.path.exists(yol):
        print(f"Kayıt dosyası yok: {yol}")
        print("Bot henüz hiç çalışmamış olabilir.")
        sys.exit(1)
    with open(yol, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def gune_gore(satirlar) -> dict:
    gunler = defaultdict(list)
    for s in satirlar:
        gunler[s["zaman"][:10]].append(s)
    return dict(sorted(gunler.items()))


def _sayi(s, alan, varsayilan=0.0):
    try:
        return float(s.get(alan) or varsayilan)
    except ValueError:
        return varsayilan


def gun_ozeti(gun: str, satirlar: list[dict], ayrintili=False):
    asamalar = Counter(s["asama"] for s in satirlar)
    kararlar = Counter(s["karar"] for s in satirlar if s["asama"] in ("karar", "emir"))
    katmanlar = Counter(s["katman"] for s in satirlar)

    karar_satirlari = [s for s in satirlar if s["asama"] in ("karar", "emir")]
    guvenler = [_sayi(s, "guven") for s in karar_satirlari]
    fiyatlar = [_sayi(s, "fiyat") for s in satirlar if _sayi(s, "fiyat") > 0]

    ilk = satirlar[0]["zaman"][11:16]
    son = satirlar[-1]["zaman"][11:16]

    print(f"\n{gun}  ({ilk}–{son})")
    print(f"  Döngü: {len(satirlar):<5} "
          f"KISA:{katmanlar.get('KISA', 0)}  UZUN:{katmanlar.get('UZUN', 0)}")

    parcalar = [f"{ASAMA_ETIKET.get(a, a)}:{n}"
                for a, n in asamalar.most_common()]
    print(f"  Aşama: {'  '.join(parcalar)}")

    if karar_satirlari:
        ort = sum(guvenler) / len(guvenler)
        print(f"  Karar: AL:{kararlar.get('AL', 0)}  SAT:{kararlar.get('SAT', 0)}  "
              f"BEKLE:{kararlar.get('BEKLE', 0)}  |  ort. güven {ort:.1f}/10  "
              f"(en yüksek {max(guvenler):.0f})")
    else:
        print("  Karar: — (hiçbir döngü karar aşamasına gelmedi)")

    if fiyatlar:
        print(f"  Fiyat: {min(fiyatlar):.2f} – {max(fiyatlar):.2f}")

    emirler = [s for s in satirlar if s["asama"] == "emir"]
    if emirler:
        print(f"  ► {len(emirler)} EMİR:")
        for e in emirler:
            print(f"      {e['zaman'][11:16]} {e['katman']:<5} {e['karar']:<4} "
                  f"@ {_sayi(e, 'fiyat'):.2f}  SL {_sayi(e, 'sl'):.2f} / "
                  f"TP {_sayi(e, 'tp'):.2f}  {int(_sayi(e, 'kaldirac'))}x  "
                  f"güven {int(_sayi(e, 'guven'))}")

    if ayrintili and karar_satirlari:
        print(f"\n  Karar aşamasına gelen döngüler:")
        print(f"  {'saat':<6} {'kat':<5} {'sinyal':<10} {'risk':<11} "
              f"{'onay':<5} {'karar':<6} {'güven':>5}  gerekçe")
        print("  " + "-" * 70)
        for s in karar_satirlari:
            print(f"  {s['zaman'][11:16]:<6} {s['katman']:<5} {s['sinyal']:<10} "
                  f"{s['risk']:<11} {s['onay']:<5} {s['karar']:<6} "
                  f"{int(_sayi(s, 'guven')):>5}  {s['gerekce'][:34]}")


def genel_toplam(gunler: dict):
    tum = [s for g in gunler.values() for s in g]
    asamalar = Counter(s["asama"] for s in tum)
    kararlar = Counter(s["karar"] for s in tum if s["asama"] in ("karar", "emir"))
    karar_say = asamalar.get("karar", 0) + asamalar.get("emir", 0)

    print(f"\n{CIZGI}\n  GENEL TOPLAM — {len(gunler)} gün\n{CIZGI}")
    print(f"  Toplam döngü          : {len(tum):,}")
    print(f"  Karar aşamasına gelen : {karar_say:,}"
          + (f"  (%{karar_say / len(tum) * 100:.1f})" if tum else ""))
    print(f"  Gönderilen emir       : {asamalar.get('emir', 0)}")
    print(f"  Karar dağılımı        : AL:{kararlar.get('AL', 0)}  "
          f"SAT:{kararlar.get('SAT', 0)}  BEKLE:{kararlar.get('BEKLE', 0)}")

    # Claude çağrısı = karar aşamasına gelen her döngüde 3 ajan
    print(f"  Tahmini Claude çağrısı: ~{karar_say * 3:,} "
          f"(karar aşaması × 3 ajan)")

    # BEKLE gerekçelerinin dağılımı — neyin engellediğini gösterir
    engeller = Counter()
    for s in tum:
        if s["asama"] in ("karar", "emir") and s["karar"] == "BEKLE":
            g = s["gerekce"]
            if "Risk ajani engelledi" in g:
                engeller["risk ajanı HAYIR dedi"] += 1
            elif "ekonomik veri" in g:
                engeller["takvim koruması"] += 1
            elif "çelişiyor" in g:
                engeller["makro/haber–teknik çelişkisi"] += 1
            else:
                engeller["güven eşiğinin altında"] += 1
    if engeller:
        print(f"\n  BEKLE sebepleri:")
        for sebep, n in engeller.most_common():
            print(f"    {n:>4}  {sebep}")

    if asamalar.get("breakout_yok"):
        oran = asamalar["breakout_yok"] / len(tum) * 100
        print(f"\n  Kısa katman döngülerinin %{oran:.0f}'ında breakout bulunamadı.")


def main():
    argumanlar = [a for a in sys.argv[1:] if not a.startswith("--")]
    ayrintili  = "--kararlar" in sys.argv

    satirlar = satirlari_oku()
    if not satirlar:
        print("Kayıt dosyası boş — bot henüz hiç döngü tamamlamamış.")
        return 0

    gunler = gune_gore(satirlar)

    print(CIZGI)
    print(f"  KARAR KAYDI RAPORU  —  {KARAR_CSV}")
    print(CIZGI)

    if argumanlar:
        gun = argumanlar[0]
        if gun not in gunler:
            print(f"\n{gun} için kayıt yok. Mevcut günler: {', '.join(gunler)}")
            return 1
        gun_ozeti(gun, gunler[gun], ayrintili=True)
    else:
        for gun, satir in gunler.items():
            gun_ozeti(gun, satir, ayrintili=ayrintili)
        if len(gunler) > 1 or True:
            genel_toplam(gunler)

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
