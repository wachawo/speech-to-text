<template>
  <div class="stt-page" :class="{ 'stt-dragging': dragging }">

    <!-- Where the sound comes from. Links rather than buttons, carrying the
         source in the address: a reload, a bookmark or a link sent to someone
         opens the same source. While a source is working the others are
         plain text: switching would destroy the upload or the session in
         progress. The title is on the item, because a disabled link takes no
         pointer and would never show one. -->
    <ul class="nav nav-tabs stt-subtabs">
      <li class="nav-item" v-for="entry in sources" :key="entry.value" :title="tabTitle(entry)">
        <router-link v-if="!tabLocked(entry)" class="nav-link" :class="{ active: source === entry.value }"
                     :to="{ path: $route.path, query: { source: entry.value } }">{{ entry.label }}</router-link>
        <span v-else class="nav-link disabled" aria-disabled="true">{{ entry.label }}</span>
      </li>
    </ul>

    <!-- The source's own form, and under it whatever it needs to say about
         itself. Mode and language are this screen's and are the same for
         every source, so they are written once here and placed by the source
         in its row; the source says when they must be off (`busy`). -->
    <component :is="sourceComponent" ref="source" :mode="requestMode" :language="requestLanguage"
               :compact="!!result" :held="catalogPending" @busy="sourceBusy = $event">
      <template #options="{ busy }">
        <!-- Who said what, or just the words. Speakers is offered only when
             the server has the diarizer loaded; otherwise the select holds
             Text alone and says why. -->
        <div style="margin-right: 0.25rem">
          <div class="input-group input-group-sm" :title="modeTitle">
            <select class="form-select form-select-sm" style="width: 110px" aria-label="Mode"
                    v-model="form.mode" :disabled="busy || catalogPending || modes.length < 2" @change="rememberMode">
              <option v-for="mode in modes" :key="mode.value" :value="mode.value" :title="mode.title">
                {{ mode.label }}
              </option>
            </select>
          </div>
        </div>

        <!-- The language, from the default backend's own list. A backend that
             detects the language itself takes no argument, so the select is
             off and the request carries none. -->
        <div style="margin-right: 0.25rem">
          <div class="input-group input-group-sm" :title="languageTitle">
            <select class="form-select form-select-sm" style="width: 180px" aria-label="Language"
                    v-model="languageChoice" :disabled="busy || catalogPending || !languageUsed">
              <option value="" :title="acceptsLanguage ? 'Sends no language; the server uses its own default' : null">
                {{ defaultLanguageLabel }}
              </option>
              <template v-if="acceptsLanguage">
                <option value="auto" title="The backend detects the language from the audio">Auto detect</option>
                <option v-for="code in languageCodes" :key="code" :value="code">
                  {{ code }} {{ $languageName(code) }}
                </option>
              </template>
            </select>
          </div>
        </div>
      </template>
    </component>

    <!-- This screen's own messages: the catalogue, when it could not be read,
         and a file dropped on a source that takes none. -->
    <stt-alerts :wait="wait" :error.sync="error" :warning.sync="warning"></stt-alerts>

    <!-- The open source's last result: the component draws it and owns
         COPY / TXT / JSON. -->
    <stt-transcript v-if="result" :result="result"></stt-transcript>

  </div>
</template>

<script>
/* The transcribe screen: sound in, a transcript out.

   The screen is the frame the sources share: the FILE / DEVICE switch, the
   mode and the language, and the transcript under them. Each source is its
   own component with its own form, its own request and its own messages, and
   keeps its result in the store (keep_transcript):

   - FILE (views/FileSource.vue): a file, chosen or dropped, sent whole.
   - DEVICE (views/DeviceSource.vue): an input captured live and streamed.
   - STREAM (views/StreamSource.vue): an address the server reads itself.

   Each source has its own last result, and the screen shows the open one's:
   switching to DEVICE and back to FILE finds FILE's transcript where it was,
   and so does a visit to MODELS, since the store outlives the screen. A live
   session still ends when the screen is left.

   The screen also owns the window's drag and drop, for every source: a file
   dropped on a page that does not catch it is opened by the browser in the
   page's place, which on a live source would end the session and lose the
   transcript. FILE takes the file; the others refuse it and say where it
   goes.
*/

var SOURCES = [
  { value: 'file', label: 'FILE', title: 'Transcribe an audio file', component: 'stt-file-source' },
  { value: 'device', label: 'DEVICE', title: 'Transcribe live from a microphone, a headset, or the sound of a tab', component: 'stt-device-source' },
  { value: 'stream', label: 'STREAM', title: 'Transcribe live from an address the server reads: radio, HLS, RTMP, RTSP or SRT', component: 'stt-stream-source' },
];

/* What a locked sub-tab says: which work is in the way. */
var BUSY_TITLES = {
  file: 'Wait for the file to finish transcribing first',
  device: 'Stop the live session first',
  stream: 'Stop the live session first',
};

/* Whether a drag carries files rather than text or a link from the page. */
var carriesFiles = function (event) {
  var types = event && event.dataTransfer && event.dataTransfer.types;
  return !!types && Array.prototype.indexOf.call(types, 'Files') !== -1;
};

/* The modes. Speakers and Turns need the diarizer loaded; Turns is FILE's
   alone - /api/diarize takes a whole file, and a live session has no
   diarize-only form. */
var MODES = [
  { value: 'speakers', label: 'Speakers', title: 'Who said what: the recording split by speaker, then transcribed', diarizer: true },
  { value: 'text', label: 'Text', title: 'The words alone, with no speakers' },
  { value: 'turns', label: 'Turns', title: 'Who spoke when: speaker turns on a timeline, with no text', diarizer: true, fileOnly: true },
];

var sourceEntry = function (value) {
  return SOURCES.filter(function (entry) { return entry.value === value; })[0] || null;
};

module.exports = {
  mixins: [SttWait],

  components: {
    'stt-file-source': httpVueLoader('/views/FileSource.vue'),
    'stt-device-source': httpVueLoader('/views/DeviceSource.vue'),
    'stt-stream-source': httpVueLoader('/views/StreamSource.vue'),
  },

  data: function () {
    var prefs = this.$store.state.transcribe;
    return {
      wait: [],
      error: '',
      warning: '',
      sources: SOURCES,
      // Whether the source on the screen is working - an upload in flight, a
      // live session from `opening` until idle again. Reported by the source.
      sourceBusy: false,
      // A file is being dragged over the window, and FILE would take it.
      dragging: false,
      source: sourceEntry(prefs.source) ? prefs.source : 'file',
      form: { mode: prefs.mode, language: prefs.language },
    };
  },

  created: function () {
    this.applySource();
    this.settleForm();
    // Kept off `data`: nothing renders from it.
    this.dragDepth = 0;
    // The guard asked already; it only failed to get an answer if the server
    // was down, and then this screen asks again and says why in its bar.
    if (!this.catalog.loaded) this.fetchCatalog();
  },

  /* On the window rather than on the drop zone: a file let go a few pixels
     off any target would otherwise be opened by the browser in place of this
     page. The listeners live exactly as long as the screen. */
  mounted: function () {
    window.addEventListener('dragenter', this.handleDragEnter);
    window.addEventListener('dragover', this.handleDragOver);
    window.addEventListener('dragleave', this.handleDragLeave);
    window.addEventListener('drop', this.handleDrop);
  },

  beforeDestroy: function () {
    window.removeEventListener('dragenter', this.handleDragEnter);
    window.removeEventListener('dragover', this.handleDragOver);
    window.removeEventListener('dragleave', this.handleDragLeave);
    window.removeEventListener('drop', this.handleDrop);
  },

  computed: {
    /* The open source's last result, from the store: {mode, name, language,
       data}, plus {live, listening, finishing, seconds, skipped, messages,
       stem} from a live session. `data` is the server's JSON as sent. */
    result: function () {
      return this.$store.state.transcripts[this.source] || null;
    },

    /* The catalogue is being read. Until it answers, the selects cannot show
       what the server offers - a remembered Speakers would read as Text - so
       they, and every source's start button, wait for it. */
    catalogPending: function () {
      return this.wait.indexOf('catalogue') !== -1;
    },

    /* FILE would take a file dropped now. */
    fileWelcome: function () {
      return this.source === 'file' && !this.sourceBusy;
    },

    sourceComponent: function () {
      return sourceEntry(this.source).component;
    },

    catalog: function () {
      return this.$store.state.catalog;
    },

    /* The row of the backend the server transcribes with: the one the
       catalogue names as its default, or the row flagged default. Null until
       the catalogue is in. */
    backendRow: function () {
      var rows = this.catalog.models;
      var named = this.catalog.backend;
      return rows.filter(function (row) { return row.backend === named; })[0] ||
        rows.filter(function (row) { return row['default'] === true; })[0] ||
        null;
    },

    speakersAvailable: function () {
      return this.catalog.models.some(function (row) {
        return row.backend === 'diarize' && row.status === 'loaded';
      });
    },

    modes: function () {
      var available = this.speakersAvailable;
      var source = this.source;
      return MODES.filter(function (mode) {
        if (mode.diarizer && !available) return false;
        return !mode.fileOnly || source === 'file';
      });
    },

    modeTitle: function () {
      if (this.speakersAvailable) return 'Mode';
      if (!this.catalog.loaded) return 'Speakers and Turns need the server catalogue, which has not answered';
      return 'Speakers and Turns need the diarizer, and this server has not loaded it';
    },

    /* Unknown counts as yes: before the catalogue answers, the select offers
       what every backend that takes a language accepts. */
    acceptsLanguage: function () {
      return !this.backendRow || this.backendRow.accepts_language !== false;
    },

    languageCodes: function () {
      var row = this.backendRow;
      var codes = (row && Array.isArray(row.languages)) ? row.languages.slice() : [];
      return codes.sort();
    },

    /* Whether the request will carry the language: not for a backend that
       detects it itself, and not for Turns, which transcribes nothing. */
    languageUsed: function () {
      return this.acceptsLanguage && this.requestMode !== 'turns';
    },

    languageTitle: function () {
      if (this.requestMode === 'turns') return 'Who spoke when takes no language';
      if (this.acceptsLanguage) return 'Language of the recording';
      return 'The ' + this.backendRow.backend + ' backend detects the language itself';
    },

    defaultLanguageLabel: function () {
      if (!this.acceptsLanguage) return 'Detected by the backend';
      var code = this.backendRow && this.backendRow.default_language;
      return code ? 'Server default (' + code + ')' : 'Server default';
    },

    /* The select's value. A backend that takes no language shows the empty
       choice, whatever is remembered for the next backend that does. */
    languageChoice: {
      get: function () {
        return this.acceptsLanguage ? this.form.language : '';
      },
      set: function (value) {
        this.form.language = value;
        this.$savePrefs('transcribe', { language: value });
      },
    },

    /* What a source sends, reconciled with what the server offers and what
       the open source can do. */
    requestMode: function () {
      var wanted = this.form.mode;
      var offered = this.modes.some(function (mode) { return mode.value === wanted; });
      return offered ? wanted : 'text';
    },
    requestLanguage: function () {
      return this.languageUsed ? this.form.language : '';
    },
  },

  watch: {
    /* A catalogue that answers after the screen opened - the guard's first
       request failed, or RELOAD on the models screen - may add or take away
       Speakers and change the language list. */
    catalog: function () {
      this.settleForm();
    },

    /* Another source offers other modes: Turns is FILE's alone. The
       remembered mode is put back on the select as far as the new source
       allows, and comes back when FILE does. */
    source: function () {
      this.settleForm();
    },

    /* A sub-tab clicked, Back pressed, or the TRANSCRIBE tab clicked with no
       source in its link. The screen stays; only the source under it
       changes, and the one that goes stops what it was doing on its way out. */
    '$route.query.source': function () {
      this.applySource();
    },
  },

  methods: {
    /* Source */

    /* The source named in the address, remembered for the next visit. An
       address that names none - the header's TRANSCRIBE tab, a bookmark from
       before there were sources - opens the remembered one and is rewritten to
       say so, so the address always names the source on the screen.

       While the source on the screen is working, the address is put back
       instead: the locked sub-tabs stop a click, and this stops Back and a
       typed address from doing what the click could not. */
    applySource: function () {
      var wanted = this.$route.query.source;
      if (this.sourceBusy && wanted !== this.source) {
        this.rewriteSource(this.source);
        return;
      }
      if (!sourceEntry(wanted)) {
        var remembered = this.$store.state.transcribe.source;
        var fallback = sourceEntry(remembered) ? remembered : 'file';
        this.source = fallback;
        this.rewriteSource(fallback);
        return;
      }
      this.source = wanted;
      if (this.$store.state.transcribe.source !== wanted) this.$savePrefs('transcribe', { source: wanted });
    },

    rewriteSource: function (value) {
      var query = Object.assign({}, this.$route.query, { source: value });
      var leaving = this.$router.replace({ path: this.$route.path, query: query });
      if (leaving && leaving.catch) leaving.catch(function () {});
    },

    tabLocked: function (entry) {
      return this.sourceBusy && entry.value !== this.source;
    },

    tabTitle: function (entry) {
      return this.tabLocked(entry) ? BUSY_TITLES[this.source] : entry.title;
    },

    /* Drag and drop. A depth count, because the window sees a dragenter and a
       dragleave for every element the pointer crosses, and the highlight must
       not flicker off on each of them. Only drags carrying files are
       touched; text dragged within the page behaves as it always did.

       Every file drag is caught, so the browser never opens the file. FILE
       accepts it unless an upload is running; any other source refuses it -
       the pointer says so - and the warning says where it goes, once per
       drag, as the file comes over the page. */
    handleDragEnter: function (event) {
      if (!carriesFiles(event)) return;
      event.preventDefault();
      this.dragDepth += 1;
      this.dragging = this.fileWelcome;
      if (this.dragDepth !== 1) return;
      if (this.source !== 'file') this.warning = 'Files are transcribed on the FILE tab - open it and drop the file there';
      else if (this.sourceBusy) this.warning = 'Wait for the file being transcribed to finish';
    },

    handleDragOver: function (event) {
      if (!carriesFiles(event)) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = this.fileWelcome ? 'copy' : 'none';
    },

    handleDragLeave: function (event) {
      if (!carriesFiles(event)) return;
      this.dragDepth = Math.max(0, this.dragDepth - 1);
      if (this.dragDepth === 0) this.dragging = false;
    },

    handleDrop: function (event) {
      if (!carriesFiles(event)) return;
      event.preventDefault();
      this.dragDepth = 0;
      this.dragging = false;
      if (!this.fileWelcome || !this.$refs.source || !this.$refs.source.dropFiles) return;
      this.warning = '';
      this.$refs.source.dropFiles(event.dataTransfer.files);
    },

    /* Form */

    /* Put the remembered mode and language on the selects, as far as this
       server allows them. Read from the store each time, not from the
       selects: before the catalogue answers only Text is on offer, and
       settling on it then must not lose a remembered Speakers for when the
       catalogue arrives. */
    settleForm: function () {
      var prefs = this.$store.state.transcribe;
      var offered = this.modes.map(function (mode) { return mode.value; });
      var wanted = prefs.mode || offered[0];
      this.form.mode = offered.indexOf(wanted) !== -1 ? wanted : offered[0];
      var language = prefs.language;
      if (language && language !== 'auto' && this.languageCodes.indexOf(language) === -1) language = '';
      this.form.language = language;
    },

    /* The operator's choice, remembered for the next visit. Written on a
       change the operator made, never on one settleForm made - and only the
       field that changed: a DEVICE that could not offer Turns and showed
       Speakers instead must not overwrite a remembered Turns when only the
       language was touched. */
    rememberMode: function () {
      this.$savePrefs('transcribe', { mode: this.form.mode });
    },

    fetchCatalog: function () {
      var self = this;
      this.waitPush('catalogue');
      this.$store.dispatch('fetch_models')
        .catch(function (err) { self.error = self.$apiError(err); })
        .finally(function () { self.waitDrop('catalogue'); });
    },
  },
};
</script>
