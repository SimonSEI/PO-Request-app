# =============================================================================
# SETUP - run this ONCE, before anything else.
# =============================================================================
# In R, a line starting with # is a comment. R ignores it. It's for humans.
#
# HOW TO RUN A SCRIPT:
#   In RStudio, press Ctrl+Shift+Enter (runs the whole file), or put your
#   cursor on a line and press Ctrl+Enter to run just that line.
#   Running one line at a time is the best way to learn - you see each step.
# =============================================================================

# A "package" is someone else's code you borrow. install.packages() downloads
# it to your computer. You only ever need to do this ONCE per package.
needed <- c(
  "tidyverse",  # the big one: data wrangling (dplyr) + charts (ggplot2)
  "jsonlite",   # reads JSON, the format web APIs speak
  "lubridate",  # makes working with dates sane
  "scales"      # nice axis labels on charts (e.g. "20,000" not "2e+04")
)

# --- Where do packages go? -----------------------------------------------
# R ships with a library inside "C:/Program Files/R/...", but Windows won't
# let you write there without admin rights - you'll get:
#     'lib = "C:/Program Files/R/R-4.6.1/library"' is not writable
#
# The fix is a PERSONAL library in your own user folder. No admin needed, and
# R picks it up automatically once the folder exists.
user_lib <- Sys.getenv("R_LIBS_USER")
dir.create(user_lib, recursive = TRUE, showWarnings = FALSE)
.libPaths(user_lib)

message("Library: ", user_lib)

# Only install what's actually missing, so re-running this is harmless.
missing <- needed[!(needed %in% rownames(installed.packages()))]

if (length(missing) > 0) {
  message("Installing: ", paste(missing, collapse = ", "))
  install.packages(missing, lib = user_lib, repos = "https://cloud.r-project.org")
} else {
  message("All packages already installed. Nothing to do.")
}

# Quick check that everything loads. library() = "actually use this package".
# You DO need library() every time you start a new R session.
library(tidyverse)
library(jsonlite)

message("Setup complete. R version: ", R.version.string)
