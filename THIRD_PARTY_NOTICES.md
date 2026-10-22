# Third-party notices and asset provenance

## Application source

Hecklarr's application source was assembled for this project with AI coding assistance. The reviewed source uses Python's standard library and browser APIs; no vendored application libraries, frontend packages, external fonts, video files, or performer photographs are included.

Hecklarr's application source is licensed under the [GNU General Public License v3.0](LICENSE) (GPL-3.0-only). This inventory records third-party material; it is not a guarantee of originality, trademark clearance, or noninfringement.

## TMDB logo and data

`tmdb-logo.svg` is TMDB's approved **Alt short (blue)** SVG, downloaded without modification from its official [Logos & Attribution page](https://www.themoviedb.org/about/logos-attribution).

- Source: <https://www.themoviedb.org/assets/v4/logos/v2/blue_short-8e7b30f73a4020692ccca9c88bafe5dcb6f8a62a4c6bc55cd9ba82bb2cd95f6c.svg>
- SHA-256: `8e7b30f73a4020692ccca9c88bafe5dcb6f8a62a4c6bc55cd9ba82bb2cd95f6c`
- Conditions: [TMDB API terms](https://www.themoviedb.org/api-terms-of-use) and [attribution requirements](https://developer.themoviedb.org/docs/faq).

TMDB branding and API data remain subject to their own terms and are not covered by Hecklarr's GPL license. Users provide their own API credentials. The application identifies its API requests as `Hecklarr/0.1`, stores no movie posters or video, and expires cached metadata after 180 days. Commercial API use requires a separate agreement with TMDB.

This application uses TMDB and the TMDB APIs but is not endorsed, certified, or otherwise approved by TMDB.

## Hecklarr icon

`icon.png` is the user-selected generated raster image, copied byte-for-byte from the supplied PNG. It is used by the app, README, and browser icon. The earlier vector experiment is no longer the active icon.

The icon was generated and revised with OpenAI's image-generation tool. Prompts and visual-reference history are recorded in [icon-prompts.md](icon-prompts.md). The workflow used user-supplied visual references and a [microphone-clip product photograph](https://goknight.com/gator-gfw-mic-clip-standard-microphone-clip/) for hardware anatomy. Reference photographs are not bundled with the app; no performer likeness or product branding appears in the icon.

- PNG SHA-256: `157f9d62744ff33a657fa76fa65f4f65247df53b2d11d636bce9bc8f8980cc8d`
- PNG format: 600 × 600 RGBA.

AI assistance does not establish exclusivity or trademark clearance. The icon has not undergone a visual-similarity or trademark search.

## Container runtime

The source repository does not bundle Python, Alpine Linux, or their binaries. The Dockerfile builds on the official Python image pinned by digest and installs Alpine's `tzdata` package.

- Python: [license and incorporated-software notices](https://docs.python.org/3/license.html).
- Official image: [docker-library/python](https://github.com/docker-library/python) and [image documentation](https://hub.docker.com/_/python).
- Alpine packages: [package information and licenses](https://pkgs.alpinelinux.org/packages).
- Timezone database: [IANA timezone database](https://www.iana.org/time-zones).

A built container contains additional OS libraries and tools with their own licenses, including copyleft components. Hecklarr's GPL license does not replace those licenses. Publishing a container image requires a separate review of the exact built image's notices and applicable source-availability obligations.
