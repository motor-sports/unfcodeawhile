(function() {
    // Wait until Leaflet map exists
    function waitForMap() {
        var mapEl = document.querySelector('.folium-map');
        if (!mapEl) { setTimeout(waitForMap, 100); return; }
        var mapId = mapEl.id;
        var map = window[mapId];
        if (!map) { setTimeout(waitForMap, 100); return; }

        attachZipClickHandlers(map);
        console.log("ZIP click handler initialized");
    }

    // Recursively attach click handler to all GeoJson layers
    function attachZipClickHandlers(layer) {
        if (layer.feature && layer.feature.properties && layer.feature.properties.postcode) {
            layer.on('click', onZipClick);
        } else if (layer._layers) {
            for (var key in layer._layers) {
                attachZipClickHandlers(layer._layers[key]);
            }
        }
    }

    // Click handler
    function onZipClick(e) {
        var zip = e.target.feature.properties.postcode;
        console.log("ZIP clicked:", zip);

        // Dispatch custom event
        window.dispatchEvent(new CustomEvent("zipClick", { detail: { zip: zip } }));

        // Optional: highlight selection
        if (window.selectedZip) {
            window.selectedZip.setStyle({ weight: 0.8 });
        }
        window.selectedZip = e.target;
        e.target.setStyle({ weight: 3 });
    }

    // Start waiting
    waitForMap();
})();