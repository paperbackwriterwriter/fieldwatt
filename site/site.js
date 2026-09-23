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
    featured_company: "https://buy.stripe.com/7sYaEX3iRbmq4Vo6Gg5Ne01",  // $299 / month
    sponsor_slot: "https://buy.stripe.com/28EcN5g5D9ei87Ad4E5Ne02",  // $250 one-time
    sponsored_program: "https://buy.stripe.com/dRm5kD1aJduy2Ng8Oo5Ne05"  // $199 / month
  };

  /* === Cloudflare Turnstile site key (public; the secret goes in Vercel as
     TURNSTILE_SECRET_KEY). While this is empty no widget renders and the
     server falls back to the honeypot and the timing check. */
  window.FIELDWATT_TURNSTILE = "0x4AAAAAAFBAnC55SP40EDRw";

  var SITE = 'FieldWatt';
  var LOADED_AT = Date.now();

  /* mobile menu */
  var btn = document.getElementById('menu-btn'), menu = document.getElementById('mobile-menu');
  if (btn && menu) btn.addEventListener('click', function () {
    var open = menu.classList.toggle('hidden') === false;
    btn.setAttribute('aria-expanded', open ? 'true' : 'false');
  });

  /* Linked sections land centred in the viewport. A plain anchor jump pins the
     target to the top edge, which puts a card like #featured-job right under
     the sticky header with the rest of the page pushed off screen. */
  function centreOnHash(hash, smooth) {
    if (!hash || hash.length < 2) return;
    var el;
    try { el = document.getElementById(decodeURIComponent(hash.slice(1))); } catch (e) { return; }
    if (!el) return;
    // positioned by hand rather than scrollIntoView({block:'center'}), which
    // counts the element's scroll-margin and lands half of it off centre. The
    // margin still earns its keep as the no-JS fallback, where the browser's
    // own jump would otherwise tuck the card under the sticky header.
    var box = el.getBoundingClientRect();
    var top = box.top + window.pageYOffset - (window.innerHeight - box.height) / 2;
    window.scrollTo({ top: Math.max(0, top), behavior: smooth ? 'smooth' : 'auto' });
  }

  centreOnHash(location.hash, false);
  // fonts and images settle after parse and shift the page, so correct once more
  window.addEventListener('load', function () { centreOnHash(location.hash, false); });
  window.addEventListener('hashchange', function () { centreOnHash(location.hash, true); });
  document.addEventListener('click', function (e) {
    var a = e.target && e.target.closest && e.target.closest('a[href*="#"]');
    if (!a) return;
    var url;
    try { url = new URL(a.href, location.href); } catch (err) { return; }
    // only same-page links; a different page scrolls itself on arrival
    if (url.pathname !== location.pathname || !url.hash) return;
    if (!document.getElementById(decodeURIComponent(url.hash.slice(1)))) return;
    e.preventDefault();
    if (url.hash !== location.hash) history.pushState(null, '', url.hash);
    centreOnHash(url.hash, true);
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

  /* Turnstile. Rendered from here rather than in the page markup so the
     widget and its script only exist once a site key is configured, and so
     the form pages stay free of provider-specific HTML. */
  var widgets = new WeakMap();
  function mountTurnstile() {
    document.querySelectorAll('form[data-form]').forEach(function (form) {
      if (widgets.has(form)) return;
      var holder = document.createElement('div');
      holder.className = 'mt-5';
      var submit = form.querySelector('button[type="submit"]');
      (submit && submit.parentNode ? submit.parentNode : form).insertBefore(holder, submit || null);
      widgets.set(form, window.turnstile.render(holder, {
        sitekey: window.FIELDWATT_TURNSTILE,
        theme: 'auto'
      }));
    });
  }
  if (window.FIELDWATT_TURNSTILE && document.querySelector('form[data-form]')) {
    window.onTurnstileReady = mountTurnstile;
    var ts = document.createElement('script');
    ts.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit&onload=onTurnstileReady';
    ts.defer = true;
    document.head.appendChild(ts);
  }

  /* forms */
  document.querySelectorAll('form[data-form]').forEach(function (form) {
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var status = form.querySelector('[data-status]');
      var payload = {
        site: SITE,
        form: form.dataset.form,
        page: location.pathname,
        // how long the page was open before submitting; a script fills and
        // fires a form far faster than a person can read it
        elapsedMs: Date.now() - LOADED_AT
      };
      if (window.FIELDWATT_TURNSTILE) {
        var id = widgets.get(form);
        var token = id !== undefined && window.turnstile ? window.turnstile.getResponse(id) : '';
        if (!token) {
          if (status) status.textContent = 'Please complete the verification above and try again.';
          return;
        }
        payload.turnstileToken = token;
      }
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
          var wid = widgets.get(form);
          if (wid !== undefined && window.turnstile) window.turnstile.reset(wid);
        })
        .catch(function () { if (status) status.textContent = 'Something went wrong. Please try again in a moment.'; })
        .then(function () { if (submit) submit.disabled = false; });
    });
  });
})();
