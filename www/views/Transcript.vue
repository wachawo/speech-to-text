<template>
  <div class="stt-transcript">
    <!-- What the result is of, and the three ways to take it away. The
         buttons stand apart, each its own action. -->
    <div class="d-flex align-items-center flex-wrap gap-1 mb-1">
      <stt-summary :result="result"></stt-summary>
      <span class="ms-auto"></span>
      <button type="button" class="btn btn-sm btn-secondary fw-bold btn-w85"
              :title="exportTitle('Copy the transcript as text')" :disabled="exportLocked" @click="copyText">
        <i class="fa fa-copy"></i> COPY
      </button>
      <button type="button" class="btn btn-sm btn-secondary fw-bold btn-w85"
              :title="exportTitle('Save as ' + fileStem + '.txt')" :disabled="exportLocked" @click="downloadText">
        <i class="fa fa-download"></i> TXT
      </button>
      <button type="button" class="btn btn-sm btn-secondary fw-bold btn-w85"
              :title="exportTitle('Save the server answer as ' + fileStem + '.json')" :disabled="exportLocked"
              @click="downloadJson">
        <i class="fa fa-download"></i> JSON
      </button>
    </div>

    <!-- The server fell behind in a live session and dropped audio it had
         queued: one line, kept with the transcript, its figure growing as the
         server reports more. -->
    <div v-if="result.skipped" class="stt-live-note stt-skipped">
      <i class="fa fa-triangle-exclamation" aria-hidden="true"></i>
      The server fell behind and skipped {{ $fmtSeconds(result.skipped) }} of audio
    </div>

    <!-- Who spoke when: the timeline and the list, no text. -->
    <template v-if="result.mode === 'turns'">
      <stt-turns v-if="segments.length" :turns="segments"></stt-turns>
      <div v-else class="stt-block">
        <div class="stt-block-text text-secondary">No speech found</div>
      </div>
    </template>

    <!-- One block per segment, in order. The speaker's colour is on the rule
         and the name, and the name is always printed; a contested segment
         says so in its header with a glyph and a word, and in its title. -->
    <template v-else-if="result.mode === 'speakers'">
      <div v-for="(segment, index) in segments" :key="index"
           class="stt-block" :class="$speakerClass(segment.speaker)"
           :title="segment.overlap ? overlapNote : null">
        <div class="stt-block-head">
          <span class="stt-block-who" :title="speakerTitle(segment)">{{ $speakerLabel(segment.speaker) || 'No speaker' }}</span>
          <span class="stt-block-time">{{ fmtRange(segment) }}</span>
          <span v-if="segment.overlap" class="stt-block-overlap">
            <i class="fa fa-people-arrows me-1" aria-hidden="true"></i>overlap
          </span>
        </div>
        <div class="stt-block-text">{{ segment.text || '-' }}</div>
      </div>
      <div v-if="segments.length === 0 && !waiting" class="stt-block">
        <div class="stt-block-text text-secondary">No speech recognised</div>
      </div>
    </template>

    <!-- The words alone: one block, no speakers to tell apart. A live
         session without speakers still arrives phrase by phrase, so its
         phrases are joined into the one block as they come. -->
    <div v-else-if="plainText || !waiting" class="stt-block">
      <div class="stt-block-text" v-if="plainText">{{ plainText }}</div>
      <div class="stt-block-text text-secondary" v-else>No speech recognised</div>
    </div>

    <!-- A live session between phrases. Nothing arrives while someone is
         talking - a phrase comes back after they pause - so this is what says
         the capture is working. After STOP, the last phrase is still on its
         way, and the line says that instead. -->
    <div v-if="result.listening" class="stt-live-note stt-listening">
      <i class="fa fa-ear-listen" aria-hidden="true"></i>
      Listening - each phrase appears about a second after the speaker pauses
    </div>
    <div v-else-if="result.finishing" class="stt-live-note">
      <i class="fa fa-spinner fa-pulse" aria-hidden="true"></i>
      Finishing - the last phrase is on its way
    </div>
  </div>
</template>

<script>
/* A transcript on the screen, and the ways to take it away: COPY, TXT, JSON.

   Knows nothing about where the audio came from - it is handed a result and
   draws it - so any source that ends in the same answer can put it under its
   own form. Used as:

     <stt-transcript :result="result"></stt-transcript>

   where `result` is {mode, name, language, data}: `mode` 'speakers', 'text'
   or 'turns' (who spoke when, drawn by views/Turns.vue),
   `name` the recording's file name (the downloads are saved under it),
   `language` what the request asked for ('' for the server default), and
   `data` the server's JSON as sent - JSON saves exactly that.

   A live session adds `live: true`, `listening` (between START and STOP),
   `finishing` (between STOP and the server's `done` or `error`), `seconds`
   (audio the server has received), `stem` (the name its downloads are saved
   under - a device label is no file name) and `messages` (every message the
   server sent but `progress`, which is what JSON saves), `skipped` (seconds
   of audio the server dropped when it fell behind), and its segments grow
   while it is on the screen.

   `progress` arrives once a second for as long as a session runs, and the
   only thing it changes is the audio figure in the line above the blocks.
   That line is its own small component, so the tick re-renders the line and
   not every block under it. */

/* Scripts written without spaces between words or sentences: Chinese and
   Japanese (CJK punctuation, kana, ideographs, full-width forms). Two live
   phrases meeting at one of these are joined as they are; a space there would
   be a gap no reader of the language expects. Korean is absent because it
   spaces its words, and Thai because it puts a space between sentences, which
   is what a phrase ending at a pause usually is. */
var UNSPACED = /[\u3000-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]/;

/* Live phrases as one text: a space between two, unless either side of the
   join is in an unspaced script. */
var joinPhrases = function (phrases) {
  return phrases.reduce(function (text, phrase) {
    var next = (phrase || '').trim();
    if (!next) return text;
    if (!text) return next;
    var glue = (UNSPACED.test(text.charAt(text.length - 1)) || UNSPACED.test(next.charAt(0))) ? '' : ' ';
    return text + glue + next;
  }, '');
};

/* Speaker labels are positions, and the name says so. */
var SPEAKER_NOTE = 'Numbered in the order they first speak in this recording - a position, never an identity';
var OVERLAP_NOTE = 'Another speaker was talking at the same time: this block can hold both voices, ' +
  'and the speaker named is the one whose turn covers most of it';
var NO_SPEAKER_NOTE = 'No speaker turn covered this stretch of speech';

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

/* The line above the blocks. "dialog.wav - ru - 2 speakers - transcribed in
   0.9 s"; "meeting.wav - 4 speakers - 57 turns - diarized in 3.1 s"; for a
   live session "<device> - ru - 2 speakers - 21.9 s of audio". */
var TranscriptSummary = {
  props: {
    result: { type: Object, required: true },
  },
  computed: {
    text: function () {
      var result = this.result;
      var parts = [result.name];
      if (result.language) parts.push(result.language === 'auto' ? 'language detected' : result.language);
      if (result.mode === 'speakers' || result.mode === 'turns') {
        var count = Number(result.data.speakers) || 0;
        parts.push(count + (count === 1 ? ' speaker' : ' speakers'));
      }
      if (result.mode === 'turns') {
        var turns = Array.isArray(result.data.segments) ? result.data.segments.length : 0;
        parts.push(turns + (turns === 1 ? ' turn' : ' turns'));
      }
      if (result.live) parts.push(this.$fmtSeconds(result.seconds) + ' of audio');
      else parts.push((result.mode === 'turns' ? 'diarized in ' : 'transcribed in ') + this.$fmtSeconds(result.data.elapsed));
      return parts.join(' - ');
    },
  },
  template: '<small class="text-secondary">{{ text }}</small>',
};

module.exports = {
  components: {
    'stt-summary': TranscriptSummary,
    'stt-turns': httpVueLoader('/views/Turns.vue'),
  },

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
      return joinPhrases(this.segments.map(function (segment) { return segment.text; }));
    },

    /* A live session still has phrases coming: while listening, or after
       STOP until the server's last word. The empty state waits for it. */
    waiting: function () {
      return !!(this.result.listening || this.result.finishing);
    },

    /* After STOP the last phrase is still on its way, and an export taken now
       would be missing it - or, for a short session, be empty. COPY, TXT and
       JSON wait for `done` or `error`. */
    exportLocked: function () {
      return !!this.result.finishing;
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

    /* The transcript as text - what COPY copies and TXT saves. For Speakers,
       one line per segment, and a contested one says so: the overlap mark
       has to survive into every copy of a transcript, not only the screen.
       For Turns, one line per turn: the time and the speaker, nothing else. */
    transcriptText: function () {
      var self = this;
      if (this.result.mode === 'turns') {
        return this.segments.map(function (turn) {
          return '[' + self.fmtRange(turn) + '] ' + (self.$speakerLabel(turn.speaker) || 'No speaker');
        }).join('\n') + '\n';
      }
      if (this.result.mode !== 'speakers') return this.plainText + '\n';
      return this.segments.map(function (segment) {
        var label = self.$speakerLabel(segment.speaker);
        if (segment.overlap) label += (label ? ' ' : '') + '(overlap)';
        return '[' + self.fmtRange(segment) + '] ' + (label ? label + ': ' : '') + (segment.text || '');
      }).join('\n') + '\n';
    },
  },

  methods: {
    exportTitle: function (text) {
      return this.exportLocked ? 'Waiting for the last phrase' : text;
    },

    /* Whether the page is scrolled to its end, give or take a line. */
    atBottom: function () {
      var page = document.documentElement;
      return window.innerHeight + window.scrollY >= page.scrollHeight - 48;
    },

    fmtRange: function (segment) {
      return this.$fmtStamp(segment.start) + ' - ' + this.$fmtStamp(segment.end);
    },

    speakerTitle: function (segment) {
      return this.$speakerLabel(segment.speaker) ? SPEAKER_NOTE : NO_SPEAKER_NOTE;
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
