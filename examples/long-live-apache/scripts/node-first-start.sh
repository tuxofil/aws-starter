#!/bin/sh -e

set -x

# Update apt-get indices:
apt-get update

# Do not ask any questions during upgrade/install:
export DEBIAN_FRONTEND=noninteractive

# Upgrade instance software to the latest versions:
apt-get -y dist-upgrade

# Install all required software to the instance:
apt-get -y install apache2
