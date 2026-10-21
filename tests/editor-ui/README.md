# Recovered hosted-editor checks

These historical hosted-editor probes were recovered from `build/ui-test/`.
They use Arcade and Inner Breeze's existing test driver. Their old public
editor labels and scenarios are retained for reference; the maintained
standalone developer editor check is `make editor-ui-test`.

Run graphical checks only on a private Xvfb display with inherited desktop
and session variables scrubbed. Use disposable profiles under `build/ui-test/`.
