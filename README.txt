# Ollama Model Tester - Kullanim Rehberi

Web tabanli LLM test araci. 5 kategoride 70 prompt ile Ollama modellerini test eder.

---

## Sistem Gereksinimleri

* Python 3.8+
* pip
* Ollama sunucusu (yerel veya uzak)

## Baslangic

### 1. Sunucuyu Baslat

Windows PowerShell'de:

```bash
cd Ollama_Model_Tester
python main.py
```

Tarayici ac: http://localhost:8000

### 2. Model Secimi

1. "Model Adi" kutusuna model yaz (orn: qwen3:14b)
2. "Listeyi Cek" butonuna tikla
3. Listeden modeli sec

### 3. Kategori Secimi

Kategorilerden bir veya birden fazla sec:

* Coding (46 test) - Kod uretimi, debug, guvenlik
* Vision (8 test) - Goruntu analizi, OCR
* Tools (6 test) - Fonksiyon cagrisi, tool selection
* Thinking (6 test) - Mantik, olasilik, muhakeme
* Embedding (4 test) - Semantic search, similarity

### 4. Testi Baslat

"Testi Baslat" butonuna tikla.

---

## Warmup Davranisi

| Durum | Aciklama |
|-------|----------|
| Model zaten GPU bellekte | Warmup atlanir, test hemen baslar |
| Model GPU bellekte degil | 5 dakika warmup beklenir |

---

## Aktif Test Uyarisi

| Senaryo | Sonuc |
|---------|-------|
| Ayni model + aktif test var | Eski test etkilenmez, yeni test baslar |
| Farkli model + aktif test var | Eski test hata verebilir (Ollama modeli degistirir) |

---

## Test Ekrani Kontrolleri

* Duraklat - Testi duraklatir
* Devam Et - Devam ettirir  
* Durdur - Testi sonlandirir
* Sonuclari Gor - Bitince sonuc sayfasina gider

---

## Sistem Bilgisi

Test ekraninda gosterilir:
* Model adi ve boyutu
* GPU VRAM kullanimi
* Quantization seviyesi (Q4_K_M vb.)

---

## Sonuclar

* Tekil sonuc: Sonuclar Gor butonu
* Karsilastirma: Karislastir menusu - N model yan yana

---

## Hizli Test Tavsiyesi

Az promptlu kategori sec (Tools/Thinking/Embedding) hizli sonuc icin.

---

## Sorun Giderme

| Problem | Cozum |
|---------|-------|
| Baglanti hatasi | Ollama host adresini kontrol et |
| Model bulunamadi | /api/tags endpoint'ini kontrol et |
| Timeout | Prompt 3 dk, warmup 5 dk limiti. Sunucu yuku kontrol et |
| Eski test etkilendi | Ayni model ile yeni test baslat |

---

## Proje Yapisi

```
Ollama_Model_Tester/
  main.py              - FastAPI backend
  static/              - HTML/JS/CSS
  prompts/             - Test promptlari (JSON)
  results/             - Test sonuclari
  logs/                - Status dosyalari
```

---

## Teknik Notlar

* Port: 8000
* Timeout: Normal prompt 180 sn, warmup 300 sn
* Veri saklama: JSON dosyalari (veritabani yok)
* GPU izleme: nvidia-ml-py ile (opsiyonel)

