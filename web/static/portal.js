// A single navigation surface becomes an accessible modal drawer on smaller screens.
const navigation = document.getElementById('workspace-navigation');
const navigationMedia = window.matchMedia('(max-width: 900px)');
const navigationBackdrop = document.querySelector('.navigation-backdrop');
const navigationTriggers = [...document.querySelectorAll('[data-open-navigation]')];
let navigationReturnFocus = null;
let navigationOpen = false;
function setNavigation(open, restoreFocus = true) {
  if (!navigation) return;
  navigationOpen = Boolean(open && navigationMedia.matches);
  document.documentElement.classList.toggle('nav-open', navigationOpen);
  document.body.classList.toggle('navigation-locked', navigationOpen);
  navigationBackdrop.hidden = !navigationOpen;
  navigationTriggers.forEach(button => button.setAttribute('aria-expanded', String(navigationOpen)));
  navigation.inert = navigationMedia.matches && !navigationOpen;
  if (navigationMedia.matches) {
    navigation.setAttribute('aria-hidden', String(!navigationOpen));
    if (navigationOpen) {
      navigation.setAttribute('role', 'dialog');
      navigation.setAttribute('aria-modal', 'true');
    } else {
      navigation.removeAttribute('role');
      navigation.removeAttribute('aria-modal');
    }
  } else {
    navigation.removeAttribute('aria-hidden');
    navigation.removeAttribute('role');
    navigation.removeAttribute('aria-modal');
  }
  document.querySelectorAll('.workspace, .mobile-bar, .mobile-tabs').forEach(element => { element.inert = navigationOpen; });
  if (navigationOpen) navigation.querySelector('[data-close-navigation]').focus();
  else if (restoreFocus && navigationReturnFocus && navigationMedia.matches) navigationReturnFocus.focus();
}
if (navigation) {
  document.documentElement.classList.add('nav-enhanced');
  setNavigation(false, false);
  navigationTriggers.forEach(button => button.addEventListener('click', () => {
    navigationReturnFocus = button;
    setNavigation(true);
  }));
  document.querySelectorAll('[data-close-navigation]').forEach(button => button.addEventListener('click', () => setNavigation(false)));
  navigationMedia.addEventListener('change', () => {
    const focusedInside = navigation.contains(document.activeElement);
    setNavigation(false, false);
    if (navigationMedia.matches && focusedInside) navigationTriggers[0].focus();
  });
  document.addEventListener('keydown', event => {
    if (!navigationOpen) return;
    if (event.key === 'Escape') { event.preventDefault(); setNavigation(false); return; }
    if (event.key === 'Tab') {
      const controls = [...navigation.querySelectorAll('a[href],button:not([disabled]),summary,select,input:not([type=hidden])')].filter(element => element.getClientRects().length);
      const first = controls[0], last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  });
}
let submitting = false;
let submissionTimer;
let disabledForSubmission = [];
function recoverSubmission(message) {
  clearTimeout(submissionTimer);
  submitting = false;
  disabledForSubmission.forEach(button => { button.disabled = false; });
  disabledForSubmission = [];
  document.querySelectorAll('form[aria-busy]').forEach(form => form.removeAttribute('aria-busy'));
  const status = document.getElementById('working-status');
  if (status) { status.textContent = message; status.hidden = !message; }
}
document.addEventListener('securitypolicyviolation', event => {
  if (submitting && event.effectiveDirective === 'form-action') {
    recoverSubmission('The browser blocked the connection redirect. Refresh this page before trying again.');
  }
});
let dirty = false;
document.querySelectorAll('input,textarea,select').forEach(input => {
  input.addEventListener('input', () => { dirty = true; input.setCustomValidity(''); });
});
document.querySelectorAll('[data-dialog]').forEach(button => {
  button.addEventListener('click', () => {
    if (navigationOpen) setNavigation(false);
    document.getElementById(button.dataset.dialog).showModal();
  });
});
document.querySelectorAll('[data-close-dialog]').forEach(button => {
  button.addEventListener('click', () => button.closest('dialog').close());
});
document.querySelectorAll('[data-refresh]').forEach(button => {
  button.addEventListener('click', () => location.reload());
});
document.querySelectorAll('form').forEach(form => {
  form.addEventListener('submit', event => {
    if (submitting) { event.preventDefault(); return; }
    if (form.dataset.confirm && !window.confirm(form.dataset.confirm)) { event.preventDefault(); return; }
    const textarea = form.querySelector('textarea[required]');
    if (textarea && !textarea.value.trim()) {
      event.preventDefault(); textarea.setCustomValidity('Enter some text before saving.'); textarea.reportValidity(); return;
    }
    submitting = true;
    disabledForSubmission = [...document.querySelectorAll('button:not([disabled])')];
    disabledForSubmission.forEach(button => { button.disabled = true; });
    submissionTimer = setTimeout(() => recoverSubmission('This request is taking longer than expected. Refresh to check its outcome before trying again.'), 30000);
    form.setAttribute('aria-busy', 'true');
    const status = document.getElementById('working-status');
    if (status) { status.textContent = form.dataset.loading || 'Updating your workspace…'; status.hidden = false; }
  });
});
window.addEventListener('pageshow', event => { if (event.persisted) location.reload(); });
let signature = null;
async function poll() {
  if (submitting || document.hidden) return;
  try {
    const response = await fetch('/api/status', {headers: {'Accept': 'application/json'}, cache: 'no-store'});
    if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) return;
    const state = await response.json();
    if (signature && signature !== state.signature) {
      if (dirty || navigationOpen || document.querySelector('dialog[open], .queue-item[open], .source-details[open]')) {
        document.getElementById('update-notice').hidden = false;
      } else { location.reload(); return; }
    }
    // A fast job may finish before this page's first poll.
    if (!signature && document.body.dataset.busy === 'true' && !state.busy && !dirty && !navigationOpen && !document.querySelector('dialog[open], .queue-item[open], .source-details[open]')) { location.reload(); return; }
    signature = state.signature;
  } catch { /* Retain all edits during a temporary network interruption. */ }
}
poll();
setInterval(poll, 3500);

// Filter the local tool directory without hiding connected account management.
const integrationSearch = document.getElementById('integration-search');
if (integrationSearch) integrationSearch.addEventListener('input', () => {
  const query = integrationSearch.value.trim().toLowerCase();
  const cards = [...document.querySelectorAll('[data-integration]')];
  cards.forEach(card => { card.hidden = !card.dataset.integration.toLowerCase().includes(query); });
  document.getElementById('integration-no-results').hidden = cards.some(card => !card.hidden);
});

const queueSearch = document.getElementById('queue-search');
if (queueSearch) {
  const controls = ['queue-search','queue-tool','queue-status','queue-account'].map(id => document.getElementById(id));
  const rows = [...document.querySelectorAll('.queue-item')];
  function filterQueue() {
    const [search,tool,status,account] = controls.map(control => control.value.trim());
    rows.forEach(row => {
      row.hidden = !(!tool || row.dataset.tool === tool) || !(!status || row.dataset.status === status) || !(!account || row.dataset.account === account) || !row.dataset.search.toLowerCase().includes(search.toLowerCase());
    });
    const count = rows.filter(row => !row.hidden).length;
    document.getElementById('queue-filter-count').textContent = `${count} of ${rows.length} decisions`;
    document.getElementById('queue-no-match').hidden = count !== 0 || rows.length === 0;
  }
  controls.forEach(control => control.addEventListener('input', filterQueue));
  document.getElementById('queue-clear').addEventListener('click', () => { controls.forEach(control => { control.value = ''; }); filterQueue(); });
  filterQueue();
}


if (location.hash) {
  const target = document.querySelector(location.hash);
  if (target && target.tagName === 'DETAILS') target.open = true;
}

const profileMenu = document.getElementById('profile-menu');
document.querySelectorAll('[data-toggle-profile]').forEach(button => {
  button.addEventListener('click', () => {
    if (!profileMenu) return;
    profileMenu.open = !profileMenu.open;
    if (profileMenu.open) profileMenu.scrollIntoView({ block: 'nearest' });
  });
});
document.addEventListener('click', event => {
  if (profileMenu && profileMenu.open && !profileMenu.contains(event.target) && !event.target.closest('[data-toggle-profile]')) {
    profileMenu.open = false;
  }
});
