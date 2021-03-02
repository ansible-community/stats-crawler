#!/usr/bin/env python3

# takes a JSON file of objects and a target collection to upload to
# TODO - assumes a "number" field to construct the ID, won't work for other crawls
# TODO - add proper environment-based auth in MongoClient call
#
# Example:
# ./import_to_mongo.py --collection issues ./issues.json

import argparse
import json
import yaml
import sys
import pymongo
import os
from packaging import version

dirname = os.path.dirname(__file__)
configname = os.path.join(dirname, '../config/crawler.yml')
if version.parse(yaml.__version__) < version.parse("5"):
    with open(configname, "r") as f:
        config = yaml.load(f)
else:
    with open(configname, "r") as f:
        config = yaml.load(f, Loader=yaml.FullLoader)

user   = config['default']['mongo']['user']
passwd = config['default']['mongo']['password']
ip     = config['default']['mongo']['ip']
port   = config['default']['mongo']['port']
url    = "mongodb://" + user + ":" + passwd + "@" + ip + ":" + port + "/ansible_collections"

parser = argparse.ArgumentParser()
parser.add_argument('--collection')
parser.add_argument('file', type=argparse.FileType('r'), default=sys.stdin,
                            nargs='?')
args = parser.parse_args()

myclient = pymongo.MongoClient(url)
mydb = myclient["ansible_collections"]
mycol = mydb[args.collection]

items = json.load(args.file)

for item in items:
    id = item['repository']['nameWithOwner'] + '/' + str(item['number'])
    item['_id'] = id
    mycol.replace_one({'_id':id}, item, upsert = True)
