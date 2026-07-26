import time
import subprocess


def senkronize_et(client) -> int:
    """Yerel saat ile Binance sunucusu arasındaki farkı ms olarak döndürür.
    Fark >1000ms ise chronyc makestep çalıştırır."""
    yerel = int(time.time() * 1000)
    sunucu = client.get_server_time()["serverTime"]
    fark = abs(yerel - sunucu)
    if fark > 1000:
        subprocess.run(["sudo", "chronyc", "makestep"], capture_output=True)
        print(f"[ZamanSync] {fark}ms fark tespit edildi — chronyc makestep çalıştırıldı.")
    return fark
