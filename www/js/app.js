/* STT - Vue 2 entry point.
   - Hash-mode router with named routes and a guard: the first navigation asks
     GET /api/models, and a 401 there means the server wants a token, so the
     sign-in screen asks for one, keeps it in this browser and every request
     carries it
   - Minimal Vuex: the toasts, the theme in force, the token, the model
     catalogue the screens share, the transcribe screen's remembered choices
   - The wait-queue mixin (SttWait) and the language names, each written once
     and read by every screen that needs them
   - Shared formatters, so every screen prints a size, a duration and a
     timestamp the same way
   - Shared error unwrapping, so no screen shows the operator raw JSON
*/

Vue.prototype.$http = axios;

Vue.use(httpVueLoader);
Vue.use(Vuex);

/* The one place an axios failure becomes a sentence for an alert box.

   The API reports every failure as {"error": "<category>", "request_id":
   "<12 hex>"} and keeps the details in its log. The request id goes on the end
   in brackets: it is the one thing the operator can quote that finds the same
   failure in the server log.

   413 is the exception, because the category says nothing the operator can act
   on and the body carries the one number they can: the server's upload limit.
   nginx answers its own 413 without that number, and then the sentence says
   the same thing without it. */
const apiError = function (err) {
  var resp = err && err.response;
  var data = resp && resp.data;
  if (resp && resp.status === 413) {
    var limit = data && typeof data === 'object' ? data.limit_mb : null;
    return limit ? 'File is larger than the server limit of ' + limit + ' MB'
                 : 'File is larger than the server accepts';
  }
  var text = '';
  if (data && typeof data === 'object') {
    if (typeof data.error === 'string' && data.error) text = data.error;
    else if (data.error) text = JSON.stringify(data.error);
    if (text && data.request_id) text += ' (request ' + data.request_id + ')';
  } else if (typeof data === 'string' && data && data.charAt(0) !== '<') {
    // A plain-text body is a sentence; a body that opens a tag is a proxy's
    // own error page, and the status line below says the same thing shorter.
    text = data;
  }
  if (text) return text;
  if (resp) return resp.status + ' ' + resp.statusText;
  return (err && err.message) || 'The request failed';
};
Vue.prototype.$apiError = apiError;

/* Whether a failure is the server refusing the token (or its absence). */
const unauthorized = function (err) {
  return !!(err && err.response && err.response.status === 401);
};

/* Screens are loaded from .vue files at runtime - there is no build step.
   A screen whose file is missing or does not parse must not take the shell
   down with it: the header and the router keep working, the router-view says
   which screen did not load and why, and the console has the full error.

   The fallback is resolved here rather than handed to vue-router as the
   `{component, error}` factory form: that form is Vue's own and vue-router 3
   does not read it - a rejected loader aborts the navigation, so the address
   stays where it was and the fallback never renders. Catching the rejection
   and answering the placeholder is what lets the navigation finish. */
const missingScreen = function (name, err) {
  var reason = (err && err.message) || String(err || 'unknown error');
  return {
    data: function () {
      return { name: name, reason: reason };
    },
    template:
      '<div class="stt-page">' +
      '<div class="stt-card">' +
      '<div class="label">Screen unavailable</div>' +
      '<div class="sub">/views/{{ name }}.vue: {{ reason }}</div>' +
      '</div></div>',
  };
};

const loadScreen = function (name) {
  var load = httpVueLoader('/views/' + name + '.vue');
  return function () {
    return load().catch(function (err) {
      console.error(err);
      return missingScreen(name, err);
    });
  };
};

/* The furniture every screen shares, registered once rather than through a
   `components:` block per screen - one screen keeping its own loader is how
   two copies of the same control end up drifting apart.

   `stt-alerts` is the four bars - error, warning, info, success - each bound
   with `.sync` to a string on the screen. `stt-transcript` draws a result as
   blocks with its COPY / TXT / JSON actions, whatever source produced it.
   `stt-header` and `stt-toaster` are the shell's own and are rendered by the
   App root below. */
Vue.component('stt-alerts',     httpVueLoader('/views/Alerts.vue'));
Vue.component('stt-transcript', httpVueLoader('/views/Transcript.vue'));
Vue.component('stt-toaster',    httpVueLoader('/views/Toaster.vue'));
Vue.component('stt-header',     httpVueLoader('/views/Header.vue'));

/* Shared formatters. */
const UNITS = ['B', 'KB', 'MB', 'GB', 'TB'];

/* Bytes as a short figure: "186 KB", "1.2 MB". Whole numbers below a
   kilobyte and from 10 up, one decimal in between - the decimal is what tells
   1.2 MB from 1.9 MB, and past ten it is noise. Null and anything unusable
   print as "-" rather than "0 B", which would claim a size nobody measured. */
Vue.prototype.$fmtBytes = function (value) {
  if (value === null || value === undefined || value === '') return '-';
  var bytes = Number(value);
  if (!isFinite(bytes) || bytes < 0) return '-';
  var index = 0;
  while (bytes >= 1024 && index < UNITS.length - 1) {
    bytes /= 1024;
    index += 1;
  }
  var figure = (index === 0 || bytes >= 10) ? Math.round(bytes).toString() : bytes.toFixed(1);
  return figure + ' ' + UNITS[index];
};

/* Seconds with one decimal and the unit: 4.2 -> "4.2 s". Null, undefined and
   anything that is not a number print as "-" rather than "NaN s". */
Vue.prototype.$fmtSeconds = function (value) {
  if (value === null || value === undefined || value === '') return '-';
  var seconds = Number(value);
  if (!isFinite(seconds)) return '-';
  return seconds.toFixed(1) + ' s';
};

/* A position in a recording: 6.48 -> "00:06.5", 3725.2 -> "1:02:05.2".
   Rounded to tenths first and split after, so 59.96 prints as "01:00.0" rather
   than "00:60.0". Minutes and seconds always two digits, so a column of these
   lines up; hours only when there are any. */
const fmtStamp = function (value) {
  var seconds = Number(value);
  if (value === null || value === undefined || value === '' || !isFinite(seconds) || seconds < 0) return '-';
  var tenths = Math.round(seconds * 10);
  var hours = Math.floor(tenths / 36000);
  var minutes = Math.floor((tenths % 36000) / 600);
  var rest = (tenths % 600) / 10;
  var clock = (minutes < 10 ? '0' : '') + minutes + ':' + (rest < 10 ? '0' : '') + rest.toFixed(1);
  return hours ? hours + ':' + clock : clock;
};
Vue.prototype.$fmtStamp = fmtStamp;

/* English names for the language codes the backends report.

   The server sends codes only - GET /api/models lists each backend's own
   `languages` - and this table is what turns them into words for the selects
   and the models dialog. It is Whisper's own table (whisper.tokenizer
   LANGUAGES, all 100 entries, in its order), and Parakeet's 25 codes are all in
   it. A code missing here prints as the bare code rather than as nothing: a new
   backend with a language this file has not heard of still gets a usable
   option. */
const LANGUAGE_NAMES = {
  en: 'English', zh: 'Chinese', de: 'German', es: 'Spanish', ru: 'Russian',
  ko: 'Korean', fr: 'French', ja: 'Japanese', pt: 'Portuguese', tr: 'Turkish',
  pl: 'Polish', ca: 'Catalan', nl: 'Dutch', ar: 'Arabic', sv: 'Swedish',
  it: 'Italian', id: 'Indonesian', hi: 'Hindi', fi: 'Finnish', vi: 'Vietnamese',
  he: 'Hebrew', uk: 'Ukrainian', el: 'Greek', ms: 'Malay', cs: 'Czech',
  ro: 'Romanian', da: 'Danish', hu: 'Hungarian', ta: 'Tamil', no: 'Norwegian',
  th: 'Thai', ur: 'Urdu', hr: 'Croatian', bg: 'Bulgarian', lt: 'Lithuanian',
  la: 'Latin', mi: 'Maori', ml: 'Malayalam', cy: 'Welsh', sk: 'Slovak',
  te: 'Telugu', fa: 'Persian', lv: 'Latvian', bn: 'Bengali', sr: 'Serbian',
  az: 'Azerbaijani', sl: 'Slovenian', kn: 'Kannada', et: 'Estonian', mk: 'Macedonian',
  br: 'Breton', eu: 'Basque', is: 'Icelandic', hy: 'Armenian', ne: 'Nepali',
  mn: 'Mongolian', bs: 'Bosnian', kk: 'Kazakh', sq: 'Albanian', sw: 'Swahili',
  gl: 'Galician', mr: 'Marathi', pa: 'Punjabi', si: 'Sinhala', km: 'Khmer',
  sn: 'Shona', yo: 'Yoruba', so: 'Somali', af: 'Afrikaans', oc: 'Occitan',
  ka: 'Georgian', be: 'Belarusian', tg: 'Tajik', sd: 'Sindhi', gu: 'Gujarati',
  am: 'Amharic', yi: 'Yiddish', lo: 'Lao', uz: 'Uzbek', fo: 'Faroese',
  ht: 'Haitian Creole', ps: 'Pashto', tk: 'Turkmen', nn: 'Nynorsk', mt: 'Maltese',
  sa: 'Sanskrit', lb: 'Luxembourgish', my: 'Myanmar', bo: 'Tibetan', tl: 'Tagalog',
  mg: 'Malagasy', as: 'Assamese', tt: 'Tatar', haw: 'Hawaiian', ln: 'Lingala',
  ha: 'Hausa', ba: 'Bashkir', jw: 'Javanese', su: 'Sundanese', yue: 'Cantonese',
};

/* The English name of a language code, or the code itself when the table has
   none. */
Vue.prototype.$languageName = function (code) {
  return Object.prototype.hasOwnProperty.call(LANGUAGE_NAMES, code) ? LANGUAGE_NAMES[code] : code;
};

/* The wait queue, shared by every screen that has one.

   `wait` is an array of labels on the screen's own data - the strip above
   the content joins them, and the controls are disabled while it is not
   empty. A label goes on before the request and comes off in its `finally`,
   by exact text: the one label that changes while it is queued (the
   transcribe screen's ticking "transcribing 12s") is replaced in place by its
   timer and dropped under its final text. Published on window so the .vue
   files, which are loaded at runtime with no imports, can name it in
   `mixins`. */
window.SttWait = {
  methods: {
    waitPush: function (label) {
      this.wait.push(label);
    },
    waitDrop: function (label) {
      var i = this.wait.indexOf(label);
      if (i !== -1) this.wait.splice(i, 1);
    },
  },
};

/* localStorage, or null where there is none.

   A browser with site data switched off throws on the property itself rather
   than answering undefined, and this file is also run by syntax checks in a
   sandbox where the global is simply absent. Either way the app has to start:
   the preference becomes the default, not a ReferenceError thrown before the
   router exists. */
const browserStorage = function () {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage;
  } catch (err) {
    return null;
  }
};

/* Light or dark, chosen by the operator.

   A view preference belonging to this browser rather than configuration
   belonging to the server, so it lives in this browser's localStorage under
   one key. Only the two spellings are accepted on the way in as well as on
   the way out: the stored text is hand-editable, and `data-theme="sepia"` is
   a document that matches neither half of the palette and renders with no
   theme at all. The same key and the same rule as the inline guard in
   index.html, which sets the attribute before the stylesheets load. */
const THEME_KEY = 'stt.theme';
const THEMES = ['light', 'dark'];

/* What the operator's own system asks for, and the answer for an operator
   whose browser will not say. This is the default and only the default - a
   stored choice outranks it, because somebody who has picked dark on a light
   desktop picked it on purpose. */
const systemTheme = function () {
  try {
    if (typeof window === 'undefined' || !window || !window.matchMedia) return 'light';
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  } catch (err) {
    return 'light';
  }
};

const readTheme = function () {
  var box = browserStorage();
  var stored = null;
  if (box) {
    try {
      stored = box.getItem(THEME_KEY);
    } catch (err) {
      stored = null;
    }
  }
  return THEMES.indexOf(stored) === -1 ? systemTheme() : stored;
};

/* Both attributes, on the document element.

   `data-theme` is what css/main.css keys its dark palette on. `data-bs-theme`
   is what Bootstrap 5.3 keys its own on, and every dialog, input and close
   glyph on these screens is Bootstrap's - setting only ours would give a dark
   page full of white modals.

   Guarded rather than assumed: this file is also run by syntax checks against
   no document at all, and an app that throws here is an app that never
   reaches the router. */
const applyTheme = function (theme) {
  var root = (typeof document === 'undefined' || !document) ? null : document.documentElement;
  if (!root || !root.setAttribute) return;
  root.setAttribute('data-theme', theme);
  root.setAttribute('data-bs-theme', theme);
};

/* Applied here, as the file loads, and not from a mounted hook.

   Everything below this line is the app being assembled; the attribute is on
   the document before any of it runs. Set later, every load would paint the
   light palette, hold it, and then flip, and that flash is on every page an
   operator opens all day. */
const startingTheme = readTheme();
applyTheme(startingTheme);

/* The other preference of this browser: what the transcribe screen opens
   with. Same home as the theme - localStorage, one key per group,
   'stt.transcribe' - and the same rule on the way in: only the fields named
   here, only in the type named here, anything else the default. The stored
   text is hand-editable.

   An empty string means "not chosen": for the mode, the screen picks Speakers
   when the server can diarize and Text when it cannot; for the language, it is
   the server's own default, so a browser that never chose follows the
   deployment rather than a value baked into this file; for the source, FILE;
   for the device, the browser's default input; for the stream address,
   nothing.

   A group is written whole, so a screen saving one field starts from the
   stored group and changes only its own - see $savePrefs. */
const PREFS_PREFIX = 'stt.';
const PREFS = {
  transcribe: { mode: '', language: '', source: '', device: '', url: '' },
};

const validatePrefs = function (name, value) {
  var defaults = PREFS[name];
  var given = (value && typeof value === 'object') ? value : {};
  var clean = {};
  Object.keys(defaults).forEach(function (key) {
    var fallback = defaults[key];
    clean[key] = typeof given[key] === typeof fallback ? given[key] : fallback;
  });
  return clean;
};

const readPrefs = function (name) {
  var box = browserStorage();
  var stored = null;
  if (box) {
    try {
      stored = JSON.parse(box.getItem(PREFS_PREFIX + name));
    } catch (err) {
      // Nothing stored, or text that is not JSON any more: the defaults.
      stored = null;
    }
  }
  return validatePrefs(name, stored);
};

/* Global toast notifications.
   Pushed from anywhere via `this.$store.dispatch('push_toast', {...})`.
   Auto-dismissed after `ttl` ms (default 8000). Ids come off a counter: two
   toasts pushed in the same millisecond must still be two keys. */
var toastSerial = 0;

const push_toast = function (context, payload) {
  toastSerial += 1;
  var toast = Object.assign(
    { level: 'info', message: '', ttl: 8000 },
    payload,
    { id: toastSerial }
  );
  context.state.toasts.push(toast);
  setTimeout(function () {
    var i = context.state.toasts.findIndex(function (t) { return t.id === toast.id; });
    if (i !== -1) context.state.toasts.splice(i, 1);
  }, toast.ttl);
};

const dismiss_toast = function (context, id) {
  var i = context.state.toasts.findIndex(function (t) { return t.id === id; });
  if (i !== -1) context.state.toasts.splice(i, 1);
};

/* The API token, when the server wants one.

   Kept in this browser under its own key, like the theme: the sign-in screen
   writes it after the server has accepted it, every request carries it from
   the store, and a 401 anywhere clears it and sends the operator back to sign
   in. Only a string is accepted on the way in; anything else reads as "not
   signed in". */
const TOKEN_KEY = 'stt.token';

const readToken = function () {
  var box = browserStorage();
  if (!box) return '';
  try {
    var stored = box.getItem(TOKEN_KEY);
    return typeof stored === 'string' ? stored : '';
  } catch (err) {
    return '';
  }
};

const state = {
  toasts: [],
  // The theme in force, always resolved to one of the two rather than left as
  // "whatever was stored": the header toggle reads this to know which way to
  // flip and which glyph to show. Already applied to the document above - this
  // is the copy the interface reads, and it is what holds the setting for the
  // rest of the session in a browser that refused to keep it.
  theme: startingTheme,
  // Whether GET /api/models has answered (with anything at all) since the
  // token last changed, and the token this browser holds. There is no route
  // that says whether the server wants a token, so the guard asks for the
  // catalogue and reads a 401 as "yes". Replaced whole, never edited in
  // place.
  auth: { checked: false, token: readToken() },
  // GET /api/models, as sent: `backend` is the server's default transcription
  // backend, `models` one row per backend it carries. `loaded` is false until
  // the first answer, so a screen can tell "not asked yet" from "no rows".
  // Replaced whole by file_models, never edited in place.
  catalog: { loaded: false, backend: '', models: [] },
  // The transcribe screen's remembered mode and language, already validated.
  // Replaced whole by $savePrefs.
  transcribe: readPrefs('transcribe'),
};

/* A GET /api/models answer into the catalog. Its own action because two
   callers have an answer in hand: fetch_models below, and the sign-in screen,
   whose probe with the typed token is the same request. */
const file_models = function (context, data) {
  var body = data || {};
  context.state.catalog = {
    loaded: true,
    backend: typeof body['default'] === 'string' ? body['default'] : '',
    models: Array.isArray(body.models) ? body.models : [],
  };
  return context.state.catalog;
};

/* GET /api/models into the catalog. `options` is handed to axios as it is -
   the guard passes `probe: true` there (see the interceptors). The promise
   answers the catalog; a failure leaves the catalog as it was and rejects, so
   the caller can say so.

   Any answer but a 401 settles `auth.checked` - a server that is down or still
   loading has said nothing about tokens, and the screens show that failure
   themselves. A 401 never settles it: by the time this handler runs the
   interceptor or the guard has already forgotten the token and reopened the
   check, and marking it done here would undo that. */
const fetch_models = function (context, options) {
  return axios.get('/api/models', options || {}).then(function (resp) {
    context.state.auth = { checked: true, token: context.state.auth.token };
    return file_models(context, resp.data);
  }, function (err) {
    if (!unauthorized(err)) context.state.auth = { checked: true, token: context.state.auth.token };
    return Promise.reject(err);
  });
};

const actions = {
  push_toast,
  dismiss_toast,
  file_models,
  fetch_models,
};

const store = new Vuex.Store({ state, actions });

/* Write the token, or forget it with ''. Answers whether the browser kept it;
   the store holds it for the session either way.

   A token is only ever written after the server accepted it, so writing one
   settles the check. Forgetting one - sign-out, a 401 - reopens it: the guard
   asks the server again on the next navigation, so the brand link on the
   sign-in screen, or a bookmark, cannot open a screen the server will refuse
   the moment it asks for anything. */
Vue.prototype.$saveToken = function (token) {
  var value = typeof token === 'string' ? token : '';
  var box = browserStorage();
  var kept = false;
  if (box) {
    try {
      if (value) box.setItem(TOKEN_KEY, value);
      else box.removeItem(TOKEN_KEY);
      kept = true;
    } catch (err) {
      kept = false;
    }
  }
  store.state.auth = { checked: !!value, token: value };
  return kept;
};

/* Write the theme: to storage, to the store so the header re-renders, and to
   the document so the page changes under it.

   Answers false when the browser refused to keep it. The setting is in force
   either way, which is the point of putting it in the store as well as in
   storage: a browser with site data switched off gets the theme it asked for
   until the tab is reloaded, rather than a control that visibly does nothing -
   and the header says so, because otherwise the operator picks dark, reloads
   tomorrow, finds light, and nothing anywhere says the server is not at
   fault. */
Vue.prototype.$saveTheme = function (next) {
  var theme = THEMES.indexOf(next) === -1 ? 'light' : next;
  var box = browserStorage();
  var kept = false;
  if (box) {
    try {
      box.setItem(THEME_KEY, theme);
      kept = true;
    } catch (err) {
      // A full quota, or storage in read-only mode. Reported to the caller
      // rather than swallowed: the alternative is a switch that silently
      // forgets itself on the next load.
      kept = false;
    }
  }
  store.state.theme = theme;
  applyTheme(theme);
  return kept;
};

/* Write one preference group: to storage and to the store, as a new object.

   `value` holds only the fields being changed; the rest of the group is kept
   as it is in the store, so two screens (or two sources on one screen) that
   each remember their own field cannot reset each other's. The result goes
   through the same validation as a stored one, so a caller cannot put a field
   in the store that a reload would not bring back. Answers false when the
   browser refused to keep it; the choice holds until the tab is reloaded
   either way. */
Vue.prototype.$savePrefs = function (name, value) {
  if (!PREFS[name]) return false;
  var clean = validatePrefs(name, Object.assign({}, store.state[name], value));
  var box = browserStorage();
  var kept = false;
  if (box) {
    try {
      box.setItem(PREFS_PREFIX + name, JSON.stringify(clean));
      kept = true;
    } catch (err) {
      kept = false;
    }
  }
  store.state[name] = clean;
  return kept;
};

/* Router. Every screen is a named route and the address bar always names one:
   the default is a redirect rather than a component on '/', so after it the
   address says which screen is open, and a typo in the address lands on the
   transcribe screen rather than on a blank page. */
const router = new VueRouter({
  mode: 'hash',
  routes: [
    { path: '/login',      name: 'login',      component: loadScreen('Login') },
    { path: '/',           redirect: '/transcribe' },
    { path: '/transcribe', name: 'transcribe', component: loadScreen('Transcribe') },
    { path: '/models',     name: 'models',     component: loadScreen('Models') },
    { path: '*',           redirect: '/transcribe' },
  ],
});

/* Every programmatic navigation goes through here.

   vue-router 3 rejects the promise it returns when a navigation is redirected,
   cancelled or already where it was asked to go. All three are ordinary, and
   none of them is an error worth an "Uncaught (in promise)" in the console. */
const goto = function (target) {
  var leaving = router.push(target);
  if (leaving && leaving.catch) leaving.catch(function () {});
};
Vue.prototype.$goto = goto;

/* What the browser tab says. One name and the screen you are on, so a window
   with three tabs open on this UI can be told apart without clicking through
   them. Set from the route rather than by each screen: a screen that forgot
   would leave the previous one's name in the tab, which is worse than a name
   that never changes. */
const TAB_TITLES = {
  login: 'Sign in',
  transcribe: 'Transcribe',
  models: 'Models',
};

router.afterEach(function (to) {
  var name = TAB_TITLES[to.name];
  document.title = name ? 'STT - ' + name : 'STT';
});

/* A route this app may send someone back to after signing in. `next=` arrives
   from the address bar, so it is typed by anyone: a value starting "//" is an
   absolute URL to a browser, and anything that is not a path of ours is
   dropped rather than corrected. */
const internalPath = function (value) {
  if (typeof value !== 'string') return '';
  if (value.charAt(0) !== '/' || value.charAt(1) === '/') return '';
  if (value === '/' || value.indexOf('/login') === 0) return '';
  return value;
};
Vue.prototype.$internalPath = internalPath;

/* Where an operator without a token is sent, remembering where they were
   going: a bookmark to /#/models must end on /#/models after signing in. */
const loginRoute = function (to) {
  var wanted = internalPath(to && to.fullPath);
  return wanted ? { path: '/login', query: { next: wanted } } : '/login';
};

/* The guard. The server is asked once, on the first navigation, for its
   catalogue - the cheapest route behind the token check, and one every screen
   needs anyway. A 401 means it wants a token this browser does not have (or
   has a stale one), so the token is forgotten and the operator is sent to sign
   in. Any other failure - the server still loading its models, say - lets the
   screen through: it asks again and shows the failure in its own error bar. */
router.beforeEach(function (to, from, next) {
  if (to.name === 'login') return next();
  if (store.state.auth.checked) return next();
  store.dispatch('fetch_models', { probe: true }).then(function () {
    next();
  }, function (err) {
    if (!unauthorized(err)) return next();
    Vue.prototype.$saveToken('');
    next(loginRoute(to));
  });
});

/* Every API request carries the token the browser holds, unless the request
   set its own (the sign-in screen's probe). Only /api/ - nginx's own files
   have no use for it. */
const apiRequest = function (config) {
  var url = (config && config.url) || '';
  return url.indexOf('/api/') === 0;
};

axios.interceptors.request.use(function (config) {
  var token = store.state.auth.token;
  config.headers = config.headers || {};
  if (token && apiRequest(config) && !config.headers.Authorization) {
    config.headers.Authorization = 'Bearer ' + token;
  }
  return config;
});

/* The token was refused: forget it and send the operator to sign in, with the
   screen they were on kept for afterwards. One place for every way a refusal
   arrives - an HTTP 401 below, or an `Unauthorized` error on the live
   websocket, which has no status code to intercept. */
const signInAgain = function () {
  Vue.prototype.$saveToken('');
  if (router.currentRoute.name !== 'login') goto(loginRoute(router.currentRoute));
};
Vue.prototype.$signInAgain = signInAgain;

/* A 401 from any request means the token is gone or wrong. A request marked
   `probe` is excluded: its caller reads the 401 itself - the guard as "sign
   in first", the sign-in screen as "wrong token". The mark is an axios config
   field rather than a header, so it never leaves the browser. */
axios.interceptors.response.use(
  function (resp) { return resp; },
  function (err) {
    var probe = err && err.config && err.config.probe;
    if (unauthorized(err) && !probe) signInAgain();
    return Promise.reject(err);
  }
);

/* App root. Mounted at once: the guard asks the server about the token on
   the first navigation, so nothing has to be awaited here. */
const App = {
  template:
    '<div>' +
    '<stt-header></stt-header>' +
    '<stt-toaster></stt-toaster>' +
    '<router-view :key="$route.path" />' +
    '</div>',
};

new Vue({ router, store, render: function (h) { return h(App); } }).$mount('#app');
