/* SttLive - the /api/stream client, one implementation for every live source.

   A Vue mixin rather than a class: a live source is a screen component whose
   state (the START / STOP button, the clock, the error bar, the wait strip) is
   the session's state, and a mixin puts the session straight into it. Loaded
   by index.html ahead of app.js and named in `mixins` by the sources, the way
   SttWait is.

   The protocol, from this side:
   1. liveBegin() at START: a new attempt, the old session record dropped.
   2. liveConnect(): the socket, and a `start` message carrying the source's
      own fields plus the stored token, if any (a browser cannot set headers
      on a websocket).
   3. On `ready` the session record is created and kept in the store as this
      source's transcript (keep_transcript), and the source's onLiveReady hook
      starts whatever it feeds the socket with.
   4. `segment` messages are added to the record as they come; `progress`
      moves the clock; `skipped` - the server fell behind and dropped queued
      phrases - updates the running total the transcript warns about.
   5. liveStop(): the source's onLiveStopping hook runs (a device flushes its
      last frame), `stop` goes out, and the socket stays open until `done` or
      `error` - the "finishing" state. The server may also end a session on
      its own with `done`, when a URL source runs out.
   6. Any failure - an `error` message, a close without either, the source's
      own - is liveFail(): the error bar, and everything released.

   What a source provides:
   - data `wait`, `error`, `warning`, `info` (the stt-alerts strings), and the
     props `mode` and `language` the screen hands down;
   - `liveKind` in data ('device', 'stream'): the prefix of the file name a
     transcript is saved under;
   - liveName(): what the transcript is of, for the line above it;
   - optional hooks onLiveReady(message), onLiveStopping() -> Promise,
     onLiveRelease() - the last must be safe to call at any point.

   Every asynchronous step is tagged with the attempt it belongs to. START,
   STOP, START inside one permission prompt is three attempts, and a
   continuation that finds a newer one than its own does nothing but close
   what it opened. */
(function () {
  'use strict';

  /* How long a session left behind when its screen goes may take to finish
     before its socket is closed regardless. The server needs a few seconds
     for the last phrase; this is only the bound on waiting for it. */
  var ABANDON_TIMEOUT_MS = 60000;

  /* How much audio may wait in the socket's own buffer before frames are
     dropped: three seconds of 16 kHz PCM16. A link slower than the audio
     would otherwise queue without bound - memory growing for as long as the
     session runs, and the server hearing it later and later. */
  var BACKLOG_BYTES = 3 * 32000;

  var LOST = 'The connection to the server was lost';

  /* The live error categories, in words a user can act on. The server's own
     category is what stays in the JSON; this is only the error bar. Anything
     not listed is shown as the category itself, the way every HTTP failure is. */
  var CATEGORY_TEXT = {
    'Invalid stream URL': 'Invalid stream URL - use an http, https, rtmp, rtmps, rtsp or srt address',
    'Stream source failed': 'The server could not read the stream at that address',
    'Forbidden': 'This server does not allow URL sources from this page',
    'Service Unavailable': 'The server is busy - too many live sessions at once, try again later',
  };

  var OPEN = 1;

  /* "20260925-103012", for the name a live transcript is saved under. */
  var fileStamp = function () {
    var now = new Date();
    var pad = function (value) { return (value < 10 ? '0' : '') + value; };
    return now.getFullYear() + pad(now.getMonth() + 1) + pad(now.getDate()) + '-' +
      pad(now.getHours()) + pad(now.getMinutes()) + pad(now.getSeconds());
  };

  /* The error bar's sentence for an `error` message, with the id that finds
     it in the server log. */
  var errorText = function (message) {
    var category = typeof message.error === 'string' && message.error ? message.error : 'Live transcription failed';
    var text = CATEGORY_TEXT[category] || category;
    if (message.request_id) text += ' (request ' + message.request_id + ')';
    return text;
  };

  /* `stop` once per socket, and only on one that is open: before `open` there
     is nothing to stop, and after `close` nobody to tell. */
  var sendStop = function (ws) {
    if (!ws || ws.sttStopSent || ws.readyState !== OPEN) return;
    ws.sttStopSent = true;
    ws.send(JSON.stringify({ type: 'stop' }));
  };

  window.SttLive = {
    data: function () {
      return {
        // 'idle', 'opening' (the source and the socket, before `ready`),
        // 'live', 'finishing' (stop sent, waiting for `done`).
        state: 'idle',
        // Seconds of audio the server reports having received.
        seconds: 0,
      };
    },

    created: function () {
      // Kept off `data`: nothing renders from them, and Vue would walk every
      // field of a socket it was handed.
      this.socket = null;
      this.session = null;
      this.attempt = 0;
      this.backlogWarned = false;
    },

    /* Leaving - another source, another screen - ends the session. */
    beforeDestroy: function () {
      this.liveAbandon();
    },

    watch: {
      /* The screen locks the source switch while a session runs, so it hears
         about every change - from `opening` until the session is idle again. */
      state: {
        immediate: true,
        handler: function (value) {
          this.$emit('busy', value !== 'idle');
        },
      },
    },

    computed: {
      liveActive: function () {
        return this.state !== 'idle';
      },

      liveClock: function () {
        return this.$fmtClock(this.seconds);
      },
    },

    methods: {
      /* START. Answers the attempt's id, which every later step of it checks
         with liveCurrent(). The previous session's record is let go here, so
         an error before the new `ready` cannot land in the old transcript. */
      liveBegin: function () {
        this.attempt += 1;
        this.session = null;
        this.backlogWarned = false;
        this.error = '';
        this.warning = '';
        this.info = '';
        this.seconds = 0;
        this.state = 'opening';
        return this.attempt;
      },

      /* Whether an attempt is still the one in progress, before `ready`. */
      liveCurrent: function (attempt) {
        return attempt === this.attempt && this.state === 'opening';
      },

      /* The socket, for an attempt that is still current - never for a stale
         one. `fields` are the source's part of the start message; an
         undefined field is left out by JSON.stringify, which is what an
         omitted language (the server's default) needs. */
      liveConnect: function (attempt, fields) {
        var self = this;
        if (!this.liveCurrent(attempt)) return;
        var address = (window.location.protocol === 'https:' ? 'wss://' : 'ws://') +
          window.location.host + '/api/stream';
        var start = Object.assign({ type: 'start' }, fields);
        var token = this.$store.state.auth.token;
        if (token) start.token = token;
        var ws;
        try {
          ws = new WebSocket(address);
        } catch (err) {
          this.liveFail(LOST);
          return;
        }
        this.socket = ws;
        this.waitPush('connecting');
        ws.onopen = function () {
          if (ws === self.socket) ws.send(JSON.stringify(start));
        };
        ws.onmessage = function (event) { self.liveMessage(ws, event); };
        // After `done` or `error` the socket is no longer this.socket, so
        // arriving here means neither came: the network, or the server going
        // away mid-session.
        ws.onclose = function () {
          if (ws === self.socket) self.liveFail(LOST);
        };
      },

      liveMessage: function (ws, event) {
        if (ws !== this.socket) return;
        var message;
        try {
          message = JSON.parse(event.data);
        } catch (err) {
          return;
        }
        if (!message || typeof message !== 'object') return;
        if (message.type === 'ready') this.liveReady(message);
        else if (message.type === 'segment') this.liveSegment(message);
        else if (message.type === 'progress') this.liveProgress(message);
        else if (message.type === 'skipped') this.liveSkipped(message);
        else if (message.type === 'done') this.liveDone(message);
        else if (message.type === 'error') this.liveServerError(message);
      },

      /* The server is listening: the transcript is created and kept as this
         source's, and the source may start. Every field is there from the
         start, so the store, which makes the object reactive when it takes
         it, sees every later addition. */
      liveReady: function (message) {
        if (this.state !== 'opening') return;
        this.waitDrop('connecting');
        this.state = 'live';
        this.seconds = 0;
        this.session = {
          mode: message.diarize ? 'speakers' : 'text',
          name: this.liveName(),
          stem: this.liveKind + '-' + fileStamp(),
          language: this.language,
          live: true,
          listening: true,
          finishing: false,
          seconds: 0,
          skipped: 0,
          messages: [message],
          data: { segments: [], speakers: 0, elapsed: null },
        };
        this.$store.dispatch('keep_transcript', { source: this.liveKind, result: this.session });
        if (this.onLiveReady) this.onLiveReady(message);
      },

      /* A phrase. The fields are the ones /api/transcript segments have, so
         the transcript draws both the same way; the message itself is kept as
         sent, for JSON. The speaker count is the number of different speakers
         so far. */
      liveSegment: function (message) {
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

      liveProgress: function (message) {
        var seconds = Number(message.seconds);
        if (!isFinite(seconds)) return;
        this.seconds = seconds;
        if (this.session) this.session.seconds = seconds;
      },

      /* The server fell more than two minutes behind and dropped phrases it
         had queued. `seconds` is the running total for the session, so the
         latest one is the figure to show; each is kept for JSON. */
      liveSkipped: function (message) {
        var seconds = Number(message.seconds);
        if (!isFinite(seconds) || !this.session) return;
        this.session.messages.push(message);
        this.session.skipped = seconds;
      },

      /* The end. After STOP it is the answer to `stop`; while still live it
         is the server ending the session itself - a URL source that ran out -
         and the info bar says so, since nobody pressed anything. */
      liveDone: function (message) {
        var ended = this.state === 'live';
        var session = this.session;
        if (session) {
          session.messages.push(message);
          if (isFinite(Number(message.seconds))) session.seconds = Number(message.seconds);
          session.data.elapsed = message.elapsed === undefined ? null : message.elapsed;
        }
        this.liveFinish();
        if (ended) this.info = 'The source ended - the transcript is complete';
      },

      /* A refused token is what it is everywhere else: the sign-in screen. */
      liveServerError: function (message) {
        if (this.session) this.session.messages.push(message);
        this.liveFail(errorText(message));
        if (message.error === 'Unauthorized') this.$signInAgain();
      },

      /* One frame out. Dropped rather than queued when the socket's buffer
         already holds a few seconds, with one warning per session: a warning
         per dropped frame would be ten a second. */
      liveSend: function (buffer) {
        var ws = this.socket;
        if (!ws || ws.readyState !== OPEN) return;
        if (ws.bufferedAmount > BACKLOG_BYTES) {
          if (!this.backlogWarned) {
            this.backlogWarned = true;
            this.warning = 'The connection cannot keep up - some audio was dropped';
          }
          return;
        }
        ws.send(buffer);
      },

      /* STOP. Before `ready` nothing has been sent, so there is nothing to
         finish: the attempt is retired and everything closed. After it, the
         source is stopped, `stop` goes out, and the socket stays open for the
         last phrase and `done`. */
      liveStop: function () {
        var self = this;
        if (this.state === 'opening') {
          this.attempt += 1;
          this.liveFinish();
          return;
        }
        if (this.state !== 'live') return;
        this.state = 'finishing';
        this.waitPush('finishing');
        if (this.session) {
          this.session.listening = false;
          this.session.finishing = true;
        }
        var ws = this.socket;
        var stopping = this.onLiveStopping ? this.onLiveStopping() : null;
        var send = function () {
          if (ws === self.socket) sendStop(ws);
        };
        Promise.resolve(stopping).then(send, send);
      },

      /* The session is over, however it ended: the source released, the
         socket closed, the screen back to START. The socket is forgotten
         before it is closed, so its own close event finds it is no longer
         this.socket and does not report a lost connection. */
      liveFinish: function () {
        if (this.onLiveRelease) this.onLiveRelease();
        var ws = this.socket;
        this.socket = null;
        if (ws && ws.readyState <= OPEN) ws.close(1000);
        this.state = 'idle';
        if (this.session) {
          this.session.listening = false;
          this.session.finishing = false;
        }
        this.waitDrop('connecting');
        this.waitDrop('finishing');
      },

      liveFail: function (text) {
        this.error = text;
        this.liveFinish();
      },

      /* The screen is going. The source is released at once. An open socket
         is told to stop - also when STOP was pressed but the device's flush
         had not finished, which would otherwise never send it - and is left
         to finish on its own: it closes on the server's `done` or `error`, or
         after a minute regardless, so the server ends the session the
         ordinary way rather than finding the client gone mid-phrase. A socket
         still connecting has nothing to finish and is closed. */
      liveAbandon: function () {
        this.attempt += 1;
        this.state = 'idle';
        if (this.session) {
          this.session.listening = false;
          this.session.finishing = false;
        }
        if (this.onLiveRelease) this.onLiveRelease();
        var ws = this.socket;
        this.socket = null;
        if (!ws) return;
        if (ws.readyState !== OPEN) {
          if (ws.readyState < OPEN) ws.close(1000);
          return;
        }
        sendStop(ws);
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
})();
