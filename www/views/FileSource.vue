<template>
  <div class="stt-source">

    <div class="form-check-inline m-1 d-flex flex-wrap row-gap-1 align-items-center">
      <!-- The file: one field with its attachments - the paperclip that opens
           the picker, the name, the size once there is a file, and the cross
           that clears it. The native input is kept but hidden: its button
           text cannot be styled. A file dropped anywhere on the page lands
           here as well: the screen catches the drop and hands it to
           dropFiles(). -->
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

      <!-- Mode and language: the screen's own, the same for every source. -->
      <slot name="options" :busy="busy"></slot>

      <div style="margin-left: auto"></div>

      <div>
        <button type="button" class="btn btn-primary btn-sm fw-bold" style="min-width:100px"
                :title="file ? 'Send ' + file.name + ' to the server' : 'Choose a file first'"
                :disabled="!canTranscribe || held" @click="transcribe">
          <i class="fa fa-play"></i> TRANSCRIBE
        </button>
      </div>
    </div>

    <!-- Until there is a result the drop zone is the big target under the
         form; with a transcript under it, it shrinks to one line so the text
         is on the screen without scrolling. A button to the keyboard as well
         as to the pointer: Enter or Space opens the same picker the paperclip
         does. -->
    <div class="stt-drop" :class="{ 'stt-drop-compact': compact }" role="button" tabindex="0"
         :aria-disabled="busy ? 'true' : 'false'"
         @click="pickFile" @keydown.enter.prevent="pickFile" @keydown.space.prevent="pickFile">
      <i class="fa fa-file-audio" aria-hidden="true"></i>
      <div v-if="file">{{ file.name }} - {{ $fmtBytes(file.size) }}</div>
      <div v-else>Drop an audio file here, or click to choose one</div>
    </div>

    <stt-alerts :wait="wait" :error.sync="error" :warning.sync="warning"
                :info.sync="info" :success.sync="success"></stt-alerts>
  </div>
</template>

<script>
/* The FILE source of the transcribe screen: an audio file, chosen or dropped,
   sent whole.

   Three requests behind one button, one per mode. All take the file as the
   multipart field `file`:
   - Speakers is POST /api/transcript - diarization first, then
     transcription, joined into segments that each name a speaker;
   - Text is POST /api/stt - the words alone;
   - Turns is POST /api/diarize - who spoke when, as time ranges, and no text
     at all.
   The first two take the language as the form field `language` when one is
   chosen; diarization has no use for one.

   The screen owns the mode and the language (they are the same for every
   source) and hands this the values to send. The answer is kept in the store
   as FILE's transcript, where the screen reads it - and where it still lands
   if the screen was left while the upload ran. The chosen file is kept there
   too, so a look at another screen does not lose it. `busy` tells the screen
   when an upload is in flight, so it can keep the source switch from
   destroying it. Used as:

     <stt-file-source :mode="mode" :language="language" :compact="!!result"
                      :held="catalogue loading" @busy="...">
       <template #options="{ busy }">...the mode and language selects...</template>
     </stt-file-source>
*/

/* Where each mode is sent, and what the wait strip says meanwhile. */
var REQUESTS = {
  speakers: { url: '/api/transcript', doing: 'transcribing' },
  text: { url: '/api/stt', doing: 'transcribing' },
  turns: { url: '/api/diarize', doing: 'finding who spoke when in' },
};

module.exports = {
  mixins: [SttWait],

  props: {
    // What the request carries: 'speakers', 'text' or 'turns', and a language
    // code, 'auto', or '' for none. Already reconciled with what the server
    // offers.
    mode: { type: String, default: 'text' },
    language: { type: String, default: '' },
    // A transcript is on the screen: the drop zone shrinks to one line.
    compact: { type: Boolean, default: false },
    // The screen is still reading the catalogue: TRANSCRIBE waits for it.
    held: { type: Boolean, default: false },
  },

  data: function () {
    return {
      wait: [],
      error: '',
      warning: '',
      info: '',
      success: '',
    };
  },

  created: function () {
    // Kept off `data`: nothing renders from it.
    this.tickTimer = null;
  },

  beforeDestroy: function () {
    if (this.tickTimer) clearInterval(this.tickTimer);
  },

  watch: {
    busy: {
      immediate: true,
      handler: function (value) {
        this.$emit('busy', value);
      },
    },
  },

  computed: {
    /* The File the operator chose or dropped, held in the store rather than
       read back off the input: a dropped file never touches the input at
       all, and the input is rebuilt with the screen. */
    file: {
      get: function () {
        return this.$store.state.chosenFile;
      },
      set: function (value) {
        this.$store.dispatch('choose_file', value);
      },
    },

    busy: function () {
      return this.wait.length > 0;
    },

    canTranscribe: function () {
      return !!this.file && !this.busy;
    },

    fileTitle: function () {
      return this.file ? this.file.name : 'Choose an audio file, or drop one anywhere on this page';
    },
  },

  methods: {
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

    /* Files dropped on the page, handed over by the screen, which refuses
       the drop while an upload is in flight - the file would silently
       replace the one being transcribed. */
    dropFiles: function (files) {
      if (this.busy || !files || !files.length) return;
      this.setFile(files[0]);
      if (files.length > 1) this.warning = 'One file at a time - ' + files[0].name + ' was taken';
    },

    /* Transcribe */

    /* The wait strip counts the seconds: a long recording takes minutes, and
       a spinner that does not count is a spinner that may have stopped. The
       label is replaced in place and dropped under its last text. */
    transcribe: function () {
      var self = this;
      if (!this.canTranscribe || this.held) return;
      var file = this.file;
      var mode = REQUESTS[this.mode] ? this.mode : 'text';
      var request = REQUESTS[mode];
      var language = mode === 'turns' ? '' : this.language;
      var body = new FormData();
      body.append('file', file, file.name);
      if (language) body.append('language', language);
      this.error = '';
      this.warning = '';
      var started = Date.now();
      var caption = request.doing + ' ' + file.name + ' ';
      var label = caption + '0s';
      this.waitPush(label);
      this.tickTimer = setInterval(function () {
        var next = caption + Math.round((Date.now() - started) / 1000) + 's';
        var i = self.wait.indexOf(label);
        if (i !== -1) self.wait.splice(i, 1, next);
        label = next;
      }, 1000);
      // No Content-Type of our own: axios writes the multipart boundary into
      // it, and a header set here would drop the boundary.
      this.$http.post(request.url, body)
        .then(function (resp) {
          var result = { mode: mode, name: file.name, language: language, data: resp.data || {} };
          self.$store.dispatch('keep_transcript', { source: 'file', result: result });
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
