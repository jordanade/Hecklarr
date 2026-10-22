const $ = (selector) => document.querySelector(selector);
let settings;
let search_example;
const searchExamples = [
  'Bill Burr', 'Louis C.K.', 'Sheng Wang', 'Maria Bamford',
  'Taylor Tomlinson', 'Nate Bargatze', 'Gary Gulman', 'Tig Notaro',
  'Mike Birbiglia', 'Ali Wong', 'Josh Johnson', 'Bo Burnham', 'Ricky Gervais',
  'Chris Rock', 'Wanda Sykes',
  'Steven Wright', 'Stewart Lee', 'Demetri Martin', 'Joe Pera',
  'Jacqueline Novak', 'Julio Torres', 'Anthony Jeselnik', 'Neal Brennan', 'Jim Norton'
];
let personToRemove;
let fileToDelete;
const monitorRequests = new Set();
const fileRequests = new Set();
let catalogItems = [];
let reviewedItems = [];
let checkedComedians = new Set();
let catalogRefreshPending = false;
let catalogRefreshError = false;
let downloadStatuses = {items: {}, movies: {}, messages: {}, pendingMovieIds: [], updatedAt: null, lastError: null};
let downloadStatusRequest = false;
let downloadStatusGeneration = 0;
let downloadStatusFollowup;
let downloadStatusSource;
let downloadStatusWaiting = false;
const downloadLabels = {
  downloaded: 'Downloaded', downloading: 'Downloading', queued: 'Queued', paused: 'Paused',
  importing: 'Importing', 'import-blocked': 'Import blocked', failed: 'Failed', warning: 'Warning',
  'client-unavailable': 'Download client unavailable', unreleased: 'Unreleased', missing: 'Missing',
  unmonitored: 'Unmonitored', 'not-in-radarr': 'Not in Radarr', unknown: 'Unknown',
  checking: 'Checking…', updating: 'Updating…', unavailable: 'Unavailable'
};
async function api(path, body, signal) {
  const response = await fetch('/api/' + path, {method: body === undefined ? 'GET' : 'POST',
    headers: {'Content-Type': 'application/json', 'X-Hecklarr': '1'},
    body: body === undefined ? undefined : JSON.stringify(body), signal});
  // A busy or failing server can answer without a JSON body.
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.error || `Request failed (HTTP ${response.status})`);
  return result;
}
function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function notify(text, error = false) {
  $('#notice').hidden = false;
  $('#notice').textContent = text;
  $('#notice').className = error ? 'error' : '';
}
async function busy(button, action) {
  button.disabled = true;
  try { await action(); } catch (error) { notify(error.message, true); }
  finally { button.disabled = false; }
}
function formData(form) { return Object.fromEntries(new FormData(form).entries()); }
function trashButton(label) {
  const button = element('button', undefined, 'quiet icon-button trash-button');
  button.type = 'button';
  button.title = label;
  button.setAttribute('aria-label', label);
  const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  icon.setAttribute('viewBox', '0 0 24 24');
  icon.setAttribute('aria-hidden', 'true');
  const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  path.setAttribute('d', 'M4 6h16M9 6V3h6v3M6 6l1 15h10l1-15M10 10v7M14 10v7');
  icon.append(path);
  button.append(icon);
  return button;
}
function acceptDownloadStatuses(result) {
  const same_source = downloadStatusSource === settings.radarrUrl;
  downloadStatusSource = settings.radarrUrl;
  downloadStatusWaiting = catalogItems.length > 0 && (!result.updatedAt
    || catalogItems.some(movie => !Object.hasOwn(result.items || {}, movie.tmdbId)));
  // A restarted or waking server can return an empty display cache before its
  // shared Radarr poll finishes. Keep known values for this connection until a
  // completed poll arrives; never carry them across different Radarr addresses.
  if (!result.updatedAt && same_source && downloadStatuses.updatedAt) {
    downloadStatuses = {...result, updatedAt: downloadStatuses.updatedAt,
      items: {...downloadStatuses.items, ...result.items},
      movies: {...downloadStatuses.movies, ...result.movies},
      messages: {...downloadStatuses.messages, ...result.messages},
      pendingMovieIds: [...new Set([...(downloadStatuses.pendingMovieIds || []), ...(result.pendingMovieIds || [])])]};
  } else {
    downloadStatuses = result;
  }
}
function renderDownloadBadges() {
  for (const badge of document.querySelectorAll('#specials .download-state')) {
    const movie_id = Number(badge.dataset.tmdbId);
    const changing = monitorRequests.has(movie_id) || fileRequests.has(movie_id);
    const awaiting_status = downloadStatuses.pendingMovieIds?.includes(movie_id);
    const updating = changing || (awaiting_status && !downloadStatuses.lastError);
    const cached = downloadStatuses.items[badge.dataset.tmdbId];
    const fallback = downloadStatuses.lastError ? 'unavailable' : 'checking';
    const state = updating ? 'updating' : awaiting_status ? 'unavailable'
      : Object.hasOwn(downloadLabels, cached) ? cached : fallback;
    badge.textContent = downloadLabels[state];
    badge.className = 'download-state status-' + state;
    badge.setAttribute('aria-busy', String(updating));
    const messages = state === cached ? downloadStatuses.messages?.[movie_id] || [] : [];
    const explanation = badge.parentElement.querySelector('.download-message');
    explanation.textContent = messages.join(' · ');
    explanation.hidden = messages.length === 0;
    if (cached && downloadStatuses.lastError && !changing && !awaiting_status) badge.classList.add('is-stale');
    const checked = downloadStatuses.updatedAt ? 'Last checked ' + new Date(downloadStatuses.updatedAt).toLocaleString() : 'Waiting for Radarr status';
    badge.title = updating ? 'Waiting for fresh download status from Radarr.'
      : awaiting_status ? 'Could not refresh download status after the monitoring change. ' + downloadStatuses.lastError
      : checked + (downloadStatuses.lastError ? '. ' + downloadStatuses.lastError + '. Showing the last known status when available.' : '');
  }
  for (const button of document.querySelectorAll('.delete-file')) {
    const movie_id = Number(button.dataset.tmdbId);
    const file_id = downloadStatuses.movies?.[movie_id]?.movieFileId;
    button.hidden = downloadStatuses.items[movie_id] !== 'downloaded';
    button.disabled = !file_id || Boolean(downloadStatuses.lastError) || monitorRequests.has(movie_id)
      || fileRequests.has(movie_id) || Boolean(downloadStatuses.pendingMovieIds?.includes(movie_id));
  }
  renderMonitorFlags();
}
function renderMonitorFlags() {
  for (const button of document.querySelectorAll('.monitor-toggle')) {
    const id = button.dataset.tmdbId;
    const state = downloadStatuses.movies?.[id];
    const known = state && typeof state.monitored === 'boolean';
    const monitored = known && state.monitored;
    const pending = monitorRequests.has(Number(id));
    const stale = Boolean(downloadStatuses.lastError);
    button.classList.toggle('is-monitored', Boolean(monitored));
    button.classList.toggle('is-unknown', !known);
    button.classList.toggle('is-stale', stale);
    button.setAttribute('aria-pressed', known ? String(monitored) : 'mixed');
    button.setAttribute('aria-busy', String(pending));
    button.disabled = pending || fileRequests.has(Number(id)) || !known;
    const action = monitored ? 'Unmonitor' : 'Monitor';
    const label = pending ? 'Updating monitoring for ' + button.dataset.title
      : !known ? 'Monitoring status unknown for ' + button.dataset.title
      : action + ' ' + button.dataset.title + ' in Radarr';
    button.setAttribute('aria-label', label);
    button.title = label + (stale ? ' · Radarr status is stale; clicking checks the current value before changing it.' : '');
  }
}
function monitorToggle(movie) {
  const button = element('button', undefined, 'monitor-toggle');
  button.type = 'button';
  button.dataset.tmdbId = movie.tmdbId;
  button.dataset.title = movie.title;
  const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  icon.setAttribute('viewBox', '0 0 16 20');
  icon.setAttribute('aria-hidden', 'true');
  const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  path.setAttribute('d', 'M2 1h12v17l-6-4-6 4z');
  icon.append(path);
  button.append(icon);
  button.addEventListener('click', async () => {
    const state = downloadStatuses.movies?.[movie.tmdbId];
    if (!state || typeof state.monitored !== 'boolean' || monitorRequests.has(movie.tmdbId)) return;
    const monitored = !state.monitored;
    monitorRequests.add(movie.tmdbId);
    downloadStatusGeneration++;
    renderDownloadBadges();
    try {
      const result = await api('specials/monitor', {movieId: movie.tmdbId, monitored});
      downloadStatusGeneration++;
      downloadStatuses.movies = {...downloadStatuses.movies, [movie.tmdbId]: result.movie};
      downloadStatuses.pendingMovieIds = [...new Set([...(downloadStatuses.pendingMovieIds || []), movie.tmdbId])];
      renderDownloadBadges();
      notify(result.warning || (monitored ? movie.title + ' is monitored in Radarr.' + (result.searchRequested ? ' Search requested.' : '')
        : movie.title + ' is unmonitored in Radarr. Files and active downloads are kept.'), Boolean(result.warning));
    } catch (error) {
      notify(error.message, true);
    } finally {
      monitorRequests.delete(movie.tmdbId);
      renderDownloadBadges();
      void loadDownloadStatuses();
    }
  });
  return button;
}
async function loadDownloadStatuses() {
  clearTimeout(downloadStatusFollowup);
  if (downloadStatusRequest || !settings?.hasRadarrKey || $('#dashboard').hidden) return;
  downloadStatusRequest = true;
  const generation = downloadStatusGeneration;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10000);
  try {
    const result = await api('download-status', undefined, controller.signal);
    if (generation === downloadStatusGeneration) acceptDownloadStatuses(result);
  } catch (error) {
    if (generation === downloadStatusGeneration) downloadStatuses = {...downloadStatuses, lastError: error.message};
  } finally {
    clearTimeout(timeout);
    downloadStatusRequest = false;
  }
  renderDownloadBadges();
  // Initial reads and monitor writes can precede the shared Radarr poll. Read
  // its cheap display cache promptly instead of waiting for the 15-second tick.
  if ((downloadStatusWaiting || downloadStatuses.pendingMovieIds?.length)
      && !downloadStatuses.lastError && document.visibilityState === 'visible') {
    downloadStatusFollowup = setTimeout(() => { void loadDownloadStatuses(); }, 1000);
  }
}
function normalizeComedianName(name) {
  return name.normalize('NFKD').toLowerCase().replace(/[^a-z0-9]/g, '');
}
function updateSearchExample() {
  const tracked_names = new Set(settings.comedians.map(person => normalizeComedianName(person.name)));
  const available_examples = searchExamples.filter(name => !tracked_names.has(normalizeComedianName(name)));
  if (search_example && available_examples.includes(search_example)) return;
  let previous_example;
  try { previous_example = sessionStorage.getItem('hecklarr-search-example'); } catch {}
  const different_examples = available_examples.filter(name => name !== previous_example);
  const candidates = different_examples.length ? different_examples : available_examples;
  search_example = candidates[Math.floor(Math.random() * candidates.length)];
  $('#search').placeholder = search_example ? `E.g., ${search_example}` : 'Search by comedian name';
  try {
    if (search_example) sessionStorage.setItem('hecklarr-search-example', search_example);
  } catch {}
}
function ownsSpecial(movie, person) {
  return (movie.personIds || []).includes(person.id);
}
function onlyOwner(movie, person) {
  const owners = movie.personIds || [];
  return owners.length > 0 && owners.every(id => id === person.id);
}
function additionModeOptions(name, selected_mode, label) {
  const options = element('fieldset', undefined, 'mode-options');
  options.setAttribute('aria-label', label);
  options.append(element('legend', 'Addition mode', 'sr-only'));
  for (const [value, title] of [['all', 'All'], ['future', 'Future only'], ['manual', 'Manual']]) {
    const choice = element('label');
    const radio = element('input');
    radio.type = 'radio';
    radio.name = name;
    radio.value = value;
    radio.required = true;
    radio.checked = value === selected_mode;
    choice.append(radio, document.createTextNode(title));
    options.append(choice);
  }
  return options;
}
function renderPeople() {
  updateSearchExample();
  $('#people-count').textContent = settings.comedians.length;
  $('#comedians').replaceChildren();
  $('#following-heading').hidden = settings.comedians.length === 0;
  const select = $('#override-form').elements.personId;
  select.replaceChildren();
  const special_filter = $('#special-filter');
  const selected_filter = special_filter.value;
  special_filter.replaceChildren(new Option('All comedians', ''), ...settings.comedians.map(person => new Option(person.name, person.id)));
  special_filter.value = settings.comedians.some(person => String(person.id) === selected_filter) ? selected_filter : '';
  const review_filter = $('#review-filter');
  const selected_review_filter = review_filter.value;
  review_filter.replaceChildren(new Option('All comedians', ''), ...settings.comedians.map(person => new Option(person.name, person.id)));
  review_filter.value = settings.comedians.some(person => String(person.id) === selected_review_filter) ? selected_review_filter : '';
  $('#exceptions').replaceChildren();
  for (const person of settings.comedians) {
    const special_count = catalogItems.filter(movie => ownsSpecial(movie, person)).length;
    const left_out_count = reviewedItems.filter(movie => movie.personId === person.id).length;
    const checked = checkedComedians.has(person.id);
    const count_copy = checked ? `${special_count} special${special_count === 1 ? '' : 's'} found`
      : catalogRefreshPending ? 'Checking for specials…'
      : catalogRefreshError ? 'Could not check specials' : 'Not checked yet';
    select.add(new Option(person.name, person.id));
    const row = element('div', undefined, 'person');
    const label = element('div');
    const count_link = element('a', count_copy, 'special-count-link');
    count_link.href = '#specials-section';
    count_link.setAttribute('aria-label', checked ? `Show ${special_count} special${special_count === 1 ? '' : 's'} for ${person.name}` : `Show specials for ${person.name}`);
    count_link.addEventListener('click', event => {
      event.preventDefault();
      special_filter.value = person.id;
      renderSpecials();
      $('#specials-section').scrollIntoView({behavior: 'smooth', block: 'start'});
    });
    const left_out_link = element('a', `${left_out_count} left out`, 'special-count-link');
    left_out_link.href = '#entries-left-out';
    left_out_link.setAttribute('aria-label', `Show ${left_out_count} left out for ${person.name}`);
    left_out_link.addEventListener('click', event => {
      event.preventDefault();
      $('#review-filter').value = person.id;
      renderReviewEntries();
      $('#metadata-review').open = true;
      $('#entries-left-out').scrollIntoView({behavior: 'smooth', block: 'start'});
    });
    const counts = element('div', undefined, 'person-counts');
    counts.append(count_link, left_out_link);
    label.append(element('strong', person.name), counts);
    const remove = trashButton('Remove ' + person.name + ' from Hecklarr');
    remove.addEventListener('click', () => {
      personToRemove = person;
      const tracked_count = catalogItems.filter(movie => onlyOwner(movie, person)).length;
      const shared_count = catalogItems.filter(movie => ownsSpecial(movie, person)).length - tracked_count;
      $('#remove-person-name').textContent = person.name;
      $('#delete-comedian-movies-copy').textContent =
        `Also remove ${tracked_count} tracked special${tracked_count === 1 ? '' : 's'} from Radarr and delete their movie files, if present.` +
        (shared_count ? ` ${shared_count} special${shared_count === 1 ? ' is' : 's are'} shared with another comedian and will be kept.` : '');
      $('#delete-comedian-movies').checked = false;
      $('#remove-person-error').textContent = '';
      $('#confirm-remove-person').textContent = 'Remove comedian';
      $('#remove-person-dialog').showModal();
    });
    label.className = 'person-summary';
    const mode_options = additionModeOptions('monitorMode-' + person.id, person.monitorMode || 'all', 'Addition mode for ' + person.name);
    mode_options.addEventListener('change', async event => {
      mode_options.disabled = true;
      mode_options.setAttribute('aria-busy', 'true');
      try {
        const result = await api('comedians/mode', {id: person.id, monitorMode: event.target.value});
        settings = result.settings;
        renderPeople();
        if (result.warning) notify(result.warning, true);
      } catch (error) {
        for (const radio of mode_options.querySelectorAll('input')) radio.checked = radio.value === (person.monitorMode || 'all');
        notify(error.message, true);
      } finally {
        mode_options.disabled = false;
        mode_options.setAttribute('aria-busy', 'false');
      }
    });
    row.append(label, remove, mode_options); $('#comedians').append(row);
    const exceptions = element('p', `${person.name}: included IDs ${(person.includeIds || []).join(', ') || 'none'}; excluded IDs ${(person.excludeIds || []).join(', ') || 'none'}`, 'hint');
    $('#exceptions').append(exceptions);
  }
  renderReviewEntries();
}
function renderSpecials() {
  const filter_id = $('#special-filter').value;
  const comedian = settings.comedians.find(person => String(person.id) === filter_id);
  const filtered_items = catalogItems.filter(movie => !comedian || ownsSpecial(movie, comedian));
  $('#specials').replaceChildren();
  const newestFirst = [...filtered_items].sort((a, b) =>
    (b.releaseDate || b.year || '').localeCompare(a.releaseDate || a.year || '') || a.title.localeCompare(b.title));
  for (const movie of newestFirst) {
    const row = element('tr');
    const title = element('td');
    const link = element('a', movie.title);
    link.href = 'https://www.themoviedb.org/movie/' + movie.tmdbId;
    link.target = '_blank'; link.rel = 'noreferrer';
    const badge = element('span', 'Checking…', 'download-state status-checking');
    badge.dataset.tmdbId = movie.tmdbId;
    const explanation = element('span', undefined, 'download-message');
    explanation.hidden = true;
    title.append(link, badge, explanation);
    const monitoring = element('td', undefined, 'monitor-cell');
    monitoring.append(monitorToggle(movie));
    const actions = element('td', undefined, 'file-actions');
    const trash = trashButton('Delete downloaded file for ' + movie.title);
    trash.classList.add('delete-file');
    trash.dataset.tmdbId = movie.tmdbId;
    trash.addEventListener('click', () => {
      const radarr_movie = downloadStatuses.movies?.[movie.tmdbId];
      const file_id = radarr_movie?.movieFileId;
      if (!file_id) return;
      fileToDelete = {movie, file_id};
      $('#delete-file-title').textContent = movie.title;
      const unmonitor = $('#unmonitor-deleted-file');
      unmonitor.checked = radarr_movie.monitored === true;
      unmonitor.disabled = !unmonitor.checked;
      unmonitor.closest('label').hidden = unmonitor.disabled;
      $('#delete-file-error').textContent = '';
      $('#delete-file-dialog').showModal();
    });
    actions.append(trash);
    row.append(monitoring, title, element('td', movie.year), element('td', (movie.comedians || []).join(', ')), element('td', movie.reason), actions);
    $('#specials').append(row);
  }
  $('#empty').textContent = comedian ? `No specials currently found for ${comedian.name}.` : 'Add a comedian and refresh to start your catalog.';
  $('#empty').hidden = filtered_items.length > 0;
  renderDownloadBadges();
}
function renderStatus(status) {
  checkedComedians = new Set((status.people || []).map(person => person.id));
  catalogRefreshError = Boolean(status.lastError);
  catalogItems = status.items || [];
  if (status.downloadStatuses) acceptDownloadStatuses(status.downloadStatuses);
  reviewedItems = (status.reviewed || []).filter(row => !row.included);
  $('#special-count').textContent = catalogItems.length;
  $('#connection').textContent = settings.radarrListId ? 'Connected to Radarr' : 'Ready to connect';
  $('#connection').classList.toggle('is-connected', Boolean(settings.radarrListId));
  $('#updated').textContent = 'Daily refresh at 3 AM · ' + (settings.timeZone || 'server time');
  $('#catalog-updated').textContent = status.updatedAt ? 'Updated ' + new Date(status.updatedAt).toLocaleString() : 'Waiting for first refresh';
  renderSpecials();
  renderReviewEntries();
  if (status.lastError) notify('Refresh failed: ' + status.lastError +
    (status.updatedAt ? '. The previous catalog is still available.' : '. Refresh the catalog to reload metadata.'), true);
}
function renderReviewEntries() {
  const filter_id = $('#review-filter').value;
  const filtered_items = reviewedItems.filter(movie => !filter_id || String(movie.personId) === filter_id);
  $('#review').replaceChildren();
  for (const movie of filtered_items) {
    const row = element('div', undefined, 'review-row');
    const description = element('div', undefined, 'review-copy');
    const title_link = element('a', movie.title);
    title_link.href = 'https://www.themoviedb.org/movie/' + movie.tmdbId;
    title_link.target = '_blank'; title_link.rel = 'noreferrer';
    description.append(title_link, element('span', ` (${movie.year || 'TBA'}) · TMDB ${movie.tmdbId}`),
      element('small', `${movie.comedian} · ${movie.reason}`));
    const include = element('button', 'Include', 'quiet');
    include.type = 'button';
    include.setAttribute('aria-label', 'Include ' + movie.title);
    include.addEventListener('click', () => busy(include, async () => {
      settings = await api('overrides', {personId: movie.personId, movieId: movie.tmdbId, action: 'include'});
      renderPeople();
      try {
        await refreshCatalog();
      } catch (error) {
        throw new Error('Inclusion saved for ' + movie.title + ', but the catalog could not refresh: ' + error.message);
      }
    }));
    row.append(description, include);
    $('#review').append(row);
  }
  $('#review-empty').hidden = filtered_items.length > 0;
  $('#review-empty').textContent = filter_id ? 'No entries left out for this comedian.' : 'No entries left out.';
}
async function refreshCatalog() {
  catalogRefreshPending = true;
  renderPeople();
  notify('Checking TMDB for specials…');
  try {
    const status = await api('refresh', {});
    settings = await api('settings');
    renderStatus(status);
    void loadDownloadStatuses();
    notify(`Catalog refreshed: ${status.items.length} specials.`);
  } catch (error) {
    catalogRefreshError = true;
    throw error;
  } finally {
    catalogRefreshPending = false;
    renderPeople();
  }
}
$('#delete-comedian-movies').addEventListener('change', event => {
  $('#confirm-remove-person').textContent = event.target.checked ? 'Remove & delete' : 'Remove comedian';
});
$('#special-filter').addEventListener('change', renderSpecials);
$('#review-filter').addEventListener('change', renderReviewEntries);
$('#delete-file-dialog').addEventListener('close', () => { fileToDelete = null; });
$('#cancel-delete-file').addEventListener('click', () => $('#delete-file-dialog').close());
$('#delete-file-form').addEventListener('submit', event => {
  event.preventDefault();
  if (!fileToDelete) return;
  const {movie, file_id} = fileToDelete;
  fileRequests.add(movie.tmdbId);
  downloadStatusGeneration++;
  renderDownloadBadges();
  busy(event.submitter, async () => {
    try {
      const result = await api('specials/delete-file', {movieId: movie.tmdbId, movieFileId: file_id, unmonitor: $('#unmonitor-deleted-file').checked});
      downloadStatusGeneration++;
      downloadStatuses.movies = {...downloadStatuses.movies, [movie.tmdbId]: result.movie};
      downloadStatuses.pendingMovieIds = [...new Set([...(downloadStatuses.pendingMovieIds || []), movie.tmdbId])];
      $('#delete-file-dialog').close();
      notify(result.warning || 'Downloaded file deleted for ' + movie.title + '. Its movie entry is kept in Radarr.', Boolean(result.warning));
    } catch (error) {
      $('#delete-file-error').textContent = error.message;
      throw error;
    } finally {
      fileRequests.delete(movie.tmdbId);
      renderDownloadBadges();
      void loadDownloadStatuses();
    }
  });
});
$('#remove-person-dialog').addEventListener('close', () => { personToRemove = null; });
$('#cancel-remove-person').addEventListener('click', () => $('#remove-person-dialog').close());
$('#remove-person-form').addEventListener('submit', event => {
  event.preventDefault();
  if (!personToRemove) return;
  const button = event.submitter;
  busy(button, async () => {
    const person = personToRemove;
    const delete_from_radarr = $('#delete-comedian-movies').checked;
    let result;
    try {
      result = await api('comedians/remove', {id: person.id, deleteFromRadarr: delete_from_radarr});
    } catch (error) {
      $('#remove-person-error').textContent = error.message;
      throw error;
    }
    $('#remove-person-dialog').close();
    settings = result.settings;
    renderStatus(await api('status'));
    renderPeople();
    try {
      await refreshCatalog();
    } catch (error) {
      notify(`${person.name} was removed from Hecklarr, but the catalog could not refresh: ${error.message}`, true);
      return;
    }
    if (!delete_from_radarr) notify(`${person.name} was removed from Hecklarr. Radarr movies and files were left untouched.`);
    else if (!result.removedFromRadarr) notify(`${person.name} was removed from Hecklarr. No tracked movies were found in Radarr to delete.`);
    else if (result.hadFiles) notify(`${person.name} was removed from Hecklarr and Radarr; its movie files were deleted.`);
    else notify(`${person.name} was removed from Hecklarr and Radarr. No movie files were present.`);
    if (delete_from_radarr && result.sharedCount) notify(`${$('#notice').textContent} ${result.sharedCount} shared special${result.sharedCount === 1 ? ' was' : 's were'} kept for other comedians.`);
  });
});
async function loadOptions() {
  const options = await api('radarr/options');
  $('#root-folders').replaceChildren(...options.roots.map(row => new Option(row.path, row.path)));
  const profile = $('#settings-form').elements.qualityProfileId;
  const selected = profile.value || settings.qualityProfileId || '';
  profile.replaceChildren(new Option('Choose a quality profile', ''), ...options.profiles.map(row => new Option(row.name, row.id)));
  profile.value = selected;
  profile.disabled = false;
  $('#radarr-library-options').hidden = false;
  $('#load-options').textContent = 'Reconnect Radarr';
}
async function loadDashboard() {
  downloadStatusGeneration++;
  settings = await api('settings');
  $('#setup').hidden = true; $('#login').hidden = true;
  const library_ready = Boolean(settings.radarrListId || (settings.radarrUrl && settings.hasRadarrKey));
  for (const section of document.querySelectorAll('[data-library-ready]')) section.hidden = !library_ready;
  $('.grid').classList.toggle('setup-only', !library_ready);
  $('.workspace').classList.toggle('setup-only', !library_ready);
  if (!library_ready) $('#library-settings').open = true;
  const form = $('#settings-form');
  for (const key of ['radarrUrl', 'rootFolderPath', 'feedBaseUrl', 'qualityProfileId']) form.elements[key].value = settings[key] || '';
  if (!settings.feedBaseUrl) form.elements.feedBaseUrl.value = location.origin;
  for (const [key, present] of [['radarrApiKey', settings.hasRadarrKey], ['tmdbApiKey', settings.hasTmdbKey]]) {
    form.elements[key].placeholder = present ? 'Saved — leave blank to keep' : 'Enter an API key';
    form.elements[key].value = '';
  }
  try { renderStatus(await api('status')); } catch (error) { notify(error.message, true); }
  renderPeople();
  if (settings.radarrUrl && settings.hasRadarrKey) {
    try { await loadOptions(); } catch (error) { notify(error.message, true); }
  }
  $('#dashboard').hidden = false; $('#logout').hidden = false; $('#credits').hidden = false;
  void loadDownloadStatuses();
}
$('#setup-form').addEventListener('submit', async event => {
  event.preventDefault(); const button = event.submitter; button.disabled = true;
  try {
    const account = formData(event.target);
    account.username = account.username.trim();
    await api('setup', account);
    event.target.reset(); $('#setup').hidden = true; $('#login').hidden = false;
    $('#login-form').elements.username.value = account.username;
    $('#login-error').textContent = '';
  } catch (error) { $('#login-error').textContent = error.message; }
  finally { button.disabled = false; }
});
$('#login-form').addEventListener('submit', async event => {
  event.preventDefault(); const button = event.submitter; button.disabled = true;
  try { await api('login', formData(event.target)); event.target.elements.password.value = ''; $('#login-error').textContent = ''; await loadDashboard(); }
  catch (error) { $('#login-error').textContent = error.message; }
  finally { button.disabled = false; }
});
$('#logout').addEventListener('click', async () => { await api('logout', {}); location.reload(); });
$('#refresh').addEventListener('click', event => busy(event.target, refreshCatalog));
$('#load-options').addEventListener('click', event => busy(event.target, async () => {
  const form = $('#settings-form');
  const radarr_url = form.elements.radarrUrl.value.trim();
  if (!radarr_url) throw new Error('Enter the Radarr address first');
  settings = await api('settings', {radarrUrl: radarr_url, radarrApiKey: form.elements.radarrApiKey.value});
  form.elements.radarrApiKey.value = '';
  form.elements.radarrApiKey.placeholder = settings.hasRadarrKey ? 'Saved — leave blank to keep' : 'Enter your Radarr API key';
  await loadOptions();
  notify('Connected to Radarr. Choose a destination and quality profile.');
}));
$('#settings-form').addEventListener('submit', event => {
  event.preventDefault(); busy(event.submitter, async () => {
    await api('settings', formData(event.target));
    let result;
    try {
      result = await api('sync', {});
    } catch (error) {
      await loadDashboard();
      throw new Error('Settings saved in Hecklarr, but could not be applied to Radarr: ' + error.message);
    }
    await loadDashboard();
    notify('Settings saved and applied to Radarr. New specials will go to ' + result.rootFolderPath + '.');
  });
});
$('#search-form').addEventListener('submit', event => {
  event.preventDefault(); busy(event.submitter, async () => {
    const people = await api('search?q=' + encodeURIComponent($('#search').value));
    $('#search-results').replaceChildren(element('h3', 'Search results', 'search-results-heading'));
    if (!people.length) $('#search-results').append(element('p', 'No matching people found.', 'hint'));
    for (const person of people) {
      const row = element('form', undefined, 'result'); const text = element('div', undefined, 'result-summary');
      text.append(element('strong', person.name), element('small', person.knownFor || 'No known-for titles listed'));
      const tracked = settings.comedians.find(tracked => tracked.id === person.id);
      const modes = additionModeOptions('monitorMode', tracked?.monitorMode || 'all', 'Addition mode for ' + person.name);
      const button = element('button', 'Add'); button.type = 'submit';
      button.disabled = Boolean(tracked);
      modes.disabled = Boolean(tracked);
      if (button.disabled) button.textContent = 'Added';
      row.addEventListener('submit', event => {
        event.preventDefault();
        const monitor_mode = formData(row).monitorMode;
        busy(button, async () => {
          settings = await api('comedians', {id: person.id, monitorMode: monitor_mode});
          renderPeople();
          $('#search-results').replaceChildren();
          await refreshCatalog();
          $('#special-filter').value = person.id;
          renderSpecials();
          $('#specials-section').scrollIntoView({behavior: 'smooth', block: 'start'});
        });
      });
      row.append(text, modes, button); $('#search-results').append(row);
    }
  });
});
$('#override-form').addEventListener('submit', event => {
  event.preventDefault(); busy(event.submitter, async () => {
    settings = await api('overrides', formData(event.target)); renderPeople(); await refreshCatalog();
  });
});
(async () => {
  try {
    const auth = await api('auth');
    if (auth.setupRequired) $('#setup').hidden = false;
    else if (auth.authenticated) await loadDashboard();
    else $('#login').hidden = false;
  } catch (error) { $('#login-error').textContent = error.message; }
})();
setInterval(() => {
  if (document.visibilityState === 'visible') void loadDownloadStatuses();
}, 15000);
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') void loadDownloadStatuses();
});
