"""Mi cine: consulta TMDB, arma los JSON de la app y avisa por ntfy.

- Tendencias (películas y series, hoy y semana).
- Para cada título de tu watchlist de Letterboxd: estado digital / HD.
  "HD" = salió en digital (alquiler/compra/streaming) en Argentina o en EE.UU.,
  o aparece en alguna plataforma legal en Argentina.
- Avisa solo cuando un título CAMBIA a HD respecto de la corrida anterior.
"""
import json, os, time, urllib.request, urllib.parse
from datetime import date, datetime, timedelta, timezone

KEY = os.environ["TMDB_API_KEY"]
TOPIC = os.environ.get("NTFY_TOPIC", "")
BASE = "https://api.themoviedb.org/3"
AHORA_AR = datetime.now(timezone.utc) - timedelta(hours=3)
HOY = AHORA_AR.date().isoformat()
APP = "https://guillemontiveros.github.io/MI-CINE/"


def tmdb(path, **params):
    params.update(api_key=KEY, language="es-AR")
    url = f"{BASE}{path}?{urllib.parse.urlencode(params)}"
    for intento in range(3):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.load(r)
        except Exception:
            if intento == 2:
                raise
            time.sleep(2)


def leer(ruta, defecto):
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return defecto


def guardar(ruta, datos):
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=1)


def avisar(titulo, mensaje, click=None):
    if not TOPIC:
        return
    h = {"Title": titulo.encode("utf-8"), "Tags": "movie_camera"}
    if click:
        h["Click"] = click
    req = urllib.request.Request(f"https://ntfy.sh/{TOPIC}", data=mensaje.encode(), headers=h)
    urllib.request.urlopen(req, timeout=30)


def tarjeta(x, tipo=None):
    return {
        "id": x["id"],
        "tipo": x.get("media_type") or tipo,
        "titulo": x.get("title") or x.get("name"),
        "fecha": x.get("release_date") or x.get("first_air_date"),
        "poster": x.get("poster_path"),
        "puntaje": round(x.get("vote_average", 0), 1),
    }


# ---------- Watchlist ----------

def buscar_id(t, cache):
    clave = f"{t['titulo']}|{t['anio']}"
    if clave in cache:
        return cache[clave]
    res = tmdb("/search/movie", query=t["titulo"], year=t["anio"] or "")["results"]
    tipo = "movie"
    if not res:
        res = tmdb("/search/tv", query=t["titulo"], first_air_date_year=t["anio"] or "")["results"]
        tipo = "tv"
    cache[clave] = {"id": res[0]["id"], "tipo": tipo} if res else None
    return cache[clave]


def plataformas(wp):
    ar = wp.get("results", {}).get("AR", {})
    out = {}
    for modo in ("flatrate", "rent", "buy"):
        nombres = [p["provider_name"] for p in ar.get(modo, [])]
        if nombres:
            out[modo] = nombres
    return out, ar.get("link")


def fecha_digital(rd, pais):
    for r in rd.get("results", []):
        if r["iso_3166_1"] == pais:
            fechas = [d["release_date"][:10] for d in r["release_dates"] if d["type"] == 4]
            if fechas:
                return min(fechas)
    return None


def estado_titulo(ref):
    if ref["tipo"] == "movie":
        d = tmdb(f"/movie/{ref['id']}", append_to_response="release_dates,watch/providers")
        dig_ar = fecha_digital(d.get("release_dates", {}), "AR")
        dig_us = fecha_digital(d.get("release_dates", {}), "US")
    else:
        d = tmdb(f"/tv/{ref['id']}", append_to_response="watch/providers")
        dig_ar = dig_us = None
    plats, link = plataformas(d.get("watch/providers", {}))
    hd = bool(plats) or any(f and f <= HOY for f in (dig_ar, dig_us))
    if plats:
        motivo = "Disponible en Argentina"
    elif dig_ar and dig_ar <= HOY:
        motivo = f"Salió en digital en Argentina ({dig_ar})"
    elif dig_us and dig_us <= HOY:
        motivo = f"Salió en digital en EE.UU. ({dig_us})"
    else:
        motivo = None
    proximo = min([f for f in (dig_ar, dig_us) if f and f > HOY], default=None)
    return {
        **tarjeta(d, ref["tipo"]),
        "hd": hd,
        "motivo": motivo,
        "digital_ar": dig_ar,
        "digital_us": dig_us,
        "digital_proximo": proximo,
        "plataformas": plats,
        "link": link,
    }


# ---------- Series ----------

def ep(e):
    if not e:
        return None
    return {"id": e["id"], "fecha": e.get("air_date"), "t": e.get("season_number"),
            "e": e.get("episode_number"), "nombre": e.get("name")}


def estado_serie(nombre, cache):
    clave = f"serie|{nombre}"
    if clave not in cache:
        r = tmdb("/search/tv", query=nombre)["results"]
        cache[clave] = r[0]["id"] if r else None
    if not cache[clave]:
        return None
    d = tmdb(f"/tv/{cache[clave]}", append_to_response="watch/providers")
    plats, link = plataformas(d.get("watch/providers", {}))
    return {**tarjeta(d, "tv"), "estado": d.get("status"), "ultimo": ep(d.get("last_episode_to_air")),
            "proximo": ep(d.get("next_episode_to_air")), "plataformas": plats, "link": link}


def codigo(x):
    return f"T{x['t']} E{x['e']}"


# ---------- Cineclubs ----------

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def cineclubs(enviados):
    cfg = leer("data/cineclubs.json", {"clubes": []})
    hoy_dia = DIAS[AHORA_AR.weekday()]
    hora_ar = AHORA_AR.hour
    for c in cfg["clubes"]:
        if c.get("fecha") and c["fecha"] < HOY:
            c["pelicula"] = c["fecha"] = None  # función pasada: se limpia
        clave = f"club|{c['nombre']}|{HOY}"
        if c["dia"] == hoy_dia and hora_ar >= 12 and clave not in enviados:
            peli = c.get("pelicula") or "fijate qué pelí dan en su Instagram"
            hora = f" a las {c['hora']}" if c.get("hora") else ""
            avisar(f"🎟️ Hoy hay cineclub en {c['nombre']}", f"Gratis{hora}: {peli}", c.get("instagram"))
            enviados.append(clave)
    guardar("data/cineclubs.json", cfg)


def main():
    app = APP
    # Tendencias
    tend = {
        "pelis_hoy": [tarjeta(x, "movie") for x in tmdb("/trending/movie/day")["results"]],
        "pelis_semana": [tarjeta(x, "movie") for x in tmdb("/trending/movie/week")["results"]],
        "series_hoy": [tarjeta(x, "tv") for x in tmdb("/trending/tv/day")["results"]],
        "series_semana": [tarjeta(x, "tv") for x in tmdb("/trending/tv/week")["results"]],
        "hoy": [tarjeta(x) for x in tmdb("/trending/all/day")["results"]],
    }

    # Watchlist
    lb = leer("data/letterboxd.json", {"esperadas": []})
    cache = leer("data/ids.json", {})
    anterior = {str(x["id"]): x for x in leer("data/esperadas.json", {"titulos": []})["titulos"]}
    primera_vez = not anterior
    titulos, nuevos_hd = [], []
    for t in lb["esperadas"]:
        try:
            ref = buscar_id(t, cache)
            if not ref:
                continue
            e = estado_titulo(ref)
        except Exception as err:
            print("Error con", t["titulo"], err)
            continue
        e["agregada"] = t["agregada"]
        previo = anterior.get(str(e["id"]))
        e["hd_desde"] = (previo or {}).get("hd_desde") or (HOY if e["hd"] else None)
        if e["hd"] and previo is not None and not previo.get("hd"):
            nuevos_hd.append(e)
        titulos.append(e)

    # Prioridades (se suman a la vigilancia de HD aunque no estén en la watchlist)
    seguir = leer("data/seguir.json", {"series": [], "prioridades": []})
    ids_wl = {e["id"] for e in titulos}
    prioridades = []
    for nombre, anio in seguir["prioridades"]:
        try:
            ref = buscar_id({"titulo": nombre, "anio": str(anio)}, cache)
            if not ref:
                continue
            if ref["id"] in ids_wl:
                e = next(x for x in titulos if x["id"] == ref["id"])
            else:
                e = estado_titulo(ref)
                previo = anterior.get(str(e["id"]))
                e["hd_desde"] = (previo or {}).get("hd_desde") or (HOY if e["hd"] else None)
                if e["hd"] and previo is not None and not previo.get("hd"):
                    nuevos_hd.append(e)
                titulos.append(e)
            e["prioridad"] = True
            prioridades.append(e["id"])
        except Exception as err:
            print("Error con", nombre, err)

    # Series
    estado = leer("data/estado.json", {"enviados": []})
    enviados = estado["enviados"]
    previas = {str(x["id"]): x for x in leer("data/series.json", {"series": []})["series"]}
    series = []
    for nombre in seguir["series"]:
        try:
            sr = estado_serie(nombre, cache)
        except Exception as err:
            print("Error con", nombre, err)
            continue
        if not sr:
            continue
        series.append(sr)
        pv = previas.get(str(sr["id"]), {})
        u, p = sr["ultimo"], sr["proximo"]
        link = sr.get("link") or app
        if u and u["fecha"] and u["fecha"] >= (date.fromisoformat(HOY) - timedelta(days=2)).isoformat():
            k = f"ep|{u['id']}"
            if k not in enviados:
                avisar(f"📺 Salió capítulo nuevo de {sr['titulo']}", f"{codigo(u)}: {u['nombre']}", link)
                enviados.append(k)
        if p and p["fecha"] and p["e"] == 1 and (pv.get("proximo") or {}).get("id") != p["id"]:
            k = f"temp|{p['id']}"
            if k not in enviados:
                avisar(f"📅 {sr['titulo']}: temporada {p['t']} ya tiene fecha", f"Se estrena el {p['fecha']}", link)
                enviados.append(k)
    cineclubs(enviados)
    estado["enviados"] = enviados[-500:]

    ahora = datetime.now(timezone.utc).isoformat()
    guardar("data/estado.json", estado)
    guardar("data/series.json", {"actualizado": ahora, "series": series, "prioridades": prioridades})
    guardar("data/ids.json", cache)
    guardar("data/esperadas.json", {"actualizado": ahora, "titulos": titulos})
    guardar("data/tendencias.json", {"actualizado": ahora, **tend})

    for e in nuevos_hd:
        donde = ", ".join(sum(e["plataformas"].values(), [])) or e["motivo"]
        avisar(f"🎬 {e['titulo']} ya está en HD", f"{e['motivo']}. {donde}", e.get("link") or app)
    if primera_vez:
        n = sum(1 for e in titulos if e["hd"])
        avisar("Mi cine: vigilancia activada",
               f"Sigo {len(titulos)} títulos de tu watchlist. {n} ya están en HD. "
               "Desde ahora te aviso cuando otra pase a HD.", app)
    print(f"OK: {len(titulos)} títulos, {len(nuevos_hd)} nuevos en HD")


if __name__ == "__main__":
    main()
