# Functions & helpers for the Meetup crawler job

library(here)
library(config)
library(dplyr)
library(tidyr)
library(purrr)
library(meetupr)
library(mongolite)

# Auth
meetupr::meetup_auth(token = here::here('.httr-oauth.meetupr'))

read_meetups_yaml <- function() {
  # Load the meetups list
  config::get(file = here('config/meetups.yml'))
}

crawl_meetup_groups <- function(meetups) {

  fields = c('past_event_count','proposed_event_count','upcoming_event_count','topics')
  groups_s <- find_groups('Ansible', fields = fields)
  groups_t <- find_groups(topic_id = 1434182, fields = fields)
  groups <- rbind(groups_t, groups_s) %>%
    distinct(urlname, .keep_all = T) %>%
    filter(urlname %in% meetups$allowlist)

  # sanity tests on api data?
  groups %>%
    write_to_mongo('groups')
}

crawl_meetup_events <- function() {

  # Since we  have the groups in Mongo, lets use it
  groups <- mongo('groups', url = mongo_con() )$find(
    query = '{}',
    fields = '{"urlname":1}') %>%
    transmute(group.id = `_id`, urlname)

  events <- groups %>%
    rowwise() %>%
    mutate(upcoming  = map(urlname, ~get_events(.x, 'upcoming')),
           past      = map(urlname, ~get_events(.x, 'past')),
           cancelled = map(urlname, ~get_events(.x, 'cancelled')))

  # sanity tests on api data?
  events %>%
    tidyr::pivot_longer(c(upcoming, past, cancelled),
                        names_to = 'event_status', values_to = 'events') %>%
    unnest(cols = c(events)) %>%
    write_to_mongo('events')
}

summary_of_crawl <- function(group_result, event_result) {

  m <- mongo('cron', url = mongo_con() )
  m$update(
    '{"_id":"crawler"}',
    sprintf('{"$set":{"last_run": "%s"}}', Sys.time()),
    upsert = TRUE)
  m$disconnect()

  # For now just returns the results
  print(glue::glue('Meetups updated: {group_result$nInserted}'))
  print(glue::glue('Events updated:  {event_result$nInserted}'))

}

mongo_con <- function() {
  config <- config::get(file = here('config/crawler.yml'))

  user   = config$mongo$user
  passwd = config$mongo$password
  ip     = config$mongo$ip
  port   = config$mongo$port

  glue::glue("mongodb://{user}:{passwd}@{ip}:{port}/meetup")
}

write_to_mongo <- function(dataframe,table) {

  m <- mongo(table, url = mongo_con() )
  old_table <- m$find()

  # This is a fake upsert - we insert the new records with a temp key
  # and then read the whole table back. Where we have two copies, we
  # prefer new = TRUE, filter, drop, and write back

  dataframe %>% mutate(new = TRUE,
                       last_seen_by_us = Sys.time()) %>% m$insert()

  new_df <- m$find() %>% # keep _id field intact
    group_by(id) %>%
    arrange(new) %>%      # this is Logical, so FALSE (0) comes before TRUE (1)
    slice_tail(n=1) %>%   # thus the new entries (TRUE) are last, so slice_tail
    mutate(new=FALSE,     # Now we have 1 record per id, so set all to FALSE
           `_id` = glue::glue('{table}:{id}')) # Set a proper id key

  # Verify this looks sane
  # how?

  # Clear the DB - risky but upsert is *far* harder to get right
  # If we got this far then we already have a prepped dataframe ready to go
  # but just in case we'll save it locally.
  saveRDS(old_table, file = glue::glue('/tmp/meetup-{table}-pre.replace.rds'))

  m$remove('{}')
  m$insert(new_df)   # Insert the records
}
