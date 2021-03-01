# Functions & helpers for the crawler job

library(here)
library(config)
library(dplyr)
library(purrr)
library(mongolite)

read_collections_yaml <- function() {
  # Load the collection list, and convert to a data.frame
  collections <- config::get(file = here('config/collections.yml'))
  as.data.frame(t(sapply(collections, rbind))) %>%
    setNames(c(
      'Site', 'Org', 'Repo', 'Regex', 'NewCollections', 'MergeKey'))
}

crawl_each_repo <- function(collections) {
  # Load config
  config <- config::get(file = here('config/crawler.yml'))

  # Set token
  if (is.null(config$github_token)) {
    stop('Please set the GITHUB_TOKEN variable in the config')
  }
  Sys.setenv(GITHUB_TOKEN=config$github_token)

  # Create a cache dir
  dir.create(paste0(tempdir(),'/crawl'))
  setwd(paste0(tempdir(),'/crawl'))

  # The actual crawler is written in Python, shell out to it
  scan_repo <- function(org, repo) {
    if (interactive()) print(paste0('\nScanning:',org,'/',repo))
    system2(here('lib/crawl_issues_and_prs.py'),
            c('--git-org', org,
              '--git-repo', repo,
              '--all'),
            stdout = F, stderr = F)
  }
  scan_repo = possibly(scan_repo, otherwise = 1)

  result <- collections %>%
    select(Org, Repo) %>%
    mutate(exitcode = map2_int(.$Org, .$Repo, scan_repo))

  if (sum(result$exitcode) != 0) {
    stop('Errors during scanning repos!')
  }

  result
}

import_json_to_mongo <- function(scans) {
  # Likewise the code that imports the resulting JSON is in Python
  import_repo <- function(org, repo, type) {
    file = if_else(type == 'pulls', 'pull_requests.json', 'issues.json')
    path = paste0(org,'%',repo,'/', file)

    if (interactive()) print(paste0("\n\nImporting:",path))

    # Need to pass config here, or read it in Python
    system2(here('lib/crawl_import_to_mongo.py'),
            c('--collection', type, path),
            stdout = F, stderr = F)
  }
  import_repo = possibly(import_repo, otherwise = 1)

  # Check the exitcode column is all 0, and then proceed
  result <- scans %>%
    mutate(exit_issue = map2_int(.$Org, .$Repo, import_repo, 'issues'),
           exit_pulls = map2_int(.$Org, .$Repo, import_repo, 'pulls'))

  if (sum(result$exit_issue) != 0) {
    stop('Errors during importing issues!')
  }
  if (sum(result$exit_pulls) != 0) {
    stop('Errors during importing pull requests!')
  }

  result
}

summary_of_crawl <- function(imports) {
  # Function to summarise the results

  # If we got this far all is fine, so timestamp the DB
  config <- config::get(file = here('config/crawler.yml'))

  user   = config$mongo$user
  passwd = config$mongo$password
  ip     = config$mongo$ip
  port   = config$mongo$port
  url    = glue::glue("mongodb://{user}:{passwd}@{ip}:{port}/ansible_collections")

  m <- mongo('cron',url = url)
  m$update(
    '{"_id":"crawler"}', sprintf('{"$set":{"last_run": "%s"}}', Sys.time()),
    upsert = TRUE)
  m$disconnect()

  # For now just returns the df
  print(imports)

  # Cleanup
  setwd(here())
  unlink(paste0(tempdir(),'/crawl'), force = T, recursive = T)
}

