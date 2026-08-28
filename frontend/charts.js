/* ============================================================================
   Altaha — Charts
   ----------------------------------------------------------------------------
   A drop-in Charts tab. One <script> line in index.html and nothing else: this
   file injects its own tab button (desktop bar and mobile bar), its own view
   container, and its own workspace. It reads API_BASE from the page and needs
   no backend change to run.

   WHAT IS NEW HERE VERSUS THE EXISTING CHART PANEL
   ------------------------------------------------
   1. Drawings are anchored to TIME AND PRICE, not to the on-screen pixel or to
      a bar index. Switch 15m to 1D and the trendline you drew still sits on the
      same two dates. The old panel stored a lightweight-charts LineSeries per
      drawing, which meant the drawing was data — it could not be moved, could
      not be deleted individually, and was wiped on every timeframe change.
   2. Drawings live on a canvas above the chart, so there is no limit on what
      can be drawn: rectangles, Fibonacci grids, parallel channels, a measuring
      ruler and a risk/reward position box are all just paths.
   3. Everything is selectable, draggable by body or by handle, deletable, and
      undoable, and it persists per symbol in the browser.
   4. It works on touch. The existing site hides its drawing tools below 780px
      with the comment "unusable on touch" — they were not unusable, the hit
      targets were 24px. These are 40px with 16px hit tolerance.
   5. The last candle updates from the live quote every second or two instead
      of the whole chart being refetched every sixty. That, more than anything
      else, is what makes a chart feel alive.

   The drawing model is deliberately plain JSON:
     { id, type, pts:[{t,p}], color, width, text }
   so it can be exported, shared as a URL, or saved server-side later without
   touching any of the rendering code.
   ========================================================================== */
