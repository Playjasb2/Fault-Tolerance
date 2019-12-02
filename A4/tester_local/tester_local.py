#!/usr/bin/env python3

import datetime
import itertools
import os.path
import random
import subprocess
import sys
import time
import threading
import argparse

# Set True if all processes and commands execute on the local host.
#   - This will ignore any hostnames found in the configuration files.
#   - This should probably be turned into a command-line argument.
#   - This is the local tester. It has not been tested in non-local mode.
local = True

# Set print_cmds to True (with command line argument -p) if you want to see the
# actual commands the tester is issuing. Default (set by parse_args) is False. 
print_cmds = None

test_user = subprocess.check_output(["whoami"]).decode(sys.stdout.encoding).split()[0]

# Note: You may need to change these paths to match your directory setup.

# Tester copies code from development directory into 'remote_src_path' at
# start of test, and forcibly removes it at the end.
# 1. DO NOT point remote_src_path at your development directory!
#    (see also comments for cleanup_src() function).
# 2. remote_src_path MUST match the 'remote_path' in mserver.c, used to
#    spawn a server process on another host (see get_spawn_cmd() in mserver.c).
remote_src_path = "csc469_a4/"

# This allows client source code to come from a different directory than the
# server/mserver source code. It is useful to ensure the client has not been
# modified from the starter code during marking of a group assignment.
# For student use, it is fine for the client and server source to come from the
# same location.
def client_src_path():
    return args.localpath

def tester_path():
    return args.tester_path

def tests_path():
    return args.tester_path + "tests/"

# Note: This assumes the mserver is started locally.
# Change the default ports and watch out for failures due to unavailable ports!
mserver_host = "localhost"
mserver_client_port = "27725"
mserver_server_port = "31651"

# Hard-coded filenames for server configuration, client configuration,
# and list of tests to run.
# Modify these if you are want to use different configuration or test files.
def server_config():
    return tester_path() + "srvcfg_local.txt"

def client_config():
    return tester_path() + "clicfg_local.txt"

def all_tests():
    return tester_path() + "all_tests.txt"

def all_ops():
    return tester_path() + "all_ops.txt"


def roundrobin(*iterables):
    "roundrobin('ABC', 'D', 'EF') --> A D E B F C"
    # Recipe credited to George Sakkis
    pending = len(iterables)
    nexts = itertools.cycle(iter(it).__next__ for it in iterables)
    while pending:
        try:
            for next in nexts:
                yield next()
        except StopIteration:
            pending -= 1
            nexts = itertools.cycle(itertools.islice(nexts, pending))

# Constructs a string to execute 'cmd' in directory 'remote_path'.
#   - If 'local' is True, 'user' and 'host' arguments are ignored.
#   - If 'local' is False, you should first have ssh keys set up on 'host' 
#     so the ssh command can be executed on host without entering a password.
def ssh_cmd(user, host, remote_path, cmd):
    result = (" ".join(["cd", remote_path, "&&"] + cmd) if local
        else ["ssh", "-o", "StrictHostKeyChecking=no", user + "@" + host, "cd", remote_path, "&&"] + cmd)
    if print_cmds:
        print(result)
    return result

# Constructs string to execute rsync to copy files from 'remote_path' to 'path'.
# If 'local' is True, 'user' and 'host' are ignored; rsync will execute locally.
# Optionally, provide a list of files to exclude from the copy.
def rsync_get_cmd(user, host, remote_path, path, exclude=[]):
    excluded = list(itertools.chain.from_iterable(("--exclude", x) for x in exclude))
    result = (" ".join(["rsync", "-rltPq"] + excluded + [remote_path, path]) if local
        else ["rsync", "-rltPq"] + excluded + [user + "@" + host + ":" + remote_path, path])
    if print_cmds:
        print(result)
    return result

# Constructs string to execute rsync to copy files from 'path' to 'remote_path'.
# If 'local' is True, 'user' and 'host' are ignored; rsync will execute locally.
def rsync_put_cmd(user, host, path, remote_path, exclude=[]):
    excluded = list(itertools.chain.from_iterable(("--exclude", x) for x in exclude))
    result = (" ".join(["rsync", "-rltPq"] + excluded + [path, remote_path]) if local
        else ["rsync", "-rltPq"] + excluded + [path, user + "@" + host + ":" + remote_path])
    if print_cmds:
        print(result)
    return result


# Constructs a string to send SIGKILL to all processes named 'process' belonging
# to 'user'.
def kill_cmd(user, process):
    return ["killall", "-s", "SIGKILL", "-u", user, "-q"] + [process]


# Waits for process to exit, with optional result checking and timeout.
#   - Spawns a new thread to actually wait on the process, and then uses
#     threading.join() to wait for the thread with a timeout.
#   - If the timeout expires, the process is forceably killed.
#   - If 'check' is True, Exceptions are raised upon timeout, or upon normal
#     process exit with non-zero exitcode.
def wait_process(cmd, process, check=False, timeout=None):
    thread = threading.Thread(target=lambda: process.wait())
    thread.start()
    thread.join(timeout)

    if thread.is_alive():
        process.kill()
        thread.join()
        if check:
            raise Exception("%s pid=%d timeout" % (cmd, process.pid))
        return None
    else:
        if check and (process.returncode != 0):
            raise Exception("%s pid=%d failed with %d" % (cmd, process.pid, process.returncode))
        return process.returncode


#------------------------------------------------------------------------------
# This section contains functions to read and parse configuration & test files
#------------------------------------------------------------------------------

# Returns list of hostnames extracted from server configuration file.
def read_server_config(filename):
    with open(filename) as f:
        lines = f.read().splitlines()
        count = int(lines[0])
        return [l.split()[0].split('@')[-1] for l in lines[1:(count + 1)]]

# Returns list of clients based on client configuration file.
# - Each line in client file specifies a hostname and number of client processes
#   to start on that host.
# - List construction uses the roundrobin() function to interleave clients on
#   different hosts.
# - Comment lines in client configuration file begin with '#' as first character.
def read_client_config(filename):
    with open(filename) as f:
        lines = f.read().splitlines()
        tokens = [l.split() for l in lines if l[0] != "#"]
        return list(roundrobin(*[[t[0] for i in range(int(t[1]))] for t in tokens]))

# Reads and parses a single test case.
#  - First line is the test name.
#  - Comment lines begin with '#' but cannot have comment on first line.
#  - Second non-comment line sets the 'fail_period' (how often failures occur)
#    and verbosity level.
#  - Subsequent lines define the clients that will be started concurrently
#    - Each client in the test file is specified as:
#      "ops_file_name" "count" "timeout"
#        - "ops_file_name" is the file containing list of ops for this client
#        - "count" is the number of times a new client process will run this set
#          of ops sequentially (i.e., each starts after previous one finishes)
#        - "timeout" is time limit (in secs) for the client to complete its ops
def read_test_case(filename):
    with open(filename) as f:
        lines = f.read().splitlines()
        name = lines[0]
        tokens = [l.split() for l in lines[1:] if l[0] != "#"]
        fail_period = int(tokens[0][0])
        verbose = (int(tokens[0][1]) != 0)
        client_ops = [[(t[i], int(t[i + 1]), int(t[i + 2])) for i in range(0, len(t), 3)] for t in tokens[1:]]
        return (name, fail_period, verbose, client_ops)


# Reads a file containing list of filenames, each defining a single test.
#  - Comment lines begin with '#'
def read_tests_list(filename):
    with open(filename) as f:
        lines = f.read().splitlines()
        return [l for l in lines if l[0] != '#']


# Reads a file containing a list of arguments for the opsgen2.py program,
# defining the sets of operations files to generate for use in the tests.
#  - Comment lines begin with '#'
def read_ops_list(filename):
    with open(filename) as f:
        lines = f.read().splitlines()
        return [l.split() for l in lines if l[0] != "#"]


#------------------------------------------------------------------------------
# This section contains functions to kill processes and cleanup temp files.
#------------------------------------------------------------------------------

# Kills all processes named 'name' executing on 'host' belonging to 'test_user'
def kill_procs(host, name):
    subprocess.call(ssh_cmd(test_user, host, ".", kill_cmd(test_user, name)), shell=local)

# Kills all the key-value processes (mserver, server, client) on all hosts.
def kill_all_procs(servers, clients):
    kill_procs(mserver_host, "mserver");
    for host in list(set(servers)):
        kill_procs(host, "server")
    for host in list(set(clients)):
        kill_procs(host, "client")

# Forcibly removes 'remote_src_path' on 'host'.
# USE WITH CAUTION!
# Assumes that source code was copied from development directory into
# 'remote_src_path' on 'host' at start of test.
def cleanup_src(host):
    subprocess.call(ssh_cmd(test_user, host, ".", ["rm", "-rf", remote_src_path]), shell=local)


# Cleans up source code on all hosts used in tests. This allows the
# 'remote_src_path' to be on local storage on each host (e.g., /tmp) rather
# than shared network storage. 
def cleanup_all_src(servers, clients):
    cleanup_src(mserver_host)
    if not local:
        # Servers/clients may execute on different hosts. Cleanup on all.
        for host in list(set(servers + clients)):
            cleanup_src(host)

# Full cleanup - kills all test processes and removes all extra copies of source
def cleanup(servers, clients):
    kill_all_procs(servers, clients)
    # For safety, the source code cleanup is commented out in student tester.
    #cleanup_all_src(servers, clients)


#------------------------------------------------------------------------------
# This section contains functions to set everything up on hosts for testing.
#------------------------------------------------------------------------------

# Invokes the opsgen2.py program to generate a set of files with the client
# operations to be executed by some client process in the tests.
# Raises CalledProcessError if opsgen2.py has non-zero exitcode.
def generate_ops(ops_list):
    for ops in ops_list:
        subprocess.check_call(" ".join(["./opsgen2.py"] + ops + [" > /dev/null"]), shell=True)


def make_src(path, host):
    cleanup_src(host)
    subprocess.check_call(ssh_cmd(test_user, host, ".", ["mkdir", "-p", remote_src_path]), shell=local)
    subprocess.check_call(rsync_put_cmd(test_user, host, path, remote_src_path, ["tester.py"]), shell=local)
    return subprocess.call(ssh_cmd(test_user, host, remote_src_path, ["make > make.log 2>&1"]), shell=local) == 0


def make_all_src(path, servers, clients):
    if not make_src(path, mserver_host):
        return False

    if not local:
        # Make sure executable exists on every host.
        for host in list(set(servers)):
            if not make_src(path, host):
                return False

        for host in list(set(clients)):
            if not make_src(path if local else client_src_path(), host):
                return False

    return True


def put_server_config():
    subprocess.check_call(rsync_put_cmd(test_user, mserver_host, server_config(), remote_src_path), shell=local)


def put_client_ops(host):
    subprocess.call(ssh_cmd(test_user, host, remote_src_path, ["rm", "-f", "ops_*.txt"]), shell=local)
    subprocess.check_call(rsync_put_cmd(test_user, host, tests_path(), remote_src_path), shell=local)


def put_all_client_ops(clients):
    if local:
        put_client_ops("localhost")
    else:
        for host in list(set(clients)):
            put_client_ops(host)


#------------------------------------------------------------------------------
# This section contains functions to manage log files.
#------------------------------------------------------------------------------

# Rename a server log file on 'host' to include the test number
def rename_server_log(host, id, run):
    subprocess.call(ssh_cmd(test_user, host, remote_src_path,
                    ["mv", "server_%d.log" % (id), "server_%d_%d.log" % (id, run)]), shell=local)


def rename_all_server_logs(servers, run):
    for i in range(len(servers)):
        rename_server_log(servers[i], i, run)


# Remove a server log file on 'host'
def delete_server_log(host, id):
    subprocess.call(ssh_cmd(test_user, host, remote_src_path, ["rm", "-f", "server_%d.log" % (id)]), shell=local)


def delete_all_server_logs(servers):
    for i in range(len(servers)):
        delete_server_log(servers[i], i)

# Use rsync to retrieve log files (all, or only stderr logs) from 'host'
def get_logs(host, stderr_only=False):
    if stderr_only:
        subprocess.call(rsync_get_cmd(test_user, host, remote_src_path + "*_stderr.log", "."), shell=local)
    else:
        subprocess.call(rsync_get_cmd(test_user, host, remote_src_path + "*.log", "."), shell=local)


def get_all_logs(servers, clients, stderr_only=False):
    get_logs(mserver_host, stderr_only)
    for host in list(set(servers)):
        get_logs(host, stderr_only)
    for host in list(set(clients)):
        get_logs(host, stderr_only)

#------------------------------------------------------------------------------
# This section contains functions to start/stop mserver and clients for a test.
#------------------------------------------------------------------------------

def start_mserver(run, verbose=True):
    cmd = ssh_cmd(test_user, mserver_host, remote_src_path,
                  ["./mserver", "-c", mserver_client_port, "-s", mserver_server_port,
                   "-C", os.path.basename(server_config())] +
                  (["-l", "mserver_%d.log" % (run)] if verbose else []) +
                  ["1>", ("mserver_%d_stdout.log" % (run)) if verbose else "/dev/null",
                   "2>", "mserver_%d_stderr.log" % (run)])
    return subprocess.Popen(cmd, stdin=subprocess.PIPE, shell=local)

def stop_mserver(process):
    process.stdin.close()
    return wait_process("mserver", process, timeout=30) == 0


def start_client(host, id, op_file, run, verbose=True):
    cmd = ssh_cmd(test_user, host, remote_src_path,
                  ["./client", "-h", mserver_host, "-p", mserver_client_port, "-f", op_file] +
                  (["-l", "client_%d_%d.log" % (id, run)] if verbose else []) +
                  ["1>", ("client_%d_%d_stdout.log" % (id, run)) if verbose else "/dev/null",
                   "2>", "client_%d_%d_stderr.log" % (id, run)])
    return subprocess.Popen(cmd, shell=local)

def stop_client(process, id, timeout=None):
    return wait_process("client_%d" % (id), process, timeout=timeout)

def client_thread_f(host, id, op_file, run, count, time_limit, results, verbose=True):
    for i in range(count):
        p = start_client(host, id, op_file, run, verbose)
        r = stop_client(p, id, time_limit)
        if r != 0:
            results[id] = None if r is None else False
            return
    results[id] = True

#------------------------------------------------------------------------------
# This section contains functions to force periodic server failures during test
#------------------------------------------------------------------------------

killer_timer = None

def kill_arg(user, arg_pattern):
    return ["pkill", "-SIGKILL", "-u", user, "-f", "\'%s\'" % (arg_pattern)]

def killer_thread_f(servers, period):
    global killer_timer

    sid = random.randint(0, len(servers) - 1)
    subprocess.call(ssh_cmd(test_user, servers[sid], ".", kill_arg(test_user, "server .* -S %d .*" % (sid))), shell=local)

    killer_timer = threading.Timer(period, killer_thread_f, (servers, period))
    killer_timer.start()


#------------------------------------------------------------------------------
# This section contains functions to execute a test and print the results.
#------------------------------------------------------------------------------

def print_test_result(name, output, status):
    print("%s: %s (%s)" % (name, status, output))


# Run a single test.
# Includes cleaning up any existing processes, starting a new mserver,
# setting up for periodic forced server failures, starting client threads,
# waiting for clients to finish, collecting all the results and printing the
# overall test result (success or failure). 
def run_test(servers, clients, test, run):
    global killer_timer

    kill_all_procs(servers, clients)

    name = test[0]
    fail_period = test[1]
    verbose = test[2]
    client_ops = test[3]

    mserver_process = start_mserver(run, verbose)
    time.sleep(5)
    if not (mserver_process.poll() is None):
        stop_mserver(mserver_process)
        print_test_result(
            name,
            "test %d failed, mserver failed to start, see \'*_%d.log\' files for details" % (run, run),
            "error"
        )
        return

    killer_timer = None
    if fail_period != 0:
        killer_timer = threading.Timer(1, killer_thread_f, (servers, fail_period))
        killer_timer.start()

    client_threads = []
    results = {}

    # The client config file specifies max number of client threads to start.
    # The test file may have specified more client_ops than that, but if so,
    # only the first max-clients lines are executed.
    for id in range(min(len(clients),len(client_ops))):        
        op = client_ops[id][0]
        thread = threading.Thread(target=client_thread_f,
                                  args=(clients[id], id, op[0], run,
                                        op[1], op[2], results, verbose))
        client_threads.append(thread)

    for t in client_threads:
        t.start()
    for t in client_threads:
        t.join()

    if killer_timer:
        killer_timer.cancel()
        killer_timer = None

    stop_mserver(mserver_process)

    num_successes = sum(1 for v in results.values() if v)
    num_failures = sum(1 for v in results.values() if not v)
    num_timeouts = sum(1 for v in results.values() if v is None)
    success = (num_failures == 0) and (num_timeouts == 0) and (num_successes > 0)

    print_test_result(
        name,
        "success" if success else
            ("test %d failed, total %d/%d clients failed, %d clients timed out, see \'*_%d.log\' files for details"
             % (run, num_failures, num_failures + num_successes, num_timeouts, run)),
        "pass" if success else "fail"
    )


# Run a list of tests. Performs initial cleanup of any prior tests,
# builds the source code on all hosts used for the tests, and distributes
# the server configuration file and client operations files to server and
# client hosts respectively. Next it reads the description of each test and
# executes it. Finally, logs are collected and cleanup is performed again.
def run_all_tests(path, servers, clients, tests):
    cleanup(servers, clients)
    try:
        make_success = make_all_src(path, servers, clients)
        print_test_result(
            "make",
            "success" if make_success else "make failed, see \'make.log\' for details",
            "pass" if make_success else "error"
        )
        if not make_success:
            return

        put_server_config()
        put_all_client_ops(clients)

        for i in range(len(tests)):
            test = read_test_case(tests_path() + tests[i])
            run_test(servers, clients, test, i)
            if (test[2]):
                rename_all_server_logs(servers, i)
            else:
                delete_all_server_logs(servers)

    except Exception as e:
        #...
        raise

    finally:
        get_all_logs(servers, clients)
        cleanup(servers, clients)

        
def parse_command_line_args():
    parser = argparse.ArgumentParser(description='Test key-value service.') 
    parser.add_argument('-l', '--localpath', default='./',
                        help='local path to source code to be tested (default is current directory)')
    parser.add_argument('-t', '--tester-path', default='./',
                        help='path to tester configuration files and tests subdirectory (default is current directory)')
    parser.add_argument('-g', '--generate-ops', action='store_true',
                        help='generate operation files for testing (default is false)')
    parser.add_argument('-p', '--print_cmds', action='store_true',
                        help='print actual commands issued by tester (default is false)')
    return parser.parse_args()


def main():
    global print_cmds
    
    servers = read_server_config(server_config())
    clients = read_client_config(client_config())
    tests = read_tests_list(all_tests())

    print_cmds = args.print_cmds

    if (args.generate_ops):
        ops = read_ops_list(all_ops())
        generate_ops(ops)

    # path is used with rsync, which needs trailing / to work correctly.
    if not args.localpath.endswith('/'):
        args.localpath = args.localpath + '/'
        
    run_all_tests(args.localpath, servers, clients, tests)

# Make args global
args = parse_command_line_args()

main()
