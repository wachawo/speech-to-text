<template>
  <div class="stt-toaster" role="status" aria-live="polite" aria-atomic="false">
    <!-- A polite live region, so a screen reader announces each toast once
         the current sentence ends. On the stack rather than on each toast:
         the region has to exist before the text arrives, or nothing is
         announced. Not atomic, which role="status" is by default: a new
         toast is read on its own, not together with the ones still shown. -->
    <div v-for="t in $store.state.toasts" :key="t.id"
         class="stt-toast" :class="'stt-toast-' + t.level"
         @click="$store.dispatch('dismiss_toast', t.id)">
      <i class="fa me-2" :class="icon(t.level)"></i>
      <span class="stt-toast-msg">{{ t.message }}</span>
      <i class="fa fa-xmark ms-2 stt-toast-x"></i>
    </div>
  </div>
</template>

<script>
/* The stack of toasts in the top right corner, fed by the store: any screen
   pushes one with `this.$store.dispatch('push_toast', {level, message, ttl})`
   and a click dismisses it early. Levels are danger, warning, success and
   info; anything else is drawn as info. */
module.exports = {
  methods: {
    icon: function (level) {
      if (level === 'danger')  return 'fa-circle-exclamation';
      if (level === 'success') return 'fa-circle-check';
      if (level === 'warning') return 'fa-triangle-exclamation';
      return 'fa-circle-info';
    },
  },
};
</script>
