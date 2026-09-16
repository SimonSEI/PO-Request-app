# This file exists to switch OFF Shiny's R/ autoloading.
#
# shiny::runApp() automatically sources every .R file in an R/ folder that sits
# next to app.R. In this project R/ holds the ANALYSIS PIPELINE - fifteen
# scripts that download weather, query FDOT, parse PDFs and refit models.
#
# Without this file, every local launch of the dashboard silently re-ran the
# whole pipeline first. That is why startup took ~90 seconds, why pipeline
# output kept appearing in the app's logs, and why the app eventually failed to
# start at all when FDOT's server timed out mid-launch.
#
# Shiny skips autoloading when a file with exactly this name is present. The
# dashboard reads the pipeline's OUTPUTS (data/, output/), never its scripts.
# Railway was never affected: .dockerignore keeps R/ out of the image.
