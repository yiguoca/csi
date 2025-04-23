#!/usr/bin/env python
# Copyright (c) 2016  Ted Roberts/AutodataCorp
#
# generate GM IOM data
#

# python system imports
import os
import platform
import shutil
import stat
import sys
import tempfile
import time
import zipfile
from optparse import OptionParser

# chrome python extensions
sys.path.append('/opt/chrome/scripts/lib')
from chromedata import JavaApp, Mail, GetProductVersion, Message, DefaultsFile

# establish what we are running and where
ScriptName = os.path.basename(__file__)
HostName = platform.node()


class IOMScriptOptions(OptionParser):
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
                        metavar='[QA,PROD,PreProd]')
        self.add_option('--country',
                        dest='COUNTRY',
                        help='country code (required)',
                        metavar='[US,CA]')
        self.add_option('--years',
                        dest='YEARS',
                        help='years to process')
        self.add_option('--version',
                        dest='VERSION',
                        help='version to run (eg, v14)')
        self.add_option('--mailto',
                        dest='MAILTO',
                        help='email addresses to notify')
        self.add_option('--debug',
                        action='store_true',
                        dest='DEBUG',
                        help='prints command and exits')
        self.add_option('--nowait',
                        dest='WAIT',
                        action='store_false',
                        help='ignore .waiting file, just run')
        self.add_option('--nopublish',
                        dest='PUB',
                        action='store_false',
                        help='do not check for publish.log file, just run')
        self.add_option('--noupdate',
                        dest='REFRESHINPUTS',
                        action='store_false',
                        help='do not update input files from PROD sources before running')
        self.set_defaults(ENV='QA')
        self.set_defaults(DEBUG=False)
        self.set_defaults(COUNTRY=None)
        self.set_defaults(MAILTO=None)
        self.set_defaults(WAIT=True)
        self.set_defaults(PUB=True)
        self.set_defaults(REFRESHINPUTS=True)

    def parse_args(self):
        # use the base class method to get list of arguments
        (o, a) = OptionParser.parse_args(self)
        # add our own values to the options list
        # these become constants in the main module
        o.BASEPATH = os.path.join(
            '/', 'mnt', 'chrome', 'MISC-Data', 'GM-IOM-MVD', o.ENV)
        o.LOGPATH = os.path.join(o.BASEPATH, 'logs')
        o.TEMPPATH = os.path.join(o.BASEPATH, 'temp')
        # return the modified options list and arguments
        return (o, a)


class GMIOMMVD(JavaApp):
    # derive an application class from the generic
    # Chrome Java Application class

    def __init__(self, opts):
        # initiallize the class with script arguments and source file
        JavaApp.__init__(self)
        self.Jar(
            os.path.join(opts.BASEPATH, opts.VERSION, 'gm-iom-mvd-etl.jar'))
        self.Option('-XX:+UseConcMarkSweepGC')
        self.Option('-XX:+CMSClassUnloadingEnabled')
        self.Option('-XX:PermSize=256M')
        self.Option('-XX:MaxPermSize=4g')
        self.Option('-Xms256m')
        self.Option('-Xmx2g')
        self.SetArg(''.join(['app-context-', opts.COUNTRY, '.xml']).lower())
        self.SetArg('IOM_MVD_Export')
        if 'PROD' in opts.ENV:
            self.SetArg('='.join(['years', opts.YEARS]))


def refresh_inputs(s):
    shutil.copy(os.path.join('/', 'mnt', 'chrome', 'CMS', 'datavarprod', 'nvd211_' + s['config.country'] + '_EN', s['config.chromeInputFile']), s['config.inDir'])
    shutil.copy(os.path.join('/', 'mnt', 'chrome', 'ftp', 'GM', 'BYOassets', 'Data-pgm_veh_config-brand.csv'), s['config.gmDataFile'])
    shutil.copy(os.path.join('/', 'mnt', 'chrome', 'ftp', 'GM_IOM', 'model_name_override.txt'), s['config.modelPassThroughFilename'])
    shutil.copy(os.path.join('/', 'mnt', 'chrome', 'MISC-Data', 'BYO-PROD', 'Images', 'IOM', 'PVC Body style sheet.csv'), s['config.pvcFile'])


def promote_outputs(env):
    pass


def main():
    # get command line options and arguments
    (opts, args) = IOMScriptOptions().parse_args()

    # check to make sure we have sane options
    if not (opts.COUNTRY and opts.VERSION and opts.YEARS):
        IOMScriptOptions().print_help()
        return
    if opts.DEBUG:
        print opts
        GMIOMMVD(opts).debug()
        return

    # can we read the settings.properties for this run?
    settings = DefaultsFile(os.path.join(opts.BASEPATH, opts.VERSION, 'settings_' + opts.COUNTRY + '.properties'))
    if not settings:
        raise()
        return

    # check for publish.log in input folder
    PUB = os.path.join(os.path.join(settings['config.inDir'], 'publish.log'))
    if (opts.PUB and os.path.exists(PUB)):
        return

    # if the running file exists ...
    RUN = os.path.join(opts.TEMPPATH, '-'.join([ScriptName, HostName, opts.ENV]) + '.running')
    if (os.path.exists(RUN)):
        # get the age of the file, converted into hours
        age = int(time.time() - os.stat(RUN).st_mtime) / (60 * 60)
        # if the running file is older than 24 hours
        if (age > 24):
            # get the information from the running file and send an alert
            r = open(RUN, 'r')
            a = Mail()
            a.From(ScriptName + '@' + HostName)
            a.To('ted.roberts@chromedata.com')
            a.Priority('High')
            a.Subj(ScriptName + ' running long')
            a.Body = '\n'.join([RUN,
                                r.read()
                                ])
            a.Send()
            r.close()
        # otherwise just exit silently
        return

    # if the waiting file exists, exit silently
    WAIT = os.path.join(opts.TEMPPATH, 'IOM-' + opts.ENV + '-' + opts.COUNTRY + '.waiting')
    if (os.path.exists(WAIT) and opts.WAIT):
        return

    # can we get a real java app object with the options passed to the script?
    iom = GMIOMMVD(opts)
    if not iom:
        if opts.DEBUG:
            print 'could not create iom'
            print opts
        return

    # do we want to refresh the input files or just run with what we already have?
    if opts.REFRESHINPUTS:
        # the paths are in the settings we extracted from the properties file
        refresh_inputs(settings)

    # we are now confident that we should run
    # echo the process, host, time into the running file
    r = open(RUN, 'w')
    r.write('\n'.join([time.strftime('%c'), HostName, ScriptName, str(opts), str(args)]))
    r.close()

    # time the actual run
    startTime = time.localtime()
    iom.OutputLog(os.path.join(opts.LOGPATH, time.strftime('%Y%m%d%H%M%S', startTime) + '.out'))
    iom.ErrorLog(iom.OutputLog())
    returncode = iom.Run()
    endTime = time.localtime()

    # use an array to collect some stats for the email body
    # so we can embed some logic into the text
    mlines = []
    mlines.append('Started     : ' + time.strftime('%c', startTime))
    mlines.append('Host        : ' + HostName)
    mlines.append('Environment : ' + opts.ENV)
    mlines.append('Version     : ' + iom.Version())
    mlines.append('Finished    : ' + time.strftime('%c', endTime))
    mlines.append('Status      : ' + str(returncode))

    # only submit prod results
    if 'PROD' in opts.ENV:
        msg = Message()
        if returncode != 0:
            msg.Priority('Error')
        s = 'GM-IOM-MVD'
        msg.Subject(s)
        msg.Body('\n'.join(mlines))
        msg.Send()

    # set up email and send it away
    m = Mail()
    m.From(ScriptName + '@' + HostName)
    m.To('ted.roberts@chromedata.com')
    if (opts.MAILTO):
        if (',' in opts.MAILTO):
            for recipient in opts.MAILTO.split(','):
                try:
                    m.To(recipient.strip())
                except:
                    # skip bad addresses
                    pass
        else:
            m.To(opts.MAILTO.strip())
    # get some meaningful information into the email subject
    subj = ' '.join(['GM IOM MVD', opts.ENV, opts.VERSION, opts.COUNTRY])
    if returncode != 0:
        m.Priority('High')
        m.Subj(' '.join(['ERROR:', subj]))
    else:
        m.Subj(subj)
    # convert the mlines array into text for email
    m.Body = '\n'.join(mlines)
    # zip the logs and attach them to email
    (zf, zn) = tempfile.mkstemp()
    z = zipfile.ZipFile(zn, 'w', zipfile.ZIP_DEFLATED)
    z.write(iom.OutputLog(), 'gm-iom-mvd-output.txt')
    z.close()
    m.Attach(zn, 'gm-iom-mvd-results.zip')
    m.Send()

    # delete the logs and running file
    os.remove(zn)
    os.remove(iom.OutputLog())
    os.remove(RUN)

    # delete the publish trigger
    if opts.PUB:
        os.remove(PUB)

    # restore the waiting file with open permissions
    if (opts.WAIT):
        w = open(WAIT, 'w')
        w.write('\n'.join([HostName, time.strftime('%c', endTime)]))
        w.close()
        os.chmod(WAIT, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP |
                 stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH)

    return


if __name__ == '__main__':
    main()
