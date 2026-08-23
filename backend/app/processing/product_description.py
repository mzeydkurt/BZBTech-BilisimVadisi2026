"""Ürün sayfası açıklama metni çıkarımı.

Bankaların finansman sayfalarındaki \"Nedir?\", tanıtım ve özellik
paragraflarını alır. Menü/footer/çerez blokları açıklama sanılmaz.

⚠️ clean_text çoğu zaman TEK satır sonu kullanır (`\\n`); çift boş satıra
güvenilmez. Satırlar birleştirilerek anlamlı paragraf kurulur.
Kesik cümle / yapay \"…\" kırpması yapılmaz — açıklama tam kalır.
"""

from __future__ import annotations

import re
from typing import Final

from app.core.normalization.text import collapse_whitespace, lower_tr

_MIN_SATIR: Final[int] = 40
_MIN_ACIKLAMA: Final[int] = 60
# Üst sınır yalnızca aşırı ücret/tablo sayfalarını kesmek için;
# kırpma her zaman cümle sonunda yapılır (orta kelime yok).
_MAX_ACIKLAMA: Final[int] = 4500
_MAX_PARAGRAF: Final[int] = 6

# Satırın TAMAMI veya baskın içeriği bu ise atılır (alt dize değil).
_ATILACAK_SATIR: Final[tuple[str, ...]] = (
    "çerez ayarları",
    "çerez politikası",
    "cookie policy",
    "kvkk aydınlatma",
    "kişisel verilerin korunması",
    "gizlilik politikası",
    "tüm hakları saklıdır",
    "copyright",
    "english",
    "العربية",
)

# Bu başlıklardan sonra tanıtım bitti sayılır — belge / CTA / tablo.
_BOLUM_SONU: Final[tuple[str, ...]] = (
    "başvurusu nasıl",
    "basvurusu nasil",
    "gerekli belgeler",
    "gerekli evrak",
    "hesaplama araç",
    "hesaplama arac",
    "kâr payı oranları",
    "kar payi oranlari",
    "maliyet tablosu",
    "finansman oranları",
    "finansman oranlari",
    "masraf |",
    "en yakın şube",
    "en yakin sube",
    "sıkça sorulan",
    "sikca sorulan",
    "sss",
)

# Ürün tanıtımına işaret — bu satırlar öncelikli alınır.
_ONCELIK: Final[tuple[str, ...]] = (
    "nedir",
    "finansman",
    "finansmanı",
    "sağlanan",
    "sunulan",
    "imkân",
    "imkan",
    "vade",
    "kâr payı",
    "kar payi",
    "katılım bankacılığı",
    "katilim bankaciligi",
    "ev sahibi",
    "araç",
    "arac",
    "konut",
    "ihtiyaç",
    "ihtiyac",
    "peşinat",
    "pesinat",
    "özellik",
    "ozellik",
)

# Site menüsü / duyuru kirintisi — ürün tanıtımı sayılmaz.
_NAV_KIRINTISI: Final[tuple[str, ...]] = (
    "mobil bankacılık",
    "mobil bankaciligi",
    "hakkımızda",
    "hakkimizda",
    "yatırımcı ilişkileri",
    "yatirimci iliskileri",
    "tüm kampanyalar",
    "tum kampanyalar",
    "duyurular",
    "size özel",
    "size ozel",
    "ürün ve hizmet ücretleri",
    "urun ve hizmet ucretleri",
    "albaraka mobil",
    "elİs işlem",
    "elis islem",
)

_CUMLE_SONU = re.compile(r"[.!?…][\"”')\]]?\s*$")
_YUMUSAK_KESIK = re.compile(
    r"(yeni sekmede|için tıklayın|detaylı bilgi|aşağıdaki gibidir)\s*$",
    re.IGNORECASE,
)


def _satir_atilsin_mi(satir: str) -> bool:
    """Menü / yasal tek satır mı?"""
    dusuk = lower_tr(satir)
    if len(satir) < _MIN_SATIR:
        return True
    if any(a in dusuk for a in _ATILACAK_SATIR):
        return True
    if satir.count("|") >= 3 or satir.count("·") >= 4 or satir.count("•") >= 5:
        return True
    if re.fullmatch(r"(hemen başvur|online başvuru|başvur|hesapla)[.!]*", dusuk):
        return True
    return False


def _bolum_sonu_mu(satir: str) -> bool:
    dusuk = lower_tr(satir)
    return any(b in dusuk for b in _BOLUM_SONU)


def _oncelik_skoru(satir: str) -> int:
    dusuk = lower_tr(satir)
    return sum(1 for k in _ONCELIK if k in dusuk)


def _faq_sorusu_mu(satir: str) -> bool:
    """SSS / kısa soru başlığı — tanıtım bloğunun sonu."""
    dusuk = lower_tr(satir)
    if "sıkça sorulan" in dusuk or "sikca sorulan" in dusuk:
        return True
    if dusuk.startswith("sss ") or dusuk == "sss":
        return True
    if len(satir) < 140 and re.search(r"\bnedir\?\s*$", dusuk):
        return True
    return False


def _nav_kirintisi_mi(satir: str) -> bool:
    dusuk = lower_tr(satir)
    if any(n in dusuk for n in _NAV_KIRINTISI):
        return True
    # Ülke / dil seçici menüsü
    if satir.count("|") >= 2 and len(satir) < 200:
        return True
    # Kaynak metin zaten ortadan kesilmiş (… / ...)
    if satir.rstrip().endswith("...") or satir.rstrip().endswith("\u2026"):
        return True
    return False


def _tanitim_basliyor_mu(satir: str) -> bool:
    """Sayfa üstündeki ilk anlamlı tanıtım paragrafı mı?"""
    if _nav_kirintisi_mi(satir):
        return False
    if _satir_atilsin_mi(satir) and "nedir" not in lower_tr(satir):
        return False
    if _bolum_sonu_mu(satir) and "nedir" not in lower_tr(satir):
        return False
    if _faq_sorusu_mu(satir):
        return False
    skor = _oncelik_skoru(satir)
    if "nedir" in lower_tr(satir) and len(satir) >= _MIN_SATIR:
        return True
    if skor >= 2 and len(satir) >= 80:
        return True
    if skor >= 1 and len(satir) >= 120:
        return True
    return False


def _tanitim_devam_mi(satir: str) -> bool:
    """Tanıtım bloğu içinde ardışık paragraf olarak alınabilir mi?"""
    if _nav_kirintisi_mi(satir):
        return False
    if _bolum_sonu_mu(satir):
        return False
    if _faq_sorusu_mu(satir):
        return False
    if satir.count("|") >= 2:
        return False
    if re.match(r"^\d+\s*\|", satir):
        return False
    return True


def _cumle_tam_mi(satir: str) -> bool:
    return bool(_CUMLE_SONU.search(satir.rstrip()))


def _paragraflari_birlestir(satirlar: list[str]) -> list[str]:
    """Yumuşak satır kırıklıklarını tek paragrafa birleştir."""
    if not satirlar:
        return []
    paragraflar: list[str] = []
    buf = satirlar[0]
    for satir in satirlar[1:]:
        if (not _cumle_tam_mi(buf)) or _YUMUSAK_KESIK.search(buf):
            buf = f"{buf} {satir}"
            continue
        ilk = satir.lstrip()[:1]
        if ilk and ilk.islower() and not _bolum_sonu_mu(satir):
            buf = f"{buf} {satir}"
            continue
        paragraflar.append(collapse_whitespace(buf))
        buf = satir
    paragraflar.append(collapse_whitespace(buf))
    return [p for p in paragraflar if p]


def _cumle_sonunda_kes(metin: str, azami: int) -> str:
    """Azami uzunluğu aşarsa son tam cümlede kes; '…' ekleme."""
    if len(metin) <= azami:
        return metin
    dilim = metin[:azami]
    son = -1
    for m in re.finditer(r"[.!?…][\"”')\]]?(?:\s|$)", dilim):
        son = m.end()
    if son >= _MIN_ACIKLAMA:
        return dilim[:son].rstrip()
    parca = dilim.rsplit(" ", 1)[0].rstrip()
    return parca if len(parca) >= _MIN_ACIKLAMA else dilim.rstrip()


def _boilerplate_cumleleri_at(metin: str) -> str:
    """Paragrafa karışmış menü / çerez / KVKK cümlelerini çıkar."""
    cumleler = re.split(r"(?<=[.!?…])\s+", metin)
    kalan: list[str] = []
    for cumle in cumleler:
        dusuk = lower_tr(cumle)
        if any(a in dusuk for a in _ATILACAK_SATIR):
            continue
        if len(cumle.strip()) < 25 and any(
            k in dusuk for k in ("internet şubesi", "internet subesi", "mobil bankacılık")
        ):
            continue
        kalan.append(cumle)
    return " ".join(kalan).strip()


def extract_product_description(body_text: str | None, title: str | None = None) -> str | None:
    """Temiz gövde metninden ürün açıklaması üretir.

    Args:
        body_text: clean_html / source_documents.clean_text çıktısı.
        title: Ürün başlığı (yinelenen satırı atlamak için).

    Returns:
        Açıklama veya None — uydurma yok. Ortada kesilmez.
    """
    if not body_text or not body_text.strip():
        return None

    baslik = collapse_whitespace(title or "")
    baslik_dusuk = lower_tr(baslik)

    ham_satirlar: list[str] = []
    for ham in body_text.split("\n"):
        satir = collapse_whitespace(ham)
        if not satir:
            continue
        if baslik_dusuk and lower_tr(satir) == baslik_dusuk:
            continue
        ham_satirlar.append(satir)

    paragraflar = _paragraflari_birlestir(ham_satirlar)

    # Sayfa üstünden tanıtım bloğunu sırayla oku (SSS / tablo öncesi)
    secilen: list[str] = []
    toplam = 0
    basladi = False

    for satir in paragraflar:
        if not basladi:
            if not _tanitim_basliyor_mu(satir):
                continue
            basladi = True
            secilen.append(satir)
            toplam += len(satir)
            continue

        if not _tanitim_devam_mi(satir):
            break
        if _satir_atilsin_mi(satir):
            break
        secilen.append(satir)
        toplam += len(satir)
        if len(secilen) >= _MAX_PARAGRAF or toplam >= _MAX_ACIKLAMA:
            break

    if not secilen:
        return None

    metin = "\n\n".join(secilen).strip()
    metin = _boilerplate_cumleleri_at(metin)
    if len(metin) < _MIN_ACIKLAMA:
        return None
    metin = _cumle_sonunda_kes(metin, _MAX_ACIKLAMA)
    if metin and not _cumle_tam_mi(metin):
        son = -1
        for m in re.finditer(r"[.!?…][\"”')\]]?", metin):
            son = m.end()
        if son >= _MIN_ACIKLAMA:
            metin = metin[:son].rstrip()
    return metin if len(metin) >= _MIN_ACIKLAMA else None
