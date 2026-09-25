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

  // What the server takes: /api/stream wants 16 kHz mono PCM16.
  var TARGET_RATE = 16000;

  // One frame is 100 ms: 1600 samples, 3200 bytes. Small enough that the
  // server sees speech about as soon as it is said, large enough that a
  // session is ten messages a second rather than hundreds.
  var FRAME_SAMPLES = 1600;

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

     Each output sample is the average of the source samples it spans - a box
     filter, which is enough for speech going to a recogniser: the aliasing it
     lets through sits above the band a voice occupies. The span is fractional
     at 44.1 kHz (2.75625 source samples per output sample), so the position
     carries the remainder from one output sample to the next instead of
     drifting. Every channel is mixed into one first: a tab's audio is usually
     stereo and the server takes mono.

     Output is posted in blocks of FRAME_SAMPLES, transferred rather than
     copied. 'flush' posts whatever is left and then 'flushed'; a port keeps
     its order, so every block posted before 'flushed' arrives before it. */
  var workletMain = function () {
    var OUT_RATE = 16000;
    var BLOCK = 1600;

    class SttDownsampler extends AudioWorkletProcessor {
      constructor() {
        super();
        this.step = sampleRate / OUT_RATE;
        this.position = 0;
        this.sum = 0;
        this.count = 0;
        this.block = new Float32Array(BLOCK);
        this.filled = 0;
        this.port.onmessage = (event) => {
          if (event.data !== 'flush') return;
          this.post();
          this.port.postMessage('flushed');
        };
      }

      post() {
        if (!this.filled) return;
        var out = this.block.slice(0, this.filled);
        this.filled = 0;
        this.port.postMessage(out, [out.buffer]);
      }

      process(inputs) {
        var input = inputs[0];
        if (!input || !input.length) return true;
        var channels = input.length;
        var frames = input[0].length;
        for (var i = 0; i < frames; i++) {
          var sample = 0;
          for (var c = 0; c < channels; c++) sample += input[c][i];
          this.sum += sample / channels;
          this.count += 1;
          this.position += 1;
          if (this.position >= this.step) {
            this.position -= this.step;
            this.block[this.filled] = this.sum / this.count;
            this.filled += 1;
            this.sum = 0;
            this.count = 0;
            if (this.filled === BLOCK) this.post();
          }
        }
        return true;
      }
    }

    registerProcessor('stt-downsampler', SttDownsampler);
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

  /* Whether the page can ask for a tab's or the screen's sound. Desktop
     browsers only; a phone has no getDisplayMedia. */
  var displaySupported = function () {
    var devices = mediaDevices();
    return !!(supported() && devices.getDisplayMedia);
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
      stream.getTracks().forEach(function (track) { track.stop(); });
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
     audio comes back is the user's choice in the browser's picker - "Share
     audio" - and a share without it rejects here as NoAudioShared, with
     everything it opened closed again. */
  var openDisplay = function () {
    var options = { audio: true, video: true };
    return mediaDevices().getDisplayMedia(options).then(function (stream) {
      stream.getVideoTracks().forEach(function (track) {
        track.stop();
        stream.removeTrack(track);
      });
      if (stream.getAudioTracks().length) return stream;
      stream.getTracks().forEach(function (track) { track.stop(); });
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

    var stopTracks = function () {
      if (!stream) return;
      stream.getTracks().forEach(function (track) {
        track.removeEventListener('ended', onTrackEnded);
        track.stop();
      });
    };

    /* Safe to call twice: stop() tears down after its flush, and a release()
       that follows - the screen being left - must find nothing left to close
       rather than a closed context to close again. */
    var teardown = function () {
      if (source) {
        source.disconnect();
        source = null;
      }
      stopTracks();
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
        node = new AudioWorkletNode(context, 'stt-downsampler', { numberOfOutputs: 1, outputChannelCount: [1] });
        node.port.onmessage = onMessage;
        source.connect(node);
        // Nothing is heard: the worklet writes no output. Wired to the
        // destination anyway, because a node the graph does not pull is a node
        // a browser is free not to run.
        node.connect(context.destination);
        stream.getAudioTracks().forEach(function (track) {
          track.addEventListener('ended', onTrackEnded);
        });
        // The context may have been created without the click that asked for
        // it still counting as a gesture; resuming is harmless when it runs.
        return context.resume();
      }).catch(function (err) {
        teardown();
        throw err;
      });
    };

    /* The input is cut first, so nothing recorded after STOP reaches the
       server - not even the silence a stopped track keeps producing - and
       then the worklet is asked for what it still holds. */
    capture.stop = function () {
      if (!node) {
        teardown();
        return Promise.resolve();
      }
      if (source) {
        source.disconnect();
        source = null;
      }
      stopTracks();
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
    TARGET_RATE: TARGET_RATE,
    FRAME_SAMPLES: FRAME_SAMPLES,
    supported: supported,
    displaySupported: displaySupported,
    listInputs: listInputs,
    askPermission: askPermission,
    openDevice: openDevice,
    openDisplay: openDisplay,
    create: create,
    toInt16: toInt16,
    rms: rms,
  };
})();
