#!/bin/sh

set -e
set -x

{{SSH|node1}} ip a

{{SSH|node2}} ip a
