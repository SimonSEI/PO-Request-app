# =============================================================================
# PROJECT LIBRARY
# =============================================================================
# R runs this file automatically whenever an R session starts in this folder -
# RStudio opening the project, Rscript run from here, or a Scheduled Task.
#
# WHY THIS EXISTS
#
# Packages were originally installed to the default per-user library at
# %LOCALAPPDATA%\R\win-library. That turned out to be a trap: the assistant's
# shell runs inside a sandboxed Windows app container, so LOCALAPPDATA was
# silently redirected to
#     ...\AppData\Local\Packages\Claude_.....\LocalCache\Local\R\win-library
# Everything installed fine and every script worked - but only from inside that
# sandbox. A Windows Scheduled Task, and very likely your own RStudio, resolve
# LOCALAPPDATA to the REAL location, find it empty, and fail with
#     Error in library(tidyverse): there is no package called 'tidyverse'
#
# Keeping the library INSIDE the project removes the ambiguity entirely. It is
# the same folder for every caller, it travels with the project, and it cannot
# be redirected out from under you.
# =============================================================================

local({
  lib <- file.path(getwd(), ".Rlib")
  if (!dir.exists(lib)) dir.create(lib, recursive = TRUE, showWarnings = FALSE)
  .libPaths(c(lib, .libPaths()))
})

options(
  repos = c(CRAN = "https://cloud.r-project.org"),
  warn = 1
)
