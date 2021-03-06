#
#
# You may redistribute it and/or modify it under the terms of the
# GNU General Public License, as published by the Free Software
# Foundation; either version 3 of the License, or (at your option)
# any later version.
#
# mirror is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with mirror. If not, write to:
#   The Free Software Foundation, Inc.,
#   51 Franklin Street, Fifth Floor
#   Boston, MA  02110-1301, USA.
#
#


"""Common functions for Mirror :("""

import os, sys
import re
import time
import logging
import pkg_resources
import gettext
import locale

from mirror.error import *

log = logging.getLogger(__name__)

DEFAULT_MIRRORD_LOG_DIR = '/var/log/mirrord'
DEFAULT_TASK_LOG_DIR    = '/var/log/rsync'

def get_version():
    """
    Returns the version of mirror from the python egg metadata

    :returns: the version of mirror

    """
    return pkg_resources.require("mirror")[0].version

def get_default_config_dir(filename=None):
    """
    :param filename: if None, only the config directory path is returned,
                     if provided, a path including the filename will be returned
    :type  filename: string
    :returns: a file path to the config directory and optional filename
    :rtype: string

    """

    try:
        from xdg.BaseDirectory import save_config_path
        config_path = save_config_path("mirror")
    except:
        config_path = os.path.join(os.path.expanduser("~/.config"),
                                   "mirror")
    if not filename:
        filename = ''
    return os.path.join(config_path, filename)

def setup_translations():
    translations_path = resource_filename("mirror", "i18n")
    log.info("Setting up translations from %s", translations_path)

    try:
        if hasattr(locale, "bindtextdomain"):
            locale.bindtextdomain("mirror", translations_path)
        if hasattr(locale, "textdomain"):
            locale.textdomain("mirror")
        gettext.install("mirror", translations_path, unicode=True)
    except Exception, e:
        log.error("Unable to initialize gettext/locale")
        log.exception(e)
        import __builtin__
        __builtin__.__dict__["_"] = lambda x: x

def resource_filename(module, path):
    return pkg_resources.require(
               "mirror>=%s" % get_version())[0].get_resource_filename(
                pkg_resources._manager, os.path.join(*(module.split('.')+[path]))
            )

def check_mirrord_running(pidfile):
    pid = None
    if os.path.isfile(pidfile):
        try:
            pid = int(open(pidfile).read().strip())
        except:
            pass

    def is_process_running(pid):
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        else:
            return True

    if pid and is_process_running(pid):
        raise MirrordRunningError("Another mirrord is running with pid: %d", pid)

def lock_file(pidfile):
    """
    Actually the code below is needless...

    """

    import fcntl
    try:
        fp = open(pidfile, "r+" if os.path.isfile(pidfile) else "w+")
    except IOError:
        raise MirrorError("Can't open or create %s", pidfile)

    try:
        fcntl.flock(fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except IOError:
        try:
            pid = int(fp.read().strip())
        except:
            raise MirrorError("Can't lock %s", pidfile)
        raise MirrorError("Can't lock %s, maybe another mirrord with pid %d is running",
                              pidfile, pid)

    # See document at http://man7.org/linux/man-pages/man2/fcntl.2.html
    fcntl.fcntl(fp, fcntl.F_SETFD, 1)
    fp.seek(0)
    fp.write("%d\n" % os.getpid())
    fp.truncate()
    fp.flush()

    # We need to return fp to keep a reference on it
    return fp

def find_command(command):
    """
    Find the path of `command`.

    :returns: the path of command or None if not found

    """
    paths = os.getenv("PATH").split(":")
    for path in paths:
        filepath = (path if path.endswith('/') else path + '/') + command
        if os.path.isfile(filepath):
            return filepath
    return None

def parse_timeout(timeout):
    """
    Parse timeout expression, e.g. 12h17m, 12h, 17m

    :returns: the seconds represented by timeout, or 0 if timeout is not valid

    """
    try:
        return int(timeout)
    except:
        pass
    h = timeout.find('h')
    m = timeout.find('m')
    if h > 0 or m > 0:
        try:
            return ((int(timeout[:h]) * 3600 if h > 0 else 0) 
                   + (int(timeout[h+1:m]) * 60 if m > 0 else 0))
        except:
            return 0
    else:
        return 0

CRON_TIME = re.compile(r'^\s*([^@#\s]+)\s+([^@#\s]+)\s+([^@#\s]+)' +
                       r'\s+([^@#\s]+)\s+([^@#\s]+)\s*(#\s*([^\n]*)|$)')
CRON_ITEM = re.compile(r'^(\d+)-(\d+)/(\d+)$')

def parse_cron_time(time):
    """
    Parse the cron time format, e.g. */20 * * * *

    :returns: a tuple with 7 elements,
              (minute, hour, day of month, month, day of week, comment with #,
               comment).
              Or None if `time` is not valid
    """
    extent      = (60, 24, 32, 13, 8)
    result_text = CRON_TIME.findall(time)
    if result_text:
        result_text = result_text[0]
        result  = []
        for i in xrange(5):
            value = result_text[i]
            items = CRON_ITEM.findall(value)
            if value == '*':
                result.append([d for d in xrange(i >= 2, extent[i])])
            elif value.startswith('*/'):
                every = int(value.split('/')[1])
                result.append([d for d in xrange(i >= 2, extent[i], every)])
            elif items:
                item  = items[0]
                start = int(item[0])
                end   = int(item[1])
                every = int(item[2])
                if start > extent[i]:
                    start = extent[i]
                if start < (i >= 2):
                    start = (i >= 2)
                if end   > extent[i]:
                    end   = extent[i]
                result.append([d for d in xrange(start, end, every)])
            elif value.find(',') != -1:
                result.append(
                        sorted([int(d) for d in value.split(',') if (int(d) < extent[i] and int(d) >= (i >= 2))]))
            else:
                try:
                    d = int(value)
                    if (int(value) < extent[i] and int(value) >= (i >= 2)):
                        result.append([d])
                    else:
                        result.append([])
                except:
                    result.append([])
        result += result_text[-2:]
        return result
    else:
        return None

