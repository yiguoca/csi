#!/usr/bin/env python
# Copyright (c) 2012,2013  Ted Roberts/Chrome Data Solutions, LP
#
# test script harness for rosetta extract

# python system imports
import os
import shutil
import platform
import stat
import sys
import time
import zipfile
from optparse import OptionParser


# chrome python extensions
sys.path.append('/opt/chrome/scripts/lib')
from chromedata import JavaApp, Mail, Message, DefaultsFile


ScriptName = os.path.basename(__file__)
HostName = platform.node()


class GmsmsOptions(OptionParser):
    # derive an OptionParser class to deal with
    # command line options for this script, and provide 'help' output
    # set some defaults, too

    def __init__(self):
        # initialize the base class
        OptionParser.__init__(self)
        # set up the command line options
        self.add_option('-e',
                        '--environment',
                        dest='ENV',
                        help='environment (defaults to QA)',
                        metavar='[QA,PROD,STG]')
        self.add_option('-p',
                        '--propfile',
                        dest='PROPFILE',
                        help='alternate properties file.  Defaults to [QA]/env/gm-sms-etl.properties')
        self.add_option('-c',
                        '--country',
                        dest='CTRY',
                        help='country (required)',
                        metavar='[US,CA]')
        self.add_option('--mailto',
                        dest='MAILTO',
                        help='email addresses to notify')
        self.add_option('--nowait',
                        action='store_false',
                        help='ignore .waiting file, just run',
                        dest='WAIT')
        self.add_option('--debug',
                        action='store_true',
                        dest='DEBUG',
                        help='debug, print java cmd and exit')
        self.add_option('--nopublish',
                        action='store_false',
                        help='do not check for publish.log in input, do not create a publish.log file in output',
                        dest='PUBLISH')
        self.add_option('--noclean',
                        action='store_false',
                        help='do not clean old files from output directory',
                        dest='CLEAN')
        self.set_defaults(ENV='QA')
        self.set_defaults(WAIT=True)
        self.set_defaults(MAILTO=None)
        self.set_defaults(DEBUG=False)
        self.set_defaults(PUBLISH=True)
        self.set_defaults(CLEAN=True)
        self.set_defaults(KEEP=14)

    def parse_args(self):
        # use the base class method to get list of arguments
        (o, a) = OptionParser.parse_args(self)
        # add our own values to the options list
        # these become constants in the main module
        # start with constants for all environments
        o.BASEPATH = os.path.join('/', 'mnt', 'chrome', 'MISC-Data', 'GMSMS')
        o.ENVPATH = os.path.join(o.BASEPATH, o.ENV, 'env')
        o.LIBPATH = os.path.join(o.BASEPATH, o.ENV, 'lib')
        o.LOGPATH = os.path.join(o.BASEPATH, o.ENV, 'logs')
        o.TEMPPATH = os.path.join(o.BASEPATH, o.ENV, 'temp')
        if (o.CTRY):
            o.INPATH = os.path.join(o.BASEPATH, o.ENV, 'IN', o.CTRY)
            o.OUTPATH = os.path.join(o.BASEPATH, o.ENV, 'OUT', o.CTRY)
        return (o, a)


def main():
    # get command line options and arguments
    (opts, args) = GmsmsOptions().parse_args()

    # check for required options
    if not (opts.CTRY):
        GmsmsOptions().print_help()
        return -1

    # control files
    INPUB = os.path.join(opts.INPATH, 'publish.log')
    RUN = os.path.join(opts.TEMPPATH, ScriptName + '-' + opts.ENV + '_' + opts.CTRY + '.running')
    WAIT = os.path.join(opts.TEMPPATH, ScriptName + '-' + opts.ENV + '_' + opts.CTRY + '.waiting')

    # if the running file exists ...
    if (os.path.exists(RUN)):
        # get the age of the running file, converted into hours
        runage = int(time.time() - os.stat(RUN).st_mtime) / (60 * 60)
        # if the running file is older than 12 hours
        if (runage > 12):
            # why is the running file still there?
            # check the LOG from the running file
            r = open(RUN, 'r')
            rlines = r.readlines()
            r.close()
            LOG = str(None)
            for line in rlines:
                if line.startswith('LOG'):
                    LOG = line.split('~~')[1]
                    break
            # if there is a running file but no log, job is dead, delete running file
            if not os.path.exists(LOG):
                os.remove(RUN)
                return
            # there is a log, but is it active?
            else:
                logage = int(time.time() - os.stat(LOG).st_mtime) / (60 * 60)
                # if the log older than an hour, job is dead, delete running file
                if (logage > 1):
                    os.remove(RUN)
                    return
        else:
            # get the information from the running file and send an alert
            r = open(RUN, 'r')
            a = Mail()
            a.From(ScriptName + '@' + HostName)
            a.To('ted.roberts@chromedata.com')
            a.Priority('High')
            a.Subj(opts.ENV + ' running ' + str(runage) + ' hours')
            a.Body = os.linesep.join([RUN, r.read()])
            a.Send()
            r.close()
        # otherwise just exit silently
        return

    # if the waiting file exists, exit silently
    if (os.path.exists(WAIT) and opts.WAIT):
        return

    # is there new data in the input folder?
    if (opts.PUBLISH and not os.path.exists(INPUB)):
        return

    # we are confident we should run

    # start preparing the application
    app = JavaApp()
    app.Jar(os.path.join(opts.LIBPATH, 'gm-sms-etl.jar'))
    app.SetArg('-Propfile')
    if (opts.PROPFILE):
        app.SetArg(opts.PROPFILE)
        props = DefaultsFile(opts.PROPFILE)
    else:
        _prop_file_name = 'gm-sms-etl_' + opts.CTRY + '.properties'
        app.SetArg(os.path.join(opts.ENVPATH, _prop_file_name))
        props = DefaultsFile(os.path.join(opts.ENVPATH, _prop_file_name))
    startTime = time.localtime()
    app.OutputLog(os.path.join(opts.LOGPATH, time.strftime('%Y%m%d%H%M%S', startTime) + '.etl'))
    app.ErrorLog(app.OutputLog())

    if (opts.DEBUG):
        app.debug()
        return
    else:
        # set up the running file to block other attempts to run
        r = open(RUN, 'w')
        r.write(os.linesep.join([time.strftime('%c', startTime), HostName, __file__, str(opts), str(args)]))
        # lines for Kevan's lock alert check script
        r.write('Script~~' + ScriptName + os.linesep)
        r.write('Hostname~~' + HostName + os.linesep)
        r.write('Started~~' + time.strftime('%c', startTime) + os.linesep)
        r.write('Epoch~~' + str(int(time.time())) + os.linesep)
        r.write('PID~~' + str(os.getpid()) + os.linesep)
        r.write('LOG~~' + str(app.OutputLog()) + os.linesep)
        r.close()
        returncode = app.Run()
        endTime = time.localtime()

    # tag the output file with datestamp
    # this code has to work around a "bug" in the java app
    # where the .cvs in props is actually .zip in filename
    (pp, ff) = os.path.split(props['out.file'])
    (fn, fx) = os.path.splitext(ff)
    tag = time.strftime('%Y%m%d')
    newname = '_'.join([fn, tag])
    oldfilepath = os.path.join(pp, fn + '.zip')
    newfilepath = os.path.join(pp, newname + '.zip')
    try:
        os.rename(oldfilepath, newfilepath)
    except:
        newfilepath = 'File not created !!'

    # only keep the last opts.KEEP files
    dellog=[]
    if (returncode == 0 and opts.CLEAN):
        fstats = {}
        # get contents of the output directory
        for root, dirs, files in os.walk(pp):
            for file in files:
                fname = os.path.join(root, file)
                fstats[fname] = os.stat(fname).st_mtime
        # sort the files by date
        sortedFiles = sorted(fstats.items(), key=lambda x:x[1])
        delete = len(sortedFiles) - opts.KEEP
        for f in range(0, delete):
            try:
                os.remove(sortedFiles[f][0])
            except:
                dellog.append("Failed to delete " + str(sortedFiles[f][0]))
            else:
                dellog.append("Deleted " + str(sortedFiles[f][0]))

    # create publish.log to trigger Kevan's scripts only if we succeeded
    # don't forget to update /mnt/chrome/CMS/bin/Posters2.xml
    if (returncode == 0 and opts.PUBLISH):
        pfile = os.path.join(pp, 'publish.log')
        p = open(pfile, 'w')
        p.write(os.linesep.join([HostName, time.strftime('%c', endTime)]))
        p.close()
        os.chmod(pfile, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH)

    # prepare the message for console and email
    mlines = []
    mlines.append('Started     : ' + time.strftime('%c', startTime))
    mlines.append('Host        : ' + HostName)
    mlines.append('Version     : ' + app.Version())
    mlines.append('Environment : ' + str(opts.ENV))
    mlines.append('File        : ' + newfilepath)
    mlines.append('Finished    : ' + time.strftime('%c', endTime))

    # only submit prod results to the console
    if opts.ENV == 'PROD':
        msg = Message()
        if returncode != 0:
            msg.Priority('Error')
        msg.Subject('GM SMS ETL')
        msg.Body(os.linesep.join(mlines))
        msg.Send()

    # set up email and send it away
    m = Mail()
    m.From(ScriptName + '@' + HostName)
    m.To('ted.roberts@chromedata.com')
    if (opts.MAILTO):
        if (',' in opts.MAILTO):
            for e in opts.MAILTO.split(','):
                m.To(e.strip())
        else:
            m.To(opts.MAILTO.strip())
    subj = ' '.join(['GM', 'SMS', 'Extract', opts.ENV, opts.CTRY])
    if returncode != 0:
        m.Priority('High')
        m.Subj(' '.join(['ERROR:', subj]))
    else:
        m.Subj(subj)
    mlines.append('\nSee attached logs for details.')
    mlines.append('\n\nOutput cleanup:')
    for i in dellog:
        mlines.append('\n' + str(i))
    m.Body = os.linesep.join(mlines)
    # zip the output log before attaching it to the email
    zipname = os.path.join(opts.TEMPPATH, ScriptName + '-' + opts.ENV + '.zip')
    zf = zipfile.ZipFile(zipname, 'w', zipfile.ZIP_DEFLATED)
    zf.write(app.OutputLog(), 'gmsms-output.txt')
    zf.close()
    m.Attach(zipname, 'gmsms-output.zip')
    m.Send()

    # clean up
    if os.path.exists(INPUB):
        os.remove(INPUB)
    os.remove(app.OutputLog())
    os.remove(zipname)
    os.remove(RUN)

    # restore the waiting file with open permissions
    if (opts.WAIT):
        w = open(WAIT, 'w')
        w.write(os.linesep.join([HostName, time.strftime('%c', endTime)]))
        w.close()
        os.chmod(WAIT, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH)

    return


if __name__ == '__main__':
    main()
