<template>
  <div class="stt-transcript">
    <!-- What the result is of, and the three ways to take it away. The
         buttons stand apart, each its own action. -->
    <div class="d-flex align-items-center flex-wrap gap-1 mb-1">
      <small class="text-secondary">{{ summary }}</small>
      <span class="ms-auto"></span>
      <button type="button" class="btn btn-sm btn-secondary fw-bold btn-w85"
              title="Copy the transcript as text" @click="copyText">
        <i class="fa fa-copy"></i> COPY
      </button>
      <button type="button" class="btn btn-sm btn-secondary fw-bold btn-w85"
              :title="'Save as ' + fileStem + '.txt'" @click="downloadText">
        <i class="fa fa-download"></i> TXT
      </button>
      <button type="button" class="btn btn-sm btn-secondary fw-bold btn-w85"
              :title="'Save the server answer as ' + fileStem + '.json'" @click="downloadJson">
        <i class="fa fa-download"></i> JSON
      </button>
    </div>

    <!-- One block per segment, in order. The speaker's colour is on the rule
         and the name, and the name is always printed; a contested segment
         says so in its header with a glyph and a word, and in its title. -->
    <template v-if="result.mode === 'speakers'">
      <div v-for="(segment, index) in segments" :key="index"
           class="stt-block" :class="speakerClass(segment)"
           :title="segment.overlap ? overlapNote : null">
        <div class="stt-block-head">
          <span class="stt-block-who" :title="speakerTitle(segment)">{{ speakerLabel(segment) || 'No speaker' }}</span>
          <span class="stt-block-time">{{ fmtRange(segment) }}</span>
          <span v-if="segment.overlap" class="stt-block-overlap">
            <i class="fa fa-people-arrows me-1" aria-hidden="true"></i>overlap
          </span>
        </div>
        <div class="stt-block-text">{{ segment.text || '-' }}</div>
      </div>
      <div v-if="segments.length === 0 && !result.listening" class="stt-block">
        <div class="stt-block-text text-secondary">No speech recognised</div>
      </div>
    </template>

    <!-- The words alone: one block, no speakers to tell apart. A live
         session without speakers still arrives phrase by phrase, so its
         phrases are joined into the one block as they come. -->
    <div v-else-if="plainText || !result.listening" class="stt-block">
      <div class="stt-block-text" v-if="plainText">{{ plainText }}</div>
      <div class="stt-block-text text-secondary" v-else>No speech recognised</div>
    </div>

    <!-- A live session between phrases. Nothing arrives while someone is
         talking - a phrase comes back after they pause - so this is what says
         the capture is working. -->
    <div v-if="result.listening" class="stt-listening">
      <i class="fa fa-ear-listen" aria-hidden="true"></i>
      Listening - each phrase appears about a second after the speaker pauses
    </div>
  </div>
</template>

<script>
/* A transcript on the screen, and the ways to take it away: COPY, TXT, JSON.

   Knows nothing about where the audio came from - it is handed a result and
   draws it - so any source that ends in the same answer can put it under its
   own form. Used as:

     <stt-transcript :result="result"></stt-transcript>

   where `result` is {mode, name, model, language, data}: `mode` 'speakers'
   or 'text', `name` the recording's file name (the downloads are saved under
   it), `model` the id of the model that transcribed ('' when the server did
   not say), `language` what the request asked for ('' for the server
   default), and
   `data` the server's JSON as sent - JSON saves exactly that.

   A live session adds `live: true`, `listening` (between START and STOP),
   `seconds` (audio the server has received), `stem` (the name its downloads
   are saved under - a device label is no file name) and `messages` (every
   message the server sent but `progress`, which is what JSON saves), and its
   segments grow while it is on the screen.
*/

/* Speaker labels are positions, and the name says so. */
var SPEAKER_NOTE = 'Numbered in the order they first speak in this recording - a position, never an identity';
var OVERLAP_NOTE = 'Another speaker was talking at the same time: this block can hold both voices, ' +
  'and the speaker named is the one whose turn covers most of it';
var NO_SPEAKER_NOTE = 'No speaker turn covered this stretch of speech';

/* How many speaker inks the palette has (--stt-speaker-1..8), which is also
   the diarizer's ceiling. A ninth would start the colours over; the name
   still tells them apart. */
var SPEAKER_INKS = 8;

/* The clipboard the old way, for a page the browser does not trust with
   navigator.clipboard - plain http from another host is the common case for
   a UI like this one. Answers whether the copy went through. */
var copyByTextarea = function (text) {
  if (typeof document === 'undefined' || !document.body) return false;
  var box = document.createElement('textarea');
  box.value = text;
  box.setAttribute('readonly', '');
  box.style.position = 'fixed';
  box.style.opacity = '0';
  document.body.appendChild(box);
  box.select();
  var copied;
  try {
    copied = document.execCommand('copy');
  } catch (err) {
    copied = false;
  }
  document.body.removeChild(box);
  return copied;
};

module.exports = {
  props: {
    result: { type: Object, required: true },
  },

  data: function () {
    return { overlapNote: OVERLAP_NOTE };
  },

  watch: {
    /* A phrase arrived in a live session. The page follows it only if the
       reader was already at the bottom: someone who has scrolled up to read
       an earlier phrase must not be pulled away from it by the next one. The
       check runs here, before the new block is drawn - afterwards the page is
       taller and nobody is at the bottom any more. */
    segmentCount: function () {
      if (!this.result.live || !this.atBottom()) return;
      this.$nextTick(function () {
        window.scrollTo(0, document.documentElement.scrollHeight);
      });
    },
  },

  created: function () {
    // Kept off `data`: nothing renders from it.
    this.downloadUrl = '';
  },

  beforeDestroy: function () {
    this.setDownloadUrl('');
  },

  computed: {
    segmentCount: function () {
      return this.segments.length;
    },

    /* The text of a Text result: the server's `text` for a file, the phrases
       so far for a live session, which sends no text of its own. */
    plainText: function () {
      if (!this.result.live) return this.result.data.text || '';
      return this.segments.map(function (segment) { return segment.text || ''; }).join(' ').trim();
    },

    segments: function () {
      var data = this.result.data;
      return (data && Array.isArray(data.segments)) ? data.segments : [];
    },

    /* The file name the downloads are saved under: the recording's own,
       without its extension. */
    fileStem: function () {
      if (this.result.stem) return this.result.stem;
      var name = this.result.name || '';
      return name.replace(/\.[^.]*$/, '') || 'transcript';
    },

    /* "dialog.wav - ru - 2 speakers - transcribed in 0.9 s", or for a live
       session "<device> - ru - 2 speakers - 21.9 s of audio". */
    summary: function () {
      var result = this.result;
      var parts = [result.name];
      if (result.model) parts.push(result.model);
      if (result.language) parts.push(result.language === 'auto' ? 'language detected' : result.language);
      if (result.mode === 'speakers') {
        var count = Number(result.data.speakers) || 0;
        parts.push(count + (count === 1 ? ' speaker' : ' speakers'));
      }
      if (result.live) parts.push(this.$fmtSeconds(result.seconds) + ' of audio');
      else parts.push('transcribed in ' + this.$fmtSeconds(result.data.elapsed));
      return parts.join(' - ');
    },

    /* The transcript as text - what COPY copies and TXT saves. For Speakers,
       one line per segment, and a contested one says so: the overlap mark
       has to survive into every copy of a transcript, not only the screen. */
    transcriptText: function () {
      var self = this;
      if (this.result.mode !== 'speakers') return this.plainText + '\n';
      return this.segments.map(function (segment) {
        var label = self.speakerLabel(segment);
        if (segment.overlap) label += (label ? ' ' : '') + '(overlap)';
        return '[' + self.fmtRange(segment) + '] ' + (label ? label + ': ' : '') + (segment.text || '');
      }).join('\n') + '\n';
    },
  },

  methods: {
    /* Whether the page is scrolled to its end, give or take a line. */
    atBottom: function () {
      var page = document.documentElement;
      return window.innerHeight + window.scrollY >= page.scrollHeight - 48;
    },

    fmtRange: function (segment) {
      return this.$fmtStamp(segment.start) + ' - ' + this.$fmtStamp(segment.end);
    },

    /* The server's speaker number, or null for a segment no turn covered. */
    speakerIndex: function (segment) {
      var speaker = segment.speaker;
      if (speaker === null || speaker === undefined || speaker === '') return null;
      var number = Number(speaker);
      return isFinite(number) && number >= 0 ? Math.floor(number) : null;
    },

    /* "Speaker 1" for speaker 0: the server counts from zero, people from one.
       '' for a segment no turn covered. */
    speakerLabel: function (segment) {
      var index = this.speakerIndex(segment);
      return index === null ? '' : 'Speaker ' + (index + 1);
    },

    /* The ink follows the number, and the number is arrival order, so the
       first voice in a recording is always the first colour. */
    speakerClass: function (segment) {
      var index = this.speakerIndex(segment);
      return index === null ? 'stt-speaker-none' : 'stt-speaker-' + ((index % SPEAKER_INKS) + 1);
    },

    speakerTitle: function (segment) {
      return this.speakerLabel(segment) ? SPEAKER_NOTE : NO_SPEAKER_NOTE;
    },

    /* navigator.clipboard first, the textarea trick where the browser has
       none or refuses; a toast either way, because a COPY that says nothing
       is a COPY the operator presses three times. */
    copyText: function () {
      var self = this;
      var text = this.transcriptText.replace(/\n$/, '');
      var done = function () {
        self.$store.dispatch('push_toast', { level: 'success', message: 'Copied', ttl: 3000 });
      };
      var fallback = function () {
        if (copyByTextarea(text)) return done();
        self.$store.dispatch('push_toast', {
          level: 'danger',
          message: 'This browser would not copy - save TXT instead.',
        });
      };
      if (typeof navigator !== 'undefined' && navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, fallback);
      } else {
        fallback();
      }
    },

    downloadText: function () {
      this.saveFile(this.fileStem + '.txt', this.transcriptText, 'text/plain;charset=utf-8');
    },

    /* What the server said, as it said it: the answer to the upload, or
       every message of a live session but the progress ticks. */
    downloadJson: function () {
      var json = JSON.stringify(this.result.messages || this.result.data, null, 2) + '\n';
      this.saveFile(this.fileStem + '.json', json, 'application/json;charset=utf-8');
    },

    /* The text as a Blob, handed to the browser as a download through a link
       clicked for the operator. The object URL is kept until the next
       download or the end of the component: revoked at once, the save the
       browser has only just started would find nothing behind it. */
    saveFile: function (name, content, type) {
      this.setDownloadUrl(URL.createObjectURL(new Blob([content], { type: type })));
      var link = document.createElement('a');
      link.href = this.downloadUrl;
      link.download = name;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    },

    setDownloadUrl: function (url) {
      if (this.downloadUrl) URL.revokeObjectURL(this.downloadUrl);
      this.downloadUrl = url;
    },
  },
};
</script>
