"""Consulta TMDB y genera data/tendencias.json. Avisa por ntfy.
Prueba v1: solo tendencias de la semana (películas y series)."""
import json, os, urllib.request, urllib.parse
from datetime import datetime, timezone

KEY = os.environ["TMDB_API_KEY"]
TOPIC = os.environ.get("NTFY_TOPIC", "")
BASE = "https://api.themoviedb.org/3"


def tmdb(path, **params):
    params.update(api_key=KEY, language="es-AR")
    url = f"{BASE}{path}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)


def limpiar(x):
    return {
        "id": x["id"],
        "tipo": x.get("media_type"),
        "titulo": x.get("title") or x.get("name"),
        "fecha": x.get("release_date") or x.get("first_air_date"),
        "poster": x.get("poster_path"),
        "puntaje": round(x.get("vote_average", 0), 1),
        "resumen": x.get("overview", ""),
    }


def avisar(titulo, mensaje):
    if not TOPIC:
        return
    req = urllib.request.Request(
        f"https://ntfy.sh/{TOPIC}",
        data=mensaje.encode(),
        headers={"Title": titulo.encode("utf-8"), "Tags": "movie_camera"},
    )
    urllib.request.urlopen(req, timeout=30)


def main():
    semana = [limpiar(x) for x in tmdb("/trending/all/week")["results"]]
    hoy = [limpiar(x) for x in tmdb("/trending/all/day")["results"]]
    os.makedirs("data", exist_ok=True)
    with open("data/tendencias.json", "w", encoding="utf-8") as f:
        json.dump(
            {"actualizado": datetime.now(timezone.utc).isoformat(), "semana": semana, "hoy": hoy},
            f, ensure_ascii=False, indent=1,
        )
    top = ", ".join(x["titulo"] for x in semana[:5])
    avisar("Mi cine: tendencias de la semana", f"Top 5: {top}")
    print("OK:", top)


if __name__ == "__main__":
    main()
