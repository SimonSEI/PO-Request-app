# =============================================================================
# 18 - WHICH CLIENTS ARE SNOWBIRDS, WHEN ARE THEY BACK, WHEN TO RESEND
# =============================================================================
# Reads what R/17 pulled from Jobber and answers three questions per client:
#
#  1. DO THEY HAVE A HOME UP NORTH?
#     Two independent pieces of evidence:
#       a) The county property roll for the job address. No homestead exemption
#          (a sworn "this is my permanent home") + tax mail going out of state
#          = a second home. The same test R/08 uses for the county as a whole.
#       b) Their billing address in Jobber. Bills going to Ohio say Ohio.
#     Agreeing evidence = confirmed. One piece alone = likely. A homestead
#     exemption overrides a northern billing address - they live here now.
#
#  2. WHEN WILL THEY BE BACK?
#     Best: their OWN history. The first time each autumn they asked for a
#     quote or booked a job is when they personally re-engage, and people are
#     creatures of habit. Used whenever we have at least one past season.
#     Otherwise: the season-opening date from the forecast model (R/09-10),
#     which is when Collier + Lee traffic first rises above an ordinary day.
#
#  3. WHEN TO RESEND THE QUOTE (with 10% off)?
#     LEAD_DAYS before they are due back. Early enough that they can book the
#     work for when they arrive; late enough that they are already thinking
#     about the trip. If that moment has already passed and they are here
#     now, the answer is simply: now.
#
# OUTPUT (git-ignored - client data never leaves this computer):
#   output/clients/client_second_homes.csv  every client, with the evidence
#   output/clients/quote_resend_plan.csv    outstanding quotes, in send order
#
# This script only READS. It never sends, edits or discounts anything in Jobber.
# =============================================================================

if (file.exists(".Rlib")) .libPaths(c(normalizePath(".Rlib"), .libPaths()))
suppressPackageStartupMessages({ library(tidyverse); library(lubridate) })

IN_DIR  <- Sys.getenv("SNOWBIRD_CLIENT_DIR", Sys.getenv("JOBBER_DATA_DIR", "data/jobber"))
OUT_DIR <- Sys.getenv("SNOWBIRD_CLIENT_OUT", "output/clients")
dir.create(OUT_DIR, showWarnings = FALSE, recursive = TRUE)

TODAY <- as.Date(Sys.getenv("SNOWBIRD_TODAY", as.character(Sys.Date())))

# --- Fixed settings, with the reasoning ----------------------------------------
# Two weeks: long enough to plan the work around their arrival, short enough
# that the offer is still front of mind when they land. Once a season of
# resends has been tracked, replace this with the lead that actually converted.
LEAD_DAYS <- 14
DISCOUNT  <- 0.10

# Quotes Jobber still considers open. Drafts were never sent, approved and
# converted ones are won, archived ones were closed on purpose.
OUTSTANDING <- c("awaiting_response", "changes_requested")

# A client's autumn "return" is looked for between these dates. Earlier
# activity is summer business from people who never left.
RETURN_WINDOW <- c(start = "09-01", end = "01-31")

# --- Who and what this offer must NEVER go to ---------------------------------
# A "welcome back, 10% off" is aimed at a household with a second home here.
# Three kinds of recipient are not that, and sending to them is worse than
# missing a resend:
#   - businesses generally (Jobber's own isCompany flag, or a company name)
#   - HOAs, condo and community associations - a board does not come back
#     for the winter, and a homeowner discount is the wrong message
#   - landscaping, lawn and irrigation firms - trade contacts, and in several
#     cases direct competitors
#
# Over-matching is deliberately the safe direction: missing a resend costs one
# discount, emailing a competitor a homeowner offer costs more. Everything
# dropped is written to excluded_from_plan.csv with the reason, so the office
# can audit the calls rather than wonder where a quote went.
ORG_PATTERNS <- c(
  # HOAs, condo and community associations, clubs
  "ASSOCIATION", "\\bASSN\\b", "\\bASSOC\\b", "\\bH\\.?O\\.?A\\.?\\b",
  "\\bP\\.?O\\.?A\\.?\\b", "\\bC\\.?D\\.?D\\.?\\b",
  "CONDOMINIUM", "\\bCONDOS?\\b", "HOMEOWNER", "PROPERTY OWNERS",
  "\\bCOMMUNITY\\b", "COUNTRY CLUB", "\\bCLUB\\b", "\\bVILLAS\\b",
  "\\bESTATES\\b", "\\bRESORT\\b", "MASTER ASSOC",
  # landscaping and grounds trades
  "LANDSCAP", "\\bLAWNS?\\b", "IRRIGATION", "SPRINKLER",
  "\\bNURSER(Y|IES)\\b", "GROUNDS ?(KEEPING|CARE|MAINT)",
  "TREE SERVICE", "\\bSOD\\b", "\\bTURF\\b", "\\bHARDSCAPE",
  # Management companies. In this market a management company on the client
  # line almost always means an HOA or a condo board rather than a household -
  # the manager is the billing contact for the community, not a homeowner.
  # The abbreviations matter: "Mgmt" is at least as common as the full word.
  "\\bMANAGEMENT\\b", "\\bMANAGERS?\\b", "\\bMGMT\\.?\\b", "\\bMGT\\.?\\b",
  "PROPERTY MANAGE", "PROPERTY SERVICES", "\\bPROPERTIES\\b",
  "\\bREALTY\\b", "REAL ESTATE", "\\bRESIDENTIAL\\b",
  # other generic business markers
  "\\bLLC\\b", "\\bL\\.L\\.C\\.?\\b", "\\bINC\\.?\\b", "\\bCORP\\b",
  "\\bLTD\\b", "\\bHOLDINGS\\b", "\\bENTERPRISES\\b", "\\bGROUP\\b",
  "\\bCHURCH\\b", "\\bSCHOOL\\b", "\\bCITY OF\\b", "\\bCOUNTY OF\\b"
)
ORG_RE <- paste(ORG_PATTERNS, collapse = "|")

# Past this, the price, the scope and often the property have moved on. Such a
# quote wants re-quoting, not resending at a discount.
# One setting, read by both this script and clients/auto_send.R, so the plan
# and the sender can never disagree about the limit.
MAX_QUOTE_AGE_MONTHS <- as.integer(Sys.getenv("SNOWBIRD_MAX_QUOTE_AGE_MONTHS", "13"))

# An optional hand-maintained list for the ones no rule can catch - an HOA
# called "Autumn Woods" looks exactly like a person's address. One column,
# client_id or client name, one per row. Lives on the volume beside the
# Jobber data so it survives redeploys.
MANUAL_EXCLUDE <- Sys.getenv("SNOWBIRD_EXCLUDE_FILE",
                             file.path(IN_DIR, "do_not_send.csv"))

# =============================================================================
# 1. Jobber data
# =============================================================================
rd <- function(f) read_csv(file.path(IN_DIR, f), col_types = cols(.default = col_character()))
quotes  <- rd("quotes.csv")  %>% mutate(total = as.numeric(total))
clients <- rd("clients.csv")
jobs    <- rd("jobs.csv")

# Older pulls predate the is_company column; treat it as unknown rather than
# failing, so the rules still work before the next refresh.
if (!"is_company" %in% names(clients)) clients$is_company <- NA_character_

manual_list <- if (file.exists(MANUAL_EXCLUDE)) {
  m <- read_csv(MANUAL_EXCLUDE, col_types = cols(.default = col_character()))
  unique(toupper(str_squish(unlist(m[[1]]))))
} else character()

clients <- clients %>%
  mutate(
    co_flag      = tolower(str_squish(is_company)),
    co_named     = !is.na(company) & str_squish(company) != "",
    co_hit   = str_extract(toupper(str_squish(paste(coalesce(name, ""),
                                                      coalesce(company, "")))), ORG_RE),
    co_manual    = toupper(str_squish(name)) %in% manual_list | client_id %in% manual_list,
    # Order matters: Jobber's flag wins, then a company name, then the name
    # patterns, then the hand-maintained list.
    is_org = co_manual | co_flag %in% c("true", "t", "yes", "1") | co_named | !is.na(co_hit),
    org_reason = case_when(
      co_manual                              ~ "on the do-not-send list",
      co_flag %in% c("true", "t", "yes", "1") ~ "Jobber marks this client as a company",
      co_named                               ~ paste0("company name on file: ", str_squish(company)),
      !is.na(co_hit)                     ~ paste0("name looks like a business or HOA (matched \"",
                                                    co_hit, "\")"),
      TRUE                                 ~ NA_character_)
  ) %>%
  select(-co_flag, -co_named, -co_hit, -co_manual)

as_day <- function(x) as.Date(suppressWarnings(ymd_hms(x, quiet = TRUE)))

# =============================================================================
# 2. Addresses: making "123 N. Main Street, Apt 4B" and the county's
#    "123 | MAIN | ST | N | 4B" come out as the same key
# =============================================================================
SUFFIX <- c(STREET="ST", AVENUE="AVE", DRIVE="DR", BOULEVARD="BLVD", COURT="CT",
            LANE="LN", ROAD="RD", CIRCLE="CIR", PLACE="PL", TERRACE="TER",
            TRAIL="TRL", PARKWAY="PKWY", POINT="PT", COVE="CV", MANOR="MNR",
            SQUARE="SQ", ISLE="IS", ISLAND="IS", LANDING="LNDG", BEND="BND",
            HIGHWAY="HWY", WAY="WAY", LOOP="LOOP", RUN="RUN", ROW="ROW",
            WALK="WALK", CAY="CAY", PASS="PASS", PATH="PATH", CROSSING="XING")
DIRS   <- c(NORTH="N", SOUTH="S", EAST="E", WEST="W",
            NORTHEAST="NE", NORTHWEST="NW", SOUTHEAST="SE", SOUTHWEST="SW")
DROP_WORDS <- unique(c(SUFFIX, names(SUFFIX), DIRS, names(DIRS)))

clean_unit <- function(u) {
  u <- str_remove_all(toupper(coalesce(u, "")), "[^A-Z0-9]")
  u <- str_remove(u, "^0+")
  na_if(u, "")
}

# street1/street2 as typed into Jobber -> number, street core, unit
parse_street <- function(street1, street2 = NA_character_) {
  s <- toupper(paste(coalesce(street1, ""), coalesce(street2, "")))
  s <- str_replace_all(s, "[.,]", " ")
  unit_pat <- "(?:#|\\bAPT\\b|\\bAPARTMENT\\b|\\bUNIT\\b|\\bSTE\\b|\\bSUITE\\b|\\bPH\\b|\\bBLDG\\b)\\s*#?\\s*([A-Z0-9-]+)"
  unit <- str_match(s, unit_pat)[, 2]
  s    <- str_squish(str_remove_all(s, unit_pat))
  num  <- str_match(s, "^(\\d+)")[, 2]
  rest <- str_squish(str_remove(s, "^\\d+[A-Z]?\\s*"))
  core <- map_chr(str_split(rest, " "), function(w) {
    w <- w[nzchar(w) & !(w %in% DROP_WORDS)]
    if (length(w) == 0) NA_character_ else paste(w, collapse = " ")
  })
  tibble(num = num, core = core, unit = clean_unit(unit))
}

zip5 <- function(z) str_sub(str_remove_all(coalesce(z, ""), "[^0-9]"), 1, 5)

# =============================================================================
# 3. Property rolls
# =============================================================================
CANADA <- c(AB="Alberta", BC="British Columbia", MB="Manitoba", NB="New Brunswick",
            NL="Newfoundland and Labrador", NS="Nova Scotia", ON="Ontario",
            PE="Prince Edward Island", QC="Quebec", SK="Saskatchewan")

rolls <- list()

# --- Collier: the Property Appraiser's own parcel file (as used by R/08) ------
COLLIER_ROLL <- Sys.getenv("COLLIER_ROLL", "data/raw/collier_int_parcels.csv")
if (file.exists(COLLIER_ROLL)) {
  message("Reading Collier property roll...")
  rolls$collier <- read_csv(COLLIER_ROLL,
      col_select = c(ParcelId, UseCode, OwnerLine1, OwnerCity, OwnerState, OwnerCountry,
                     HmstdExemptAmount, SiteStreetNumber, SiteStreetName, SiteUnit, SiteZipCode),
      col_types = cols(.default = col_character()), progress = FALSE) %>%
    transmute(county = "Collier", parcel_id = ParcelId,
              num  = str_remove(SiteStreetNumber, "^0+"),
              core = map_chr(str_split(toupper(str_squish(SiteStreetName)), " "),
                             ~ paste(.x[!(.x %in% DROP_WORDS)], collapse = " ")),
              unit = clean_unit(SiteUnit), zip = zip5(SiteZipCode),
              owner_name = OwnerLine1, owner_city = OwnerCity,
              owner_state = OwnerState,
              owner_country = if_else(is.na(OwnerCountry) | OwnerCountry %in% c("USA", "US", "UNITED STATES"),
                                      "USA", OwnerCountry),
              homestead = coalesce(as.numeric(HmstdExemptAmount), 0) > 0)
}

# --- Lee: Florida Department of Revenue NAL file ------------------------------
# Lee's appraiser sells bulk data; the state publishes the same roll for free as
# "Lee 46 ... NAL 2026" on floridarevenue.com's Data Portal (Tax Roll Data Files
# -> NAL). Unzip the CSV to data/raw/lee_nal.csv. Column names below follow the
# Department's NAL user guide.
LEE_ROLL <- Sys.getenv("LEE_ROLL", "data/raw/lee_nal.csv")
if (file.exists(LEE_ROLL)) {
  message("Reading Lee property roll...")
  lee <- read_csv(LEE_ROLL, col_types = cols(.default = col_character()), progress = FALSE)
  need <- c("PARCEL_ID", "PHY_ADDR1", "PHY_ZIPCD", "OWN_NAME", "OWN_CITY", "OWN_STATE", "JV_HMSTD")
  miss <- setdiff(need, names(lee))
  if (length(miss)) stop("lee_nal.csv is missing expected columns: ", paste(miss, collapse = ", "),
                         " - check it is the NAL file, not SDF/NAP", call. = FALSE)
  p <- parse_street(lee$PHY_ADDR1, lee$PHY_ADDR2 %||% NA_character_)
  own_state <- toupper(str_squish(lee$OWN_STATE))
  rolls$lee <- tibble(
    county = "Lee", parcel_id = lee$PARCEL_ID,
    num = p$num, core = p$core, unit = p$unit, zip = zip5(lee$PHY_ZIPCD),
    owner_name = lee$OWN_NAME, owner_city = lee$OWN_CITY, owner_state = own_state,
    owner_country = case_when(own_state %in% names(CANADA) ~ "CANADA",
                              is.na(own_state) | own_state == "" ~ NA_character_,
                              own_state %in% c(state.abb, "DC", "PR") ~ "USA",
                              TRUE ~ own_state),
    homestead = coalesce(as.numeric(lee$JV_HMSTD), 0) > 0)
}

roll <- bind_rows(rolls) %>% filter(!is.na(num), !is.na(core), zip != "")
counties_loaded <- names(rolls)
roll_zips       <- unique(roll$zip)
message("Property rolls loaded: ", if (length(rolls)) paste(str_to_title(counties_loaded), collapse = ", ") else "none")

# =============================================================================
# 4. Every property a client has used, matched to a parcel
# =============================================================================
props <- bind_rows(
  quotes %>% select(client_id, property_id, starts_with("prop_")),
  jobs   %>% select(client_id, property_id, starts_with("prop_"))) %>%
  filter(!is.na(client_id), !is.na(prop_street1)) %>%
  distinct(client_id, prop_street1, prop_street2, prop_postal, .keep_all = TRUE)

props <- bind_cols(props, parse_street(props$prop_street1, props$prop_street2)) %>%
  mutate(zip = zip5(prop_postal))

match_one <- function(num, core, unit, zip) {
  if (is.na(num) || is.na(core) || zip == "") return(list(result = "address incomplete"))
  if (!(zip %in% roll_zips)) return(list(result = sprintf("ZIP %s is outside the property rolls loaded", zip)))
  cand <- roll[roll$zip == zip & roll$num == num & roll$core == core, ]
  if (nrow(cand) == 0) return(list(result = "no parcel found at this address"))
  if (!is.na(unit) && any(cand$unit == unit, na.rm = TRUE)) cand <- cand[which(cand$unit == unit), ]

  # Several parcels at one street address (a condo building, or a unit that
  # was not typed in Jobber): accept only if every candidate tells the same
  # story, otherwise we would be guessing which neighbour is ours.
  verdicts <- unique(paste(cand$homestead, cand$owner_state, cand$owner_country))
  if (nrow(cand) > 1 && length(verdicts) > 1)
    return(list(result = sprintf("%d units at this address disagree - add the unit number in Jobber", nrow(cand))))

  c1 <- cand[1, ]
  list(result = if (nrow(cand) > 1) "matched (all units agree)" else "matched",
       county = c1$county, parcel_id = c1$parcel_id, owner_name = c1$owner_name,
       owner_city = c1$owner_city, owner_state = c1$owner_state,
       owner_country = c1$owner_country, homestead = c1$homestead)
}

message("Matching ", nrow(props), " client properties to parcels...")
m <- pmap(list(props$num, props$core, props$unit, props$zip), match_one)
props <- props %>% mutate(
  match_result  = map_chr(m, "result"),
  county        = map_chr(m, ~ .x$county        %||% NA_character_),
  parcel_id     = map_chr(m, ~ .x$parcel_id     %||% NA_character_),
  owner_name    = map_chr(m, ~ .x$owner_name    %||% NA_character_),
  owner_city    = map_chr(m, ~ .x$owner_city    %||% NA_character_),
  owner_state   = map_chr(m, ~ .x$owner_state   %||% NA_character_),
  owner_country = map_chr(m, ~ .x$owner_country %||% NA_character_),
  homestead     = map_lgl(m, ~ .x$homestead     %||% NA),
  roll_second_home = !is.na(homestead) & !homestead &
                     (coalesce(owner_country, "USA") != "USA" | coalesce(owner_state, "FL") != "FL"))

# =============================================================================
# 5. One verdict per client
# =============================================================================
state_code <- function(x) {
  x <- str_squish(coalesce(x, ""))
  up <- toupper(x)
  case_when(up %in% c(state.abb, "DC", names(CANADA)) ~ up,
            tolower(x) %in% tolower(state.name)       ~ state.abb[match(tolower(x), tolower(state.name))],
            tolower(x) %in% tolower(CANADA)           ~ names(CANADA)[match(tolower(x), tolower(CANADA))],
            TRUE ~ na_if(up, ""))
}

NORTH_US <- c("CT","DE","IL","IN","IA","KS","ME","MD","MA","MI","MN","MO","NE","NH","NJ",
              "NY","ND","OH","PA","RI","SD","VT","WI","WV","DC","WA","OR","ID","MT","WY",
              "CO","UT","AK","KY","VA")
region_of <- function(state, country) case_when(
  !is.na(country) & !(toupper(country) %in% c("USA", "US", "UNITED STATES")) & toupper(country) != "CANADA" ~ "Overseas",
  toupper(coalesce(country, "")) == "CANADA" | state %in% names(CANADA)         ~ "Canada",
  state %in% NORTH_US                                                            ~ "Northern US",
  state == "FL"                                                                  ~ "Florida",
  !is.na(state)                                                                  ~ "Other US",
  TRUE ~ NA_character_)

best_prop <- props %>%
  group_by(client_id) %>%
  # A client with several properties: the most informative match wins.
  arrange(desc(roll_second_home), desc(!is.na(homestead))) %>%
  summarise(n_properties  = n(),
            match_result  = first(match_result),
            county        = first(county),
            parcel_id     = first(parcel_id),
            owner_name    = first(owner_name),
            owner_city    = first(owner_city),
            owner_state   = first(owner_state),
            owner_country = first(owner_country),
            homestead     = first(homestead),
            roll_second_home = first(roll_second_home),
            property_address = first(str_squish(paste(prop_street1, coalesce(prop_street2, ""), prop_city))),
            .groups = "drop")

db <- clients %>%
  left_join(best_prop, by = "client_id") %>%
  mutate(
    bill_state   = state_code(bill_province),
    bill_country = case_when(is.na(bill_country) ~ NA_character_,
                             str_detect(toupper(bill_country), "^(US|USA|UNITED STATES)") ~ "USA",
                             TRUE ~ toupper(bill_country)),
    bill_away    = (!is.na(bill_state) & bill_state != "FL") |
                   (!is.na(bill_country) & bill_country != "USA"),
    # Does the name on the tax roll look like our client? A mismatch usually
    # means a trust, an LLC or a spouse - or that our client rents.
    name_on_roll = if_else(is.na(owner_name) | is.na(last_name), NA,
                           str_detect(toupper(owner_name), fixed(toupper(str_squish(last_name))))),

    status = case_when(
      homestead %in% TRUE & bill_away   ~ "Check: homesteaded here but bills go out of state",
      homestead %in% TRUE               ~ "Year-round resident",
      roll_second_home %in% TRUE & (bill_away | name_on_roll %in% TRUE) ~ "Second home - confirmed",
      roll_second_home %in% TRUE        ~ "Second home - likely (roll only)",
      bill_away                         ~ "Second home - likely (billing address only)",
      TRUE                              ~ "Unknown"),

    snowbird     = str_starts(status, "Second home"),
    home_state   = if_else(roll_second_home %in% TRUE,
                           coalesce(state_code(owner_state), bill_state), bill_state),
    home_country = if_else(roll_second_home %in% TRUE, coalesce(owner_country, bill_country), bill_country),
    home_region  = region_of(home_state, home_country),
    evidence = pmap_chr(list(roll_second_home, homestead, owner_city, owner_state, owner_country,
                             bill_away, bill_state, county, match_result, name_on_roll),
      function(rsh, hs, oc, os, oco, ba, bs, cty, mr, nm) {
        bits <- c(
          if (isTRUE(rsh)) sprintf("%s County roll: no homestead, tax mail to %s", cty,
                                   str_squish(paste(str_to_title(coalesce(oc, "")),
                                                    if (!is.na(oco) && oco != "USA") str_to_title(oco) else coalesce(os, "")))),
          if (isTRUE(hs)) sprintf("%s County roll: homestead exemption", cty),
          if (!is.na(mr) && !str_starts(mr, "matched")) paste("Roll:", mr),
          if (isTRUE(nm == FALSE)) "owner name on roll differs from client",
          if (isTRUE(ba)) sprintf("Jobber billing address in %s", bs))
        if (length(bits) == 0) "no evidence either way" else paste(bits, collapse = "; ")
      })
  )

# =============================================================================
# 6. When will each snowbird be back?
# =============================================================================
fc <- read_csv("output/season_forecast.csv", show_col_types = FALSE)

# Collier and Lee do not share a season. Collier opens around mid-November and
# troughs in September; Lee opens about a month earlier and troughs in JUNE.
# Judging a Fort Myers client against Naples' curve is simply the wrong date,
# so each client is measured against their own county. R/09 writes one row per
# county; "Pooled" is dropped because it describes no county in particular.
fc_by_county <- if (file.exists("output/season_forecast_by_county.csv")) {
  read_csv("output/season_forecast_by_county.csv", show_col_types = FALSE) %>%
    filter(scope != "Pooled")
} else NULL

# Falls back to the headline forecast when we have no roll for that county -
# better a neighbouring county's opening than no date at all.
start_doy_for <- function(cty) {
  hit <- if (!is.null(fc_by_county)) {
    fc_by_county$start_doy[match(cty, fc_by_county$scope)]
  } else rep(NA_real_, length(cty))
  coalesce(as.numeric(hit), as.numeric(fc$start_doy))
}

county_label <- function(cty) {
  hit <- if (!is.null(fc_by_county)) {
    fc_by_county$scope[match(cty, fc_by_county$scope)]
  } else rep(NA_character_, length(cty))
  paste0(coalesce(hit, as.character(fc$county %||% "the area")), " County")
}
cond <- if (file.exists("data/current_conditions.csv"))
  read_csv("data/current_conditions.csv", show_col_types = FALSE) %>% { setNames(as.list(.$value), .$key) } else list()

# The season this resend belongs to runs 1 Aug -> 31 Jul. Once the season has
# ended (after the model's end date) we are planning for the NEXT one.
season_year <- year(TODAY) - (month(TODAY) < 8)
season_end  <- as.Date(paste0(season_year + 1, "-01-01")) + fc$end_doy - 1
if (TODAY > season_end) season_year <- season_year + 1
season_anchor <- as.Date(paste0(season_year, "-08-01"))
area_return   <- as.Date(paste0(season_year, "-01-01")) + fc$start_doy - 1
season_end    <- as.Date(paste0(season_year + 1, "-01-01")) + fc$end_doy - 1

north_anom <- suppressWarnings(as.numeric(cond$north_anom %||% NA))
lean <- if (is.na(north_anom)) "" else
  if (north_anom <= -0.5) " Up north is running cold this year, which leans arrivals earlier." else
  if (north_anom >=  0.5) " Up north is running warm this year, which leans arrivals later." else ""

# Their own autumn habit: in each past season, the first quote or job between
# 1 Sep and 31 Jan, as days after 1 Aug.
activity <- bind_rows(
  quotes %>% transmute(client_id, day = as_day(created_at)),
  jobs   %>% transmute(client_id, day = coalesce(as_day(start_at), as_day(created_at)))) %>%
  filter(!is.na(day), day < season_anchor) %>%
  mutate(season = year(day) - (month(day) < 8),
         md     = format(day, "%m-%d"),
         in_window = md >= RETURN_WINDOW[["start"]] | md <= RETURN_WINDOW[["end"]]) %>%
  filter(in_window) %>%
  group_by(client_id, season) %>%
  summarise(first_day = min(day), .groups = "drop") %>%
  mutate(offset = as.numeric(first_day - as.Date(paste0(season, "-08-01")))) %>%
  group_by(client_id) %>%
  summarise(seasons_seen = n(), typical_offset = round(median(offset)), .groups = "drop")

# A first contact only proves they were around BY that date - they may have
# arrived weeks earlier and simply not needed anything. Two or more seasons
# landing in the same place is a habit worth trusting on its own. One season
# is not: take whichever is earlier, that date or the area forecast, so a
# single mid-winter job cannot push a resend past the start of the season.
db <- db %>%
  left_join(activity, by = "client_id") %>%
  mutate(
    own_date = season_anchor + typical_offset,
    area_return = as.Date(paste0(season_year, "-01-01")) + start_doy_for(county) - 1,
    area_where  = county_label(county),
    predicted_return = case_when(
      !snowbird                               ~ as.Date(NA),
      coalesce(seasons_seen, 0L) >= 2         ~ own_date,
      coalesce(seasons_seen, 0L) == 1         ~ pmin(own_date, area_return),
      TRUE                                    ~ area_return),
    return_basis = case_when(
      !snowbird ~ NA_character_,
      coalesce(seasons_seen, 0L) >= 2 ~
        sprintf("Their own habit: first autumn contact around %s, median of %d past seasons.",
                format(own_date, "%d %b"), seasons_seen),
      coalesce(seasons_seen, 0L) == 1 & own_date <= area_return ~
        sprintf("One past season, first contact around %s - earlier than %s's season opening (%s), so their date is used.",
                format(own_date, "%d %b"), area_where, format(area_return, "%d %b")),
      coalesce(seasons_seen, 0L) == 1 ~
        sprintf("One past season, first contact not until %s. That only shows they were here by then, so %s's season opening (%s) is used instead.%s",
                format(own_date, "%d %b"), area_where, format(area_return, "%d %b"), lean),
      TRUE ~ sprintf("No past autumn contact on file, so the area forecast: %s's season opens around %s.%s",
                     area_where, format(area_return, "%d %b"), lean))
  )

# =============================================================================
# 7. The resend plan
# =============================================================================
# %m-% steps whole months without rolling past the end of a short one.
OLDEST_QUOTE <- TODAY %m-% months(MAX_QUOTE_AGE_MONTHS)

plan_all <- quotes %>%
  filter(status %in% OUTSTANDING) %>%
  inner_join(db %>% filter(snowbird), by = "client_id", suffix = c("", "_client")) %>%
  mutate(
    quote_created  = as_day(created_at),
    quote_age_days = as.numeric(TODAY - quote_created),
    # A quote with no readable creation date fails the age check rather than
    # skipping it - we cannot show it is inside the limit, so it does not go.
    excluded_because = case_when(
      is_org                       ~ org_reason,
      is.na(quote_created)         ~ "no creation date on the quote, so its age cannot be checked",
      quote_created < OLDEST_QUOTE ~ sprintf("quote is %d days old, past the %d-month limit",
                                             as.integer(round(quote_age_days)), MAX_QUOTE_AGE_MONTHS),
      TRUE                         ~ NA_character_)
  )

excluded <- plan_all %>%
  filter(!is.na(excluded_because)) %>%
  transmute(client = name, quote_number, quote_title = title, quote_status = status,
            quote_created, quote_age_days, total, excluded_because, jobber_link) %>%
  arrange(excluded_because, desc(total))

plan <- plan_all %>%
  filter(is.na(excluded_because)) %>%
  mutate(
    ideal     = predicted_return - LEAD_DAYS,
    resend_on = case_when(ideal >= TODAY ~ ideal,
                          TODAY <= season_end ~ TODAY,
                          TRUE ~ ideal),
    timing = case_when(
      ideal >= TODAY ~ sprintf("%d days before they are due back (%s).", LEAD_DAYS, format(predicted_return, "%d %b %Y")),
      TODAY <= season_end ~ sprintf("Send now: they were due back around %s and the season runs to %s.",
                                    format(predicted_return, "%d %b"), format(season_end, "%d %b %Y")),
      TRUE ~ "Season over - resend before next season."),
    total_10pct_off = round(total * (1 - DISCOUNT), 2)
  ) %>%
  arrange(resend_on, desc(total)) %>%
  # The join leaves two 'status' columns: the quote's, and the client's
  # snowbird verdict (suffixed _client).
  transmute(resend_on, client = name, snowbird_status = status_client,
            northern_home = coalesce(home_state, home_country), home_region, predicted_return,
            quote_id, quote_number, quote_title = title, quote_status = status,
            # Only quotes the client simply hasn't answered are sent
            # automatically. 'Changes requested' means they asked for edits -
            # a discount email is the wrong reply, so a person handles those.
            auto_send = if_else(status == "awaiting_response", "yes", "no - changes requested, handle manually"),
            quote_created, quote_age_days,
            # Always "no" - organisations never reach this table. The column
            # exists so auto_send.R can re-check rather than trust the file.
            client_is_company = if_else(is_org, "yes", "no"),
            total, total_10pct_off,
            why_this_date = paste(timing, return_basis), evidence, property_address, jobber_link)

client_out <- db %>%
  transmute(client = name, company, is_org, org_reason,
            status, snowbird, home_state, home_country, home_region,
            predicted_return, return_basis, evidence, n_properties, property_address, county,
            parcel_id, homestead, owner_city, owner_state, owner_country, name_on_roll,
            bill_city, bill_state, bill_country, seasons_seen, client_link) %>%
  arrange(desc(snowbird), status, client)

write_csv(client_out, file.path(OUT_DIR, "client_second_homes.csv"), na = "")
write_csv(plan,       file.path(OUT_DIR, "quote_resend_plan.csv"),   na = "")
write_csv(excluded,   file.path(OUT_DIR, "excluded_from_plan.csv"),   na = "")

# =============================================================================
# 8. Plain-English summary
# =============================================================================
not_seasonal <- quotes %>% filter(status %in% OUTSTANDING) %>%
  anti_join(db %>% filter(snowbird), by = "client_id")

cat("\n==================== SNOWBIRD CLIENTS ====================\n")
print(count(client_out, status, name = "clients"), n = Inf)
cat("\nWhere the second homes are:\n")
print(client_out %>% filter(snowbird) %>% count(home_region, home_state, sort = TRUE, name = "clients"), n = 15)
cat("\nProperty rolls used:", if (length(counties_loaded)) paste(str_to_title(counties_loaded), collapse = " + ") else "none", "\n")
if (!"lee" %in% counties_loaded)
  cat("  (Lee County roll not loaded - Lee clients are judged on billing address alone.)\n")
cat("Area forecast (", as.character(fc$county %||% "primary county"), "): season opens ",
    format(area_return, "%d %b %Y"), " | ", LEAD_DAYS, " day lead | ", DISCOUNT * 100, "% off\n", sep = "")
if (!is.null(fc_by_county)) {
  cat("Per-county openings used: ",
      paste(sprintf("%s %s", fc_by_county$scope,
                    format(as.Date(paste0(season_year, "-01-01")) + fc_by_county$start_doy - 1, "%d %b")),
            collapse = " | "), "\n", sep = "")
}

cat("\n==================== RESEND PLAN ====================\n")
if (nrow(plan) == 0) cat("No outstanding quotes belong to snowbird clients.\n") else {
  cat(nrow(plan), "outstanding quotes to snowbird clients, worth",
      scales::dollar(sum(plan$total, na.rm = TRUE)), "before discount\n\n")
  plan %>% count(resend_week = floor_date(resend_on, "week", week_start = 1), name = "quotes") %>%
    mutate(resend_week = format(resend_week, "week of %d %b %Y")) %>% print(n = Inf)
}
cat("\n", nrow(not_seasonal), " other outstanding quotes belong to year-round or unknown clients - no seasonal timing applies.\n", sep = "")

# Excluded quotes are reported, never silently dropped: a resend that vanishes
# with no explanation is indistinguishable from a bug.
cat("\n-------------------- EXCLUDED FROM THE PLAN --------------------\n")
if (nrow(excluded) == 0) cat("Nothing excluded.\n") else {
  cat(nrow(excluded), " snowbird quotes held back, worth ",
      scales::dollar(sum(excluded$total, na.rm = TRUE)), ":\n", sep = "")
  excluded %>%
    mutate(rule = case_when(
      str_detect(excluded_because, "^quote is |^no creation date") ~
        sprintf("older than %d months", MAX_QUOTE_AGE_MONTHS),
      TRUE ~ "business, HOA or trade client")) %>%
    count(rule, name = "quotes") %>% print(n = Inf)
  cat("\nThe ten largest:\n")
  excluded %>% arrange(desc(total)) %>% slice_head(n = 10) %>%
    transmute(client, quote_number,
              total = scales::dollar(total), excluded_because) %>%
    as.data.frame() %>% print(row.names = FALSE)
}
if (length(manual_list) == 0) {
  cat("\nNo do-not-send list found at ", MANUAL_EXCLUDE,
      " - add one (a single column of client names or ids) for any HOA or\n",
      "business whose name gives no clue, such as a community called Autumn Woods.\n", sep = "")
} else {
  cat("\nDo-not-send list: ", length(manual_list), " entries from ", MANUAL_EXCLUDE, "\n", sep = "")
}

cat("\nFiles:", file.path(OUT_DIR, "client_second_homes.csv"), ",",
    file.path(OUT_DIR, "quote_resend_plan.csv"), "and",
    file.path(OUT_DIR, "excluded_from_plan.csv"), "\n")
