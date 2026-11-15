#!/usr/bin/env python3
"""KO'Z — kichik server: saytni ochadi va reys ma'lumotlari uchun proxy vazifasini bajaradi.

Brauzer OpenSky va adsb.lol API'lariga to'g'ridan-to'g'ri ulana olmaydi (CORS),
shuning uchun bu server ularni o'zi olib, brauzerga uzatadi.
Faqat Python 3.9+ standart kutubxonasi kerak, hech narsa o'rnatish shart emas.

Ishga tushirish:   python server.py          ->  http://localhost:8000
Port o'zgartirish: PORT=9000 python server.py

Ixtiyoriy (OpenSky limitini oshirish uchun, https://opensky-network.org da bepul akkaunt):
  OPENSKY_CLIENT_ID=...  OPENSKY_CLIENT_SECRET=...  python server.py
"""
import json
import os
import threading
import time
import urllib.parse
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("PORT", "8000"))
UA = "KOZ-OSINT-Dashboard/1.0 (+https://github.com)"
OPENSKY_URL = "https://opensky-network.org/api/states/all"
OPENSKY_TOKEN_URL = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
MILITARY_URL = "https://api.adsb.lol/v2/mil"
CACHE_SECONDS = {"flights": 30, "military": 30, "cameras": 600}

_cache = {}
_lock = threading.Lock()
_token = {"value": None, "exp": 0}


def http_get(url, headers=None, data=None, timeout=25):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def opensky_headers():
    cid, secret = os.environ.get("OPENSKY_CLIENT_ID"), os.environ.get("OPENSKY_CLIENT_SECRET")
    if not cid or not secret:
        return {}
    if _token["value"] and time.time() < _token["exp"] - 60:
        return {"Authorization": "Bearer " + _token["value"]}
    body = urllib.parse.urlencode({"grant_type": "client_credentials", "client_id": cid, "client_secret": secret}).encode()
    tok = http_get(OPENSKY_TOKEN_URL, {"Content-Type": "application/x-www-form-urlencoded"}, data=body)
    _token.update(value=tok["access_token"], exp=time.time() + tok.get("expires_in", 1800))
    return {"Authorization": "Bearer " + _token["value"]}


def fetch_flights():
    d = http_get(OPENSKY_URL, opensky_headers())
    out = []
    for s in d.get("states") or []:
        # s: icao24, callsign, country, time_pos, last_contact, lon, lat, baro_alt, on_ground, velocity, track, ...
        if s[5] is None or s[6] is None or s[8]:
            continue
        alt = s[13] if s[13] is not None else s[7]
        out.append([s[0], s[1], s[2], round(s[5], 4), round(s[6], 4),
                    round(alt) if alt is not None else None,
                    round(s[9], 1) if s[9] is not None else None,
                    round(s[10]) if s[10] is not None else None])
    return {"time": d.get("time"), "states": out}


def fetch_military():
    d = http_get(MILITARY_URL)
    ac = []
    for a in d.get("ac") or []:
        if a.get("lat") is None or a.get("lon") is None:
            continue
        ac.append({k: a.get(k) for k in ("hex", "flight", "t", "r", "lat", "lon", "gs", "track")}
                  | {"alt": a.get("alt_baro") if isinstance(a.get("alt_baro"), (int, float)) else 0})
    return {"ac": ac}


# --- Kameralar: faqat davlat / yo'l xizmatlari OMMAGA OCHIQ efirga uzatadigan kameralar ---
TFL_URL = "https://api.tfl.gov.uk/Place/Type/JamCam"
# Caltrans (AQSh, Kaliforniya) rayonlari — ochiq ma'lumot, kalit talab qilmaydi
CALTRANS_DISTRICTS = ["d3", "d4", "d5", "d6", "d7", "d8", "d10", "d11", "d12"]
CALTRANS_URL = "https://cwwp2.dot.ca.gov/data/{d}/cctv/cctvStatus{D}.json"


def fetch_cameras():
    cams = []
    # Buyuk Britaniya — Transport for London JamCams
    try:
        for c in http_get(TFL_URL):
            props = {p["key"]: p.get("value") for p in c.get("additionalProperties", [])}
            if props.get("imageUrl") and c.get("lat") and c.get("lon"):
                cams.append({"lat": round(c["lat"], 5), "lng": round(c["lon"], 5),
                             "name": c.get("commonName", ""), "img": props["imageUrl"],
                             "video": props.get("videoUrl"), "cc": "GB"})
    except Exception:  # noqa: BLE001
        pass
    # AQSh (Kaliforniya) — Caltrans
    for d in CALTRANS_DISTRICTS:
        try:
            data = http_get(CALTRANS_URL.format(d=d, D=d.upper()))
            for item in data.get("data", []):
                cc = item.get("cctv", {})
                loc, img = cc.get("location", {}), cc.get("imageData", {})
                url = (img.get("static") or {}).get("currentImageURL") or img.get("streamingVideoURL")
                try:
                    lat, lng = float(loc.get("latitude")), float(loc.get("longitude"))
                except (TypeError, ValueError):
                    continue
                if url and lat and lng:
                    cams.append({"lat": round(lat, 5), "lng": round(lng, 5),
                                 "name": loc.get("locationName") or loc.get("nearbyPlace") or "",
                                 "img": url, "video": None, "cc": "US"})
        except Exception:  # noqa: BLE001
            continue
    # Butun dunyo ommaviy veb-kameralari — Windy (WINDY_KEY kerak).
    # Limitni tejash uchun 12 soatda bir marta yangilanadi (WINDY_CACHE_DIR keshi).
    cache_dir = os.environ.get("WINDY_CACHE_DIR")
    cache_file = os.path.join(cache_dir, "windy.json") if cache_dir else None
    wkey = os.environ.get("WINDY_KEY")
    windy = None
    if cache_file and os.path.exists(cache_file):
        try:
            blob = json.load(open(cache_file))
            if time.time() - blob.get("ts", 0) < 12 * 3600:
                windy = blob.get("cameras", [])
        except Exception:  # noqa: BLE001
            windy = None
    if windy is None and wkey:
        windy = []
        try:
            offset = 0
            while offset < 2000:
                d = http_get("https://api.windy.com/webcams/api/v3/webcams"
                             f"?limit=50&offset={offset}&include=location,images",
                             headers={"x-windy-api-key": wkey})
                webs = d.get("webcams") or []
                if not webs:
                    break
                for w in webs:
                    loc = w.get("location") or {}
                    cur = (w.get("images") or {}).get("current") or {}
                    prev = cur.get("preview") or cur.get("thumbnail")
                    if prev and loc.get("latitude") is not None:
                        windy.append({"lat": round(loc["latitude"], 5), "lng": round(loc["longitude"], 5),
                                      "name": w.get("title", ""), "img": prev, "video": None,
                                      "cc": loc.get("country_code") or ""})
                offset += 50
                if offset >= (d.get("total") or 0):
                    break
        except Exception:  # noqa: BLE001
            pass
        if cache_file and windy:
            try:
                os.makedirs(cache_dir, exist_ok=True)
                with open(cache_file, "w") as f:
                    json.dump({"ts": time.time(), "cameras": windy}, f)
            except Exception:  # noqa: BLE001
                pass
    if windy:
        cams.extend(windy)
    return {"cameras": cams}


IPTV = "https://iptv-org.github.io/api"


def build_tv(outdir):
    """Butun dunyo telekanallari — ochiq iptv-org ro'yxatidan tv.json tayyorlaydi."""
    import sys
    chans = {c["id"]: c for c in http_get(IPTV + "/channels.json")}
    streams = http_get(IPTV + "/streams.json")
    cmeta = {c["code"]: c for c in http_get(IPTV + "/countries.json")}
    bycc, seen = {}, {}
    for st in streams:
        url = st.get("url")
        if not url or not url.startswith("https") or ".m3u8" not in url:
            continue  # faqat https HLS oqimlar (statik saytda http bloklanadi)
        ch = chans.get(st.get("channel"))
        cc = (ch or {}).get("country") or "ZZ"
        name = (ch or {}).get("name") or st.get("title") or "TV"
        key = st.get("channel") or (cc + "|" + name)
        if key in seen:
            e = seen[key]
            if len(e["u"]) < 3:
                e["u"].append(url)
            continue
        e = {"n": name, "q": st.get("quality"), "u": [url]}
        seen[key] = e
        bycc.setdefault(cc, []).append(e)
    clist = []
    for cc, lst in bycc.items():
        lst.sort(key=lambda e: (e["n"] or "").lower())
        m = cmeta.get(cc, {})
        clist.append({"code": cc, "name": m.get("name") or cc, "flag": m.get("flag", ""), "count": len(lst)})
    clist.sort(key=lambda c: (-c["count"], c["name"]))
    out = {"countries": clist, "channels": bycc, "fetched": int(time.time())}
    with open(os.path.join(outdir, "tv.json"), "w") as f:
        json.dump(out, f, separators=(",", ":"), ensure_ascii=False)
    print(f"tv: {sum(len(v) for v in bycc.values())} kanal, {len(clist)} davlat", flush=True)


FETCHERS = {"flights": fetch_flights, "military": fetch_military, "cameras": fetch_cameras}


def cached(name):
    with _lock:
        hit = _cache.get(name)
        if hit and time.time() - hit[0] < CACHE_SECONDS[name]:
            return hit[1]
    try:
        data = FETCHERS[name]()
        with _lock:
            _cache[name] = (time.time(), data)
        return data
    except Exception as e:  # noqa: BLE001
        if hit:  # eski ma'lumotni qaytaramiz
            return hit[1]
        raise RuntimeError(f"{name}: {e}") from e


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path.startswith("/api/"):
            name = path[5:]
            if name not in FETCHERS:
                return self.send_error(404)
            try:
                body = json.dumps(cached(name), separators=(",", ":")).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
            except Exception as e:  # noqa: BLE001
                body = json.dumps({"error": str(e)}).encode()
                self.send_response(502)
                self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path in ("", "/"):
            self.path = "/index.html"
        elif path not in ("/index.html",):
            return self.send_error(404)  # faqat sayt fayli beriladi
        super().do_GET()

    def log_message(self, fmt, *args):
        if "/api/" not in str(args[0] if args else ""):
            super().log_message(fmt, *args)


def dump(outdir):
    """GitHub Actions uchun: ma'lumotni JSON fayllarga yozadi (statik hosting)."""
    import sys
    os.makedirs(outdir, exist_ok=True)
    for name, fn in FETCHERS.items():
        try:
            data = fn()
            data["fetched"] = int(time.time())
            with open(os.path.join(outdir, name + ".json"), "w") as f:
                json.dump(data, f, separators=(",", ":"))
            print(f"{name}: OK")
        except Exception as e:  # noqa: BLE001
            print(f"{name}: XATO {e}", file=sys.stderr)
    try:
        build_tv(outdir)
    except Exception as e:  # noqa: BLE001
        print(f"tv: XATO {e}", file=sys.stderr)


if __name__ == "__main__":
    import sys
    if len(sys.argv) == 3 and sys.argv[1] == "--dump":
        dump(sys.argv[2])
        raise SystemExit(0)
    print(f"KO'Z ishga tushdi:  http://localhost:{PORT}   (to'xtatish: Ctrl+C)")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
