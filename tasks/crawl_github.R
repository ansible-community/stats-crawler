# Top-level script for the GH crawler
# Called from cron
# Written to give a high-level view of the process

source(here::here('lib/crawler.R'))

# Ensure library is correct
renv::restore()

read_collections_yaml() %>%
  crawl_each_repo() %>%
  import_json_to_mongo() %>%
  summary_of_crawl()
