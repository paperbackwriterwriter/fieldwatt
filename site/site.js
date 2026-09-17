/* FieldWatt — progressive enhancement (no framework).
   - mobile menu
   - job feed: search box + state/family selects
   - employer directory search
   - forms -> POST /api/lead
   - Stripe payment links (fill in window.FIELDWATT_STRIPE below)
*/
(function () {
  /* === Config: paste Stripe Payment Links here (Stripe Dashboard -> Payment Links).
     While a value is empty the button opens an email to you instead. */
  window.FIELDWATT_STRIPE = {
    featured_job: "https://buy.stripe.com/3cIeVd7z78aegE62q05Ne00",  // $149 / 30 days
    featured_company: "",    // $299 / month
    sponsor_slot: "",        // $250 one-time
    sponsored_program: ""    // $199 / month
  };

  var SITE = 'FieldWatt';

  /* mobile menu */
  var btn = document.getElementById('menu-btn'), menu = document.getElementById('mobile-menu');
  if (btn && menu) btn.addEventListener('click', function () {
    var open = menu.classList.toggle('hidden') === false;
    btn.setAttribute('aria-expanded', open ? 'true' : 'false');
  });

  /* stripe links */
  document.querySelectorAll('a[data-stripe]').forEach(function (a) {
    var u = window.FIELDWATT_STRIPE[a.dataset.stripe];
    if (u) { a.href = u; a.target = '_blank'; a.rel = 'noopener'; }
  });

  /* job feed filters */
  var stateSel = document.getElementById('state-select'), famSel = document.getElementById('family-select');
  function go() {
    var s = stateSel ? stateSel.value : '', f = famSel ? famSel.value : '';
    var url = '/jobs';
    if (s === 'midwest') url = '/jobs/midwest' + (f ? '?family=' + f : '');
    else if (s && f) url = '/jobs/' + s + '/' + f;
    else if (s) url = '/jobs/' + s;
    else if (f) url = '/jobs/' + f;
    location.href = url;
  }
  if (stateSel) stateSel.addEventListener('change', go);
  if (famSel) famSel.addEventListener('change', go);

  var search = document.getElementById('job-search'), list = document.getElementById('job-list');
  function applyFilter() {
    if (!list) return;
    var q = (search ? search.value : '').trim().toLowerCase();
    var params = new URLSearchParams(location.search), fam = (params.get('family') || '').toLowerCase();
    var shown = 0;
    list.querySelectorAll('[data-job]').forEach(function (art) {
      var ok = true;
      if (q) ok = art.textContent.toLowerCase().indexOf(q) !== -1;
      if (ok && fam) ok = (art.dataset.fam || '').toLowerCase().split(' ').indexOf(fam) !== -1;
      art.style.display = ok ? '' : 'none';
      if (ok) shown++;
    });
    var empty = document.getElementById('job-empty');
    if (!empty) {
      empty = document.createElement('p');
      empty.id = 'job-empty';
      empty.className = 'py-10 text-sm text-muted-foreground';
      empty.textContent = 'No listings match that search on this page. Try fewer words or another state.';
      list.parentNode.insertBefore(empty, list.nextSibling);
    }
    empty.style.display = shown ? 'none' : '';
  }
  if (search) search.addEventListener('input', applyFilter);
  if (list) {
    applyFilter();
    // pre-select family from ?family= on the midwest hub
    var fam = new URLSearchParams(location.search).get('family');
    if (fam && famSel) famSel.value = fam;
  }

  /* employer directory search */
  var es = document.getElementById('employer-search'), el = document.getElementById('employer-list');
  if (es && el) es.addEventListener('input', function () {
    var q = es.value.trim().toLowerCase();
    el.querySelectorAll('a').forEach(function (a) { a.style.display = !q || a.textContent.toLowerCase().indexOf(q) !== -1 ? '' : 'none'; });
  });

  /* prefill alerts from ?role=&state= */
  var p = new URLSearchParams(location.search);
  var roleSel = document.getElementById('alert-role'), stSel = document.getElementById('alert-state');
  if (roleSel && p.get('role')) roleSel.value = p.get('role');
  if (stSel && p.get('state')) stSel.value = p.get('state');

  /* forms */
  document.querySelectorAll('form[data-form]').forEach(function (form) {
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var status = form.querySelector('[data-status]');
      var payload = { site: SITE, form: form.dataset.form, page: location.pathname };
      form.querySelectorAll('input, select, textarea').forEach(function (el) {
        if (!el.name) return;
        if (el.type === 'checkbox') { payload[el.name] = el.checked ? (el.value || 'yes') : ''; return; }
        if (el.type === 'radio' && !el.checked) return;
        payload[el.name] = el.value;
      });
      if (payload.email !== undefined && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(payload.email || '')) {
        if (status) status.textContent = 'Please enter a valid email address.';
        return;
      }
      var submit = form.querySelector('button[type="submit"]');
      if (submit) submit.disabled = true;
      if (status) status.textContent = 'Sending…';
      fetch('/api/lead', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
        .then(function (r) { if (!r.ok) throw new Error('bad'); return r.json(); })
        .then(function () {
          if (status) status.textContent = form.dataset.form === 'job-alert' || form.dataset.form === 'tuesday-email'
            ? "You're on the list. Watch for the Tuesday email."
            : 'Thanks — we received it and will follow up by email.';
          form.reset();
        })
        .catch(function () { if (status) status.textContent = 'Something went wrong. Please try again in a moment.'; })
        .then(function () { if (submit) submit.disabled = false; });
    });
  });
})();
