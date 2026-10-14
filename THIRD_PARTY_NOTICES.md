# Third-party notices and asset provenance

## Application source

Hecklarr's application source was assembled for this project with AI coding assistance. The reviewed source uses Python's standard library and browser APIs; no vendored application libraries, frontend packages, external fonts, video files, or performer photographs are included.

This inventory records the material found in the release. It is not a guarantee of originality, trademark clearance, or noninfringement. A project license has not yet been selected; this notice does not grant a license to the application source.

## TMDB logo and data

`tmdb-logo.svg` is TMDB's approved **Alt short (blue)** SVG, downloaded without modification from its official [Logos & Attribution page](https://www.themoviedb.org/about/logos-attribution).

- Source: <https://www.themoviedb.org/assets/v4/logos/v2/blue_short-8e7b30f73a4020692ccca9c88bafe5dcb6f8a62a4c6bc55cd9ba82bb2cd95f6c.svg>
- SHA-256: `8e7b30f73a4020692ccca9c88bafe5dcb6f8a62a4c6bc55cd9ba82bb2cd95f6c`
- Conditions: [TMDB API terms](https://www.themoviedb.org/api-terms-of-use) and [attribution requirements](https://developer.themoviedb.org/docs/faq).

TMDB branding and API data remain subject to their own terms and are not covered by a future license for Hecklarr's code. Users provide their own API credentials. The application identifies its API requests as `Hecklarr/0.1`, stores no movie posters or video, and expires cached metadata after 180 days. Commercial API use requires a separate agreement with TMDB.

This application uses TMDB and the TMDB APIs but is not endorsed, certified, or otherwise approved by TMDB.

## Hecklarr icon

`icon.png` was generated and revised with OpenAI's image-generation tool for this project. The prompts and revisions are recorded in [icon-prompts.md](icon-prompts.md). The revisions used the earlier generated icon as their reference; no performer likeness or third-party photograph was supplied in that recorded workflow.

- SHA-256: `fa3cb8f3044d6e5bc2d0fec439099618775c4cefaee6670f7d723d7d49ff59d0`
- Format: 1254 × 1254 RGB PNG.
- The image retains its embedded generation-provenance metadata.

AI generation does not establish exclusivity or trademark clearance. The icon has not undergone a visual-similarity or trademark search.

## Container runtime

The source repository does not bundle Python, Alpine Linux, or their binaries. The Dockerfile builds on the official Python image pinned by digest and installs Alpine's `tzdata` package.

- Python: [license and incorporated-software notices](https://docs.python.org/3/license.html).
- Official image: [docker-library/python](https://github.com/docker-library/python) and [image documentation](https://hub.docker.com/_/python).
- Alpine packages: [package information and licenses](https://pkgs.alpinelinux.org/packages).
- Timezone database: [IANA timezone database](https://www.iana.org/time-zones).

A built container contains additional OS libraries and tools with their own licenses, including copyleft components. A license chosen for Hecklarr does not replace those licenses. Publishing a container image requires a separate review of the exact built image's notices and applicable source-availability obligations.
