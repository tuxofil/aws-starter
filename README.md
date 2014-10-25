# Automation tool for Amazon AWS

Purpose:

* start one or more Amazon instances;
* configure each started instance;
* run some code, using access to the instances via SSH;
* terminate the instances

## Synopsis

```
aws-starter.py [-h|--help] [-p|--pause] [--no-terminate] [--no-terminate-on-error] [-v VERBOSITY] config_path
```

Positional arguments:

* _config_path_ - Path to configuration file.

Optional arguments:

* _-h, --help_ - Show this help message and exit.
* _-p, --pause_ - Wait until user press the ENTER key after
 the super script and before termination of the instances.
* _--no-terminate_ - Do not terminate the instances after
 the work is done. The instances WILL be terminated when
 an error occurs.
* _--no-terminate-on-error_ - Do not terminate the instances
 after an error has been occured. This is useful to make able
 the user to investigate the problem on the instances.
* _-v VERBOSITY, --verbosity VERBOSITY_ - Verbosity level.
 Default is "info". Possible values are: "debug", "info",
 "warning", "error", "critical".
