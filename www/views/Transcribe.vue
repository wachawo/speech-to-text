<template>
  <div class="stt-page" :class="{ 'stt-dragging': dragging }">

    <!-- The source: a file, chosen or dropped. Its form row and drop zone are
         the only part of this screen that knows where the audio comes from;
         the alerts and the transcript under them do not. -->
    <div class="form-check-inline m-1 d-flex flex-wrap row-gap-1 align-items-center">
      <!-- The file: one field with its attachments - the paperclip that opens
           the picker, the name, the size once there is a file, and the cross
           that clears it. The native input is kept but hidden: its button
           text cannot be styled. A file dropped anywhere on the page lands
           here as well (see the window listeners below). -->
      <div style="margin-right: 0.25rem">
        <input ref="file" type="file" class="d-none" accept="audio/*,video/*" @change="onFile" />
        <div class="input-group input-group-sm" style="width: 340px" :title="fileTitle">
          <button type="button" class="btn btn-sm btn-secondary" title="Choose an audio file"
                  :disabled="busy" @click="pickFile">
            <i class="fa fa-paperclip"></i>
          </button>
          <input type="text" class="form-control cursor-pointer" readonly
                 :value="file ? file.name : ''" placeholder="No file chosen"
                 :disabled="busy" @click="pickFile" />
          <span class="input-group-text" v-if="file">{{ $fmtBytes(file.size) }}</span>
          <button v-if="file" type="button" class="btn btn-sm btn-secondary px-1" title="Clear the file"
                  tabindex="-1" :disabled="busy" @click="clearFile">
            <i class="fa fa-times"></i>
          </button>
        </div>
      </div>

      <!-- Who said what, or just the words. Speakers is offered only when the
           server has the diarizer loaded; otherwise the select holds Text
           alone and says why. -->
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

      <!-- The language, from the default backend's own list. A backend that
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

      <div style="margin-left: auto"></div>

      <div>
        <button type="button" class="btn btn-primary btn-sm fw-bold" style="min-width:100px"
                :title="file ? 'Send ' + file.name + ' to the server' : 'Choose a file first'"
                :disabled="!canTranscribe" @click="transcribe">
          <i class="fa fa-play"></i> TRANSCRIBE
        </button>
      </div>
    </div>

    <!-- Until there is a result the drop zone is the big target under the
         form; with a transcript under it, it shrinks to one line so the text
         is on the screen without scrolling. A button to the keyboard as well
         as to the pointer: Enter or Space opens the same picker the paperclip
         does. -->
    <div class="stt-drop" :class="{ 'stt-drop-compact': !!result }" role="button" tabindex="0"
         :aria-disabled="busy ? 'true' : 'false'"
         @click="pickFile" @keydown.enter.prevent="pickFile" @keydown.space.prevent="pickFile">
      <i class="fa fa-file-audio" aria-hidden="true"></i>
      <div v-if="file">{{ file.name }} - {{ $fmtBytes(file.size) }}</div>
      <div v-else>Drop an audio file here, or click to choose one</div>
    </div>

    <stt-alerts :wait="wait" :error.sync="error" :warning.sync="warning"
                :info.sync="info" :success.sync="success"></stt-alerts>

    <!-- The result, whatever source produced it: the component draws the
         blocks and owns COPY / TXT / JSON. -->
    <stt-transcript v-if="result" :result="result"></stt-transcript>

  </div>
</template>

<script>
/* The transcribe screen: an audio file in, a transcript out.

   Two requests behind one button. Speakers is POST /api/transcript -
   diarization first, then transcription, joined into segments that each name a
   speaker. Text is POST /api/stt - the words alone. Both take the file as the
   multipart field `file` and the language as the form field `language` when
   one is chosen.

   The result stays on the screen until the next one replaces it; choosing
   another file does not clear it, because the line above it names the file it
   came from.
*/

var MODES = [
  { value: 'speakers', label: 'Speakers', title: 'Who said what: the recording split by speaker, then transcribed' },
  { value: 'text', label: 'Text', title: 'The words alone, with no speakers' },
];

/* Whether a drag carries files rather than text or a link from the page. */
var carriesFiles = function (event) {
  var types = event && event.dataTransfer && event.dataTransfer.types;
  return !!types && Array.prototype.indexOf.call(types, 'Files') !== -1;
};

module.exports = {
  mixins: [SttWait],

  data: function () {
    var prefs = this.$store.state.transcribe;
    return {
      wait: [],
      error: '',
      warning: '',
      info: '',
      success: '',
      form: { mode: prefs.mode, language: prefs.language },
      // The File the operator chose or dropped, held here rather than read
      // back off the input: a dropped file never touches the input at all.
      file: null,
      // The last answer and what it was an answer to: {mode, name, language,
      // data}. `data` is the server's JSON as sent - JSON saves exactly that.
      result: null,
      // A file is being dragged over the window.
      dragging: false,
    };
  },

  created: function () {
    // Kept off `data`: nothing renders from them.
    this.tickTimer = null;
    this.dragDepth = 0;
    this.settleForm();
    // The guard asked already; it only failed to get an answer if the server
    // was down, and then this screen asks again and says why in its bar.
    if (!this.catalog.loaded) this.fetchCatalog();
  },

  /* The whole window takes a dropped file, not just the drop zone: once a
     transcript is up the zone is one line tall, and a file dropped a few
     pixels off it would otherwise be opened by the browser in place of this
     page. Listening on the window is what stops that, so the listeners live
     exactly as long as this screen. */
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
    if (this.tickTimer) clearInterval(this.tickTimer);
  },

  computed: {
    busy: function () {
      return this.wait.length > 0;
    },

    canTranscribe: function () {
      return !!this.file && !this.busy;
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

    /* The select's value: what the request will carry. A backend that takes
       no language shows the empty choice, whatever is remembered for the next
       backend that does. */
    languageChoice: {
      get: function () {
        return this.acceptsLanguage ? this.form.language : '';
      },
      set: function (value) {
        this.form.language = value;
        this.rememberForm();
      },
    },

    fileTitle: function () {
      return this.file ? this.file.name : 'Choose an audio file, or drop one anywhere on this page';
    },
  },

  watch: {
    /* A catalogue that answers after the screen opened - the guard's first
       request failed, or RELOAD on the models screen - may add or take away
       Speakers and change the language list. */
    catalog: function () {
      this.settleForm();
    },
  },

  methods: {
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
       change the operator made, never on one settleForm made. */
    rememberForm: function () {
      this.$savePrefs('transcribe', { mode: this.form.mode, language: this.form.language });
    },

    fetchCatalog: function () {
      var self = this;
      this.waitPush('catalogue');
      this.$store.dispatch('fetch_models')
        .catch(function (err) { self.error = self.$apiError(err); })
        .finally(function () { self.waitDrop('catalogue'); });
    },

    /* File */

    pickFile: function () {
      if (this.busy || !this.$refs.file) return;
      this.$refs.file.click();
    },

    /* The input is emptied once the File is held: choosing the same file
       again - after editing it on disk, say - must still fire `change`. */
    onFile: function (event) {
      var files = event.target.files;
      if (files && files.length) this.setFile(files[0]);
      event.target.value = '';
    },

    setFile: function (file) {
      this.file = file;
      this.warning = '';
    },

    clearFile: function () {
      this.file = null;
    },

    /* Drag and drop. A depth count, because the window sees a dragenter and a
       dragleave for every element the pointer crosses, and the outline must
       not flicker off on each of them. Only drags carrying files are
       touched; text dragged within the page behaves as it always did. While
       a request is running the drop is refused - the file would silently
       replace the one being transcribed. */
    handleDragEnter: function (event) {
      if (!carriesFiles(event)) return;
      event.preventDefault();
      this.dragDepth += 1;
      this.dragging = !this.busy;
    },

    handleDragOver: function (event) {
      if (!carriesFiles(event)) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = this.busy ? 'none' : 'copy';
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
      if (this.busy) return;
      var files = event.dataTransfer.files;
      if (!files || !files.length) return;
      this.setFile(files[0]);
      if (files.length > 1) this.warning = 'One file at a time - ' + files[0].name + ' was taken';
    },

    /* Transcribe */

    /* The wait strip counts the seconds: a long recording takes minutes, and
       a spinner that does not count is a spinner that may have stopped. The
       label is replaced in place and dropped under its last text. */
    transcribe: function () {
      var self = this;
      if (!this.canTranscribe) return;
      var file = this.file;
      var mode = this.form.mode === 'speakers' && this.speakersAvailable ? 'speakers' : 'text';
      var language = this.acceptsLanguage ? this.form.language : '';
      var body = new FormData();
      body.append('file', file, file.name);
      if (language) body.append('language', language);
      this.error = '';
      this.warning = '';
      var started = Date.now();
      var label = 'transcribing ' + file.name + ' 0s';
      this.waitPush(label);
      this.tickTimer = setInterval(function () {
        var next = 'transcribing ' + file.name + ' ' + Math.round((Date.now() - started) / 1000) + 's';
        var i = self.wait.indexOf(label);
        if (i !== -1) self.wait.splice(i, 1, next);
        label = next;
      }, 1000);
      // No Content-Type of our own: axios writes the multipart boundary into
      // it, and a header set here would drop the boundary.
      this.$http.post(mode === 'speakers' ? '/api/transcript' : '/api/stt', body)
        .then(function (resp) {
          self.result = { mode: mode, name: file.name, language: language, data: resp.data || {} };
        })
        .catch(function (err) { self.error = self.$apiError(err); })
        .finally(function () {
          clearInterval(self.tickTimer);
          self.tickTimer = null;
          self.waitDrop(label);
        });
    },
  },
};
</script>
