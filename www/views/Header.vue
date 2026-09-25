<template>
  <header class="stt-header">
    <ul>
      <li class="navbar-brand">
        <router-link to="/transcribe">STT</router-link>
      </li>

      <!-- The sign-in screen gets the brand alone: the tabs lead to screens
           that would only send the visitor back here. -->
      <template v-if="$route.name !== 'login'">
      <li v-for="tab in tabs" :key="tab.path" class="nav-item" :class="{ active: tabActive(tab.path) }">
        <router-link :to="tab.path">{{ tab.label }}</router-link>
      </li>

      <li class="m-auto"></li>

      <!-- Light or dark. In the bar rather than on a settings screen: it is
           the one setting an operator changes because of the room they are
           sitting in.

           A real <button>, so it is reachable by keyboard and announced as a
           control; the glyph alone would be a decoration to a screen reader.
           `title` and `aria-label` carry the same sentence and both name the
           theme it switches TO - a control labelled with the state it is in
           reads, to whoever meets it first, as the state it will produce. -->
      <li class="nav-item nav-theme">
        <button type="button" class="stt-theme-toggle"
          @click="toggleTheme" :title="themeAction" :aria-label="themeAction">
          <i class="fa" :class="darkTheme ? 'fa-sun' : 'fa-moon'"></i>
        </button>
      </li>

      <!-- The way out, only when there was a way in: a browser holding no
           token has nothing to sign out of, and there is no user name to show
           beside it - the server knows tokens, not people. -->
      <li class="nav-item nav-theme" v-if="signedIn">
        <button type="button" class="stt-theme-toggle"
          title="Sign out" aria-label="Sign out" @click="logout">
          <i class="fa fa-right-from-bracket"></i>
        </button>
      </li>
      </template>
    </ul>
  </header>
</template>

<script>
/* The tabs, in order. One entry per screen, and a screen that belongs to a tab
   without being its path is listed under `owns` - otherwise nothing is lit on
   that screen and it reads as a broken page rather than a nested one. */
var TABS = [
  { path: '/transcribe', label: 'TRANSCRIBE' },
  { path: '/models', label: 'MODELS' },
];

module.exports = {
  data: function () {
    return { tabs: TABS };
  },

  computed: {
    signedIn: function () {
      return !!this.$store.state.auth.token;
    },

    /* Which half of the palette is in force. Read from the store rather than off
       the document element: app.js is what owns the attribute, and a bar that
       read the DOM back would show the wrong glyph for as long as it took Vue to
       notice a change it has no way of noticing. */
    darkTheme: function () {
      return this.$store.state.theme === 'dark';
    },
    themeAction: function () {
      return this.darkTheme ? 'Switch to the light theme' : 'Switch to the dark theme';
    },
  },

  mounted: function () {
    this.watchBarHeight();
  },

  beforeDestroy: function () {
    this.releaseBarHeight();
  },

  methods: {
    /* Forget the token and go to the sign-in screen. Nothing to tell the
       server: a bearer token has no session behind it. */
    logout: function () {
      this.$saveToken('');
      this.$goto('/login');
    },

    /* Whether a tab is the one the operator is on. By path rather than by
       name: the path is what the tab links to. */
    tabActive: function (own) {
      var tab = TABS.filter(function (entry) { return entry.path === own; })[0];
      var owned = (tab && tab.owns) || [own];
      return owned.indexOf(this.$route.path) !== -1;
    },

    /* Publish how tall this bar is, for the dialogs that open under it.

       Every modal in this UI is offset by `--stt-header-height`, and the bar is
       the only thing that knows the answer - so it is the bar that measures and
       publishes it, once, on the document element.

       Watched rather than measured once: the bar wraps onto a second line on a
       narrow window, so the height changes without anything else on the page
       changing. ResizeObserver sees that; a window listener is the fallback for
       a browser without it. A bar that measures zero - hidden, or not laid out
       yet - leaves the declared floor in place. */
    watchBarHeight: function () {
      var self = this;
      this.publishBarHeight();
      if (typeof ResizeObserver === 'function' && this.$el && this.$el.nodeType === 1) {
        this.barWatcher = new ResizeObserver(function () { self.publishBarHeight(); });
        this.barWatcher.observe(this.$el);
        return;
      }
      this.barResizeHandler = function () { self.publishBarHeight(); };
      window.addEventListener('resize', this.barResizeHandler);
    },

    publishBarHeight: function () {
      var root = document.documentElement;
      var bar = this.$el;
      if (!root || !root.style || !bar || !bar.getBoundingClientRect) return;
      var height = Math.round(bar.getBoundingClientRect().height);
      if (height > 0) {
        root.style.setProperty('--stt-header-height', height + 'px');
      } else {
        root.style.removeProperty('--stt-header-height');
      }
    },

    /* The observer and the published value both go when the bar does. A value
       left on the document outlives the element it measured. */
    releaseBarHeight: function () {
      if (this.barWatcher) {
        this.barWatcher.disconnect();
        this.barWatcher = null;
      }
      if (this.barResizeHandler) {
        window.removeEventListener('resize', this.barResizeHandler);
        this.barResizeHandler = null;
      }
      if (document.documentElement && document.documentElement.style) {
        document.documentElement.style.removeProperty('--stt-header-height');
      }
    },

    /* The switch. `$saveTheme` repaints the page and answers whether this browser
       agreed to remember it; the toast is for the case where it did not. */
    toggleTheme: function () {
      var kept = this.$saveTheme(this.darkTheme ? 'light' : 'dark');
      if (kept) return;
      this.$store.dispatch('push_toast', {
        level: 'warning',
        message: 'This browser would not store the setting, so it holds until the page is reloaded.',
        ttl: 12000,
      });
    },
  },
};
</script>
