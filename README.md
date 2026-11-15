# KO'Z — jonli global OSINT xaritasi

**Sayt:** https://muzaffarkarshiev.github.io/koz/

Osiris'ga o'xshash, ochiq ma'lumotlar asosida ishlaydigan 3D globus:

| Qatlam | Manba | Yangilanish |
|---|---|---|
| Fuqaro reyslari (~10 000) | OpenSky Network | 30 s |
| Harbiy samolyotlar | adsb.lol | 30 s |
| Sun'iy yo'ldoshlar (~1000, ISS bilan) | CelesTrak (TLE) + satellite.js | har 2 s hisoblanadi |
| Starlink (~9000, ixtiyoriy) | CelesTrak | yoqilganda |
| Zilzilalar (24 soat, M2.5+) | USGS | 2 daq |
| Yong'in, vulqon, bo'ron, muz, toshqin | NASA EONET | 10 daq |
| Ofat ogohlantirishlari (to'q sariq/qizil) | GDACS | 10 daq |
| Geomagnit Kp indeksi | NOAA SWPC | 15 daq |

Qo'shimcha imkoniyatlar: qidiruv (reys kodi, yo'ldosh nomi yoki istalgan joy nomi), obyektni bosganda ma'lumot oynasi, so'nggi hodisalar lentasi, kun/tun xaritasi, "O'zbekiston" tugmasi.

## Ishga tushirish (1 daqiqa)

Faqat Python 3.9+ kerak. Hech narsa o'rnatish shart emas.

```bash
cd koz
python server.py
```

Brauzerda **http://localhost:8000** ni oching.

> `index.html` ni to'g'ridan-to'g'ri ikki marta bosib ochsangiz ham ishlaydi, lekin reyslar chiqmaydi. Brauzer reys API'lariga to'g'ridan-to'g'ri ulana olmaydi, shuning uchun ular `server.py` orqali olinadi.

## Internetga joylash

Sayt GitHub Pages'da turibdi. `.github/workflows/deploy.yml` har 10 daqiqada reys ma'lumotini yangilab, saytni qayta joylaydi (bunda reyslar 10 daqiqalik suratlar ko'rinishida chiqadi). Mutlaqo jonli reyslar kerak bo'lsa, `server.py` ni hostingda ishga tushiring:


`server.py` istalgan Python hostingda ishlaydi (Render, Railway, Fly.io, oddiy VPS). Port `PORT` muhit o'zgaruvchisidan olinadi.
Render misolida: New → Web Service → repo → Start command: `python server.py`.

## OpenSky limiti

Ro'yxatdan o'tmasdan OpenSky kuniga cheklangan miqdorda so'rov beradi. Server javoblarni 30 soniya keshlaydi, shuning uchun bir nechta foydalanuvchi bitta so'rovdan foydalanadi. Ko'proq kerak bo'lsa, https://opensky-network.org da bepul akkaunt oching, API client yarating va quyidagicha ishga tushiring:

```bash
OPENSKY_CLIENT_ID=... OPENSKY_CLIENT_SECRET=... python server.py
```

## Sozlash

- Yangilanish tezligi: `index.html` → `REFRESH`
- Yo'ldosh guruhlari: `loadSats` ichidagi `groups` ro'yxati (CelesTrak guruh nomlari)
- Ranglar: `index.html` boshidagi `:root` CSS o'zgaruvchilari

## Eslatma

Barcha ma'lumotlar ommaviy va ochiq manbalardan olinadi. Osiris'dagi CCTV kameralar va tarmoq skanerlash (Nmap) qatlamlari bu yerga ataylab qo'shilmagan.
