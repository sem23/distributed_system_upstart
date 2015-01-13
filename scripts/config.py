#!/usr/bin/env python

# This program requires super-user privileges due to writing
# to /etc/init.
#
# DESIGN:
#
# -- upstart_script in /etc/init
#   -- starts zeroconf starter
#
# -- env_script in /home/{USER}/.ros/env/
#   -- loads ROS environment
#
# -- zeroconf starter_script in pkg dir
#   -- sources env script
#   -- starts either zeroconf master or slave

import os
import sys
import socket
import argparse
import getpass
import errno
import subprocess

import rospkg
from catkin.find_in_workspaces import get_workspaces

# this is just a global setting now, maybe its configurable later...
ZEROCONF_SUFFIX = '.local'


def check_settings():
    global is_master
    global user
    global iface
    global ws_path
    global master_hostname
    global hostname
    print 'Settings:'
    print '  Master:', is_master
    print '  User:', user
    print '  Master Hostname:', master_hostname
    print '  Client Hostname:', hostname
    print '  Interface:', iface
    print '  Workspace:', ws_path
    correct = None
    while type(correct) is not bool:
        correct = raw_input('Are these settings correct (y/n): ')
        if correct == 'y' or correct == 'n':
            correct = True if correct is 'y' else False
        else:
            print 'ERROR: You can only answer with "y" or "n".'.format(len(workspaces))
    return correct


def create_starter_script(user, pkg_path, is_master):
    """
    Create starter bash script.
    """
    template = [
        '#!/bin/bash',
        '',
        'source /home/{}/.ros/env/distributed_ros.bash'.format(user),
        'python {}/scripts/distributed_ros_{}'.format(pkg_path, 'master' if is_master else 'slave'),
    ]
    return '\n'.join(template)


def create_upstart_script(iface, is_master, pkg_path):
    """
    Create upstart service script.
    """
    template = [
        'description "Distributed ROS autostart"',
        'author "semael23@gmail.com"',
        '',
        'start on (local-filesystems and net-device-up IFACE={})'.format(iface),
        'stop on (runlevel [016] or platform-device-changed)',
        '',
        'respawn',
        '',
        'env ROSLAUNCH_SSH_UNKNOWN=1',
        '',
        'exec {}/scripts/starter.bash'.format(pkg_path),
    ]
    return '\n'.join(template)


def create_env_setup_script(ws_path, master_hostname, hostname):
    """
    Create ROS environment setup script.
    """
    template = [
        '#!/bin/bash',
        '',
        'source {}/setup.bash'.format(ws_path),
        '',
        'export ROS_MASTER_URI="http://{}.local:11311"'.format(master_hostname),
        'export ROS_HOSTNAME="{}.local"'.format(hostname),
        '',
        'export ROSLAUNCH_SSH_UNKNOWN=1',
        '',
        'exec "$@"',
    ]
    return '\n'.join(template)


# args
parser = argparse.ArgumentParser()
group = parser.add_mutually_exclusive_group(required=True)
group.add_argument('-m', '--master', action="store_true", help='Configure this machine as a distributed ROS master.')
group.add_argument('-s', '--slave', action="store_true", help='Configure this machine as a distributed ROS slave.')
group.add_argument('-c', '--clean', action="store_true", help='Remove all startup/configuration files.')
parser.add_argument('-i', '--interface', help='Configure network device on which service will wait till it starts.')
args = parser.parse_args()

# get username
user = getpass.getuser()

# get hostname
hostname = socket.gethostname()

# get package path
rospack = rospkg.RosPack()
pkg_path = rospack.get_path('distributed_system_upstart')

# check clean
if args.clean:
    if os.path.exists('/home/{}/.ros/env/distributed_env.bash'.format(user)):
        os.remove('/home/{}/.ros/env/distributed_env.bash'.format(user))
        print 'Removed environment setup script.'
    if os.path.exists('{}/scripts/starter.bash'.format(pkg_path)):
        os.remove('{}/scripts/starter.bash'.format(pkg_path))
        print 'Removed starter script.'
    if os.path.exists('/etc/init/distributed-ros.conf'):
        command = "rm /etc/init/distributed-ros.conf"
        subprocess.call(["/usr/bin/sudo", "sh", "-c", command])
        print 'Removed upstart script.'
    print "Done."
    sys.exit(0)

# check master
is_master = args.master
print 'Configuring {} as {}.'.format(hostname, 'MASTER' if is_master else 'SLAVE')
if not is_master:
    # build ROS_MASTER_URI from master hostname as zeroconf address
    master_hostname = raw_input('ROS master hostname: ')
    if master_hostname.endswith(ZEROCONF_SUFFIX):
        print 'WARNING: zeroconf suffix "{}" is auto-appended.'.format(ZEROCONF_SUFFIX)
        master_hostname = master_hostname[0:-len(ZEROCONF_SUFFIX)]
else:
    master_hostname = str(hostname)

# check interface
if args.interface:
    iface = args.interface
    try:
        import netifaces
        ifaces = netifaces.interfaces()
        if iface not in ifaces:
            print 'WARNING: Given interface ({}) not found in current interfaces ({}).'.format(iface, ', '.join(ifaces))
    except:
        print 'WARNING: Could not check if interface exists. Install python-netifaces to fix this problem.'
else:
    print 'Interface not provided (option -i INTERFACE): Set to default "eth0".'
    iface = 'eth0'

# get workspace path
workspaces = get_workspaces()
if len(workspaces) > 1:
    print 'More than one workspace found on system. Select desired one by number:'
    for i in range(len(workspaces)):
        print '{}. {}'.format(i+1, workspaces[i])
    number = 0
    repeat = True
    while repeat:
        failed = False
        try:
            number = int(raw_input('Workspace nr.: '))
            if 0 <= number-1 < len(workspaces):
                repeat = False
            else: failed = True
        except:
            failed = True
        if failed: print 'ERROR: Number should be an integer between: 1-{}'.format(len(workspaces))
    ws_path = workspaces[number-1]
else:
    ws_path = workspaces[0]

# check settings before write
print 'Verify settings (if settings are correct, files are written to their designated places):'
if check_settings():

    # write upstart script (utilizing sudo)
    upstart_script = create_upstart_script(iface, is_master, pkg_path)
    try:
        command = "echo '{}' >> /etc/init/distributed-ros.conf".format(upstart_script)
        subprocess.call(["/usr/bin/sudo", "sh", "-c", command])
    except:
        raise

    # write starter script
    starter_script = create_starter_script(user, pkg_path, is_master)
    with open('{}/scripts/starter.bash'.format(pkg_path), 'w+') as f:
        f.write(starter_script)

    # write environment script
    env_setup_script = create_env_setup_script(ws_path, master_hostname, hostname)
    if not os.path.exists('/home/{}/.ros/env'.format(user)):
        os.mkdir('/home/{}/.ros/env'.format(user))
    with open('/home/{}/.ros/env/distributed_ros.bash'.format(user), 'w+') as f:
        f.write(env_setup_script)

    print 'Finished writing files. Done.'

else:
    print 'Done. Nothing written to disk.'
