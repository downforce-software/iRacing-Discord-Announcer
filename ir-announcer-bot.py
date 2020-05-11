#!/usr/bin/env python
# -*- coding: utf-8 -*-

__program__ = "ir-announcer-bot"
__author__ = "Robert Crouch (rob.crouch@gmail.com)"
__copyright__ = "Copyright (C) 2020- Robert Crouch"
__license__ = "AGPL"
__version__ = "v0.2005011"

import os
import sys
import re
import math
import pprint
from dataclasses import dataclass
import argparse
import logging, logging.handlers
import inspect

import discord
from discord.ext import tasks
from discord.ext.commands import (
    Bot, 
    Cog, 
    command, 
    errors, 
    is_owner,
    has_permissions
)
import irsdk

DESCRIPTION = "A Discord bot that announces your iRacing sessions."

pp = pprint.PrettyPrinter(width=60, compact=True)

def ordinal(num):
    """
    Take number and return the ordinal st, nd, th.
    :num: int
    :return: str
    """
    num_str = str(num)

    SUFFIXES = {1: 'st', 2: 'nd', 3: 'rd'}
    # Check for 11-14 because those are abnormal
    if int(num_str[-2:]) > 10 and int(num_str[-2:]) < 14:
        return "{}th".format(num)
    else:
        suffix = SUFFIXES.get(int(num_str[-1:]), 'th')
    return "{}{}".format(num, suffix)

def dict_from_class(cls):
    return dict((value, key) for (key, value) in cls.__dict__.items() if key not in ['__dict__', '__doc__', '__module__', '__weakref__'])

session_states = dict_from_class(irsdk.SessionState)


@dataclass
class Driver:
    idx: int = None
    startpos: int = None
    distpct: float = None
    pos: int = None
    cpos: int = None
    num: int = None
    name: str = None
    teamname: str = None
    ir: int = None
    onpitroad: bool = None
    offtrack: bool = None
    inworld: bool = None
    carclass: str = None
    carclassid: int = None
    gap_ahead: int = None
    gap_behind: int = None


@dataclass
class Session:
    num: int = None
    type: str = None
    state_name: str = None
    state: int = None
    trackid: int = None
    tracklen: int = None


class Announcer(Cog):
    def __init__(self, bot, ir):
        self.bot = bot
        self.ir = ir
        self.check_connection.start()
        self.prevmsg = None

    async def sendmsg(self, msg):
        """A wrapper to send our messages to the channel, so we can check for dupes"""

        if msg != self.prevmsg:
            self.prevmsg = msg
            await self.bot.channel.send(msg)

    def cog_unload(self):
        self.check_connection.cancel()
        if self.auto_camera.get_task():
            self.auto_camera.cancel()

    async def check_ready(self):
        """Make sure the bot is in a good state to accept commands"""

        # make sure bot is conencted to the iRacing API
        if self.bot.ir_connected and self.ir['SessionInfo']['Sessions'][self.ir['SessionNum']]['SessionType'] not in ["Qualify", "Lone Qualify", "Race"]:
            await self.sendmsg("This command can only be used during race sessions")
            return False   
        else:
            return True   

    def update_drivers(self):
        """Builds a list of Driver objects to represent all drivers in the session"""

        # empty the list
        self.ir.drivers = []
        # empty our list of classes
        self.ir.classids = []
        # check if we've got the driver info data from the API
        if self.ir['DriverInfo']:
            # iterate over each of the drivers
            for d in self.ir['DriverInfo']['Drivers']:
                # make sure they're real human drivers in the race server
                if d['IsSpectator'] == False and d['UserID'] > 0:
                    # make a new Driver object
                    driver = Driver()
                    # fill out all the attributes we can from the API data
                    driver.idx = d['CarIdx']
                    driver.startpos = None
                    try:
                        for qr in self.ir["QualifyResultsInfo"]["Results"]:
                            if driver.idx == qr['CarIdx']:
                                driver.startpos = qr["Position"] + 1
                                break
                    except:
                        driver.startpos = None
                    driver.laps = self.ir["CarIdxLap"][driver.idx] - 1
                    driver.distpct = driver.laps + self.ir["CarIdxLapDistPct"][driver.idx]
                    driver.pos = None
                    driver.cpos = None
                    driver.num = int(d['CarNumber'])
                    driver.name = d['UserName']
                    driver.teamname = d['TeamName']
                    driver.ir = d['IRating']
                    driver.onpitroad = bool(self.ir['CarIdxOnPitRoad'][d['CarIdx']])
                    if self.ir['CarIdxTrackSurface'][d['CarIdx']] == irsdk.TrkLoc.not_in_world:
                        driver.inworld = False
                    else:
                        driver.inworld = True
                    if self.ir['CarIdxTrackSurface'][d['CarIdx']] == irsdk.TrkLoc.off_track:
                        driver.offtrack = True
                    else:
                        driver.offtrack = False                    
                    driver.carclass = d['CarClassShortName']
                    driver.carclassid = d['CarClassID']
                    self.ir.drivers.append(driver)
                    # add classid to our list if we haven't see it before
                    if d['CarClassID'] not in self.ir.classids:
                        self.ir.classids.append(d['CarClassID'])
            
            # sort the list of drivers by the distance they've covered, reversed so 1st place is 1st item in list
            self.ir.drivers.sort(key=lambda driver: (driver.distpct is not None, driver.distpct), reverse=True)
            # update the Driver objects to include the overall and class position (if required)
            class_pos = {}
            for pos, driver in enumerate(self.ir.drivers, 1):
                # make sure they're racing
                if driver.inworld:
                    # update their over all position
                    driver.pos = pos
                    # have we seen this carclass before?
                    if driver.carclassid in class_pos.keys():
                        # add this driver's distance to the list
                        class_pos[driver.carclassid].append(driver)
                    # this is the first time we've seen this class, start new position tracker
                    else:
                        class_pos[driver.carclassid] = [driver,]
                    # update their class position
                    driver.cpos = len(class_pos[driver.carclassid])

            # to get the class battle gaps, loop over the class_distances dict
            for classid, drivers in class_pos.items():
                for pos, driver in enumerate(drivers, 1):
                    # if this is the class leader, there's no one ahead
                    if pos == 1:
                        driver.gap_ahead = None
                    else:
                        driver.gap_ahead = (drivers[pos-2].distpct - driver.distpct) * self.ir.session.tracklen
                    # last place has no gap behind
                    if pos == len(drivers):
                        driver.gap_behind = None
                    else:
                        driver.gap_behind = (driver.distpct - drivers[pos].distpct) * self.ir.session.tracklen

    async def disconnect(self):
        """Does all the things required when the bot becomes disconnected from iRacing"""

        # if battles mode was on, stop it
        if self.battlemode.get_task():
            self.battlemode.stop()
        # change our connected state
        self.bot.ir_connected = False
        # shutdown the API connection
        self.ir.shutdown()
        # announce the change to the channel
        await self.sendmsg("Disconnected from iRacing client")
        return False

    @tasks.loop(seconds=1)
    async def check_connection(self):
        """Each second this loop checks if the bot is conencted to the iRacing API"""

        if self.bot.channel:
            # was connected, but now isn't... shut it all down
            if self.bot.ir_connected and not (self.ir.is_initialized and self.ir.is_connected):
                # if battles mode was on, stop it
                self.disconnect()

            # wasn't connected, but now is... initialise the base stuff we need
            elif not self.bot.ir_connected and self.ir.startup() and self.ir.is_initialized and self.ir.is_connected:
                # change our connected state
                self.bot.ir_connected = True
                # empty our session state
                self.ir.session = Session()
                # turn off the UI
                self.ir.cam_set_state(irsdk.CameraState.ui_hidden)
                # announce the change to the channel
                await self.sendmsg("Connected to iRacing client")
                return True

            # check if we're connected
            if self.bot.ir_connected:
                # freeze the API data
                self.ir.freeze_var_buffer_latest()

                # if session changed, lets update the base stuff
                if self.ir.session.num != self.ir['SessionNum'] or \
                    self.ir.session.state != self.ir['SessionState'] or \
                    self.ir.session.trackid != self.ir['WeekendInfo']['TrackID']:

                    # save out the updated data so we can compare with the bot's session object (from previous tick)
                    sess_num = self.ir['SessionNum']
                    sess_type = self.ir['SessionInfo']['Sessions'][self.ir['SessionNum']]['SessionType']
                    sess_state_name = ' '.join(w.capitalize() for w in session_states[self.ir['SessionState']].split('_'))
                    sess_state = self.ir['SessionState']
                    sess_trackid = self.ir['WeekendInfo']['TrackID']
                    sess_tracklen = float(str.split(self.ir['WeekendInfo']['TrackLength'], ' ')[0]) * 1000

                    # announce any changes
                    if self.ir.session.trackid != sess_trackid:
                        await self.sendmsg("Track: {}".format(self.ir['WeekendInfo']['TrackDisplayName']))
                        await self.sendmsg("Track Temp: {}".format(self.ir['WeekendInfo']['TrackSurfaceTemp']))
                    if self.ir.session.num != sess_num:
                        await self.sendmsg("Session Type: {}".format(sess_type))
                    if self.ir.session.state != sess_state:
                        await self.sendmsg("Session State: {}".format(sess_state_name))

                    # update our session obj with the new details
                    self.ir.session = Session(
                            num=sess_num, 
                            type=sess_type, 
                            state_name=sess_state_name, 
                            state=sess_state,
                            trackid=sess_trackid,
                            tracklen=sess_tracklen
                        )

                # update the list of Driver objects in order of position
                self.update_drivers()

                # unfreeze the API data
                self.ir.unfreeze_var_buffer_latest()
                return True

    @check_connection.before_loop
    async def before_check_connection(self):
        await self.bot.wait_until_ready()


class App(object):
    """ The main class
    """

    def __init__(self, log, args):
       
        self.log = log
        self.args = args
        self.version = "{}: {}".format(__program__, __version__)

        self.log.info(self.version)
        self.prefix = (".")

        if self.args.token:
            self.token = self.args.token
        else:
            self.token = os.environ.get('IRDCC_TOKEN')
        self.bot = Bot(
            command_prefix=self.prefix, 
            description=DESCRIPTION, 
            owner_id=self.args.owner
        )
        self.bot.args = self.args
        self.bot.channel = None

        self.setup()

    def run(self):
        logging.info("[*] Running...")
        self.bot.run(self.token)

    def setup(self):
        self.ir = irsdk.IRSDK()
        self.bot.ir_connected = False        
        self.bot.add_cog(Announcer(self.bot, self.ir))
        
        @self.bot.event
        async def on_ready():
            logging.info("[+] Connected as " + self.bot.user.name)
            logging.info("[+] Listening commands in channel #" + self.args.channel)
            self.bot.channel = discord.utils.get(self.bot.get_all_channels(), name=self.args.channel)
            await self.bot.change_presence(status=discord.Status.online)            

        @self.bot.event
        async def on_message(message):
            # Only listen on the single channel specified on the command line
            if message.channel.name == self.args.channel:
                # Ignore messages by bots (including self)
                if message.author.bot:
                    return

                if message.content.startswith(self.prefix):
                    msg = message.content.strip("".join(list(self.prefix)))
                    
                    if msg.startswith("help"):
                        return

                    # Pass on to rest of the client commands
                    await self.bot.process_commands(message)

def parse_args(argv):
    """ Read in any command line options and return them
    """

    # Define and parse command line arguments
    parser = argparse.ArgumentParser(description=__program__)
    parser.add_argument('--debug', action='store_true', default=False)
    parser.add_argument("--logfile", help="file to write log to", default="logs/%s.log" % __program__)
    parser.add_argument("--token", default=None)
    parser.add_argument("--battlegap", type=int, default=50)
    parser.add_argument("-c", "--channel", default="general")
    parser.add_argument("-o", "--owner", default=None)

    if len(sys.argv)==1:
        parser.print_help()
        sys.exit(1)

    args = parser.parse_args()

    return args

def setup_logging(args):
    """ Everything required when the application is first initialized
    """

    basepath = os.path.abspath(".")

    # set up all the logging stuff
    LOG_FILENAME = os.path.join(basepath, "%s" % args.logfile)

    LOG_LEVEL = logging.INFO    # Could be e.g. "DEBUG" or "WARNING"

    # Configure logging to log to a file, making a new file at midnight and keeping the last 3 day's data
    # Give the logger a unique name (good practice)
    log = logging.getLogger(__name__)
    # Set the log level to LOG_LEVEL
    log.setLevel(LOG_LEVEL)
    # Make a handler that writes to a file, making a new file at midnight and keeping 3 backups
    handler = logging.handlers.TimedRotatingFileHandler(LOG_FILENAME, when="midnight", backupCount=3)
    # Format each log message like this
    formatter = logging.Formatter('%(asctime)s %(levelname)-8s %(message)s')
    # Attach the formatter to the handler
    handler.setFormatter(formatter)
    # Attach the handler to the logger
    log.addHandler(handler)

def main(raw_args):
    """ Main entry point for the script.
    """

    # call function to parse command line arguments
    args = parse_args(raw_args)

    # setup logging
    setup_logging(args)

    # connect to the logger we set up
    log = logging.getLogger(__name__)

    # fire up our base class and get this app cranking!
    app = App(log, args)
    try:
        app.run()
    except KeyboardInterrupt:
        pass
    except:
        logging.exception('')        

    pass

if __name__ == '__main__':
    sys.exit(main(sys.argv))
