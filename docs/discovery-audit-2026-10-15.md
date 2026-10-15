# Stand-up discovery coverage audit

Checked October 15, 2026, against live TMDB data and the artist, distributor, and broadcaster sources linked below.

**Hecklarr does not find every special.** At the audit baseline, the missing-keyword fix for Sheng Wang recovered 16 other movie entries across the example pool. Eight further full-length performances were still rejected. The follow-up below resolves those eight; gaps remain for television episodes and incomplete movie records.

## Follow-up matching fix

Replaying all 844 audited performer/movie pairs after the follow-up produces **132 matches**, up from 124. Exactly the eight confirmed full-length misses below are added; no previously accepted titles drop out and no other titles are added in this sample.

- Blank roles can qualify when a movie has explicit stand-up/comedy-special description, exact `Comedian: Subtitle` billing, a lead credit, a comedy genre, at least 20 minutes of runtime, and no Documentary genre. This resolves *It's About Time* and *# (Hashtag)*.
- The written self-performance fallback also recognizes `Screenplay` credits and `A Comedian Special` title forms. This resolves *Boyish Girl Interrupted* and *A Steven Wright Special*.
- A stand-up comedy title can qualify with a lead self credit, the performer's writing credit, all-self cast, comedy genre, sufficient runtime, and no Documentary genre. This resolves *Freshman Fifteen*.
- [Three source-verified movie/headliner pairs](../verified-specials.json) cover *Old Baby*, *My Favorite Shapes*, and *Mouthful of Shame*. They retain the performer, lead, runtime, and comedy checks while accommodating contradictory metadata. They do not apply to other titles or guest performers. Explicit user exclusions still win.
- Regression fixtures contain all eight source-backed cases with minimal metadata and synthetic descriptions. Negative cases cover documentaries, fictional roles, guest/archive credits, missing evidence, and user exclusions.

Validation: all 78 automated tests pass. The Docker image builds, and all eight reference cases pass inside the image with networking disabled and no real configuration mounted. The local service was restarted and passed its health check with its existing settings unchanged.

Correction to the original analysis: `stand[ -]?up` already recognized “standup,” “stand up,” and “stand-up.” Gulman's special was rejected by the earlier missing-role guard, not by spelling.

These changes remain local. No release, deployment, watchlist change, or Radarr sync was performed for the fix.

## Method and limits

- Audited all 24 comedians in the rotating search examples: 844 performer/movie pairs, representing 772 unique TMDB movies.
- Ran the classifier on fresh cast credits with no manual inclusions, exclusions, or previously retained movies. Compared the implementation before the Sheng Wang fix (`4972bfc`) with the fixed implementation (`d289f19`).
- Also searched TMDB movie titles by comedian name and checked television credits. The name searches found no additional confirmed standalone special missing from the cast-credit candidates. This does not prove that TMDB contains every special.
- Compared results with published artist catalogs, broadcaster listings, and selected release announcements. This is a coverage audit, not an independently exhaustive filmography: “no omission identified” means none in the references checked.
- Read-only audit: no comedians added to the watchlist, no changes to Radarr, and no releases or deployments. Indexer availability and actual downloads were not tested.

The fresh classifier returns **107 matches before the fix and 124 after it**. These are matching results, not a count of independently verified solo specials: hosted showcases and potentially inaccurate TMDB entries can be included. A configured installation can show different counts because of explicit overrides, retained entries, and shared-title deduplication.

## Results by comedian

The counts below include every automatically accepted movie entry, including any half-hours, outtakes, and hosted shows. They are not totals for a comedian's complete body of work. Sources are reference catalogs or spot checks, not necessarily exhaustive catalogs themselves.

| Comedian | Before → after | Findings and reference sources |
| --- | ---: | --- |
| Bill Burr | 10 → 10 | No omission identified in his [current official catalog](https://billburr.com/). Includes *Friends Who Kill*, a hosted showcase; not ten solo hour-long shows. Earlier Comedy Central appearances remain an episode coverage question. |
| Louis C.K. | 14 → 14 | Finds the [artist's video specials](https://louisck.com/pages/comedy-specials) and [*Ridiculous*](https://www.netflix.com/tudum/articles/louis-ck-ridiculous-release-date-news?inapp=true). Audio-only releases are outside movie support. |
| Sheng Wang | 1 → 2 | *Sweet and Juicy* recovered; [*Purple*](https://www.netflix.com/title/81778997) already matched. His [2011 Comedy Central half-hour](https://ir.paramount.com/news-releases/news-release-details/comedy-central-presents-back-featuring-todays-best-and-brightest/) is absent from these movie candidates. |
| Maria Bamford | 4 → 5 | *Weakness Is the Brand* recovered. *Old Baby* still rejected despite appearing in her [official specials catalog](https://mariabamford.com/specials). That catalog's other four titles now match; the extra automatic match is the homemade Christmas special. Her site also identifies two Comedy Central half-hours, outside this catalog. |
| Taylor Tomlinson | 4 → 4 | All four specials listed in her [official biography](https://taylortomlinsoncomedy.com/press) match. *The Comedy Lineup* debut is a [series appearance](https://media.netflix.com/en/only-on-netflix/81157965), not an additional movie candidate. |
| Nate Bargatze | 2 → 5 | Recovers *Full Time Magic*, *The Greatest Average American*, and *Hello World*: all five solo titles in the [official catalog](https://nateland.com/pages/specials) now match. The Christmas variety show is rejected. Earlier Comedy Central and *The Standups* episodes are separate. |
| Gary Gulman | 3 → 4 | *In This Economy?* recovered. *It's About Time* still rejected; Gulman discusses its release in this [BUILD interview](https://www.youtube.com/watch?v=GT4BEeftCtA). *Grandiloquent* is currently advertised with an [upcoming special taping](https://garygulman.com/); do not count the touring show as an already released film. |
| Tig Notaro | 2 → 3 | *Drawn* recovered. *Boyish Girl Interrupted* still rejected, although [HBO identifies it as stand-up](https://www.hbo.com/specials). *Happy to Be Here* and *Hello Again* match. Documentary *Tig* remains excluded. |
| Mike Birbiglia | 4 → 6 | Recovers *My Girlfriend's Boyfriend* and *The Old Man and the Pool*. No omission identified among the filmed solo performances checked against his [biography](https://www.birbigs.com/about) and [producer catalog](https://www.comedydynamics.com/producers/dave-becky/). The feature-film adaptation of *Sleepwalk with Me* is an acting film, not a stand-up recording. |
| Ali Wong | 4 → 4 | All four titles in her [official biography](https://www.aliwong.com/about) match. Her supporting appearance in Sheng Wang's special correctly does not count as her own. |
| Josh Johnson | 3 → 3 | [*# (Hashtag)*](https://www.paramountplus.com/movies/video/K3ybt7y_R_No9QSCj5ZNZuh2Fxwj0lHr/) and *Freshman Fifteen* are rejected. The latter is confirmed in its [producer's biography](https://www.filmindependent.org/sponsored-projects/happy-accidents/). *Up Here Killing Myself*, the Luigi Mangione recording, and [*Symphony*](https://press.wbd.com/ca/property/josh-johnson-symphony) match. Regular YouTube sets are not comprehensively represented in TMDB. |
| Bo Burnham | 4 → 5 | *The Inside Outtakes* recovered. Main filmed specials match; references include the [first hour's broadcaster announcement](https://ir.paramount.com/static-files/7e37b370-f891-459a-aa24-1688bfb73950), [*Make Happy*](https://www.netflix.com/gb/title/80106124), and [*Inside*](https://www.boburnham.com/new-cover-page-1). His earlier Comedy Central half-hour is episode coverage, not included in the five. |
| Ricky Gervais | 10 → 10 | No omission identified in the stand-up titles checked against his [early tour catalog](https://www.rickygervais.com/humanity.php), [*Armageddon*](https://media.netflix.com/en/only-on-netflix/81714181), and [*Mortality*](https://www.netflix.com/na/title/82051730). |
| Chris Rock | 7 → 7 | Seven stand-up movie entries match, including *Big Ass Jokes*, the HBO hours, *Tamborine*, and [*Selective Outrage*](https://chrisrock.com/). No omission identified in these checked titles. The *Tamborine* extended edit was not separately verified as a Radarr movie. |
| Wanda Sykes | 6 → 7 | *I'm an Entertainer* recovered. No omission identified across the [four early specials](https://about.netflix.com/en/news/netflix-announces-wanda-sykes-stand-up-comedy-special), *Not Normal*, *I'm an Entertainer*, and [*Legacy*](https://www.netflix.com/title/81743118). |
| Steven Wright | 2 → 2 | *A Steven Wright Special* rejected; the other two performances in his [official filmography](https://www.stevenwright.com/about-steven/) match. |
| Stewart Lee | 9 → 10 | *Snowflake* recovered; filmed solo catalog substantially covered against [official DVD listings](https://www.stewartlee.co.uk/merchandise-dvds/) and the [current site](https://www.stewartlee.co.uk/). One accepted *Man-Wulf* entry needs release verification; *Comedy Vehicle* is a television series. |
| Demetri Martin | 3 → 6 | Recovers *If I*, *Standup Comedian*, and *Live (At the Time)*. Six standalone performances match. The [official site](https://demetrimartin.com/pages/about) also includes earlier material whose movie entries have empty genres/roles; DVD editions may duplicate a Comedy Central episode. [*Demetri Deconstructed*](https://www.netflix.com/title/81630186) matches. |
| Joe Pera | 1 → 1 | [*Slow & Steady*](https://www.youtube.com/watch?v=9_97zE4GRZk) matches. The *Drifting Off* live podcast recording and Adult Swim character programs are excluded; their exclusion is not established as a stand-up matching bug. |
| Jacqueline Novak | 1 → 1 | [*Get on Your Knees*](https://qr.netflix.com/de/title/81240800) matches. Her [2016 *The Half Hour* appearance](https://www.paramountpressexpress.com/comedy-central/releases/?view=105010-press-comedy-central-announces-talent-lineup-for-season-5-of-the-half-hour) is not among her movie candidates. |
| Julio Torres | 1 → 1 | *My Favorite Shapes* rejected; [*Color Theories*](https://press.wbd.com/na/media-release/hbo-0/hbo-original-comedy-special-color-theories-julio-torres-debuts-march-27) matches. His [2017 Comedy Central half-hour](https://www.paramountplus.com/shows/comedy-central-stand-up-presents/episodes/) also has a sparse movie entry that is rejected. |
| Anthony Jeselnik | 4 → 4 | *Caligula*, *Thoughts and Prayers*, *Fire in the Maternity Ward*, and *Bones and All* match. References: [Comedy Central](https://ir.paramount.com/static-files/bd14a2a7-69de-41c0-966c-1df5365f325e), [Netflix](https://www.netflix.com/title/80227677), [Netflix](https://www.netflix.com/title/81738579?fromWatch=true&source=35). His earlier Comedy Central half-hour is not a movie candidate. |
| Neal Brennan | 5 → 5 | [*Women and Black Dudes*](https://www.paramountplus.com/movies/video/gxRR4VIKiwb3CUpbJd2TU_thSeXZdKZU/), [*3 Mics*](https://qr.netflix.com/title/80117452), [*Blocks*](https://www.netflix.com/na/title/81036234), [*Crazy Good*](https://www.netflix.com/na/title/81728557), and the half-hour movie entry match. No omission identified in these checked titles. |
| Jim Norton | 3 → 5 | *Monster Rain* and *Contextually Inadequate* recovered. *Mouthful of Shame* still rejected despite [Netflix's release announcement](https://media.netflix.com/en/only-on-netflix/80134967). [*Unconceivable*](https://www.jimnorton.com/) matches. The *One Night Stand* movie entry is also rejected for missing genres. |

## Confirmed full-length false negatives at the audit baseline

These eight titles **already reach the classifier through movie cast credits**. The discovery step is not the cause of these misses. All have TMDB movie IDs usable for explicit inclusion.

| Comedian / special | TMDB movie | Why it is rejected |
| --- | --- | --- |
| Maria Bamford — *Old Baby* | [455601](https://www.themoviedb.org/movie/455601) | Empty performer role and no stand-up keyword. Also tagged Documentary, so the new conservative fallback would still reject it. |
| Gary Gulman — *It's About Time* | [396109](https://www.themoviedb.org/movie/396109) | Empty performer role and no stand-up keyword. The role guard rejected it before the description matcher could recognize “standup.” |
| Tig Notaro — *Boyish Girl Interrupted* | [355177](https://www.themoviedb.org/movie/355177) | No stand-up keyword or recognized description phrase; performer writing job is `Screenplay` rather than `Writer`, so the new fallback does not accept it. |
| Josh Johnson — *# (Hashtag)* | [843407](https://www.themoviedb.org/movie/843407) | Empty performer role and no stand-up keyword, despite an explicit comedy-special description. |
| Josh Johnson — *Freshman Fifteen: A Stand Up Comedy Film* | [1394888](https://www.themoviedb.org/movie/1394888) | No stand-up keyword. “Stand Up” appears in the title, not the overview; overview misspells the surname as “Johson.” Exact comedian-name title prefix also absent. |
| Steven Wright — *A Steven Wright Special* | [55882](https://www.themoviedb.org/movie/55882) | No stand-up keyword or recognized overview phrase. The title is not `Comedian: Subtitle`, so it misses the new fallback despite a writing credit and solo self cast. |
| Julio Torres — *My Favorite Shapes by Julio Torres* | [612392](https://www.themoviedb.org/movie/612392) | No stand-up keyword or recognized overview phrase. The title uses “by Julio Torres”; voice cameos are fictional objects rather than self roles. [HBO explicitly confirms the special and voice cameos](https://press.wbd.com/us/media-release/hbo-0/julio-torres-debuts-first-comedy-special-hbo-my-favorite-shapes-julio-torres). |
| Jim Norton — *Mouthful of Shame* | [446048](https://www.themoviedb.org/movie/446048) | No stand-up keyword or recognized overview phrase. Documentary genre and uncredited guest cameos disqualify the new fallback. The selected lead performer himself is credited normally. |

These were left unchanged during the research audit, then resolved by the follow-up above. The original rejection reasons are preserved here as the evidence behind the changes.

## Short specials, series, and packaging

Further rejected movie records include:

- [Julio Torres: Comedy Central Stand-Up Presents — 1525174](https://www.themoviedb.org/movie/1525174): 20 minutes; genres and performer role absent. [Paramount lists the television episode](https://www.paramountplus.com/shows/comedy-central-stand-up-presents/episodes/).
- [Jim Norton – One Night Stand — 1245383](https://www.themoviedb.org/movie/1245383): 30 minutes; no genres or stand-up keyword. It is also an episode of *One Night Stand*.
- [The Place Where My Jokes Come From–Demetri Martin — 1269560](https://www.themoviedb.org/movie/1269560): 20 minutes; no genres or role. [Comedy Central confirms his 2004 half-hour](https://ir.paramount.com/node/46271/pdf). The [*These Are Jokes* DVD record — 798482](https://www.themoviedb.org/movie/798482) is also rejected for empty genres and describes a package including that episode and extras; do not assume these are two distinct new performances.
- [Gary Gulman: Live — 1403520](https://www.themoviedb.org/movie/1403520): 30 minutes; empty genres. Its synopsis mixes a 2002 performance with *Boyish Man* wording. Release identity needs corroboration before treating it as another distinct special.

There are also verified half-hour performances with **no standalone movie candidate** in this audit, including Sheng Wang (2011), Nate Bargatze (2011), Maria Bamford's early appearances, Bo Burnham (2009), Josh Johnson (2017), Anthony Jeselnik (2009), and Jacqueline Novak (2016). Sources: [Comedy Central 2011 lineup](https://ir.paramount.com/news-releases/news-release-details/comedy-central-presents-back-featuring-todays-best-and-brightest/), [Comedy Central half-hour catalog](https://ir.paramount.com/node/46271/pdf), and [2016 lineup](https://www.paramountpressexpress.com/comedy-central/releases/?view=105010-press-comedy-central-announces-talent-lineup-for-season-5-of-the-half-hour).

Hecklarr currently reads only movie cast credits; it does not collect TV episodes. An “Always include” override can rescue an existing TMDB **movie** ID, but cannot turn a TMDB TV episode into a Radarr movie. Some older half-hours have both types of record; others do not. A person TV-credit query alone also misses appearances when the episode cast links are incomplete, as with Sheng Wang in the current data.

## False positives and ambiguous entries

- *Bill Burr Presents: Friends Who Kill* automatically matches because Burr is the first cast member and the stand-up keyword exists. It is a hosted showcase, not a solo Burr special. Keeping or excluding hosted shows is a product choice.
- [Stewart Lee vs The Man-Wulf — 1479926](https://www.themoviedb.org/movie/1479926) automatically matches with a 2024 release date. The [artist's current site](https://www.stewartlee.co.uk/) advertises the continuing tour, while the DVD/streaming catalog does not establish this record as an official released film. Its release status remains unverified; a date in TMDB is not sufficient corroboration.
- Documentary *Tig*, Bamford's *Paralyzed by Hope*, and acting films remain excluded in this run. Simply accepting every self credit or every movie named after a comedian would weaken that protection.
- A manual inclusion intentionally bypasses the automatic rules, and accepted titles are retained on subsequent refreshes if metadata weakens. Actual configured lists therefore need separate review; a fresh classifier audit cannot validate those choices.

## Recommendations recorded at the audit baseline

1. Add regression cases for the eight confirmed full-length misses, then make small evidence-based matching changes. Account for blank roles, `standup`/`stand up`/`stand-up`, title-based descriptions, `Screenplay`, and guest cameos without treating every self-led documentary as stand-up.
2. Keep explicit movie-ID inclusion for ambiguous packaging and incomplete records. Clearer review reasons can explain when a missing genre or role prevents automatic acceptance.
3. State the movie-only boundary plainly. Supporting anthology episodes would require a separate television workflow or a verified standalone movie record; a broader movie keyword filter cannot solve it.
4. Keep a human-verified reference catalog for regression checks. Neither a live TMDB count nor this audit establishes that every released performance has been found. New releases and corrected metadata will change the results.

## Should the API change?

TMDB remains useful for Radarr compatibility: [Radarr documents TMDB as its movie metadata source](https://wiki.servarr.com/radarr/faq). The eight full-length false negatives above are already present in the movie credits returned by TMDB. Changing the discovery provider is not necessary to address those demonstrated failures.

| Source | Potential role | Limitation established from its documentation |
| --- | --- | --- |
| TMDB | Movie identities, performer credits, and Radarr compatibility | Sparse or inconsistent classification fields; movie credits do not enumerate TV episodes. |
| Trakt | Human-curated lists and cross-provider IDs | [Trakt imports movie information from TMDB](https://forums.trakt.tv/t/how-are-movies-imported/22130). Its lists could supplement classification, but changing to Trakt does not provide an independent underlying movie catalog. |
| TheTVDB | A candidate to evaluate for anthology episodes and television specials | [API access is licensed per project](https://www.thetvdb.com/api-information). TV episode identification does not itself produce a movie Radarr can manage. Its coverage has not been benchmarked against this audit. |
| IMDb | Independent title/credit data, including TV specials and episodes | The [official API requires an AWS Data Exchange subscription and AWS authentication](https://data.imdb.com/documentation/api-documentation/getting-access/). The [non-commercial downloads](https://data.imdb.com/non-commercial-datasets/) have a limited published schema and are bulk data, not a ready-made comedian-special discovery API. Its full API coverage has not been benchmarked here. |
| OMDb | Supplementary title/IMDb-ID lookups | [Documented search is by title or ID](https://www.omdbapi.com/); there is no documented performer-filmography discovery endpoint. |

Recommendation: keep TMDB movie IDs, correct the demonstrated matching failures, and use a verified reference catalog to measure future changes. If episode support or independently verified omissions justify another provider, add it as a discovery supplement with explicit ID mapping. No replacement API has yet been shown by this audit to collect every stand-up special.

## TMDB attribution

This application uses TMDB and the TMDB APIs but is not endorsed, certified, or otherwise approved by TMDB. Movie links and IDs identify the records inspected; no credentials or bulk TMDB response dumps are included here.
