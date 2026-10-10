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
   too, so a look at another screen does not lose it, and so is the upload in
   flight, so the source rebuilt on the way back shows it still running and
   does not send the file again, and so is the reason it failed, so a failure
   that comes while the screen is away is still on the error bar when it is
   back. `busy` tells the screen when an upload is in flight, so it can keep
   the source switch from destroying it. Used as:

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
      warning: '',
      info: '',
      success: '',
    };
  },

  created: function () {
    // Kept off `data`: nothing renders from them.
    this.tickTimer = null;
    this.uploadLabel = '';
    this.showUpload(this.upload);
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

    upload: function (value) {
      this.showUpload(value);
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

    /* The upload in flight, from the store: it may have been started by
       the FILE source that stood here before the screen was left. */
    upload: function () {
      return this.$store.state.upload;
    },

    busy: function () {
      return !!this.upload;
    },

    /* The error bar, from the store: the failure of an upload this source
       may not have sent, if the screen was left while it ran. Dismissing it
       clears it there, so the rebuilt source does not show it again. */
    error: {
      get: function () {
        return this.$store.state.uploadError;
      },
      set: function (value) {
        this.$store.dispatch('keep_upload_error', value);
      },
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

    /* The upload in flight on the wait strip, or nothing. The strip counts
       the seconds from the upload's start: a long recording takes minutes,
       and a spinner that does not count is a spinner that may have stopped.
       The label is replaced in place and dropped under its last text. */
    showUpload: function (upload) {
      var self = this;
      if (this.tickTimer) clearInterval(this.tickTimer);
      this.tickTimer = null;
      this.waitDrop(this.uploadLabel);
      this.uploadLabel = '';
      if (!upload) return;
      var labelNow = function () {
        return upload.caption + Math.round((Date.now() - upload.started) / 1000) + 's';
      };
      this.uploadLabel = labelNow();
      this.waitPush(this.uploadLabel);
      this.tickTimer = setInterval(function () {
        var next = labelNow();
        var i = self.wait.indexOf(self.uploadLabel);
        if (i !== -1) self.wait.splice(i, 1, next);
        self.uploadLabel = next;
      }, 1000);
    },

    /* The upload goes into the store before the request does, so TRANSCRIBE
       is off from this click on, whichever FILE source is on the screen when
       the answer comes; the answer, or the failure, is filed under the
       upload's number. */
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
      this.$store.dispatch('start_upload', request.doing + ' ' + file.name + ' ');
      var serial = this.$store.state.upload.serial;
      // No Content-Type of our own: axios writes the multipart boundary into
      // it, and a header set here would drop the boundary.
      this.$http.post(request.url, body)
        .then(function (resp) {
          var result = { mode: mode, name: file.name, language: language, data: resp.data || {} };
          self.$store.dispatch('finish_upload', { serial: serial, result: result, error: '' });
        }, function (err) {
          self.$store.dispatch('finish_upload', { serial: serial, result: null, error: self.$apiError(err) });
        });
    },
  },
};
</script>
