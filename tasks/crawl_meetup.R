# Top-level script for the Meetup crawler
# Called from cron
# Written to give a high-level view of the process

# This also runs the meetupr Auth process...
source(here::here('lib/meetup.R'))

# Ensure library is correct
renv::restore()

meetups <- read_meetups_yaml()
crawl_meetup_groups(meetups) -> group_result
crawl_meetup_events()        -> event_result
#  crawl_meetup_members() %>% # TODO: is this needed?
summary_of_crawl(group_result, event_result)
