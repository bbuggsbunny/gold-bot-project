"""
agents/utils.py
───────────────
Binance zaman senkronizasyonu.

Binance imzalı isteklerde yerel saat ile sunucu saati arasında ~1 saniyeden
fazla fark olursa -1021 / -2015 hatası döner. Bu modül farkı ölçer, gerekirse
chronyc ile düzeltmeyi dener.

TAKILMA KORUMASI (2026-07-26)
    Önceden `sudo chronyc makestep` düz çağrılıyordu. Şifresiz sudo kuralı
    tanımlı değilse sudo terminalden şifre ister ve gözetimsiz çalışan bot
    orada kilitlenir. Artık `sudo -n` (asla sorma) + timeout kullanılıyor;
    başarısız olursa bot uyarı basıp yoluna devam eder.

    Kalıcı çözüm için (bir kez, root gerekir):
        echo "$USER ALL=(ALL) NOPASSWD: /usr/bin/chronyc makestep" \
            | sudo tee /etc/sudoers.d/chronyc
        sudo chmod 440 /etc/sudoers.d/chronyc
"""
import subprocess
import time

ESIK_MS = 1000      # bu farkın üstünde düzeltme denenir
ZAMAN_ASIMI = 10    # chronyc çağrısı için saniye

_uyari_verildi = False   # aynı uyarıyı her döngüde tekrarlama


def _saati_duzelt() -> bool:
    """chronyc makestep dener. Başarılıysa True. Asla exception fırlatmaz."""
    global _uyari_verildi
    try:
        sonuc = subprocess.run(
            ["sudo", "-n", "chronyc", "makestep"],   # -n: şifre sorma, hemen dön
            capture_output=True, text=True, timeout=ZAMAN_ASIMI,
        )
    except FileNotFoundError:
        if not _uyari_verildi:
            print("  [ZamanSync] ⚠️  sudo/chronyc bulunamadı — saat düzeltilemiyor.")
            _uyari_verildi = True
        return False
    except subprocess.TimeoutExpired:
        print(f"  [ZamanSync] ⚠️  chronyc {ZAMAN_ASIMI}s içinde yanıt vermedi.")
        return False

    if sonuc.returncode == 0:
        return True

    if not _uyari_verildi:
        hata = (sonuc.stderr or "").strip().splitlines()
        print(f"  [ZamanSync] ⚠️  Saat düzeltilemedi: {hata[-1] if hata else 'bilinmeyen hata'}")
        print("  [ZamanSync]    Şifresiz sudo kuralı için agents/utils.py başlığına bakın.")
        _uyari_verildi = True
    return False


def senkronize_et(client) -> int:
    """
    Yerel saat ile Binance sunucusu arasındaki farkı ms olarak döndürür.
    Fark eşiği aşarsa saati düzeltmeyi dener; başarısız olursa bot durmaz.
    """
    yerel  = int(time.time() * 1000)
    sunucu = client.get_server_time()["serverTime"]
    fark   = abs(yerel - sunucu)

    if fark <= ESIK_MS:
        return fark

    if _saati_duzelt():
        print(f"  [ZamanSync] {fark}ms fark — chronyc makestep ile düzeltildi.")
    else:
        print(f"  [ZamanSync] ⚠️  {fark}ms fark sürüyor — Binance imza hatası verebilir.")

    return fark
