# Bundle signing modes and environment variables

- HMAC signing: set `CONTINUUM_SIGNING_KEY` (or `CONTINUUM_BUNDLE_HMAC_KEY`).
- Ed25519 signing: set `CONTINUUM_SIGNING_PRIVATE_KEY` or `CONTINUUM_SIGNING_PRIVATE_KEY_FILE`.
- Ed25519 verification: set `CONTINUUM_SIGNING_PUBLIC_KEY` or `CONTINUUM_SIGNING_PUBLIC_KEY_FILE` (public-key only verification supported).
