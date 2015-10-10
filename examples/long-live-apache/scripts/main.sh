#!/bin/sh -e

set -x

# copy some info to the instance with SCP:
{{SCP}} ./some/local/file {{IP|node1}}:

# Do some extra wotk on the instance:
{{SSH|node1}} ./some-remote-command.sh
