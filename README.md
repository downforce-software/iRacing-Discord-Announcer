# iRacing Discord Announcer Bot

A Discord bot that announces your iRacing sessions.

Built using:

* Python 3.7+
* https://github.com/Rapptz/discord.py
* https://github.com/kutu/pyirsdk

## Getting started

1. Install Python 3.8 on your PC: https://www.python.org/downloads/release/python-382/
2. Install PIP and virtualenv: https://programwithus.com/learn-to-code/Pip-and-virtualenv-on-Windows/
3. Download the latest release: https://github.com/Fuzzwah/iRacing-Discord-Announcer
4. Unzip the files into a `iRacing-Discord-Announcer` folder
5. Open a console window; Start -> run -> cmd
6. Change into the folder where you extracted the zip: `cd <path to folder>`
7. Create a new virtual environment: `virtualenv env`
8. Fire up the virtual env: `env\Scripts\activate.bat`
9. Install the required python libs: `pip install -r requirements.txt`
10. Create a new discord bot account: https://discordpy.readthedocs.io/en/latest/discord.html#creating-a-bot-account - copy the Token, you'll need this for the command line
11. Find your Discord User ID: https://support.discord.com/hc/en-us/articles/206346498-Where-can-I-find-my-User-Server-Message-ID-
12. Run the bot: `python ir-announcer-bot.py --token [TOKEN FROM STEP 10] --owner [YOUR DISCORD USER ID] --channel [CHAN THE BOT WILL ANNOUNCE IN]`
13. Invite your bot to your server: https://discordpy.readthedocs.io/en/latest/discord.html#inviting-your-bot
14. The bot will announce:
- when it detects that iRacing is running
- when you enter a session
- when the session type changes (ie: practice, qual, race)
- where you qualify
- where you finish in the race
