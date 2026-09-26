<template>
  <div class="stt-source">

    <div class="form-check-inline m-1 d-flex flex-wrap row-gap-1 align-items-center">
      <!-- The address: one field with its attachments - the glyph that says
           what it is, and the cross that clears it. Enter starts, as START
           does. -->
      <div style="margin-right: 0.25rem">
        <div class="input-group input-group-sm" style="width: 420px" :title="urlTitle">
          <span class="input-group-text px-2"><i class="fa fa-tower-broadcast" aria-hidden="true"></i></span>
          <input type="url" class="form-control" aria-label="Stream address"
                 placeholder="https://..., rtmp://..., rtsp://... or srt://..."
                 autocomplete="off" spellcheck="false"
                 v-model="url" :disabled="liveActive" @keydown.enter.prevent="start" />
          <button v-if="url" type="button" class="btn btn-sm btn-secondary px-1" title="Clear the address"
                  tabindex="-1" :disabled="liveActive" @click="url = ''">
            <i class="fa fa-times"></i>
          </button>
        </div>
      </div>

      <!-- Mode and language: the screen's own, the same for every source. -->
      <slot name="options" :busy="liveActive"></slot>

      <div style="margin-left: auto"></div>

      <!-- While the server reads: how much of the source it has had. No level
           bar - the audio never passes through this page. -->
      <div v-if="state === 'live' || state === 'finishing'" class="d-flex align-items-center"
           style="margin-right: 0.25rem">
        <small class="text-secondary stt-clock" title="Audio the server has read from the source">{{ liveClock }}</small>
      </div>

      <div>
        <button type="button" class="btn btn-sm fw-bold" style="min-width:100px"
                :class="liveActive ? 'btn-danger' : 'btn-primary'" :title="buttonTitle"
                :disabled="state === 'finishing' || (!liveActive && !canStart)" @click="toggle">
          <i class="fa" :class="liveActive ? 'fa-stop' : 'fa-play'"></i> {{ liveActive ? 'STOP' : 'START' }}
        </button>
      </div>
    </div>

    <stt-alerts :wait="wait" :error.sync="error" :warning.sync="warning"
                :info.sync="info" :success.sync="success"></stt-alerts>
  </div>
</template>

<script>
/* The STREAM source of the transcribe screen: an address the server reads
   itself - internet radio, HLS, RTMP, RTSP, SRT - with each phrase coming back
   about a second after the speaker pauses.

   Nothing is captured here and no audio is sent: the start message carries
   `"source": "url"` and the address, and the rest of the session is the same
   protocol as a device's (js/live.js) - `ready`, segments, progress, and
   `done`, which the server also sends on its own when the source runs out.
   STOP asks it to stop reading and waits for the last phrase, as for a device.

   No https is needed for this one: there is no device to ask the browser
   for. */

module.exports = {
  mixins: [SttWait, SttLive],

  props: {
    // What the session asks for: 'speakers' or 'text', and a language code,
    // 'auto', or '' for none. Already reconciled with what the server offers.
    mode: { type: String, default: 'text' },
    language: { type: String, default: '' },
    // The screen is still reading the catalogue: START waits for it.
    held: { type: Boolean, default: false },
    // Passed to every source; there is no drop zone here to shrink.
    compact: { type: Boolean, default: false },
  },

  data: function () {
    return {
      wait: [],
      error: '',
      warning: '',
      info: '',
      success: '',
      liveKind: 'stream',
      // The address, starting from the last one used.
      url: this.$store.state.transcribe.url,
    };
  },

  created: function () {
    // The address the running session was started with: the field can be
    // edited only when nothing runs, but the transcript is named after what
    // was actually read.
    this.startedUrl = '';
  },

  computed: {
    canStart: function () {
      return !!this.url.trim() && !this.held;
    },

    urlTitle: function () {
      return this.url.trim() || 'The address the server reads: http, https, rtmp, rtmps, rtsp or srt';
    },

    buttonTitle: function () {
      if (this.state === 'finishing') return 'Waiting for the last phrase';
      if (this.liveActive) return 'Stop reading, and keep what was transcribed';
      if (this.held) return 'Waiting for the server catalogue';
      if (!this.url.trim()) return 'Enter an address first';
      return 'Start transcribing ' + this.url.trim();
    },
  },

  methods: {
    toggle: function () {
      if (this.liveActive) this.liveStop();
      else this.start();
    },

    /* The address is trimmed and remembered as it is sent; which schemes the
       server takes is the server's call, and its refusal says which they are. */
    start: function () {
      if (this.liveActive || !this.canStart) return;
      var url = this.url.trim();
      this.url = url;
      this.startedUrl = url;
      this.$savePrefs('transcribe', { url: url });
      var attempt = this.liveBegin();
      this.liveConnect(attempt, {
        source: 'url',
        url: url,
        diarize: this.mode === 'speakers',
        language: this.language || undefined,
      });
    },

    /* What the transcript is of, for the line above it. */
    liveName: function () {
      return this.startedUrl;
    },
  },
};
</script>
