<template>
  <div class="stt-source" :class="{ 'stt-dragging': dragging }">

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

      <!-- Model, mode and language: the screen's own, the same for every source. -->
      <slot name="options" :busy="busy"></slot>

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

   Two requests behind one button. Speakers is POST /api/transcript -
   diarization first, then transcription, joined into segments that each name a
   speaker. Text is POST /api/stt - the words alone. Both take the file as the
   multipart field `file`, and the model and the language as the form fields
   `model` and `language` when one is chosen.

   The screen owns the model, the mode and the language (they are the same
   for every source) and hands this the values to send; the answer goes back
   up as a `result` event, and the screen draws it. Used as:

     <stt-file-source :model="model" :mode="mode" :language="language"
                      :compact="!!result" @result="showResult">
       <template #options="{ busy }">...the model, mode and language selects...</template>
     </stt-file-source>
*/

/* Whether a drag carries files rather than text or a link from the page. */
var carriesFiles = function (event) {
  var types = event && event.dataTransfer && event.dataTransfer.types;
  return !!types && Array.prototype.indexOf.call(types, 'Files') !== -1;
};

module.exports = {
  mixins: [SttWait],

  props: {
    // What the request carries: a model id or '' for the server default,
    // 'speakers' or 'text', and a language code, 'auto', or '' for none.
    // Already reconciled with what the server offers.
    model: { type: String, default: '' },
    mode: { type: String, default: 'text' },
    language: { type: String, default: '' },
    // A transcript is on the screen: the drop zone shrinks to one line.
    compact: { type: Boolean, default: false },
  },

  data: function () {
    return {
      wait: [],
      error: '',
      warning: '',
      info: '',
      success: '',
      // The File the operator chose or dropped, held here rather than read
      // back off the input: a dropped file never touches the input at all.
      file: null,
      // A file is being dragged over the window.
      dragging: false,
    };
  },

  created: function () {
    // Kept off `data`: nothing renders from them.
    this.tickTimer = null;
    this.dragDepth = 0;
  },

  /* The whole window takes a dropped file, not just the drop zone: once a
     transcript is up the zone is one line tall, and a file dropped a few
     pixels off it would otherwise be opened by the browser in place of this
     page. Listening on the window is what stops that, so the listeners live
     exactly as long as this source is on the screen. */
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

    /* Drag and drop. A depth count, because the window sees a dragenter and a
       dragleave for every element the pointer crosses, and the highlight must
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
      var mode = this.mode === 'speakers' ? 'speakers' : 'text';
      var model = this.model;
      var language = this.language;
      var body = new FormData();
      body.append('file', file, file.name);
      if (model) body.append('model', model);
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
          var data = resp.data || {};
          // The model the server says transcribed, which is the default's id
          // when none was chosen.
          var used = typeof data.model === 'string' ? data.model : model;
          self.$emit('result', { mode: mode, name: file.name, model: used, language: language, data: data });
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
