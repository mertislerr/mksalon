# Mevcut kütüphanelere ek olarak 'twilio' kütüphanesini en tepede kontrol et
from twilio.rest import Client as TwilioClient

# ... (baştaki bağlantı kodların aynı kalsın) ...

# Twilio Bilgilerini buraya da tanıtalım (Hatırlatma mesajları için)
twilio_sid = os.getenv("TWILIO_ACCOUNT_SID")
twilio_token = os.getenv("TWILIO_AUTH_TOKEN")
t_client = TwilioClient(twilio_sid, twilio_token)

# --- YENİ: OTOMATİK HATIRLATMA KAPISI ---
@app.get("/hatirlat")
async def randevu_hatirlatici():
    # 1. Şu andan 2 saat sonrasını hesapla
    su_an = datetime.now()
    iki_saat_sonra = (su_an + timedelta(hours=2)).strftime("%H:%M")
    bugun = su_an.strftime("%Y-%m-%d")

    # 2. Supabase'den hatırlatma bekleyenleri bul
    query = supabase.table("randevular").select("*")\
        .eq("randevu_tarihi", bugun)\
        .lte("randevu_saati", iki_saat_sonra)\
        .eq("hatirlatma_gonderildi", False).execute()

    gonderilen_sayisi = 0
    for r in query.data:
        numara = r['musteri_no']
        isim = r['musteri_adi']
        saat = r['randevu_saati']
        
        # 3. WhatsApp Mesajı Gönder
        mesaj = f"Merhaba {isim} Hanım, NK Salon'daki randevunuza yaklaşık 2 saat kaldı (Saat: {saat}). Sizi bekliyoruz! 😊"
        
        try:
            t_client.messages.create(
                from_='whatsapp:+14155238886', # Twilio numaran
                body=mesaj,
                to=numara
            )
            # 4. Mesaj gitti olarak işaretle
            supabase.table("randevular").update({"hatirlatma_gonderildi": True}).eq("id", r['id']).execute()
            gonderilen_sayisi += 1
        except Exception as e:
            print(f"Mesaj gönderme hatası: {e}")

    return {"mesaj": f"{gonderilen_sayisi} kişiye hatırlatma gönderildi."}