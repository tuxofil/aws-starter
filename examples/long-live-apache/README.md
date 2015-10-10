# Long live Apache2 instance

## Summary

This example shows how to automate starting Amazon AWS
instance with Apache2 installed for relatively long time
period, and how to stop created instance. Start and stop are
made with two invocations of aws-starter tool, so you can
safely reboot your workstation between these invocations
(you will not loose started instance until you remove the
aws-starter.instance_ids file).

## Before you start

* set access_key_id, secret_access_key, image_id, subnet_id
 in the aws-starter.cfg;
* copy SSH identity file to ssh/access-key.pem.

## Starting

```
make
```

Under the hood:

* launch a new Amazon AWS instance;
* run scripts/node-first-start.sh script on the created instance;
* substitute macros in the scripts/main.sh and execute it locally;
* write instance ID to the local file 'aws-starter.instance_ids'.

## Stopping

```
make stop
```

Under the hood:

* read instance ID from the local file 'aws-starter.instance_ids';
* terminate the Amazon AWS instance with given ID.
