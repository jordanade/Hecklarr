<img src="icon.png" alt="Hecklarr microphone icon" width="96">

# Hecklarr

Track your favorite stand-up comedians and automatically add their specials to Radarr.

Hecklarr finds specials through TMDB and maintains a Radarr import list. Radarr handles searching, downloading, renaming, and importing. Point Plex at a separate comedy folder to give your specials their own library.

## Features

- Find comedians by name and build a watchlist.
- Discover new and back-catalog specials, displayed newest first.
- Send specials to Radarr with your chosen destination folder and quality profile.
- Refresh on demand or automatically each day at 3 AM in the configured timezone.
- Review excluded titles and manually include specials with incomplete metadata.
- Preserve the last successful catalog during temporary outages, with a 180-day metadata expiry.

## Requirements

- Docker with Docker Compose.
- Radarr with working indexers and a download client.
- A [TMDB API key or API Read Access Token](https://developer.themoviedb.org/docs/getting-started).
- A destination folder Radarr can write to.

Hecklarr connects to Radarr and TMDB; it does not require access to your media files or download client.

## Installation

Clone this repository or download and extract its ZIP. Run these commands from the directory containing `Dockerfile` and `compose.yaml`.

On a Linux Docker host, prepare the configuration directory for the container, which runs as UID/GID `1000:1000`:

```sh
mkdir -p config
sudo chown 1000:1000 config
sudo chmod 700 config
```

Start Hecklarr:

```sh
docker compose up -d --build
```

Open **[http://localhost:6162](http://localhost:6162)** on the Docker host.

### Access from another computer

By default, the app listens only on the Docker host's loopback address. To make it accessible on your local network, create a `.env` file beside `compose.yaml`:

```dotenv
HECKLARR_BIND_ADDRESS=192.168.1.10
TZ=America/Detroit
```

Replace `192.168.1.10` with your Docker host's LAN IP and choose your timezone. Apply the change:

```sh
docker compose up -d
```

Then open **`http://YOUR_SERVER_IP:6162`** in your browser. Keep direct HTTP access on your private network; use an HTTPS reverse proxy for remote access.

### Add to an existing Compose stack

Copy the service from `compose.yaml` into your stack. Adjust `build` to point at the Hecklarr source directory and the volume to a persistent configuration directory owned by `1000:1000`.

If Radarr and Hecklarr share a Docker network, they can use service names to reach each other. Otherwise, use addresses reachable from the respective containers.

## First run

1. Open Hecklarr and create your account with a username, password, and password confirmation. Passwords must have at least eight characters. Internal keys are generated automatically.
2. Sign in. The first login shows **Library settings** with only **Radarr address**, **Radarr API key**, and **Connect to Radarr**.
3. Enter the address and API key, then click **Connect to Radarr**. Hecklarr loads Radarr's folders and quality profiles and reveals the rest of the settings.
4. Choose your **Specials destination** and **Quality profile**.
5. Enter your **TMDB API key or Read Access Token** under **TMDB and feed settings**.
6. Check **Feed address for Radarr**. It must be an address Radarr can reach. See the connection examples below.
7. In Radarr's import-list settings, set library cleanup to **Disabled**. Hecklarr checks this before applying the list.
8. Click **Save & apply to Radarr**. Once the list is successfully configured, the full dashboard opens.

Your account and settings persist across container restarts and upgrades. If applying settings fails, they remain saved and the app explains the error.

### Connection addresses

The Radarr address is reached **from Hecklarr**. The feed address is reached **from Radarr**. An address that works in your browser may not work inside a container.

| Deployment | Example Radarr address | Example feed address |
| --- | --- | --- |
| Shared Docker network, services named `radarr` and `hecklarr` | `http://radarr:7878` | `http://hecklarr:6162` |
| Services accessible through the host's LAN IP | `http://192.168.1.10:7878` | `http://192.168.1.10:6162` |

These are examples; use your actual addresses and ports. `localhost` inside a container refers to that container. If Radarr shares a VPN container's network namespace, its address may use the VPN service name instead.

The feed address defaults to the URL you used to open Hecklarr. A browser URL such as `http://localhost:6162` usually needs changing when Radarr is in another container. If your reverse proxy adds its own sign-in requirement, provide Radarr a direct internal feed address; the feed already requires Hecklarr's generated key.

### Destination folder and Plex

The destination is the final library folder **as Radarr sees it**, such as `/data/comedy`. It is separate from your download client's temporary folder. Create the directory and ensure Radarr can write to it before applying settings.

Keep the comedy root separate from your main movie root. For example, use sibling folders `/data/movies` and `/data/comedy`. Create a Plex **movie** library pointed at the comedy folder, using the path Plex sees through its own volume mapping.

The destination and quality profile apply to newly added movies. Hecklarr does not move existing movies to a new folder.

## Using Hecklarr

Search for a comedian under **Comedians**, identify the correct person, and click **Add**. Hecklarr refreshes the catalog and requests a Radarr list sync. **Refresh catalog** checks again immediately; scheduled refreshes run daily.

**Stand-up specials** shows the newest releases first. Under **Review metadata & exceptions**, use **Include this** to add a title excluded by incomplete metadata. You can also include or exclude a title by its TMDB movie ID. Explicit exclusions take priority over inclusions.

Removing a comedian removes its specials from the feed but leaves existing Radarr movies in place. **Exclude this** opens a confirmation dialog with Radarr deletion checked by default. Confirming removes the title from Hecklarr and Radarr, and permanently deletes any movie files Radarr manages for it. Uncheck the option to exclude the title from Hecklarr's feed only. The exclusion remains in Hecklarr so a later refresh will not add the special again. To pause all additions, disable the **Hecklarr - Comedy** import list in Radarr.

## Matching and limitations

Automatic matching uses the comedian's TMDB movie cast credits, lead billing, a runtime of at least 20 minutes, the Comedy genre, and stand-up metadata. Acting roles, archive footage, crew-only work, and short sketches are excluded. Confirmed titles are retained through later classification changes, with fresh metadata fetched on each successful refresh. Titles removed from TMDB are dropped from the feed.

TMDB metadata can be incomplete, so some specials need manual inclusion. Downloads depend on your indexers and quality profile. A title appearing in Hecklarr does not guarantee that Radarr can find it.

## TMDB data and attribution

Each installation uses its own TMDB API key or Read Access Token. TMDB data and branding are governed by [TMDB's API terms](https://www.themoviedb.org/api-terms-of-use), separately from the application code. Commercial use requires a separate agreement with TMDB.

Cached metadata expires after 180 days, conservatively within TMDB's six-month limit. Successful refreshes fetch current data for all catalog titles, including retained specials. During an outage, the last successful catalog remains available until expiry. Expired metadata is removed from the active cache and the feed returns unavailable until a refresh succeeds; existing Radarr movies are unaffected. Expiry is checked at startup, on requests, before refreshes, and hourly while running.

If TMDB returns an authorization denial, Hecklarr clears its cached metadata. If your TMDB permission is terminated or you discontinue API use, stop Hecklarr, remove `config/snapshot.json`, and purge cached metadata from any backups. Stopped installations cannot run expiry housekeeping; check or remove their cache and backup copies before the retention deadline.

The app includes TMDB's approved logo and required attribution notice in its Credits footer. See [third-party notices](THIRD_PARTY_NOTICES.md) for asset sources and conditions.

## Updating and backups

Back up `config/settings.json` privately before updating; it contains your account, API keys, and watchlist preferences. Do not publish it or commit it to Git. The catalog in `config/snapshot.json` is a renewable metadata cache; exclude it from long-term backups. Any backup containing TMDB metadata must follow the same retention limit as the live cache.

After pulling or copying the latest source, rebuild:

```sh
docker compose up -d --build
```

View service status and logs:

```sh
docker compose ps
docker compose logs --tail 100 hecklarr
```

Stop Hecklarr while retaining its configuration:

```sh
docker compose stop hecklarr
```

## Troubleshooting

- **Cannot connect to Radarr:** check the address from Hecklarr's network, the API key, and any firewall or proxy restrictions.
- **No quality profiles:** connect to Radarr first. **Reconnect Radarr** reloads the available folders and profiles.
- **Settings saved but not applied:** check the displayed error, Radarr's access to the destination, the feed address, and that import-list cleanup is disabled.
- **Special missing:** check **Review metadata & exceptions** and confirm the movie's TMDB ID if necessary.
- **Special listed but not downloaded:** inspect Radarr's movie status and search results; availability and quality restrictions are handled there.
- **Container cannot write configuration:** check that the mounted configuration directory is writable by UID/GID `1000:1000`.

## Development checks

The app uses Python's standard library and native browser APIs. Run the tests and check JavaScript syntax from this directory:

```sh
python3 -m unittest discover -s tests -v
node --check app.js
```

## Credits

<img src="tmdb-logo.svg" alt="TMDB" width="90">

This application uses TMDB and the TMDB APIs but is not endorsed, certified, or otherwise approved by TMDB.

Asset provenance and third-party conditions are documented in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
