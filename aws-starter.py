#!/usr/bin/env python

"""
Launch some Amazon instances, do some work
and stop the instances.
"""


import argparse
import atexit
import ConfigParser
import logging
import os.path
import socket
import subprocess
import sys
import time
import threading
import boto
import boto.ec2


# ----------------------------------------------------------------------
# Global vars

# Amazon AWS access requisites
ACCESS_KEY_ID = None
SECRET_ACCESS_KEY = None
REGION_NAME = None

# Logging interface object
LOGGER = logging.getLogger()

# where new instance IDs will be registered
INSTANCES = {}


def connect():
    """
    Create connection to Amazon AWS API.
    Access requisites will be taken from global vars:
     - ACCESS_KEY_ID;
     - SECRET_ACCESS_KEY;
     - REGION_NAME.

    :rtype: instance of boto.ec2.Connection
    """
    global ACCESS_KEY_ID, SECRET_ACCESS_KEY, REGION_NAME
    global LOGGER
    LOGGER.debug('connecting to %s region...', REGION_NAME)
    # search region info
    region_info = None
    for region in boto.ec2.regions():
        if region.name == REGION_NAME:
            region_info = region
            break
    # connect to Amazon AWS API
    connection = boto.connect_ec2(
        aws_access_key_id = ACCESS_KEY_ID,
        aws_secret_access_key = SECRET_ACCESS_KEY,
        region = region_info)
    LOGGER.debug('connected')
    return connection


def launch(instance_name, instance_type, image_id, subnet_id,
           max_wait_time = None, script = None, script_log = None,
           ssh_config = None):
    """
    Launch a new instance.
    On success return tuple of an instance ID and instance public IP.
    Return NoneType in case of error.

    :param instance_name: instance name in the configuration file
    :type instance_name: string
    :param instance_type: Amazon instance type to launch
    :type instance_type: string
    :param image_id: base AMI ID to launch instance from
    :type image_id: string
    :param subnet_id: Amazon Subnet ID to associate with the instance
    :type subnet_id: string
    :param max_wait_time: max time (in seconds) to wait for
        instance to start.
    :type max_wait_time: integer or NoneType. Default is 120 (seconds).
    :param script: path to script to run on the instance after
        the very first start
    :type script: string or NoneType
    :param script_log: path to file which will be used to redirect
        all the output of the script.
    :type script_log: string or NoneType
    :param ssh_config: path to SSH config file
    :type ssh_config: string or NoneType
    :rtype: (string, string) or NoneType
    """
    global LOGGER
    global INSTANCES
    connection = connect()
    LOGGER.debug(
        'launching %s from AMI %s (with subnet %s)...',
        instance_type, image_id, subnet_id)
    reservation = connection.run_instances(
        image_id = image_id,
        instance_type = instance_type,
        subnet_id = subnet_id)
    instance = reservation.instances[0]
    instance_id = instance.id
    INSTANCES[instance_name]['instance_id'] = instance_id
    LOGGER.info('launched %s. Wait until it starts...', instance_id)
    if max_wait_time is None:
        max_wait_time = 120
    start_time = time.time()
    deadline = start_time + max_wait_time
    while True:
        if time.time() > deadline:
            LOGGER.error(
                'instance %s failed to start within %r seconds',
                instance_id, max_wait_time)
            return None
        if instance.update() == 'running':
            break
        time.sleep(5)
    LOGGER.info('instance %s started', instance_id)
    # Map instance ID to public IP
    reservations = connection.get_all_instances([instance_id])
    instances = [instance
                 for reservation in reservations
                 for instance in reservation.instances
                 if instance.id == instance_id]
    if len(instances) != 1:
        LOGGER.error(
            'launched instance %s is not found',
            instance_id)
        return None
    ip_address = instances[0].ip_address
    if ip_address is None:
        LOGGER.error(
            'failed to get public IP address for instance %s',
            instance_id)
        return None
    ip_address = str(ip_address)  # dispose of unicode string
    INSTANCES[instance_name]['ip_address'] = ip_address
    LOGGER.info(
        'instance %s has public IP %s',
        instance_id, ip_address)
    if script is not None:
        LOGGER.info(
            'wait for SSHD on %s (%s)...',
            instance_id, ip_address)
        start_time = time.time()
        deadline = start_time + max_wait_time
        while True:
            if time.time() > deadline:
                LOGGER.error(
                    'timeout waiting for SSHD at %s (%s) within %r seconds',
                    instance_id, ip_address, max_wait_time)
                return None
            if ping_tcp(ip_address, 22):
                break
            time.sleep(5)
        LOGGER.info(
            'running script %r on the %s (%s)...',
            script, instance_id, ip_address)
        if not execute_script_remotely(ip_address, script,
                                       script_log, ssh_config):
            LOGGER.error(
                '%s (%s): failed to run script %r',
                instance_id, ip_address, script)
            if script_log is not None:
                LOGGER.error(
                    '%s (%s): see details in log file: %r',
                    instance_id, ip_address, script_log)
            return None
    # mark instance as up and ready with special flag field
    INSTANCES[instance_name]['ready'] = True
    return (instance_id, ip_address)


def ping_tcp(host, port):
    """
    Test connectivity to remote TCP server.
    Return True if remote server is alive, False if not.

    :param host: hostname or IP address of the remote TCP server.
    :type host: string
    :param port: TCP port number of the remote server.
    :type port: integer
    :rtype: boolean
    """
    try:
        sock = socket.socket(type = socket.SOCK_STREAM)
        sock.settimeout(1)
        sock.connect((host, port))
        sock.close()
        return True
    except Exception:
        return False


def terminate_all():
    """
    Terminate all Amazon instances, registered in INSTANCES
    global dictionary.
    """
    global LOGGER
    global INSTANCES
    instance_ids = \
        [INSTANCES[instance_name]['instance_id']
         for instance_name in INSTANCES
         if 'instance_id' in INSTANCES[instance_name]]
    try:
        if len(instance_ids) > 0:
            connection = connect()
            LOGGER.info('terminating instances: %r...', instance_ids)
            connection.terminate_instances(instance_ids)
            # deregister terminated instances
            for instance in INSTANCES:
                if 'instance_id' in instance:
                    del instance['instance_id']
                if 'ip_address' in instance:
                    del instance['ip_address']
            LOGGER.info('instances terminated')
    except Exception as exc:
        LOGGER.critical(
            'failed to terminate instances %r: %r',
            instance_ids, exc)
        LOGGER.exception(exc)
        sys.exit(1)


def execute_script_remotely(host, script_path, script_log = None,
                            ssh_config = None):
    """
    Upload local script to a remote SSH server and run
    the script on the remote side.
    Return True if subprocess exited with 0 exit code and False otherwise.

    :param host: remote server hostname or IP address
    :type host: string
    :param script_path: path to file with the target script
    :type script_path: string
    :param script_log: path to file which will be used to redirect
        all the output of the target script.
    :type script_log: string or NoneType
    :param ssh_config: path to SSH config file
    :type ssh_config: string or NoneType
    :rtype: boolean
    """
    if not scp(script_path, host + ':', script_log, ssh_config):
        return False
    basename = os.path.basename(script_path)
    if not ssh(host, ['chmod', '755', basename], script_log, ssh_config):
        return False
    return ssh(host, ['./' + basename], script_log, ssh_config)


def ssh(host, command, script_log = None, ssh_config = None):
    """
    Invocate external command on a remote server via SSH.
    Return True if subprocess exited with 0 exit code and False otherwise.

    :param host: remote server hostname or IP address
    :type host: string
    :param command: command to execute on the remote side
    :type command: list of strings
    :param script_log: path to file which will be used to redirect
        all the output of the target script.
    :type script_log: string or NoneType
    :param ssh_config: path to SSH config file
    :type ssh_config: string or NoneType
    :rtype: boolean
    """
    final_command = ['ssh']
    if ssh_config is not None:
        final_command += ['-F', ssh_config]
    return cmd(final_command + [host] + command, script_log)


def scp(source_path, destination_path,
        script_log = None, ssh_config = None):
    """
    Invocate SCP process.
    Return True if subprocess exited with 0 exit code and False otherwise.

    :param source_path: path to source file
    :type source_path: string
    :param destination_path: path to destination file
    :type destination_path: string
    :param script_log: path to file which will be used to redirect
        all the output of the target script.
    :type script_log: string or NoneType
    :param ssh_config: path to SSH config file
    :type ssh_config: string or NoneType
    :rtype: boolean
    """
    final_command = ['scp']
    if ssh_config is not None:
        final_command += ['-F', ssh_config]
    return cmd(final_command + [source_path, destination_path], script_log)


def cmd(command, log_path = None):
    """
    Run external process.
    Return True if subprocess exited with 0 exit code and False otherwise.

    :param command: command line
    :type command: list of strings
    :param log_path: path to logfile to which all stdout and stderr
        will be redirected
    :type log_path: string or NoneType
    :rtype: boolean
    """
    global LOGGER
    LOGGER.debug('spawning command: %r...', command)
    if log_path is None:
        proc = subprocess.Popen(
            command, stdout = subprocess.PIPE,
            stderr = subprocess.PIPE,
            env = {'LC_ALL': 'C'},
            close_fds = True)
        (stdout_data, stderr_data) = proc.communicate()
        if stdout_data:
            for line in stdout_data.rstrip().split('\n'):
                LOGGER.info('STDOUT:   %r', line.rstrip())
        if stderr_data:
            for line in stderr_data.rstrip().split('\n'):
                LOGGER.warning('STDERR:   %r', line.rstrip())
    else:
        with open(log_path, 'a') as fdescr:
            proc = subprocess.Popen(
                command, stdout = fdescr, stderr = fdescr,
                env = {'LC_ALL': 'C'}, close_fds = True)
            _data = proc.communicate()
    retcode = proc.wait()
    if retcode == 0:
        LOGGER.debug('subprocess done')
    else:
        LOGGER.error('subprocess exited with %r', retcode)
    return retcode == 0


def main():
    """
    Entry point.
    """
    global ACCESS_KEY_ID, SECRET_ACCESS_KEY, REGION_NAME
    global LOGGER
    global INSTANCES
    # parse command line args
    parser = argparse.ArgumentParser(
        description = 'Do some work with Amazon instances.')
    parser.add_argument(
        '-v', '--verbosity',
        default = 'warn',
        help = 'verbosity level. Default is "info". Possible'
        ' values are: "debug", "info", "warning", "error", "critical".')
    parser.add_argument(
        'config_path',
        help = 'path to configuration file')
    args = parser.parse_args()
    # configure the Logger
    verbosities = {
        'critical': 50,
        'error': 40,
        'warning': 30,
        'info': 20,
        'debug': 10}
    logging.basicConfig(
        format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt = '%Y-%m-%d %H:%M:%S',
        level = verbosities.get(args.verbosity, 20))
    LOGGER = logging.getLogger('AmazonStarter')
    # read the configuration file
    config = ConfigParser.RawConfigParser(
        {'instance_type': 't1.micro'})
    config.read(args.config_path)
    # initialize global vars
    ACCESS_KEY_ID = config.get('main', 'access_key_id')
    SECRET_ACCESS_KEY = config.get('main', 'secret_access_key')
    REGION_NAME = config.get('main', 'region')
    def getOrNone(config, section, option):
        try:
            return config.get(section, option)
        except ConfigParser.NoOptionError:
            return None
    ssh_config = getOrNone(config, 'main', 'ssh_config')
    super_script = getOrNone(config, 'main', 'super_script')
    super_log = getOrNone(config, 'main', 'super_log')
    base_image_id = getOrNone(config, 'main', 'image_id')
    base_subnet_id = getOrNone(config, 'main', 'subnet_id')
    base_max_wait_time = getOrNone(config, 'main', 'max_wait_time')
    if base_max_wait_time is None:
        base_max_wait_time = 120
    base_max_wait_time = int(base_max_wait_time)
    base_script = getOrNone(config, 'main', 'script')
    # setup termination hook
    atexit.register(terminate_all)
    LOGGER.debug('MAIN> parse the rest of the configuration file...')
    for section in config.sections():
        if section == 'main':
            continue
        instance_type = config.get(section, 'instance_type')
        image_id = getOrNone(config, section, 'image_id')
        if not image_id:
            image_id = base_image_id
        subnet_id = getOrNone(config, section, 'subnet_id')
        if not subnet_id:
            subnet_id = base_subnet_id
        max_wait_time = getOrNone(config, section, 'max_wait_time')
        if not max_wait_time:
            max_wait_time = base_max_wait_time
        max_wait_time = int(max_wait_time)
        script = getOrNone(config, section, 'script')
        if not script:
            script = base_script
        script_log = getOrNone(config, section, 'script_log')
        INSTANCES[section] = \
            {'instance_type': instance_type,
             'image_id': image_id,
             'subnet_id': subnet_id,
             'max_wait_time': max_wait_time,
             'script': script,
             'script_log': script_log,
             'ssh_config': ssh_config}
    LOGGER.info('MAIN> start instances...')
    threads = []
    for instance_name in INSTANCES:
        args = INSTANCES[instance_name]
        thread = threading.Thread(
            target = launch,
            args = [instance_name, args['instance_type'],
                    args['image_id'], args['subnet_id'],
                    args['max_wait_time'], args['script'],
                    args['script_log'], args['ssh_config']])
        thread.start()
        threads.append(thread)
    LOGGER.info('MAIN> wait for the threads...')
    for thread in threads:
        thread.join()
    LOGGER.info('MAIN> check launch results...')
    for instance_name in INSTANCES:
        instance = INSTANCES[instance_name]
        if not instance.get('ready', False):
            LOGGER.critical(
                'MAIN> instance %r is not ready (id=%r; ip=%r)',
                instance_name, instance.get('instance_id'),
                instance.get('ip_address'))
            sys.exit(1)
    LOGGER.info('MAIN> all instances is up and ready')
    if super_script is not None:
        LOGGER.info('MAIN> substituting macros in %r...', super_script)
        new_super_script = super_script + '.substituted'
        substitute_macros(super_script, new_super_script, ssh_config)
        LOGGER.info('MAIN> running super script %r...', new_super_script)
        if cmd([new_super_script], super_log):
            LOGGER.info('MAIN> super script %r done', new_super_script)
        else:
            LOGGER.critical(
                'MAIN> super script %r failed', new_super_script)
            if super_log is not None:
                LOGGER.error('MAIN> see %r for details', super_log)
            sys.exit(1)


def substitute_macros(infile, outfile, ssh_config):
    """
    Take a super script template from infile, substitute macros with
    real values and write it to the outfile.

    Next macroses will be substituted:
     - {{SSH|nodename}} -> "ssh node_ip" or "ssh -F ssh_config node_ip";
     - {{IP|nodename}} -> node_ip.

    :param infile: path to super script template.
    :type infile: string
    :param outfile: path to final super script.
    :type outfile: string
    :param ssh_config: path to SSH config.
    :type ssh_config: string or NoneType
    """
    global INSTANCES
    with open(infile, 'r') as fdescr:
        body = fdescr.read()
    for instance_name in INSTANCES:
        instance = INSTANCES[instance_name]
        # replace {{SSH|nodename}} macros
        if ssh_config is not None:
            replacement = \
                'ssh -F %s %s' % (ssh_config, instance['ip_address'])
        else:
            replacement = \
                'ssh %s' % instance['ip_address']
        body = body.replace(('{{SSH|%s}}' % instance_name), replacement)
        # replace {{IP|nodename}} macros
        body = body.replace(('{{IP|%s}}' % instance_name),
                            instance['ip_address'])
    with open(outfile, 'w') as fdescr:
        fdescr.write(body)
    os.chmod(outfile, 0755)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
