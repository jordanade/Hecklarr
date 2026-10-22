# <img src="icon.png" alt="" width="56" align="absmiddle">&nbsp;&nbsp;Hecklarr

Track stand-up comedians and choose which specials to monitor in Radarr. Hecklarr uses TMDB to find titles; Radarr owns monitoring and handles searching and downloading.

<img width="1385" height="885" alt="Screenshot 2026-10-22 at 5 42 23 AM" src="https://github.com/user-attachments/assets/751fc44f-901a-4a61-8bbb-ca1a4c304f90" />

## Install

Requirements: Docker Compose, Radarr with working indexers and a download client, and a TMDB API key or Read Access Token.

Download the [Compose file](compose.yaml); it pulls `ghcr.io/jordanade/hecklarr:latest`. On a Linux host:

```sh
mkdir -p config
sudo chown 1000:1000 config
sudo chmod 700 config
docker compose up -d
```

Open `http://<server-IP>:6162`. Don't expose port 6162 to the internet; use an HTTPS reverse proxy, and set `TRUSTED_PROXIES` in `compose.yaml` to the proxy's address so login rate limits apply per visitor.

## Configure

1. Create your account using the setup code from `docker compose logs hecklarr`. Registration closes afterwards.
2. Enter your Radarr address and API key, then select **Connect to Radarr**.
3. Choose a destination folder (as Radarr sees it, e.g. `/data/comedy`) and a quality profile.
4. Add your TMDB key and set **Feed address for Radarr** to an address Radarr can reach.
5. In Radarr, disable cleanup for the Hecklarr import list, then select **Save & apply to Radarr**.

Addresses must be reachable from the container making the request; `localhost` inside a container means that container. On a shared Docker network, `http://radarr:7878` and `http://hecklarr:6162` work.

## Use

Search for a comedian under **Comedians**, click **Add**, then choose a mode in the confirmation dialog:

- **All specials:** add the whole catalog to Radarr.
- **Future specials only:** add only specials released after today.
- **Manual:** add nothing automatically; use a special's bookmark to monitor it.

The dialog displays Radarr's **Search on Add** setting; automatic additions honor that setting without changing it. The bookmark mirrors Radarr's monitored flag. Use **Review metadata & exceptions** to fix TMDB matches. Hecklarr only finds specials TMDB lists as movies, not TV episodes. See [docs/usage.md](docs/usage.md) for details.

## Updating

Back up `config/settings.json`, then pull the new image and restart:

```sh
docker compose pull
docker compose up -d
```

`docker compose up -d` on its own won't update; the `pull` is what fetches the new version.

## Backups and recovery

Back up `config/settings.json` privately. `config/snapshot.json` is a renewable TMDB cache; leave it out of backups. Password reset, feed-key rotation and API access are covered in [docs/usage.md](docs/usage.md#recovery-and-automation).

## TMDB data, credits and license

Each installation uses its own TMDB key, under [TMDB's API terms](https://www.themoviedb.org/api-terms-of-use). Hecklarr is licensed under [GPL-3.0-only](LICENSE); third-party materials keep their own terms, see [third-party notices](THIRD_PARTY_NOTICES.md).
