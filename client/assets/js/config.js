var CACHE_COORDS = {
    "delivery-node-1": { lat: -23.0, lon: -47.0, label: "Cache 1 (BR)" },
    "delivery-node-2": { lat: -33.0, lon: -71.0, label: "Cache 2 (CL)" },
    "delivery-node-3": { lat:  5.0,  lon: -74.0, label: "Cache 3 (CO)" }
};

// Como você está usando o Gateway no dash-client, aponte para o localhost
var STEERING_SERVER_URL = "https://localhost:30500";

console.log("Config loaded. UI Origin: " + window.location.origin);
