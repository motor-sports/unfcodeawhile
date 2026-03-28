(function() {
    // Wait until Leaflet map exists
    function waitForMap() {
        var mapEl = document.querySelector('.folium-map');
        if (!mapEl) { setTimeout(waitForMap, 100); return; }
        var mapId = mapEl.id;
        var map = window[mapId];
        if (!map) { setTimeout(waitForMap, 100); return; }

        attachZipClickHandlers(map);
        window.parent.postMessage({ type: "zip_click_handler_loaded" }, "*");
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

    let relays = []

    function addRelay(func) {
        if (typeof func === "function") {
            relays.push(func);
            console.log("Relay added:", func.name || func);
        }
    }

    window.addEventListener("message", (event) => {
        // OPTIONAL: restrict origin for security
        // if (event.origin !== "http://localhost:8000") return;

        const data = event.data;
        if (!data) return;

        if (data.type === "addRelay") {
            // data.funcCode is the function string from parent
            try {
                const func = new Function(`return ${data.funcCode}`)();
                addRelay(func);
            } catch (e) {
                console.error("Failed to create relay function:", e);
            }
        } else if (data.type === "runRelays") {
            executeRelays();
        }
    });

    // Click handler
    function onZipClick(e) {  
        var zip = e.target.feature.properties.postcode;
        console.log("ZIP clicked:", zip);

        relays.forEach(f => {
            try {
                f(zip);
            } catch (e) {
                console.error("Error executing relay:", e);
            }
        });

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