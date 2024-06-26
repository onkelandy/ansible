#!/usr/local/bin/python3
# -*- coding: utf-8 -*-

# Copyright © 2008-2010, David Paleino <d.paleino@gmail.com>
#           © 2001-2008, Tommi Virtanen <tv@debian.org>
#           © 1998-2000, Lars Wirzenius <liw@iki.fi>
#
#      This program is free software; you can redistribute it and/or modify
#      it under the terms of the GNU General Public License as published by
#      the Free Software Foundation; either version 3 of the License, or
#      (at your option) any later version.
#
#      This program is distributed in the hope that it will be useful,
#      but WITHOUT ANY WARRANTY; without even the implied warranty of
#      MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#      GNU General Public License for more details.
#
#      You should have received a copy of the GNU General Public License
#      along with this program; if not, write to the Free Software
#      Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#      MA 02110-1301, USA.

"""Summarize the contents of a syslog log file.

The syslog(3) service writes system log messages in a certain format:

Jan 17 19:21:50 zeus kernel: klogd 1.3-3, log source = /proc/kmsg started.

This program summarizes the contents of such a file, by displaying each
unique (except for the time) line once, and also the number of times such
a line occurs in the input. The lines are displayed in the order they occur
in the input.

Lars Wirzenius <liw@iki.fi>
Tommi Virtanen <tv@debian.org>
David Paleino <d.paleino@gmail.com>"""

import sys, re, getopt
from gzip import open as gzopen
from hashlib import sha1
import io
from optparse import OptionParser

version = "1.14"

datepats = [
    re.compile(r"^(Jan|Jän|Feb|Mär|Mar|Apr|May|Mai|Jun|Jul|Aug|Sep|Oct|Okt|Nov|Dec|Dez) [ 0-9][0-9] [ 0-9][0-9]:[0-9][0-9]:[0-9][0-9] "),
    re.compile(r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun) (Jan|Jän|Feb|Mär|Mar|Apr|May|Mai|Jun|Jul|Aug|Sep|Oct|Okt|Nov|Dec|Dez) [ 0-9][0-9][0-9][0-9]:[0-9][0-9] "),
    re.compile(r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun) (Jan|Jän|Feb|Mär|Mar|Apr|May|Mai|Jun|Jul|Aug|Sep|Oct|Okt|Nov|Dec|Dez) [ 0-9][0-9][0-9][0-9]:[0-9][0-9]:[0-9][0-9] "),
]
pidpat = re.compile(r"^([^ ]* [^ ]*)\[[0-9][0-9]*\]: ")
repeatpat = re.compile(r"^[^ ]* last message repeated (\d+) times$")

ignore_pats = []


def io_error(err, filename, die=True):
    """Prints a nice error message, i.e. Tracebacks are ugly to end users"""
    import os, errno, traceback
    num = err.errno
    # DEBUG && die ensures that if it's a non-fatal exception, we don't
    # show all the traceback mess...
    if DEBUG:
        if die:
            traceback.print_exc(file=sys.stderr)
        else:
            print("[E] {} [{}({}) - {}]".format(os.strerror(num), errno.errorcode[num], num, filename))
    if die:
        sys.exit(1)


def read_patterns(filename):
    """Reads patterns to ignore from file specified by -i | --ignore="""
    pats = []
    try:
        f = io.open(filename, "r", encoding='utf-8')
    except IOError as e:
        io_error(e, filename, False)
        return []
    for line in f:
        rule = line.strip()
        if rule[0:1] == "#":
            continue
        else:
            pats.append(re.compile(rule))
    f.close()
    return pats


def read_states(filename):
    """Reads the previous state saved into the argument of -s | --state="""
    states = {}
    if not filename:
        return states
    try:
        f = io.open(filename, "r", encoding='utf-8')
    except IOError as e:
        io_error(e, filename, False)
        return states
    for line in f:
        fields = line.split()
        states[fields[0]] = (int(fields[1]), fields[2])
    f.close()
    return states


def save_states(filename, states):
    if not filename:
        return
    try:
        f = io.open(filename, "w")
    except IOError as e:
        io_error(e, filename, True)
    for filename in states.keys():
        value = states[filename]
        f.write("{} {} {}\n".format(filename, value[0], value[1]))
    f.close()


def should_be_ignored(line):
    for pat in ignore_pats:
        if pat.search(line):
            return 1
    return 0


def split_date(line):
    for pat in datepats:
        m = pat.match(line)
        if m:
            return line[:m.end()], line[m.end():]
    print("line has bad date: <{}>".format(line.rstrip()))
    return None, line


def is_gzipped(filename):
    """Returns True if the filename is a gzipped compressed file"""
    try:
        import magic
        ms = magic.open(magic.MAGIC_NONE)
        ms.load()
        if re.search("^gzip compressed data.*", ms.file(filename)):
            return True
        else:
            return False
    except Exception as e:
        print("Problem: {}".format(e))
        from os.path import splitext

        if not QUIET:
            print("Using fallback detection... please install python-magic for better gzip detection.")

        if splitext(filename)[1] == ".gz":
            return True
        else:
            return False


def summarize(filename, states):
    counts = {}
    dates = {}
    order = []
    ignored_count = 0
    if not QUIET:
        print("Summarizing {}".format(filename))

    # If the file is a gzipped log, open it
    # using the proper function from the gzip
    # module.
    try:
        if is_gzipped(filename):
            file = gzopen(filename, "rb")
        else:
            file = io.open(filename, "r", encoding='utf-8')
    except IOError as e:
        io_error(e, filename, True)

    linecount = 0

    shaobj = sha1()
    if filename in states:
        oldlines, oldsha = states[filename]
        for i in range(oldlines):
            line = file.readline()
            shaobj.update(line.encode('utf-8'))
#        print "OLD-new: %s" % shaobj.hexdigest()
#        print "OLD-file: %s" % oldsha
        if shaobj.hexdigest() != oldsha:
            file.seek(0)
            shaobj = sha1()
        else:
            linecount = oldlines
    if not QUIET:
        print("{:8} Lines skipped (already processed)".format(linecount))

    line = file.readline()
    previous = None
#    print "BEFORE-while: %s" % shaobj.hexdigest()
    while line:
        shaobj.update(line.encode('utf-8'))
        linecount += 1

        if should_be_ignored(line):
            ignored_count += 1
            if DEBUG:
                print("Ignoring: {}".format(line))
            line = file.readline()

        date, rest = split_date(line)
        if date:
            found = pidpat.search(rest)
            if found:
                rest = found.group(1) + ": " + rest[found.end():]

        count = 1
        repeated = None
        if REPEAT:
            repeated = repeatpat.search(rest)
        if repeated and previous:
            count = int(repeated.group(1))
            rest = previous

        if rest in counts:
            counts[rest] = counts[rest] + count
        else:
            assert count == 1
            counts[rest] = count
            order.append(rest)
        dates[rest] = date
        if not repeated:
            previous = rest
        line = file.readline()
    file.close()

    states[filename] = (linecount + ignored_count, shaobj.hexdigest())

    if QUIET and order:
        print("Summarizing {}".format(filename))
    if not QUIET or order:
        print("{:8} Patterns to ignore".format(len(ignore_pats)))
        print("{:8} Ignored lines".format(ignored_count))
    for rest in order:
        print("{:8} {} {}".format(counts[rest], dates[rest], rest.replace("\n", "")))
    if not QUIET or order:
        print


def main():
    global ignore_pats, IGNORE_FILENAME, STATE_FILENAME, REPEAT, QUIET, DEBUG

    parser = OptionParser(usage="%prog [options] <logfile> [<logfile> ...]",
                          version="%%prog %s" % version,
                          description="Summarize the contents of a syslog log file")
    parser.add_option("-i", "--ignore", dest="ignorefile", default="/etc/syslog-summary/ignore.rules",
                      help="read regular expressions from <file>, and ignore lines in the <logfile> that match them",
                      metavar="<file>")
    parser.add_option("-s", "--state", dest="statefile",
                      help="read state information from <file> (see the man page)",
                      metavar="<file>")
    parser.add_option("-r", "--repeat", action="store_true", dest="repeat", default=False,
                      help="merge \"last message repeated x times\" with the event repeated")
    parser.add_option("-q", "--quiet", action="store_true", dest="quiet", default=False,
                      help="don't output anything, unless there were unmatched lines")
    parser.add_option("-d", "--debug", action="store_true", dest="debug", default=False,
                      help="shows additional messages in case of error")

    (options, args) = parser.parse_args()

    if len(sys.argv) == 1:
        parser.error("no logfile specified")

    IGNORE_FILENAME = options.ignorefile
    STATE_FILENAME = options.statefile
    REPEAT = options.repeat
    QUIET = options.quiet
    DEBUG = options.debug

    ignore_pats = read_patterns(IGNORE_FILENAME)
    states = read_states(STATE_FILENAME)
    for filename in args:
        summarize(filename, states)
    save_states(STATE_FILENAME, states)


if __name__ == "__main__":
    main()
