# =============================================================================
# COLLIER PROPERTY ROLL, KEPT FRESH ON THE RAILWAY VOLUME
# =============================================================================
# The Property Appraiser's parcel file is public and free, but 168 MB unzipped,
# far too big for GitHub. So the clients service downloads it itself, keeps
# only the eleven columns R/18 matches on (about a quarter of the size), and
# re-downloads once a month. Ownership and homestead status change slowly;
# monthly is plenty.
# =============================================================================

COLLIER_URL <- "https://www.collierappraiser.com/Main_Data/downloadgdfile.asp?folderName=INT%20FILES%20(NEW)&file=int_parcels_csv.zip"

ROLL_COLUMNS <- c("ParcelId", "UseCode", "OwnerLine1", "OwnerCity", "OwnerState", "OwnerCountry",
                  "HmstdExemptAmount", "SiteStreetNumber", "SiteStreetName", "SiteUnit", "SiteZipCode")

# zip_path lets a local copy stand in for the download (used in testing).
ensure_collier_roll <- function(dest, max_age_days = 30, zip_path = NULL) {
  if (file.exists(dest) &&
      difftime(Sys.time(), file.mtime(dest), units = "days") < max_age_days)
    return(invisible("current"))

  dir.create(dirname(dest), showWarnings = FALSE, recursive = TRUE)

  if (is.null(zip_path)) {
    zip_path <- tempfile(fileext = ".zip")
    on.exit(unlink(zip_path), add = TRUE)
    message("Downloading Collier property roll...")
    ua <- httr::user_agent("Mozilla/5.0 (snowbird client analysis)")
    r  <- httr::GET(COLLIER_URL, httr::write_disk(zip_path, overwrite = TRUE), ua, httr::timeout(600))

    # The county hosts the file on Google Drive. Files over ~25 MB come back as
    # a "too large to scan for viruses - download anyway?" page instead of the
    # zip. That page is a plain form; submitting its fields is the same as
    # clicking the button.
    if (httr::status_code(r) == 200 && grepl("text/html", httr::headers(r)[["content-type"]] %||% "")) {
      page   <- paste(readLines(zip_path, warn = FALSE), collapse = "\n")
      action <- regmatches(page, regexpr('(?<=<form id="download-form" action=")[^"]+', page, perl = TRUE))
      inputs <- regmatches(page, gregexpr('<input type="hidden" name="[^"]+" value="[^"]*"', page))[[1]]
      if (length(action) == 1 && length(inputs)) {
        fields <- setNames(as.list(sub('.*value="([^"]*)".*', "\\1", inputs)),
                           sub('.*name="([^"]+)".*', "\\1", inputs))
        r <- httr::GET(action, query = fields, httr::write_disk(zip_path, overwrite = TRUE), ua, httr::timeout(600))
      }
    }
    if (httr::status_code(r) != 200 || file.size(zip_path) < 1e6) {
      # Keep using last month's copy rather than lose the matching entirely.
      if (file.exists(dest)) {
        message("Roll download failed (HTTP ", httr::status_code(r), ") - keeping the existing copy")
        return(invisible("stale"))
      }
      stop("Could not download the Collier property roll (HTTP ", httr::status_code(r), ")", call. = FALSE)
    }
  }

  inside <- utils::unzip(zip_path, list = TRUE)$Name
  csv    <- inside[grepl("int_parcels.*\\.csv$", inside, ignore.case = TRUE)][1]
  if (is.na(csv)) stop("The roll download did not contain int_parcels.csv", call. = FALSE)

  tmp_dir <- tempfile()
  on.exit(unlink(tmp_dir, recursive = TRUE), add = TRUE)
  utils::unzip(zip_path, files = csv, exdir = tmp_dir)

  slim <- readr::read_csv(file.path(tmp_dir, csv), col_select = dplyr::all_of(ROLL_COLUMNS),
                          col_types = readr::cols(.default = readr::col_character()),
                          progress = FALSE)
  # Write beside the destination then rename, so a crash mid-write never
  # leaves a half-file that looks current.
  readr::write_csv(slim, paste0(dest, ".partial"), na = "")
  file.rename(paste0(dest, ".partial"), dest)
  message("Collier roll ready: ", format(nrow(slim), big.mark = ","), " parcels")
  invisible("refreshed")
}
