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
  sigorta: "Sigorta",
  yatirim_birikim: "Yatırım",
  konut_gayrimenkul: "Konut",
  kurumsal_kobi: "Kurumsal / KOBİ",
  dogalgaz_enerji: "Doğalgaz / Enerji",
  otomotiv: "Otomotiv",
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
  // audience (şartname 5.3)
  mevcut_musteri: "Mevcut Müşteri",
  maas_musterisi: "Maaş Müşterisi",
  emekli: "Emekli",
  ogrenci: "Öğrenci",
  genc: "Genç",
  kamu_calisani: "Kamu Çalışanı",
  banka_calisani: "Banka Çalışanı",
  esnaf: "Esnaf",
  ciftci: "Çiftçi",
  kobi: "KOBİ",
  ticari_kurumsal: "Ticari / Kurumsal",
  ozel_bankacilik: "Özel Bankacılık",
  herkes: "Herkes",
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
  // Campaign.segment (kanal — audience değil)
  bireysel: "Bireysel",
  kurumsal: "Kurumsal",
  ticari: "Ticari",
  tarim: "Tarım",
};

/** Filtre açılır listelerinde kullanılan sık sektörler. */
export const SECTOR_FILTER_OPTIONS: string[] = [
  "market_gida",
  "akaryakit",
  "giyim_aksesuar",
  "elektronik_telekom",
  "beyaz_esya_ev",
  "mobilya_dekorasyon",
  "yapi_hirdavat",
  "eticaret_pazaryeri",
  "seyahat_konaklama",
  "ulasim_arac_kiralama",
  "restoran_kafe",
  "eglence_dijital",
  "egitim_kitap",
  "saglik_kozmetik",
  "vergi_fatura_kamu",
  "yatirim_birikim",
  "otomotiv",
  "kurumsal_kobi",
  "genel",
];

/** Filtre açılır listelerinde kullanılan sık ürün türleri. */
export const PRODUCT_TYPE_FILTER_OPTIONS: string[] = [
  "kart",
  "finansman",
  "ihtiyac_finansmani",
  "konut_finansmani",
  "tasit_finansmani",
  "birikim_katilma_hesabi",
  "yatirim_urunu",
  "yeni_musteri",
  "alisveris_puani",
  "pos_uye_isyeri",
  "dijital_bankacilik",
  "odeme_fatura",
  "alisveris_finansmani",
  "kobi_ticari",
];

export const SEGMENT_FILTER_OPTIONS: string[] = [
  "bireysel",
  "kurumsal",
  "kobi",
  "ticari",
  "tarim",
];

const AXIS_LABELS: Record<string, string> = {
  product_type: "Ürün türü",
  sector: "Sektör",
  audience: "Hedef kitle",
  benefit: "Fayda",
};

/** Taksonomi slug'ını Türkçe okunur etikete çevirir; karşılığı yoksa slug'ı olduğu gibi döner. */
export function taxonomyLabel(value: string): string {
  return TAXONOMY_LABELS[value] ?? value;
}

/** Taksonomi eksen adını Türkçe gösterir. */
export function taxonomyAxisLabel(axis: string): string {
  return AXIS_LABELS[axis] ?? axis;
}
