/* SttCapture - live audio from a device, as 16 kHz mono PCM16 frames, for the
   transcribe screen's DEVICE source.

   A plain script rather than a module, like everything else under /js: there
   is no build step, and index.html loads it ahead of app.js so the screens can
   assume `window.SttCapture` exists.

   Three jobs, kept apart:
   - finding the inputs (`listInputs`) and opening one - a device through
     getUserMedia, or the sound of a tab or screen through getDisplayMedia;
   - turning an open stream into frames (`create`): an AudioWorklet
     downsamples to 16 kHz mono, and this side converts to signed 16-bit
     little-endian and hands over one frame per 100 ms;
   - nothing about the server. Where the frames go is the caller's business.

   The pure parts - the Int16 conversion and the level - are exposed on the
   object as well, so they can be checked from node without a browser. */
(function () {
  'use strict';

  // How long stop() waits for the worklet to hand over what it still holds.
  // The answer normally takes one message round trip; this is only for a
  // worklet that never answers, so a STOP cannot hang on it.
  var FLUSH_TIMEOUT_MS = 500;

  /* The worklet, written as a function so it is real code here - read, and
     checked by the same syntax pass as the rest of this file - and shipped as
     its own source text through a Blob URL, so the page serves no second file
     for it. It is never called on the page: `sampleRate`,
     `AudioWorkletProcessor` and `registerProcessor` exist only inside the
     worklet's own scope.

     It resamples whatever rate the device runs at to 16 kHz, in either
     direction, after mixing every channel into one (a tab's audio is usually
     stereo and the server takes mono):
     - Down (44.1 kHz, 48 kHz): each output sample is the average of the
       source samples it spans - a box filter, which is enough for speech going
       to a recogniser: the aliasing it lets through sits above the band a
       voice occupies. The span is fractional at 44.1 kHz (2.75625 source
       samples per output sample), so the position carries the remainder from
       one output sample to the next instead of drifting.
     - Up (8 kHz, 11.025 kHz - a telephone headset, an old USB dongle):
       averaging can only ever emit one output per input, which would send
       8 kHz audio labelled 16 kHz, so it is linear interpolation between each
       pair of neighbouring source samples instead.
     - 16 kHz itself takes the down path with a span of exactly one, which
       passes every sample through unchanged.

     Output is posted in blocks of BLOCK samples, transferred rather than
     copied. 'flush' posts whatever is left and then 'flushed'; a port keeps
     its order, so every block posted before 'flushed' arrives before it. */
  var workletMain = function () {
    // What the server takes: /api/stream wants 16 kHz mono PCM16.
    var OUT_RATE = 16000;
    // One block is 100 ms: 1600 samples, 3200 bytes once converted. Small
    // enough that the server sees speech about as soon as it is said, large
    // enough that a session is ten messages a second rather than hundreds.
    var BLOCK = 1600;

    class SttResampler extends AudioWorkletProcessor {
      constructor() {
        super();
        // Source samples per output sample: 3 at 48 kHz, 0.5 at 8 kHz.
        this.step = sampleRate / OUT_RATE;
        this.down = this.step >= 1;
        // Down: the running average of the current output sample's span.
        this.position = 0;
        this.sum = 0;
        this.count = 0;
        // Up: the previous source sample, and where the next output sample
        // falls after it, in source samples.
        this.previous = null;
        this.offset = 0;
        this.block = new Float32Array(BLOCK);
        this.filled = 0;
        this.port.onmessage = (event) => {
          if (event.data !== 'flush') return;
          this.post();
          this.port.postMessage('flushed');
        };
      }

      emit(value) {
        this.block[this.filled] = value;
        this.filled += 1;
        if (this.filled === BLOCK) this.post();
      }

      post() {
        if (!this.filled) return;
        var out = this.block.slice(0, this.filled);
        this.filled = 0;
        this.port.postMessage(out, [out.buffer]);
      }

      average(sample) {
        this.sum += sample;
        this.count += 1;
        this.position += 1;
        if (this.position < this.step) return;
        this.position -= this.step;
        this.emit(this.sum / this.count);
        this.sum = 0;
        this.count = 0;
      }

      interpolate(sample) {
        if (this.previous === null) {
          this.previous = sample;
          return;
        }
        while (this.offset < 1) {
          this.emit(this.previous + (sample - this.previous) * this.offset);
          this.offset += this.step;
        }
        this.offset -= 1;
        this.previous = sample;
      }

      process(inputs) {
        var input = inputs[0];
        if (!input || !input.length) return true;
        var channels = input.length;
        var frames = input[0].length;
        for (var i = 0; i < frames; i++) {
          var sample = 0;
          for (var c = 0; c < channels; c++) sample += input[c][i];
          sample /= channels;
          if (this.down) this.average(sample);
          else this.interpolate(sample);
        }
        return true;
      }
    }

    registerProcessor('stt-resampler', SttResampler);
  };

  var WORKLET_SOURCE = '(' + workletMain.toString() + ')();';

  /* Float samples in -1..1 to signed 16-bit little-endian PCM, as an
     ArrayBuffer ready for a websocket. Clamped first: a sample just outside
     the unit range would otherwise wrap to the opposite sign, and the loudest
     syllable would reach the server as a click. Written through a DataView so
     the byte order is the one the server expects whatever the machine's. */
  var toInt16 = function (samples) {
    var buffer = new ArrayBuffer(samples.length * 2);
    var view = new DataView(buffer);
    for (var i = 0; i < samples.length; i++) {
      var sample = Math.max(-1, Math.min(1, samples[i]));
      view.setInt16(i * 2, sample < 0 ? sample * 0x8000 : sample * 0x7FFF, true);
    }
    return buffer;
  };

  /* The root mean square of a block: what the level meter shows, so the
     meter moves with what the server is being sent rather than with the raw
     device. */
  var rms = function (samples) {
    if (!samples.length) return 0;
    var total = 0;
    for (var i = 0; i < samples.length; i++) total += samples[i] * samples[i];
    return Math.sqrt(total / samples.length);
  };

  /* Every track of a stream stopped - the device light goes out - and, when
     given, a listener taken off each first, so a track's own `ended` does not
     report a stop this side asked for. The one place tracks are stopped, for
     this file and for the DEVICE source. */
  var stopTracks = function (stream, endedListener) {
    if (!stream) return;
    stream.getTracks().forEach(function (track) {
      if (endedListener) track.removeEventListener('ended', endedListener);
      track.stop();
    });
  };

  var mediaDevices = function () {
    return (typeof navigator !== 'undefined' && navigator.mediaDevices) || null;
  };

  /* Whether this page can capture at all. Audio devices exist only on a
     secure page - https, or http on localhost - and the worklet is what the
     frames come from, so a browser without either gets a form that says so
     instead of one that can only fail. */
  var supported = function () {
    if (typeof window === 'undefined' || !window.isSecureContext) return false;
    var devices = mediaDevices();
    return !!(devices && devices.getUserMedia && devices.enumerateDevices &&
      window.AudioWorkletNode && (window.AudioContext || window.webkitAudioContext));
  };

  /* Whether this is a Chromium browser - Chrome, Edge, Opera and the rest of
     the family. userAgentData names the engine outright where it exists; the
     user-agent string is the fallback for the versions that predate it, and
     it is read for the three brands rather than for "Chrome" alone, which
     other engines put in their strings for compatibility. */
  var isChromium = function () {
    if (typeof navigator === 'undefined') return false;
    var data = navigator.userAgentData;
    if (data && Array.isArray(data.brands)) {
      return data.brands.some(function (entry) { return /Chromium/i.test(entry.brand); });
    }
    var agent = navigator.userAgent || '';
    return /(Chrome|Chromium|Edg|OPR)\/\d/.test(agent) && !/Firefox|FxiOS/.test(agent);
  };

  /* Whether the page can ask for a tab's or the screen's sound. Chromium
     only: Firefox and Safari have getDisplayMedia too, but it hands back
     video alone, so offering the entry there would be offering a failure.
     Desktop only as well; a phone has no getDisplayMedia at all. */
  var displaySupported = function () {
    var devices = mediaDevices();
    return !!(supported() && devices.getDisplayMedia && isChromium());
  };

  /* The audio inputs, as {id, label}. Until the page has been allowed a
     microphone the browser hides the names - and, in Chrome, the ids - so an
     unnamed entry is numbered, and the id '' is the browser's own default. A
     headset's microphone is one of these; so, on Linux, are the "Monitor of"
     sources, which carry whatever is playing through the speakers. `named` is
     whether the browser gave real names, which is also whether access has been
     granted. */
  var listInputs = function () {
    var devices = mediaDevices();
    if (!devices || !devices.enumerateDevices) return Promise.resolve({ inputs: [], named: false });
    return devices.enumerateDevices().then(function (all) {
      var seen = {};
      var inputs = [];
      var named = false;
      all.forEach(function (device) {
        if (device.kind !== 'audioinput' || seen[device.deviceId]) return;
        seen[device.deviceId] = true;
        if (device.label) named = true;
        var label = device.label ||
          (device.deviceId ? 'Microphone ' + (inputs.length + 1) : 'Default microphone');
        inputs.push({ id: device.deviceId, label: label });
      });
      if (!inputs.length) inputs.push({ id: '', label: 'Default microphone' });
      return { inputs: inputs, named: named };
    });
  };

  /* Ask for a microphone and put it straight back: the grant is what makes
     the browser name its devices, and nothing is recorded. */
  var askPermission = function () {
    return mediaDevices().getUserMedia({ audio: true }).then(function (stream) {
      stopTracks(stream);
    });
  };

  /* One input device, raw. Echo cancellation and noise suppression are off:
     both are built for a call, and both damage exactly what this is for - a
     loopback of what the speakers play, or a second voice in the room, which
     they treat as noise to remove. Gain control stays on, so a quiet
     microphone still reaches the level the recogniser needs. */
  var openDevice = function (id) {
    var audio = { echoCancellation: false, noiseSuppression: false, autoGainControl: true };
    if (id) audio.deviceId = { exact: id };
    return mediaDevices().getUserMedia({ audio: audio });
  };

  /* The sound of a browser tab, or of the whole system where the operating
     system allows it (Windows, ChromeOS). Chrome only offers tab capture
     together with video, so video is asked for and dropped at once. Whether
     audio comes back is the user's choice in the browser's picker, and a
     share without it rejects here as NoAudioShared, with everything it opened
     closed again. */
  var openDisplay = function () {
    var options = { audio: true, video: true };
    return mediaDevices().getDisplayMedia(options).then(function (stream) {
      stream.getVideoTracks().forEach(function (track) {
        track.stop();
        stream.removeTrack(track);
      });
      if (stream.getAudioTracks().length) return stream;
      stopTracks(stream);
      var error = new Error('No audio was shared');
      error.name = 'NoAudioShared';
      throw error;
    });
  };

  /* One capture of an open stream. `start()` resolves once frames flow;
     `stop()` flushes the last partial frame to onFrame, closes everything and
     resolves; `release()` closes everything at once and delivers nothing, for
     a screen that is being left. The stream is the caller's until start() -
     after it, this owns the tracks and stops them.

     onFrame(buffer, level) - an ArrayBuffer of PCM16 and the RMS of it;
     onEnded() - the device went away (unplugged, access revoked, "Stop
     sharing" pressed in the browser bar). */
  var create = function (stream, options) {
    var settings = options || {};
    var onFrame = typeof settings.onFrame === 'function' ? settings.onFrame : function () {};
    var onEnded = typeof settings.onEnded === 'function' ? settings.onEnded : function () {};

    var context = null;
    var source = null;
    var node = null;
    var moduleUrl = '';
    var flushed = null;
    // Set by release(). The worklet module loads asynchronously, and a screen
    // left while it loads must not find a capture started behind it.
    var released = false;

    var capture = {};

    /* Safe to call twice: stop() tears down after its flush, and a release()
       that follows - the screen being left - must find nothing left to close
       rather than a closed context to close again. */
    var teardown = function () {
      if (source) {
        source.disconnect();
        source = null;
      }
      stopTracks(stream, onTrackEnded);
      stream = null;
      if (node) {
        node.port.onmessage = null;
        node.disconnect();
        node = null;
      }
      if (context) {
        try { context.close(); } catch (err) { /* already closed */ }
        context = null;
      }
      if (moduleUrl) {
        URL.revokeObjectURL(moduleUrl);
        moduleUrl = '';
      }
    };

    var onTrackEnded = function () {
      if (!stream) return;
      onEnded();
    };

    var onMessage = function (event) {
      if (event.data === 'flushed') {
        if (flushed) flushed();
        return;
      }
      if (!(event.data instanceof Float32Array)) return;
      onFrame(toInt16(event.data), rms(event.data));
    };

    /* At the device's own rate. Firefox refuses to connect a stream into a
       context running at another rate, and Chrome resamples at the source
       anyway, so the rate the track reports is the one asked for; a track
       that reports none, or a browser that refuses the option, gets the
       default context, which is then the rate the stream already runs at. */
    var openContext = function () {
      var Context = window.AudioContext || window.webkitAudioContext;
      var track = stream.getAudioTracks()[0];
      var trackSettings = (track && track.getSettings) ? track.getSettings() : {};
      if (trackSettings.sampleRate) {
        try {
          return new Context({ sampleRate: trackSettings.sampleRate });
        } catch (err) {
          // Falls through to the default rate.
        }
      }
      return new Context();
    };

    capture.start = function () {
      try {
        context = openContext();
        moduleUrl = URL.createObjectURL(new Blob([WORKLET_SOURCE], { type: 'application/javascript' }));
      } catch (err) {
        teardown();
        return Promise.reject(err);
      }
      return context.audioWorklet.addModule(moduleUrl).then(function () {
        if (released) return;
        source = context.createMediaStreamSource(stream);
        node = new AudioWorkletNode(context, 'stt-resampler', { numberOfOutputs: 1, outputChannelCount: [1] });
        node.port.onmessage = onMessage;
        source.connect(node);
        // Nothing is heard: the worklet writes no output. Wired to the
        // destination anyway, because a node the graph does not pull is a node
        // a browser is free not to run.
        node.connect(context.destination);
        // A track can end before anyone listens for it - the device unplugged,
        // or "Stop sharing" pressed, while the socket was still connecting.
        // Its `ended` event is gone by then, so the state is read as well;
        // otherwise the capture would run on, sending the silence an ended
        // track produces, as if it were live.
        var tracks = stream.getAudioTracks();
        tracks.forEach(function (track) {
          track.addEventListener('ended', onTrackEnded);
        });
        var alreadyEnded = !tracks.length || tracks.some(function (track) { return track.readyState === 'ended'; });
        // The context may have been created without the click that asked for
        // it still counting as a gesture; resuming is harmless when it runs.
        return context.resume().then(function () {
          if (alreadyEnded && !released) onTrackEnded();
        });
      }).catch(function (err) {
        // A capture stopped or released while it was starting has nothing to
        // report: the error is its own teardown pulling the context away.
        if (released) return;
        teardown();
        throw err;
      });
    };

    /* The input is cut first, so nothing recorded after STOP reaches the
       server - not even the silence a stopped track keeps producing - and
       then the worklet is asked for what it still holds. */
    capture.stop = function () {
      // Still starting - the worklet module loading. Nothing has been captured,
      // so there is nothing to flush; the start in flight must find the
      // capture released rather than build a graph on a closed context.
      if (!node) {
        released = true;
        teardown();
        return Promise.resolve();
      }
      if (source) {
        source.disconnect();
        source = null;
      }
      stopTracks(stream, onTrackEnded);
      return new Promise(function (resolve) {
        var finish = function () {
          clearTimeout(timer);
          flushed = null;
          teardown();
          resolve();
        };
        var timer = setTimeout(finish, FLUSH_TIMEOUT_MS);
        flushed = finish;
        node.port.postMessage('flush');
      });
    };

    /* A stop() still waiting on its flush is finished here rather than left
       pending: its caller is waiting on the promise to send the server its
       last message. */
    capture.release = function () {
      released = true;
      if (flushed) flushed();
      else teardown();
    };

    return capture;
  };

  window.SttCapture = {
    supported: supported,
    displaySupported: displaySupported,
    isChromium: isChromium,
    listInputs: listInputs,
    stopTracks: stopTracks,
    askPermission: askPermission,
    openDevice: openDevice,
    openDisplay: openDisplay,
    create: create,
    toInt16: toInt16,
    rms: rms,
  };
})();
