import os
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, Response
from supabase import create_client, Client
from groq import Groq
from twilio.rest import Client as TwilioClient
from dotenv import load_dotenv

load_dotenv()

# Bağlantılar
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
supabase: Client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
t_client = TwilioClient(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))

app = FastAPI()
hafıza = {}

# --- GÜNCELLENMİŞ SİSTEM TALİMATI (NK MERMER) ---
SISTEM_TALIMATI = """
Sen 'NK Mermer' firmasının profesyonel, nazik ve çözüm odaklı yapay zeka asistanısın.

HİTAP VE KONUŞMA KURALLARI (ÇOK ÖNEMLİ):
1. ÖNCE VERİTABANI: Sana verilen 'CRM BİLGİSİ'ni oku. Eğer müşterinin ismi oradaysa MUTLAKA ismiyle hitap et (Örn: 'Merhaba Ahmet Bey').
2. İSİM YOKSA: Asla 'Merhaba hanım/bey' gibi yarım ve robotik cümleler kurma. Bunun yerine 'Merhaba, size nasıl yardımcı olabilirim? İsim ve soyisminizi öğrenebilir miyim?' de.
3. DİL BİLGİSİ: Asla devrik cümle kurma. (Örn: 'Baktım ben' DEĞİL, 'Kontrol ettim' de). Türkçe imla kurallarına uy.

GÖREVLERİN:
1. Müşteri mermer çeşitleri, tezgah, masa veya zemin kaplama sorarsa profesyonel bilgi ver.
2. Randevu veya ölçü alma talebi olursa kaydet.
3. Randevu onayında ŞU FORMATI KULLAN: KAYIT_ONAY: [İsim], [İşlem/Ürün], [Tarih], [Saat]
"""

@app.post("/whatsapp")
async def whatsapp_reply(request: Request):
    form_data = await request.form()
    gelen_mesaj = form_data.get('Body', '')
    gonderen = form_data.get('From', '')
    bugun = datetime.now().strftime("%Y-%m-%d")

    # --- YENİ: İSİM VE GEÇMİŞ HAFIZASI (CRM) ---
    # Veritabanından bu numaraya ait en son kaydı getir
    musteri_sorgu = supabase.table("randevular").select("musteri_adi, islem_tipi")\
        .eq("musteri_no", gonderen).order("created_at", desc=True).limit(1).execute()
    
    kayitli_isim = None
    gecmis_islem = "Yeni müşteri."
    
    if musteri_sorgu.data:
        kayitli_isim = musteri_sorgu.data[0]['musteri_adi'] # İsim bulundu!
        gecmis_islem = f"Daha önce '{musteri_sorgu.data[0]['islem_tipi']}' işlemi yapıldı."

    # AI'ya fısılda: "Bak bu konuştuğun kişi [İSİM]"
    crm_notu = f"Müşteri İsmi: {kayitli_isim if kayitli_isim else 'BİLİNMİYOR (İsmini sor)'}. Not: {gecmis_islem}"

    if gonderen not in hafıza: hafıza[gonderen] = []
    
    # Sisteme CRM notunu ekle
    mesaj_gecmisi = [{"role": "system", "content": f"{SISTEM_TALIMATI}\nBugün: {bugun}\nCRM BİLGİSİ: {crm_notu}"}]
    
    for m in hafıza[gonderen][-5:]: mesaj_gecmisi.append(m)
    mesaj_gecmisi.append({"role": "user", "content": gelen_mesaj})

    try:
        completion = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=mesaj_gecmisi,
            temperature=0.3 # Daha ciddi ve hatasız konuşması için düşürdük
        )
        ai_cevabi = completion.choices[0].message.content

        # Kayıt Onay Mantığı
        if "KAYIT_ONAY:" in ai_cevabi:
            detaylar = ai_cevabi.split("KAYIT_ONAY:")[1].split(",")
            isim, islem, tarih, saat = detaylar[0].strip(), detaylar[1].strip(), detaylar[2].strip(), detaylar[3].strip()
            
            supabase.table("randevular").insert({
                "musteri_no": gonderen, "musteri_adi": isim, "islem_tipi": islem, 
                "randevu_tarihi": tarih, "randevu_saati": saat
            }).execute()
            
            ai_cevabi = ai_cevabi.split("KAYIT_ONAY:")[0].strip() + f"\n\n✅ Kaydınızı oluşturdum {isim} Bey/Hanım."

        hafıza[gonderen].append({"role": "user", "content": gelen_mesaj})
        hafıza[gonderen].append({"role": "assistant", "content": ai_cevabi})
        
    except Exception as e:
        ai_cevabi = "Kısa süreli bir bağlantı sorunu yaşıyorum, lütfen tekrar yazar mısınız?"

    return Response(content=f"<?xml version='1.0' encoding='UTF-8'?><Response><Message>{ai_cevabi}</Message></Response>", media_type="application/xml")

# Hatırlatıcı endpoint'i (Öncekiyle aynı mantıkta duruyor)
@app.get("/hatirlat")
async def hatirlat():
    # Burası cron-job ile çalışacak kısım
    return {"status": "ok"}