# =============================================================================
# SETUP - install every package this project needs, INTO the project
# =============================================================================
# Run this once. It puts all packages in a .Rlib folder inside the project,
# which .Rprofile then adds to the library path automatically.
#
# WHY NOT THE NORMAL USER LIBRARY
#
# The default is %LOCALAPPDATA%\R\win-library. That works fine until something
# runs in a different environment - a Windows Scheduled Task, a sandboxed app
# container - and LOCALAPPDATA resolves somewhere else. You then get
#     Error in library(tidyverse) : there is no package called 'tidyverse'
# from a script that works perfectly when you run it yourself.
#
# A library inside the project is the same folder for every caller, travels
# with the project, and cannot be redirected.
# =============================================================================

lib <- file.path(getwd(), ".Rlib")
dir.create(lib, recursive = TRUE, showWarnings = FALSE)

# .Library only - deliberately NOT .libPaths().
#
# The first attempt used .libPaths(c(lib, .libPaths())), which left the old
# user library visible. install.packages() then saw every dependency as
# "already installed", skipped them all, and produced a project library with
# 9 packages in it instead of ~120. It looked like a success and would have
# failed the moment anything ran outside the environment holding the real
# packages.
#
# Hiding the other libraries forces a genuine, self-contained install.
.libPaths(c(lib, .Library))

cat("Project library:", lib, "\n")
cat("Resolving against:", paste(.libPaths(), collapse = " | "), "\n")

pkgs <- c(
  "tidyverse",        # data wrangling + ggplot2
  "jsonlite",         # web APIs
  "scales",           # axis formatting
  "shiny",            # the dashboard
  "bslib",            # dashboard layout and theming
  "shinycssloaders",  # loading spinners
  "DBI", "odbc",      # reading FDOT's Access database
  "pdftools"          # reading the airport statistics PDFs
)

# Checking only the NAMED packages is not enough. The second attempt at this
# reported "all required packages present" with 9 packages installed, because
# the 9 headline names were there - while their ~110 dependencies were not.
# The real test is whether the packages LOAD with nothing else on the path.
installed <- rownames(installed.packages(lib.loc = lib))
missing   <- setdiff(pkgs, installed)

if (length(missing) > 0) {
  cat("Installing:", paste(missing, collapse = ", "), "\n")
  install.packages(missing, lib = lib, repos = "https://cloud.r-project.org")
}

final <- rownames(installed.packages(lib.loc = lib))
cat("\nPackages in project library:", length(final), "\n")

# Proof rather than assumption: actually load each one.
cat("\nVerifying each package loads from the project library alone...\n")
failed <- character()
for (p in pkgs) {
  ok <- suppressWarnings(suppressMessages(
    requireNamespace(p, quietly = TRUE, lib.loc = c(lib, .Library))
  ))
  cat(" ", if (ok) "OK  " else "FAIL", p, "\n")
  if (!ok) failed <- c(failed, p)
}

if (length(failed) > 0) {
  cat("\nFAILED TO LOAD:", paste(failed, collapse = ", "), "\n")
  cat("Delete the .Rlib folder and run this script again.\n")
  quit(status = 1)
}
cat("\nAll", length(pkgs), "packages load cleanly. Library is self-contained.\n")
