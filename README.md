# Ollama Model Tester

Ollama API'sine bağlı LLM modellerini çoklu kategorilerde test eden, sonuçları dosya-tabanlı saklayan ve N-way karşılaştırma yapan web uygulaması.

## Özellikler

- **5 Test Kategorisi:** Coding (46), Vision (8), Tools (6), Thinking (6), Embedding (4)
- **N-Way Karşılaştırma:** 2, 3, 4+ model yan yana karşılaştırma
- **Gerçek Zamanlı İzleme:** Progress bar, log penceresi, pause/resume/stop
- **Sistem Bilgisi:** GPU VRAM, model boyutu, quantization seviyesi
- **Warmup Optimizasyonu:** Model zaten GPU bellekteyse warmup atlanır
- **Offline Destek:** Tüm sonuçlar ve UI tek klasörde, tarayıcıda açılabilir
- **DB Yok:** Sonuçlar JSON dosyalarında saklanır

## Hızlı Başlangıç

### 1. Kurulum

```bash
cd C:\AI_Projects\Ollama_Model_Tester
pip install -r requirements.txt
```

Opsiyonel (GPU izleme için):
```bash
pip install nvidia-ml-py
```

### 2. Çalıştırma

```bash
python main.py
```

Varsayılan: [http://localhost:8000](http://localhost:8000)

### 3. Test Adımları

1. **Ollama Bağlantısı:** Host adresini gir (varsayılan: 192.168.240.30:11434)
2. **Model Seçimi:** Model adı yaz veya "Listeyi Çek" ile listeden seç
3. **Kategori Seçimi:** Test edilecek kategorileri seç
4. **Testi Başlat:** "Testi Başlat" butonuna tıkla

## Sayfalar

| Sayfa | Açıklama |
|-------|----------|
| `index.html` | Model ve kategori seçimi |
| `test.html` | Test ekranı (progress + log + sistem bilgisi) |
| `result.html` | Sonuç raporu (AI yorumları ile) |
| `compare.html` | N-way model karşılaştırma |
| `system.html` | Python bağımlılık kontrolü ve kurulum |
| `tests.html` | Tüm 70 promptun listesi |

## Teknik Detaylar (AI Asistanlar İçin)

### API Endpoints

| Endpoint | Metod | Açıklama |
|----------|-------|----------|
| `/api/models?host=` | GET | Ollama model listesi |
| `/api/prompts/{category}` | GET | Promptları getir |
| `/api/test/start` | POST | Test başlat |
| `/api/test/status/{run_id}` | GET | Test durumu |
| `/api/test/pause/{run_id}` | POST | Duraklat |
| `/api/test/resume/{run_id}` | POST | Devam et |
| `/api/test/stop/{run_id}` | POST | Durdur |
| `/api/test/active` | GET | Aktif testler |
| `/api/results` | GET | Sonuç listesi |
| `/api/results/{id}` | GET | Detaylı sonuç |
| `/api/admin/ollama-ps` | GET | GPU'da aktif modeller |
| `/api/admin/gpu-info` | GET | Yerel GPU bilgisi |
| `/api/admin/system-check` | GET | Bağımlılık kontrolü |
| `/api/admin/install` | POST | Paket kur (onaylı) |

### Timeout Ayarları

```python
PROMPT_TIMEOUT_SECONDS = 240   # Normal prompt (4 dk)
WARMUP_TIMEOUT_SECONDS = 300   # İlk prompt / model yükleme (5 dk)
```

### Veri Yapısı

```
results/
  {model_adi}_{tarih}/
    manifest.json
    {kategori}/
      {prompt_id}.json

logs/
  status_{run_id}.json  # Çalışma zamanı durumu
```

### Warmup Mantığı

1. Test başlamadan `/api/ps` ile GPU'daki aktif modeller kontrol edilir
2. Eğer test modeli listedeyse → warmup atlanır
3. Değilse → "Say 'OK'" warmup promptu gönderilir (300s timeout)

### Aktif Test Kontrolü

- Aynı model + aktif test → Uyarı gösterir, kullanıcı onayları
- Farklı model + aktif test → Ollama eski modeli bellekten atar, aktif test hata verir

### Offline Kullanım

Test sonuçlarını başka makinede görmek için:
1. `results/` klasörünü kopyala
2. `static/` dosyalarını tarayıcıda aç
3. Karşılaştırma sayfasında sonuçları görüntüle

## History

- **v1.0.0 (2026-04-27):** İlk sürüm. 70 prompt, 5 kategori, N-way karşılaştırma.
- **v1.1.0 (2026-04-27):**
  - Pause/Resume/Stop kontrolleri eklendi
  - Timeout ve warmup mekanizması eklendi
  - Sistem bilgisi kartı (GPU VRAM, quantization)
  - Model uyarısı (yüklü model != test modeli)
  - Sistem kontrol sayfası (bağımlılık kontrolü)
  - Warmup optimizasyonu (GPU'da varsa atla)
  - Eski test banner'ı otomatik temizleme
  - XSS koruması (escapeHtml)
