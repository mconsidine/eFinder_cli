#!/bin/bash -e

# Place app files in the image
install -d -m 755 /home/efinder/Solver
install -m 755 files/eFinder.py    /home/efinder/Solver/eFinder.py
install -m 755 files/install.sh    /home/efinder/install.sh
install -m 600 files/config.env    /home/efinder/config.env
chown -R efinder:efinder /home/efinder

# Install the first-boot runner service
install -m 644 files/firstrun.service /etc/systemd/system/firstrun.service
install -m 755 files/firstrun.sh      /usr/local/bin/firstrun.sh
systemctl enable firstrun.service
