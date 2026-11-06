# Run from the repository root using the pinned R installation.
source("paper/R/common.R")
temp_path <- tempfile()
writeLines("hash-regression-fixture", temp_path)
expected <- paste(rep("b", 64), collapse = "")
# This filename header becomes exactly 64 hex digits under the old parser.
header <- paste0("XYZ", paste(rep("a", 64), collapse = ""), " :")
saved_system2 <- system2
system2 <- function(...) c(header, expected, "CertUtil: command completed successfully.")
stopifnot(identical(sha256_file(temp_path), expected))
system2 <- saved_system2
unlink(temp_path)

input <- file.path("workspace/runs/sa_25sp_observed_morris86_seed20261030_r30_refNguard_20261030",
                   "review_20261030/paper_data")
denied <- tryCatch({ read_single_seed_sa_bundle(input); FALSE }, error=function(e) {
  grepl("allow-unvalidated-demo", conditionMessage(e), fixed=TRUE)
})
stopifnot(denied)
bundle <- read_single_seed_sa_bundle(input, allow_demo=TRUE)
stopifnot(isTRUE(bundle$is_demo), sum(bundle$rankings$elbow_core)==10L,
          sum(bundle$rankings$display_core)==13L, nrow(bundle$effects)==430L,
          all(bundle$effects$n_valid==30L), !bundle$manifest$original_full_design_passed)
cat("PASS: SHA header regression, review gate, current bundle hashes and scope.\n")
