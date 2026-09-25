<template>
  <div class="stt-page">

    <!-- Where the sound comes from. Links rather than buttons, carrying the
         source in the address: a reload, a bookmark or a link sent to someone
         opens the same source. -->
    <ul class="nav nav-tabs stt-subtabs">
      <li class="nav-item" v-for="entry in sources" :key="entry.value">
        <router-link class="nav-link" :class="{ active: source === entry.value }" :title="entry.title"
                     :to="{ path: $route.path, query: { source: entry.value } }">{{ entry.label }}</router-link>
      </li>
    </ul>

    <!-- The source's own form, and under it whatever it needs to say about
         itself. Model, mode and language are this screen's and are the same
         for every source, so they are written once here and placed by the
         source in its row; the source says when they must be off (`busy`). -->
    <component :is="sourceComponent" :model="requestModel" :mode="requestMode" :language="requestLanguage"
               :compact="!!result" @result="showResult">
      <template #options="{ busy }">
        <!-- The model, among the ones the server loaded at startup. The empty
             choice sends none, so the server's default serves. A server with
             one model, or one from before per-request models that lists no
             selectable row, gets no select at all and looks as it always did. -->
        <div style="margin-right: 0.25rem" v-if="hasModelChoice">
          <div class="input-group input-group-sm" title="The model that transcribes, among the ones the server loaded">
            <select class="form-select form-select-sm" style="width: 220px" aria-label="Model"
                    v-model="modelChoice" :disabled="busy">
              <option value="" title="Sends no model; the server uses its default">{{ defaultModelLabel }}</option>
              <option v-for="row in selectableRows" :key="row.id" :value="row.id" :title="row.backend + ' ' + row.id">
                {{ row.id }}
              </option>
            </select>
          </div>
        </div>

        <!-- Who said what, or just the words. Speakers is offered only when
             the server has the diarizer loaded; otherwise the select holds
             Text alone and says why. -->
        <div style="margin-right: 0.25rem">
          <div class="input-group input-group-sm" :title="modeTitle">
            <select class="form-select form-select-sm" style="width: 110px" aria-label="Mode"
                    v-model="form.mode" :disabled="busy || modes.length < 2" @change="rememberForm">
              <option v-for="mode in modes" :key="mode.value" :value="mode.value" :title="mode.title">
                {{ mode.label }}
              </option>
            </select>
          </div>
        </div>

        <!-- The language, from the chosen model's own list. A backend that
             detects the language itself takes no argument, so the select is
             off and the request carries none. -->
        <div style="margin-right: 0.25rem">
          <div class="input-group input-group-sm" :title="languageTitle">
            <select class="form-select form-select-sm" style="width: 180px" aria-label="Language"
                    v-model="languageChoice" :disabled="busy || !acceptsLanguage">
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

    <!-- This screen's own messages: the catalogue, when it could not be read. -->
    <stt-alerts :wait="wait" :error.sync="error"></stt-alerts>

    <!-- The result, whatever source produced it: the component draws the
         blocks and owns COPY / TXT / JSON. -->
    <stt-transcript v-if="result" :result="result"></stt-transcript>

  </div>
</template>

<script>
/* The transcribe screen: sound in, a transcript out.

   The screen is the frame the sources share: the FILE / DEVICE switch, the
   model, the mode and the language, and the transcript under them. Each source is its
   own component with its own form, its own request and its own messages, and
   hands its result up as a `result` event:

   - FILE (views/FileSource.vue): a file, chosen or dropped, sent whole.
   - DEVICE (views/DeviceSource.vue): an input captured live and streamed.

   The result stays on the screen until the next one replaces it, from either
   source: the line above it names what it came from.
*/

var SOURCES = [
  { value: 'file', label: 'FILE', title: 'Transcribe an audio file', component: 'stt-file-source' },
  { value: 'device', label: 'DEVICE', title: 'Transcribe live from a microphone, a headset, or the sound of a tab', component: 'stt-device-source' },
];

var MODES = [
  { value: 'speakers', label: 'Speakers', title: 'Who said what: the recording split by speaker, then transcribed' },
  { value: 'text', label: 'Text', title: 'The words alone, with no speakers' },
];

var sourceEntry = function (value) {
  return SOURCES.filter(function (entry) { return entry.value === value; })[0] || null;
};

module.exports = {
  mixins: [SttWait],

  components: {
    'stt-file-source': httpVueLoader('/views/FileSource.vue'),
    'stt-device-source': httpVueLoader('/views/DeviceSource.vue'),
  },

  data: function () {
    var prefs = this.$store.state.transcribe;
    return {
      wait: [],
      error: '',
      sources: SOURCES,
      source: sourceEntry(prefs.source) ? prefs.source : 'file',
      form: { model: prefs.model, mode: prefs.mode, language: prefs.language },
      // The last answer and what it was an answer to: {mode, name, language,
      // data}, plus {live, listening, seconds, messages, stem} from a live
      // session. `data` is the server's JSON as sent.
      result: null,
    };
  },

  created: function () {
    this.applySource();
    this.settleForm();
    // The guard asked already; it only failed to get an answer if the server
    // was down, and then this screen asks again and says why in its bar.
    if (!this.catalog.loaded) this.fetchCatalog();
  },

  computed: {
    sourceComponent: function () {
      return sourceEntry(this.source).component;
    },

    catalog: function () {
      return this.$store.state.catalog;
    },

    /* The models a request may name: one row each, in the catalogue's order. */
    selectableRows: function () {
      return this.catalog.models.filter(function (row) {
        return row.selectable === true && typeof row.id === 'string' && row.id;
      });
    },

    /* The row of the model a request without `model` gets: the row flagged
       default, or - from a server older than per-request models - the row of
       the backend the catalogue names as its default. Null until the
       catalogue is in. */
    defaultRow: function () {
      var rows = this.catalog.models;
      var named = this.catalog.backend;
      return rows.filter(function (row) { return row['default'] === true; })[0] ||
        rows.filter(function (row) { return row.backend === named; })[0] ||
        null;
    },

    /* The row of the model this screen transcribes with: the chosen one while
       the server still lists it, the default otherwise. Its languages and
       whether it takes one at all drive the language select. */
    backendRow: function () {
      var wanted = this.requestModel;
      return this.selectableRows.filter(function (row) { return row.id === wanted; })[0] || this.defaultRow;
    },

    /* Whether there is a model to choose at all: two selectable rows or more. */
    hasModelChoice: function () {
      return this.selectableRows.length > 1;
    },

    defaultModelLabel: function () {
      var id = this.catalog.defaultModel || (this.defaultRow && this.defaultRow.id);
      return id ? 'Server default (' + id + ')' : 'Server default';
    },

    /* The select's value. A remembered model the server no longer lists shows
       as the default. Choosing another model keeps the language only when the
       new model knows it. */
    modelChoice: {
      get: function () {
        return this.requestModel;
      },
      set: function (value) {
        this.form.model = value;
        if (!this.isOfferedLanguage(this.form.language)) this.form.language = '';
        this.rememberForm();
      },
    },

    speakersAvailable: function () {
      return this.catalog.models.some(function (row) {
        return row.backend === 'diarize' && row.status === 'loaded';
      });
    },

    modes: function () {
      var available = this.speakersAvailable;
      return MODES.filter(function (mode) { return available || mode.value !== 'speakers'; });
    },

    modeTitle: function () {
      if (this.speakersAvailable) return 'Mode';
      if (!this.catalog.loaded) return 'Speakers needs the server catalogue, which has not answered';
      return 'Speakers needs the diarizer, and this server has not loaded it';
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

    languageTitle: function () {
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
        this.rememberForm();
      },
    },

    /* What a source sends, reconciled with what the server offers. A
       remembered model is sent only while there is a choice, so a server
       with one model gets the requests it always got. */
    requestModel: function () {
      var wanted = this.form.model;
      var listed = this.selectableRows.some(function (row) { return row.id === wanted; });
      return wanted && listed && this.hasModelChoice ? wanted : '';
    },
    requestMode: function () {
      return this.form.mode === 'speakers' && this.speakersAvailable ? 'speakers' : 'text';
    },
    requestLanguage: function () {
      return this.acceptsLanguage ? this.form.language : '';
    },
  },

  watch: {
    /* A catalogue that answers after the screen opened - the guard's first
       request failed, or RELOAD on the models screen - may add or take away
       Speakers, a model and change the language list. */
    catalog: function () {
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
       say so, so the address always names the source on the screen. */
    applySource: function () {
      var wanted = this.$route.query.source;
      if (!sourceEntry(wanted)) {
        var remembered = this.$store.state.transcribe.source;
        var fallback = sourceEntry(remembered) ? remembered : 'file';
        this.source = fallback;
        var query = Object.assign({}, this.$route.query, { source: fallback });
        var leaving = this.$router.replace({ path: this.$route.path, query: query });
        if (leaving && leaving.catch) leaving.catch(function () {});
        return;
      }
      this.source = wanted;
      if (this.$store.state.transcribe.source !== wanted) this.$savePrefs('transcribe', { source: wanted });
    },

    showResult: function (result) {
      this.result = result;
    },

    /* Form */

    /* Put the remembered model, mode and language on the selects, as far as
       this server allows them. Read from the store each time, not from the
       selects: before the catalogue answers only Text is on offer, and
       settling on it then must not lose a remembered Speakers for when the
       catalogue arrives. */
    settleForm: function () {
      var prefs = this.$store.state.transcribe;
      // The model first: the language list below is the chosen model's.
      this.form.model = prefs.model;
      var offered = this.modes.map(function (mode) { return mode.value; });
      var wanted = prefs.mode || offered[0];
      this.form.mode = offered.indexOf(wanted) !== -1 ? wanted : offered[0];
      this.form.language = this.isOfferedLanguage(prefs.language) ? prefs.language : '';
    },

    /* Whether the language select of the current model offers a value: the
       empty choice and auto always, a code only from the model's own list. */
    isOfferedLanguage: function (language) {
      return !language || language === 'auto' || this.languageCodes.indexOf(language) !== -1;
    },

    /* The operator's choice, remembered for the next visit. Written on a
       change the operator made, never on one settleForm made. */
    rememberForm: function () {
      this.$savePrefs('transcribe', { model: this.form.model, mode: this.form.mode, language: this.form.language });
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
