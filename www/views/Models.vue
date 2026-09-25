<template>
  <div class="stt-page">

    <!-- One control, and it stands alone on the right: there is nothing to
         filter on a screen whose whole job is one short list. -->
    <div class="form-check-inline m-1 d-flex flex-wrap row-gap-1 align-items-center">
      <div style="margin-left:auto"></div>
      <div>
        <button type="button" class="btn btn-sm btn-secondary fw-bold" style="min-width:100px"
                title="Ask the server again what it carries"
                :disabled="wait.length > 0" @click="reload">
          <i class="fa fa-rotate"></i> RELOAD
        </button>
      </div>
    </div>

    <stt-alerts :wait="wait" :error.sync="error" :warning.sync="warning"
                :info.sync="info" :success.sync="success"></stt-alerts>

    <!-- One row per backend GET /api/models reports, as it reports it. No
         row tint: the STATUS word carries the state, and on a server with
         one backend loaded out of three, painting the rest would turn most of
         the table one colour. -->
    <div class="stt-card p-0 overflow-hidden">
      <div class="table-responsive">
        <table class="table table-striped table-sm table-fixed mb-0">
          <caption>MODELS</caption>
          <colgroup>
            <col style="width:12%">
            <col style="width:30%">
            <col style="width:11%">
            <col style="width:9%">
            <col style="width:13%">
            <col style="width:11%">
            <col style="width:14%">
          </colgroup>
          <thead>
            <tr>
              <td class="td-ellipsis">Backend</td>
              <td class="td-ellipsis">Model</td>
              <td class="td-ellipsis">Status</td>
              <td class="td-ellipsis" title="The backend this server transcribes with">Default</td>
              <td class="td-ellipsis" title="Whether a request's language means anything to this backend">Accepts language</td>
              <td class="td-ellipsis">Languages</td>
              <td class="td-ellipsis">Max speakers</td>
            </tr>
          </thead>
          <tbody>
            <!-- A row with a language list opens it; a row without one (the
                 diarizer produces no text) opens nothing and does not look as
                 if it would. -->
            <tr v-for="row in rows" :key="row.backend"
                :class="{ 'cursor-pointer': hasLanguages(row) }"
                :title="hasLanguages(row) ? 'Show the ' + row.languages.length + ' languages' : null"
                @click="openLanguages(row)">
              <td class="td-ellipsis" :title="row.backend">{{ row.backend || '-' }}</td>
              <td class="td-ellipsis" :title="modelTitle(row)">{{ row.model || '-' }}</td>
              <td :class="statusClass(row.status)" :title="statusTitle(row.status)">{{ row.status || '-' }}</td>
              <td>{{ row['default'] ? 'yes' : '-' }}</td>
              <td>{{ yesNo(row.accepts_language) }}</td>
              <td>{{ hasLanguages(row) ? row.languages.length : '-' }}</td>
              <td>{{ row.max_speakers || '-' }}</td>
            </tr>
            <tr v-if="rows.length === 0 && wait.length === 0">
              <td colspan="7" class="text-center">-</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- The languages of one backend. Bootstrap's own Modal, as the house
         dialogs are; the list is read-only, so the footer is CLOSE alone. -->
    <div class="modal fade" ref="modalEl" tabindex="-1" aria-hidden="true">
      <div class="modal-dialog modal-lg modal-dialog-scrollable">
        <div class="modal-content">
          <div class="modal-header bg-blue py-1 px-3">
            <h5 class="modal-title fw-bold mb-0 text-uppercase">{{ shown ? shown.backend + ' ' + shown.model : '' }}</h5>
            <button type="button" class="btn btn-primary btn-sm ms-auto"
                    data-bs-dismiss="modal" title="Close" aria-label="Close">
              <i class="fa fa-times"></i>
            </button>
          </div>
          <div class="modal-body py-2" v-if="shown">
            <div class="text-secondary mb-2">{{ shownSummary }}</div>
            <div class="stt-lang-grid">
              <div v-for="code in shownCodes" :key="code" class="td-ellipsis" :title="$languageName(code)">
                <code>{{ code }}</code>{{ $languageName(code) }}
              </div>
            </div>
          </div>
          <div class="modal-footer p-1 d-flex justify-content-end">
            <button type="button" class="btn btn-sm btn-secondary fw-bold" style="min-width:100px"
                    data-bs-dismiss="modal">CLOSE</button>
          </div>
        </div>
      </div>
    </div>

  </div>
</template>

<script>
/* What the server carries: GET /api/models, one row per backend - the
   transcription backends with their own language lists, and the diarizer.
   Read-only - a backend is installed at image build time and chosen in the
   server's environment, neither of which belongs behind a button here. */

var STATUS_TITLES = {
  loaded: 'In memory and answering requests',
  installed: 'On disk but not loaded - the server environment decides which backend runs',
  absent: 'Not installed in this image',
};

module.exports = {
  mixins: [SttWait],

  data: function () {
    return {
      wait: [],
      error: '',
      warning: '',
      info: '',
      success: '',
      // The row whose languages the dialog shows, or null.
      shown: null,
    };
  },

  computed: {
    rows: function () {
      return this.$store.state.catalog.models;
    },

    shownCodes: function () {
      return this.hasLanguages(this.shown) ? this.shown.languages.slice().sort() : [];
    },

    /* "100 languages - derived - default en English" */
    shownSummary: function () {
      var row = this.shown;
      if (!row) return '';
      var parts = [row.languages.length + ' languages'];
      if (row.languages_source) parts.push(row.languages_source);
      if (row.default_language) parts.push('default ' + row.default_language + ' ' + this.$languageName(row.default_language));
      if (row.accepts_language === false) parts.push('detected from the audio, never chosen');
      return parts.join(' - ');
    },
  },

  created: function () {
    // The guard filled the catalogue on the way in; ask only when it could
    // not (the server was not answering then).
    if (!this.$store.state.catalog.loaded) this.reload();
  },

  mounted: function () {
    // The Bootstrap handle is kept off `data`: Vue would make the library
    // object reactive and walk every field it owns.
    this.modalEl = this.$refs.modalEl;
    this.modal = (typeof bootstrap !== 'undefined' && bootstrap.Modal) ? new bootstrap.Modal(this.modalEl) : null;
    this.modalOpen = false;
    this.modalEl.addEventListener('hidden.bs.modal', this.handleHidden);
  },

  /* A dialog left open when the route changes (Back while it is up) has to be
     taken down by hand. `dispose()` removes the backdrop Bootstrap appended to
     <body>, but not what `show()` did to <body> itself - the `modal-open`
     class and the inline overflow and padding - and left there, the next
     screen renders on a page that cannot scroll. */
  beforeDestroy: function () {
    if (this.modalEl) this.modalEl.removeEventListener('hidden.bs.modal', this.handleHidden);
    if (this.modal) {
      if (this.modalOpen && document.body) {
        document.body.classList.remove('modal-open');
        document.body.style.removeProperty('overflow');
        document.body.style.removeProperty('padding-right');
      }
      this.modal.dispose();
      this.modal = null;
    }
    this.modalEl = null;
  },

  methods: {
    reload: function () {
      var self = this;
      this.error = '';
      this.waitPush('models');
      this.$store.dispatch('fetch_models')
        .catch(function (err) { self.error = self.$apiError(err); })
        .finally(function () { self.waitDrop('models'); });
    },

    hasLanguages: function (row) {
      return !!row && Array.isArray(row.languages) && row.languages.length > 0;
    },

    /* The model id, and the other names the server answers to for it. */
    modelTitle: function (row) {
      var aliases = Array.isArray(row.aliases) ? row.aliases : [];
      return aliases.length ? row.model + ' (also ' + aliases.join(', ') + ')' : row.model;
    },

    statusClass: function (status) {
      if (status === 'loaded') return 'stt-state-on';
      if (status === 'absent') return 'stt-state-off';
      return '';
    },

    statusTitle: function (status) {
      return STATUS_TITLES[status] || null;
    },

    /* true / false as words, anything else - the server not saying - as "-". */
    yesNo: function (value) {
      if (value === true) return 'yes';
      if (value === false) return 'no';
      return '-';
    },

    openLanguages: function (row) {
      if (!this.hasLanguages(row) || !this.modal) return;
      this.shown = row;
      this.modalOpen = true;
      this.modal.show();
    },

    handleHidden: function () {
      this.modalOpen = false;
      this.shown = null;
    },
  },
};
</script>
