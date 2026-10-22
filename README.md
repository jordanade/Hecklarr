# <img src="icon.png" alt="" width="56" align="absmiddle">&nbsp;&nbsp;Hecklarr

Track stand-up comedians and choose which specials to monitor in Radarr. Hecklarr uses TMDB to find titles; Radarr owns monitoring and handles searching and downloading.

<img width="1222" height="808" alt="Screenshot 2026-10-16 at 5 30 17 AM" src="https://github.com/user-attachments/assets/e923905d-5569-44e7-9bff-a93739ee5513" />

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

Use an address reachable from the container making the request. For example, containers on a shared Docker network can use `http://radarr:7878` and `http://hecklarr:6162`. If Radarr and Hecklarr do not share a network, use an address reachable through your host or proxy. `localhost` inside a container refers to that container.

Set the destination as Radarr sees it, such as `/data/comedy`. Keep it separate from your main movie folder if you want a distinct Plex or Jellyfin library. Hecklarr applies the destination to newly added movies; it does not move existing movies.

## Use

Search prioritizes exact names and matching name prefixes, then popularity within equally relevant matches.

Find comedians under **Comedians**, choose an addition mode directly in the search result, and click **Add**. New results default to **All**, which can immediately add and download the existing catalog. Every mode keeps all discovered titles visible in **Stand-up specials**:

- **Manual:** discover the catalog without adding movies to Radarr. Turn on a special's bookmark flag to add it, monitor it, and start a search.
- **Future specials only:** automatically add specials whose release date is after the day you enable this mode, using the application's timezone. The cutoff stays fixed across refreshes and restarts. Older specials and titles without valid release dates remain available to monitor individually.
- **All specials:** automatically add all matching specials, including the existing catalog.

Existing comedians keep **All specials** after upgrading. Change a comedian's mode with the inline **All**, **Future only**, or **Manual** radios; changes save immediately. Mode changes affect automatic additions; they leave movies and monitoring values already in Radarr unchanged.

The bookmark flag is filled when Radarr monitors the movie and outlined when it does not. Turning it off unmonitors the movie in Radarr, keeping its files and active downloads. Changes made in Radarr appear in Hecklarr within about a minute while the page is open. Monitoring values are cached only for display; Hecklarr does not store a second set of per-special monitoring preferences. During outages, flags keep their last known values and are marked stale; unknown values are not shown as unmonitored.

Hecklarr refreshes the catalog daily and asks Radarr to sync eligible automatic additions; you can also refresh manually. Existing unmonitored Radarr movies stay unmonitored during list syncs. Deleting an automatically eligible movie can allow it to be added again; select Radarr's import-list exclusion option when deleting to prevent this.

Downloaded specials have a Trash icon for deleting the media file while keeping the movie entry in Radarr. For monitored specials, the confirmation defaults to unmonitoring to prevent future automatic downloads; clear that option to keep monitoring. Already unmonitored specials do not show this option. The file shown when opening the confirmation must still match Radarr’s current file before deletion.

Click **Y left out** beside a comedian’s specials count to open their filtered **Entries left out** list. Use **Review metadata & exceptions** to confirm or exclude TMDB matches. These are discovery corrections, separate from monitoring. Confirming a special follows its comedian's addition mode; in Manual mode, use the bookmark afterward to start monitoring. A failed refresh keeps the last successful catalog available.

Removing a comedian removes their titles from the catalog and automatic feed. A special shared with another tracked comedian stays in the catalog and remains eligible through that comedian's mode. The comedian’s Trash icon offers to also delete the comedian's movies from Radarr; that option is off by default, and confirming it permanently deletes files managed by Radarr. Disable the import list in Radarr to pause automatic additions.

Discovery covers specials listed as TMDB movies. Performances catalogued only as TV episodes cannot be added to Radarr. Matching uses performer and writing credits, title billing, descriptions, and stage-name aliases. Ambiguous entries remain available for review; your exclusions take precedence.

TMDB metadata can be incomplete, and an item in Hecklarr does not guarantee a release is available from your indexers.

Badges show **Updating…** after a monitor change until fresh Radarr status arrives. Otherwise, they show the Radarr download status, independently of monitoring: a downloaded special can be unmonitored. Warnings and other queue problems include Radarr’s explanation beneath the status. Background checks keep the previous status visible; **Checking…** appears only when no previous status is available. Status refreshes every minute while Hecklarr is open in a browser, and pauses five minutes after the last visit. Browser sessions share one poll of Radarr's movie list and download queue. If Radarr is unavailable, Hecklarr keeps the last known status and marks it stale.

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

## License

Hecklarr is licensed under the [GNU General Public License v3.0](LICENSE) (GPL-3.0-only). Third-party materials retain their own terms; see [third-party notices](THIRD_PARTY_NOTICES.md).
