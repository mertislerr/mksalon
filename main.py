from fastapi import FastAPI, Request, Response, BackgroundTasks
from supabase import create_client, Client
from groq import Groq
import os
import asyncio # Geri bildirim gecikmesi için
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
supabase: Client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

app = FastAPI()
hafıza = {}

# --- GERİ BİLDİRİM FONKSİYONU ---
async def geri_bildirim_gonder(gonderen, isim):
    # Gerçek dünyada 3 saat beklenir (3 * 3600), test için kısa tutulabilir
    await asyncio.sleep(10) # 10 saniye sonra (Test amaçlı)
    print(f"📩 {isim} hanıma Google yorum mesajı gönderildi: https://g.page/NK-Salon/review")

@app.post("/whatsapp")
async def whatsapp_reply(request: Request, background_tasks: BackgroundTasks):
    form_data = await request.form()
    gelen_mesaj = form_data.get('Body', '')
    gonderen = form_data.get('From', '')

    bugun = datetime.now().strftime("%Y-%m-%d")

    # 1. CRM: MÜŞTERİ GEÇMİŞİ VE ÇAPRAZ SATIŞ KONTROLÜ
    gecmis = supabase.table("randevular").select("islem_tipi").eq("musteri_no", gonderen).execute()
    yapilan_islemler = [x['islem_tipi'] for x in gecmis.data]
    
    ozel_not = "Bu müşteri yeni."
    if yapilan_islemler:
        ozel_not = f"Müşteri daha önce {', '.join(set(yapilan_islemler))} yaptırmış."
        if "Cilt Bakımı" not in yapilan_islemler:
            ozel_not += " Henüz Cilt Bakımı yaptırmamış, Hydrafacial indirimini teklif et."

    SISTEM_TALIMATI = f"""
    Sen 'NK Güzellik Salonu' Akıllı Yöneticisisin. 
    Bugün: {bugun}.
    {ozel_not}

    YETKİLERİN:
    1. AKILLI SATIŞ: Randevu alanlara mutlaka yapmadıkları bir işlemi (Örn: Cilt Bakımı) nazikçe öner.
    2. BEKLEME LİSTESİ: Eğer istenen saat doluysa 'KAYIT_BEKLEME: [İsim], [İşlem], [Tarih], [Saat]' formatıyla listeye al.
    3. KAYIT ONAY: Boş saatler için 'KAYIT_ONAY: [İsim], [İşlem], [Tarih], [Saat]' kullan.
    """

    if gonderen not in hafıza: hafıza[gonderen] = []
    mesaj_gecmisi = [{"role": "system", "content": SISTEM_TALIMATI}]
    for m in hafıza[gonderen][-5:]: mesaj_gecmisi.append(m)
    mesaj_gecmisi.append({"role": "user", "content": gelen_mesaj})

    try:
        completion = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=mesaj_gecmisi
        )
        ai_cevabi = completion.choices[0].message.content

        # KAYIT İŞLEMLERİ
        if "KAYIT_ONAY:" in ai_cevabi:
            try:
                detaylar = ai_cevabi.split("KAYIT_ONAY:")[1].split(",")
                isim, islem, tarih, saat = detaylar[0].strip(), detaylar[1].strip(), detaylar[2].strip(), detaylar[3].strip()

                # Doluluk Kontrolü
                kontrol = supabase.table("randevular").select("*").eq("randevu_tarihi", tarih).eq("randevu_saati", saat).execute()
                
                if len(kontrol.data) > 0:
                    ai_cevabi = f"Maalesef {saat} saati dolu {isim} hanım. Sizi bekleme listesine almamı ister misiniz? Ya da başka bir saat seçelim mi?"
                else:
                    supabase.table("randevular").insert({
                        "musteri_no": gonderen, "musteri_adi": isim, "islem_tipi": islem, 
                        "randevu_tarihi": tarih, "randevu_saati": saat
                    }).execute()
                    
                    # OTOMATİK GERİ BİLDİRİMİ PLANLA
                    background_tasks.add_task(geri_bildirim_gonder, gonderen, isim)
                    ai_cevabi = ai_cevabi.split("KAYIT_ONAY:")[0].strip() + "\n\n✨ Randevunuzu kaydettim!"

            except Exception as e: print(f"Hata: {e}")

        elif "KAYIT_BEKLEME:" in ai_cevabi:
            try:
                detaylar = ai_cevabi.split("KAYIT_BEKLEME:")[1].split(",")
                supabase.table("bekleme_listesi").insert({
                    "musteri_no": gonderen, "musteri_adi": detaylar[0].strip(),
                    "islem_tipi": detaylar[1].strip(), "istenen_tarih": detaylar[2].strip(),
                    "istenen_saat": detaylar[3].strip()
                }).execute()
                ai_cevabi = ai_cevabi.split("KAYIT_BEKLEME:")[0].strip() + "\n\n📋 Sizi bekleme listesine ekledim, yer açılırsa haber vereceğim!"
            except Exception as e: print(f"Hata: {e}")

        hafıza[gonderen].append({"role": "user", "content": gelen_mesaj})
        hafıza[gonderen].append({"role": "assistant", "content": ai_cevabi})
        
    except Exception as e:
        ai_cevabi = "Sistemde bir güncelleme yapıyorum, hemen döneceğim!"

    return Response(content=f"<?xml version='1.0' encoding='UTF-8'?><Response><Message>{ai_cevabi}</Message></Response>", media_type="application/xml")