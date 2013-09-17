# Authors:
#   Petr Viktorin <pviktori@redhat.com>
#
# Copyright (C) 2013  Red Hat
# see file 'COPYING' for use and warranty information
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Objects for communicating with remote hosts"""

import os
import socket
import threading
import subprocess
from contextlib import contextmanager
import errno

from ipapython.ipa_log_manager import log_mgr

try:
    import paramiko
    have_paramiko = True
except ImportError:
    have_paramiko = False


class Transport(object):
    """Mechanism for communicating with remote hosts

    The Transport can manipulate files on a remote host, and open a Command.

    The base class defines an interface that specific subclasses implement.
    """
    def __init__(self, host):
        self.host = host
        self.logger_name = '%s.%s' % (host.logger_name, type(self).__name__)
        self.log = log_mgr.get_logger(self.logger_name)
        self._command_index = 0

    def get_file_contents(self, filename):
        """Read the named remote file and return the contents as a string"""
        raise NotImplementedError('Transport.get_file_contents')

    def put_file_contents(self, filename, contents):
        """Write the given string to the named remote file"""
        raise NotImplementedError('Transport.put_file_contents')

    def file_exists(self, filename):
        """Return true if the named remote file exists"""
        raise NotImplementedError('Transport.file_exists')

    def mkdir(self, path):
        """Make the named directory"""
        raise NotImplementedError('Transport.mkdir')

    def start_shell(self, argv, log_stdout=True):
        """Start a Shell

        :param argv: The command this shell is intended to run (used for
                     logging only)
        :param log_stdout: If false, the stdout will not be logged (useful when
                           binary output is expected)

        Given a `shell` from this method, the caller can then use
        ``shell.stdin.write()`` to input any command(s), call ``shell.wait()``
        to let the command run, and then inspect ``returncode``,
        ``stdout_text`` or ``stderr_text``.
        """
        raise NotImplementedError('Transport.start_shell')

    def mkdir_recursive(self, path):
        """`mkdir -p` on the remote host"""
        if not path or path == '/':
            raise ValueError('Invalid path')
        if not self.file_exists(path or '/'):
            self.mkdir_recursive(os.path.dirname(path))
            self.mkdir(path)

    def get_file(self, remotepath, localpath):
        """Copy a file from the remote host to a local file"""
        contents = self.get_file_contents(remotepath)
        with open(localpath, 'wb') as local_file:
            local_file.write(contents)

    def put_file(self, localpath, remotepath):
        """Copy a local file to the remote host"""
        with open(localpath, 'rb') as local_file:
            contents = local_file.read()
        self.put_file_contents(remotepath, contents)

    def get_next_command_logger_name(self):
        self._command_index += 1
        return '%s.cmd%s' % (self.host.logger_name, self._command_index)


class Command(object):
    """A Popen-style object representing a remote command

    Instances of this class should only be created via method of a concrete
    Transport, such as start_shell.

    The standard error and output are handled by this class. They're not
    available for file-like reading, and are logged by default.
    To make sure reading doesn't stall after one buffer fills up, they are read
    in parallel using threads.

    After calling wait(), ``stdout_text`` and ``stderr_text`` attributes will
    be strings containing the output, and ``returncode`` will contain the
    exit code.
    """
    def __init__(self, argv, logger_name=None, log_stdout=True):
        self.returncode = None
        self.argv = argv
        self._done = False

        if logger_name:
            self.logger_name = logger_name
        else:
            self.logger_name = '%s.%s' % (self.__module__, type(self).__name__)
        self.log = log_mgr.get_logger(self.logger_name)

    def wait(self, raiseonerr=True):
        """Wait for the remote process to exit

        Raises an excption if the exit code is not 0, unless raiseonerr is
        true.
        """
        if self._done:
            return self.returncode

        self._end_process()

        self._done = True

        if raiseonerr and self.returncode:
            self.log.error('Exit code: %s', self.returncode)
            raise subprocess.CalledProcessError(self.returncode, self.argv)
        else:
            self.log.debug('Exit code: %s', self.returncode)
        return self.returncode

    def _end_process(self):
        """Wait until the process exits and output is received, close channel

        Called from wait()
        """
        raise NotImplementedError()


class ParamikoTransport(Transport):
    """Transport that uses the Paramiko SSH2 library"""
    def __init__(self, host):
        super(ParamikoTransport, self).__init__(host)
        sock = socket.create_connection((host.external_hostname,
                                         host.ssh_port))
        self._transport = transport = paramiko.Transport(sock)
        transport.connect(hostkey=host.host_key)
        if host.root_ssh_key_filename:
            self.log.debug('Authenticating with private RSA key')
            filename = os.path.expanduser(host.root_ssh_key_filename)
            key = paramiko.RSAKey.from_private_key_file(filename)
            transport.auth_publickey(username='root', key=key)
        elif host.root_password:
            self.log.debug('Authenticating with password')
            transport.auth_password(username='root',
                                    password=host.root_password)
        else:
            self.log.critical('No SSH credentials configured')
            raise RuntimeError('No SSH credentials configured')

    @contextmanager
    def sftp_open(self, filename, mode='r'):
        """Context manager that provides a file-like object over a SFTP channel

        This provides compatibility with older Paramiko versions.
        (In Paramiko 1.10+, file objects from `sftp.open` are directly usable
        as context managers).
        """
        file = self.sftp.open(filename, mode)
        try:
            yield file
        finally:
            file.close()

    @property
    def sftp(self):
        """Paramiko SFTPClient connected to this host"""
        try:
            return self._sftp
        except AttributeError:
            transport = self._transport
            self._sftp = paramiko.SFTPClient.from_transport(transport)
            return self._sftp

    def get_file_contents(self, filename):
        """Read the named remote file and return the contents as a string"""
        self.log.debug('READ %s', filename)
        with self.sftp_open(filename) as f:
            return f.read()

    def put_file_contents(self, filename, contents):
        """Write the given string to the named remote file"""
        self.log.info('WRITE %s', filename)
        with self.sftp_open(filename, 'w') as f:
            f.write(contents)

    def file_exists(self, filename):
        """Return true if the named remote file exists"""
        self.log.debug('STAT %s', filename)
        try:
            self.sftp.stat(filename)
        except IOError, e:
            if e.errno == errno.ENOENT:
                return False
            else:
                raise
        return True

    def mkdir(self, path):
        self.log.info('MKDIR %s', path)
        self.sftp.mkdir(path)

    def start_shell(self, argv, log_stdout=True):
        logger_name = self.get_next_command_logger_name()
        ssh = self._transport.open_channel('session')
        self.log.info('RUN %s', argv)
        return SSHCommand(ssh, argv, logger_name=logger_name,
                          log_stdout=log_stdout)

    def get_file(self, remotepath, localpath):
        self.log.debug('GET %s', remotepath)
        self.sftp.get(remotepath, localpath)

    def put_file(self, localpath, remotepath):
        self.log.info('PUT %s', remotepath)
        self.sftp.put(localpath, remotepath)


class SSHCommand(Command):
    """Command implementation for ParamikoTransport and OpenSSHTranspport"""
    def __init__(self, ssh, argv, logger_name, log_stdout=True,
                 collect_output=True):
        super(SSHCommand, self).__init__(argv, logger_name,
                                         log_stdout=log_stdout)
        self._stdout_lines = []
        self._stderr_lines = []
        self.running_threads = set()

        self._ssh = ssh

        self.log.debug('RUN %s', argv)

        self._ssh.invoke_shell()
        stdin = self.stdin = self._ssh.makefile('wb')
        stdout = self._ssh.makefile('rb')
        stderr = self._ssh.makefile_stderr('rb')

        if collect_output:
            self._start_pipe_thread(self._stdout_lines, stdout, 'out',
                                    log_stdout)
            self._start_pipe_thread(self._stderr_lines, stderr, 'err', True)

    def _end_process(self, raiseonerr=True):
        self._ssh.shutdown_write()

        while self.running_threads:
            self.running_threads.pop().join()

        self.stdout_text = ''.join(self._stdout_lines)
        self.stderr_text = ''.join(self._stderr_lines)
        self.returncode = self._ssh.recv_exit_status()
        self._ssh.close()

    def _start_pipe_thread(self, result_list, stream, name, do_log=True):
        """Start a thread that copies lines from ``stream`` to ``result_list``

        If do_log is true, also logs the lines under ``name``

        The thread is added to ``self.running_threads``.
        """
        log = log_mgr.get_logger('%s.%s' % (self.logger_name, name))

        def read_stream():
            for line in stream:
                if do_log:
                    log.debug(line.rstrip('\n'))
                result_list.append(line)

        thread = threading.Thread(target=read_stream)
        self.running_threads.add(thread)
        thread.start()
        return thread