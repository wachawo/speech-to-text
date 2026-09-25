<template>
  <div class="stt-source">

    <div class="form-check-inline m-1 d-flex flex-wrap row-gap-1 align-items-center">
      <!-- The input: one field with one attachment, the button that reads the
           list again - or, while the browser still hides the names, asks for
           the access that makes it show them. -->
      <div style="margin-right: 0.25rem">
        <div class="input-group input-group-sm" style="width: 340px" :title="deviceTitle">
          <button type="button" class="btn btn-sm btn-secondary" :title="refreshTitle"
                  :disabled="!usable || active" @click="refreshDevices(true)">
            <i class="fa fa-rotate"></i>
          </button>
          <select class="form-select form-select-sm" aria-label="Device"
                  v-model="deviceId" :disabled="!usable || active" @change="rememberDevice">
            <option v-for="input in inputs" :key="input.id" :value="input.id">{{ input.label }}</option>
            <option v-if="displayOffered" :value="displayValue" :title="displayNote">Tab or screen audio</option>
          </select>
        </div>
      </div>

      <!-- Model, mode and language: the screen's own, the same for every source. -->
      <slot name="options" :busy="active || !usable"></slot>

      <div style="margin-left: auto"></div>

      <!-- While audio flows: how loud it is and how much of it the server has.
           A thin bar and a clock, next to the button that stops them. -->
      <div v-if="state === 'live' || state === 'finishing'" class="d-flex align-items-center gap-2"
           style="margin-right: 0.25rem">
        <span class="stt-meter" title="Input level, as sent to the server" role="meter"
              aria-label="Input level" aria-valuemin="0" aria-valuemax="100" :aria-valuenow="levelPercent">
          <span class="stt-meter-fill" :style="{ width: levelPercent + '%' }"></span>
        </span>
        <small class="text-secondary stt-clock" title="Audio the server has received">{{ clock }}</small>
      </div>

      <div>
        <button type="button" class="btn btn-sm fw-bold" style="min-width:100px"
                :class="active ? 'btn-danger' : 'btn-primary'" :title="buttonTitle"
                :disabled="!usable || state === 'finishing'" @click="toggle">
          <i class="fa" :class="active ? 'fa-stop' : 'fa-microphone'"></i> {{ active ? 'STOP' : 'START' }}
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
   carries what the speakers play, or the sound of a browser tab or screen -
   sent to /api/stream as it is captured, with each phrase coming back about a
   second after the speaker pauses.

   The session, in order:
   1. START opens the input (the browser may ask first).
   2. A websocket to /api/stream; the first message is `start`, with the
      model, mode and language the screen hands down and the stored token, if
      any.
   3. On `ready` - never before it - the capture starts and each 100 ms frame
      goes out as one binary message.
   4. `segment` messages append to the transcript as they arrive; `progress`
      moves the clock.
   5. STOP cuts the input, flushes the last partial frame, sends `stop`, and
      keeps the socket open until `done` or `error` - "finishing" meanwhile.

   Any failure - an `error` message, the socket closing without one, the input
   refusing to open - lands in this source's error bar and ends the capture.

   The transcript is one object for the whole session: emitted as `result`
   when the server is ready, so the screen draws it, and then added to here as
   messages arrive. The screen makes it reactive when it takes it, and every
   field is present from the start, so the additions show. */

var DISPLAY = 'display';
var DISPLAY_NOTE = 'Captures what plays in a browser tab, or the whole system\'s sound where the OS ' +
  'allows it (Windows, ChromeOS) - tick "Share audio" in the browser\'s picker';

/* How much the level meter shows: -60 dBFS (silence, for this purpose) to
   0 dBFS (full scale). A linear bar would sit near zero for ordinary speech,
   whose RMS is a few percent of full scale. */
var METER_FLOOR_DB = -60;

/* How long a session left behind when the screen goes may take to finish
   before its socket is closed regardless. The server needs a few seconds for
   the last phrase; this is only the bound on waiting for it. */
var ABANDON_TIMEOUT_MS = 60000;

var stopTracks = function (stream) {
  if (!stream) return;
  stream.getTracks().forEach(function (track) { track.stop(); });
};

/* m:ss for the clock. */
var formatClock = function (seconds) {
  var whole = Math.floor(Number(seconds) || 0);
  var rest = whole % 60;
  return Math.floor(whole / 60) + ':' + (rest < 10 ? '0' : '') + rest;
};

/* "20260925-103012", for the name a live transcript is saved under. */
var fileStamp = function () {
  var now = new Date();
  var pad = function (value) { return (value < 10 ? '0' : '') + value; };
  return now.getFullYear() + pad(now.getMonth() + 1) + pad(now.getDate()) + '-' +
    pad(now.getHours()) + pad(now.getMinutes()) + pad(now.getSeconds());
};

module.exports = {
  mixins: [SttWait],

  props: {
    // What the session asks for: a model id or '' for the server default,
    // 'speakers' or 'text', and a language code, 'auto', or '' for none.
    // Already reconciled with what the server offers.
    model: { type: String, default: '' },
    mode: { type: String, default: 'text' },
    language: { type: String, default: '' },
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
      // 'idle', 'opening' (the input and the socket, before `ready`), 'live',
      // 'finishing' (stop sent, waiting for `done`).
      state: 'idle',
      // The RMS of the last frame sent, and the seconds of audio the server
      // reported receiving.
      level: 0,
      seconds: 0,
      tlsPort: '',
    };
  },

  created: function () {
    // The session's moving parts, kept off `data`: nothing renders from them,
    // and Vue would walk every field of a socket or a stream it was handed.
    this.stream = null;
    this.capture = null;
    this.socket = null;
    this.session = null;
    if (!this.secure) this.fetchUiConfig();
    if (!this.usable) return;
    this.refreshDevices(false);
    navigator.mediaDevices.addEventListener('devicechange', this.handleDeviceChange);
  },

  /* Leaving - another source, another screen - ends the capture: the input is
     closed at once, and the server is told to stop and left to finish on its
     own (see abandon). */
  beforeDestroy: function () {
    if (this.usable) navigator.mediaDevices.removeEventListener('devicechange', this.handleDeviceChange);
    this.abandon();
  },

  computed: {
    usable: function () {
      return this.secure && this.capable;
    },

    active: function () {
      return this.state !== 'idle';
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
      if (this.active) return 'Stop, and keep what was transcribed';
      return 'Start transcribing ' + this.selectedLabel;
    },

    levelPercent: function () {
      if (!this.level) return 0;
      var db = 20 * Math.log10(this.level);
      var share = (db - METER_FLOOR_DB) / -METER_FLOOR_DB;
      return Math.round(Math.max(0, Math.min(1, share)) * 100);
    },

    clock: function () {
      return formatClock(this.seconds);
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
        .then(function (found) {
          self.inputs = found.inputs;
          self.named = found.named;
          self.settleDevice();
        })
        .catch(function (err) { self.error = self.mediaError(err, false); })
        .finally(function () { self.waitDrop('devices'); });
    },

    /* A headset plugged in or pulled out. Not while a session runs: the
       select is off then, and the input in use announces its own end. */
    handleDeviceChange: function () {
      if (this.active) return;
      this.refreshDevices(false);
    },

    /* Keep the choice on the select while the list still has it; otherwise
       the remembered one, otherwise the first. Before access is granted the
       list has no real ids, so a remembered device shows as the default until
       the first START names them - and is picked up then. */
    settleDevice: function () {
      var ids = this.inputs.map(function (input) { return input.id; });
      if (this.displayOffered) ids.push(DISPLAY);
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
      if (name === 'NoAudioShared') return 'No audio was shared - tick "Share audio" in the browser\'s picker and try again';
      if (name === 'NotAllowedError') return display ? 'Sharing was cancelled or refused' : 'Microphone access was refused';
      if (name === 'NotFoundError' || name === 'OverconstrainedError') {
        return 'The chosen device is not available - read the device list again';
      }
      if (name === 'NotReadableError' || name === 'AbortError') {
        return 'The device could not be opened - another program may be holding it';
      }
      return (err && err.message) || 'The device could not be opened';
    },

    /* Session */

    toggle: function () {
      if (this.active) this.stop();
      else this.start();
    },

    /* The input first, because that is where the browser may stop and ask;
       the socket only once there is something to send. */
    start: function () {
      var self = this;
      if (!this.usable || this.active) return;
      var display = this.deviceId === DISPLAY;
      var label = display ? 'choosing what to share' : 'opening the device';
      this.error = '';
      this.warning = '';
      this.state = 'opening';
      this.waitPush(label);
      var opening = display ? SttCapture.openDisplay() : SttCapture.openDevice(this.deviceId);
      opening.then(function (stream) {
        self.waitDrop(label);
        // STOP pressed, or the screen left, while the browser was asking.
        if (self.state !== 'opening') {
          stopTracks(stream);
          return;
        }
        self.stream = stream;
        // Access is granted now, so the browser names its inputs.
        if (!display && !self.named) self.refreshDevices(false);
        self.connect();
      }, function (err) {
        self.waitDrop(label);
        if (self.state !== 'opening') return;
        self.state = 'idle';
        self.error = self.mediaError(err, display);
      });
    },

    connect: function () {
      var self = this;
      var address = (window.location.protocol === 'https:' ? 'wss://' : 'ws://') +
        window.location.host + '/api/stream';
      var ws;
      try {
        ws = new WebSocket(address);
      } catch (err) {
        this.fail('The connection to the server was lost');
        return;
      }
      this.socket = ws;
      this.waitPush('connecting');
      ws.onopen = function () {
        if (ws === self.socket) ws.send(JSON.stringify(self.startMessage()));
      };
      ws.onmessage = function (event) { self.handleMessage(ws, event); };
      ws.onclose = function () { self.handleClose(ws); };
    },

    /* A browser cannot set headers on a websocket, so the token rides in the
       first message. Absent fields are left out rather than sent empty: an
       omitted model or language is the server's default. */
    startMessage: function () {
      var message = { type: 'start', diarize: this.mode === 'speakers' };
      if (this.model) message.model = this.model;
      if (this.language) message.language = this.language;
      var token = this.$store.state.auth.token;
      if (token) message.token = token;
      return message;
    },

    handleMessage: function (ws, event) {
      if (ws !== this.socket) return;
      var message;
      try {
        message = JSON.parse(event.data);
      } catch (err) {
        return;
      }
      if (!message || typeof message !== 'object') return;
      if (message.type === 'ready') this.onReady(message);
      else if (message.type === 'segment') this.onSegment(message);
      else if (message.type === 'progress') this.onProgress(message);
      else if (message.type === 'done') this.onDone(message);
      else if (message.type === 'error') this.onServerError(message);
    },

    /* The server is listening: the transcript is created and handed up, and
       only now does audio start to flow. The name is the track's own label,
       which for a shared tab says what was shared. */
    onReady: function (message) {
      var self = this;
      if (this.state !== 'opening' || !this.stream) return;
      this.waitDrop('connecting');
      this.state = 'live';
      this.seconds = 0;
      this.level = 0;
      var track = this.stream.getAudioTracks()[0];
      this.session = {
        mode: message.diarize ? 'speakers' : 'text',
        name: (track && track.label) || this.selectedLabel,
        stem: 'live-' + fileStamp(),
        // The model `ready` names: the chosen one, or the server's default.
        model: typeof message.model === 'string' ? message.model : this.model,
        language: this.language,
        live: true,
        listening: true,
        seconds: 0,
        messages: [message],
        data: { segments: [], speakers: 0, elapsed: null },
      };
      this.$emit('result', this.session);
      this.capture = SttCapture.create(this.stream, { onFrame: this.sendFrame, onEnded: this.handleEnded });
      this.stream = null;
      this.capture.start().catch(function (err) {
        self.fail((err && err.message) || 'The audio could not be captured');
      });
    },

    /* One frame out, and the meter moved to what was in it. The flush after
       STOP comes through here as well, which is why it checks the socket and
       not the state. */
    sendFrame: function (buffer, level) {
      this.level = level;
      var ws = this.socket;
      if (ws && ws.readyState === WebSocket.OPEN) ws.send(buffer);
    },

    /* A phrase. The fields are the ones /api/transcript segments have, so the
       transcript draws both the same way; the message itself is kept as sent,
       for JSON. The speaker count is the number of different speakers so far. */
    onSegment: function (message) {
      var session = this.session;
      if (!session) return;
      session.messages.push(message);
      session.data.segments.push({
        id: message.id,
        start: message.start,
        end: message.end,
        text: message.text,
        speaker: message.speaker === undefined ? null : message.speaker,
        overlap: !!message.overlap,
      });
      var seen = {};
      session.data.segments.forEach(function (segment) {
        if (segment.speaker !== null) seen[segment.speaker] = true;
      });
      session.data.speakers = Object.keys(seen).length;
    },

    onProgress: function (message) {
      var seconds = Number(message.seconds);
      if (!isFinite(seconds)) return;
      this.seconds = seconds;
      if (this.session) this.session.seconds = seconds;
    },

    onDone: function (message) {
      var session = this.session;
      if (session) {
        session.messages.push(message);
        if (isFinite(Number(message.seconds))) session.seconds = Number(message.seconds);
        session.data.elapsed = message.elapsed === undefined ? null : message.elapsed;
        session.listening = false;
      }
      this.finish();
    },

    /* The server's own account of what went wrong: the category and the id
       that finds it in the server log, as every HTTP failure is shown. A
       refused token is also what it is everywhere else - the sign-in screen. */
    onServerError: function (message) {
      if (this.session) this.session.messages.push(message);
      var text = typeof message.error === 'string' && message.error ? message.error : 'Live transcription failed';
      if (message.request_id) text += ' (request ' + message.request_id + ')';
      this.fail(text);
      if (message.error === 'Unauthorized') this.$signInAgain();
    },

    /* The socket closed on its own. After `done` or `error` it is no longer
       this.socket, so arriving here means neither came: the network, or the
       server going away mid-session. */
    handleClose: function (ws) {
      if (ws !== this.socket) return;
      this.fail('The connection to the server was lost');
    },

    /* The input went away mid-session: unplugged, access revoked, or "Stop
       sharing" pressed in the browser's bar. What was captured is kept - the
       session is stopped the way STOP stops it. */
    handleEnded: function () {
      if (this.state !== 'live') return;
      this.warning = this.deviceId === DISPLAY ? 'Sharing was stopped - the transcript ends here'
                                               : 'The device stopped sending audio - the transcript ends here';
      this.stop();
    },

    /* STOP. Before `ready` nothing has been sent, so there is nothing to
       finish: the input and the socket are simply closed. After it, the input
       is cut and flushed, `stop` goes out, and the socket stays open for the
       last phrase and `done`. */
    stop: function () {
      var self = this;
      if (this.state === 'opening') {
        this.closeSocket();
        stopTracks(this.stream);
        this.stream = null;
        this.state = 'idle';
        this.waitDrop('connecting');
        return;
      }
      if (this.state !== 'live') return;
      this.state = 'finishing';
      this.waitPush('finishing');
      if (this.session) this.session.listening = false;
      var capture = this.capture;
      this.capture = null;
      var ws = this.socket;
      (capture ? capture.stop() : Promise.resolve()).then(function () {
        if (ws === self.socket && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'stop' }));
      });
    },

    /* The session is over, however it ended: everything closed, the screen
       back to START. */
    finish: function () {
      if (this.capture) {
        this.capture.release();
        this.capture = null;
      }
      stopTracks(this.stream);
      this.stream = null;
      this.closeSocket();
      this.state = 'idle';
      this.level = 0;
      if (this.session) this.session.listening = false;
      this.waitDrop('connecting');
      this.waitDrop('finishing');
    },

    fail: function (text) {
      this.error = text;
      this.finish();
    },

    /* Forgotten before it is closed, so its own close event finds it is no
       longer this.socket and does not report a lost connection. */
    closeSocket: function () {
      var ws = this.socket;
      this.socket = null;
      if (ws && ws.readyState <= WebSocket.OPEN) ws.close(1000);
    },

    /* The screen is going. The input closes at once. A live session is told
       to stop and left to finish on its own - its socket closes on the
       server's `done` or `error`, or after a minute regardless - so the server
       ends the session the ordinary way rather than finding the client gone
       mid-phrase. Anything earlier has nothing to finish and is closed. */
    abandon: function () {
      var wasLive = this.state === 'live' || this.state === 'finishing';
      var sendStop = this.state === 'live';
      this.state = 'idle';
      // The transcript stays on the screen, but nothing more is coming to it.
      if (this.session) this.session.listening = false;
      if (this.capture) {
        this.capture.release();
        this.capture = null;
      }
      stopTracks(this.stream);
      this.stream = null;
      var ws = this.socket;
      this.socket = null;
      if (!ws) return;
      if (!wasLive || ws.readyState !== WebSocket.OPEN) {
        if (ws.readyState <= WebSocket.OPEN) ws.close(1000);
        return;
      }
      if (sendStop) ws.send(JSON.stringify({ type: 'stop' }));
      var timer = setTimeout(function () { ws.close(1000); }, ABANDON_TIMEOUT_MS);
      ws.onmessage = function (event) {
        var message = null;
        try {
          message = JSON.parse(event.data);
        } catch (err) {
          return;
        }
        if (message && (message.type === 'done' || message.type === 'error')) {
          clearTimeout(timer);
          ws.close(1000);
        }
      };
      ws.onclose = function () { clearTimeout(timer); };
    },
  },
};
</script>
