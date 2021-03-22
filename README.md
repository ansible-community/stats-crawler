# Stats Crawler

Primary indexer for the raw data used in the other stats reports and dashboards

A lot of the data we used is available via APIs with rate limits (such as
GitHub, Meetup, etc). It's preferrable to have that data locally, so we can
query it as often as we like. This project handles the import of the *primary*
(upstream) data sources.

The apps that depend on this data will be responsible for the creation of the
*secondary* data themselves - to put it all here would likely lead to many many
software dependencies and difficulty in getting it all to play nice.

# Basic Outline

There are 3 main directories:

## `config`

This directory contains the necessary input data for the vaious jobs to
function. In some cases these will be example files that are modified on the
production server, because they contain API keys, etc.

## `lib`

This directory holds the necessary functions and files for the jobs to run.
Most of the complexity of each job is to be found here.

## `tasks`

This holds a set of scripts which are to be executed by `cron`, and should be
vaguely readable even to those not familiar with the project. They will call
high-level functions defined in `lib` for each step of the task, so that the
flow of the job can be understood.

# Deployment

Currently there are two tasks (GitHub and Meetup), and they need to be set up in
cron manually. Run it with `Rscript path/to/task.R`, but be aware that the
project uses `renv` and will call `renv::restore` at the start of each run to
ensure it matches the lockfile.

Eventual plan is to have all the tasks represented in a simple Ansible playbook
which defines a system user and entries in that users `crontab` - each new task
would need a matching stanza in the playbook. This is still TBD.

# Contribution

All contribution is welcome, please open a PR

# License

GPL3
