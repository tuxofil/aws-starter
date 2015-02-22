# Automation tool for Amazon AWS

[![Join the chat at https://gitter.im/tuxofil/aws-starter](https://badges.gitter.im/Join%20Chat.svg)](https://gitter.im/tuxofil/aws-starter?utm_source=badge&utm_medium=badge&utm_campaign=pr-badge&utm_content=badge)

Purpose:

* start one or more Amazon instances;
* configure each started instance;
* run some code, using access to the instances via SSH;
* terminate the instances

## Synopsis

To show usage help:

```sh
aws-starter -h
```

To start instances:

```sh
aws-starter [options] config_path
```

Positional arguments:

* _config_path_ - Path to configuration file.

Optional arguments:

* _-h, --help_ - Show this help message and exit.
* _-p, --pause_ - Wait until user press the ENTER key after
 the super script and before termination of the instances.
 In case of an error no pause will be made.
* _--pause-on-error_ - Wait until user press the ENTER key
 before termination of the instances when an error occurs.
* _--no-terminate_ - Do not terminate the instances after
 the work is done. The instances WILL be terminated when
 an error occurs.
* _--no-terminate-on-error_ - Do not terminate the instances
 after an error has been occured. This is useful to make able
 the user to investigate the problem on the instances.
* _-v VERBOSITY, --verbosity VERBOSITY_ - Verbosity level.
 Default is "info". Possible values are: "debug", "info",
 "warning", "error", "critical".

## Instance features

Each instance started with _aws-starter_ have the following features:

* _instance_initiated_shutdown_behaviour_ option is set to
 _terminate_ which means the instance will be terminated after
 a shutdown initiated within the instance (i.e. by ```poweroff```
 command line tool);
* a set of standard tags will be set, e.g.
  * _Name_ - instance name defined in the ```aws-starter.cfg``` file;
  * _StartedBy_ - effective user name and short hostname where
   the aws-starter tool was launched;
  * _StarterProg_ - 'aws-starter';
  * _StarterHost_ - ```uname -a``` string.
