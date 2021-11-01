# Heedy CGM Plugin

This plugin provides integration of heedy with the open-source glucose monitoring ecosystem. In particular, the plugin aims to be compatible with the [Nightscout](https://github.com/nightscout/cgm-remote-monitor) REST API, meaning that you can gather data from sources compatible with Nightscout.

## Building

This plugin is based on https://github.com/heedy/heedy-template-plugin, and can be run/debugged using the instructions there.

To build a release, run:

```
make
```

The resulting plugin zip file will be in the `dist/` folder.
