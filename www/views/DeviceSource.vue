<template>
  <div class="stt-source">

    <div class="form-check-inline m-1 d-flex flex-wrap row-gap-1 align-items-center">
      <!-- Read the list again - or, while the browser still hides the names,
           ask for the access that makes it show them. Its own control, apart
           from the select: two actions welded into one group read as one. -->
      <div style="margin-right: 0.25rem">
        <button type="button" class="btn btn-sm btn-secondary" :title="refreshTitle" :aria-label="refreshTitle"
                :disabled="!usable || liveActive" @click="refreshDevices(true)">
          <i class="fa fa-rotate"></i>
        </button>
      </div>

      <div style="margin-right: 0.25rem">
        <div class="input-group input-group-sm" style="width: 300px" :title="deviceTitle">
          <select class="form-select form-select-sm" aria-label="Device"
                  v-model="deviceId" :disabled="!usable || liveActive" @change="rememberDevice">
            <option v-for="input in inputs" :key="input.id" :value="input.id">{{ input.label }}</option>
            <option v-if="displayOffered" :value="displayValue" :title="displayNote">Tab or screen audio</option>
          </select>
        </div>
      </div>

      <!-- Mode and language: the screen's own, the same for every source. -->
      <slot name="options" :busy="liveActive || !usable"></slot>

      <div style="margin-left: auto"></div>

      <!-- While audio flows: how loud it is and how much of it the server has.
           A thin bar and a clock, next to the button that stops them. -->
      <div v-if="state === 'live' || state === 'finishing'" class="d-flex align-items-center gap-2"
           style="margin-right: 0.25rem">
        <span class="stt-meter" title="Input level, as sent to the server" role="meter"
              aria-label="Input level" aria-valuemin="0" aria-valuemax="100" :aria-valuenow="levelPercent">
          <span class="stt-meter-fill" :style="{ width: levelPercent + '%' }"></span>
        </span>
        <small class="text-secondary stt-clock" title="Audio the server has received">{{ liveClock }}</small>
      </div>

      <div>
        <button type="button" class="btn btn-sm fw-bold" style="min-width:100px"
                :class="liveActive ? 'btn-danger' : 'btn-primary'" :title="buttonTitle"
                :disabled="!usable || state === 'finishing' || (!liveActive && held)" @click="toggle">
          <i class="fa" :class="liveActive ? 'fa-stop' : 'fa-microphone'"></i> {{ liveActive ? 'STOP' : 'START' }}
        </button>
      </div>
    </div>

    <!-- Why the form is off, in one line where the file source has its drop
         zone. The link keeps the path and hash, so it opens this same screen. -->
    <div v-if="!secure" class="stt-note">
      <i class="fa fa-lock" aria-hidden="true"></i>
      Audio devices need https: open <a :href="httpsUrl">{{ httpsUrl }}</a>
    </div>
    <div v-else-if="!capable" class="stt-note">
      <i class="fa fa-circle-info" aria-hidden="true"></i>
      This browser cannot capture audio from a device
    </div>

    <stt-alerts :wait="wait" :error.sync="error" :warning.sync="warning"
                :info.sync="info" :success.sync="success"></stt-alerts>
  </div>
</template>

<script>
/* The DEVICE source of the transcribe screen: live audio from an input -
   a microphone, a headset's microphone, a "Monitor of" source on Linux that
   carries what the speakers play, or, in Chromium browsers, the sound of a
   tab or screen - sent to /api/stream as it is captured.

   The session is the shared protocol client (js/live.js); what is this
   source's own is the input:
   - START opens it (the browser may ask first), then connects;
   - on `ready` the capture starts and every 100 ms frame goes out;
   - on STOP the input is cut and its last partial frame flushed before
     `stop` is sent;
   - on leaving, or on any failure, the input is closed at once.

   Every step of a START carries its attempt: a permission prompt answered
   after STOP, or after STOP and a second START, closes the stream it granted
   and does nothing else. */

var DISPLAY = 'display';
var DISPLAY_NOTE = 'Captures what plays in a browser tab, or the whole system\'s sound where the OS ' +
  'allows it (Windows, ChromeOS); the browser asks what to share';

/* How much the level meter shows: -60 dBFS (silence, for this purpose) to
   0 dBFS (full scale). A linear bar would sit near zero for ordinary speech,
   whose RMS is a few percent of full scale. */
var METER_FLOOR_DB = -60;

/* The id of the device a stream actually records, which is not always the
   one asked for: the default, a fallback, or whatever the browser resolved
   "default" to. */
var recordedDeviceId = function (stream) {
  var track = stream && stream.getAudioTracks()[0];
  var settings = (track && track.getSettings) ? track.getSettings() : {};
  return settings.deviceId || null;
};

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
    var secure = typeof window !== 'undefined' && !!window.isSecureContext;
    return {
      wait: [],
      error: '',
      warning: '',
      info: '',
      success: '',
      liveKind: 'device',
      secure: secure,
      capable: SttCapture.supported(),
      displayOffered: SttCapture.displaySupported(),
      displayValue: DISPLAY,
      displayNote: DISPLAY_NOTE,
      // The inputs as the browser lists them, and whether it gave their real
      // names - which is also whether access has been granted.
      inputs: [{ id: '', label: 'Default microphone' }],
      named: false,
      deviceId: this.$store.state.transcribe.device,
      // The RMS of the last frame sent.
      level: 0,
      tlsPort: '',
    };
  },

  created: function () {
    // The input's moving parts, kept off `data`: nothing renders from them,
    // and Vue would walk every field of a stream it was handed.
    this.stream = null;
    this.capture = null;
    // A capture STOP has taken out of service but whose flush has not
    // finished yet; leaving the screen then must still close it.
    this.stopping = null;
    // The id of the device being recorded, once a stream is open: the select
    // shows that one, never a different one.
    this.recordingId = null;
    // The wait label of an input still opening, so a STOP during the prompt
    // can take it off the strip.
    this.openingLabel = '';
    if (!this.secure) this.fetchUiConfig();
    if (!this.usable) return;
    this.refreshDevices(false);
    navigator.mediaDevices.addEventListener('devicechange', this.handleDeviceChange);
  },

  beforeDestroy: function () {
    if (this.usable) navigator.mediaDevices.removeEventListener('devicechange', this.handleDeviceChange);
  },

  computed: {
    usable: function () {
      return this.secure && this.capable;
    },

    selectedLabel: function () {
      if (this.deviceId === DISPLAY) return 'Tab or screen audio';
      var self = this;
      var input = this.inputs.filter(function (entry) { return entry.id === self.deviceId; })[0];
      return input ? input.label : 'Default microphone';
    },

    deviceTitle: function () {
      if (this.deviceId === DISPLAY) return DISPLAY_NOTE;
      return this.selectedLabel;
    },

    refreshTitle: function () {
      return this.named ? 'Read the device list again'
                        : 'Allow microphone access, so the devices are listed by name';
    },

    buttonTitle: function () {
      if (!this.usable) return 'Audio devices are not available on this page';
      if (this.state === 'finishing') return 'Waiting for the last phrase';
      if (this.liveActive) return 'Stop, and keep what was transcribed';
      if (this.held) return 'Waiting for the server catalogue';
      return 'Start transcribing ' + this.selectedLabel;
    },

    levelPercent: function () {
      if (!this.level) return 0;
      var db = 20 * Math.log10(this.level);
      var share = (db - METER_FLOOR_DB) / -METER_FLOOR_DB;
      return Math.round(Math.max(0, Math.min(1, share)) * 100);
    },

    /* The https address of this same screen, for the line that explains why
       the form is off. The port comes from nginx (/ui-config.json); without
       an answer the address is printed without one. */
    httpsUrl: function () {
      var place = window.location;
      return 'https://' + place.hostname + (this.tlsPort ? ':' + this.tlsPort : '') +
        place.pathname + place.search + place.hash;
    },
  },

  methods: {
    /* Devices */

    fetchUiConfig: function () {
      var self = this;
      this.$http.get('/ui-config.json')
        .then(function (resp) {
          var port = resp.data && resp.data.tls_port;
          self.tlsPort = /^\d+$/.test(String(port)) ? String(port) : '';
        })
        .catch(function () { self.tlsPort = ''; });
    },

    /* Read the inputs, asking for access first when `ask` and the browser is
       still hiding their names. Asking is always the operator's click, never
       the page opening: a prompt nobody asked for is a prompt that gets
       refused. */
    refreshDevices: function (ask) {
      var self = this;
      var asking = (ask && !this.named) ? SttCapture.askPermission() : Promise.resolve();
      this.waitPush('devices');
      asking
        .then(function () { return SttCapture.listInputs(); })
        .then(function (found) { self.applyInputs(found); })
        .catch(function (err) { self.error = self.mediaError(err, false); })
        .finally(function () { self.waitDrop('devices'); });
    },

    /* The list as the select shows it. Before access is granted the browser
       lists one unnamed input with no id, so a remembered device cannot be
       found in it; it is kept on the select as "Last used microphone" rather
       than shown as the default, because START will ask for it and not for
       the default. */
    applyInputs: function (found) {
      var inputs = found.inputs.slice();
      var stored = this.$store.state.transcribe.device;
      var listed = inputs.some(function (input) { return input.id === stored; });
      if (!found.named && stored && stored !== DISPLAY && !listed) {
        inputs.push({ id: stored, label: 'Last used microphone' });
      }
      this.inputs = inputs;
      this.named = found.named;
      this.settleDevice();
    },

    /* A headset plugged in or pulled out. Not while a session runs: the
       select is off then, and the input in use announces its own end. */
    handleDeviceChange: function () {
      if (this.liveActive) return;
      this.refreshDevices(false);
    },

    /* What the select shows: the device being recorded while there is one,
       otherwise the choice on it while the list still has it, otherwise the
       remembered one, otherwise the first. */
    settleDevice: function () {
      var ids = this.inputs.map(function (input) { return input.id; });
      if (this.displayOffered) ids.push(DISPLAY);
      if (this.recordingId && ids.indexOf(this.recordingId) !== -1) {
        this.deviceId = this.recordingId;
        return;
      }
      if (ids.indexOf(this.deviceId) !== -1) return;
      var stored = this.$store.state.transcribe.device;
      this.deviceId = ids.indexOf(stored) !== -1 ? stored : ids[0];
    },

    rememberDevice: function () {
      this.$savePrefs('transcribe', { device: this.deviceId });
    },

    /* The sentence for an input that would not open. */
    mediaError: function (err, display) {
      var name = err && err.name;
      if (name === 'NoAudioShared') return 'No audio came with the share - choose a tab or screen together with its sound';
      if (name === 'NotAllowedError') return display ? 'Sharing was cancelled or refused' : 'Microphone access was refused';
      if (name === 'NotFoundError' || name === 'OverconstrainedError') {
        return 'The chosen device is not available - read the device list again';
      }
      if (name === 'NotReadableError' || name === 'AbortError') {
        return 'The device could not be opened - another program may be holding it';
      }
      return (err && err.message) || 'The device could not be opened';
    },

    /* The chosen input, exactly - a remembered one too, before access has
       been granted and the list could name it. Only if that device is gone
       does it fall back to the default, and says so. */
    openInput: function (id) {
      var self = this;
      if (!id) return SttCapture.openDevice('');
      return SttCapture.openDevice(id).catch(function (err) {
        var gone = err && (err.name === 'OverconstrainedError' || err.name === 'NotFoundError');
        if (!gone) throw err;
        self.warning = 'The chosen device is not available - recording the default input instead';
        return SttCapture.openDevice('');
      });
    },

    /* Session */

    toggle: function () {
      if (this.liveActive) this.liveStop();
      else this.start();
    },

    /* The input first, because that is where the browser may stop and ask;
       the socket only once there is something to send. */
    start: function () {
      var self = this;
      if (!this.usable || this.liveActive || this.held) return;
      var display = this.deviceId === DISPLAY;
      var attempt = this.liveBegin();
      var label = display ? 'choosing what to share' : 'opening the device';
      this.openingLabel = label;
      this.waitPush(label);
      var opening = display ? SttCapture.openDisplay() : this.openInput(this.deviceId);
      opening.then(function (stream) {
        self.waitDrop(label);
        // STOP pressed, or STOP and START again, or the screen left, while
        // the browser was asking: this stream belongs to nobody.
        if (!self.liveCurrent(attempt)) {
          SttCapture.stopTracks(stream);
          return;
        }
        self.openingLabel = '';
        self.stream = stream;
        if (!display) self.followRecording(stream);
        self.liveConnect(attempt, {
          diarize: self.mode === 'speakers',
          language: self.language || undefined,
        });
      }, function (err) {
        self.waitDrop(label);
        if (!self.liveCurrent(attempt)) return;
        self.openingLabel = '';
        self.liveFail(self.mediaError(err, display));
      });
    },

    /* The select follows the device actually recorded. Access has just been
       granted if it was not before, so the list is read again for its names;
       either way the one being recorded is what the select shows. */
    followRecording: function (stream) {
      this.recordingId = recordedDeviceId(stream);
      if (!this.named) this.refreshDevices(false);
      else this.settleDevice();
    },

    /* What the transcript is of: the track's own label, which for a shared
       tab says what was shared. */
    liveName: function () {
      var track = this.stream && this.stream.getAudioTracks()[0];
      return (track && track.label) || this.selectedLabel;
    },

    /* The server is listening: only now does audio start to flow. The
       capture owns the stream from here. */
    onLiveReady: function () {
      var self = this;
      var attempt = this.attempt;
      this.capture = SttCapture.create(this.stream, { onFrame: this.sendFrame, onEnded: this.handleEnded });
      this.stream = null;
      this.capture.start().catch(function (err) {
        if (attempt === self.attempt && self.state === 'live') {
          self.liveFail((err && err.message) || 'The audio could not be captured');
        }
      });
    },

    /* One frame out, and the meter moved to what was in it. The flush after
       STOP comes through here as well. */
    sendFrame: function (buffer, level) {
      this.level = level;
      this.liveSend(buffer);
    },

    /* STOP: the input is cut and its last partial frame sent before `stop`. */
    onLiveStopping: function () {
      var self = this;
      var capture = this.capture;
      this.capture = null;
      this.level = 0;
      if (!capture) return null;
      this.stopping = capture;
      return capture.stop().then(function () {
        if (self.stopping === capture) self.stopping = null;
      });
    },

    /* Everything this source opened, closed; safe at any point, twice. */
    onLiveRelease: function () {
      if (this.capture) {
        this.capture.release();
        this.capture = null;
      }
      if (this.stopping) {
        this.stopping.release();
        this.stopping = null;
      }
      SttCapture.stopTracks(this.stream);
      this.stream = null;
      this.recordingId = null;
      this.level = 0;
      if (this.openingLabel) {
        this.waitDrop(this.openingLabel);
        this.openingLabel = '';
      }
    },

    /* The input went away mid-session: unplugged, access revoked, or "Stop
       sharing" pressed in the browser's bar. What was captured is kept - the
       session is stopped the way STOP stops it. */
    handleEnded: function () {
      if (this.state !== 'live') return;
      this.warning = this.deviceId === DISPLAY ? 'Sharing was stopped - the transcript ends here'
                                               : 'The device stopped sending audio - the transcript ends here';
      this.liveStop();
    },
  },
};
</script>
