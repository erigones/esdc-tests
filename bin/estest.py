#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import re
import sys
import json
import time
import inspect

try:
    # noinspection PyUnresolvedReferences
    from fabric.api import local, abort, env
    # noinspection PyUnresolvedReferences
    from fabric.colors import red, green, yellow, cyan
    # noinspection PyUnresolvedReferences
    from fabric.main import main as _fabmain
except ImportError:
    sys.stderr.write('ERROR: No module named fabric\n'
                     'Please install the python fabric package (http://www.fabfile.org/)\n')
    sys.exit(99)

###############################################################################
# globals
###############################################################################

DEBUG = False
SELF = os.path.realpath(__file__)
ERIGONES_HOME = os.environ.get('ERIGONES_HOME', '/opt/erigones')
ES = os.path.join(ERIGONES_HOME, 'bin', 'es')
STATUS_CODES_OK = (200, 201)

TESTS_RUN = 0
TESTS_FAIL = 0
TESTS_WARN = 0

USER_TASK_PREFIX = ''  # Used by tests
ADMIN_TASK_PREFIX = ''

RE_TASK_PREFIX = re.compile(r'([a-zA-Z]+)')
DEFAULT_TASK_PREFIX = [None, 'e', '1', 'd', '1']

env.warn_only = True

if not os.path.exists(ES):
    sys.stderr.write('ERROR: %s does not exist\n' % ES)
    sys.exit(100)

###############################################################################
# helpers
###############################################################################


def _es(*argv):
    return local(ES + ' ' + ' '.join(argv), capture=True)


def _exp_compare(exp, text, equal=False):
    if isinstance(exp, dict):
        for i in exp.keys():
            if not _exp_compare(exp[i], text[i], True):
                return False
    elif isinstance(exp, (list, tuple)):
        for i in range(len(exp)):
            if not _exp_compare(exp[i], text[i], True):
                return False
    elif equal:
        if exp != text:
            return False
    else:
        if exp not in text:
            return False

    return True


def _test(cmd, exp, scode=200, rc=0, custom_test=None, dc='main'):
    caller = inspect.stack()[1][3]
    global TESTS_RUN
    TESTS_RUN += 1

    def log_fail(res, s=''):
        global TESTS_FAIL
        TESTS_FAIL += 1
        print(red('Test %s failed: %s' % (caller, s)))
        print(res)

    # noinspection PyUnusedLocal
    def log_warn(res, s=''):
        global TESTS_WARN
        TESTS_WARN += 1
        print(yellow('Test %s warning: %s' % (caller, s)))
        print(res)

    def log_ok(s=''):
        print(green('Test %s succeeded %s' % (caller, s)))

    if dc:
        cmd += ' -dc %s' % dc

    ret = False
    out = _es(cmd)

    if out.return_code != rc:
        log_fail(out, 'return_code='+str(out.return_code))
    else:
        # noinspection PyBroadException
        try:
            jout = json.loads(out)
        except:
            log_fail(out, 'json not parsed')
        else:
            try:
                if jout['status'] != scode:
                    raise ValueError('status code mismatch')
            except Exception as e:
                log_fail(out, str(e))
            else:
                text = jout['text']
                try:
                    if not _exp_compare(exp, text):
                        raise Exception('test structure not found')
                except Exception as e:
                    log_fail(out, str(e))
                else:
                    if custom_test:
                        try:
                            if custom_test(text):
                                log_ok()
                                ret = True
                            else:
                                log_fail(out, 'custom test failed')
                        except Exception as e:
                            log_fail(out, 'custom test got exception: ' + str(e))
                    else:
                        log_ok()
                        ret = True

    return ret


def _summary():
    print('''

*** Test summary ***
    Total:      %s
    Failed:     %s
    Warning:    %s
    Successful: %s
''') % (TESTS_RUN, red(TESTS_FAIL), yellow(TESTS_WARN), green(TESTS_RUN-(TESTS_FAIL+TESTS_WARN)))
    raise SystemExit(TESTS_FAIL)


def _remove_token_store():
    # noinspection PyBroadException
    try:
        os.remove('/tmp/esdc.session')
    except:
        pass


def _sleep(seconds):
    print(cyan('\n***\n* Taking a %s seconds break to avoid API throttling.\n***' % (seconds,)))
    i = 0
    while i < seconds:
        sys.stdout.write('.')
        sys.stdout.flush()
        time.sleep(1)
        i += 1
    print('\n')


def _task_prefix_from_task_id(task_id):
    """Get (user ID, task type, owner ID) tuple from task ID"""
    tp = RE_TASK_PREFIX.split(task_id[:-24])
    return tuple(tp + DEFAULT_TASK_PREFIX[len(tp):])


###############################################################################
# automatic test creation
###############################################################################

def test(name=''):
    """create test from stdin - pipe \"es -d\" into this"""
    if sys.stdin.isatty():
        abort(red('no stdin (pipe the output of es -d command)'))

    stdin = [line.strip() for line in sys.stdin.readlines()]
    if not stdin:
        abort(red('no stdin'))

    # noinspection PyBroadException
    try:
        jin = json.loads('\n'.join(stdin))
    except:
        abort(red('stdin json not parsed'))

    # noinspection PyBroadException
    try:
        # noinspection PyUnboundLocalVariable
        cmd, text, code = jin['command'], jin['text'], jin['status']
        # noinspection PyBroadException
        try:
            text.pop('task_id')
        except:
            pass
    except:
        abort(red('es output not parsed (missing -d option?)'))

    if not name:
        # noinspection PyBroadException
        try:
            # noinspection PyUnboundLocalVariable
            _cmd = cmd.split()
            _met = _cmd[0]
            _res = _cmd[1][1:].split('/')
            _mod = _res[0]
            _sub = '_'
            # noinspection PyBroadException
            try:
                _sub += '_'.join(_res[2:])
            except:
                pass
            # noinspection PyUnboundLocalVariable
            name = '%s%s_%s_%s' % (_mod, _sub, _met, code)
        except:
            abort(red('could not generate test name'))

    # noinspection PyUnboundLocalVariable
    print('''
def _%s():
    cmd = '%s'
    exp = %s
    _test(cmd, exp, %s, %d)
''') % (name, cmd, text, code, 0 if int(code) in STATUS_CODES_OK else 1)
    sys.exit(0)


###############################################################################
# ping
###############################################################################

def _ping():
    return _test('get /ping', 'pong', 200)


###############################################################################
# accounts tests
###############################################################################

def _accounts_login_user_good(username='test', password='lacodoma'):
    cmd = 'login -username %s -password %s' % (username, password)
    cod = 200
    exp = {"detail": "Welcome to Danube Cloud API."}
    _test(cmd, exp, cod)


def _accounts_login_admin_good(username='admin', password='changeme'):
    cmd = 'login -username %s -password %s' % (username, password)
    cod = 200
    exp = {"detail": "Welcome to Danube Cloud API."}
    _test(cmd, exp, cod)


def _accounts_user_create_test_201():
    cmd = 'create /accounts/user/test -password lacodoma -first_name Tester -last_name Tester ' \
          '-email tester1@erigones.com -api_access true'
    exp = {u'status': u'SUCCESS', u'result': {u'username': u'test', u'first_name': u'Tester', u'last_name': u'Tester',
                                              u'api_access': True, u'is_active': True, u'is_super_admin': False,
                                              u'callback_key': u'***', u'groups': [], u'api_key': u'***',
                                              u'email': u'tester1@erigones.com'}}
    _test(cmd, exp, 201)


def _accounts_user_delete_test_200():
    cmd = 'delete /accounts/user/test'
    exp = {u'status': u'SUCCESS', u'result': None}
    _test(cmd, exp, 200)


def _accounts_login_bad1():
    _test('login', {"detail": {"username": ["This field is required."],
                               "password": ["This field is required."]}}, 400, 4)


def _accounts_login_bad2():
    _test('login -password test', {"detail": {"username": ["This field is required."]}}, 400, 4)


def _accounts_login_bad3():
    _test('login -username test', {"detail": {"password": ["This field is required."]}}, 400, 4)


def _accounts_login_bad4():
    _test('login -username test -password test', {"detail": "Unable to log in with provided credentials."}, 400, 4)


def _accounts_logout_good():
    _test('logout', {"detail": "Bye."}, 200)


def _accounts_logout_bad():
    _remove_token_store()
    _test('logout', {"detail": "Authentication credentials were not provided."}, 403, 1)


def _accounts_delete_test_vm_relation_400():
    cmd = 'delete /accounts/user/test'
    exp = {u'status': u'FAILURE',
           u'result': {u'detail': u'Cannot delete user, because he has relations to some objects.',
                       u'relations': {u'VM': [u'test99.example.com']}}}
    _test(cmd, exp, 400, 1)


###############################################################################
# task tests
###############################################################################

def _set_user_task_prefix(text):
    # noinspection PyBroadException
    try:
        global USER_TASK_PREFIX
        USER_TASK_PREFIX = ''.join(_task_prefix_from_task_id(text['task_id']))
    except:
        return False
    else:
        return True


def _set_admin_task_prefix(text):
    # noinspection PyBroadException
    try:
        global ADMIN_TASK_PREFIX
        ADMIN_TASK_PREFIX = ''.join(_task_prefix_from_task_id(text['task_id']))
    except:
        return False
    else:
        return True


def _task_get_prefix(set_fun=_set_user_task_prefix):
    cmd = 'get /vm'
    exp = {'status': 'SUCCESS', 'result': []}

    _test(cmd, exp, 200, custom_test=set_fun)


def _user_task_prefix():
    assert USER_TASK_PREFIX, 'Run _task_get_prefix() first'
    return USER_TASK_PREFIX


def _admin_task_prefix():
    assert ADMIN_TASK_PREFIX, 'Run _task_get_prefix() first'
    return ADMIN_TASK_PREFIX


def _task__get_200():
    cmd = 'get /task'
    exp = []
    _test(cmd, exp, 200)


def _task_details_get_404_1():
    cmd = 'get /task/%s-0000-1111-aaaa-12345678' % _user_task_prefix()
    exp = {'detail': 'Task does not exist'}
    _test(cmd, exp, 404, 1)


def _task_details_get_403_1():
    cmd = 'get /task/%s-6f75849b-c9ca-42b1-968e' % _admin_task_prefix()
    exp = {u'detail': u'Permission denied'}
    _test(cmd, exp, 403, 1)


def _task_done_get_201():
    cmd = 'get /task/%s-0000-1111-aaaa-12345678/done' % _user_task_prefix()
    exp = {'done': False}
    _test(cmd, exp, 201)


def _task_done_get_403():
    cmd = 'get /task/%s-6f75849b-c9ca-42b1-968e/done' % _admin_task_prefix()
    exp = {u'detail': u'Permission denied'}
    _test(cmd, exp, 403, 1)


def _task_status_get_201():
    cmd = 'get /task/%s-0000-1111-aaaa-12345678/status' % _user_task_prefix()
    exp = {'status': 'PENDING', 'result': None}
    _test(cmd, exp, 201)


def _task_status_get_403():
    cmd = 'get /task/%s-6f75849b-c9ca-42b1-968e/status' % _admin_task_prefix()
    exp = {u'detail': u'Permission denied'}
    _test(cmd, exp, 403, 1)


def _task_cancel_set_406():
    cmd = 'set /task/%s-6f75849b-c9ca-42b1-968e/cancel' % _user_task_prefix()
    exp = {u'detail': u'Task cannot be canceled'}
    _test(cmd, exp, 406, 1)


def _task_cancel_set_403():
    cmd = 'set /task/%s-6f75849b-c9ca-42b1-968e/cancel' % _admin_task_prefix()
    exp = {u'detail': u'Permission denied'}
    _test(cmd, exp, 403, 1)


def _task__get_403():
    cmd = 'get /task'
    exp = {'detail': 'Authentication credentials were not provided.'}
    _test(cmd, exp, 403, 1)


def _task_done_get_logout_403():
    cmd = 'get /task/6-0000-1111-aaaa-12345678/done'
    exp = {'detail': 'Authentication credentials were not provided.'}
    _test(cmd, exp, 403, 1)


def _task_status_get_logout_403():
    cmd = 'get /task/6-0000-1111-aaaa-12345678/status'
    exp = {'detail': 'Authentication credentials were not provided.'}
    _test(cmd, exp, 403, 1)


def _task_log_get_200():
    cmd = 'get /task/log'
    exp = []
    _test(cmd, exp, 200)


def _task_log_last_get_200():
    cmd = 'get /task/log'
    exp = []
    _test(cmd, exp, 200)


def _task_log_get_logout_403():
    cmd = 'get /task/log'
    exp = {'detail': 'Authentication credentials were not provided.'}
    _test(cmd, exp, 403, 1)


def _task_log_0_get_logout_403():
    cmd = 'get /task/log -page 1'
    exp = {'detail': 'Authentication credentials were not provided.'}
    _test(cmd, exp, 403, 1)


###############################################################################
# vm tests
###############################################################################

def _vm__get_200():
    cmd = 'get /vm'
    exp = {'status': 'SUCCESS'}
    cst = lambda t: isinstance(t['result'], list)
    _test(cmd, exp, 200, custom_test=cst)


def _vm__get_403():
    cmd = 'get /vm'
    exp = {'detail': 'Authentication credentials were not provided.'}
    _test(cmd, exp, 403, 1)


def _vm__get_404():
    cmd = 'get /vm/test99.example.com'
    exp = {'detail': 'VM not found'}
    _test(cmd, exp, 404, 1)


def _vm__delete_404():
    cmd = 'delete /vm/test99.example.com'
    exp = {'detail': 'VM not found'}
    _test(cmd, exp, 404, 1)


def _vm__create_404():
    cmd = 'create /vm/test99.example.com'
    exp = {'detail': 'VM not found'}
    _test(cmd, exp, 404, 1)


def _vm_define_get_200():
    cmd = 'get /vm/define'
    exp = {'status': 'SUCCESS', 'result': []}
    _test(cmd, exp, 200)


def _vm_status_get_200():
    cmd = 'get /vm/status'
    exp = {'status': 'SUCCESS', 'result': []}
    _test(cmd, exp, 200)


def _vm_define_create_403():
    cmd = 'create /vm/test99.example.com/define'
    exp = {'detail': 'Permission denied'}
    _test(cmd, exp, 403, 1)


def _vm_define_disk_1_create_403():
    cmd = 'create /vm/test99.example.com/define/disk/1'
    exp = {'detail': 'Permission denied'}
    _test(cmd, exp, 403, 1)


def _vm_define_nic_1_create_403():
    cmd = 'create /vm/test99.example.com/define/nic/1'
    exp = {'detail': 'Permission denied'}
    _test(cmd, exp, 403, 1)


# no input
def _vm_define_create_400_1():
    cmd = 'create /vm/test99.example.com/define'
    exp = {'status': 'FAILURE', 'result': {'vcpus': ['This field is required.'], 'ram': ['This field is required.']}}
    _test(cmd, exp, 400, 1)


# low input
def _vm_define_create_400_2():
    cmd = 'create /vm/test99.example.com/define -ram 1 -vcpus 0 -ostype 0'
    exp = {'status': 'FAILURE', 'result': {'ostype': ['Select a valid choice. 0 is not one of the available choices.'],
                                           'vcpus': ['Ensure this value is greater than or equal to 1.'],
                                           'ram': ['Ensure this value is greater than or equal to 32.']}}
    _test(cmd, exp, 400, 1)


# large input
def _vm_define_create_400_3():
    cmd = 'create /vm/test99.example.com/define -ram 999999 -vcpus 999 -ostype 999 -template nil -owner nil ' \
          '-node nil -hostname xx -alias yy'
    exp = {'status': 'FAILURE',
           'result': {'node': ['Object with hostname=nil does not exist.'],
                      'ram': ['Ensure this value is less than or equal to 524288.'],
                      'hostname': ['Ensure this value has at least 4 characters (it has 2).'],
                      'owner': ['Object with username=nil does not exist.'],
                      'alias': ['Ensure this value has at least 4 characters (it has 2).'],
                      'vcpus': ['Ensure this value is less than or equal to 64.'],
                      'template': ['Object with name=nil does not exist.'],
                      'ostype': ['Select a valid choice. 999 is not one of the available choices.']}}
    _test(cmd, exp, 400, 1)


# large input vs. node resources
def _vm_define_create_400_4():
    cmd = 'create /vm/test99.example.com/define -alias test -owner test -node headnode.dev.erigones.com -ram 99999 ' \
          '-vcpus 24'
    exp = {'status': 'FAILURE', 'result': {'node': ['Not enough free vCPUs on node.', 'Not enough free RAM on node.']}}
    _test(cmd, exp, 400, 1)


def _vm_define_create_201_1():
    cmd = 'create /vm/test99.example.com/define -alias test -owner test -ram 99999 -vcpus 24'
    exp = {'status': 'SUCCESS', 'result': {'node': None, 'hostname': 'test99.example.com', 'ram': 99999, 'ostype': 1,
                                           'alias': 'test', 'vcpus': 24, 'template': None, 'owner': 'test'}}
    _test(cmd, exp, 201, 0)


def _vm_define_get_200_1():
    cmd = 'get /vm/test99.example.com/define'
    exp = {'status': 'SUCCESS', 'result': {'node': None, 'hostname': 'test99.example.com', 'ram': 99999, 'ostype': 1,
                                           'alias': 'test', 'vcpus': 24, 'template': None, 'owner': 'test'}}
    _test(cmd, exp, 200)


#
# vm_define_disk
#
def _vm_define_disk_1_create_400_1():
    cmd = 'create /vm/test99.example.com/define/disk/1 -boot true -image centos-6 -size 9999'
    exp = {'status': 'FAILURE', 'result': {'size': ['Cannot define smaller disk size than image size (10240).']}}
    _test(cmd, exp, 400, 1)


def _vm_define_disk_1_delete_200():
    cmd = 'delete /vm/test99.example.com/define/disk/1'
    exp = {'status': 'SUCCESS', 'result': None}
    _test(cmd, exp, 200)


def _vm_define_disk_1_create_201():
    cmd = 'create /vm/test99.example.com/define/disk/1 -boot true -size 51200'
    exp = {'status': 'SUCCESS', 'result': {'compression': 'lz4', 'image': None, 'boot': True, 'zpool': 'zones',
                                           'model': 'virtio', 'size': 51200}}
    _test(cmd, exp, 201)


def _vm_define_disk_2_create_400_1():
    cmd = 'create /vm/test99.example.com/define/disk/2'
    exp = {'status': 'FAILURE', 'result': {'size': ['This field is required.']}}
    _test(cmd, exp, 400, 1)


def _vm_define_disk_2_create_400_2():
    cmd = 'create /vm/test99.example.com/define/disk/2 -model nil -size nil -image nil -boot true ' \
          '-compression nil -zpool nil'
    exp = {'status': 'FAILURE',
           'result': {'model': ['Select a valid choice. nil is not one of the available choices.'],
                      'boot': ['Cannot set boot flag on disks other than first disk.'],
                      'compression': ['Select a valid choice. nil is not one of the available choices.'],
                      'image': ['Object with name=nil does not exist.'],
                      'size': ['Enter a whole number.']}}
    _test(cmd, exp, 400, 1)


def _vm_define_disk_3_create_406():
    cmd = 'create /vm/test99.example.com/define/disk/3 -size 512'
    exp = {'detail': 'VM disk out of range'}
    _test(cmd, exp, 406, 1)


def _vm_define_disk_2_create_201_1():
    cmd = 'create /vm/test99.example.com/define/disk/2 -size 3000 -compression gzip -model ide'
    exp = {'status': 'SUCCESS', 'result': {'compression': 'gzip', 'image': None, 'boot': False, 'zpool': 'zones',
                                           'model': 'ide', 'size': 3000}}
    _test(cmd, exp, 201)


def _vm_define_disk_2_set_200():
    cmd = 'set /vm/test99.example.com/define/disk/2 -size 9999998'
    exp = {'status': 'SUCCESS', 'result': {'size': 9999998}}
    _test(cmd, exp, 200)


def _vm_define_disk_2_set_400_3():
    cmd = 'set /vm/test99.example.com/define/disk/2 -image blabla'
    exp = {'status': 'FAILURE', 'result': {'image': ['Cannot set image on disks other than first disk.']}}
    _test(cmd, exp, 400, 1)


def _vm_define_disk_2_delete_200():
    cmd = 'delete /vm/test99.example.com/define/disk/2'
    exp = {'status': 'SUCCESS', 'result': None}
    _test(cmd, exp, 200)


#
# vm_define_nic
#
def _vm_define_nic_2_delete_200_0():
    cmd = 'delete /vm/test99.example.com/define/nic/1'
    exp = {'status': 'SUCCESS', 'result': None}
    _test(cmd, exp, 200)


def _vm_define_nic_1_create_400_1():
    cmd = 'create /vm/test99.example.com/define/nic/1 -ip nil -netmask nil -gateway nil -model nil -net nil'
    exp = {'status': 'FAILURE', 'result': {'ip': ['Enter a valid IPv4 address.'],
                                           'model': ['Select a valid choice. nil is not one of the available choices.'],
                                           'net': ['Object with name=nil does not exist.']}}
    _test(cmd, exp, 400, 1)


def _vm_define_nic_1_create_400_2():
    cmd = 'create /vm/test99.example.com/define/nic/1 -ip 1.1.1.1 -net lan'
    exp = {'status': 'FAILURE', 'result': {'ip': ['Object with name=1.1.1.1 does not exist.']}}
    _test(cmd, exp, 400, 1)


def _vm_define_nic_1_create_201():
    cmd = 'create /vm/test99.example.com/define/nic/1 -net lan -ip 10.10.91.30'
    exp = {'status': 'SUCCESS', 'result': {'ip': '10.10.91.30', 'gateway': '10.10.91.1',
                                           'netmask': '255.255.255.0', 'dns': True, 'model': 'virtio',
                                           'net': 'lan', 'mac': None}}
    _test(cmd, exp, 201)


def _vm_define_nic_2_create_400_3():
    cmd = 'create /vm/test99.example.com/define/nic/2 -ip 10.10.91.50 -netmask 0.0.0.0 -gateway 10.10.91.1'
    exp = {'status': 'FAILURE', 'result': {'net': ['This field is required.']}}
    _test(cmd, exp, 400, 1)


def _vm_define_nic_3_create_406():
    cmd = 'create /vm/test99.example.com/define/nic/3 -net lan'
    exp = {'detail': 'VM NIC out of range'}
    _test(cmd, exp, 406, 1)


def _vm_define_nic_1_get_200():
    cmd = 'get /vm/test99.example.com/define/nic/1'
    exp = {'status': 'SUCCESS', 'result': {'ip': '10.10.91.30', 'gateway': '10.10.91.1',
                                           'netmask': '255.255.255.0', 'dns': False, 'model': 'virtio',
                                           'net': 'lan', 'mac': None}}
    _test(cmd, exp, 200)


def _vm_define_nic_1_set_200_1():
    cmd = 'set /vm/test99.example.com/define/nic/1 -net lan'
    exp = {'status': 'SUCCESS', 'result': {'gateway': '10.10.91.1',
                                           'netmask': '255.255.255.0', 'dns': False, 'model': 'virtio',
                                           'net': 'lan', 'mac': None}}
    _test(cmd, exp, 200)


def _vm_define_nic_1_set_200_2():
    cmd = 'set /vm/test99.example.com/define/nic/1 -ip 10.10.91.31'
    exp = {'status': 'SUCCESS', 'result': {'ip': '10.10.91.31', 'gateway': '10.10.91.1',
                                           'netmask': '255.255.255.0', 'dns': False, 'model': 'virtio',
                                           'net': 'lan', 'mac': None}}
    _test(cmd, exp, 200)


def _vm_define_nic_2_create_400():
    cmd = 'create /vm/test99.example.com/define/nic/2 -net lan -ip 10.10.91.31'
    exp = {'status': 'FAILURE', 'result': {'ip': ['Object with name=10.10.91.31 is already taken.']}}
    _test(cmd, exp, 400, 1)


def _vm_define_nic_2_create_201():
    cmd = 'create /vm/test99.example.com/define/nic/2 -net lan -model e1000'
    exp = {'status': 'SUCCESS'}
    _test(cmd, exp, 201)


def _vm_define_nic_2_delete_200():
    cmd = 'delete /vm/test99.example.com/define/nic/2'
    exp = {'status': 'SUCCESS', 'result': None}
    _test(cmd, exp, 200)
#
#
#


# remove template
def _vm_define_set_200_1():
    cmd = 'set /vm/test99.example.com/define -template null'
    exp = {'status': 'SUCCESS', 'result': {'node': None, 'hostname': 'test99.example.com', 'ram': 99999, 'ostype': 1,
                                           'alias': 'test', 'vcpus': 24, 'template': None, 'owner': 'test'}}
    _test(cmd, exp, 200)


# set node later: larget input vs. node resources (cpu, ram, disk)
def _vm_define_set_400_1():
    cmd = 'set /vm/test99.example.com/define -node headnode.dev.erigones.com'
    exp = {'status': 'FAILURE', 'result': {'node': ['Not enough free disk space on storage with zpool=zones.',
                                                    'Not enough free vCPUs on node.',
                                                    'Not enough free RAM on node.',
                                                    'Not enough free disk space on node.']}}
    _test(cmd, exp, 400, 1)


# set template - values overridden by template values
def _vm_define_set_200_2():
    cmd = 'set /vm/test99.example.com/define -vcpus 2 -ram 4096'
    exp = {'status': 'SUCCESS', 'result': {'node': None, 'hostname': 'test99.example.com', 'ram': 4096, 'ostype': 1,
                                           'alias': 'test', 'vcpus': 2, 'template': None, 'owner': 'test'}}
    _test(cmd, exp, 200)


# node set success
def _vm_define_set_200_3():
    cmd = 'set /vm/test99.example.com/define -node headnode.dev.erigones.com'
    exp = {'status': 'SUCCESS', 'result': {'node': 'headnode.dev.erigones.com', 'hostname': 'test99.example.com',
                                           'ram': 4096, 'ostype': 1, 'alias': 'test', 'vcpus': 2, 'template': None,
                                           'owner': 'test'}}
    _test(cmd, exp, 200)


# hostname/alias set success
def _vm_define_set_200_4():
    cmd = 'set /vm/test99.example.com/define -hostname test77.example.com -alias test77'
    exp = {'status': 'SUCCESS', 'result': {'node': 'headnode.dev.erigones.com', 'hostname': 'test77.example.com',
                                           'ram': 4096, 'ostype': 1, 'alias': 'test77', 'vcpus': 2, 'template': None,
                                           'owner': 'test'}}

    _test(cmd, exp, 200)


# node change failed
def _vm_define_set_400_2():
    cmd = 'set /vm/test99.example.com/define -node node02.example.com'
    exp = {'status': 'FAILURE', 'result': {'node': ['Object with hostname=node02.example.com does not exist.']}}
    _test(cmd, exp, 400, 1)


# hostname duplicate
def _vm_define_create_406():
    cmd = 'create /vm/test99.example.com/define -template Erigon.AG'
    exp = {'detail': 'VM already exists'}
    _test(cmd, exp, 406, 1)


# alias duplicate
def _vm_define_create_400_5():
    cmd = 'create /vm/test98.example.com/define -alias test -owner test -vcpus 1 -ram 4096 -ostype 2'
    exp = {'status': 'FAILURE',
           'result': {'alias': ['This server name is already in use. Please supply a different server name.']}}
    _test(cmd, exp, 400, 1)


# vm list
def _vm__get_200_4():
    cmd = 'get /vm'
    exp = {'status': 'SUCCESS', 'result': ['test99.example.com']}
    _test(cmd, exp, 200)


def _vm_define_get_full_200():
    cmd = 'get /vm/test99.example.com/define -full'
    exp = {'status': 'SUCCESS', 'result': {'node': '#4e344a', 'disks': [{'compression': 'lz4', 'image': None,
                                                                         'boot': True, 'zpool': 'zones',
                                                                         'model': 'virtio', 'size': 51200}],
                                           'nics': [{'ip': '10.10.91.31', 'gateway': '10.10.91.1',
                                                     'netmask': '255.255.255.0', 'dns': False, 'model': 'virtio',
                                                     'net': 'lan', 'mac': None}], 'ram': 4096, 'ostype': 1,
                                           'alias': 'test', 'vcpus': 2, 'template': None, 'owner': 'test',
                                           'hostname': 'test99.example.com'}}
    _test(cmd, exp, 200)


def _vm_status_get_200_2():
    cmd = 'get /vm/test99.example.com/status'
    exp = {'status': 'SUCCESS', 'result': {'status': 'notcreated', 'alias': 'test', 'hostname': 'test99.example.com',
                                           'status_change': None, 'tasks': {}}}
    _test(cmd, exp, 200)


def _vm__get_status_200():
    cmd = 'get /vm/status'
    exp = {'status': 'SUCCESS', 'result': [{'status': 'notcreated', 'alias': 'test', 'hostname': 'test99.example.com',
                                            'status_change': None, 'tasks': {}}]}
    _test(cmd, exp, 200)


def _vm_snapshot_get_200():
    cmd = 'get /vm/test99.example.com/snapshot'
    exp = {'status': 'SUCCESS', 'result': []}
    _test(cmd, exp, 200)


def _vm_vm_create_403():
    cmd = 'create /vm/test99.example.com'
    exp = {'detail': 'You do not have permission to perform this action.'}
    _test(cmd, exp, 403, 1)


def _vm_define_delete_200():
    cmd = 'delete /vm/test77.example.com/define'
    exp = {'status': 'SUCCESS', 'result': None}
    _test(cmd, exp, 200)


###############################################################################
# aggregates
###############################################################################

def _create_test_user(set_admin_task_prefix=False):
    _accounts_login_admin_good()
    if set_admin_task_prefix:
        _task_get_prefix(set_fun=_set_admin_task_prefix)
    _accounts_user_create_test_201()
    _accounts_logout_good()


def _delete_test_user():
    _accounts_login_admin_good()
    _accounts_user_delete_test_200()
    _accounts_logout_good()


def ping():
    """simple ping test"""
    if not _ping():
        abort('ping failed')


def accounts(summary=True):
    """run tests for accounts module"""
    ping()
    _accounts_logout_bad()
    _create_test_user()
    _accounts_login_user_good()
    _accounts_logout_good()
    _accounts_logout_bad()
    _accounts_login_bad1()
    _accounts_login_bad2()
    _accounts_login_bad3()
    _accounts_login_bad4()
    _delete_test_user()

    if summary:
        _summary()


def task(summary=True):
    """run tests for task module"""
    ping()
    _create_test_user(set_admin_task_prefix=True)
    _accounts_login_user_good()
    _task_get_prefix(set_fun=_set_user_task_prefix)
    _task__get_200()
    _task_details_get_404_1()
    _task_details_get_403_1()
    _task_done_get_201()
    _task_done_get_403()
    _task_status_get_201()
    _task_status_get_403()
    _task_cancel_set_406()
    _task_cancel_set_403()
    _task_log_last_get_200()
    _accounts_logout_good()
    _task__get_403()
    _task_status_get_logout_403()
    _task_done_get_logout_403()
    _task_log_get_logout_403()
    _task_log_0_get_logout_403()
    _delete_test_user()

    if summary:
        _summary()


def vm(summary=True):
    """run tests for vm module"""
    ping()
    _create_test_user()
    _accounts_login_user_good()
    _vm__get_200()
    _vm__get_404()
    _vm__delete_404()
    _vm__create_404()
    _vm_define_get_200()
    _vm_status_get_200()
    _vm_define_create_403()
    _vm_define_disk_1_create_403()
    _vm_define_nic_1_create_403()
    _accounts_logout_good()
    _accounts_login_admin_good()
    _vm__get_200()

    _vm_define_create_400_1()
    _vm_define_create_400_2()
    _vm_define_create_400_3()
    _vm_define_create_400_4()
    _vm_define_create_201_1()
    _vm_define_get_200_1()

    _vm_define_disk_1_create_400_1()
    _vm_define_disk_1_create_201()
    _vm_define_disk_1_delete_200()
    _vm_define_disk_1_create_201()
    _vm_define_disk_2_create_400_1()
    _vm_define_disk_2_create_400_2()
    _vm_define_disk_3_create_406()
    _vm_define_disk_2_create_201_1()
    _vm_define_disk_2_set_200()
    _vm_define_disk_2_set_400_3()

    _sleep(60)

    _vm_define_nic_1_create_400_1()
    _vm_define_nic_1_create_400_2()
    _vm_define_nic_1_create_201()
    _vm_define_nic_2_delete_200_0()
    _vm_define_nic_1_create_201()
    _vm_define_nic_2_create_400_3()
    _vm_define_nic_3_create_406()
    _vm_define_nic_1_get_200()
    _vm_define_nic_1_set_200_1()
    _vm_define_nic_1_set_200_2()
    _vm_define_nic_2_create_400()
    _vm_define_nic_2_create_201()
    _vm_define_nic_2_delete_200()

    _vm_define_set_200_1()
    _vm_define_set_400_1()
    _vm_define_disk_2_delete_200()
    _vm_define_set_200_2()

    _vm_define_set_200_3()
    _vm_define_set_400_2()
    _vm_define_create_406()
    _vm_define_create_400_5()
    _accounts_logout_good()
    _accounts_login_user_good()
    _vm__get_200_4()
    _vm_define_get_full_200()
    _vm_status_get_200_2()
    _vm__get_status_200()
    _vm_snapshot_get_200()
    _vm_vm_create_403()
    _accounts_logout_good()
    _accounts_login_admin_good()
    _accounts_delete_test_vm_relation_400()
    _vm_define_set_200_4()
    _vm_define_delete_200()
    _delete_test_user()
    _vm__get_403()

    if summary:
        _summary()


# noinspection PyShadowingBuiltins
def all(summary=True):
    """run all tests"""
    accounts(False)
    task(False)
    vm(False)

    if summary:
        _summary()


###############################################################################
# main
###############################################################################

if __name__ == '__main__':
    if len(sys.argv) == 1:
        sys.argv.append('-l')
    sys.argv.insert(1, '-f')
    sys.argv.insert(2, SELF)
    _fabmain()
