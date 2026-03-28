import requests

query = """
[out:xml][timeout:120];
area["name"="Jacksonville"]["admin_level"="8"]->.jax;
(
  way["highway"="motorway"](area.jax);
  way["highway"="trunk"](area.jax);
  way["highway"="primary"](area.jax);
  way["highway"="secondary"](area.jax);
);
out body;
>;
out skel qt;
"""

r = requests.get(
    "https://overpass-api.de/api/interpreter",
    params={"data": query},
    stream=True
)

with open("jacksonville_roads.xml", "wb") as f:
    for chunk in r.iter_content(chunk_size=8192):
        f.write(chunk)

print("Done — saved to jacksonville_roads.xml")