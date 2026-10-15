<img src="icon.png" alt="Hecklarr microphone icon" width="80">

# Hecklarr

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

Open [http://localhost:6162](http://localhost:6162) on the Docker host. The service listens on localhost by default. To access it from another computer, set `HECKLARR_BIND_ADDRESS` to the host's LAN IP in a `.env` file beside `compose.yaml`, then run `docker compose up -d` again. Use an HTTPS reverse proxy for access outside your private network.

## Configure

1. Create an account and sign in.
2. Enter your Radarr address and API key, then select **Connect to Radarr**.
3. Choose a destination folder Radarr can write to and a quality profile.
4. Add your TMDB key under **TMDB and feed settings**. Set **Feed address for Radarr** to an address Radarr can reach.
5. In Radarr, disable cleanup for the Hecklarr import list, then select **Save & apply to Radarr**.

Use an address reachable from the container making the request. For example, containers on a shared Docker network can use `http://radarr:7878` and `http://hecklarr:6162`. If Radarr and Hecklarr do not share a network, use an address reachable through your host or proxy. `localhost` inside a container refers to that container.

Set the destination as Radarr sees it, such as `/data/comedy`. Keep it separate from your main movie folder if you want a distinct Plex or Jellyfin library. Hecklarr applies the destination to newly added movies; it does not move existing movies.

## Use

Add comedians from **Comedians**. Hecklarr refreshes the catalog and asks Radarr to sync the list; you can also refresh manually. Use **Entries left out** to review excluded TMDB credits or include a title by its TMDB movie ID.

Removing a comedian removes their titles from the feed. **Exclude this** opens a confirmation with Radarr deletion selected; confirming permanently deletes files managed by Radarr. Uncheck it to exclude a title from the feed only. Disable the import list in Radarr to pause additions.

TMDB metadata can be incomplete, and an item in Hecklarr does not guarantee a release is available from your indexers.

Badges beneath each title show its Radarr download status. Status refreshes in the background every minute; if Radarr is unavailable, Hecklarr keeps the last known status and marks it stale.

## TMDB data and credits

Each installation uses its own TMDB API key or Read Access Token. TMDB data and branding are governed by [TMDB's API terms](https://www.themoviedb.org/api-terms-of-use); commercial use requires a separate agreement. The app includes TMDB's required attribution and logo; see [third-party notices](THIRD_PARTY_NOTICES.md).

Hecklarr expires cached TMDB metadata after 180 days. If you stop using TMDB or lose access, stop Hecklarr and delete `config/snapshot.json` and any backup copies of that cache.

## Updates and backups

Back up `config/settings.json` privately; it contains your account, API keys, and watchlist. The metadata cache in `config/snapshot.json` is renewable and should not be kept in long-term backups.

Pull and start the latest image:

```sh
docker compose pull
docker compose up -d
```

For help, check service status and logs with `docker compose ps` and `docker compose logs --tail 100 hecklarr`.
