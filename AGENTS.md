# Ollama Model Tester — AI Asistan Talimatları

Bu dosya, bu projeyle çalışan AI asistanın (sen) izlemesi gereken kuralları içerir.
Kullanıcı "`AGENTS.md`'yi oku" veya "klasördeki talimat dosyasını oku" dediğinde,
**önce bu dosyayı okumalısın** ve aşağıdaki prosedürleri takip etmelisin.

---

## 1. Proje Amacı

Ollama API'sine bağlı LLM modellerini çoklu kategorilerde (Coding, Vision, Tools, Thinking, Embedding) test eden,
sonuçları dosya-tabanlı saklayan ve **N-way karşılaştırma** yapan web uygulaması.

**Backend:** Python FastAPI (Ollama proxy + test runner)
**Frontend:** Vanilla HTML + Bootstrap 5 + Vanilla JS (offline çalışabilir)
**Veri:** `results/` klasöründe JSON dosyaları (DB yok)

---

## 2. Kritik Kurallar

> **Asla `prompts/*.json` dosyalarını değiştirme.**
> Bunlar test standardıdır. Kullanıcı "yeni prompt ekle" derse, `AGENTS.md`'ye not düş, sonra ekle.
>
> **Asla `results/` klasörüne elle müdahale etme.** Sadece uygulama yazsın.
>
> **Offline çalışabilirlik bozulmamalı.** `static/` dosyaları doğrudan tarayıcıda açılabilmeli.

---

## 3. Klasör Yapısı (Mutlak)

```
Ollama_Model_Tester/
├── main.py                  # FastAPI backend (DOKUNMA)
├── requirements.txt         # Python bağımlılıkları
├── README.md                # İnsan kullanıcı rehberi
├── AGENTS.md                # Bu dosya (SEN İÇİN)
├── prompts/
│   ├── coding.json          # 46 prompt (Coding testleri)
│   ├── vision.json          # 8 prompt (Vision testleri)
│   ├── tools.json           # 6 prompt (Tools testleri)
│   ├── thinking.json        # 6 prompt (Thinking testleri)
│   └── embedding.json       # 4 prompt (Embedding testleri)
├── static/
│   ├── index.html           # Ana sayfa (model/kategori seçimi)
│   ├── test.html            # Test ekranı (progress bar + log)
│   ├── result.html          # Sonuç sayfası (AI yorumları)
│   ├── compare.html         # N-way karşılaştırma
│   ├── css/style.css        # Global stiller
│   └── js/
│       ├── app.js           # Ana uygulama
│       ├── ollama.js        # Ollama API client
│       ├── tester.js        # Test motoru
│       ├── ui.js            # UI güncellemeleri
│       └── compare.js       # Karşılaştırma motoru
├── results/                 # Test sonuçları (DB yerine)
│   └── {model_adi}_{tarih}/
│       ├── manifest.json
│       └── {kategori}/
│           └── {prompt_id}.json
└── logs/                    # Uygulama logları
```

---

## 4. Geliştirme Prosedürü

### Yeni Sayfa Eklenecekse
1. `static/` altında HTML + JS oluştur.
2. `main.py`'ye yeni endpoint ekle.
3. `static/index.html` navigasyonuna link ekle.

### Yeni Kategori Eklenecekse
1. `prompts/{kategori}.json` oluştur (standart schema ile).
2. `static/index.html`'de checkbox kartı ekle.
3. `main.py`'de kategori validasyonu güncelle.

### Backend Değişikliği
- `main.py` tek ana dosyadır.
- FastAPI endpoint'leri `api/` prefixiyle çalışır.
- Ollama proxy: CORS sorununu önlemek için zorunludur.

---

## 5. Prompt JSON Schema (Referans)

Her prompt dosyası (`prompts/*.json`) şu schema ile yazılmalıdır:

```json
[
  {
    "id": "unique_prompt_id",
    "category": "coding",
    "prompt": "Modelden istenen talimat (markdown destekler)",
    "depends_on": null,
    "expected_focus": ["beklenen nokta 1", "beklenen nokta 2"]
  }
]
```

- `depends_on`: Başka bir prompt ID'si. Önceki cevabı context olarak verir.
- `expected_focus`: Değerlendirme kriterleri (AI yorumları için referans).

---

## 6. Sonuç JSON Schema (Referans)

Her test sonucu (`results/*/{kategori}/{prompt_id}.json`):

```json
{
  "id": "prompt_id",
  "category": "coding",
  "prompt": "...",
  "response": "...",
  "duration_sec": 120.5,
  "timestamp": "2026-04-27T19:30:00",
  "expected_focus": ["..."],
  "ai_evaluation": {
    "correctness": "passed|failed|partial",
    "hallucination": false,
    "security_aware": true,
    "completeness": "full|partial",
    "idiomatic": true,
    "notes": "AI yorumu..."
  }
}
```

---

## 7. Karşılaştırma Prosedürü

Kullanıcı "modelleri karşılaştır" dediğinde:
1. `results/` klasöründen tüm `manifest.json` dosyalarını oku.
2. Kullanıcı N model seçsin.
3. Prompt bazlı tablo oluştur: her modelin her prompttaki skoru.
4. Kategori bazlı özet grafik (bar/radar) üret.
5. Export: HTML olarak indirilebilir rapor.

---

## 8. Offline Çalışma Modu

Uygulama iki modda çalışabilir:
- **Online:** FastAPI backend çalışıyor, test yapılabilir.
- **Offline:** Sadece `static/` dosyaları açılmış, `results/` verileri JS ile okunuyor.

Offline modda test yapılamaz ama mevcut sonuçlar görüntülenebilir ve karşılaştırılabilir.

---

## 9. Hata Durumları

| Hata | Çözüm |
|------|-------|
| Ollama bağlantı yok | UI'de kırmızı banner, test pause |
| Model cevap vermiyor | 3 retry sonra skip, logla |
| Prompt JSON bozuk | Uygulama başlangıçta validasyon yapar, hata verir |
| Disk dolu | Sonuçları yazarken hata kontrolü, kullanıcıya bildir |

---

## 10. Versiyon ve Değişiklik Takibi

Yapılan değişiklikleri `README.md`'nin altına History bölümü olarak ekle.

---

## 🔔 BİR SONRAKİ OTURUM İÇİN HATIRLATMA

**[2026-04-28] AÇIK SORUN: Model Capability Fetch Çalışmıyor**

- `main.py`'de `_fetch_model_capabilities()` fonksiyonu Ollama sitesinden yetenekleri çekemiyor.
- Tüm modellerde `no special capabilities` çıkıyor.
- Debug log eklendi (`[API] Fetching capabilities for:`) ama console/terminalde hiç log görünmüyor.
- **Muhtemel nedenler:** Firewall, SSL sertifika hatası, proxy, timeout (10sn yetmeyebilir), veya Ollama sitesinin HTML yapısı değişmiş olabilir.
- **Yapılacaklar:**
  1. Terminalde `python main.py` çalışırken logları kontrol et
  2. Eğer log yoksa: `timeout=10`'u `timeout=30` yap
  3. Eğer hala yoksa: Ollama sitesine curl/requests ile manuel test yap
  4. Alternatif: Ollama API'sinden yetenek bilgisi var mı kontrol et
  5. Son çare: statik bir capability mapping dictionary'i ekle (manuel bakım gerektirir)

**Eklenen ama tam çalışmayan özellikler:**
- `main.py`: `_fetch_model_capabilities()` — Ollama sitesinden `vision/tools/thinking` çekme
- `main.py`: `/api/models` — her modele `capabilities` array'i ekleme
- `index.html`: Model listesinde capability badge'leri (renkli: vision=mavi, tools=yeşil, thinking=sarı)
- `index.html`: Kategori kartlarında yeteneğe göre vurgu (desteklenen=yeşil border, desteklenmeyen=soluk)
- `index.html`: Desteklenmeyen kategori seçimi tamamen engellendi (alert gösterip return)
- `test.html`: Thinking testleri için 5dk timeout bilgisi + uyarı banner
