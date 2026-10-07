# GCSU Catalytics: test version

A browser test version of GCSU Catalytics, the TrackMan reporting app built by the GCSU AI Lab for GCSU Baseball.

**Open the page, go to Load Data, and choose a TrackMan CSV export.** The app runs entirely in your browser
(Python compiled to WebAssembly, via [stlite](https://github.com/whitphx/stlite)):

- Your TrackMan file is read on your own computer. It is never uploaded to this site or anywhere else.
- Nothing is saved. Everything you load is cleared when you close the tab.
- The first visit downloads Python into the browser and takes about a minute.

This repository holds only the app code needed for the test page. It contains no player data.
The full project, data and documentation are kept in a private repository.
