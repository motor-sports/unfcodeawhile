import json
import time
import argparse

from lxml import etree
import osm2geojson
import geopandas as gpd
import pandas as pd
import folium


# ═════════════════════════════════════════════════════════════════════
# CONFIG  — edit these paths if needed
# ═════════════════════════════════════════════════════════════════════
DEFAULT_SHAPEFILE  = "tl_2023_us_zcta520/tl_2023_us_zcta520.shp"
DEFAULT_ROADS_XML  = "tl_2023_us_zcta520/jacksonville_roads.xml"
DEFAULT_ZIP_PREFIX = "322"          # all Jacksonville ZIPs start with 322
OUTPUT_FILE        = "map.html"

MAJOR_ROAD_TYPES = {"motorway", "trunk", "primary", "secondary"}

ROAD_STYLES = {
    "motorway":  {"color": "#cccccc", "weight": 1},
    "trunk":     {"color": "#cccccc", "weight": 1},
    "primary":   {"color": "#cccccc", "weight": 1},
    "secondary": {"color": "#cccccc", "weight": 1},
}

# Distinct map colors — chosen to be visually separable on a dark basemap.
# Uses a 4-color-map-safe palette so adjacent ZIPs never share a color.
MAP_PALETTE = [
    "#e63946",  # red
    "#2a9d8f",  # teal
    "#e9c46a",  # gold
    "#6a4c93",  # purple
    "#f4a261",  # orange
    "#457b9d",  # steel blue
    "#a8dadc",  # ice blue
    "#52b788",  # green
    "#c77dff",  # violet
    "#fb8500",  # amber
    "#48cae4",  # cyan
    "#d62828",  # dark red
    "#80b918",  # lime
    "#ff6b6b",  # salmon
    "#4cc9f0",  # sky
    "#b5838d",  # mauve
    "#06d6a0",  # mint
    "#ffd166",  # yellow
    "#118ab2",  # ocean
    "#ef476f",  # pink
]


# ═════════════════════════════════════════════════════════════════════
# STEP 1 — ZIP BOUNDARIES from Census TIGER shapefile
# ═════════════════════════════════════════════════════════════════════
def load_zip_boundaries(shp_path: str, zip_prefix: str) -> gpd.GeoDataFrame:
    t0 = time.perf_counter()
    print(f"[1/3] Loading ZIP boundaries from: {shp_path}")

    zcta = gpd.read_file(shp_path)

    # Find the ZIP code column (differs slightly across TIGER vintages)
    zip_col = next(
        (c for c in zcta.columns if "ZCTA" in c.upper() or "ZIP" in c.upper()),
        None
    )
    if zip_col is None:
        raise ValueError(
            f"Could not find ZIP column in shapefile. "
            f"Columns present: {zcta.columns.tolist()}"
        )

    # Filter to the target prefix
    gdf = zcta[zcta[zip_col].str.startswith(zip_prefix)].copy()
    if gdf.empty:
        raise ValueError(
            f"No ZIP codes starting with '{zip_prefix}' found in shapefile."
        )

    gdf = (
        gdf.rename(columns={zip_col: "postcode"})
           .to_crs("EPSG:4326")[["postcode", "geometry"]]
    )

    # Simplify — reduces file size and speeds up browser rendering
    gdf["geometry"] = gdf.geometry.simplify(0.0001, preserve_topology=True)

    # Assign a distinct color to each ZIP (cycles through palette)
    sorted_zips = sorted(gdf["postcode"].unique())
    color_map   = {z: MAP_PALETTE[i % len(MAP_PALETTE)]
                   for i, z in enumerate(sorted_zips)}
    gdf["color_"] = gdf["postcode"].map(color_map)

    print(f"    {len(gdf)} ZIP regions  ({time.perf_counter()-t0:.1f}s)")
    return gdf


# ═════════════════════════════════════════════════════════════════════
# STEP 2 — ROADS from Overpass / OSM XML
# ═════════════════════════════════════════════════════════════════════
def load_roads(xml_path: str) -> gpd.GeoDataFrame:
    t0 = time.perf_counter()
    print(f"[2/3] Loading roads from: {xml_path}")

    tree = etree.parse(xml_path)
    root = tree.getroot()

    # Index all nodes for fast geometry reconstruction
    nodes_by_id = {el.get("id"): el for el in root.findall("node")}

    wanted_way_ids:  set[str] = set()
    wanted_node_ids: set[str] = set()

    for way in root.findall("way"):
        tags = {t.get("k"): t.get("v") for t in way.findall("tag")}
        if tags.get("highway") in MAJOR_ROAD_TYPES:
            wanted_way_ids.add(way.get("id"))
            for nd in way.findall("nd"):
                wanted_node_ids.add(nd.get("ref"))

    if not wanted_way_ids:
        print("    [warn] no major roads found — road layer will be empty")
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    # Rebuild minimal OSM XML with only roads + their nodes
    osm_el = etree.Element("osm", attrib={"version": "0.6"})
    for nid, el in nodes_by_id.items():
        if nid in wanted_node_ids:
            osm_el.append(el)
    for way in root.findall("way"):
        if way.get("id") in wanted_way_ids:
            osm_el.append(way)

    xml_string = etree.tostring(osm_el, encoding="unicode")
    geojson    = osm2geojson.xml2geojson(
        xml_string, filter_used_refs=False, log_level="ERROR"
    )
    gdf = gpd.GeoDataFrame.from_features(geojson["features"], crs="EPSG:4326")

    # Flatten tags — drop columns that already exist to avoid collisions
    if "tags" in gdf.columns:
        tags_df = (
            gdf["tags"]
            .dropna()
            .apply(lambda x: x if isinstance(x, dict) else {})
            .apply(pd.Series)
        )
        existing = set(gdf.columns) - {"tags"}
        tags_df  = tags_df.drop(
            columns=[c for c in tags_df.columns if c in existing],
            errors="ignore"
        )
        gdf = gdf.drop(columns=["tags"]).join(tags_df)

    # Keep only major road lines
    road_gdf = gdf[
        gdf.geometry.geom_type.isin(["LineString", "MultiLineString"]) &
        gdf.get("highway", pd.Series(dtype=str)).isin(MAJOR_ROAD_TYPES)
    ].copy()

    # Simplify geometry
    road_gdf["geometry"] = road_gdf.geometry.simplify(
        0.00005, preserve_topology=True
    )

    # Add style columns so a single GeoJson call can colour each road
    road_gdf["_color"]  = road_gdf["highway"].map(
        {k: v["color"]  for k, v in ROAD_STYLES.items()}
    ).fillna("#ccc")
    road_gdf["_weight"] = road_gdf["highway"].map(
        {k: v["weight"] for k, v in ROAD_STYLES.items()}
    ).fillna(2)

    # Keep only the columns we need
    keep = ["geometry", "highway", "_color", "_weight"]
    if "name" in road_gdf.columns:
        keep.append("name")
    road_gdf = road_gdf[keep]

    print(f"    {len(road_gdf)} road segments  ({time.perf_counter()-t0:.1f}s)")
    return road_gdf


# ═════════════════════════════════════════════════════════════════════
# STEP 3 — BUILD FOLIUM MAP
# ═════════════════════════════════════════════════════════════════════
def build_map(zip_gdf: gpd.GeoDataFrame, road_gdf: gpd.GeoDataFrame) -> folium.Map:
    t0 = time.perf_counter()
    print("[3/3] Building map")

    centroid = zip_gdf.geometry.union_all().centroid
    minx, miny, maxx, maxy = zip_gdf.total_bounds
    padding = 0.01
    bounds = [[miny-padding, minx-padding], [maxy+padding, maxx+padding]]

    m = folium.Map(
        location=[(miny+maxy)/2, (minx+maxx)/2],
        zoom_start=11,
        tiles=None,
        zoom_control=False,       # remove buttons
        scrollWheelZoom=True,    # disable mouse wheel
        dragging=True,            # allow panning
        doubleClickZoom=False,    # disable double-click zoom
        touchZoom=True,            # pinch zoom still works on mobile
        max_bounds=bounds
    )

    zoom_js = f"""
    <script>
    (function waitForMap() {{
        var mapEl = document.querySelector('.folium-map');
        if (!mapEl) {{ setTimeout(waitForMap, 100); return; }}
        var map = window[mapEl.id];
        if (!map) {{ setTimeout(waitForMap, 100); return; }}

        map.setMinZoom(10);


        console.log("Zoom bounds set: min=10");
    }})();
    </script>
    """
    m.get_root().html.add_child(folium.Element(zoom_js))

    max_bounds_js = f"""
    <script>
    (function waitForMap() {{
        var mapEl = document.querySelector('.folium-map');
        if (!mapEl) {{ setTimeout(waitForMap, 100); return; }}
        var map = window[mapEl.id];
        if (!map) {{ setTimeout(waitForMap, 100); return; }}

        // Set max bounds once map is ready
        var bounds = L.latLngBounds({bounds});
        map.setMaxBounds(bounds);
        map.options.maxBoundsViscosity = 1.0;

        console.log("Max bounds applied:", bounds);
    }})();
    </script>
    """
    m.get_root().html.add_child(folium.Element(max_bounds_js))

    folium.TileLayer(
        tiles="https://{s}.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}{r}.png",
        attr="CartoDB",
        name="Dark",
        show=True
    ).add_to(m)

    folium.TileLayer(
        tiles="https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png",
        attr="CartoDB",
        name="Light",
        show=False
    ).add_to(m)

    # ── ZIP boundary layer ────────────────────────────────────────────
    zip_layer = folium.FeatureGroup(name="ZIP Code Regions", show=True)
    folium.GeoJson(
        data=json.loads(zip_gdf.to_json()),
        style_function=lambda f: {
            "fillColor":   f["properties"].get("color_", "#4a90d9"),
            "color":       "#ffffff",   # white border separates adjacent ZIPs
            "weight":      0.8,
            "fillOpacity": 0.45,
        },
        tooltip=folium.GeoJsonTooltip(
            fields=["postcode"],
            aliases=["ZIP:"],
            style=(
                "background:#1a1a2e;color:#fff;"
                "border:none;font-size:13px;padding:6px 10px;"
            ),
        ),
    ).add_to(zip_layer)
    zip_layer.add_to(m)

    # ── Labels always on top via custom Leaflet pane ──────────────────
    # Leaflet z-index order: tilePane=200, overlayPane=400, shadowPane=500,
    # markerPane=600. We create a pane at 650 so labels render above all
    # vector layers (ZIP polygons, roads). pointerEvents=none so clicks
    # pass through to the map underneath.
    labels_js = """
    <script>
    (function waitForMap() {
        var mapEl = document.querySelector('.folium-map');
        if (!mapEl) { setTimeout(waitForMap, 100); return; }
        var mapId = mapEl.id;
        var map   = window[mapId];
        if (!map)  { setTimeout(waitForMap, 100); return; }

        // Create high-z pane
        var pane = map.createPane('labelsPane');
        pane.style.zIndex     = 650;
        pane.style.pointerEvents = 'none';

        // Labels tile layer
        var labelsLayer = L.tileLayer(
            'https://{s}.basemaps.cartocdn.com/dark_only_labels/{z}/{x}/{y}{r}.png',
            { attribution: 'CartoDB', pane: 'labelsPane', opacity: 1.0 }
        );
        labelsLayer.addTo(map);

        // Wire into layer control so it's toggleable
        // Find the existing layer control and add Labels as an overlay
        map.eachLayer(function(l) {
            if (l._layers) {  // it's a layer control
                l.addOverlay(labelsLayer, 'Labels');
            }
        });
    })();
    </script>
    """
    m.get_root().html.add_child(folium.Element(labels_js))
    folium.LayerControl(position="bottomleft", collapsed=False).add_to(m)

    m.get_root().html.add_child(folium.Element('<script src="zip_click_handler.js"></script>'))

    print(f"    done  ({time.perf_counter()-t0:.1f}s)")
    return m


# ═════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(description="Render ZIP regions + major roads")
    parser.add_argument("--shapefile",  default=DEFAULT_SHAPEFILE,
                        help="Path to Census TIGER .shp file")
    parser.add_argument("--roads",      default=DEFAULT_ROADS_XML,
                        help="Path to OSM roads .xml file")
    parser.add_argument("--zip-prefix", default=DEFAULT_ZIP_PREFIX,
                        help="ZIP prefix to filter (e.g. 322 for Jacksonville)")
    parser.add_argument("--output",     default=OUTPUT_FILE,
                        help="Output HTML filename")
    args = parser.parse_args()

    t_total = time.perf_counter()

    zip_gdf  = load_zip_boundaries(args.shapefile, args.zip_prefix)
    road_gdf = load_roads(args.roads)
    m        = build_map(zip_gdf, road_gdf)

    m.save(args.output)
    print(f"\n✓ Saved → {args.output}  (total: {time.perf_counter()-t_total:.1f}s)")


if __name__ == "__main__":
    main()