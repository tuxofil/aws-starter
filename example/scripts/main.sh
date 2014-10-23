#!/bin/sh

set -e
set -x

# ssh to the launched instances and do some remote work
{{SSH|node1}} ip a

{{SSH|node2}} ip a

# talk to the launched instances by their IP addresses
curl -v "http://{{IP|node1}}/"

curl -v "http://{{IP|node2}}/"

# send a file to the instance via SCP
{{SCP}} ./some/local/file {{IP|node1}}:

# play with instance private IPs
echo "Private address of node1 is {{PRIV_IP|node1}}"
