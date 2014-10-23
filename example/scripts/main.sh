#!/bin/sh

set -e
set -x

{{SSH|node1}} ip a

{{SSH|node2}} ip a

curl -v "http://{{IP|node1}}/"

curl -v "http://{{IP|node2}}/"
