<template>
  <div class="stt-turns">
    <!-- One lane per speaker, in arrival order, each turn a bar placed by
         time. Two voices at once are two bars at the same place in two
         lanes, and the strip under the lanes marks exactly those stretches,
         hatched rather than coloured so it is never read as a ninth
         speaker. -->
    <div class="stt-timeline">
      <div v-for="lane in lanes" :key="lane.key" class="stt-lane" :class="lane.cls">
        <div class="stt-lane-name" :title="speakerNote">{{ lane.label }}</div>
        <div class="stt-lane-track">
          <span v-for="bar in lane.bars" :key="bar.key" class="stt-bar"
                :style="{ left: bar.left, width: bar.width }" :title="bar.title"></span>
        </div>
      </div>
      <div v-if="overlaps.length" class="stt-lane stt-lane-overlap">
        <div class="stt-lane-name" :title="overlapNote">Overlap</div>
        <div class="stt-lane-track">
          <span v-for="bar in overlaps" :key="bar.key" class="stt-bar"
                :style="{ left: bar.left, width: bar.width }" :title="bar.title"></span>
        </div>
      </div>
      <div class="stt-lane stt-axis-row" aria-hidden="true">
        <div></div>
        <div class="stt-axis">
          <span v-for="tick in ticks" :key="tick.key" class="stt-tick" :style="{ left: tick.left }">{{ tick.label }}</span>
        </div>
      </div>
    </div>

    <!-- The same turns as a list, in time order: what the timeline shows
         to the eye, here to read and to find. -->
    <div class="stt-turn-list">
      <div v-for="item in items" :key="item.key" class="stt-turn-item" :class="item.cls"
           :title="item.overlap ? overlapNote : null">
        <span class="stt-block-time">{{ item.range }}</span>
        <span class="stt-block-who">{{ item.label }}</span>
        <i v-if="item.overlap" class="fa fa-people-arrows stt-block-overlap" aria-hidden="true"></i>
      </div>
    </div>
  </div>
</template>

<script>
/* Who spoke when, drawn: the answer to POST /api/diarize - turns of
   {speaker, start, end} and no text - as a timeline and a list. Used by the
   transcript for a Turns result:

     <stt-turns :turns="result.data.segments"></stt-turns>

   Positions are percentages of the recording's length - the end of its last
   turn - so the timeline fills whatever width it is given and needs no
   measuring. */

var SPEAKER_NOTE = 'Numbered in the order they first speak in this recording - a position, never an identity';
var OVERLAP_NOTE = 'More than one speaker was talking at the same time';

/* The axis steps, in seconds: the first that puts no more than eight ticks
   on the recording is the one used, so a 20-second clip is marked every five
   seconds and an hour-long meeting every ten minutes. */
var TICK_STEPS = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200];
var MAX_TICKS = 8;

var percent = function (value) {
  return (Math.round(value * 1000) / 1000) + '%';
};

module.exports = {
  props: {
    turns: { type: Array, required: true },
  },

  data: function () {
    return { speakerNote: SPEAKER_NOTE, overlapNote: OVERLAP_NOTE };
  },

  computed: {
    /* The turns with usable times, in time order. */
    ordered: function () {
      return this.turns.filter(function (turn) {
        return isFinite(Number(turn.start)) && isFinite(Number(turn.end)) && Number(turn.end) >= Number(turn.start);
      }).map(function (turn, index) {
        return { speaker: turn.speaker, start: Number(turn.start), end: Number(turn.end), key: index };
      }).sort(function (a, b) { return a.start - b.start; });
    },

    /* The length the timeline spans: the last turn's end, never zero. */
    total: function () {
      var end = this.ordered.reduce(function (latest, turn) { return Math.max(latest, turn.end); }, 0);
      return end > 0 ? end : 1;
    },

    lanes: function () {
      var self = this;
      var bySpeaker = {};
      this.ordered.forEach(function (turn) {
        var key = turn.speaker === null || turn.speaker === undefined ? 'none' : String(turn.speaker);
        if (!bySpeaker[key]) bySpeaker[key] = { speaker: turn.speaker, turns: [] };
        bySpeaker[key].turns.push(turn);
      });
      return Object.keys(bySpeaker).sort(function (a, b) {
        if (a === 'none') return 1;
        if (b === 'none') return -1;
        return Number(a) - Number(b);
      }).map(function (key) {
        var lane = bySpeaker[key];
        var label = self.$speakerLabel(lane.speaker) || 'No speaker';
        return {
          key: key,
          label: label,
          cls: self.$speakerClass(lane.speaker),
          bars: lane.turns.map(function (turn) { return self.bar(turn, label); }),
        };
      });
    },

    /* The stretches where two or more speakers talk at once, found in one
       pass over the turns' edges: at equal times an end is taken before a
       start, so two turns that merely touch are not an overlap. */
    overlaps: function () {
      var self = this;
      var edges = [];
      this.ordered.forEach(function (turn) {
        edges.push({ at: turn.start, step: 1, speaker: turn.speaker });
        edges.push({ at: turn.end, step: -1, speaker: turn.speaker });
      });
      edges.sort(function (a, b) { return a.at - b.at || a.step - b.step; });
      var active = {};
      var speaking = 0;
      var since = null;
      var found = [];
      edges.forEach(function (edge) {
        var key = String(edge.speaker);
        var before = active[key] || 0;
        active[key] = before + edge.step;
        if (before === 0 && edge.step > 0) speaking += 1;
        if (before === 1 && edge.step < 0) speaking -= 1;
        if (speaking >= 2 && since === null) since = edge.at;
        if (speaking < 2 && since !== null) {
          if (edge.at > since) found.push({ start: since, end: edge.at, key: found.length });
          since = null;
        }
      });
      return found.map(function (stretch) { return self.bar(stretch, 'Overlap'); });
    },

    /* Which turns share time with another speaker's: sorted by start, each
       turn is compared only with the ones that begin before it ends. */
    overlapping: function () {
      var marked = {};
      var list = this.ordered;
      for (var i = 0; i < list.length; i++) {
        for (var j = i + 1; j < list.length && list[j].start < list[i].end; j++) {
          if (list[j].speaker !== list[i].speaker) {
            marked[list[i].key] = true;
            marked[list[j].key] = true;
          }
        }
      }
      return marked;
    },

    items: function () {
      var self = this;
      return this.ordered.map(function (turn) {
        return {
          key: turn.key,
          range: self.fmtRange(turn),
          label: self.$speakerLabel(turn.speaker) || 'No speaker',
          cls: self.$speakerClass(turn.speaker),
          overlap: !!self.overlapping[turn.key],
        };
      });
    },

    ticks: function () {
      var total = this.total;
      var step = TICK_STEPS.filter(function (candidate) { return total / candidate <= MAX_TICKS; })[0] ||
        TICK_STEPS[TICK_STEPS.length - 1];
      var ticks = [];
      for (var at = 0; at <= total; at += step) {
        ticks.push({ key: at, left: percent(at / total * 100), label: this.$fmtClock(at) });
      }
      return ticks;
    },
  },

  methods: {
    fmtRange: function (span) {
      return this.$fmtStamp(span.start) + ' - ' + this.$fmtStamp(span.end);
    },

    /* A span as a bar: where it starts and how wide it is, as shares of the
       recording, and what it is in words for the pointer. */
    bar: function (span, label) {
      return {
        key: span.key,
        left: percent(span.start / this.total * 100),
        width: percent((span.end - span.start) / this.total * 100),
        title: label + ': ' + this.fmtRange(span),
      };
    },
  },
};
</script>
