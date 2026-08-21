/**
 * Kontrollü sözlük değerlerinin Türkçe karşılıkları.
 *
 * Veritabanında slug tutulur (`market_gida`); kullanıcıya okunur ad gösterilir.
 * Karşılığı olmayan bir değer gelirse slug olduğu gibi gösterilir — sessizce
 * gizlemek, sınıflandırmanın yeni bir değer ürettiğini fark etmemize engel olur.
 */
export const TAXONOMY_LABELS: Record<string, string> = {
  // sector
  market_gida: "Market ve Gıda",
  akaryakit: "Akaryakıt",
  giyim_aksesuar: "Giyim ve Aksesuar",
  elektronik_telekom: "Elektronik",
  beyaz_esya_ev: "Beyaz Eşya",
  mobilya_dekorasyon: "Mobilya",
  yapi_hirdavat: "Yapı ve Hırdavat",
  kuyum_optik_saat: "Kuyum ve Optik",
  eticaret_pazaryeri: "E-ticaret",
  seyahat_konaklama: "Seyahat",
  ulasim_arac_kiralama: "Ulaşım",
  restoran_kafe: "Restoran",
  eglence_dijital: "Eğlence ve Dijital",
  egitim_kitap: "Eğitim ve Kitap",
  saglik_kozmetik: "Sağlık ve Kozmetik",
  hobi_oyuncak_spor: "Hobi ve Spor",
  vergi_fatura_kamu: "Vergi ve Fatura",
  yatirim_birikim: "Yatırım",
  konut_gayrimenkul: "Konut",
  kurumsal_kobi: "Kurumsal / KOBİ",
  genel: "Genel",
  // product_type
  finansman: "Finansman",
  ihtiyac_finansmani: "İhtiyaç Finansmanı",
  konut_finansmani: "Konut Finansmanı",
  tasit_finansmani: "Taşıt Finansmanı",
  kart: "Kart",
  alisveris_puani: "Alışveriş Puanı",
  yeni_musteri: "Yeni Müşteri",
  yatirim_urunu: "Yatırım Ürünü",
  birikim_katilma_hesabi: "Katılma Hesabı",
  sigorta: "Sigorta",
  pos_uye_isyeri: "POS / Üye İşyeri",
  dijital_bankacilik: "Dijital Bankacılık",
  odeme_fatura: "Ödeme ve Fatura",
  kobi_ticari: "KOBİ / Ticari",
  isyeri_finansmani: "İşyeri Finansmanı",
  // product_type — KATİP KAPI 6 (Finansmanlar sekmesi)
  gayrimenkul_finansmani: "Gayrimenkul Finansmanı",
  alisveris_finansmani: "Alışveriş Finansmanı",
  surdurulebilir_finansman: "Sürdürülebilir Finansman",
  arsa_finansmani: "Arsa Finansmanı",
  egitim_finansmani: "Eğitim Finansmanı",
  karz_i_hasen: "Karz-ı Hasen",
  digital_arac_finansmani: "Dijital Araç Finansmanı",
  marka_ozel_finansman: "Marka Özel Finansman",
  // product_type — KATİP KAPI 7 (Katılım Hesabı sekmesi)
  katilma_hesabi: "Katılma Hesabı",
  ozel_katilma_hesabi: "Özel Katılma Hesabı",
  altin_katilma_hesabi: "Altın Katılma Hesabı",
  ara_donem_kar_odemeli: "Ara Ödemeli Katılma Hesabı",
  devlet_katkili_hesap: "Devlet Katkılı Hesap",
  // benefit
  nakit_iade: "Nakit İade",
  puan_mil: "Puan / Mil",
  taksit: "Taksit",
  vade_farksiz_taksit: "Vade Farksız Taksit",
  indirim: "İndirim",
  hediye_ceki: "Hediye Çeki",
  ucret_muafiyeti: "Ücret Muafiyeti",
  masrafsiz: "Masrafsız",
  avantajli_kar_payi: "Avantajlı Kâr Payı",
  hediye_urun: "Hediye Ürün",
  cekilis: "Çekiliş",
};

/** Taksonomi slug'ını Türkçe okunur etikete çevirir; karşılığı yoksa slug'ı olduğu gibi döner. */
export function taxonomyLabel(value: string): string {
  return TAXONOMY_LABELS[value] ?? value;
}
