# <img src="icon.png" alt="" width="56" align="absmiddle">&nbsp;&nbsp;Hecklarr

Track stand-up comedians and automatically add their specials to Radarr. Hecklarr uses TMDB to find titles and maintains a Radarr import list; Radarr handles searching and downloading.

## Install

Requirements: Docker Compose, Radarr, working indexers and a download client, and a TMDB API key or Read Access Token.

Hecklarr is a prebuilt container on [GitHub Container Registry](https://github.com/jordanade/Hecklarr/pkgs/container/hecklarr). Download the [Compose file](compose.yaml) from this repository. It uses `ghcr.io/jordanade/hecklarr:latest` and pulls the image automatically.

On a Linux host, create the configuration directory, then start Hecklarr:

```sh
mkdir -p config
sudo chown 1000:1000 config
sudo chmod 700 config
docker compose up -d
```

Open `http://<server-IP>:6162` from another computer on your network, or [http://localhost:6162](http://localhost:6162) on the Docker host. For localhost-only access, change the port mapping in `compose.yaml` to `127.0.0.1:6162:6162`. Use an HTTPS reverse proxy for access outside your private network, and do not expose port 6162 to the internet directly.

Behind a reverse proxy, set `TRUSTED_PROXIES` in `compose.yaml` to the proxy's address or range (comma-separated, CIDR allowed). Hecklarr then limits login attempts per visitor using `X-Forwarded-For`; without it, every visitor shares the proxy's limit.

## Configure

1. Create the sole account and sign in. Creating the account requires the setup code Hecklarr prints at startup; find it with `docker compose logs hecklarr`. Registration closes after the account is created.
2. Enter your Radarr address and API key, then select **Connect to Radarr**.
3. Choose a destination folder Radarr can write to and a quality profile.
4. Add your TMDB key. Set **Feed address for Radarr** to an address Radarr can reach.
5. In Radarr, disable cleanup for the Hecklarr import list, then select **Save & apply to Radarr**.

Use an address reachable from the container making the request. For example, containers on a shared Docker network can use `http://radarr:7878` and `http://hecklarr:6162`. If Radarr and Hecklarr do not share a network, use an address reachable through your host or proxy. 

Set the destination as Radarr sees it, such as `/data/comedy`. Keep it separate from your main movie folder if you want a distinct Plex or Jellyfin library. Hecklarr applies the destination to newly added movies; it does not move existing movies.

## Use

Add comedians from **Comedians**. Hecklarr refreshes the catalog and asks Radarr to sync the list; you can also refresh manually. Use **Entries left out** to review excluded TMDB credits or include a title by its TMDB movie ID.

Removing a comedian removes their titles from the feed. A special shared with another tracked comedian stays in the feed and in Radarr. **Exclude this** and **Remove** each offer to also delete the movie from Radarr; that option is off by default, and confirming it permanently deletes files managed by Radarr. Disable the import list in Radarr to pause additions.

Discovery covers specials listed as TMDB movies. Performances catalogued only as TV episodes cannot be added to Radarr. Matching uses performer and writing credits, title billing, descriptions, and stage-name aliases. Ambiguous entries remain available for review; your exclusions take precedence.

TMDB metadata can be incomplete, and an item in Hecklarr does not guarantee a release is available from your indexers.

Badges beneath each title show its Radarr download status. Status refreshes every minute while Hecklarr is open in a browser, and pauses five minutes after the last visit. Each refresh reads Radarr's download queue; the full movie list is re-read only when a tracked download finishes, after Hecklarr changes Radarr, or every 30 minutes; if Radarr is unavailable, Hecklarr keeps the last known status and marks it stale.

## TMDB data and credits

Each installation uses its own TMDB API key or Read Access Token. TMDB data and branding are governed by [TMDB's API terms](https://www.themoviedb.org/api-terms-of-use); commercial use requires a separate agreement. The app includes TMDB's required attribution and logo; see [third-party notices](THIRD_PARTY_NOTICES.md).

Hecklarr expires cached TMDB metadata after 180 days. If you stop using TMDB or lose access, stop Hecklarr and delete `config/snapshot.json` and any backup copies of that cache.

## Updates and backups

Back up `config/settings.json` privately; it contains your account, API keys, and watchlist. The metadata cache in `config/snapshot.json` is renewable and should not be kept in long-term backups.

## Recovery and automation

Stop Hecklarr before editing `config/settings.json`, then start it again.

- **Forgotten password:** set `authUser` and `authHash` to `""` and delete `config/sessions.json`. On the next start, Hecklarr prints a new setup code so you can create the account again. Your watchlist and connections are kept.
- **Rotate the feed key:** delete the `feedKey` entry. After restarting, select **Save & apply to Radarr** so Radarr gets the new feed address.
- **API access:** `apiKey` in `settings.json` authenticates scripts and dashboards through an `X-Api-Key` header. Requests that change anything also need an `X-Hecklarr: 1` header. Delete the entry and restart to rotate it.

Pull and start the latest image:

```sh
docker compose pull
docker compose up -d
```

For help, check service status and logs with `docker compose ps` and `docker compose logs --tail 100 hecklarr`.
