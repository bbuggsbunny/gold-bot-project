"""
bot/durum.py
────────────
Botun paylaşılan çalışma durumu.

Önceden main.py'de 6 modül seviyesi değişken, 4 ayrı kilit ve bunlara
erişen `global` ifadeleri vardı. Hepsi burada iki sınıfta toplandı:

    BaglamDurumu — haber / makro / takvim raporlarının son hali
    ZararTakibi  — günlük zarar sayacı ve limiti

Kilitleme notu: bağlam için üç ayrı kilit yerine tek kilit kullanılıyor.
Okumalar birkaç mikrosaniye sürdüğü ve bot dakikada bir çalıştığı için
çekişme diye bir şey yok; tek kilit okumayı da yazmayı da basitleştiriyor.
"""
import threading
from datetime import datetime

from tipler import HaberRaporu, MakroRaporu, TakvimRaporu


class BaglamDurumu:
    """
    Üç bağlam ajanının en son raporunu tutar.

    Raporlar hiçbir zaman yerinde değiştirilmez — her güncelleme yeni bir
    nesne atar. Bu yüzden okuyucular referansı alıp kilidi bırakabilir.
    """

    def __init__(self):
        self._kilit  = threading.Lock()
        self._haber  = HaberRaporu(ozet="Henüz haber analizi yapılmadı.")
        self._makro  = MakroRaporu()
        self._takvim = TakvimRaporu()

    # ── Yazma ────────────────────────────────────────────────────
    def haber_yaz(self, rapor: HaberRaporu) -> None:
        with self._kilit:
            self._haber = rapor

    def makro_yaz(self, rapor: MakroRaporu) -> MakroRaporu:
        """Yeni raporu yazar, ÖNCEKİ raporu döndürür (değişim bildirimi için)."""
        with self._kilit:
            onceki, self._makro = self._makro, rapor
        return onceki

    def takvim_yaz(self, rapor: TakvimRaporu) -> TakvimRaporu:
        """Yeni raporu yazar, ÖNCEKİ raporu döndürür (mod değişimi için)."""
        with self._kilit:
            onceki, self._takvim = self._takvim, rapor
        return onceki

    # ── Okuma ────────────────────────────────────────────────────
    def oku(self) -> tuple[HaberRaporu, MakroRaporu, TakvimRaporu]:
        """Üç raporun o anki halini tek seferde okur."""
        with self._kilit:
            return self._haber, self._makro, self._takvim

    @property
    def takvim_modu(self) -> str:
        with self._kilit:
            return self._takvim.mod


class ZararTakibi:
    """
    Günlük zarar sayacı.

    Her açılan pozisyonun stop-loss'a çarpması hâlindeki potansiyel zararı
    toplar; limit aşılınca o gün için işlem kapanır. Gece 00:00 geçişinde
    sıfırlanır.

    DİKKAT (PROJE.md Bölüm 12, Sorun 7): sabit 0.01 oz pozisyonda işlem
    başına risk ~$0.45. $75'lik limitin tetiklenmesi için aynı günde ~167
    işlem gerekir; yani limit pratikte devreye girmiyor. Hesap doğru, eşik
    pozisyon boyutuyla uyumsuz.
    """

    def __init__(self, limit: float, miktar: float):
        self._kilit  = threading.Lock()
        self._limit  = limit
        self._miktar = miktar
        self._toplam = 0.0
        self._durdu  = False
        self._gun    = None

    def gun_kontrol(self):
        """
        Gece 00:00 geçişini tespit edip sayacı sıfırlar.

        Dönüş: gün gerçekten değiştiyse `(önceki_gün, önceki_toplam)`,
        aksi halde None. İlk başlatmada da None döner — o an biten bir gün
        yok. Çağıran bu bilgiyle günlük özet bildirimini gönderir.
        """
        bugun = datetime.now().date()
        with self._kilit:
            if self._gun is not None and bugun == self._gun:
                return None

            devir = None
            if self._gun is not None:
                print(f"\n  [ZARAR] Yeni gün — sayaç sıfırlandı "
                      f"(önceki gün toplam: ${self._toplam:.2f})")
                devir = (self._gun, self._toplam)

            self._toplam = 0.0
            self._durdu  = False
            self._gun    = bugun
            return devir

    def limitte_mi(self) -> bool:
        """True dönerse bugün için işlem yasak."""
        with self._kilit:
            return self._durdu

    def ekle(self, stop_loss_pct: float, fiyat: float) -> bool:
        """
        Pozisyonun potansiyel SL zararını sayaca ekler.

        Dönüş: limit BU çağrıda aşıldıysa True (çağıran Telegram'a bildirir).
        """
        kayip = self._miktar * fiyat * (stop_loss_pct / 100)

        with self._kilit:
            self._toplam += kayip
            print(f"  [ZARAR] Günlük açık zarar: ${self._toplam:.2f} "
                  f"/ ${self._limit:.2f}")

            if not self._durdu and self._toplam >= self._limit:
                self._durdu = True
                print(f"  [ZARAR] ⛔ ${self._limit:.2f} limiti aşıldı — "
                      f"bugün işlem yok.")
                return True
        return False

    @property
    def toplam(self) -> float:
        with self._kilit:
            return self._toplam

    @property
    def limit(self) -> float:
        return self._limit
