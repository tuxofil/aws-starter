# One-shot task example

## Summary

* start two instances: t1.micro (node1) and m1.small (node2);
* run script/node-first-start.sh script on each and redirect output to logs/node{1,2}.log;
* run script/main.sh script, which runs 'ip a' at node1 and 'ip a' at node2;
* terminate the instances.

## Before you start

* set access_key_id, secret_access_key, image_id, subnet_id in the aws-starter.cfg;
* copy SSH identity file to ssh/access-key.pem.

## How to start

```
aws-starter aws-starter.cfg
```
