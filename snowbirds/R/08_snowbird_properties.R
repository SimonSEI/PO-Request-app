# =============================================================================
# 08 - MEASURING SNOWBIRDS DIRECTLY
# =============================================================================
# THE PROBLEM THIS FIXES
#
# Script 06 weighted origin states using IRS migration records. That data only
# sees people who CHANGE THEIR TAX ADDRESS - i.e. people who stopped being
# northerners. A classic snowbird does the exact opposite: they buy in Naples
# and deliberately keep the northern domicile. The instrument was structurally
# blind to the population we care about.
#
# THE FIX
#
# Florida property tax rolls record, for every parcel:
#   - where the owner receives mail  (OwnerState, OwnerCountry)
#   - whether they claim a HOMESTEAD EXEMPTION
#
# A homestead exemption is a sworn declaration that this Florida property is
# your permanent residence. So:
#
#   residential parcel + owner mail goes out of state + NO homestead exemption
#       = a second home someone lives in part of the year
#       = a snowbird property, by definition
#
# This is not a proxy. It is the thing itself.
#
# WHAT IT ALSO RECOVERS: Canadians. IRS data cannot see them - no US tax
# return. Ontario turns out to own more Naples property than Indiana or
# Minnesota. The original guess of "Toronto" was right, and the IRS-based
# correction that removed it was wrong.
#
# DATA: Collier County Property Appraiser, "int_parcels" CSV
#       https://www.collierappraiser.com/Main_Data/DataDownloads.html
#       (~33 MB zip -> 168 MB CSV, tax year 2026 preliminary roll)
# =============================================================================

library(tidyverse)

PARCELS <- "C:/Users/SWeardon/AppData/Local/Temp/claude/C--Users-SWeardon-Desktop-Coding-in-R/56267a43-4d94-42e8-8b39-eef1ca5d0ec4/scratchpad/int_parcels.csv"

# From the county's own int_usecodes lookup. These are the codes people
# actually live in; everything else is commercial, farm, government or vacant.
RESIDENTIAL <- c("1", "2", "4", "5")   # single family, mobile home, condo, co-op

# -----------------------------------------------------------------------------
# 1. Read only the columns we need
# -----------------------------------------------------------------------------
# The full file is 168 MB and ~100 columns. col_select reads just these, which
# turns a slow job into a quick one. Always ask for what you need, not
# everything followed by select().
parcels <- read_csv(
  PARCELS,
  col_select = c(ParcelId, UseCode, OwnerCountry, OwnerState, OwnerCity,
                 HmstdExemptAmount, TotalJustValue, SiteCity),
  col_types = cols(.default = col_character()),
  progress = FALSE
) %>%
  mutate(
    homestead = !is.na(as.numeric(HmstdExemptAmount)) &
                 as.numeric(HmstdExemptAmount) > 0,
    value     = as.numeric(TotalJustValue),
    country   = str_trim(toupper(coalesce(OwnerCountry, "USA"))),
    state     = str_trim(toupper(OwnerState))
  )

message(format(nrow(parcels), big.mark = ","), " parcels in the roll")

homes <- parcels %>% filter(UseCode %in% RESIDENTIAL)
message(format(nrow(homes), big.mark = ","), " residential parcels")

# -----------------------------------------------------------------------------
# 2. Classify every home
# -----------------------------------------------------------------------------
homes <- homes %>%
  mutate(
    category = case_when(
      homestead                          ~ "Permanent resident (homesteaded)",
      country != "USA"                   ~ "Foreign-owned second home",
      state == "FL"                      ~ "Florida-owned, not homesteaded",
      TRUE                               ~ "Out-of-state second home"
    )
  )

cat("\n=== Every home in Collier County ===\n")
homes %>%
  count(category) %>%
  mutate(share = paste0(round(100 * n / sum(n), 1), "%")) %>%
  arrange(desc(n)) %>%
  as.data.frame() %>% print(row.names = FALSE)

# The snowbird stock: a home here, a mailbox somewhere else, no declaration
# that Florida is home.
snowbirds <- homes %>%
  filter(!homestead, !(country == "USA" & state == "FL"))

cat("\nSnowbird-owned homes: ", format(nrow(snowbirds), big.mark = ","),
    " (", round(100 * nrow(snowbirds) / nrow(homes)), "% of all homes)\n", sep = "")

# -----------------------------------------------------------------------------
# 3. Where are they from? - the weights we actually wanted
# -----------------------------------------------------------------------------
# Canadian provinces sit in OwnerState too (ON, QC...), so treat the
# country+state pair as the origin and label it honestly.
origins <- snowbirds %>%
  mutate(
    origin = if_else(country == "USA", state, paste0(country, ":", state)),
    origin = if_else(is.na(state) | state == "",
                     paste0(country, ":unknown"), origin)
  ) %>%
  group_by(origin, country) %>%
  summarise(
    homes      = n(),
    total_value = sum(value, na.rm = TRUE),
    median_value = median(value, na.rm = TRUE),
    .groups = "drop"
  ) %>%
  arrange(desc(homes)) %>%
  mutate(share = homes / sum(homes))

write_csv(origins, "data/snowbird_origins.csv")

cat("\n=== Where Naples snowbirds actually keep their mailbox ===\n")
origins %>%
  slice_head(n = 20) %>%
  transmute(origin, homes,
            share = paste0(round(100 * share, 1), "%"),
            median_value = scales::comma(median_value)) %>%
  as.data.frame() %>% print(row.names = FALSE)

# -----------------------------------------------------------------------------
# 4. How different is this from the IRS picture?
# -----------------------------------------------------------------------------
if (file.exists("data/origin_states.csv")) {
  irs <- read_csv("data/origin_states.csv", show_col_types = FALSE) %>%
    transmute(origin = state, irs_share = share)

  compare <- origins %>%
    filter(country == "USA") %>%
    mutate(prop_share = homes / sum(homes)) %>%
    select(origin, homes, prop_share) %>%
    full_join(irs, by = "origin") %>%
    mutate(
      prop_share = replace_na(prop_share, 0),
      irs_share  = replace_na(irs_share, 0),
      diff_pp    = 100 * (prop_share - irs_share)
    ) %>%
    arrange(desc(prop_share)) %>%
    slice_head(n = 15)

  cat("\n=== Property records vs IRS migration (US states only) ===\n")
  compare %>%
    transmute(
      State = origin,
      `Property %` = round(100 * prop_share, 1),
      `IRS %`      = round(100 * irs_share, 1),
      `Diff (pp)`  = round(diff_pp, 1)
    ) %>%
    as.data.frame() %>% print(row.names = FALSE)

  write_csv(compare, "output/origin_comparison.csv")
}

# -----------------------------------------------------------------------------
# 5. Save weights the temperature model can use
# -----------------------------------------------------------------------------
# Match the shape script 06 produced, so downstream code can swap one for the
# other. US states only here: mapping a whole country to one temperature point
# would be meaningless, and Ontario is handled separately below.
state_weights <- origins %>%
  filter(country == "USA", !is.na(origin), nchar(origin) == 2, origin != "FL") %>%
  transmute(state = origin, people = homes) %>%
  mutate(share = people / sum(people)) %>%
  arrange(desc(people))

write_csv(state_weights, "data/snowbird_state_weights.csv")

cat("\nSaved weights for ", nrow(state_weights), " states.\n", sep = "")
cat("Top 12 cover ",
    round(100 * sum(slice_head(state_weights, n = 12)$share)), "% of US snowbird homes\n", sep = "")

# And the thing IRS data could never show us:
ontario <- origins %>% filter(origin == "CANADA:ON")
if (nrow(ontario) > 0) {
  us_rank <- sum(state_weights$people > ontario$homes) + 1
  cat("\nOntario alone owns ", format(ontario$homes, big.mark = ","),
      " Naples homes - which would rank #", us_rank,
      " if it were a US state.\n", sep = "")
  cat("IRS migration data records this as zero.\n")
}
