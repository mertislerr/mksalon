import os
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, Response, BackgroundTasks
from supabase import create_client, Client
from groq import Groq
from twilio.rest import Client as TwilioClient
from dotenv import load_dotenv

# Ayarları yükle
load_dotenv()

# Bağlantıları Başlat
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
supabase: Client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
t_client = TwilioClient(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))

app = FastAPI()
hafıza = {}

# --- SİSTEM TALİMATI (DÜZGÜN TÜRKÇE VE SATIŞ) ---
SISTEM_TALIMATI = """
Sen 'NK Güzellik Salonu'nun kurumsal, nazik ve profesyonel asistanısın. 

DİL VE ÜSLUP KURALLARI:
1. Kesinlikle kurallı cümleler kur. Özne + Tümleç + Yüklem yapısını kullan.
2. Asla devrik cümle kurma (Örn: 'Geldim ben' yerine 'Ben geldim' de).
3. Türkçe imla kurallarına (de/da, -mı/mi ekleri) azami özen göster.
4. Müşteriye her zaman 'Hanım' veya 'Bey' diye hitap ederek kurumsal bir nezaket sergile.

GÖREVLERİN:
1. Randevu taleplerinde mutlaka dükkanın diğer hizmetlerini (Örn: Cilt bakımı, keratin) nazikçe öner.
2. Eğer istenen saat doluysa müşteriyi 'KAYIT_BEKLEME' formatıyla listeye almayı teklif et.
3. Randevu kesinleştiğinde ŞU FORMATI KULLAN: KAYIT_ONAY: [İsim], [İşlem], [Tarih], [Saat]
4. Bekleme listesi için: KAYIT_BEKLEME: [İsim], [İşlem], [Tarih], [Saat]
"""

# --- WHATSAPP MESAJ YÖNETİMİ ---
@app.post("/whatsapp")
async def whatsapp_reply(request: Request):
    form_data = await request.form()
    gelen_mesaj = form_data.get('Body', '')
    gonderen = form_data.get('From', '')
    bugun = datetime.now().strftime("%Y-%m-%d")

    # CRM: Müşterinin geçmişini kontrol et (Satış artırma için)
    gecmis = supabase.table("randevular").select("islem_tipi").eq("musteri_no", gonderen).execute()
    islemler = [x['islem_tipi'] for x in gecmis.data]
    ozel_durum = "Müşteri yeni." if not islemler else f"Müşteri daha önce {', '.join(set(islemler))} yaptırmış."

    # Hafıza ve AI hazırlığı
    if gonderen not in hafıza: hafıza[gonderen] = []
    mesaj_gecmisi = [{"role": "system", "content": f"{SISTEM_TALIMATI}\nBugün: {bugun}\nCRM Notu: {ozel_durum}"}]
    for m in hafıza[gonderen][-5:]: mesaj_gecmisi.append(m)
    mesaj_gecmisi.append({"role": "user", "content": gelen_mesaj})

    try:
        completion = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=mesaj_gecmisi,
            temperature=0.5 # Dil kalitesini korumak için yaratıcılığı sabitledik
        )
        ai_cevabi = completion.choices[0].message.content

        # KAYIT İŞLEMLERİ
        if "KAYIT_ONAY:" in ai_cevabi:
            detaylar = ai_cevabi.split("KAYIT_ONAY:")[1].split(",")
            isim, islem, tarih, saat = detaylar[0].strip(), detaylar[1].strip(), detaylar[2].strip(), detaylar[3].strip()
            
            # Doluluk Kontrolü
            kontrol = supabase.table("randevular").select("*").eq("randevu_tarihi", tarih).eq("randevu_saati", saat).execute()
            if len(kontrol.data) > 0:
                ai_cevabi = f"Üzgünüm {isim} Hanım, belirttiğiniz saat dolu. Başka bir saat bakabiliriz veya sizi bekleme listesine alabilirim."
            else:
                supabase.table("randevular").insert({
                    "musteri_no": gonderen, "musteri_adi": isim, "islem_tipi": islem, 
                    "randevu_tarihi": tarih, "randevu_saati": saat
                }).execute()
                ai_cevabi = ai_cevabi.split("KAYIT_ONAY:")[0].strip() + "\n\n✅ Randevunuzu kaydettim, görüşmek üzere!"

        elif "KAYIT_BEKLEME:" in ai_cevabi:
            detaylar = ai_cevabi.split("KAYIT_BEKLEME:")[1].split(",")
            supabase.table("bekleme_listesi").insert({
                "musteri_no": gonderen, "musteri_adi": detaylar[0].strip(),
                "islem_tipi": detaylar[1].strip(), "istenen_tarih": detaylar[2].strip(), "istenen_saat": detaylar[3].strip()
            }).execute()
            ai_cevabi = ai_cevabi.split("KAYIT_BEKLEME:")[0].strip() + "\n\n📋 Sizi sıraya ekledim!"

        hafıza[gonderen].append({"role": "user", "content": gelen_mesaj})
        hafıza[gonderen].append({"role": "assistant", "content": ai_cevabi})
        
    except Exception as e:
        ai_cevabi = "Sistemde bir güncelleme yapıyorum, lütfen birazdan tekrar dener misiniz?"

    return Response(content=f"<?xml version='1.0' encoding='UTF-8'?><Response><Message>{ai_cevabi}</Message></Response>", media_type="application/xml")

# --- YENİ: OTOMATİK HATIRLATMA (Her 30 dk'da bir çalışır) ---
@app.get("/hatirlat")
async def randevu_hatirlatici():
    su_an = datetime.now()
    iki_saat_sonra = (su_an + timedelta(hours=2)).strftime("%H:%M")
    bugun = su_an.strftime("%Y-%m-%d")

    query = supabase.table("randevular").select("*")\
        .eq("randevu_tarihi", bugun)\
        .lte("randevu_saati", iki_saat_sonra)\
        .eq("hatirlatma_gonderildi", False).execute()

    sayac = 0
    for r in query.data:
        mesaj = f"Merhaba {r['musteri_adi']} Hanım, NK Salon randevunuza 2 saat kaldı ({r['randevu_saati']}). Sizi bekliyoruz! ✨"
        try:
            t_client.messages.create(from_='whatsapp:+14155238886', body=mesaj, to=r['musteri_no'])
            supabase.table("randevular").update({"hatirlatma_gonderildi": True}).eq("id", r['id']).execute()
            sayac += 1
        except: pass

    return {"durum": f"{sayac} hatırlatma gönderildi."}