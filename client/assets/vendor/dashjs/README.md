# Vendored dash.js dependency

The player bundle is stored in `5.2.1/dash.all.debug.js` and declares dash.js
version 5.2.1. This move preserves the existing bundle byte for byte.

- Upstream project: https://github.com/Dash-Industry-Forum/dash.js
- Versioned distribution: https://cdn.dashjs.org/v5.2.1/modern/umd/dash.all.debug.js
- SHA-256 of the checked-in bundle: `94a3c83e8c78da6f4f29ecca2403d6c4114c7edca79349a092e7df87c5d9aa53`

Keep simulator behavior in `client/assets/js/main.js`; do not patch this bundle.
For an upgrade, replace the dependency from the versioned upstream distribution,
update its directory, the script URL in `client/index.html`, this checksum and
version references, then run the Redis tests and browser smoke test. Check native
Content Steering, all three BaseURLs, CMCD v2 reporting and decision correlation.

The checksum records this repository's bundle; it is not an independent upstream
integrity verification. See upstream for license and release information.
