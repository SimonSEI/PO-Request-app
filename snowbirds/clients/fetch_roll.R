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

# =============================================================================
# LEE PROPERTY ROLL (Florida Department of Revenue "NAL" file)
# =============================================================================
# Without it every Lee County client is judged on their billing address alone,
# so a Fort Myers or Cape Coral snowbird whose bills go to the Florida house
# is invisible. The state publishes each county's roll free on its Data Portal
# (Tax Roll Data Files -> NAL -> "Lee 46 ... NAL"). The exact link changes each
# tax year, so it is a setting, LEE_ROLL_URL, rather than written here. Unset,
# this does nothing and the service carries on exactly as before.
LEE_COLUMNS <- c("PARCEL_ID", "PHY_ADDR1", "PHY_ADDR2", "PHY_ZIPCD",
                 "OWN_NAME", "OWN_CITY", "OWN_STATE", "JV_HMSTD")

ensure_lee_roll <- function(dest, url = Sys.getenv("LEE_ROLL_URL", ""), max_age_days = 30) {
  if (!nzchar(url)) return(invisible("not configured"))
  if (file.exists(dest) &&
      difftime(Sys.time(), file.mtime(dest), units = "days") < max_age_days)
    return(invisible("current"))

  dir.create(dirname(dest), showWarnings = FALSE, recursive = TRUE)
  zip_path <- tempfile(fileext = ".zip")
  on.exit(unlink(zip_path), add = TRUE)
  message("Downloading Lee property roll...")
  r <- httr::GET(url, httr::write_disk(zip_path, overwrite = TRUE),
                 httr::user_agent("Mozilla/5.0 (snowbird client analysis)"), httr::timeout(900))
  if (httr::status_code(r) != 200 || file.size(zip_path) < 1e6) {
    # Last month's copy is better than none; no copy means Lee is simply
    # judged the old way, which is where it was before this existed.
    msg <- paste0("Lee roll download failed (HTTP ", httr::status_code(r), ", ",
                  file.size(zip_path), " bytes) - check LEE_ROLL_URL")
    if (file.exists(dest)) { message(msg, "; keeping the existing copy"); return(invisible("stale")) }
    message(msg); return(invisible("failed"))
  }

  # The state ships a zip; accept a bare CSV too, in case the link is to one.
  is_zip <- tryCatch({ utils::unzip(zip_path, list = TRUE); TRUE }, error = function(e) FALSE)
  tmp_dir <- tempfile()
  on.exit(unlink(tmp_dir, recursive = TRUE), add = TRUE)
  if (is_zip) {
    inside <- utils::unzip(zip_path, list = TRUE)$Name
    csv    <- inside[grepl("\\.(csv|txt)$", inside, ignore.case = TRUE)][1]
    if (is.na(csv)) { message("The Lee download held no CSV - check LEE_ROLL_URL"); return(invisible("failed")) }
    utils::unzip(zip_path, files = csv, exdir = tmp_dir)
    src <- file.path(tmp_dir, csv)
  } else src <- zip_path

  header <- names(readr::read_csv(src, n_max = 0, show_col_types = FALSE))
  miss   <- setdiff(LEE_COLUMNS, header)
  if (length(miss)) {
    message("The Lee file is missing ", paste(miss, collapse = ", "),
            " - it should be the NAL file, not SDF or NAP")
    return(invisible("failed"))
  }
  slim <- readr::read_csv(src, col_select = dplyr::all_of(LEE_COLUMNS),
                          col_types = readr::cols(.default = readr::col_character()),
                          progress = FALSE)
  readr::write_csv(slim, paste0(dest, ".partial"), na = "")
  file.rename(paste0(dest, ".partial"), dest)
  message("Lee roll ready: ", format(nrow(slim), big.mark = ","), " parcels")
  invisible("refreshed")
}
