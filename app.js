const $ = (selector) => document.querySelector(selector);
let settings;
let search_example;
const searchExamples = [
  'Bill Burr', 'Louis C.K.', 'George Carlin', 'Sheng Wang', 'Maria Bamford',
  'Taylor Tomlinson', 'Nate Bargatze', 'Gary Gulman', 'Tig Notaro',
  'Mike Birbiglia', 'Ali Wong', 'Josh Johnson', 'Bo Burnham', 'Ricky Gervais'
];
let specialToExclude;
let personToRemove;
let catalogItems = [];
let reviewedItems = [];
let checkedComedians = new Set();
let catalogRefreshPending = false;
let catalogRefreshError = false;
let downloadStatuses = {items: {}, updatedAt: null, lastError: null};
let downloadStatusRequest = false;
let downloadStatusGeneration = 0;
const downloadLabels = {
  downloaded: 'Downloaded', downloading: 'Downloading', queued: 'Queued', paused: 'Paused',
  importing: 'Importing', 'import-blocked': 'Import blocked', failed: 'Failed', warning: 'Warning',
  'client-unavailable': 'Download client unavailable', unreleased: 'Unreleased', missing: 'Missing',
  unmonitored: 'Unmonitored', 'not-in-radarr': 'Not in Radarr', unknown: 'Unknown',
  checking: 'Checking…', unavailable: 'Unavailable'
};
async function api(path, body, signal) {
  const response = await fetch('/api/' + path, {method: body === undefined ? 'GET' : 'POST',
    headers: {'Content-Type': 'application/json', 'X-Hecklarr': '1'},
    body: body === undefined ? undefined : JSON.stringify(body), signal});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Request failed');
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
function renderDownloadBadges() {
  for (const badge of document.querySelectorAll('#specials .download-state')) {
    const cached = downloadStatuses.items[badge.dataset.tmdbId];
    const fallback = downloadStatuses.lastError ? 'unavailable' : 'checking';
    const state = Object.hasOwn(downloadLabels, cached) ? cached : fallback;
    badge.textContent = downloadLabels[state];
    badge.className = 'download-state status-' + state;
    if (cached && downloadStatuses.lastError) badge.classList.add('is-stale');
    const checked = downloadStatuses.updatedAt ? 'Last checked ' + new Date(downloadStatuses.updatedAt).toLocaleString() : 'Waiting for Radarr status';
    badge.title = checked + (downloadStatuses.lastError ? '. ' + downloadStatuses.lastError + '. Showing the last known status when available.' : '');
  }
}
async function loadDownloadStatuses() {
  if (downloadStatusRequest || !settings?.hasRadarrKey || $('#dashboard').hidden) return;
  downloadStatusRequest = true;
  const generation = downloadStatusGeneration;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10000);
  try {
    const result = await api('download-status', undefined, controller.signal);
    if (generation === downloadStatusGeneration) downloadStatuses = result;
  } catch (error) {
    if (generation === downloadStatusGeneration) downloadStatuses = {...downloadStatuses, lastError: error.message};
  } finally {
    clearTimeout(timeout);
    downloadStatusRequest = false;
  }
  renderDownloadBadges();
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
function renderPeople() {
  updateSearchExample();
  $('#people-count').textContent = settings.comedians.length;
  $('#comedians').replaceChildren();
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
    const special_count = catalogItems.filter(movie => movie.personId === person.id).length;
    const checked = checkedComedians.has(person.id);
    const count_copy = checked ? `${special_count} special${special_count === 1 ? '' : 's'} tracked`
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
    label.append(element('strong', person.name), count_link);
    const remove = element('button', 'Remove', 'quiet');
    remove.addEventListener('click', () => {
      personToRemove = person;
      const tracked_count = catalogItems.filter(movie => movie.personId === person.id).length;
      $('#remove-person-name').textContent = person.name;
      $('#delete-comedian-movies-copy').textContent =
        `Also remove ${tracked_count} tracked special${tracked_count === 1 ? '' : 's'} from Radarr and delete their movie files, if present.`;
      $('#delete-comedian-movies').checked = true;
      $('#remove-person-error').textContent = '';
      $('#confirm-remove-person').textContent = 'Remove & delete';
      $('#remove-person-dialog').showModal();
    });
    row.append(label, remove); $('#comedians').append(row);
    const exceptions = element('p', `${person.name}: included IDs ${(person.includeIds || []).join(', ') || 'none'}; excluded IDs ${(person.excludeIds || []).join(', ') || 'none'}`, 'hint');
    $('#exceptions').append(exceptions);
  }
  renderReviewEntries();
}
function renderSpecials() {
  const filter_id = $('#special-filter').value;
  const comedian = settings.comedians.find(person => String(person.id) === filter_id);
  const filtered_items = catalogItems.filter(movie => !comedian || movie.comedian === comedian.name);
  $('#specials').replaceChildren();
  const newestFirst = [...filtered_items].sort((a, b) =>
    (b.releaseDate || b.year || '').localeCompare(a.releaseDate || a.year || '') || a.title.localeCompare(b.title));
  for (const movie of newestFirst) {
    const row = element('tr');
    const title = element('td');
    const link = element('a', movie.title);
    link.href = 'https://www.themoviedb.org/movie/' + movie.tmdbId;
    link.target = '_blank'; link.rel = 'noreferrer';
    const exclude = element('button', 'Exclude this', 'quiet table-exclude');
    exclude.type = 'button';
    exclude.setAttribute('aria-label', 'Exclude ' + movie.title + ' from Hecklarr');
    exclude.addEventListener('click', () => {
      specialToExclude = movie;
      $('#exclude-special-title').textContent = movie.title;
      $('#exclude-error').textContent = '';
      $('#delete-from-radarr').checked = true;
      $('#confirm-exclude').textContent = 'Exclude & delete';
      $('#exclude-dialog').showModal();
    });
    const badge = element('span', 'Checking…', 'download-state status-checking');
    badge.dataset.tmdbId = movie.tmdbId;
    title.append(link, badge);
    const actions = element('td', undefined, 'table-actions');
    actions.append(exclude);
    row.append(title, element('td', movie.year), element('td', movie.comedian), element('td', movie.reason), actions);
    $('#specials').append(row);
  }
  $('#empty').textContent = comedian ? `No specials currently tracked for ${comedian.name}.` : 'Add a comedian and refresh to start your catalog.';
  $('#empty').hidden = filtered_items.length > 0;
  renderDownloadBadges();
}
function renderStatus(status) {
  checkedComedians = new Set((status.people || []).map(person => person.id));
  catalogRefreshError = Boolean(status.lastError);
  if (status.downloadStatuses) downloadStatuses = status.downloadStatuses;
  catalogItems = status.items || [];
  reviewedItems = (status.reviewed || []).filter(row => !row.included);
  $('#special-count').textContent = catalogItems.length;
  $('#connection').textContent = settings.radarrListId ? 'Connected to Radarr' : 'Ready to connect';
  $('#updated').textContent = 'Daily refresh at 3 AM · America/Detroit';
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
    const include = element('button', 'Include this', 'quiet');
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
    notify(`Catalog refreshed: ${status.items.length} specials.`);
  } catch (error) {
    catalogRefreshError = true;
    throw error;
  } finally {
    catalogRefreshPending = false;
    renderPeople();
  }
}
$('#delete-from-radarr').addEventListener('change', event => {
  $('#confirm-exclude').textContent = event.target.checked ? 'Exclude & delete' : 'Exclude from feed';
});
$('#delete-comedian-movies').addEventListener('change', event => {
  $('#confirm-remove-person').textContent = event.target.checked ? 'Remove & delete' : 'Remove comedian';
});
$('#special-filter').addEventListener('change', renderSpecials);
$('#review-filter').addEventListener('change', renderReviewEntries);
$('#exclude-dialog').addEventListener('close', () => { specialToExclude = null; });
$('#cancel-exclude').addEventListener('click', () => $('#exclude-dialog').close());
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
  });
});
$('#exclude-form').addEventListener('submit', event => {
  event.preventDefault();
  if (!specialToExclude) return;
  const button = event.submitter;
  busy(button, async () => {
    const title = specialToExclude.title;
    const delete_from_radarr = $('#delete-from-radarr').checked;
    let result;
    try {
      result = await api('specials/exclude', {movieId: specialToExclude.tmdbId, deleteFromRadarr: delete_from_radarr});
    } catch (error) {
      $('#exclude-error').textContent = error.message;
      throw error;
    }
    $('#exclude-dialog').close();
    settings = await api('settings'); renderStatus(await api('status')); renderPeople();
    if (!delete_from_radarr) notify(title + ' was excluded from Hecklarr and left in Radarr.');
    else if (!result.removedFromRadarr) notify(title + ' was excluded from Hecklarr. No matching movie was in Radarr to delete.');
    else if (result.hadFiles) notify(title + ' was excluded, removed from Radarr, and its movie files were deleted.');
    else notify(title + ' was excluded and removed from Radarr. It had no movie files to delete.');
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
    $('#search-results').replaceChildren();
    if (!people.length) $('#search-results').append(element('p', 'No matching people found.', 'hint'));
    for (const person of people) {
      const row = element('div', undefined, 'result'); const text = element('div');
      text.append(element('strong', person.name), element('small', person.knownFor || 'No known-for titles listed'));
      const button = element('button', 'Add'); button.type = 'button';
      button.addEventListener('click', () => busy(button, async () => {
        settings = await api('comedians', {id: person.id}); renderPeople(); $('#search-results').replaceChildren(); await refreshCatalog();
      }));
      row.append(text, button); $('#search-results').append(row);
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
    else { $('#login').hidden = false; $('#login-form').elements.username.value = auth.username; }
  } catch (error) { $('#login-error').textContent = error.message; }
})();
setInterval(() => {
  if (document.visibilityState === 'visible') void loadDownloadStatuses();
}, 15000);
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') void loadDownloadStatuses();
});
