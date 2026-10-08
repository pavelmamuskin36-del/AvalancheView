# Bundled frontend resources

- MapLibre GL JS **5.6.2**, BSD-3-Clause: `vendor/maplibre-gl.js`, `vendor/maplibre-gl.css`, `vendor/LICENSE-maplibre.txt`. Source: https://github.com/maplibre/maplibre-gl-js ; distribution: https://unpkg.com/maplibre-gl@5.6.2/ . Includes third-party components under their respective licenses.
- deck.gl **9.1.14**, MIT: `vendor/deck.gl.js`, `vendor/LICENSE-deck.txt`. Source: https://github.com/visgl/deck.gl ; distribution: https://unpkg.com/deck.gl@9.1.14/dist.min.js . Includes luma.gl/loaders.gl/math.gl dependencies under their respective licenses.
- Natural Earth 1:110m admin_0 countries, public domain: `countries.geojson`. Source: https://github.com/nvkelso/natural-earth-vector/blob/master/geojson/ne_110m_admin_0_countries.geojson . Terms: https://www.naturalearthdata.com/about/terms-of-use/ . This is overview geography, not a source of precise model coordinates or political-boundary adjudication.
- Qt WebChannel JavaScript is supplied by installed Qt through `qrc:///qtwebchannel/qwebchannel.js`; Qt/PyQt distribution terms apply.

No online provider's tile collection is bundled. Providers keep their own attribution and terms in BasemapRegistry; no API keys are embedded.
