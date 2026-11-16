"""Procesa un pedido hecho desde la app (issue de GitHub) y actualiza data/seguir.json.
Título del issue: "[mi-cine] <accion>" ; cuerpo con líneas clave: valor
  accion: prioridad | quitar | seguir   (seguir = serie para avisos)
  tipo: movie | tv
  id: <id TMDB>   (opcional si viene 'buscar')
  titulo: <texto>
  buscar: <texto libre>   (si no hay id, busco en TMDB)
"""
import json, os, re, sys, urllib.parse, urllib.request

KEY = os.environ["TMDB_API_KEY"]
cuerpo = os.environ.get("CUERPO", "")
datos = dict(re.findall(r"^\s*(\w+)\s*:\s*(.+?)\s*$", cuerpo, flags=re.M))
accion = datos.get("accion", "prioridad").lower()
tipo = datos.get("tipo", "movie")


def tmdb(path, **p):
    p.update(api_key=KEY, language="es-AR")
    with urllib.request.urlopen(f"https://api.themoviedb.org/3{path}?{urllib.parse.urlencode(p)}", timeout=30) as r:
        return json.load(r)


ident = datos.get("id")
titulo = datos.get("titulo") or datos.get("buscar") or ""
if not ident and datos.get("buscar"):
    r = tmdb("/search/multi", query=datos["buscar"])["results"]
    r = [x for x in r if x.get("media_type") in ("movie", "tv")]
    if not r:
        print(f"No encontré «{datos['buscar']}» en TMDB.")
        sys.exit(0)
    ident, tipo = str(r[0]["id"]), r[0]["media_type"]
    titulo = r[0].get("title") or r[0].get("name")
ident = int(ident)

s = json.load(open("data/seguir.json", encoding="utf-8"))
s.setdefault("prioridades_id", [])
s.setdefault("series_id", [])
item = {"id": ident, "tipo": tipo, "titulo": titulo}

if accion == "quitar":
    s["prioridades_id"] = [x for x in s["prioridades_id"] if x["id"] != ident]
    s["series_id"] = [x for x in s["series_id"] if x["id"] != ident]
    s["quitados"] = sorted(set(s.get("quitados", []) + [ident]))
    msg = f"Saqué «{titulo}» de tus prioridades."
elif accion == "seguir" and tipo == "tv":
    if all(x["id"] != ident for x in s["series_id"]):
        s["series_id"].append({**item, "prioridad": False})
    msg = f"Ahora sigo «{titulo}»: te aviso de capítulos nuevos."
else:
    if tipo == "tv":
        s["series_id"] = [x for x in s["series_id"] if x["id"] != ident] + [{**item, "prioridad": True}]
    elif all(x["id"] != ident for x in s["prioridades_id"]):
        s["prioridades_id"].append(item)
    s["quitados"] = [x for x in s.get("quitados", []) if x != ident]
    msg = f"Agregué «{titulo}» a tus prioridades."

json.dump(s, open("data/seguir.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(msg)
