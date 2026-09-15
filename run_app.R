# =============================================================================
# LAUNCH THE DASHBOARD
# =============================================================================
# Three ways to start this app, easiest first:
#
#   1. In RStudio: open app.R and click the "Run App" button (top right of
#      the editor). This is the normal way.
#
#   2. In RStudio: open THIS file and press Ctrl+Shift+Enter.
#
#   3. From a terminal, in the project folder:
#        "C:\Program Files\R\R-4.6.1\bin\Rscript.exe" run_app.R
#
# Stop it with Escape in the RStudio console, or Ctrl+C in a terminal.
# =============================================================================

# Make sure packages installed to your personal library are visible.
.libPaths(c(Sys.getenv("R_LIBS_USER"), .libPaths()))

# Run from this file's folder, so the app finds data/weather_daily.csv
# no matter where you launched R from.
app_dir <- tryCatch(
  dirname(normalizePath(sys.frame(1)$ofile)),
  error = function(e) getwd()
)

message("Starting dashboard from: ", app_dir)
message("It will open in your browser. Press Escape or Ctrl+C to stop.")

shiny::runApp(app_dir, port = 7788, launch.browser = TRUE)
