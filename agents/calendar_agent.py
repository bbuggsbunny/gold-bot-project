import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
import re

from tipler import Olay, TakvimRaporu

# ──────────────────────────────────────────
# Anahtar kelime → etki skoru
# ──────────────────────────────────────────
ETKI_KURALLARI = [
    (10, ["fomc", "fed", "interest rate decision", "federal funds rate"]),
    (9,  ["cpi", "inflation", "consumer price"]),
    (8,  ["nfp", "non-farm", "payroll", "gdp"]),
    (7,  ["ppi", "producer price", "pce", "unemployment"]),
    (6,  ["retail sales", "durable goods", "ism"]),
    (5,  ["trade balance", "housing", "building permits"]),
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.investing.com/economic-calendar/",
    "Content-Type": "application/x-www-form-urlencoded",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


def _etki_skoru(olay_adi: str) -> int:
    """Olay adına göre etki skoru döndürür. Eşleşme yoksa 0."""
    kucuk = olay_adi.lower()
    for etki, kelimeler in ETKI_KURALLARI:
        if any(k in kucuk for k in kelimeler):
            return etki
    return 0


def _takvim_cek(date_from: str, date_to: str) -> list:
    """
    Investing.com'dan etkinlik listesi çeker.
    Her eleman: {"isim": str, "zaman": datetime}
    """
    resp = requests.post(
        "https://www.investing.com/economic-calendar/Service/getCalendarFilteredData",
        headers=HEADERS,
        data={
            "country[]": "5",          # ABD
            "dateFrom":  date_from,
            "dateTo":    date_to,
            "timeZone":  "55",         # UTC
            "timeFilter": "timeRemain",
            "currentTab": "custom",
            "submitFilters": "1",
            "limit_from": "0",
        },
        timeout=15,
    )
    resp.raise_for_status()

    json_veri = resp.json()
    html = json_veri.get("data", "")
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    satirlar = soup.find_all("tr", class_="js-event-item")

    olaylar = []
    for satir in satirlar:
        # Olay adı
        isim_td = satir.find("td", class_="event")
        if not isim_td:
            continue
        isim = isim_td.get_text(strip=True)

        # Zaman — data-event-datetime="2024/05/18 14:30:00"
        dt_str = satir.get("data-event-datetime", "")
        if not dt_str:
            continue
        try:
            zaman = datetime.strptime(dt_str.strip(), "%Y/%m/%d %H:%M:%S")
        except ValueError:
            continue

        olaylar.append({"isim": isim, "zaman": zaman})

    return olaylar


def _mod_belirle(yaklasan: list[Olay], aciklanan: list[Olay]) -> str:
    """
    YUKSEK_RISK: etki 8+ ve 2 saat içinde / son 30dk içinde
    DIKKATLI   : etki 7+ ve 4 saat içinde / son 1 saat içinde
    NORMAL     : diğer
    """
    for olay in yaklasan:
        if olay.etki >= 8 and olay.saat_sonra <= 2:
            return "YUKSEK_RISK"

    for olay in aciklanan:
        if olay.etki >= 8 and olay.saat_once <= 0.5:
            return "YUKSEK_RISK"

    for olay in yaklasan:
        if olay.etki >= 7 and olay.saat_sonra <= 4:
            return "DIKKATLI"

    for olay in aciklanan:
        if olay.etki >= 7 and olay.saat_once <= 1:
            return "DIKKATLI"

    return "NORMAL"


def calistir() -> TakvimRaporu:
    simdi = datetime.now(timezone.utc).replace(tzinfo=None)
    bugun  = simdi.strftime("%Y-%m-%d")
    yarin  = (simdi + timedelta(days=1)).strftime("%Y-%m-%d")

    try:
        olaylar = _takvim_cek(bugun, yarin)
    except Exception as e:
        print(f"  [TAKVİM] ⚠️  Takvim ajanı hatası ({type(e).__name__}): {e} → NORMAL")
        return TakvimRaporu.hata(e)

    yaklasan  = []
    aciklanan = []

    for olay in olaylar:
        etki = _etki_skoru(olay["isim"])
        if etki == 0:
            continue

        fark_saat = (olay["zaman"] - simdi).total_seconds() / 3600

        if fark_saat >= 0:
            yaklasan.append(Olay(isim=olay["isim"], etki=etki,
                                 saat_sonra=round(fark_saat, 2)))
        else:
            # Geçmiş — son 2 saat içinde açıklananlar
            gecen = abs(fark_saat)
            if gecen <= 2:
                aciklanan.append(Olay(isim=olay["isim"], etki=etki,
                                      saat_once=round(gecen, 2)))

    # Yaklaşan olayları zamana göre sırala
    yaklasan.sort(key=lambda o: o.saat_sonra)

    return TakvimRaporu(
        mod=_mod_belirle(yaklasan, aciklanan),
        yaklasan_olaylar=yaklasan,
        aciklanan_olaylar=aciklanan,
    )


if __name__ == "__main__":
    import json
    print("=== EKONOMİK TAKVİM AJANI ===")
    print(json.dumps(calistir().sozluk(), indent=2, ensure_ascii=False))
