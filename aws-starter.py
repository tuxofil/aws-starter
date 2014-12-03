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

VARS = {'ERROR_OCCURED': False,
        'PAUSE': False,
        'PAUSE_ON_ERROR': False,
        'NO_TERMINATE': False,
        'NO_TERMINATE_ON_ERROR': False}

# Logging interface object
LOGGER = logging.getLogger('AmazonStarter')
logging.basicConfig(
    format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt = '%Y-%m-%d %H:%M:%S',
    level = 20)

# where new instance IDs will be registered
INSTANCES = {}


class InstanceLaunchError(Exception):
    """
    Raises when thread fails to launch and prepare an instance.
    """
    pass


def connect():
    """
    Create connection to Amazon AWS API.
    Access requisites will be taken from global vars:
     - ACCESS_KEY_ID;
     - SECRET_ACCESS_KEY;
     - REGION_NAME.

    :rtype: instance of boto.ec2.Connection
    """
    LOGGER.debug(
        'connecting to %s region...', VARS['REGION_NAME'])
    # search region info
    region_info = None
    for region in boto.ec2.regions():
        if region.name == VARS['REGION_NAME']:
            region_info = region
            break
    # connect to Amazon AWS API
    connection = boto.connect_ec2(
        aws_access_key_id = VARS['ACCESS_KEY_ID'],
        aws_secret_access_key = VARS['SECRET_ACCESS_KEY'],
        region = region_info)
    LOGGER.debug('connected')
    return connection


def launch_catched(*args):
    """
    A wrapper for the launch() function.
    Just set a global VARS['ERROR_OCCURED'] flag on any exception.
    """
    try:
        launch(*args)
    except Exception as exc:
        VARS['ERROR_OCCURED'] = True
        LOGGER.exception(exc)


def launch(instance_name, instance_type, image_id, subnet_id,
           max_wait_time, script = None, script_log = None,
           ssh_config = None, private_ip = None, ssh_key_name = None):
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
    :type max_wait_time: integer
    :param script: path to script to run on the instance after
        the very first start
    :type script: string or NoneType
    :param script_log: path to file which will be used to redirect
        all the output of the script.
    :type script_log: string or NoneType
    :param ssh_config: path to SSH config file
    :type ssh_config: string or NoneType
    :param private_ip: private IP to assign with the instance.
    :type private_ip: string or NoneType
    :param ssh_key_name: name of the SSH key on the Amazon side
        to access to the instance.
    :type ssh_key_name: string or NoneType
    :rtype: (string, string) or NoneType
    """
    connection = connect()
    LOGGER.debug(
        'launching %s from AMI %s (with subnet %s)...',
        instance_type, image_id, subnet_id)
    reservation = connection.run_instances(
        image_id = image_id,
        key_name = ssh_key_name,
        instance_type = instance_type,
        subnet_id = subnet_id,
        private_ip_address = private_ip)
    instance = reservation.instances[0]
    INSTANCES[instance_name]['instance_id'] = instance.id
    LOGGER.info(
        'launched %s at %s. Wait until it starts...',
        instance.id, VARS['REGION_NAME'])
    wait_for_instance(instance, instance.id, max_wait_time)
    if VARS['ERROR_OCCURED']:
        return
    LOGGER.info('instance %s started', instance.id)
    map_instance_to_ip_addrs(connection, instance_name, instance.id)
    if script is not None:
        wait_for_sshd(instance_name, max_wait_time)
        LOGGER.info(
            'running script %r on the %s...',
            script, instance4log(instance_name))
        if not execute_script_remotely(
                INSTANCES[instance_name]['ip_address'],
                script, script_log, ssh_config):
            LOGGER.error(
                '%s: failed to run script %r',
                instance4log(instance_name), script)
            if script_log is not None:
                LOGGER.error(
                    '%s: see details in log file: %r',
                    instance4log(instance_name), script_log)
            raise InstanceLaunchError
    if VARS['ERROR_OCCURED']:
        return
    # mark instance as up and ready with special flag field
    INSTANCES[instance_name]['ready'] = True


def wait_for_sshd(instance_name, max_wait_time):
    """
    Wait for the SSHD on the instance for some time.

    :param instance_name: instance name (from config file)
    :type instance_name: string
    :param max_wait_time: max time to wait, in seconds
    :type max_wait_time: integer
    """
    LOGGER.info(
        'wait for SSHD on %s...', instance4log(instance_name))
    start_time = time.time()
    deadline = start_time + max_wait_time
    while True:
        if VARS['ERROR_OCCURED']:
            raise InstanceLaunchError
        if time.time() > deadline:
            LOGGER.error(
                'timeout waiting for SSHD at %s within %r seconds',
                instance4log(instance_name), max_wait_time)
            raise InstanceLaunchError
        if ping_tcp(INSTANCES[instance_name]['ip_address'], 22):
            break
        time.sleep(5)


def instance4log(instance_name):
    """
    Generate formatted string representing instance with given name.

    :param instance_name: instance name (from config file)
    :type instance_name: string
    :rtype: string
    """
    return '"%s" (id=%s, ip=%s, priv_ip=%s)' % \
        (instance_name,
         INSTANCES[instance_name].get('instance_id'),
         INSTANCES[instance_name].get('ip_address'),
         INSTANCES[instance_name].get('private_ip_address'))


def wait_for_instance(instance, instance_id, max_wait_time):
    """
    Wait until the instance status become 'running'.

    :param instance: Amazon instance object
    :type instance: instance of boto.ec2.Instance
    :param instance_id: Amazon instance unique ID
    :type instance_id: string
    :param max_wait_time: max time to wait, in seconds
    :type max_wait_time: integer
    """
    start_time = time.time()
    deadline = start_time + max_wait_time
    while True:
        if time.time() > deadline:
            LOGGER.error(
                'instance %s failed to start within %r seconds',
                instance_id, max_wait_time)
            raise InstanceLaunchError
        if instance.update() == 'running':
            break
        time.sleep(5)


def map_instance_to_ip_addrs(connection, instance_name, instance_id):
    """
    Map Amazon instance to public and private IP addresses.
    The addresses will be stored in the INSTANCES global var.

    :param connection: connection to Amazon AWS API
    :type connection: instance of boto.ec2.Connection
    :param instance_name: name of the instance (from config file)
    :type instance_name: string
    :param instance_id: Amazon instance ID
    :type instance_id: string
    """
    reservations = connection.get_all_instances([instance_id])
    instances = [instance
                 for reservation in reservations
                 for instance in reservation.instances
                 if instance.id == instance_id]
    if len(instances) != 1:
        LOGGER.error(
            'launched instance %s is not found',
            instance_id)
        raise InstanceLaunchError
    # look for a private IP address
    private_ip_address = instances[0].private_ip_address
    if private_ip_address is None:
        LOGGER.error(
            'failed to get private IP address for instance %s',
            instance_id)
        raise InstanceLaunchError
    private_ip_address = str(private_ip_address)  # dispose of unicode string
    INSTANCES[instance_name]['private_ip_address'] = private_ip_address
    LOGGER.info(
        'instance %s has private IP %s',
        instance_id, private_ip_address)
    # look for a public IP address
    ip_address = instances[0].ip_address
    if ip_address is None:
        LOGGER.error(
            'failed to get public IP address for instance %s',
            instance_id)
        raise InstanceLaunchError
    ip_address = str(ip_address)  # dispose of unicode string
    INSTANCES[instance_name]['ip_address'] = ip_address
    LOGGER.info(
        'instance %s has public IP %s',
        instance_id, ip_address)


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
    except socket.error:
        return False


def pause_if_requested():
    """
    Make a pause until the user press the ENTER key,
    if such behaviour was requested by the user with
    corresponding command line options.
    The function is registered as atexit trigger and
    must run before the terminate_all() function.
    """
    if (VARS['PAUSE'] and not VARS['ERROR_OCCURED']) or \
            (VARS['PAUSE_ON_ERROR'] and VARS['ERROR_OCCURED']):
        LOGGER.info('MAIN> press ENTER to terminate')
        sys.stdin.readline()


def terminate_all():
    """
    Terminate all Amazon instances, registered in INSTANCES
    global dictionary.
    """
    instance_ids = \
        [INSTANCES[instance_name]['instance_id']
         for instance_name in INSTANCES
         if 'instance_id' in INSTANCES[instance_name]]
    if VARS['NO_TERMINATE'] and not VARS['ERROR_OCCURED']:
        LOGGER.warning(
            'instances %r WILL NOT be terminated' % instance_ids)
        return
    if VARS['NO_TERMINATE_ON_ERROR'] and VARS['ERROR_OCCURED']:
        LOGGER.warning(
            'instances %r WILL NOT be terminated' % instance_ids)
        return
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
    # parse command line args
    cmd_args = parse_cmd_args()
    VARS['PAUSE'] = cmd_args.pause
    VARS['PAUSE_ON_ERROR'] = cmd_args.pause_on_error
    VARS['NO_TERMINATE'] = cmd_args.no_terminate
    VARS['NO_TERMINATE_ON_ERROR'] = cmd_args.no_terminate_on_error
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
        level = verbosities.get(cmd_args.verbosity, 20))
    # read the configuration file
    config = parse_config_file(cmd_args.config_path)
    # setup termination hook
    atexit.register(terminate_all)
    atexit.register(pause_if_requested)
    LOGGER.info('MAIN> start instances...')
    threads = []
    for instance_name in INSTANCES:
        args = INSTANCES[instance_name]
        thread = threading.Thread(
            target = launch_catched,
            args = [instance_name, args['instance_type'],
                    args['image_id'], args['subnet_id'],
                    args['max_wait_time'], args['script'],
                    args['script_log'], args['ssh_config'],
                    args['requested_private_ip'],
                    args['ssh_key_name']])
        thread.start()
        threads.append(thread)
    LOGGER.info('MAIN> wait for the threads...')
    for thread in threads:
        thread.join()
    LOGGER.info('MAIN> check launch results...')
    for instance_name in INSTANCES:
        instance = INSTANCES[instance_name]
        if not instance.get('ready', False):
            VARS['ERROR_OCCURED'] = True
            LOGGER.critical(
                'MAIN> instance %r is not ready (id=%r; ip=%r)',
                instance_name, instance.get('instance_id'),
                instance.get('ip_address'))
            sys.exit(1)
    LOGGER.info('MAIN> all instances is up and ready')
    # print instance addresses table
    max_name_len = max([len(name) for name in INSTANCES])
    LOGGER.info(
        'MAIN>   %s\tInstance ID\tPrivate IP\tPublic IP' %
        'Nodename'.ljust(max_name_len))
    for instance_name in sorted(INSTANCES.keys()):
        LOGGER.info(
            'MAIN>   %s\t%s\t%s\t%s' %
            (instance_name.ljust(max_name_len),
             INSTANCES[instance_name]['instance_id'],
             INSTANCES[instance_name]['private_ip_address'],
             INSTANCES[instance_name]['ip_address']))
    # launch super script if defined
    if config['super_script'] is not None:
        LOGGER.info(
            'MAIN> substituting macros in %r...',
            config['super_script'])
        new_super_script = config['super_script'] + '.substituted'
        substitute_macros(
            config['super_script'], new_super_script,
            config['ssh_config'])
        LOGGER.info('MAIN> running super script %r...', new_super_script)
        if cmd([new_super_script], config['super_log']):
            LOGGER.info('MAIN> super script %r done', new_super_script)
        else:
            VARS['ERROR_OCCURED'] = True
            LOGGER.critical(
                'MAIN> super script %r failed', new_super_script)
            if config['super_log'] is not None:
                LOGGER.error(
                    'MAIN> see %r for details', config['super_log'])
            sys.exit(1)


def parse_cmd_args():
    """
    Parse command line arguments and return
    an object with parsed tool arguments.

    :rtype: object
    """
    parser = argparse.ArgumentParser(
        description = 'Do some work with Amazon instances.')
    parser.add_argument(
        '-p', '--pause',
        action = 'store_true',
        help = 'wait until user press the ENTER key after the super'
        ' script and before termination of the instances.'
        ' In case of an error no pause will be made.')
    parser.add_argument(
        '--pause-on-error',
        action = 'store_true',
        help = 'wait until user press the ENTER key before'
        ' termination of the instances when an error occurs.')
    parser.add_argument(
        '--no-terminate',
        action = 'store_true',
        help = 'do not terminate the instances after the work is'
        ' done. The instances WILL be terminated when an error occurs.')
    parser.add_argument(
        '--no-terminate-on-error',
        action = 'store_true',
        help = 'do not terminate the instances after an error has'
        ' been occured. This is useful to make able the user to'
        ' investigate the problem on the instances.')
    parser.add_argument(
        '-v', '--verbosity',
        default = 'warn',
        help = 'verbosity level. Default is "info". Possible'
        ' values are: "debug", "info", "warning", "error", "critical".')
    parser.add_argument(
        'config_path',
        help = 'path to configuration file')
    return parser.parse_args()


def parse_config_file(config_path):
    """
    Parse the configuration file and initialize
    global variables.

    :param config_path: configuration file path
    :type config_path: string
    """
    cfg = ConfigParser.RawConfigParser(
        {'instance_type': 't1.micro'})
    cfg.read(config_path)
    VARS['ACCESS_KEY_ID'] = cfg.get('main', 'access_key_id')
    VARS['SECRET_ACCESS_KEY'] = cfg.get('main', 'secret_access_key')
    VARS['REGION_NAME'] = cfg.get('main', 'region')
    LOGGER.debug('MAIN> parse the rest of the configuration file...')
    for section in cfg.sections():
        if section == 'main':
            continue
        instance_type = \
            getcfg(cfg, section, 'instance_type', 'instance_type',
                   default = 't1.micro')
        image_id = getcfg(cfg, section, 'image_id', 'image_id')
        subnet_id = getcfg(cfg, section, 'subnet_id', 'subnet_id')
        ssh_key_name = getcfg(cfg, section, 'ssh_key_name', 'ssh_key_name')
        private_ip = getcfg(cfg, section, 'private_ip')
        max_wait_time = \
            int(getcfg(cfg, section, 'max_wait_time', 'max_wait_time',
                       default = '120'))
        INSTANCES[section] = \
            {'instance_type': instance_type,
             'image_id': image_id,
             'subnet_id': subnet_id,
             'max_wait_time': max_wait_time,
             'script': getcfg(cfg, section, 'script', 'script'),
             'script_log': getcfg(cfg, section, 'script_log'),
             'ssh_config': getcfg(cfg, 'main', 'ssh_config'),
             'requested_private_ip': private_ip,
             'ssh_key_name': ssh_key_name}
    return {
        'super_script': getcfg(cfg, 'main', 'super_script'),
        'super_log': getcfg(cfg, 'main', 'super_log'),
        'ssh_config': getcfg(cfg, 'main', 'ssh_config')}


def getcfg(cfg, section, item, main_item = None, default = None):
    """
    Return a value for configuration item from the config file.
    If main_item arg is defined, a corresponding item in the
    configs 'main' section will be looked up when no item
    found in the requested section.
    If no explicit value was found in the section nor in the
    main section, default value will be returned.

    :param cfg: config object
    :type cfg: instance of ConfigParser
    :param section: config section name
    :type section: string
    :param item: section item name
    :type item: string
    :param main_item: item in the 'main' section
    :type main_item: string or NoneType
    :param default: default value for the item
    :type default: string or NoneType
    :rtype: string or None
    """
    try:
        return cfg.get(section, item)
    except ConfigParser.NoOptionError:
        if main_item is not None:
            return getcfg(cfg, 'main', item, default = default)
        return default


def substitute_macros(infile, outfile, ssh_config):
    """
    Take a super script template from infile, substitute macros with
    real values and write it to the outfile.

    Next macroses will be substituted:
     - {{SSH|nodename}} -> "ssh node_ip" or "ssh -F ssh_config node_ip";
     - {{SCP}} -> "scp" or "scp -F ssh_config";
     - {{PRIV_IP|nodename}} -> instance_private_ip;
     - {{IP|nodename}} -> instance_public_ip.

    :param infile: path to super script template.
    :type infile: string
    :param outfile: path to final super script.
    :type outfile: string
    :param ssh_config: path to SSH config.
    :type ssh_config: string or NoneType
    """
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
        # replace {{SCP}} macros
        if ssh_config is not None:
            replacement = 'scp -F %s' % ssh_config
        else:
            replacement = 'scp'
        body = body.replace('{{SCP}}', replacement)
        # replace {{PRIV_IP|nodename}} macros
        body = body.replace(('{{PRIV_IP|%s}}' % instance_name),
                            instance['private_ip_address'])
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
    except Exception as exc:
        VARS['ERROR_OCCURED'] = True
        LOGGER.exception(exc)
        sys.exit(1)
